"""Explicit opt-in owned PostgreSQL -> API -> mTLS -> concrete worker -> HTTPS.

All upstream data is synthetic. No vendor, device, APK or Linux acceptance.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import grpc
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from wso_core.tvt.account_projection import AccountFailure

from tests.integration.test_tvt_domain_scope import seed_foundation
from tests.integration.test_tvt_sessions import foundation_contents, issue
from tests.support.job_handlers import verify_fixture_database
from tests.tvt_parity.test_bridge_mtls import certs

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT
    / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W05-account-api-runtime-evidence"
)
MIGRATION_SHA = "86f154d10c7cd14ca51aae9327982c80f60945f59820ccda1769ca777f510f6d"
MIGRATION_LF_SHA = "fb8af73ebd92986efb2eb448db105cb755f2d77da301d2ba70ff39fbf2059608"


def verify_migration_source(source: bytes) -> None:
    assert hashlib.sha256(source).hexdigest() in {MIGRATION_SHA, MIGRATION_LF_SHA}
    canonical = source.replace(b"\r\n", b"\n")
    assert b"\r" not in canonical
    assert hashlib.sha256(canonical).hexdigest() == MIGRATION_LF_SHA


def receipt(name, value):
    if EVIDENCE.exists():
        (EVIDENCE / name).write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )


@pytest.fixture(scope="module")
def runtime_db():
    if os.getenv("WSO_TEST_ACCOUNT_RPC_RUNTIME") != "1":
        pytest.skip("requires explicit owned account RPC runtime activation")
    verify_migration_source(
        (ROOT / "infra/migrations/versions/0007_tvt_account_sessions.py").read_bytes()
    )
    roles = ("ADMIN", "APP", "IDENTITY", "MIGRATOR", "SESSION", "WORKER")
    assert all(os.getenv(f"WSO_TEST_{role}_DATABASE_URL") for role in roles)
    urls = {
        role: make_url(os.environ[f"WSO_TEST_{role}_DATABASE_URL"]) for role in roles
    }
    bounds = {
        "connect_timeout": 5,
        "options": "-c statement_timeout=10000 -c lock_timeout=3000",
    }
    source = create_engine(urls["ADMIN"], hide_parameters=True, connect_args=bounds)
    control = None
    engines = {}
    identity = None
    name = "w05_rpc_" + uuid4().hex
    marker = "owned-w05-rpc-" + uuid4().hex
    result = {
        "name": name,
        "marker": marker,
        "cleanup": False,
        "source_unchanged": False,
    }
    source_rows = None
    try:
        verify_fixture_database(source, domain_only=sys.platform == "win32")
        with source.connect() as db:
            source_rows = foundation_contents(db)
            source_identity = db.execute(
                text(
                    "SELECT oid,datdba,shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"
                )
            ).one()
        for url in urls.values():
            assert (url.drivername, url.host, url.port, url.database) == (
                urls["ADMIN"].drivername,
                urls["ADMIN"].host,
                urls["ADMIN"].port,
                urls["ADMIN"].database,
            )
        control = create_engine(
            urls["ADMIN"].set(database="postgres"),
            isolation_level="AUTOCOMMIT",
            hide_parameters=True,
            connect_args=bounds,
        )
        with control.connect() as db:
            assert (
                db.execute(text("SHOW server_version_num"))
                .scalar_one()
                .startswith("17")
            )
            assert re.fullmatch(r"w05_rpc_[0-9a-f]{32}", name)
            assert (
                db.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname=:n"),
                    {"n": name},
                ).scalar_one()
                == 0
            )
            db.execute(
                text(f'CREATE DATABASE "{name}" OWNER wso_migrator TEMPLATE template0')
            )
            db.execute(text(f"COMMENT ON DATABASE \"{name}\" IS '{marker}'"))
            identity = db.execute(
                text(
                    "SELECT oid,datdba,pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:n"
                ),
                {"n": name},
            ).one()
            assert identity[2:] == ("wso_migrator", marker)
            result.update(oid=identity[0], owner_oid=identity[1], owner=identity[2])
        engines = {
            role: create_engine(
                url.set(database=name), hide_parameters=True, connect_args=bounds
            )
            for role, url in urls.items()
        }
        config = Config(str(ROOT / "infra/alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            urls["ADMIN"]
            .set(database=name)
            .render_as_string(hide_password=False)
            .replace("%", "%%"),
        )
        command.upgrade(config, "0007_tvt_account_sessions")
        with engines["ADMIN"].connect() as db:
            assert (
                db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0007_tvt_account_sessions"
            )
        yield engines, seed_foundation(engines["ADMIN"])
    finally:
        for engine in engines.values():
            engine.dispose()
        if control is not None:
            try:
                if identity is not None:
                    verify_fixture_database(source, domain_only=sys.platform == "win32")
                    with control.connect() as db:
                        current = db.execute(
                            text(
                                "SELECT oid,datdba,pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:n"
                            ),
                            {"n": name},
                        ).one()
                        assert current == identity
                        db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
                        assert (
                            db.execute(
                                text(
                                    "SELECT count(*) FROM pg_database WHERE datname=:n"
                                ),
                                {"n": name},
                            ).scalar_one()
                            == 0
                        )
                        result["cleanup"] = True
            finally:
                control.dispose()
        if source_rows is not None:
            with source.connect() as db:
                assert foundation_contents(db) == source_rows
                assert (
                    db.execute(
                        text(
                            "SELECT oid,datdba,shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"
                        )
                    ).one()
                    == source_identity
                )
                result["source_unchanged"] = True
        source.dispose()
        receipt(f"database-{name}.json", result)


class Upstream:
    def __init__(self, folder):
        self.paths = []
        self.errors = []
        self.delay_login = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    request = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    )
                    basic = request["basic"]
                    assert set(basic) in (
                        {"ver", "id", "time", "nonce"},
                        {"ver", "id", "time", "nonce", "token"},
                    )
                    assert basic["id"].isdigit() and int(basic["id"]) >= 1
                    assert 100_000_000 <= basic["nonce"] <= 999_999_999
                    assert abs(time.time() - basic["time"]) < 30
                    data = request.get("data", {})
                    path = self.path.removeprefix("/mobile_v1.0")
                    if path == "/user/login":
                        from wso_core.tvt.account_protocol import _proof

                        assert basic["ver"] == "1.1"
                        assert (
                            data["type"] == 1
                            and data["userName"] == "person@example.test"
                        )
                        assert (
                            data["lang"] == "en"
                            and data["country"] == "US"
                            and data["appVersion"] == "1.18.1"
                        )
                        assert data["password"] == _proof(
                            "person@example.test",
                            "synthetic-password",
                            basic["nonce"],
                            basic["time"],
                        )
                        assert re.fullmatch("[0-9a-f]{128}", data["uuid"])
                        assert (
                            data["customerAppId"] == "fixture-app"
                            and data["customerMark"] == "fixture-mark"
                        )
                        if "imgCode" in data:
                            assert (
                                data["idCode"] == "synthetic-image-id"
                                and data["imgCode"] == "1234"
                            )
                        result = {
                            "token": "synthetic-user-token",
                            "p2pId": "synthetic-p2p-token",
                        }
                        if outer.delay_login:
                            outer.entered.set()
                            assert outer.release.wait(15)
                    elif path == "/user/img-code/get":
                        assert basic["ver"] == "1.0" and data == {
                            "customerAppId": "fixture-app"
                        }
                        result = {
                            "idCode": "synthetic-image-id",
                            "imgCodeImgData": base64.b64encode(
                                b"\x89PNG\r\n\x1a\nfixtureIEND\xaeB`\x82"
                            ).decode(),
                        }
                    elif path == "/user/img-code/check":
                        assert basic["ver"] == "1.0" and data == {
                            "idCode": "synthetic-image-id",
                            "imgCode": "1234",
                            "customerAppId": "fixture-app",
                        }
                        result = {}
                    else:
                        assert basic["token"] == "synthetic-user-token" and not data
                        assert basic["ver"] == (
                            "1.1" if path == "/user/token/renewal" else "1.0"
                        )
                        assert path in {
                            "/user/info/get",
                            "/user/token/renewal",
                            "/user/logout",
                        }
                        result = (
                            {
                                "userId": "private-user",
                                "type": 4,
                                "nickName": "Fixture",
                                "image": "/private-avatar",
                            }
                            if path == "/user/info/get"
                            else {}
                        )
                    outer.paths.append(path)
                    payload = json.dumps(
                        {"basic": {"msgcode": 200}, "data": result}
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                    pass
                except Exception:  # noqa: BLE001 - retain no decoded credentials
                    outer.errors.append("decoded request rejected")
                    self.send_error(500)
                finally:
                    outer.finished.set()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(folder / "server.pem", folder / "server.key")
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"https://localhost:{self.server.server_port}/mobile_v1.0"

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        assert not self.thread.is_alive()
        assert not self.errors


def serve(folder):
    # Fixture-only explicit trust hook: child transport otherwise deliberately
    # discards every CA override. No hostname check or certificate check disabled.
    from wso_core.tvt import account_process

    environment = account_process._environment
    ca_path = (folder / "upstream-ca.pem").resolve()
    assert ca_path.parent == folder.resolve() and ca_path.is_file()

    def trusted_environment():
        original = environment()
        assert "SSL_CERT_FILE" not in original
        result = original | {"SSL_CERT_FILE": str(ca_path)}
        assert set(result) - set(original) == {"SSL_CERT_FILE"}
        assert all(result[k] == v for k, v in original.items())
        return result

    account_process._environment = trusted_environment
    from wso_tvt_bridge.server import create_server_from_environment

    server = create_server_from_environment()
    try:
        (folder / "worker-pid").write_text(str(os.getpid()), encoding="utf-8")
        (folder / "port").write_text(str(server.start()), encoding="utf-8")
        sys.stdin.readline()
    finally:
        drained = server.close(grace=3)
        (folder / "closed").write_text(
            json.dumps({"drained": drained}), encoding="utf-8"
        )


@pytest.fixture
def runtime(runtime_db, monkeypatch, request):
    from scripts.dev.write_tvt_account_profile import write_profile

    folder = Path(tempfile.mkdtemp(prefix="w05-account-rpc-")).resolve()
    upstream = None
    process = None
    result = {
        "directory": str(folder),
        "certificates_removed": False,
        "process_settled": False,
    }
    try:
        certs(folder)
        upstream = Upstream(folder)
        tls_case = getattr(request, "param", None)
        if tls_case == "wrong-ca":
            other = folder / "other-ca"
            other.mkdir()
            certs(other)
            shutil.copyfile(other / "ca.pem", folder / "upstream-ca.pem")
        else:
            shutil.copyfile(folder / "ca.pem", folder / "upstream-ca.pem")
        origin = (
            upstream.origin.replace("localhost", "127.0.0.1")
            if tls_case == "wrong-host"
            else upstream.origin
        )
        write_profile(
            folder,
            "profile.json",
            [
                {
                    "region": "test",
                    "brand": "SuperLivePlus",
                    "origin": origin,
                    "language": "en",
                    "country": "US",
                    "app_version": "1.18.1",
                    "customer_app_id": "fixture-app",
                    "customer_mark": "fixture-mark",
                }
            ],
        )
        (folder / "vault.key").write_bytes(os.urandom(32))
        worker_env = {
            k: v for k, v in os.environ.items() if not k.startswith(("WSO_", "PG"))
        }
        worker_env.update(
            WSO_WORKER_DATABASE_URL=runtime_db[0]["WORKER"].url.render_as_string(
                hide_password=False
            ),
            WSO_CONNECTION_KEY_FILE=str(folder / "vault.key"),
            WSO_TVT_ACCOUNT_PROFILE_FILE=str(folder / "profile.json"),
            WSO_TVT_BRIDGE_BIND="localhost:0",
            WSO_TVT_BRIDGE_CA_FILE=str(folder / "ca.pem"),
            WSO_TVT_BRIDGE_SERVER_CERT_FILE=str(folder / "server.pem"),
            WSO_TVT_BRIDGE_SERVER_KEY_FILE=str(folder / "server.key"),
            WSO_TVT_BRIDGE_CLIENT_SANS_JSON='["api.test"]',
        )
        executable = sys._base_executable if os.name == "nt" else sys.executable
        launch = (
            f"import site;site.addsitedir({str(Path(sys.prefix) / ('Lib/site-packages' if os.name == 'nt' else 'lib/python3.12/site-packages'))!r});"
            "from pathlib import Path;from tests.integration.test_tvt_account_rpc import serve;import sys;serve(Path(sys.argv[1]))"
        )
        process = subprocess.Popen(
            [executable, "-c", launch, str(folder)],
            cwd=ROOT,
            env=worker_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        result["pid"] = process.pid
        end = time.monotonic() + 15
        while (
            not (folder / "port").exists()
            and time.monotonic() < end
            and process.poll() is None
        ):
            time.sleep(0.025)
        assert (folder / "port").exists(), "owned worker did not start"
        assert int((folder / "worker-pid").read_text()) == process.pid

        def stop_worker():
            if process.poll() is None:
                process.communicate(b"close\n", timeout=15)
            assert process.returncode == 0
            assert json.loads((folder / "closed").read_text())["drained"]

        upstream.stop_worker = stop_worker
        for name in (
            "WSO_WORKER_DATABASE_URL",
            "WSO_CONNECTION_KEY_FILE",
            "WSO_TVT_ACCOUNT_PROFILE_FILE",
        ):
            monkeypatch.delenv(name, raising=False)
        for name, value in {
            "WSO_TVT_BRIDGE_ENDPOINT": "localhost:" + (folder / "port").read_text(),
            "WSO_TVT_BRIDGE_CA_FILE": str(folder / "ca.pem"),
            "WSO_TVT_BRIDGE_CLIENT_CERT_FILE": str(folder / "client.pem"),
            "WSO_TVT_BRIDGE_CLIENT_KEY_FILE": str(folder / "client.key"),
        }.items():
            monkeypatch.setenv(name, value)
        yield upstream
    finally:
        try:
            try:
                if upstream is not None:
                    upstream.release.set()
                if process is not None:
                    try:
                        if process.poll() is None:
                            process.communicate(b"close\n", timeout=15)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=5)
                    result["process_settled"] = process.poll() is not None
                    result["exit_code"] = process.returncode
                    if (folder / "closed").exists():
                        result.update(json.loads((folder / "closed").read_text()))
            finally:
                if upstream is not None:
                    upstream.close()
        finally:
            assert (
                folder.name.startswith("w05-account-rpc-")
                and folder.parent == Path(tempfile.gettempdir()).resolve()
            )
            shutil.rmtree(folder)
            result["certificates_removed"] = not folder.exists()
            receipt("resources-" + uuid4().hex + ".json", result)
        if process is not None:
            assert (
                result["process_settled"]
                and result["exit_code"] == 0
                and result.get("drained")
            )


@contextmanager
def api(runtime_db, actor="staff"):
    from wso_api.auth import (
        AuthService,
        AuthSettings,
        OIDCVerifier,
        PostgresSessionStore,
        WebSession,
        token_digest,
    )
    from wso_api.main import create_app

    engines, ids = runtime_db
    settings = AuthSettings(
        issuer="https://w02.test",
        audience="wso-web",
        jwks_url="https://w02.test/keys",
        exchange_key="x" * 48,
        public_origin="https://app.test",
        session_database_url="postgresql+psycopg://wso_web_session@localhost/test",
    )
    sessions = PostgresSessionStore(
        settings.session_database_url, session_factory=sessionmaker(engines["SESSION"])
    )
    app = create_app()
    app.state.auth_service = AuthService(
        settings,
        OIDCVerifier(settings),
        sessions,
        identity_factory=sessionmaker(engines["IDENTITY"]),
        tenant_factory=sessionmaker(engines["APP"]),
    )
    with TestClient(app, base_url="https://app.test") as client:
        token = uuid4().hex
        assert sessions.create(
            token_digest(token),
            WebSession(
                "https://w02.test",
                str(ids[actor]),
                ids[actor],
                token_digest("csrf"),
                datetime.now(UTC) + timedelta(minutes=10),
            ),
            token_digest(uuid4().hex),
        )
        client.cookies.set("__Host-wso-session", token)
        yield client


def test_concrete_six_operations_sql_authority_and_web_session(
    runtime_db, runtime, monkeypatch
):
    from wso_api.tvt.session_service import AccountWorkerExecutor
    from wso_core.secrets import FileKeyProvider
    from wso_core.tvt.token_vault import TokenVault

    def forbidden(*args, **kwargs):
        pytest.fail("API constructed worker secret capability")

    monkeypatch.setattr(FileKeyProvider, "encryption_key", forbidden)
    monkeypatch.setattr(TokenVault, "__init__", forbidden)
    monkeypatch.setattr(AccountWorkerExecutor, "__init__", forbidden)
    params = {"tenant_id": str(runtime_db[1]["tenant"])}
    headers = {"Origin": "https://app.test", "X-CSRF-Token": "csrf"}
    prefix = "/api/v1/tvt/identities"
    selection = {"region": "test", "brand": "SuperLivePlus"}
    body = dict(
        selection,
        mode="email",
        account="person@example.test",
        secret="synthetic-password",
    )
    with api(runtime_db) as client:
        assert client.app.state.tvt_account_worker is not None
        assert (
            client.post(prefix + "/login", params=params, content="{bad").status_code
            == 403
        )

        def post(path, value):
            response = client.post(
                prefix + path, params=params, headers=headers, json=value
            )
            assert response.status_code == 200, (
                response.json().get("error", {}).get("code")
            )
            assert response.json()["request_id"] == response.headers["x-request-id"]
            assert response.headers["cache-control"] == "no-store"
            assert all(
                secret not in response.text
                for secret in (
                    "synthetic-user-token",
                    "synthetic-p2p-token",
                    "synthetic-password",
                    "synthetic-image-id",
                    "private-user",
                    "/private-avatar",
                )
            )
            return response.json()

        challenge = post("/challenges/image", selection)
        check = dict(
            selection, challenge_id=challenge["challenge_id"], image_code="1234"
        )
        with api(runtime_db, "owner") as wrong:
            denied = wrong.post(
                prefix + "/challenges/image/check",
                params=params,
                headers=headers,
                json=check,
            )
            assert (
                denied.status_code == 409
                and denied.json()["error"]["code"] == "CHALLENGE_EXPIRED"
            )
        assert post("/challenges/image/check", check)["checked"]
        assert (
            client.post(
                prefix + "/challenges/image/check",
                params=params,
                headers=headers,
                json=check,
            ).status_code
            == 409
        )
        fresh = post("/challenges/image", selection)
        logged = post(
            "/login", dict(body, challenge_id=fresh["challenge_id"], image_code="1234")
        )
        identity = UUID(logged["identity_id"])
        response = client.get(prefix + f"/{identity}/me", params=params)
        assert (
            response.status_code == 200
            and response.json()["profile"]["nickname"] == "Fixture"
        )
        assert response.json()["profile"]["avatar_url"] is None
        with api(runtime_db, "owner") as wrong:
            assert (
                wrong.get(prefix + f"/{identity}/me", params=params).status_code == 404
            )
        before = token_state(runtime_db, identity)
        refreshed = post(
            f"/{identity}/refresh", {"kind": "USER", "expected_generation": 1}
        )
        assert (
            refreshed["generation"] == 1 and token_state(runtime_db, identity) == before
        )
        pending = issue(runtime_db, "profile", identity, 1)
        closed = post(f"/{identity}/logout", None)
        assert closed["state"] == "CLOSED" and closed["upstream_outcome"] == "confirmed"
        with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
            client.app.state.tvt_account_worker.profile(
                pending, deadline_ms=5000, correlation_id="revoked-ticket"
            )
        assert client.get("/api/v1/me").status_code == 200
        assert client.get(prefix + f"/{identity}/me", params=params).status_code == 404
        # W05 retains inert token metadata; logout removes the encrypted bytes.
        assert token_state(runtime_db, identity) == before
        with runtime_db[0]["ADMIN"].connect() as db:
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM wso_private.connection_secrets s JOIN wso_private.tvt_account_tokens t USING(connection_id) WHERE t.identity_id=:id"
                    ),
                    {"id": identity},
                ).scalar_one()
                == 0
            )
            assert (
                db.execute(
                    text(
                        "SELECT state FROM wso_private.tvt_account_sessions WHERE identity_id=:id"
                    ),
                    {"id": identity},
                ).scalar_one()
                == "CLOSED"
            )
    assert set(runtime.paths) == {
        "/user/img-code/get",
        "/user/img-code/check",
        "/user/login",
        "/user/info/get",
        "/user/token/renewal",
        "/user/logout",
    }
    assert not runtime.errors


def token_state(runtime_db, identity):
    with runtime_db[0]["ADMIN"].connect() as db:
        return db.execute(
            text(
                "SELECT kind,version_id,generation FROM wso_private.tvt_account_tokens WHERE identity_id=:id ORDER BY kind"
            ),
            {"id": identity},
        ).all()


def test_cancelled_rpc_after_upstream_admission_cannot_publish(runtime_db, runtime):
    from wso_contracts.tvt.account import AccountLogin
    from wso_tvt_bridge.client import create_account_worker_client
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.selected import PROTOCOL_VERSION, encode_input

    runtime.delay_login = True
    with runtime_db[0]["ADMIN"].connect() as db:
        before = db.execute(
            text("SELECT count(*) FROM wso_private.tvt_account_sessions")
        ).scalar_one()
    client = create_account_worker_client()
    try:
        ticket = issue(runtime_db, "login")
        request = pb.LoginRequest(
            context=pb.RpcContext(
                protocol_version=PROTOCOL_VERSION,
                ticket=ticket,
                deadline_ms=10000,
                correlation_id="cancel-after-admission",
            ),
            account_login_json=encode_input(
                AccountLogin(
                    region="test",
                    brand="SuperLivePlus",
                    mode="email",
                    account="person@example.test",
                    secret="synthetic-password",
                )
            ),
        )
        pending = client._stub.Login.future(request, timeout=10)
        assert runtime.entered.wait(5), "owned HTTPS request did not arrive"
        assert pending.cancel()
        with pytest.raises(grpc.FutureCancelledError):
            pending.result()
        runtime.release.set()
        assert runtime.finished.wait(5)
        # Same ticket is already redeemed. A normal RPC must observe denial.
        with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
            client.login(
                ticket,
                AccountLogin(
                    region="test",
                    brand="SuperLivePlus",
                    mode="email",
                    account="person@example.test",
                    secret="synthetic-password",
                ),
                deadline_ms=5000,
                correlation_id="cancel-replay",
            )
        runtime.stop_worker()
        with runtime_db[0]["ADMIN"].connect() as db:
            assert (
                db.execute(
                    text("SELECT count(*) FROM wso_private.tvt_account_sessions")
                ).scalar_one()
                == before
            )
    finally:
        runtime.release.set()
        client.close()


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--serve":
    serve(Path(sys.argv[2]))


@pytest.mark.parametrize("runtime", ["wrong-ca", "wrong-host"], indirect=True)
def test_concrete_https_rejects_wrong_ca_and_hostname(runtime_db, runtime):
    from wso_contracts.tvt.account import AccountLogin
    from wso_tvt_bridge.client import create_account_worker_client

    with create_account_worker_client() as client, pytest.raises(AccountFailure):
        client.login(
            issue(runtime_db, "login"),
            AccountLogin(
                region="test",
                brand="SuperLivePlus",
                mode="email",
                account="person@example.test",
                secret="synthetic-password",
            ),
            deadline_ms=5000,
            correlation_id="tls-negative",
        )
    assert runtime.paths == []
    assert not runtime.errors
