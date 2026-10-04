"""Explicit root-owned local device browser runtime; import is inert."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://localhost:3543"
EVIDENCE_ROOT = ROOT / ".superpowers/verification/local-device-browser-runtime"
NATIVE_KEYS = tuple(
    "WSO_TVT_WINDOWS_LOCAL_INVENTORY_" + key
    for key in ("ENABLED", "BUNDLE", "STAGING", "SOURCE_REVIEW", "RUNTIME_REVIEW")
)
OWN = {
    "scripts/test-local-devices/runtime.py",
    "scripts/test-local-devices/server.mjs",
    "tests/contract/test_local_device_browser_fixture.py",
    "docs/integrations/tvt-local-device-browser-runtime.md",
}
ANCHORS = {
    ".superpowers/verification/local-device-api/root-receipt.json": "f780f9d52c4f05df1c9071623dba7f93b4cfb7be1d5f8585ec19b4ce2d066351",
    ".superpowers/verification/local-device-web/root-receipt.json": "7ea5c0675d857edd7487f79eaca086dfbae2df442df2ea67ac67e0ec71dad5f5",
    ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W08-local-service-integration-Fix2-reviewed-root-receipt.json": "d58b026a2f991ad98960ed5f3d3f54b0851b307890cfb317f2426bf8b403e66f",
}
NATIVE_SOURCE_ANCHOR = ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/M1-native-inventory-postpublication-source-root-receipt.json"
NATIVE_SOURCE_SHA = "06aea3adedc19e179aac515e9c962baf6a525ee36dad9b480ad18dde32410483"
BORROWED = {
    "scripts/test-tvt-account/runtime.py",
    "scripts/test-tvt-account/server.mjs",
    "tests/integration/test_tvt_directory_admission.py",
    "tests/integration/test_tvt_account_flow_admission.py",
    "tests/integration/test_tvt_sessions.py",
    "tests/tvt_parity/test_bridge_mtls.py",
    "packages/core/src/wso_core/connections.py",
    "packages/core/src/wso_core/secrets.py",
    "packages/core/src/wso_core/tvt/local_credentials.py",
    "services/api/src/wso_api/auth.py",
    "services/tvt-bridge/src/wso_tvt_bridge/windows_socket.py",
    "services/tvt-bridge/src/wso_tvt_bridge/windows_socket_worker.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_ipc.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_provider.py",
    "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_config.py",
    "tests/contract/test_windows_socket.py",
    "tests/contract/test_local_inventory_provider.py",
    "docs/integrations/tvt-windows-socket-provider.md",
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def bounded_file(path, limit=65536):
    path = Path(path)
    if (
        not path.is_absolute()
        or not path.is_file()
        or path.is_symlink()
        or path.is_junction()
    ):
        raise ValueError("bounded private file required")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise ValueError("bounded private file required")
    return raw


def anchored_sources(root=ROOT):
    trusted = {}
    for relative, digest in ANCHORS.items():
        raw = bounded_file(root / relative)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or hashlib.sha256(raw).hexdigest() != digest
        ):
            raise ValueError("new local browser source approval refused")
        data = json.loads(raw, object_pairs_hook=unique_object)
        if data["status"] != "SOURCE_ACCEPTED_UNPUBLISHED":
            raise ValueError("new local browser source approval refused")
        trusted.update(
            {name: value["sha256"] for name, value in data["sources"].items()}
        )
    return trusted


def verify_source_approval(path, expected_digest, *, required_paths=None, root=ROOT):
    try:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise ValueError()
        raw = bounded_file(path)
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError()
        receipt = json.loads(raw, object_pairs_hook=unique_object)
        if (
            set(receipt)
            != {"schema_version", "root_explicitly_accepted", "scope", "sources"}
            or type(receipt["schema_version"]) is not int
            or receipt["schema_version"] != 1
            or receipt["root_explicitly_accepted"] is not True
            or receipt["scope"] != "owned-local-device-browser-only"
        ):
            raise ValueError()
        required = set(required_paths) if required_paths is not None else OWN | BORROWED
        trusted = {}
        if required_paths is None:
            trusted = anchored_sources(root)
            native_raw = bounded_file(root / NATIVE_SOURCE_ANCHOR)
            if hashlib.sha256(native_raw).hexdigest() != NATIVE_SOURCE_SHA:
                raise ValueError()
            native = json.loads(native_raw, object_pairs_hook=unique_object)
            if (
                set(native)
                != {"status", "files", "dependencies", "critical", "important", "minor"}
                or native["status"] != "ACCEPTED_WINDOWS_NATIVE_PROVIDER_ROOT_REVIEW"
                or any(native[key] != 0 for key in ("critical", "important", "minor"))
            ):
                raise ValueError()
            for mapping in (native["files"], native["dependencies"]):
                for relative, value in mapping.items():
                    if relative in trusted and trusted[relative] != value["sha256"]:
                        raise ValueError()
                    trusted[relative] = value["sha256"]
            required |= set(trusted)
        sources = receipt["sources"]
        if (
            type(sources) is not dict
            or not required.issubset(sources)
            or len(sources) > 1024
        ):
            raise ValueError()
        for relative, digest in sources.items():
            if (
                type(relative) is not str
                or "\\" in relative
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError()
            target = root / relative
            if (
                target.is_symlink()
                or target.is_junction()
                or not target.is_file()
                or hashlib.sha256(target.read_bytes()).hexdigest() != digest
                or (relative in trusted and trusted[relative] != digest)
            ):
                raise ValueError()
        return sources
    except (ValueError, TypeError, KeyError, OSError):
        raise ValueError("new local browser source approval refused") from None


class PrivateInput:
    __slots__ = ("alias", "credentials", "store_label")

    def __init__(self, alias, label, credentials):
        self.alias, self.store_label, self.credentials = alias, label, credentials

    def __repr__(self):
        return "<LocalBrowserInput: private>"


def parse_input(raw):
    from wso_core.tvt.local_credentials import parse_local_device_credentials

    try:
        if type(raw) is not bytes or len(raw) > 16384:
            raise ValueError()
        body = json.loads(raw, object_pairs_hook=unique_object)
        if (
            type(body) is not dict
            or set(body) != {"schema_version", "devices"}
            or type(body["schema_version"]) is not int
            or body["schema_version"] != 1
            or type(body["devices"]) is not list
            or len(body["devices"]) != 2
        ):
            raise ValueError()
        items = []
        for device in body["devices"]:
            if type(device) is not dict or set(device) != {
                "alias",
                "store_label",
                "credentials",
            }:
                raise ValueError()
            credentials = parse_local_device_credentials(
                json.dumps(device["credentials"], separators=(",", ":")).encode()
            )
            for key in ("alias", "store_label"):
                value = device[key]
                if (
                    type(value) is not str
                    or not 1 <= len(value) <= 200
                    or value != value.strip()
                    or any(ord(c) < 32 for c in value)
                    or any(
                        secret.casefold() in value.casefold()
                        for secret in (
                            credentials.serial,
                            credentials.username,
                            credentials.password,
                        )
                    )
                ):
                    raise ValueError()
            items.append(
                PrivateInput(device["alias"], device["store_label"], credentials)
            )
        if (
            len({item.credentials.serial for item in items}) != 2
            or len({item.alias for item in items}) != 2
            or len({item.store_label for item in items}) != 2
        ):
            raise ValueError()
        return tuple(items)
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid private local input") from None


def borrowed_helpers():
    path = ROOT / "scripts/test-tvt-account/runtime.py"
    raw = bounded_file(path)
    if (
        hashlib.sha256(raw).hexdigest()
        != "1d961908c917d66f2da4e111c4dd1eddf46d1c130d8a542957c92b3944a0ba97"
    ):
        raise ValueError("borrowed browser helper source refused")
    spec = importlib.util.spec_from_file_location("reviewed_browser_helpers", path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), "exec"), module.__dict__)  # noqa: S102 - execute exact admitted bytes
    return module


def api_environment(roles, auth, bridge, key, ca):
    env = (
        borrowed_helpers().child_environment()
        | {
            "WSO_TEST_LOCAL_DEVICE_BROWSER": "1",
            "WSO_CONNECTION_KEY_FILE": str(key),
            "SSL_CERT_FILE": str(ca),
        }
        | auth
    )
    env.update(
        {
            f"WSO_{role}_DATABASE_URL": roles[role]
            for role in ("APP", "IDENTITY", "SESSION")
        }
    )
    env.update(
        {
            "WSO_TVT_BRIDGE_" + name: bridge[name]
            for name in ("ENDPOINT", "CA_FILE", "CLIENT_CERT_FILE", "CLIENT_KEY_FILE")
        }
    )
    return env


def worker_environment(roles, native, key):
    if (
        set(native) != set(NATIVE_KEYS)
        or native[NATIVE_KEYS[0]] != "1"
        or not all(native.values())
    ):
        raise ValueError("explicit reviewed native configuration required")
    return (
        borrowed_helpers().child_environment()
        | native
        | {
            "WSO_TEST_LOCAL_DEVICE_BROWSER": "1",
            "WSO_TEST_LOCAL_DEVICE_NATIVE": "real",
            "WSO_WORKER_DATABASE_URL": roles["WORKER"],
            "WSO_CONNECTION_KEY_FILE": str(key),
        }
    )


def required_provider(loader):
    from wso_tvt_bridge.local_inventory_provider import NativeLocalInventoryProvider

    provider = loader()
    if type(provider) is not NativeLocalInventoryProvider:
        raise ValueError("reviewed native provider unavailable")
    return provider


def settle_child(child, folder, label, *, budget=30, receipt=None, pause=time.sleep):
    if child is None:
        return
    record = receipt or (
        lambda value: borrowed_helpers().write_private(
            folder / (label + "-settled.json"), value
        )
    )
    if child.poll() is None:
        try:
            child.stdin.write(b"close\n")
            child.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
    deadline = time.monotonic() + budget
    reported = False
    while child.poll() is None:
        if not reported and time.monotonic() >= deadline:
            record({"exit": None, "custody_retained": True, "incomplete": True})
            reported = True
        pause(0.05)
    record({"exit": child.poll(), "custody_retained": False, "incomplete": False})
    if child.poll() != 0 or reported:
        raise RuntimeError("owned local child failed after settlement")


def spawn_python(arguments, env):
    import sysconfig

    launch = f"import site,runpy,sys;sys.prefix={sys.prefix!r};site.addsitedir({sysconfig.get_paths()['purelib']!r});sys.path.insert(0,{str(ROOT)!r});sys.argv={([str(Path(__file__).resolve())] + arguments)!r};runpy.run_path(sys.argv[0],run_name='__main__')"
    return subprocess.Popen(
        [sys._base_executable if os.name == "nt" else sys.executable, "-c", launch],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@contextmanager
def owned_database(evidence):
    import pytest
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from tests.integration import test_tvt_directory_admission as accepted

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(accepted, "EVIDENCE", evidence)
        with contextmanager(accepted.directory_database.__wrapped__)() as engines:
            owned = engines["ADMIN"].url.database
            if not re.fullmatch(r"w07_directory_[0-9a-f]{32}", owned):
                raise ValueError("fresh owned local database required")
            with engines["ADMIN"].connect() as db:
                actual, marker = db.execute(
                    text(
                        "SELECT current_database(),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"
                    )
                ).one()
                if actual != owned or not marker.startswith("owned-w07-directory-"):
                    raise ValueError("fresh owned local database required")
            cfg = Config(str(ROOT / "infra/alembic.ini"))
            cfg.set_main_option(
                "sqlalchemy.url",
                engines["ADMIN"]
                .url.render_as_string(hide_password=False)
                .replace("%", "%%"),
            )
            command.upgrade(cfg, "0012_tvt_local_devices")
            try:
                yield engines
            finally:
                command.downgrade(cfg, "0011_tvt_directory_read_tickets")


def seed_owner(engines, issuer, owner, key, inputs):
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from wso_core.connections import ConnectionService
    from wso_core.db import tenant_session
    from wso_core.secrets import FileKeyProvider
    from wso_core.tenancy import identity_session

    tenant, stores = uuid4(), (uuid4(), uuid4())
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO public.tenants(id,name) VALUES(:id,'Local Device Browser Demo')"
            ),
            {"id": tenant},
        )
        db.execute(
            text(
                "INSERT INTO public.users(id,oidc_issuer,oidc_subject) VALUES(:id,:issuer,:subject)"
            ),
            {"id": owner, "issuer": issuer, "subject": str(owner)},
        )
        db.execute(
            text(
                "INSERT INTO public.memberships(tenant_id,user_id,role) VALUES(:tenant,:owner,'OWNER')"
            ),
            {"tenant": tenant, "owner": owner},
        )
        for item, store in zip(inputs, stores, strict=True):
            db.execute(
                text(
                    "INSERT INTO public.stores(id,tenant_id,name,timezone) VALUES(:id,:tenant,:name,'Asia/Seoul')"
                ),
                {"id": store, "tenant": tenant, "name": item.store_label},
            )
    with identity_session(
        issuer, str(owner), session_factory=sessionmaker(engines["IDENTITY"])
    ) as lookup:
        choice = lookup.authorize_tenant(tenant)
    links = []
    with tenant_session(
        tenant, authorization=choice, session_factory=sessionmaker(engines["APP"])
    ) as db:
        for item, store in zip(inputs, stores, strict=True):
            view = ConnectionService(db, FileKeyProvider(key)).mutate(
                "create",
                {
                    "kind": "TVT_DEVICE",
                    "alias": item.alias,
                    "site": item.store_label,
                    "store_ids": [str(store)],
                },
                credentials=item.credentials.to_encrypt_bytes(),
            )
            links.append(
                {
                    "connectionId": str(view.id),
                    "storeId": str(store),
                    "alias": item.alias,
                    "storeLabel": item.store_label,
                    "generation": view.generation,
                }
            )
    return tenant, links


def worker_process(folder):
    if os.environ.get("WSO_TEST_LOCAL_DEVICE_NATIVE") != "real":
        raise ValueError("explicit real native worker mode required")
    from wso_core.secrets import FileKeyProvider
    from wso_core.tvt.local_admission import LocalDeviceAdmission
    from wso_core.tvt.local_service import LocalVerificationExecutor
    from wso_tvt_bridge.local_inventory_config import load_local_inventory_provider
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig
    from wso_tvt_bridge.windows_socket import PENDING_OWNERS

    helper = borrowed_helpers()
    provider = required_provider(load_local_inventory_provider)
    admission = LocalDeviceAdmission(
        os.environ["WSO_WORKER_DATABASE_URL"],
        FileKeyProvider(Path(os.environ["WSO_CONNECTION_KEY_FILE"])),
    )

    def dispose():
        for owner in list(PENDING_OWNERS):
            owner.passive_wait()
        if any(not owner.confirmed for owner in PENDING_OWNERS):
            raise RuntimeError("native custody remains")
        admission.shutdown()

    class NoCloudWorker:
        def __getattr__(self, name):
            from wso_core.tvt.account_projection import AccountFailure

            def unavailable(*args, **kwargs):
                raise AccountFailure()

            return unavailable

    server = AccountRpcServer(
        ServerConfig(
            bind="localhost:0",
            ca=(folder / "ca.pem").read_bytes(),
            certificate=(folder / "server.pem").read_bytes(),
            key=(folder / "server.key").read_bytes(),
            client_sans=frozenset({"api.test"}),
            capacity=2,
        ),
        NoCloudWorker(),
        local_device_worker=LocalVerificationExecutor(admission, provider),
        dispose=dispose,
    )
    try:
        port = server.start()
        helper.write_private(
            folder / "worker-ready.json",
            {"pid": os.getpid(), "port": port, "providerLoaded": True},
        )
        sys.stdin.readline()
    finally:
        drained = server.close(grace=20)
        if not drained:
            helper.write_private(
                folder / "worker-close.json",
                {"drained": False, "custodyRetained": True},
            )
            while not server.close(grace=1):
                time.sleep(0.1)
        helper.write_private(
            folder / "worker-close.json",
            {
                "drained": True,
                "custodyRetained": False,
                "nativeOwnersConfirmed": all(
                    owner.confirmed for owner in PENDING_OWNERS
                ),
            },
        )


def api_process(folder):
    import uvicorn
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from wso_api.auth import (
        AuthService,
        AuthSettings,
        OIDCVerifier,
        PostgresSessionStore,
    )
    from wso_core.secrets import SecretCipher
    from wso_core.tvt.local_admission import LocalDeviceAdmission
    from wso_core.tvt.local_service import LocalVerificationExecutor
    from wso_core.tvt.token_vault import TokenVault

    def forbidden(*args, **kwargs):
        raise RuntimeError("API local worker capability forbidden")

    if any(key in os.environ for key in NATIVE_KEYS) or os.environ.get(
        "WSO_WORKER_DATABASE_URL"
    ):
        raise ValueError("API worker environment refused")
    SecretCipher.open = forbidden
    LocalDeviceAdmission.__init__ = forbidden
    LocalVerificationExecutor.__init__ = forbidden
    TokenVault.__init__ = forbidden
    from wso_api.main import create_app

    helper = borrowed_helpers()
    settings = AuthSettings.from_environment()
    engines = {
        role: create_engine(
            os.environ[f"WSO_{role}_DATABASE_URL"], hide_parameters=True
        )
        for role in ("APP", "IDENTITY", "SESSION")
    }
    app = create_app()
    app.state.auth_service = AuthService(
        settings,
        OIDCVerifier(settings),
        PostgresSessionStore(
            settings.session_database_url,
            session_factory=sessionmaker(engines["SESSION"]),
        ),
        identity_factory=sessionmaker(engines["IDENTITY"]),
        tenant_factory=sessionmaker(engines["APP"]),
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(
        uvicorn.Config(
            helper.GuardedApplication(
                app, helper.AdmissionGate(folder / "admission.sqlite")
            ),
            log_config=None,
            log_level="critical",
            access_log=False,
            ssl_certfile=str(folder / "server.pem"),
            ssl_keyfile=str(folder / "server.key"),
            timeout_graceful_shutdown=5,
        )
    )

    def shutdown():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=shutdown, daemon=True).start()
    helper.write_private(
        folder / "api-ready.json",
        {"pid": os.getpid(), "port": listener.getsockname()[1]},
    )
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        for engine in engines.values():
            engine.dispose()


def owner_page_text(value):
    return (
        value.replace(
            "Sign in as synthetic directory staff", "Sign in as local device demo owner"
        )
        .replace("Synthetic directory fixture", "Local device browser verification")
        .replace(
            "Invented account and devices. No vendor connection.",
            "This synthetic owner uses real registered devices for read-only verification. Live playback and device control are separate.",
        )
    )


def coordinate():
    if os.environ.get("WSO_TEST_LOCAL_DEVICE_NATIVE") != "real" or not os.environ.get(
        "WSO_TEST_BROWSER_TLS_DIR"
    ):
        raise ValueError("explicit real mode and trusted TLS required")
    path = Path(os.environ["WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE"])
    if (
        not path.is_absolute()
        or path.name != "context.json"
        or not re.fullmatch(r"local-devices-[0-9a-f]{32}", path.parent.name)
        or path.parent.parent.resolve() != (ROOT / "auth-state").resolve()
    ):
        raise ValueError("explicit owned local context required")
    approved = verify_source_approval(
        Path(os.environ["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE"]),
        os.environ["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256"],
    )
    helper = borrowed_helpers()
    folder, owner = path.parent, secrets.token_hex(16)
    evidence = EVIDENCE_ROOT / folder.name
    evidence.mkdir(parents=True, exist_ok=False)
    helper.private_directory(folder)
    helper.write_private(folder / "owner.json", {"owner": owner})
    initial = helper.source_snapshot() | {
        name: {"raw_sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
        for name in OWN
    }
    (evidence / "source-before.json").write_text(json.dumps(initial, indent=2))
    worker = api = None
    result = {"apiSettled": False, "workerSettled": False, "contextRemoved": False}
    try:
        inputs = parse_input(
            bounded_file(Path(os.environ["WSO_TEST_LOCAL_BROWSER_INPUT_FILE"]), 16384)
        )
        from tests.tvt_parity.test_bridge_mtls import certs

        os.environ["WSO_TEST_ACCOUNT_BROWSER"] = (
            "1"  # Pure reviewed TLS helper opt-in only.
        )
        helper.browser_certificates(folder, certs)
        key = folder / "connection.key"
        key.write_bytes(secrets.token_bytes(32))
        key.chmod(0o600)
        bridge_folder = folder / "bridge"
        helper.private_directory(bridge_folder)
        certs(bridge_folder)
        gate = helper.AdmissionGate(folder / "admission.sqlite", create=True)
        fixed_owner = uuid4()
        with ExitStack() as stack:
            engines = stack.enter_context(owned_database(evidence))
            issuer_secret = secrets.token_urlsafe(48)
            issuer = helper.DirectoryIssuer(
                folder, str(fixed_owner), issuer_secret, gate
            )
            stack.callback(issuer.close)
            original = issuer.server.RequestHandlerClass

            class OwnerHandler(original):
                def respond(
                    self, status, value, content_type="application/json", **headers
                ):
                    if type(value) is str:
                        value = owner_page_text(value)
                    return super().respond(status, value, content_type, **headers)

            issuer.server.RequestHandlerClass = OwnerHandler
            tenant, links = seed_owner(engines, issuer.origin, fixed_owner, key, inputs)
            del inputs
            roles = {
                role: engines[role].url.render_as_string(hide_password=False)
                for role in ("APP", "IDENTITY", "SESSION", "WORKER")
            }
            native = {key: os.environ.get(key, "") for key in NATIVE_KEYS}
            worker = spawn_python(
                ["--worker", str(bridge_folder)], worker_environment(roles, native, key)
            )

            def close_worker():
                settle_child(worker, folder, "worker", budget=40)
                result["workerSettled"] = True

            stack.callback(close_worker)
            helper.wait_file(
                bridge_folder / "worker-ready.json", worker, time.monotonic() + 20
            )
            ready = json.loads((bridge_folder / "worker-ready.json").read_text())
            if ready["pid"] != worker.pid or ready["providerLoaded"] is not True:
                raise ValueError("owned native worker readiness refused")
            bridge = {
                "ENDPOINT": "localhost:" + str(ready["port"]),
                "CA_FILE": str(bridge_folder / "ca.pem"),
                "CLIENT_CERT_FILE": str(bridge_folder / "client.pem"),
                "CLIENT_KEY_FILE": str(bridge_folder / "client.key"),
            }
            auth = {
                "WSO_OIDC_ISSUER": issuer.origin,
                "WSO_OIDC_CLIENT_ID": "fixture-web",
                "WSO_OIDC_JWKS_URL": issuer.origin + "/jwks",
                "WSO_AUTH_EXCHANGE_KEY": secrets.token_urlsafe(48),
                "WSO_PUBLIC_ORIGIN": BASE_URL,
            }
            api = spawn_python(
                ["--api", str(folder)],
                api_environment(roles, auth, bridge, key, folder / "ca.pem"),
            )

            def close_api():
                settle_child(api, folder, "api", budget=20)
                result["apiSettled"] = True

            stack.callback(close_api)
            helper.wait_file(folder / "api-ready.json", api, time.monotonic() + 15)
            announcement = json.loads((folder / "api-ready.json").read_text())
            if announcement["pid"] != api.pid:
                raise ValueError("owned API readiness refused")
            api_origin = "https://localhost:" + str(announcement["port"])
            tls = ssl.create_default_context(cafile=str(folder / "ca.pem"))
            deadline = time.monotonic() + 10
            while True:
                if api.poll() is not None:
                    raise RuntimeError("owned API exited before HTTPS readiness")
                try:
                    with urlopen(
                        api_origin + "/health/live", context=tls, timeout=1
                    ) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError("owned API HTTPS readiness deadline")
                time.sleep(0.05)
            helper.write_private(
                path,
                {
                    "schemaVersion": 1,
                    "proofKind": "owned-local-device-native-pipeline",
                    "baseURL": BASE_URL,
                    "apiOrigin": api_origin,
                    "caFile": str(folder / "ca.pem"),
                    "certificateFile": str(folder / "server.pem"),
                    "keyFile": str(folder / "server.key"),
                    "tenantId": str(tenant),
                    "userId": str(fixed_owner),
                    "role": "OWNER",
                    "connections": links,
                    "nextAuth": {
                        key: auth[key]
                        for key in (
                            "WSO_OIDC_ISSUER",
                            "WSO_OIDC_CLIENT_ID",
                            "WSO_AUTH_EXCHANGE_KEY",
                        )
                    }
                    | {
                        "WSO_OIDC_CLIENT_SECRET": issuer_secret,
                        "WSO_FLOW_ENCRYPTION_KEY": secrets.token_urlsafe(32),
                    },
                },
            )
            while not (folder / "runtime-shutdown.json").exists():
                if api.poll() is not None or worker.poll() is not None:
                    raise RuntimeError("owned local service exited")
                time.sleep(0.1)
    finally:
        if api is not None and api.poll() is None:
            settle_child(api, folder, "api")
        if worker is not None and worker.poll() is None:
            settle_child(worker, folder, "worker")
        final = helper.source_snapshot() | {
            name: {"raw_sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
            for name in OWN
        }
        (evidence / "source-after.json").write_text(json.dumps(final, indent=2))
        result["sourceUnchanged"] = initial == final
        helper.remove_owned(folder, owner)
        result["contextRemoved"] = not folder.exists()
        (evidence / "resources.json").write_text(json.dumps(result, indent=2))
        if initial != final or any(
            hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest
            for name, digest in approved.items()
        ):
            raise RuntimeError("local browser source changed during proof")


def main():
    if os.environ.get("WSO_TEST_LOCAL_DEVICE_BROWSER") != "1":
        print(
            "Local device browser fixture requires explicit activation.",
            file=sys.stderr,
        )
        return 2
    sys.path.insert(0, str(ROOT))
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker_process(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--api":
        api_process(Path(sys.argv[2]))
    else:
        coordinate()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - private inputs/config never printed
        print("Local device browser fixture failed.", file=sys.stderr)
        raise SystemExit(1) from None
