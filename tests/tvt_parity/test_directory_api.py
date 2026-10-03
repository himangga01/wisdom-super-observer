"""Routing seams prove HTTP behavior, never SQL authority or APK acceptance."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from wso_api import main
from wso_api.auth import AuthService, WebSession, token_digest
from wso_contracts.tvt.directory import DirectoryView
from wso_core.tvt.account_projection import AccountFailure

TENANT = str(UUID(int=1))
FLOW = str(UUID(int=2))
ORIGIN = "https://app.example.test"
REFERENCE = {"region": "KR", "brand": "SuperLivePlus", "identity_id": FLOW}
OPERATIONS = {
    "device-list": REFERENCE,
    "channel-list": REFERENCE | {"sn_list": ["opaque-SN"]},
    "device-detail": REFERENCE | {"sn": "opaque-SN"},
    "channel-detail": REFERENCE | {"sn": "opaque-SN", "chl_index": 7},
    "sent-shares": REFERENCE,
    "received-shares": REFERENCE,
}


def subject():
    import importlib.util

    assert importlib.util.find_spec("wso_api.tvt.devices"), (
        "closed account-flow routes must exist"
    )
    from wso_api.tvt import devices

    return devices


@pytest.fixture
def setup(monkeypatch):
    module = subject()
    app = main.create_app()
    service = object.__new__(AuthService)
    service.settings = SimpleNamespace(public_origin=ORIGIN)
    principal = WebSession(
        "issuer",
        "subject",
        UUID(int=3),
        token_digest("csrf-test"),
        datetime.now(UTC) + timedelta(hours=1),
    )
    service.sessions = SimpleNamespace(
        get=lambda digest: principal if digest == token_digest("opaque-test") else None
    )
    app.state.auth_service = service
    events = []

    @contextmanager
    def tenant(permission, tenant_id, **kwargs):
        assert permission == "stores:read" and tenant_id == UUID(TENANT)
        assert kwargs == {"service": service, "principal": principal}
        events.append("begin")
        yield SimpleNamespace(session="scoped-session")
        events.append("commit")

    class Issuer:
        def __init__(self, session, remaining):
            assert session == "scoped-session" and 0 < remaining() <= 10000

        def issue(self, digest, operation, body):
            assert digest == token_digest("opaque-test")
            events.append(("issue", operation, type(body).__name__))
            return "a" * 64

    class Worker:
        def __init__(self):
            self.error = None
            self.changes = {}

        def execute(self, operation, ticket, body, **kwargs):
            assert events[-1] == "commit", (
                "issuance transaction must commit before network"
            )
            assert ticket == "a" * 64 and 0 < kwargs["deadline_ms"] <= 10000
            events.append(("rpc", operation))
            if self.error:
                raise self.error
            from wso_api.tvt.devices import _SCHEMAS
            from wso_contracts.tvt.directory import ObservationField, ObservationObject

            records = ()
            if operation in ("device_detail", "channel_detail"):
                records = (
                    ObservationObject(
                        fields=tuple(
                            ObservationField(
                                name=name,
                                state="missing",
                                source_default=member.source_default,
                            )
                            for name, member in _SCHEMAS[operation].members.items()
                        )
                    ),
                )
            return DirectoryView(
                **REFERENCE
                | {
                    "method": operation,
                    "generation": 1,
                    "request_id": kwargs["correlation_id"],
                    "records": records,
                    "total": "0"
                    if operation == "device_list"
                    else 0
                    if "shares" in operation
                    else None,
                }
                | self.changes
            )

    worker = Worker()
    for operation in OPERATIONS:
        method = operation.replace("-", "_")
        setattr(
            worker,
            "directory_" + method,
            lambda ticket, body, _method=method, **kw: worker.execute(
                _method, ticket, body, **kw
            ),
        )
    app.state.tvt_directory_worker = worker
    monkeypatch.setattr(module, "require_tenant", tenant)
    monkeypatch.setattr(module, "DirectoryTicketIssuer", Issuer)
    http = TestClient(app)
    http.cookies.set("__Host-wso-session", "opaque-test")
    return http, worker, events


def post(http, operation, body, **kwargs):
    headers = {"Origin": ORIGIN, "X-CSRF-Token": "csrf-test"} | kwargs.pop(
        "headers", {}
    )
    return http.post(
        f"/api/v1/tvt/directory/{operation}",
        params=kwargs.pop("params", {"tenant_id": TENANT}),
        json=body,
        headers=headers,
        **kwargs,
    )


def test_authentication_precedes_body():
    http = TestClient(main.create_app())
    for op in OPERATIONS:
        assert (
            http.post(
                f"/api/v1/tvt/directory/{op}?tenant_id=bad", content="{bad"
            ).status_code
            == 401
        )


@pytest.mark.parametrize("operation,body", OPERATIONS.items())
def test_committed_cookie_ticket_precedes_rpc(setup, operation, body):
    http, _worker, events = setup
    response = post(http, operation, body)
    assert response.status_code == 200, response.text
    assert (
        events[0] == "begin"
        and events[2] == "commit"
        and events[3] == ("rpc", operation.replace("-", "_"))
    )
    assert (
        response.json()["grants_operations"] is False
        and response.json()["complete"] is None
    )
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_missing_worker_before_sql(setup):
    http, _, events = setup
    http.app.state.tvt_directory_worker = None
    assert post(http, "device-list", REFERENCE).status_code == 503 and events == []


@pytest.mark.parametrize(
    "patch",
    [
        {"actor_id": FLOW},
        {"method": "sent_shares"},
        {"page_size": 1001},
        {"page_num": True},
        {"generation": 1},
    ],
)
def test_closed_inputs_before_sql(setup, patch):
    http, _, events = setup
    assert (
        post(http, "device-list", REFERENCE | patch).status_code == 422 and events == []
    )


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://evil.test"}, {"X-CSRF-Token": "wrong"}]
)
def test_csrf_before_body(setup, headers):
    http, _, events = setup
    assert (
        post(http, "device-list", {"actor_id": "secret"}, headers=headers).status_code
        == 403
        and events == []
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"identity_id": UUID(int=9)},
        {"region": "other"},
        {"method": "sent_shares"},
        {"request_id": "other"},
        {"total": 1},
        {"generation": 2**53},
    ],
)
def test_mismatched_view_fails_safely(setup, patch):
    http, worker, _ = setup
    worker.changes = patch
    response = post(http, "device-list", REFERENCE)
    assert (
        response.status_code == 502
        and response.json()["error"]["code"] == "ACCOUNT_PROTOCOL_INVALID"
    )


def test_failure_namespace_closed(setup):
    http, worker, _ = setup
    worker.error = AccountFailure("secret-value", 418)
    response = post(http, "device-list", REFERENCE)
    assert response.status_code == 503 and "secret-value" not in response.text


def test_shared_lifecycle_clears_three_before_close(monkeypatch):
    app = main.create_app()
    events = []
    client = SimpleNamespace(
        close=lambda: events.append(
            (
                app.state.tvt_account_worker,
                app.state.tvt_account_flow_worker,
                app.state.tvt_directory_worker,
            )
        )
    )
    monkeypatch.setattr(
        main.account_rpc, "create_account_worker_client", lambda: client
    )
    with TestClient(app):
        assert (
            app.state.tvt_directory_worker
            is app.state.tvt_account_worker
            is app.state.tvt_account_flow_worker
            is client
        )
    assert events == [(None, None, None)]


@pytest.mark.parametrize(
    "content",
    [
        '{"identity_id":"'
        + FLOW
        + '","region":"KR","brand":"SuperLivePlus","page_num":0,"page_num":1}',
        " " * 65537 + json.dumps(REFERENCE),
        '{"x":NaN}',
        "[" * 33 + "0" + "]" * 33,
    ],
    ids=["duplicate", "bytes", "nonfinite", "depth"],
)
def test_raw_json_rejects_duplicates_depth_nonfinite_bytes(setup, content):
    http, _, events = setup
    response = http.post(
        "/api/v1/tvt/directory/device-list",
        params={"tenant_id": TENANT},
        content=content,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": "csrf-test",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 422
    assert events == []


@pytest.mark.parametrize(
    "query",
    [
        "tenant_id=" + TENANT + "&tenant_id=" + TENANT,
        "tenant_id=" + TENANT + "&actor_id=" + FLOW,
    ],
)
def test_exact_query_denies_before_sql(setup, query):
    http, _, events = setup
    response = http.post(
        "/api/v1/tvt/directory/device-list?" + query,
        json=REFERENCE,
        headers={"Origin": ORIGIN, "X-CSRF-Token": "csrf-test"},
    )
    assert response.status_code == 422 and events == []


def test_original_budget_checked_after_rpc(setup, monkeypatch):
    http, worker, _ = setup
    module = subject()
    budgets = []

    class OriginalBudget:
        def __init__(self, ms):
            assert ms == 10000
            self.expired = False
            budgets.append(self)

        def remaining(self):
            if self.expired:
                raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
            return 9999

    monkeypatch.setattr(module, "Budget", OriginalBudget)
    execute = worker.execute

    def late(*args, **kw):
        result = execute(*args, **kw)
        budgets[0].expired = True
        return result

    worker.execute = late
    assert post(http, "device-list", REFERENCE).status_code == 504
    assert len(budgets) == 1


@pytest.mark.parametrize(
    "code,status",
    [
        ("DIRECTORY_REAUTHENTICATION_REQUIRED", 401),
        ("ACCOUNT_QUARANTINED", 503),
        ("ACCOUNT_CANCELLED", 409),
        ("RATE_LIMITED", 429),
        ("ACCOUNT_PROTOCOL_INVALID", 502),
    ],
)
def test_directory_failure_pairs(setup, code, status):
    http, worker, _ = setup
    worker.error = AccountFailure(code, status)
    response = post(http, "device-list", REFERENCE)
    assert response.status_code == status and response.json()["error"]["code"] == code


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "duplicate",
        "source-default",
        "missing-value",
        "unsafe-number",
        "string-bound",
    ],
)
def test_presence_projection_denies_invalid_source_metadata(setup, change):
    from wso_contracts.tvt.directory import ObservationField, ObservationObject

    http, worker, _ = setup
    names = [
        "sn",
        "name",
        "userId",
        "devName",
        "mode",
        "createTime",
        "maxShareNum",
        "type",
    ]
    fields = [
        ObservationField(
            name=name,
            state="missing",
            source_default="0"
            if name == "maxShareNum"
            else 0
            if name == "type"
            else None,
        )
        for name in names
    ]
    if change == "extra":
        fields.append(ObservationField(name="auth", state="missing"))
    if change == "duplicate":
        fields.append(fields[0])
    if change == "source-default":
        fields[-1] = ObservationField(name="type", state="missing", source_default="0")
    if change == "missing-value":
        fields[0] = ObservationField(name="sn", state="missing", value="private")
    if change == "unsafe-number":
        fields[-1] = ObservationField(
            name="type", state="value", value=2**53, source_default=0
        )
    if change == "string-bound":
        fields[0] = ObservationField(name="sn", state="value", value="x" * 4097)
    worker.changes = {"records": (ObservationObject(fields=tuple(fields)),)}
    response = post(http, "device-list", REFERENCE)
    assert response.status_code == 502 and "private" not in response.text


def test_startup_failure_clears_directory_before_close(monkeypatch):
    app = main.create_app()
    events = []
    worker = SimpleNamespace(
        close=lambda: events.append(
            (
                app.state.tvt_account_worker,
                app.state.tvt_account_flow_worker,
                app.state.tvt_directory_worker,
            )
        )
    )
    monkeypatch.setattr(
        main.account_rpc, "create_account_worker_client", lambda: worker
    )
    monkeypatch.setattr(
        main,
        "configure_assets",
        lambda *_args, **_kw: (_ for _ in ()).throw(RuntimeError("private")),
    )
    with pytest.raises(RuntimeError), TestClient(app):
        pass
    assert events == [(None, None, None)]


@pytest.fixture(scope="module")
def owned_directory_database():
    """Root activation and accepted exact source hashes precede any DB creation."""
    from pathlib import Path

    from tests.support.directory_source_gate import verify_directory_source_gate

    verify_directory_source_gate()
    root = Path(__file__).resolve().parents[2]
    evidence = (
        root
        / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W07-directory-api-evidence"
    )
    from tests.integration import test_tvt_directory_admission as authority

    previous = authority.EVIDENCE
    authority.EVIDENCE = evidence
    generator = authority.directory_database.__wrapped__()
    try:
        yield next(generator)
    finally:
        try:
            next(generator, None)
        finally:
            authority.EVIDENCE = previous


def test_owned_restricted_sql_commit_mtls_real_https_six_reads(
    owned_directory_database, monkeypatch, tmp_path
):
    """One actual contained composition case; synthetic source payloads only."""
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from test_account_process import trust_host_peer
    from test_bridge_mtls import StrictExecutor, certs
    from wso_api.auth import AuthSettings, OIDCVerifier, PostgresSessionStore
    from wso_api.tvt.device_service import DirectoryWorkerExecutor
    from wso_api.tvt.session_service import AccountEndpoint
    from wso_core.tvt import account_process
    from wso_core.tvt.directory_admission import DirectoryAdmission, DirectoryPolicy
    from wso_tvt_bridge.client import AccountRpcClient, ClientConfig
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig

    from tests.integration.test_tvt_directory_admission import seeded_directory
    from tests.integration.test_tvt_sessions import TestKey

    seed = seeded_directory.__wrapped__(owned_directory_database)
    engines, ids = next(seed)
    session_value, csrf = "synthetic-directory-session", "synthetic-directory-csrf"
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE public.web_sessions SET session_digest=:s,csrf_digest=:c WHERE session_digest=:old"
            ),
            {
                "s": token_digest(session_value),
                "c": token_digest(csrf),
                "old": ids["session"],
            },
        )
    ids["session"] = token_digest(session_value)
    certs(tmp_path)
    received = []
    server = None
    peer = None
    worker = None
    admission = None
    client = None
    source_paths = {
        "/resource/device/list": {
            "total": "1",
            "records": [
                {
                    "sn": "opaque-SN",
                    "name": "Synthetic camera",
                    "password": "synthetic-never-public",
                }
            ],
        },
        "/resource/channel/list": [
            {"sn": "opaque-SN", "chls": [{"chlIndex": 7, "chlName": None}]}
        ],
        "/resource/device/detail": {
            "devInfo": {"sn": "opaque-SN"},
            "chlInfos": [{"sn": "opaque-SN", "chlIndex": 7}],
        },
        "/resource/channel/detail": {"sn": "opaque-SN", "chlIndex": 7},
        "/resource/channel/share/to-other/list": {
            "total": 1,
            "records": [
                {"sn": "opaque-SN", "chlIndex": 7, "auth": ["synthetic-observation"]}
            ],
        },
        "/resource/channel/share/from-other/list": {"total": 0, "records": []},
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert (
                self.path in source_paths
                and value["basic"]["token"] == "synthetic-user-token"
            )
            with engines["ADMIN"].connect() as db:
                assert (
                    db.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND usename IN ('wso_app','wso_connection_worker') AND state LIKE 'idle in transaction%'"
                        )
                    ).scalar_one()
                    == 0
                )
            received.append(self.path)
            payload = json.dumps(
                {"basic": {"msgcode": 200}, "data": source_paths[self.path]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    try:
        peer = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(tmp_path / "server.pem", tmp_path / "server.key")
        peer.socket = context.wrap_socket(peer.socket, server_side=True)
        thread = threading.Thread(target=peer.serve_forever, daemon=True)
        thread.start()
        trust_host_peer(monkeypatch, account_process, tmp_path / "ca.pem")
        admission = DirectoryAdmission(
            engines["WORKER"].url.render_as_string(hide_password=False),
            (DirectoryPolicy("test", "SuperLivePlus", "profile", "v1"),),
            TestKey(),
        )
        worker = DirectoryWorkerExecutor(
            admission,
            (
                AccountEndpoint(
                    "test",
                    "SuperLivePlus",
                    f"https://localhost:{peer.server_port}",
                    "en",
                    "KR",
                    "1.18.1",
                    "app",
                ),
            ),
        )

        def dispose():
            try:
                worker.close()
            finally:
                admission.close()

        server = AccountRpcServer(
            ServerConfig(
                "localhost:0",
                (tmp_path / "ca.pem").read_bytes(),
                (tmp_path / "server.pem").read_bytes(),
                (tmp_path / "server.key").read_bytes(),
                frozenset({"api.test"}),
                1,
            ),
            StrictExecutor(tmp_path),
            directory_worker=worker,
            dispose=dispose,
        )
        client = AccountRpcClient(
            ClientConfig(
                f"localhost:{server.start()}",
                (tmp_path / "ca.pem").read_bytes(),
                (tmp_path / "client.pem").read_bytes(),
                (tmp_path / "client.key").read_bytes(),
            )
        )
        settings = AuthSettings(
            "https://w02.test",
            "synthetic",
            "https://w02.test/jwks",
            "x" * 32,
            ORIGIN,
            engines["SESSION"].url.render_as_string(hide_password=False),
        )
        service = AuthService(
            settings,
            OIDCVerifier(settings),
            PostgresSessionStore(
                settings.session_database_url,
                session_factory=sessionmaker(engines["SESSION"]),
            ),
            identity_factory=sessionmaker(engines["IDENTITY"]),
            tenant_factory=sessionmaker(engines["APP"]),
        )
        monkeypatch.setattr(
            main.account_rpc, "create_account_worker_client", lambda: client
        )
        app = main.create_app()
        app.state.auth_service = service
        selection = {
            "identity_id": str(ids["identity"]),
            "region": "test",
            "brand": "SuperLivePlus",
        }
        bodies = {
            "device-list": selection,
            "channel-list": selection | {"sn_list": ["opaque-SN"]},
            "device-detail": selection | {"sn": "opaque-SN", "return_chl": True},
            "channel-detail": selection | {"sn": "opaque-SN", "chl_index": 7},
            "sent-shares": selection,
            "received-shares": selection,
        }
        with TestClient(app) as http:
            http.cookies.set("__Host-wso-session", session_value)
            for operation, body in bodies.items():
                response = http.post(
                    f"/api/v1/tvt/directory/{operation}",
                    params={"tenant_id": str(ids["tenant"])},
                    json=body,
                    headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                )
                assert response.status_code == 200, response.text
                data = response.json()
                assert (
                    data["request_id"] == response.headers["X-Request-ID"]
                    and data["identity_id"] == selection["identity_id"]
                    and data["generation"] == 1
                )
                assert data["complete"] is None and data["grants_operations"] is False
                assert (
                    "no-store" in response.headers["Cache-Control"]
                    and response.headers["Vary"] == "Cookie"
                )
                assert all(
                    marker not in response.text
                    for marker in [
                        "synthetic-user-token",
                        "synthetic-p2p-token",
                        "synthetic-never-public",
                        session_value,
                        csrf,
                    ]
                )
                if operation == "channel-list":
                    assert (
                        data["records"][0]["fields"][1]["value"][0]["fields"][0][
                            "value"
                        ]
                        == 7
                    )
            assert received == list(source_paths)
            with engines["ADMIN"].begin() as db:
                db.execute(
                    text(
                        "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                    ),
                    {"s": ids["session"]},
                )
            response = http.post(
                "/api/v1/tvt/directory/device-list",
                params={"tenant_id": str(ids["tenant"])},
                json=selection,
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            )
            assert response.status_code == 401 and len(received) == 6
        assert client._closed and app.state.tvt_directory_worker is None
        with engines["ADMIN"].connect() as db:
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM wso_private.tvt_directory_tickets WHERE tenant_id=:t"
                    ),
                    {"t": ids["tenant"]},
                ).scalar_one()
                == 0
            )
    finally:
        if client is not None:
            client.close()
        if server is not None:
            assert server.close() is True
        elif admission is not None:
            admission.close()
        if peer is not None:
            peer.shutdown()
            peer.server_close()
            thread.join(2)
        next(seed, None)
        for path in tmp_path.rglob("*"):
            if path.is_file() and path.suffix in {".pem", ".key"}:
                path.unlink()
