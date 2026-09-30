"""Explicit Celery process entrypoints; importing this module opens no connections."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from wso_contracts.jobs import DispatchReference

from wso_core.jobs import DEFAULT_REGISTRY, JobRegistry


def _validate_broker_configuration(broker_url: str) -> None:
    try:
        if any(character.isspace() or ord(character) < 32 for character in broker_url):
            raise ValueError
        parsed = urlsplit(broker_url)
        hostname = parsed.hostname
        if parsed.scheme not in {"redis", "rediss"} or not hostname:
            raise ValueError
        if parsed.fragment or ";" in broker_url or parsed.netloc.endswith(":"):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        if ":" in hostname:
            ipaddress.IPv6Address(hostname)
        else:
            ascii_host = hostname.encode("idna").decode("ascii")
            if len(ascii_host) > 253 or not all(
                re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                for label in ascii_host.rstrip(".").split(".")
            ):
                raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError(
            "explicit Redis/Valkey broker hostname and valid port required"
        ) from None

    # Celery reads these ambient values before its explicit app settings. Reject
    # conflicts at startup without modifying process-wide environment variables.
    for key in (
        "CELERY_BROKER_URL",
        "CELERY_BROKER_READ_URL",
        "CELERY_BROKER_WRITE_URL",
    ):
        override = os.environ.get(key)
        if override and override != broker_url:
            raise ValueError(f"conflicting {key} configuration")
    if os.environ.get("CELERY_RESULT_BACKEND"):
        raise ValueError("CELERY_RESULT_BACKEND conflicts with disabled results")


def _create_celery_app(broker_url: str, name: str) -> Any:
    _validate_broker_configuration(broker_url)
    from celery import Celery  # type: ignore[import-untyped]

    app = Celery(name, broker=broker_url)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_ignore_result=True,
        broker_transport_options={"visibility_timeout": 3600},
        result_backend=None,
        task_default_queue="wso.default",
        task_soft_time_limit=25,
        task_time_limit=30,
        broker_connection_retry_on_startup=True,
    )
    return app


def create_app(
    broker_url: str,
    job_database_url: str,
    registry: JobRegistry = DEFAULT_REGISTRY,
    *,
    worker_id: str = "worker",
    after_execute: Callable[[DispatchReference], None] | None = None,
) -> Any:
    from wso_core.worker import JobWorker

    if not job_database_url.startswith("postgresql+psycopg://"):
        raise ValueError("explicit job database URL required")
    app = _create_celery_app(broker_url, "wso")

    @app.task(name="wso.execute_job")  # type: ignore[untyped-decorator]
    def execute_job(reference: dict[str, Any]) -> None:
        parsed = DispatchReference.model_validate(reference)
        worker = JobWorker(job_database_url, registry, worker_id)
        try:
            worker.execute(parsed)
            if after_execute is not None:
                after_execute(parsed)
        finally:
            worker.engine.dispose()

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["dispatch", "worker"])
    parser.add_argument(
        "--queue",
        choices=["wso.default", "wso.browser", "wso.cli", "wso.media"],
        default="wso.default",
    )
    args = parser.parse_args()
    broker = os.environ["WSO_BROKER_URL"]
    if args.command == "worker":
        create_app(broker, os.environ["WSO_JOB_DATABASE_URL"]).worker_main(
            ["worker", "--loglevel=WARNING", "--queues", args.queue]
        )
    else:
        from wso_core.dispatch import Dispatcher
        from wso_core.outbox import CeleryPublisher

        dispatcher = Dispatcher(
            os.environ["WSO_DISPATCH_DATABASE_URL"],
            CeleryPublisher(_create_celery_app(broker, "wso-dispatch")),
        )
        while True:
            dispatcher.run_once()
            time.sleep(0.5)


if __name__ == "__main__":
    main()
