"""Routing seams prove HTTP behavior, never SQL authority or APK acceptance."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from wso_api import main
from wso_api.auth import AuthService, WebSession, token_digest
from wso_contracts.tvt.account_flows import AccountFlowView
from wso_core.tvt.account_projection import AccountFailure

TENANT = str(UUID(int=1))
FLOW = str(UUID(int=2))
ORIGIN = "https://app.example.test"
REFERENCE = {
    "region": "KR",
    "brand": "SuperLivePlus",
    "purpose": "register",
    "flow_id": FLOW,
}
START = {k: v for k, v in REFERENCE.items() if k != "flow_id"} | {
    "mode": "email",
    "account": "person@example.test",
}
OPERATIONS = {
    "start": START,
    "state": REFERENCE,
    "existence": REFERENCE,
    "image": REFERENCE,
    "issue-code": REFERENCE,
    "register": REFERENCE | {"password": "private-test", "dynamic_code": "123456"},
    "recover": REFERENCE
    | {"purpose": "recover", "new_password": "private-test", "dynamic_code": "123456"},
    "cancel": REFERENCE,
}


def subject():
    import importlib.util

    assert importlib.util.find_spec("wso_api.tvt.account_flows"), (
        "closed account-flow routes must exist"
    )
    from wso_api.tvt import account_flows

    return account_flows


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
            return (
                AccountFlowView(
                    **{k: v for k, v in body.model_dump().items() if k in REFERENCE},
                    flow_id=UUID(FLOW),
                    state="CREATED",
                    request_id=kwargs["correlation_id"],
                )
                if operation == "start"
                else AccountFlowView(
                    **REFERENCE
                    | {
                        "purpose": body.purpose,
                        "state": "CREATED",
                        "request_id": kwargs["correlation_id"],
                    }
                    | self.changes
                )
            )

    worker = Worker()
    for operation in OPERATIONS:
        method = operation.replace("-", "_")
        setattr(
            worker,
            method,
            lambda ticket, body, _method=method, **kw: worker.execute(
                _method, ticket, body, **kw
            ),
        )
    app.state.tvt_account_flow_worker = worker
    monkeypatch.setattr(module, "require_tenant", tenant)
    monkeypatch.setattr(module, "FlowTicketIssuer", Issuer)
    http = TestClient(app)
    http.cookies.set("__Host-wso-session", "opaque-test")
    return http, worker, events


def post(http, operation, body, **kwargs):
    headers = {"Origin": ORIGIN, "X-CSRF-Token": "csrf-test"} | kwargs.pop(
        "headers", {}
    )
    return http.post(
        f"/api/v1/tvt/account-flows/{operation}",
        params=kwargs.pop("params", {"tenant_id": TENANT}),
        json=body,
        headers=headers,
        **kwargs,
    )


def test_routes_exist_and_anonymous_authentication_precedes_invalid_body():
    http = TestClient(main.create_app())
    for operation in OPERATIONS:
        response = http.post(
            f"/api/v1/tvt/account-flows/{operation}?tenant_id=bad", content="{bad"
        )
        assert response.status_code == 401


@pytest.mark.parametrize("operation,body", OPERATIONS.items())
def test_fixed_operation_commits_then_dispatches_and_binds_request_id(
    setup, operation, body
):
    http, _, events = setup
    response = post(http, operation, body)
    assert response.status_code == 200, response.text
    assert events[-1] == ("rpc", operation.replace("-", "_"))
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.json()["purpose"] == body["purpose"]
    assert response.headers["Cache-Control"] == "no-store"
    assert (
        "private-test" not in response.text
        and "person@example.test" not in response.text
    )


@pytest.mark.parametrize(
    "patch", [{"Origin": "https://evil.test"}, {"X-CSRF-Token": "bad"}]
)
def test_csrf_precedes_body_validation_and_issuance(setup, patch):
    http, _, events = setup
    assert (
        post(http, "register", {"password": "private-test"}, headers=patch).status_code
        == 403
    )
    assert events == []


@pytest.mark.parametrize(
    "body",
    [
        START | {"actor_id": TENANT},
        START | {"session_digest": "a" * 64},
        START | {"country_code": None},
        START | {"account": "bad"},
        START | {"account": "😀@example.test"},
        START | {"mode": "phone", "account": "123", "country_code": "+82"},
    ],
)
def test_invalid_body_cannot_issue_or_disclose_inputs(setup, body):
    http, _, events = setup
    response = post(http, "start", body)
    assert response.status_code == 422
    assert events == [] and "account" not in response.json()["error"]["message"].lower()


def test_invalid_tenant_and_wrong_purpose_cannot_issue(setup):
    http, _, events = setup
    assert post(http, "start", START, params={"tenant_id": "bad"}).status_code == 422
    assert (
        post(
            http, "register", OPERATIONS["register"] | {"purpose": "recover"}
        ).status_code
        == 422
    )
    assert events == []


def test_missing_worker_denies_before_sql(setup):
    http, _, events = setup
    http.app.state.tvt_account_flow_worker = None
    response = post(http, "start", START)
    assert (
        response.status_code == 503
        and response.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"
    )
    assert events == []


def test_unknown_outcome_and_safe_failure_are_not_retried(setup):
    http, worker, events = setup
    worker.changes = {"state": "UNKNOWN_OUTCOME"}
    response = post(http, "register", OPERATIONS["register"])
    assert response.json()["automatic_retry_permitted"] is False
    assert (
        len(
            [
                event
                for event in events
                if isinstance(event, tuple) and event[0] == "rpc"
            ]
        )
        == 1
    )
    worker.error = AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
    response = post(http, "state", REFERENCE)
    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "ACCOUNT_PROTOCOL_INVALID",
        "message": "Account request failed",
    }


def test_lifespan_shares_same_owned_client_and_clears_both_before_close(monkeypatch):
    app = main.create_app()
    events = []
    client = SimpleNamespace(
        close=lambda: events.append(
            (app.state.tvt_account_worker, app.state.tvt_account_flow_worker)
        )
    )
    monkeypatch.setattr(
        main.account_rpc, "create_account_worker_client", lambda: client
    )
    with TestClient(app):
        assert (
            app.state.tvt_account_flow_worker is app.state.tvt_account_worker is client
        )
    assert events == [(None, None)]


@pytest.mark.parametrize(
    "patch",
    [
        {"request_id": "other"},
        {"flow_id": UUID(int=9)},
        {"purpose": "recover"},
        {"region": "other"},
    ],
)
def test_worker_response_scope_cannot_cross_the_api_boundary(setup, patch):
    http, worker, _ = setup
    worker.changes = patch
    response = post(http, "state", REFERENCE)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ACCOUNT_PROTOCOL_INVALID"


def test_malformed_worker_view_has_safe_protocol_failure(setup):
    http, worker, _ = setup
    worker.state = lambda *args, **kwargs: AccountFlowView.model_construct(
        **REFERENCE | {"flow_id": UUID(FLOW)},
        request_id=kwargs["correlation_id"],
        state="COMPLETE",
        return_to_login=False,
    )
    response = post(http, "state", REFERENCE)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ACCOUNT_PROTOCOL_INVALID"


def test_original_budget_is_checked_after_rpc_before_publication(setup, monkeypatch):
    http, worker, _ = setup
    from wso_api.tvt import account

    class OriginalBudget:
        def __init__(self, milliseconds):
            self.expired = False
            assert milliseconds == 10000

        def remaining(self):
            if self.expired:
                raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
            return 9

    monkeypatch.setattr(account, "Budget", OriginalBudget)
    execute = worker.execute

    def late(operation, ticket, body, **kwargs):
        result = execute(operation, ticket, body, **kwargs)
        # Capture the actual route budget at issuance, never reset at RPC.
        budget[0].expired = True
        return result

    budget = []
    from wso_api.tvt import account_flows

    issuer = account_flows.FlowTicketIssuer

    def capture(session, remaining):
        budget.append(remaining.__self__)
        return issuer(session, remaining)

    monkeypatch.setattr(account_flows, "FlowTicketIssuer", capture)
    worker.execute = late
    response = post(http, "state", REFERENCE)
    assert response.status_code == 504


def test_openapi_declares_typed_rate_limit_failures():
    document = main.create_app().openapi()
    assert (
        "429"
        in document["paths"]["/api/v1/tvt/account-flows/issue-code"]["post"][
            "responses"
        ]
    )


def test_flow_failure_namespace_rejects_unreviewed_worker_codes(setup):
    http, worker, _ = setup
    worker.error = AccountFailure("private-password", 418)
    response = post(http, "state", REFERENCE)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"
    assert "private-password" not in response.text


@pytest.fixture(scope="module")
def owned_flow_database():
    """Explicit root activation only; reuse the proven disposable DB guard."""
    import hashlib
    import os
    from pathlib import Path

    if os.environ.get("WSO_TEST_W06_API_ACCEPTANCE") != "1":
        pytest.skip(
            "requires root-approved protected core and explicit owned API activation"
        )
    root = Path(__file__).resolve().parents[2]
    approved = {
        "infra/migrations/versions/0010_tvt_account_flows.py": "a8c39baf215e3b8fea4b92e5df96c21bf1701b9edbb7d61f62e27860af2e5958",
        "packages/core/src/wso_core/tvt/flow_admission.py": "0bdf2edd69aa30a7d237fb0e167e6f8210cbd9895a39ba4e8802988201b8fe26",
        "services/api/src/wso_api/tvt/flow_service.py": "b88a2658fd9552fb5af0c5cc4ebfdaa5f73b8e3afcdeac293d78630c15e0ec4b",
    }
    assert all(
        hashlib.sha256((root / p).read_bytes()).hexdigest() == digest
        for p, digest in approved.items()
    )
    from tests.integration import test_tvt_account_flow_admission as authority

    previous = authority.EVIDENCE
    authority.EVIDENCE = (
        root
        / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W06-account-flow-api-evidence"
    )
    generator = authority.flow_database.__wrapped__()
    try:
        yield next(generator)
    finally:
        try:
            next(generator, None)
        finally:
            authority.EVIDENCE = previous


def test_owned_sql_issuer_mtls_https_public_pipeline(
    owned_flow_database, monkeypatch, tmp_path
):
    """Real SQL/RPC/HTTPS, synthetic loopback payloads; no real TVT writes."""
    import base64
    import hashlib
    import json
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from test_account_process import trust_host_peer
    from test_bridge_mtls import StrictExecutor, certs
    from wso_api.auth import AuthSettings, OIDCVerifier, PostgresSessionStore
    from wso_api.tvt.flow_service import AccountFlowWorkerExecutor, FlowEndpointConfig
    from wso_api.tvt.session_service import AccountEndpoint
    from wso_core.tvt import account_process
    from wso_core.tvt.flow_admission import FlowAdmission
    from wso_tvt_bridge.client import AccountRpcClient, ClientConfig
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig

    from tests.integration.test_tvt_account_flow_admission import seeded_flow

    seed = seeded_flow.__wrapped__(owned_flow_database)
    engines, ids = next(seed)
    session_value, csrf = "synthetic-api-session", "synthetic-api-csrf"
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
    public_key = base64.b64encode(
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).decode()
    media = base64.b64encode(b"\xff\xd8\xffsynthetic-image\xff\xd9").decode()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, value))
            if self.path.endswith("is-exist"):
                data = {"isExist": False}
            elif self.path == "/user/img-code/get":
                data = {
                    "idCode": "synthetic-native-id",
                    "imgCodeImgData": media,
                    "publicKey": public_key,
                }
            elif self.path == "/user/sms-code/no-token/get":
                data = {"publicKey": public_key}
            else:
                assert self.path in {"/user/register", "/user/info/password/reset"}
                data = {"token": "synthetic-never-public"}
            payload = json.dumps({"basic": {"msgcode": 200}, "data": data}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    peer = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "server.pem", tmp_path / "server.key")
    peer.socket = context.wrap_socket(peer.socket, server_side=True)
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()
    trust_host_peer(monkeypatch, account_process, tmp_path / "ca.pem")
    admission = FlowAdmission(
        engines["WORKER"].url.render_as_string(hide_password=False),
        hashlib.sha256(bytes(range(32))).hexdigest(),
    )
    worker = AccountFlowWorkerExecutor(
        admission,
        (
            AccountEndpoint(
                "test",
                "brand",
                f"https://localhost:{peer.server_port}",
                "en",
                "KR",
                "1.18.1",
                "app",
            ),
        ),
        {("test", "brand"): FlowEndpointConfig("synthetic.example.invalid")},
        bytes(range(32)),
    )

    def dispose():
        try:
            worker.close()
        finally:
            admission.close()

    server = AccountRpcServer(
        ServerConfig(
            bind="localhost:0",
            ca=(tmp_path / "ca.pem").read_bytes(),
            certificate=(tmp_path / "server.pem").read_bytes(),
            key=(tmp_path / "server.key").read_bytes(),
            client_sans=frozenset({"api.test"}),
            capacity=1,
        ),
        StrictExecutor(tmp_path),
        flow_worker=worker,
        dispose=dispose,
    )
    client = AccountRpcClient(
        ClientConfig(
            endpoint=f"localhost:{server.start()}",
            ca=(tmp_path / "ca.pem").read_bytes(),
            certificate=(tmp_path / "client.pem").read_bytes(),
            key=(tmp_path / "client.key").read_bytes(),
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

    def call(http, operation, body):
        response = http.post(
            f"/api/v1/tvt/account-flows/{operation}",
            params={"tenant_id": str(ids["tenant"])},
            json=body,
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200, response.text
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
        assert (
            "synthetic-never-public" not in response.text
            and "synthetic-native-id" not in response.text
            and "synthetic-password" not in response.text
        )
        return response.json()

    try:
        with TestClient(app) as http:
            http.cookies.set("__Host-wso-session", session_value)
            selection = {"region": "test", "brand": "brand", "purpose": "register"}
            start_body = selection | {
                "mode": "email",
                "account": "synthetic@example.invalid",
            }
            started = call(http, "start", start_body)
            reference = selection | {"flow_id": started["flow_id"]}
            assert call(http, "existence", reference)["exists"] is False
            image = call(http, "image", reference)["image"]
            code = call(
                http,
                "issue-code",
                reference
                | {
                    "challenge_id": image["challenge_id"],
                    "challenge_generation": image["generation"],
                    "image_code": "1234",
                },
            )
            assert code["state"] == "CODE_SENT"
            assert (
                call(
                    http,
                    "register",
                    reference
                    | {"password": "synthetic-password", "dynamic_code": "123456"},
                )["return_to_login"]
                is True
            )
            recover = call(
                http,
                "start",
                start_body
                | {"purpose": "recover", "account": "recover@example.invalid"},
            )
            recovery = {
                **selection,
                "purpose": "recover",
                "flow_id": recover["flow_id"],
            }
            assert call(http, "issue-code", recovery)["state"] == "CODE_SENT"
            assert (
                call(
                    http,
                    "recover",
                    recovery
                    | {"new_password": "synthetic-password", "dynamic_code": "654321"},
                )["state"]
                == "COMPLETE"
            )
            fresh = call(
                http, "start", start_body | {"account": "cancel@example.invalid"}
            )
            assert (
                call(http, "cancel", selection | {"flow_id": fresh["flow_id"]})["state"]
                == "CLOSED"
            )
            expired = call(
                http, "start", start_body | {"account": "expired@example.invalid"}
            )
            # Simulate elapsed time in BOTH protected persistent metadata and
            # this worker's monotonic cache. Production expiry is assigned once
            # at creation; admin-only SQL shortening alone is not clock passage.
            import time

            worker._registry[UUID(expired["flow_id"])].expiry = time.monotonic() - 1
            with engines["ADMIN"].begin() as db:
                db.execute(
                    text(
                        "UPDATE wso_private.tvt_flows SET expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"
                    ),
                    {"id": expired["flow_id"]},
                )
            assert (
                call(http, "state", selection | {"flow_id": expired["flow_id"]})[
                    "state"
                ]
                == "EXPIRED"
            )
            before = len(received)
            with engines["ADMIN"].begin() as db:
                db.execute(
                    text(
                        "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                    ),
                    {"s": ids["session"]},
                )
            response = http.post(
                "/api/v1/tvt/account-flows/start",
                params={"tenant_id": str(ids["tenant"])},
                json=start_body,
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            )
            assert response.status_code == 401 and len(received) == before
            paths = [path for path, _ in received]
            assert "/user/register" in paths and "/user/info/password/reset" in paths
            assert all(path.startswith("/user/") for path in paths)
    finally:
        client.close()
        try:
            assert server.close() is True
            assert worker._closed.is_set() and worker._binding_key == b""
            assert worker._config == {} and worker._endpoints == {}
        finally:
            peer.shutdown()
            peer.server_close()
            thread.join(2)
            next(seed, None)
            for path in tmp_path.glob("*"):
                if path.is_file() and path.suffix in {".pem", ".key"}:
                    path.unlink()
