"""Four explicit fixture READ kinds; production IMPORT is never executable here."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, field_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from wso_contracts.models import WireModel
from wso_core.jobs import JobKind, JobRegistry, JobService

from tests.support.asset_faults import require


class AssetReadPayload(WireModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    schema_version: Literal[1] = 1
    operation_id: UUID
    asset_id: UUID
    checkpoint: Literal["none", "after-read", "after-commit"] = "none"

    @field_validator("schema_version", mode="before")
    @classmethod
    def version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("invalid fixture payload")
        return value

    @field_validator("operation_id", "asset_id")
    @classmethod
    def identity(cls, value):
        if value.int == 0:
            raise ValueError("invalid fixture payload")
        return value


@dataclass(frozen=True, slots=True, repr=False)
class FixtureJobKind:
    name: str
    owner_scope: Literal["OWNER"] = "OWNER"
    queue: Literal["wso.default"] = "wso.default"
    effect: Literal["READ"] = "READ"
    max_attempts: Literal[3] = 3
    credential_use: Literal[False] = False
    reconcile: None = None


@dataclass(frozen=True, slots=True, repr=False)
class ReadBinding:
    kind: str
    purpose: Literal["PHOTO", "CROP"]
    scope: Literal["TENANT", "STORE"]


JOB_KIND_SPECS = tuple(
    FixtureJobKind("ASSET_FIXTURE_" + name)
    for name in ("TENANT_READ", "STORE_READ", "PHOTO_ONLY", "NO_ASSET_READ")
)
ASSET_READ_BINDINGS = (
    ReadBinding("ASSET_FIXTURE_TENANT_READ", "PHOTO", "TENANT"),
    ReadBinding("ASSET_FIXTURE_TENANT_READ", "CROP", "TENANT"),
    ReadBinding("ASSET_FIXTURE_STORE_READ", "PHOTO", "STORE"),
    ReadBinding("ASSET_FIXTURE_STORE_READ", "CROP", "STORE"),
    ReadBinding("ASSET_FIXTURE_PHOTO_ONLY", "PHOTO", "TENANT"),
)
_READER = None
_CONTROL = None


def publish_read_milestone(job_id, milestone, error=None):
    """Best-effort fixed facts; preserve fresh cancellation or an active error."""
    if _CONTROL is None:
        return
    try:
        import multiprocessing

        from wso_core.asset_process import decode_control

        from tests.support.asset_broker import checked_read_progress, exception_category
        from tests.support.asset_faults import snapshot_json as private_json

        require(
            milestone
            in {"READ_ENTERED", "READ_SUCCEEDED", "READ_FAILED", "AFTER_EXECUTE"}
        )
        job_id = UUID(str(job_id))
        path = _CONTROL.directory / ("read-progress-" + str(job_id) + ".json")
        if milestone == "READ_ENTERED" or not path.exists():
            row = {
                "owner": _CONTROL.owner,
                "job_id": str(job_id),
                "parent_daemon": multiprocessing.current_process().daemon,
                "read_entered": False,
                "read_succeeded": False,
                "read_failed": False,
                "after_execute": False,
                "read_exception": "NONE",
            }
        else:
            with path.open("rb") as stream:
                raw = stream.read(4097)
            require(len(raw) <= 4096)
            row = decode_control(raw)
            checked_read_progress(row, _CONTROL.owner, job_id)
        row[milestone.lower()] = True
        if milestone == "READ_FAILED":
            row["read_exception"] = exception_category(error)
        checked_read_progress(row, _CONTROL.owner, job_id)
        private_json(path, row)
    except Exception:  # noqa: BLE001 -- ordinary diagnostic failures are best effort.
        return
    except BaseException:  # Preserve an already caught handler failure.
        if error is None:
            raise
        return


def reader_for_step(step, env):
    from wso_core.asset_crypto import AssetCipher, LocalAssetKeyProvider
    from wso_core.assets import (
        AssetAdmissionController,
        JobAssetReader,
        read_asset_runtime_configuration,
    )
    from wso_core.storage import (
        S3Credentials,
        S3ObjectStore,
        S3RuntimeConfig,
        SpawnS3Client,
    )

    global _READER
    require(
        step.session.execute(text("SELECT current_user")).scalar_one()
        == "wso_job_worker"
    )
    configuration = read_asset_runtime_configuration(step.session)
    require(
        str(configuration.namespace.installation_id) == env["WSO_ASSET_INSTALLATION_ID"]
        and configuration.namespace.bucket == env["WSO_ASSET_S3_BUCKET"]
    )
    if _READER is None:
        config = S3RuntimeConfig(
            endpoint_url=env["WSO_ASSET_S3_ENDPOINT_URL"],
            region=env["WSO_ASSET_S3_REGION"],
            credentials=S3Credentials(
                env["WSO_ASSET_S3_ACCESS_KEY_ID"],
                env["WSO_ASSET_S3_SECRET_ACCESS_KEY"],
                env.get("WSO_ASSET_S3_SESSION_TOKEN"),
            ),
            namespace=configuration.namespace,
            allow_loopback_http=True,
        )
        provider = LocalAssetKeyProvider(
            active_key_id=env["WSO_ASSET_ACTIVE_KEY_ID"],
            key_files={
                k: Path(v)
                for k, v in json.loads(env["WSO_ASSET_KEY_FILES_JSON"]).items()
            },
        )
        _READER = JobAssetReader(
            objects=S3ObjectStore(
                client=SpawnS3Client(config=config), namespace=configuration.namespace
            ),
            cipher=AssetCipher(provider),
            policy=configuration.policy,
            admission=AssetAdmissionController(upload_slots=2, read_slots=2),
            on_event=None,
        )
    require(
        _READER.policy == configuration.policy
        and _READER.objects.namespace == configuration.namespace
    )
    return _READER


def read_handler(step):
    from wso_core.assets import AssetEvent, AssetFailure
    from wso_core.jobs import JobFailure

    payload = step.payload
    require(type(payload) is AssetReadPayload)
    cutoff = min(
        time.monotonic() + 20,
        time.monotonic() + (step.lease.expires_at - datetime.now(UTC)).total_seconds(),
    )
    publish_read_milestone(step.lease.job_id, "READ_ENTERED")
    try:
        data = reader_for_step(step, os.environ).read(step, payload.asset_id)
    except BaseException as error:
        publish_read_milestone(step.lease.job_id, "READ_FAILED", error)
        if not isinstance(error, AssetFailure):
            raise
        if error.status not in {403, 404}:
            raise
        from tests.support.asset_faults import snapshot_json as private_json

        require(_CONTROL is not None)
        private_json(
            _CONTROL.directory / ("denied-" + str(step.lease.job_id) + ".json"),
            {
                "owner": _CONTROL.owner,
                "job_id": str(step.lease.job_id),
                "status": error.status,
                "code": error.code,
            },
        )
        raise JobFailure(error.status, "ASSET_READ_DENIED") from None
    publish_read_milestone(step.lease.job_id, "READ_SUCCEEDED")
    result = {"sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
    del data
    if _CONTROL is not None:
        from tests.support.asset_faults import snapshot_json as private_json

        private_json(
            _CONTROL.directory / "job-lease.json",
            {
                "owner": _CONTROL.owner,
                "job_id": str(step.lease.job_id),
                "token": step.lease.token,
                "generation": step.lease.generation,
                "expires_at": step.lease.expires_at.isoformat(),
            },
        )
    if payload.checkpoint == "after-read" and step.lease.generation == 1:
        require(_CONTROL is not None and time.monotonic() < cutoff)
        _CONTROL.callback(AssetEvent("JOB_AFTER_READ", step.lease.job_id))
        require(time.monotonic() < cutoff)
    step.record_item(str(payload.operation_id), "SUCCEEDED", result)
    step.complete(result)
    return result


REGISTRY = JobRegistry(
    tuple(
        JobKind(
            spec.name,
            AssetReadPayload,
            "STORE" if spec.name == "ASSET_FIXTURE_STORE_READ" else "TENANT",
            permission=spec.owner_scope,
            queue=spec.queue,
            effect_mode=spec.effect,
            max_attempts=spec.max_attempts,
            credential_use=False,
            handler=read_handler,
            reconcile=None,
        )
        for spec in JOB_KIND_SPECS
    )
)


def create_worker_app(env, control):
    from celery.signals import worker_process_init, worker_process_shutdown
    from wso_core.assets import AssetEvent
    from wso_core.job_runtime import create_app

    from tests.support.asset_faults import (
        HelperObserver,
        process_identity,
        process_identity_snapshot,
    )
    from tests.support.asset_faults import snapshot_json as private_json

    global _CONTROL
    _CONTROL = control
    from tests.support.asset_broker import install_transport_observer

    install_transport_observer(control)
    observer = {}

    def after_execute(reference):
        publish_read_milestone(reference.job_id, "AFTER_EXECUTE")
        control.callback(AssetEvent("JOB_AFTER_COMMIT", reference.job_id))

    app = create_app(
        env["WSO_ASSET_FIXTURE_BROKER_URL"],
        env["WSO_TEST_JOB_DATABASE_URL"],
        registry=REGISTRY,
        worker_id=env["WSO_ASSET_FIXTURE_WORKER_ID"],
        after_execute=after_execute,
    )
    app.conf.broker_transport_options = {"visibility_timeout": 40}

    @worker_process_init.connect(weak=False)
    def child_init(**_kwargs):
        global _READER
        _READER = None
        identity = process_identity(os.getpid(), control.owner)
        private_json(
            control.directory / f"child-{os.getpid()}.json",
            process_identity_snapshot(identity),
        )
        observer["helper"] = HelperObserver(control).start()
        control.callback(AssetEvent("WORKER_READY", UUID(hex=control.owner)))
        release = control.directory / f"child-{os.getpid()}.release"
        cutoff = time.monotonic() + 3
        while not release.exists():
            require(time.monotonic() < cutoff)
            time.sleep(min(0.025, cutoff - time.monotonic()))
        require(
            json.loads(release.read_bytes())
            == {
                "owner": control.owner,
                "pid": identity.pid,
                "start_ticks": identity.start_ticks,
            }
        )

    @worker_process_shutdown.connect(weak=False)
    def child_shutdown(**_kwargs):
        if "helper" in observer:
            observer["helper"].close()
        if _READER is not None:
            require(
                _READER.objects.local_cleanup_complete()
                and _READER.admission.retire_if_idle()
            )
        private_json(
            control.directory / f"child-{os.getpid()}-settled.json",
            {"owner": control.owner, "settled": True},
        )

    return app


def enqueue_attached(
    service,
    principal,
    scope,
    payload,
    kind,
    idempotency_key,
    *,
    attach=True,
    attachment_id=None,
):
    from wso_api.stores.router import require_store, require_tenant

    definition = REGISTRY.get(kind)
    parsed = AssetReadPayload.model_validate(payload)
    require(definition.scope_kind == scope.scope_kind)
    attaching = False
    try:
        with require_tenant(
            "assets:write", scope.tenant_id, service=service, principal=principal
        ) as authorized:
            if scope.scope_kind == "STORE":
                require_store("jobs:read", scope.store_id, tenant=authorized)
            job = JobService(authorized.session, registry=REGISTRY).enqueue(
                scope, kind, parsed, idempotency_key
            )
            require(type(attach) is bool)
            if attach:
                attaching = True
                authorized.session.execute(
                    text("SELECT public.wso_attach_job_asset(:job,:asset)"),
                    {"job": job.id, "asset": attachment_id or parsed.asset_id},
                )
            return job
    except DBAPIError as error:
        # This boundary is outside require_tenant: its transaction has rolled back.
        if attaching and getattr(error.orig, "sqlstate", None) in {"42501", "P0002"}:
            from wso_core.jobs import db_error

            raise db_error(error) from None
        raise


def run_producer(env, control):
    from fastapi import HTTPException
    from starlette.requests import Request
    from wso_api.auth import SESSION_COOKIE
    from wso_contracts.models import StoreScope, TenantScope
    from wso_core.assets import AssetFailure
    from wso_core.jobs import JobFailure

    from tests.support.asset_faults import snapshot_json as private_json
    from tests.support.job_process import auth_service

    request_data = json.loads((control.directory / "producer.json").read_bytes())
    require(request_data["owner"] == control.owner)
    service, engines = auth_service()
    try:
        request = Request(
            {
                "type": "http",
                "headers": [
                    (b"cookie", f"{SESSION_COOKIE}={request_data['token']}".encode())
                ],
            }
        )
        principal = service.authenticate(request)
        scope_type = (
            StoreScope
            if request_data["scope"].get("scope_kind") == "STORE"
            else TenantScope
        )
        scope = scope_type.model_validate(request_data["scope"])
        try:
            job = enqueue_attached(
                service,
                principal,
                scope,
                request_data["payload"],
                request_data["kind"],
                request_data["idempotency_key"],
                attach=request_data.get("attach", True),
                attachment_id=UUID(request_data["attachment_id"])
                if request_data.get("attachment_id")
                else None,
            )
        except (JobFailure, AssetFailure, HTTPException):
            private_json(
                control.directory / "producer-result.json",
                {"owner": control.owner, "accepted": False},
            )
        else:
            private_json(
                control.directory / "producer-result.json",
                {"owner": control.owner, "accepted": True, "job_id": str(job.id)},
            )
    finally:
        import sys

        primary = sys.exc_info()[1]
        first = None
        for engine in engines.values():
            try:
                engine.dispose()
            except BaseException as error:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
                first = first or error
        if first is not None and primary is None:
            raise RuntimeError("owned producer settlement refused") from None


def check_stale_lease(env, control):
    from wso_core.worker import JobLease, JobWorker

    from tests.support.asset_faults import snapshot_json as private_json

    value = json.loads((control.directory / "stale-lease.json").read_bytes())
    require(value["owner"] == control.owner)
    lease = value["lease"]
    worker = JobWorker(
        env["WSO_TEST_JOB_DATABASE_URL"], REGISTRY, env["WSO_ASSET_FIXTURE_WORKER_ID"]
    )
    try:
        try:
            with worker.step(
                JobLease(
                    UUID(lease["job_id"]),
                    lease["token"],
                    lease["generation"],
                    datetime.fromisoformat(lease["expires_at"]),
                )
            ):
                raise RuntimeError("stale job step accepted")
        except Exception as error:  # noqa: BLE001 -- classify actual protected denial only
            from wso_core.jobs import JobFailure

            require(isinstance(error, JobFailure) and error.status in {403, 404, 409})
            private_json(
                control.directory / "stale-result.json",
                {"owner": control.owner, "denied": True},
            )
    finally:
        worker.engine.dispose()


def check_guc_spoof(env, control):
    from sqlalchemy import create_engine
    from sqlalchemy.exc import DBAPIError

    from tests.support.asset_faults import snapshot_json as private_json

    value = json.loads((control.directory / "spoof.json").read_bytes())
    require(value["owner"] == control.owner)
    engine = create_engine(env["WSO_TEST_JOB_DATABASE_URL"], hide_parameters=True)
    try:
        for statement in (
            "SELECT * FROM wso_private.asset_uploads",
            "UPDATE public.assets SET state='DELETED' WHERE id=:asset",
            "SELECT * FROM public.wso_begin_job_asset_read(:asset)",
        ):
            with engine.connect() as db:
                transaction = db.begin()
                try:
                    db.execute(text("SET LOCAL statement_timeout=5000"))
                    for name, entry in (
                        ("wso.job_id", value["job_id"]),
                        ("wso.job_lease_token", value["token"]),
                        ("wso.user_id", value["actor"]),
                        ("wso.tenant_id", value["tenant"]),
                    ):
                        db.execute(
                            text("SELECT set_config(:name,:value,true)"),
                            {"name": name, "value": entry},
                        )
                    db.execute(text(statement), {"asset": UUID(value["asset_id"])})
                except DBAPIError as error:
                    require(getattr(error.orig, "sqlstate", None) == "42501")
                else:
                    raise RuntimeError("unprotected JOB authority accepted")
                finally:
                    transaction.rollback()
        private_json(
            control.directory / "spoof-result.json",
            {"owner": control.owner, "denied": True},
        )
    finally:
        engine.dispose()
