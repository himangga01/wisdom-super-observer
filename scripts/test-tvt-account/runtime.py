"""Explicit, private browser fixture. Never imported by production applications."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT
    / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W05-account-browser-fixture-fix1-evidence"
)


def canonical_digest(raw):
    canonical = raw.replace(b"\r\n", b"\n")
    if b"\r" in canonical:
        raise ValueError("unapproved source line ending")
    return hashlib.sha256(canonical).hexdigest()


def approved_migration_digest(raw):
    approved = {
        "86f154d10c7cd14ca51aae9327982c80f60945f59820ccda1769ca777f510f6d",
        "fb8af73ebd92986efb2eb448db105cb755f2d77da301d2ba70ff39fbf2059608",
    }
    digest = hashlib.sha256(raw).hexdigest()
    if (
        digest not in approved
        or canonical_digest(raw)
        != "fb8af73ebd92986efb2eb448db105cb755f2d77da301d2ba70ff39fbf2059608"
    ):
        raise ValueError("unapproved migration source")
    return digest


def fixture_png():
    """A valid synthetic 1234 challenge, replacing the protocol-only magic bytes."""
    import struct
    import zlib

    glyphs = [
        "010110010010111",
        "110001010100111",
        "110001010001110",
        "101101111001001",
    ]
    width, height = 100, 40
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            digit, column = divmod(x - 10, 22)
            gy = (y - 5) // 6
            gx = column // 6
            ink = (
                0 <= digit < 4
                and 0 <= gx < 3
                and 0 <= gy < 5
                and glyphs[digit][gy * 3 + gx] == "1"
            )
            row.extend((32, 32, 32) if ink else (245, 245, 245))
        rows.append(bytes(row))

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def source_snapshot():
    paths = []
    for prefix in (
        "apps/web/src",
        "packages/core/src",
        "packages/contracts/src",
        "packages/contracts/generated",
        "services/api/src",
        "services/tvt-bridge/src",
        "infra/migrations",
    ):
        paths += [
            p
            for p in (ROOT / prefix).rglob("*")
            if p.suffix in {".py", ".ts", ".tsx", ".css", ".json"}
            and "__pycache__" not in p.parts
            and not p.name.startswith("0008")
        ]
    paths += [
        ROOT / p
        for p in (
            "uv.lock",
            "pnpm-lock.yaml",
            "package.json",
            "apps/web/package.json",
            "packages/core/pyproject.toml",
            "tests/contract/test_account_web_fixture.py",
            "docs/integrations/tvt-account-browser-fixture.md",
            ".github/workflows/account-browser.yml",
            "scripts/dev/provision-ci-postgres.py",
            "tests/integration/test_tvt_account_rpc.py",
            "tests/integration/test_tvt_sessions.py",
            "tests/integration/test_tvt_domain_scope.py",
            "tests/support/job_handlers.py",
            "tests/tvt_parity/test_bridge_mtls.py",
            "tests/tvt_parity/e2e/login.spec.ts",
            "scripts/test-tvt-account/runtime.py",
            "scripts/test-tvt-account/server.mjs",
            "playwright.tvt-account.config.ts",
        )
    ]
    return {
        p.relative_to(ROOT).as_posix(): {
            "raw_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "canonical_lf_sha256": canonical_digest(p.read_bytes()),
        }
        for p in sorted(paths)
        if p.is_file()
    }


def private_directory(path, *, existing=False):
    if existing:
        if not path.is_dir() or path.is_symlink() or path.is_junction():
            raise ValueError("private directory ownership")
        path.chmod(0o700)
    else:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    if os.name == "nt":
        result = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            check=True,
            timeout=5,
        )
        import re

        sid = re.search(rb"S-1-[0-9-]+", result.stdout).group().decode("ascii")
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            capture_output=True,
            check=True,
            timeout=5,
        )


def write_private(path, value):
    raw = (json.dumps(value, indent=2) + "\n").encode()
    if len(raw) > 65536:
        raise ValueError("private context must be bounded")
    if (
        path.is_symlink()
        or path.is_junction()
        or path.parent.is_symlink()
        or path.parent.is_junction()
    ):
        raise ValueError("private path ownership")
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_owned(folder, owner):
    if folder.is_symlink() or json.loads((folder / "owner.json").read_text()) != {
        "owner": owner
    }:
        raise ValueError("private folder ownership mismatch")
    resolved = folder.resolve(strict=True)
    if resolved.parent != folder.parent.resolve() or resolved == ROOT:
        raise ValueError("private folder ownership mismatch")
    shutil.rmtree(resolved)


def parse_control(raw):
    if len(raw) > 256:
        raise ValueError("invalid control")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"op", "sequence"}
        or value["op"] != "session"
        or type(value["sequence"]) is not int
        or not 1 <= value["sequence"] <= 100
    ):
        raise ValueError("invalid control")
    return value["sequence"]


class AdmissionGate:
    """Private cross-process gate; transactions never span application work."""

    def __init__(self, path, *, create=False):
        self.path = path
        if create:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            with self.transaction() as db:
                db.execute(
                    "CREATE TABLE gate (closed INTEGER, api INTEGER, worker INTEGER)"
                )
                db.execute("INSERT INTO gate VALUES (0,0,0)")
        elif not path.is_file() or path.is_symlink():
            raise ValueError("private gate missing")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        finally:
            db.close()

    def enter(self, kind):
        if kind not in {"api", "worker"}:
            raise ValueError("invalid admission kind")
        with self.transaction() as db:
            if db.execute("SELECT closed FROM gate").fetchone()[0]:
                return False
            db.execute(f"UPDATE gate SET {kind}={kind}+1")
            return True

    def leave(self, kind):
        if kind not in {"api", "worker"}:
            raise ValueError("invalid admission kind")
        with self.transaction() as db:
            assert db.execute(f"SELECT {kind} FROM gate").fetchone()[0] > 0
            db.execute(f"UPDATE gate SET {kind}={kind}-1")

    @contextmanager
    def frozen(self):
        with self.transaction() as db:
            closed, api, worker = db.execute("SELECT * FROM gate").fetchone()
            if closed:
                raise ValueError("admission already frozen")
            db.execute("UPDATE gate SET closed=1")
        try:
            yield api, worker
        finally:
            with self.transaction() as db:
                db.execute("UPDATE gate SET closed=0")


def rotate_when_settled(gate, authority, rotate):
    # Freeze BOTH admissions before checking any counts, keep the freeze through
    # revoke/create. Existing calls may still leave: no lock is held over work.
    with gate.frozen() as (api, worker):
        if api or worker or any(authority()):
            raise ValueError("control requires settled logged-out scenario")
        rotate()


class GuardedApplication:
    def __init__(self, app, gate):
        self.app, self.gate = app, gate

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if not self.gate.enter("api"):
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [(b"cache-control", b"no-store")],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self.gate.leave("api")


def guard_worker_execute(original, gate):
    def guarded(service, request, context, *args, **kwargs):
        if not gate.enter("worker"):
            import grpc

            return context.abort(
                grpc.StatusCode.UNAVAILABLE, "fixture admission closed"
            )
        try:
            return original(service, request, context, *args, **kwargs)
        finally:
            gate.leave("worker")

    return guarded


def worker_process(folder, gate_path):
    # Instrument admission/settlement only. Accepted serve still creates the
    # concrete server/executor/vault/client, R53 trust hook and drain receipt.
    from wso_tvt_bridge.server import _Service

    from tests.integration import test_tvt_account_rpc as accepted

    gate = AdmissionGate(gate_path)
    original = _Service._execute
    _Service._execute = guard_worker_execute(original, gate)
    try:
        accepted.serve(folder)
    finally:
        _Service._execute = original


def wait_file(path, process, deadline):
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("owned child exited before readiness")
        if path.is_file():
            return
        time.sleep(0.025)
    raise TimeoutError("owned child readiness deadline")


def child_environment():
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("WSO_", "PG", "DATABASE", "NODE_"))
        and k not in {"SSL_CERT_FILE", "SSL_CERT_DIR"}
    }


def spawn_python(arguments, environment):
    executable = sys._base_executable if os.name == "nt" else sys.executable
    import sysconfig

    site_directory = sysconfig.get_paths()["purelib"]
    launch = f"import site,runpy,sys;site.addsitedir({site_directory!r});sys.path.insert(0,{str(ROOT)!r});sys.argv={([str(Path(__file__).resolve())] + arguments)!r};runpy.run_path(sys.argv[0],run_name='__main__')"
    return subprocess.Popen(
        [executable, "-c", launch],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def stop_child(process):
    if process.poll() is None:
        try:
            process.communicate(b"close\n", timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
    return process.returncode


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
    from wso_api.main import create_app
    from wso_api.tvt.session_service import AccountWorkerExecutor
    from wso_core.secrets import FileKeyProvider
    from wso_core.tvt.token_vault import TokenVault

    def forbidden(*args, **kwargs):
        raise RuntimeError("API worker capability forbidden")

    FileKeyProvider.encryption_key = forbidden
    TokenVault.__init__ = forbidden
    AccountWorkerExecutor.__init__ = forbidden
    assert not any(
        os.getenv(k)
        for k in (
            "WSO_WORKER_DATABASE_URL",
            "WSO_CONNECTION_KEY_FILE",
            "WSO_TVT_ACCOUNT_PROFILE_FILE",
        )
    )
    settings = AuthSettings.from_environment()
    app = create_app()
    engines = {
        role: create_engine(
            os.environ[f"WSO_{role}_DATABASE_URL"], hide_parameters=True
        )
        for role in ("APP", "IDENTITY", "SESSION")
    }
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
            GuardedApplication(app, AdmissionGate(folder / "admission.sqlite")),
            log_config=None,
            log_level="critical",
            access_log=False,
            ssl_certfile=str(folder / "api.pem"),
            ssl_keyfile=str(folder / "api.key"),
            timeout_graceful_shutdown=5,
        )
    )

    def shutdown():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=shutdown, daemon=True).start()
    write_private(
        folder / "api-port.json",
        {"port": listener.getsockname()[1], "pid": os.getpid()},
    )
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        for engine in engines.values():
            engine.dispose()


def profile(origin):
    from wso_core.tvt.startup import APK_SHA256, StartupProfile

    return StartupProfile.model_validate(
        {
            "profile_id": "browser-fixture",
            "source_apk_sha256": APK_SHA256,
            "brand": "SuperLivePlus",
            "region": "test",
            "consent_version": "fixture-v1",
            "default_locale": "en",
            "default_timezone": "UTC",
            "supported_locales": ["en", "zh"],
            "terms": {
                "source_reference": "agreement/ServiceTerms_en.html",
                "url": origin + "/tvt/policies/en/terms",
            },
            "privacy": {
                "source_reference": "agreement/PrivacyStatement_en.html",
                "url": origin + "/tvt/policies/en/privacy",
            },
            "local_routes": ["/tvt/settings", "/tvt/account"],
        }
    ).model_dump_json()


def coordinate():
    import pytest
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from wso_api.auth import PostgresSessionStore, WebSession, token_digest

    from tests.integration import test_tvt_account_rpc as accepted
    from tests.tvt_parity.test_bridge_mtls import certs

    path = Path(os.environ["WSO_TVT_ACCOUNT_BROWSER_STATE_FILE"])
    if (
        not path.is_absolute()
        or path.name != "context.json"
        or not path.parent.name.startswith("tvt-account-")
        or path.parent.parent.resolve() != (ROOT / "auth-state").resolve()
    ):
        raise ValueError("explicit owned private context path required")
    folder = path.parent
    owner = secrets.token_hex(16)
    output = os.environ.get("WSO_TVT_ACCOUNT_BROWSER_OUTPUT")
    if output:
        captures = Path(output)
        if (
            not captures.is_absolute()
            or captures.parent.resolve() != (ROOT / "auth-state").resolve()
            or not captures.name.startswith("tvt-account-captures-")
        ):
            raise ValueError("explicit private capture directory required")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    sources = source_snapshot()
    for source, expected in {
        "tests/integration/test_tvt_account_rpc.py": "e6acb9b4bf862b722a60ee96e1ca93cbf5e6f08e0e6e779bbeacb8acca34b0df",
        "tests/tvt_parity/test_bridge_mtls.py": "c28624e5dcbc871a0fc76126cd5bd1d9dfeb04087c9281c05fd3e95ddeb8aeb5",
        "services/api/src/wso_api/main.py": "3a4f030701e8a032718ae85b029b38bec2e4c13a805ce84d11a49ba8a10c76c3",
        "infra/migrations/versions/0007_tvt_account_sessions.py": "fb8af73ebd92986efb2eb448db105cb755f2d77da301d2ba70ff39fbf2059608",
    }.items():
        if sources.get(source, {}).get("canonical_lf_sha256") != expected:
            raise ValueError("accepted runtime source guard mismatch")
    private_directory(folder)
    write_private(folder / "owner.json", {"owner": owner})
    gate = AdmissionGate(folder / "admission.sqlite", create=True)
    (EVIDENCE / ("browser-source-" + owner + ".json")).write_text(
        json.dumps(sources, indent=2) + "\n"
    )
    # The accepted test-only generators retain every database ownership guard.
    # Only receipt destination and mkdtemp directory privacy are adapted here.
    process = None
    result = {"context_removed": False, "api_settled": False}
    stopped = threading.Event()
    threading.Thread(
        target=lambda: (sys.stdin.readline(), stopped.set()), daemon=True
    ).start()
    try:
        if output:
            private_directory(captures)
        with ExitStack() as stack:
            patch = stack.enter_context(pytest.MonkeyPatch.context())
            patch.setattr(accepted, "EVIDENCE", EVIDENCE)
            patch.setenv("WSO_TEST_ACCOUNT_RPC_RUNTIME", "1")
            # R58: two controller-approved raw EOL representations only. The
            # accepted generator's raw-byte assertion and all DB guards remain.
            migration = ROOT / "infra/migrations/versions/0007_tvt_account_sessions.py"
            patch.setattr(
                accepted,
                "MIGRATION_SHA",
                approved_migration_digest(migration.read_bytes()),
            )
            protocol_image = b"\x89PNG\r\n\x1a\nfixtureIEND\xaeB`\x82"
            patch.setattr(
                accepted,
                "base64",
                SimpleNamespace(
                    b64encode=lambda value: base64.b64encode(
                        fixture_png() if value == protocol_image else value
                    )
                ),
            )
            original_mkdtemp = accepted.tempfile.mkdtemp

            def secured_mkdtemp(*args, **kwargs):
                created = Path(original_mkdtemp(*args, **kwargs))
                # Secure before the accepted generator writes certificates/keys.
                private_directory(created, existing=True)
                return str(created)

            patch.setattr(accepted.tempfile, "mkdtemp", secured_mkdtemp)
            database = stack.enter_context(
                contextmanager(accepted.runtime_db.__wrapped__)()
            )

            def guarded_worker_popen(arguments, **kwargs):
                # Narrowly adapt this reviewed helper's one owned worker launch.
                expected = "from pathlib import Path;from tests.integration.test_tvt_account_rpc import serve;import sys;serve(Path(sys.argv[1]))"
                if (
                    len(arguments) != 4
                    or arguments[1] != "-c"
                    or expected not in arguments[2]
                ):
                    raise ValueError("unexpected accepted worker launch")
                launch = arguments[2].split(expected)[0] + (
                    f"import runpy,sys;sys.path.insert(0,{str(ROOT)!r});"
                    f"sys.argv={[str(Path(__file__).resolve()), '--worker', arguments[3], str(folder / 'admission.sqlite')]!r};"
                    "runpy.run_path(sys.argv[0],run_name='__main__')"
                )
                kwargs["env"] = kwargs["env"] | {"WSO_TEST_ACCOUNT_BROWSER": "1"}
                return subprocess.Popen([arguments[0], "-c", launch], **kwargs)

            patch.setattr(
                accepted,
                "subprocess",
                SimpleNamespace(
                    Popen=guarded_worker_popen,
                    PIPE=subprocess.PIPE,
                    DEVNULL=subprocess.DEVNULL,
                    TimeoutExpired=subprocess.TimeoutExpired,
                    CREATE_NO_WINDOW=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ),
            )
            upstream = stack.enter_context(
                contextmanager(accepted.runtime.__wrapped__)(
                    database, patch, SimpleNamespace(param=None)
                )
            )
            engines, ids = database
            certs(folder)
            shutil.copyfile(folder / "server.pem", folder / "api.pem")
            shutil.copyfile(folder / "server.key", folder / "api.key")
            origin = os.environ.get(
                "WSO_TVT_ACCOUNT_BROWSER_ORIGIN", "https://localhost:3543"
            )
            if origin != "https://localhost:3543":
                raise ValueError("fixture origin is fixed")
            env = child_environment() | {
                "WSO_TEST_ACCOUNT_BROWSER": "1",
                "WSO_OIDC_ISSUER": "https://w02.test",
                "WSO_OIDC_CLIENT_ID": "fixture-web",
                "WSO_OIDC_JWKS_URL": "https://w02.test/keys",
                "WSO_AUTH_EXCHANGE_KEY": secrets.token_urlsafe(48),
                "WSO_PUBLIC_ORIGIN": origin,
                "WSO_TVT_STARTUP_PROFILE": profile(origin),
            }
            for role in ("APP", "IDENTITY", "SESSION"):
                env[f"WSO_{role}_DATABASE_URL"] = engines[role].url.render_as_string(
                    hide_password=False
                )
            for key in ("ENDPOINT", "CA_FILE", "CLIENT_CERT_FILE", "CLIENT_KEY_FILE"):
                env["WSO_TVT_BRIDGE_" + key] = os.environ["WSO_TVT_BRIDGE_" + key]
            process = spawn_python(["--api", str(folder)], env)
            result["api_pid"] = process.pid
            wait_file(folder / "api-port.json", process, time.monotonic() + 15)
            announcement = json.loads((folder / "api-port.json").read_text())
            assert announcement["pid"] == process.pid
            api_origin = f"https://localhost:{announcement['port']}"
            tls = ssl.create_default_context(cafile=str(folder / "ca.pem"))
            end = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise RuntimeError("owned API child exited")
                try:
                    with urlopen(
                        api_origin + "/health/live", context=tls, timeout=1
                    ) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if time.monotonic() >= end:
                        raise TimeoutError("owned API readiness deadline") from None
                    time.sleep(0.05)
            sessions = PostgresSessionStore(
                env["WSO_SESSION_DATABASE_URL"],
                session_factory=sessionmaker(engines["SESSION"]),
            )
            state = {
                "schemaVersion": 1,
                "proofKind": "actual-pg-rpc-https",
                "baseURL": origin,
                "apiOrigin": api_origin,
                "caFile": str(folder / "ca.pem"),
                "certificateFile": str(folder / "server.pem"),
                "keyFile": str(folder / "server.key"),
                "tenantId": str(ids["tenant"]),
                "otherTenantId": str(ids["other_tenant"]),
                "userId": str(ids["staff"]),
                "account": {
                    "email": "person@example.test",
                    "phone": "+12345678",
                    "password": "synthetic-password",
                    "imageCode": "1234",
                    "secondCode": "5678",
                },
                "expectedProfile": {
                    "userName": None,
                    "nickname": "Fixture",
                    "accountType": 4,
                },
                "controlFile": str(folder / "control.json"),
                "sequence": 0,
            }
            current = None

            def fresh_session(sequence):
                nonlocal current
                if current:
                    assert sessions.revoke(
                        token_digest(current[0]), token_digest(current[1])
                    )
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                expires = datetime.now(UTC) + timedelta(seconds=600)
                assert sessions.create(
                    token_digest(token),
                    WebSession(
                        "https://w02.test",
                        str(ids["staff"]),
                        ids["staff"],
                        token_digest(csrf),
                        expires,
                    ),
                    token_digest(secrets.token_urlsafe(32)),
                )
                current = (token, csrf)
                state.update(
                    sequence=sequence,
                    expiresAt=expires.isoformat(),
                    csrfToken=csrf,
                    cookies=[
                        {
                            "name": "__Host-wso-session",
                            "value": token,
                            "url": origin,
                            "httpOnly": True,
                            "secure": True,
                            "sameSite": "Lax",
                            "expires": expires.timestamp(),
                        },
                        {
                            "name": "__Host-wso-csrf",
                            "value": csrf,
                            "url": origin,
                            "httpOnly": False,
                            "secure": True,
                            "sameSite": "Strict",
                            "expires": expires.timestamp(),
                        },
                    ],
                )
                write_private(path, state)

            fresh_session(0)
            try:
                while not stopped.wait(0.05):
                    if process.poll() is not None:
                        raise RuntimeError("owned API child exited")
                    control = folder / "control.json"
                    if control.exists():
                        with control.open("rb") as stream:
                            sequence = parse_control(stream.read(257))
                        control.unlink()
                        if sequence != state["sequence"] + 1:
                            raise ValueError("control sequence mismatch")

                        def authority():
                            with engines["ADMIN"].connect() as db:
                                return db.execute(
                                    text(
                                        "SELECT (SELECT count(*) FROM wso_private.tvt_account_sessions WHERE state NOT IN ('CLOSED','FAILED')), "
                                        "(SELECT count(*) FROM wso_private.tvt_account_tickets WHERE expires_at>clock_timestamp())"
                                    )
                                ).one()

                        rotate_when_settled(
                            gate,
                            authority,
                            lambda sequence=sequence: fresh_session(sequence),
                        )
            finally:
                if current:
                    sessions.revoke(token_digest(current[0]), token_digest(current[1]))
                result["api_exit_code"] = stop_child(process)
                result["api_settled"] = process.poll() is not None
                result["decoded_paths"] = sorted(set(upstream.paths))
                result["decoded_requests"] = len(upstream.paths)
                result["upstream_errors"] = len(upstream.errors)
                with engines["ADMIN"].connect() as db:
                    result["account_session_states"] = dict(
                        db.execute(
                            text(
                                "SELECT state,count(*) FROM wso_private.tvt_account_sessions GROUP BY state"
                            )
                        ).all()
                    )
                    result["encrypted_account_secret_rows"] = db.execute(
                        text(
                            "SELECT count(*) FROM wso_private.connection_secrets s JOIN wso_private.tvt_account_tokens t USING(connection_id)"
                        )
                    ).scalar_one()
                    result["token_generations"] = list(
                        db.execute(
                            text(
                                "SELECT DISTINCT generation FROM wso_private.tvt_account_tokens ORDER BY generation"
                            )
                        ).scalars()
                    )
                    result["target_revision"] = db.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one()
    finally:
        if process is not None and process.poll() is None:
            stop_child(process)
        remove_owned(folder, owner)
        result["context_removed"] = not folder.exists()
        final_sources = source_snapshot()
        dependency_paths = {"uv.lock", "packages/core/pyproject.toml"}
        result["dependency_changes"] = sorted(
            p for p in dependency_paths if sources.get(p) != final_sources.get(p)
        )
        result["source_unchanged"] = final_sources == sources
        result["implementation_unchanged"] = {
            p: v for p, v in final_sources.items() if p not in dependency_paths
        } == {p: v for p, v in sources.items() if p not in dependency_paths}
        (EVIDENCE / ("browser-source-final-" + owner + ".json")).write_text(
            json.dumps(final_sources, indent=2) + "\n"
        )
        (EVIDENCE / ("browser-resources-" + owner + ".json")).write_text(
            json.dumps(result, indent=2) + "\n"
        )
        if not result["implementation_unchanged"]:
            raise RuntimeError("browser source changed during proof")


def main():
    if os.environ.get("WSO_TEST_ACCOUNT_BROWSER") != "1":
        print("Account browser fixture requires explicit activation.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(ROOT))
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        worker_process(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--api":
        api_process(Path(sys.argv[2]))
    else:
        coordinate()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - never disclose private failure values
        # Never emit exception values, connection strings, payloads or tracebacks.
        import traceback

        frames = traceback.extract_tb(error.__traceback__)
        print(
            "Account browser fixture failed ("
            + type(error).__name__
            + "; "
            + ",".join(
                Path(frame.filename).name + ":" + str(frame.lineno) for frame in frames
            )
            + ").",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
