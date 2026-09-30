"""Explicit Linux fixture subprocess entrypoints; no production discovery."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.support.job_handlers import REGISTRY, CounterPayload, barrier

FIXTURE_VISIBILITY_SECONDS = 40
# Kombu 5.6.2 scans every tenth 10-second restore callback. Include that
# real scan period after the visibility age, plus bounded scheduling margin.
TRANSPORT_DEADLINE_SECONDS = 160


def create_fixture_app(
    broker_url, job_database_url, *, worker_id="fixture", after_execute=None
):
    from wso_core.job_runtime import create_app

    app = create_app(
        broker_url,
        job_database_url,
        registry=REGISTRY,
        worker_id=worker_id,
        after_execute=after_execute,
    )
    assert app.conf.task_time_limit == 30
    assert app.conf.task_time_limit < FIXTURE_VISIBILITY_SECONDS
    app.conf.update(
        broker_transport_options=app.conf.broker_transport_options
        | {
            "visibility_timeout": FIXTURE_VISIBILITY_SECONDS,
        },
        visibility_timeout=FIXTURE_VISIBILITY_SECONDS,
        result_backend_transport_options={
            "visibility_timeout": FIXTURE_VISIBILITY_SECONDS
        },
    )
    return app


def transport_event(event, record):
    """Observe completed real transport operations, never manufacture ACKs."""
    observation = dict(
        record,
        event=event,
        observed_at=time.time(),
        pid=os.getpid(),
        owner=os.environ["WSO_RECOVERY_OWNER"],
    )
    path = Path(os.environ["WSO_RECOVERY_CONTROL"]) / f"transport-{os.getpid()}.jsonl"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, (json.dumps(observation) + "\n").encode())
    finally:
        os.close(descriptor)


def install_transport_observer():
    """Fixture-only QoS subclass delegates every operation to installed Kombu."""
    from kombu.transport.redis import Channel, QoS

    class ObservedQoS(QoS):
        def append(self, message, delivery_tag):
            record = None
            if message.headers.get("task") == "wso.execute_job":
                reference = message.payload[1]["reference"]
                record = {
                    "job_id": str(UUID(reference["job_id"])),
                    "task_id": message.headers["id"],
                    "delivery_tag": str(delivery_tag),
                    "redelivered": bool(
                        message.headers.get("redelivered")
                        or message.delivery_info.get("redelivered")
                    ),
                }
            super().append(message, delivery_tag)
            if record is not None:
                if not hasattr(self, "_fixture_records"):
                    self._fixture_records = {}
                self._fixture_records[delivery_tag] = record
                transport_event("reserved", record)

        def ack(self, delivery_tag):
            record = getattr(self, "_fixture_records", {}).get(delivery_tag)
            super().ack(delivery_tag)
            if record is not None:
                transport_event("acked", record)
                self._fixture_records.pop(delivery_tag)

    Channel.QoS = ObservedQoS


def auth_service(signing_key=None):
    from wso_api.auth import (
        AuthService,
        AuthSettings,
        OIDCVerifier,
        PostgresSessionStore,
    )

    settings = AuthSettings(
        issuer="https://issuer.test",
        audience="wso-web",
        jwks_url="https://issuer.test/jwks",
        exchange_key="a" * 48,
        public_origin="https://app.test",
        session_database_url=os.environ["WSO_TEST_SESSION_DATABASE_URL"],
    )
    engines = {
        name: create_engine(
            os.environ[f"WSO_TEST_{name}_DATABASE_URL"], hide_parameters=True
        )
        for name in ("APP", "IDENTITY", "SESSION")
    }
    verifier = OIDCVerifier(settings, key_resolver=lambda _: signing_key.public_key())
    service = AuthService(
        settings,
        verifier,
        PostgresSessionStore(
            os.environ["WSO_TEST_SESSION_DATABASE_URL"],
            session_factory=sessionmaker(engines["SESSION"]),
        ),
        identity_factory=sessionmaker(engines["IDENTITY"]),
        tenant_factory=sessionmaker(engines["APP"]),
    )
    return service, engines


def enqueue(
    operation,
    *,
    barrier_name=None,
    queue="wso.default",
    external=False,
    unreadable=False,
):
    from wso_api.auth import WebSession
    from wso_api.stores.router import require_tenant
    from wso_contracts.models import TenantScope
    from wso_core.jobs import JobService

    from tests.support.job_handlers import ExternalPayload

    tenant = UUID(os.environ["WSO_RECOVERY_TENANT"])
    actor = UUID(os.environ["WSO_RECOVERY_ACTOR"])
    service, engines = auth_service()
    principal = WebSession(
        "https://issuer.test",
        str(actor),
        actor,
        "",
        datetime.now(UTC) + timedelta(minutes=5),
    )
    kind = (
        "RECOVERY_EXTERNAL"
        if external
        else ("RECOVERY_MEDIA" if queue == "wso.media" else "RECOVERY_COUNTER")
    )
    payload = (
        ExternalPayload(operation_id=operation, unreadable=unreadable)
        if external
        else (CounterPayload(operation_id=operation, barrier=barrier_name))
    )
    try:
        with require_tenant(
            "stores:read", tenant, service=service, principal=principal
        ) as authorized:
            job = JobService(authorized.session, registry=REGISTRY).enqueue(
                TenantScope(tenant_id=tenant),
                kind,
                payload,
                str(operation),
            )
        return job.id
    finally:
        for engine in engines.values():
            engine.dispose()


def main():
    mode = sys.argv[1]
    if mode == "park":
        barrier("media-parked", timeout=20)
        return
    if mode == "producer":
        enqueue(UUID(os.environ["WSO_RECOVERY_OPERATION"]))
        barrier("producer-committed")
        return

    from wso_core.outbox import CeleryPublisher

    app = create_fixture_app(
        os.environ["WSO_BROKER_URL"],
        os.environ["WSO_TEST_JOB_DATABASE_URL"],
        worker_id=f"fixture-{os.getpid()}",
        after_execute=(lambda *_: barrier("committed"))
        if os.environ.get("WSO_RECOVERY_BARRIER") == "committed"
        else None,
    )
    if mode == "worker":
        install_transport_observer()
        app.worker_main(
            [
                "worker",
                "--loglevel=CRITICAL",
                "--concurrency=1",
                "--pool=prefork",
                "--queues=" + os.environ["WSO_RECOVERY_QUEUE"],
                "--hostname=fixture-" + str(os.getpid()) + "@%h",
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
            ]
        )
        return

    from wso_core.dispatch import Dispatcher

    publisher = CeleryPublisher(app)

    def publish(reference, queue):
        publisher(reference, queue)
        if os.environ.get("WSO_RECOVERY_BARRIER") == "published":
            barrier("published")

    dispatcher = Dispatcher(
        os.environ["WSO_TEST_DISPATCH_DATABASE_URL"],
        publish,
        registry=REGISTRY,
        worker_id=f"fixture-dispatch-{os.getpid()}",
    )
    while True:
        dispatcher.run_once()
        time.sleep(0.1)


if __name__ == "__main__":
    main()
