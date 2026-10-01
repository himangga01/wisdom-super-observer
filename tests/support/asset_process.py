"""Fixed owned subprocess factories; importing opens no external resources."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from wso_core.storage import InstallationNamespace, S3Credentials

from tests.support.asset_faults import (
    BarrierControl,
    FixtureContractError,
    HelperObserver,
    RecordingObjectStore,
    RecordingTransactions,
    SendObserver,
    private_string,
    require,
)

ROLES = MappingProxyType(
    {
        "ADMIN": "postgres",
        "APP": "wso_app",
        "IDENTITY": "wso_identity_bootstrap",
        "SESSION": "wso_web_session",
        "MIGRATOR": "wso_migrator",
        "WORKER": "wso_connection_worker",
        "DISPATCH": "wso_dispatcher",
        "JOB": "wso_job_worker",
        "ASSET_MAINTENANCE": "wso_asset_maintenance",
    }
)


class ProcessMode(str, Enum):
    API = "API"
    PRODUCER = "PRODUCER"
    JOB_WORKER = "JOB_WORKER"
    DISPATCH = "DISPATCH"
    MAINTENANCE = "MAINTENANCE"
    RECONCILE = "RECONCILE"


@dataclass(frozen=True, slots=True, repr=False)
class ProcessSpec:
    owner: str
    private_directory: Path
    control_path: Path
    namespace: InstallationNamespace
    endpoint_url: str
    region: str
    gateway: S3Credentials
    maintenance: S3Credentials
    key_files: Mapping[str, Path]
    active_key_id: str
    broker_url: str
    worker_id: str

    def __post_init__(self):
        try:
            self._validate()
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise FixtureContractError() from None

    def _validate(self):
        require(
            type(self.private_directory) is type(Path())
            and type(self.control_path) is type(Path())
        )
        require(
            ".." not in self.private_directory.parts
            and ".." not in self.control_path.parts
        )
        private_string(self.owner, 128)
        require(self.owner.isascii())
        root = Path(self.private_directory)
        control = Path(self.control_path)
        require(
            root.is_absolute()
            and control.is_absolute()
            and control.is_relative_to(root)
        )
        require(
            type(self.namespace) is InstallationNamespace
            and self.namespace.installation_id.int != 0
        )
        for url, scheme in ((self.endpoint_url, "http"), (self.broker_url, "redis")):
            private_string(url)
            parsed = urlsplit(url)
            require(
                parsed.scheme == scheme
                and parsed.hostname == "127.0.0.1"
                and parsed.port is not None
                and 1 <= parsed.port <= 65535
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
            )
            require(parsed.path in ({"", "/"} if scheme == "http" else {"", "/0"}))
        require(
            type(self.gateway) is S3Credentials
            and type(self.maintenance) is S3Credentials
        )
        require(isinstance(self.key_files, Mapping) and bool(self.key_files))
        keys = {}
        for name, value in self.key_files.items():
            private_string(name, 128)
            require(
                name.isascii()
                and type(value) is type(Path())
                and ".." not in value.parts
                and value.is_absolute()
                and value.is_relative_to(root)
            )
            keys[name] = value
        require(self.active_key_id in keys)
        private_string(self.region, 128)
        private_string(self.worker_id, 128)
        object.__setattr__(self, "private_directory", root)
        object.__setattr__(self, "control_path", control)
        object.__setattr__(self, "key_files", MappingProxyType(keys))


def build_process_env(mode, source, spec):
    require(
        type(mode) is ProcessMode
        and isinstance(source, Mapping)
        and type(spec) is ProcessSpec
    )
    try:
        urls = {
            name: make_url(source[f"WSO_TEST_{name}_DATABASE_URL"]) for name in ROLES
        }
        admin = urls["ADMIN"]
        require(
            admin.host == "127.0.0.1"
            and admin.port is not None
            and bool(admin.database)
        )
        for name, role in ROLES.items():
            url = urls[name]
            require(type(source[f"WSO_TEST_{name}_DATABASE_URL"]) is str)
            require(
                (url.drivername, url.host, url.port, url.database, url.username)
                == ("postgresql+psycopg", "127.0.0.1", admin.port, admin.database, role)
            )
            require(
                bool(url.password)
                and not url.query
                and "#" not in source[f"WSO_TEST_{name}_DATABASE_URL"]
            )
        require(
            source.get("CI") == "true"
            and source.get("WSO_CI_DISPOSABLE_POSTGRES") == "1"
        )
        output = {
            name: source[name]
            for name in (
                "PATH",
                "LANG",
                "LC_ALL",
                "TMPDIR",
                "CI",
                "WSO_CI_DISPOSABLE_POSTGRES",
            )
            if name in source
        }
        require(
            all(
                type(v) is str and "\x00" not in v and "\n" not in v and "\r" not in v
                for v in output.values()
            )
        )
        if "TMPDIR" in output:
            require(
                Path(output["TMPDIR"]).is_absolute()
                and Path(output["TMPDIR"]).is_relative_to(spec.private_directory)
            )
        output.update(
            WSO_ASSET_FIXTURE_OWNER=spec.owner,
            WSO_ASSET_FIXTURE_CONTROL=str(spec.control_path),
        )
        if mode in {ProcessMode.API, ProcessMode.PRODUCER}:
            for name in ("APP", "IDENTITY", "SESSION"):
                value = source[f"WSO_TEST_{name}_DATABASE_URL"]
                output[f"WSO_{name}_DATABASE_URL"] = value
                output[f"WSO_TEST_{name}_DATABASE_URL"] = value
        elif mode is ProcessMode.JOB_WORKER:
            output["WSO_TEST_JOB_DATABASE_URL"] = source["WSO_TEST_JOB_DATABASE_URL"]
            output["WSO_ASSET_FIXTURE_BROKER_URL"] = spec.broker_url
            output["WSO_ASSET_FIXTURE_WORKER_ID"] = spec.worker_id
        elif mode is ProcessMode.DISPATCH:
            output["WSO_TEST_DISPATCH_DATABASE_URL"] = source[
                "WSO_TEST_DISPATCH_DATABASE_URL"
            ]
            output["WSO_ASSET_FIXTURE_BROKER_URL"] = spec.broker_url
        else:
            output["WSO_ASSET_MAINTENANCE_DATABASE_URL"] = source[
                "WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL"
            ]
            output["WSO_ASSET_MAINTENANCE_WORKER_ID"] = spec.worker_id
        if mode is not ProcessMode.DISPATCH:
            output.update(
                WSO_ASSET_S3_ENDPOINT_URL=spec.endpoint_url,
                WSO_ASSET_S3_REGION=spec.region,
                WSO_ASSET_S3_BUCKET=spec.namespace.bucket,
                WSO_ASSET_INSTALLATION_ID=str(spec.namespace.installation_id),
                WSO_ASSET_S3_ALLOW_LOOPBACK_HTTP="1",
            )
            maintenance = mode in {ProcessMode.MAINTENANCE, ProcessMode.RECONCILE}
            credentials = spec.maintenance if maintenance else spec.gateway
            prefix = "WSO_ASSET_MAINTENANCE_S3" if maintenance else "WSO_ASSET_S3"
            output[prefix + "_ACCESS_KEY_ID"] = credentials.access_key_id
            output[prefix + "_SECRET_ACCESS_KEY"] = credentials.secret_access_key
            if credentials.session_token is not None:
                output[prefix + "_SESSION_TOKEN"] = credentials.session_token
            if not maintenance:
                output["WSO_ASSET_ACTIVE_KEY_ID"] = spec.active_key_id
                output["WSO_ASSET_KEY_FILES_JSON"] = json.dumps(
                    {k: str(v) for k, v in sorted(spec.key_files.items())},
                    separators=(",", ":"),
                )
        return output
    except (KeyError, TypeError, ValueError, ArgumentError):
        raise FixtureContractError() from None


def create_fixture_api(env, control):
    from wso_api.assets.bootstrap import load_asset_settings, start_asset_runtime
    from wso_api.auth import configure_auth
    from wso_api.main import create_app

    from tests.support.asset_faults import snapshot_json as private_json
    from tests.support.job_process import auth_service

    runtime = start_asset_runtime(
        settings=load_asset_settings(env), on_event=control.callback
    )
    engines = {}
    observer = None
    try:
        app = create_app(asset_runtime=runtime)
        service, engines = auth_service()
        configure_auth(app, service)
        previous = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(application):
            nonlocal observer
            observer = HelperObserver(control).start()
            try:
                async with previous(application):
                    yield
            finally:
                first = None
                try:
                    observer.close()
                    require(
                        runtime.objects.local_cleanup_complete()
                        and runtime.admission.retire_if_idle()
                    )
                except BaseException as error:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
                    first = error
                for name in ("web_session", "identity", "tenant", "redemption"):
                    try:
                        getattr(runtime.authorization, name).dispose()
                    except BaseException as error:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
                        first = first or error
                for engine in engines.values():
                    try:
                        engine.dispose()
                    except BaseException as error:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
                        first = first or error
                if first is not None:
                    raise RuntimeError("owned API settlement refused") from None
                private_json(
                    control.directory / "settled.json",
                    {"owner": control.owner, "settled": True},
                )

        app.router.lifespan_context = lifespan
        records = []

        def journal(value):
            require(len(records) < 4096)
            records.append(value)
            private_json(control.directory / "send.json", records, owner=control.owner)

        app.add_middleware(SendObserver, journal=journal)
        return app
    except BaseException:
        for name in ("web_session", "identity", "tenant", "redemption"):
            try:
                getattr(runtime.authorization, name).dispose()
            except BaseException:  # noqa: BLE001, S110 -- retain owned settlement failures without raw exception output.
                pass  # Preserve startup failure while attempting every owned disposal.
        for engine in engines.values():
            try:
                engine.dispose()
            except BaseException:  # noqa: BLE001, S110 -- retain owned settlement failures without raw exception output.
                pass
        raise


def create_fixture_maintenance(env, observer, control):
    from wso_api.assets.bootstrap import (
        load_asset_maintenance_settings,
        start_asset_maintenance,
    )

    def event_callback(event):
        if event.name == "CLEANUP_EFFECT_BEFORE_ACK":
            claims = [
                row
                for transaction in observer["transactions"]
                for entry in transaction
                if "wso_claim_asset_cleanup" in entry["statement"]
                for row in entry.get("rows", [])
                if row["work_id"] == event.work_id
            ]
            require(len(claims) == 1)
            from tests.support.asset_faults import snapshot_json

            snapshot_json(
                control.directory / "cleanup-claim.json",
                {"owner": control.owner, "claim": _private_value(claims[0])},
            )
        control.callback(event)

    service = start_asset_maintenance(
        settings=load_asset_maintenance_settings(env), on_event=event_callback
    )
    service.objects = RecordingObjectStore(service.objects, observer["pages"])
    service.transactions = RecordingTransactions(
        service.transactions, observer["transactions"]
    )
    return service


def _private_value(value):
    from dataclasses import fields, is_dataclass
    from datetime import datetime
    from uuid import UUID

    if isinstance(value, (UUID, datetime)):
        return str(value)
    if is_dataclass(value):
        return {f.name: _private_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_private_value(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _private_value(v) for k, v in value.items() if k != "budget"}
    require(value is None or type(value) in {str, bool, int, float})
    return value


def adapter_failure(action, progress, code):
    stages = {
        "BOOTSTRAP",
        "PRESIGN",
        "SOURCE_READ",
        "DIRECT_PUT",
        "DIRECT_READ",
        "MULTIPART_CREATE",
        "MULTIPART_PARTS",
        "MULTIPART_COMPLETE",
        "MULTIPART_READ",
        "ABORT_AND_LIST",
        "LOCAL_SETTLEMENT",
    }
    stage, body = progress.get("stage"), progress.get("body")
    return {
        "schema": 1,
        "action": action
        if type(action) is str and action in {"adapter", "presign"}
        else "UNKNOWN",
        "stage": stage if type(stage) is str and stage in stages else "UNKNOWN",
        "body": body
        if type(body) is str and body in {"BOUNDED_DIRECT", "FULL_CIPHERTEXT"}
        else "UNKNOWN",
        "error_code": code
        if type(code) is str
        and code in {"UNAVAILABLE", "DEADLINE", "INTEGRITY", "LIMIT", "NOT_FOUND"}
        else "UNKNOWN",
    }


def read_adapter_failure(directory):
    try:
        with (directory / "adapter-diagnostic.json").open("rb") as stream:
            raw = stream.read(8193)
        require(len(raw) <= 8192)
        value = json.loads(raw)
        require(type(value) is dict)
    except (OSError, ValueError):
        value = {}
    return adapter_failure(value.get("action"), value, value.get("error_code"))


def adapter_probe(env, control, action):
    progress = {"stage": "BOOTSTRAP", "body": "UNKNOWN"}
    try:
        return _adapter_probe(env, control, action, progress)
    except BaseException as error:
        from wso_core.storage import StorageFailure

        code = error.code if isinstance(error, StorageFailure) else "UNKNOWN"
        from tests.support.asset_faults import snapshot_json

        diagnostic = adapter_failure(action, progress, code)
        try:
            snapshot_json(
                control.directory / "adapter-diagnostic.json",
                diagnostic,
                owner=control.owner,
            )
            print(
                "WSO_ASSET_ADAPTER_DIAGNOSTIC=" + json.dumps(diagnostic, sort_keys=True)
            )
        except (OSError, ValueError):
            pass
        raise


def _adapter_probe(env, control, action, progress):
    """Normal APP bootstrap and SpawnS3Client, inside restricted child custody."""
    from wso_api.assets.bootstrap import load_asset_settings, start_asset_runtime
    from wso_core.storage import PART_BYTES, IOBudget, ObjectLocator

    from tests.support.asset_faults import snapshot_json as private_json

    runtime = start_asset_runtime(settings=load_asset_settings(env))
    data = json.loads((control.directory / "adapter.json").read_bytes())
    require(data["owner"] == control.owner and action in {"adapter", "presign"})
    locator = ObjectLocator(
        *(
            UUID(data[name])
            for name in ("installation_id", "tenant_id", "asset_id", "attempt_id")
        )
    )
    require(locator.installation_id == runtime.configuration.namespace.installation_id)

    def budget():
        require(time.monotonic() < data["cutoff"])
        return IOBudget(min(time.monotonic() + 10, data["cutoff"]))

    def read_all(target):
        reader = runtime.objects.get(target, max_bytes=20971556, budget=budget())
        try:
            result = bytearray()
            while True:
                chunk = reader.read(262144)
                if not chunk:
                    break
                result.extend(chunk)
                require(len(result) <= 20971556)
            return bytes(result)
        finally:
            reader.close()

    try:
        if action == "presign":
            progress["stage"] = "PRESIGN"
            result = {
                "owner": control.owner,
                "url": runtime.objects.presign(
                    locator, expires_seconds=1, budget=budget()
                ),
            }
        else:
            import hashlib

            progress["stage"] = "SOURCE_READ"
            ciphertext = read_all(locator)
            require(
                runtime.objects.head(locator, budget=budget()).byte_size
                == len(ciphertext)
            )
            probe = ObjectLocator(
                locator.installation_id,
                locator.tenant_id,
                UUID(data["probe_asset"]),
                UUID(data["probe_attempt"]),
            )
            direct_probe = ObjectLocator(
                locator.installation_id,
                locator.tenant_id,
                UUID(data["direct_probe_asset"]),
                UUID(data["direct_probe_attempt"]),
            )
            direct_body = ciphertext[: PART_BYTES + 36]
            progress.update(stage="DIRECT_PUT", body="BOUNDED_DIRECT")
            runtime.objects.put(direct_probe, direct_body, budget=budget())
            progress["stage"] = "DIRECT_READ"
            require(
                runtime.objects.head(direct_probe, budget=budget()).byte_size
                == len(direct_body)
                and read_all(direct_probe) == direct_body
            )
            progress.update(stage="MULTIPART_CREATE", body="FULL_CIPHERTEXT")
            upload = runtime.objects.create_multipart(probe, budget=budget())
            completed = False
            try:
                progress["stage"] = "MULTIPART_PARTS"
                parts = tuple(
                    runtime.objects.upload_part(
                        probe, upload, index + 1, chunk, budget=budget()
                    )
                    for index, chunk in enumerate(
                        ciphertext[start : start + PART_BYTES]
                        for start in range(0, len(ciphertext), PART_BYTES)
                    )
                )
                require(
                    all(
                        parts[index].part_number == index + 1
                        for index in range(len(parts))
                    )
                )
                progress["stage"] = "MULTIPART_COMPLETE"
                runtime.objects.complete_multipart(
                    probe, upload, parts, budget=budget()
                )
                completed = True
            finally:
                if not completed:
                    runtime.objects.abort_multipart(probe, upload, budget=budget())
            progress["stage"] = "MULTIPART_READ"
            require(
                hashlib.sha256(read_all(probe)).digest()
                == hashlib.sha256(ciphertext).digest()
            )
            progress["stage"] = "ABORT_AND_LIST"
            abandoned = runtime.objects.create_multipart(probe, budget=budget())
            require(
                any(
                    item.upload_id == abandoned
                    for item in runtime.objects.list_multipart(
                        locator=probe, budget=budget()
                    ).items
                )
            )
            runtime.objects.abort_multipart(probe, abandoned, budget=budget())
            require(
                runtime.objects.list_objects(locator=probe, budget=budget()).items
                and not runtime.objects.list_multipart(
                    locator=probe, budget=budget()
                ).items
            )
            result = {"owner": control.owner, "accepted": True}
        progress["stage"] = "LOCAL_SETTLEMENT"
        require(
            runtime.objects.local_cleanup_complete()
            and time.monotonic() < data["cutoff"]
        )
        private_json(control.directory / "adapter-result.json", result)
    finally:
        primary = sys.exc_info()[1]
        first = None
        try:
            require(
                runtime.objects.local_cleanup_complete()
                and runtime.admission.retire_if_idle()
            )
        except BaseException as error:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
            first = error
        for name in ("web_session", "identity", "tenant", "redemption"):
            try:
                getattr(runtime.authorization, name).dispose()
            except BaseException as error:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
                first = first or error
        if first is not None and primary is None:
            raise RuntimeError("owned adapter settlement refused") from None


def delete_adapter_probes(objects, value):
    """Maintenance identity deletes both owned probes under their original cutoff."""
    from wso_core.storage import IOBudget, ObjectLocator

    def budget():
        now = time.monotonic()
        require(now < value["cutoff"])
        return IOBudget(min(now + 5, value["cutoff"]))

    for prefix in ("probe", "direct_probe"):
        locator = ObjectLocator(
            UUID(value["installation_id"]),
            UUID(value["tenant_id"]),
            UUID(value[prefix + "_asset"]),
            UUID(value[prefix + "_attempt"]),
        )
        objects.delete(locator, budget=budget())
        require(
            not objects.list_objects(locator=locator, budget=budget()).items
            and not objects.list_multipart(locator=locator, budget=budget()).items
        )
    require(time.monotonic() < value["cutoff"])
    return {"deleted": True, "identity": "wso_asset_maintenance"}


def main():
    require(
        sys.platform == "linux"
        and os.environ.get("CI") == "true"
        and os.environ.get("WSO_CI_DISPOSABLE_POSTGRES") == "1"
    )
    require(len(sys.argv) == 3)
    mode = ProcessMode(sys.argv[1])
    control = BarrierControl(
        os.environ["WSO_ASSET_FIXTURE_CONTROL"], os.environ["WSO_ASSET_FIXTURE_OWNER"]
    )
    if mode is ProcessMode.API:
        if sys.argv[2] in {"adapter", "presign"}:
            adapter_probe(os.environ, control, sys.argv[2])
        else:
            import uvicorn

            uvicorn.run(
                create_fixture_api(os.environ, control),
                host="127.0.0.1",
                port=int(sys.argv[2]),
                access_log=False,
                log_level="warning",
            )
    elif mode in {ProcessMode.MAINTENANCE, ProcessMode.RECONCILE}:
        from tests.support.asset_faults import snapshot_json as private_json

        observer = {"pages": [], "transactions": []}
        service = create_fixture_maintenance(os.environ, observer, control)
        helper = HelperObserver(control).start()
        try:
            if sys.argv[2] == "stale-cleanup":
                from sqlalchemy import text
                from sqlalchemy.exc import DBAPIError

                value = json.loads(
                    (control.directory / "stale-cleanup.json").read_bytes()
                )
                require(value["owner"] == control.owner)

                class FormerCleanupDenied(RuntimeError):
                    pass

                try:
                    with service.transactions() as db:
                        try:
                            db.execute(
                                text(
                                    "SELECT public.wso_finish_asset_cleanup(:id,:generation,:token,true)"
                                ),
                                {
                                    "id": UUID(value["work_id"]),
                                    "generation": value["lease_generation"],
                                    "token": value["lease_token"],
                                },
                            )
                        except DBAPIError as error:
                            if getattr(error.orig, "sqlstate", None) == "55000":
                                raise FormerCleanupDenied() from None
                            raise
                except FormerCleanupDenied:
                    # The normal context has rolled back; its generic SQL mapper was not bypassed for unknown errors.
                    result = {"denied": True}
                else:
                    raise RuntimeError("former cleanup token accepted")
            elif sys.argv[2] == "adapter-delete":
                value = json.loads((control.directory / "adapter.json").read_bytes())
                require(
                    value["owner"] == control.owner
                    and "WSO_ASSET_KEY_FILES_JSON" not in os.environ
                )
                result = delete_adapter_probes(service.objects, value)
            elif sys.argv[2] == "no-read":
                from wso_core.storage import IOBudget, ObjectLocator, StorageFailure

                value = json.loads((control.directory / "no-read.json").read_bytes())
                require(
                    value["owner"] == control.owner
                    and "WSO_ASSET_KEY_FILES_JSON" not in os.environ
                )
                locator = ObjectLocator(
                    *(
                        UUID(value[name])
                        for name in (
                            "installation_id",
                            "tenant_id",
                            "asset_id",
                            "attempt_id",
                        )
                    )
                )
                require(
                    locator.installation_id == service.objects.namespace.installation_id
                )
                for operation in ("GET", "HEAD"):
                    require(time.monotonic() < value["cutoff"])
                    budget = IOBudget(min(time.monotonic() + 5, value["cutoff"]))
                    try:
                        if operation == "GET":
                            service.objects.get(locator, max_bytes=1, budget=budget)
                        else:
                            service.objects.head(locator, budget=budget)
                    except StorageFailure as error:
                        require(error.code == "UNAVAILABLE")
                    else:
                        raise RuntimeError("maintenance facade read accepted")
                    require(time.monotonic() < value["cutoff"])
                result = {"no_read": True}
            else:
                count = int(sys.argv[2])
                require(1 <= count <= 100)
                result = (
                    service.reconcile_once(limit=count)
                    if mode is ProcessMode.RECONCILE
                    else service.run_once(limit=count)
                )
            require(service.objects.local_cleanup_complete())
            private_json(
                control.directory / "result.json",
                {
                    "owner": control.owner,
                    "result": result,
                    "pages": _private_value(observer["pages"]),
                    "transactions": _private_value(observer["transactions"]),
                },
            )
        finally:
            helper.close()
            require(service.objects.local_cleanup_complete())
            private_json(
                control.directory / "settled.json",
                {"owner": control.owner, "settled": True},
            )
    elif mode is ProcessMode.JOB_WORKER:
        from tests.support.asset_job_handlers import (
            check_guc_spoof,
            check_stale_lease,
            create_worker_app,
        )

        if sys.argv[2] == "stale":
            check_stale_lease(os.environ, control)
        elif sys.argv[2] == "spoof":
            check_guc_spoof(os.environ, control)
        else:
            create_worker_app(os.environ, control).worker_main(
                [
                    "worker",
                    "--loglevel=ERROR",
                    "--pool=prefork",
                    "--concurrency=1",
                    "--queues=wso.default",
                    "--without-gossip",
                    "--without-mingle",
                ]
            )
    elif mode is ProcessMode.DISPATCH:
        from wso_core.dispatch import Dispatcher
        from wso_core.job_runtime import _create_celery_app
        from wso_core.outbox import CeleryPublisher

        from tests.support.asset_job_handlers import REGISTRY

        dispatcher = Dispatcher(
            os.environ["WSO_TEST_DISPATCH_DATABASE_URL"],
            CeleryPublisher(
                _create_celery_app(
                    os.environ["WSO_ASSET_FIXTURE_BROKER_URL"],
                    "wso-asset-fixture-dispatch",
                )
            ),
            registry=REGISTRY,
        )
        try:
            while True:
                dispatcher.run_once()
                time.sleep(0.1)
        finally:
            dispatcher.engine.dispose()
    else:
        from tests.support.asset_job_handlers import run_producer

        run_producer(os.environ, control)


if __name__ == "__main__":
    main()
