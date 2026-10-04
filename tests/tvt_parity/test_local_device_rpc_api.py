"""Synthetic local API/RPC checks; no SQL or native acceptance claims."""

from uuid import UUID

import pytest


def test_local_verify_proto_contains_only_context():
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb

    assert [f.name for f in pb.LocalDeviceVerifyRequest.DESCRIPTOR.fields] == [
        "context"
    ]
    assert [
        m.name for m in pb.DESCRIPTOR.services_by_name["LocalDeviceBridgeV1"].methods
    ] == ["Verify"]


def test_public_projection_rejects_hidden_raw_channel_members():
    from datetime import UTC, datetime

    from wso_contracts.tvt.local_device import LocalChannelView, LocalDeviceView
    from wso_core.tvt.local_service import LocalDeviceFailure
    from wso_tvt_bridge.local_rpc import checked_local_view

    channel = LocalChannelView(id=UUID(int=4), ordinal=1, label="Channel 1")
    channel.__dict__["native_guid"] = "PRIVATE-RAW"
    view = LocalDeviceView.model_construct(
        connection_id=UUID(int=1),
        device_id=UUID(int=2),
        store_id=UUID(int=3),
        connection_generation=1,
        inventory_revision=1,
        inventory_state="AVAILABLE",
        observed_at=datetime.now(UTC),
        channels=(channel,),
        request_id="test",
    )
    with pytest.raises(
        LocalDeviceFailure, match="Local device request failed"
    ) as error:
        checked_local_view(view, "test")
    assert error.value.code == "LOCAL_DEVICE_PROTOCOL_INVALID"


def test_local_api_routes_document_saved_inventory_and_strict_verify():
    from wso_api.main import create_app

    paths = create_app().openapi()["paths"]
    assert "/api/v1/tvt/local-devices" in paths
    assert "/api/v1/tvt/local-devices/{connection_id}/channels" in paths
    assert "/api/v1/tvt/local-devices/{connection_id}/verify" in paths


from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from time import monotonic


def local_view(request_id="test"):
    from wso_contracts.tvt.local_device import LocalDeviceView

    return LocalDeviceView(
        connection_id=UUID(int=1),
        device_id=UUID(int=2),
        store_id=UUID(int=3),
        connection_generation=1,
        inventory_revision=1,
        inventory_state="AVAILABLE",
        observed_at=datetime.now(UTC),
        request_id=request_id,
    )


class SyntheticLocalWorker:
    def __init__(self):
        self.entered = Event()
        self.cancelled = Event()
        self.change = {}
        self.error = None
        self.calls = []

    def verify(self, ticket, *, deadline_ms, correlation_id, cancel):
        assert 0 < deadline_ms <= 20000
        self.calls.append(ticket)
        if ticket.startswith("dd"):
            self.entered.set()
            assert cancel.wait(2)
            self.cancelled.set()
        if self.error:
            raise self.error
        return local_view(correlation_id).model_copy(update=self.change)


@pytest.fixture
def local_transport(tmp_path):
    from test_bridge_mtls import StrictExecutor, certs
    from wso_tvt_bridge.client import AccountRpcClient, ClientConfig
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig

    certs(tmp_path)
    worker = SyntheticLocalWorker()
    config = ServerConfig(
        "localhost:0",
        (tmp_path / "ca.pem").read_bytes(),
        (tmp_path / "server.pem").read_bytes(),
        (tmp_path / "server.key").read_bytes(),
        frozenset({"api.test"}),
        2,
    )
    server = AccountRpcServer(
        config, StrictExecutor(tmp_path), local_device_worker=worker
    )
    port = server.start()
    clients = []

    def make(label="client"):
        c = AccountRpcClient(
            ClientConfig(
                f"localhost:{port}",
                config.ca,
                (tmp_path / f"{label}.pem").read_bytes(),
                (tmp_path / f"{label}.key").read_bytes(),
            )
        )
        clients.append(c)
        return c

    try:
        yield server, worker, make
    finally:
        for c in clients:
            c.close()
        server.close()


def test_local_verified_tls_channel_returns_only_safe_inventory(local_transport):
    server, worker, make = local_transport
    result = make().verify("01" * 32, deadline_ms=3000, correlation_id="local")
    assert result == local_view("local").model_copy(
        update={"observed_at": result.observed_at}
    )
    assert worker.calls == ["01" * 32] and server.pool.registry.active_count == 0


def test_local_wrong_peer_san_is_denied_before_worker(local_transport):
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, worker, make = local_transport
    with pytest.raises(LocalDeviceFailure) as err:
        make("other").verify("01" * 32, deadline_ms=3000, correlation_id="peer")
    assert err.value.code == "LOCAL_DEVICE_DENIED" and worker.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"request_id": "wrong"},
        {"serial": "PRIVATE-DETAIL"},
        {"channels": ("raw",)},
        {"connection_generation": True},
    ],
)
def test_local_rpc_redacts_invalid_worker_output(local_transport, change):
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, worker, make = local_transport
    worker.change = change
    with pytest.raises(LocalDeviceFailure) as err:
        make().verify("01" * 32, deadline_ms=3000, correlation_id="bad-output")
    assert err.value.code == "LOCAL_DEVICE_PROTOCOL_INVALID"
    assert "PRIVATE" not in str(err.value)


def test_local_client_cancel_reaches_original_executor(local_transport):
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, worker, make = local_transport
    client = make()
    cancel = Event()
    with ThreadPoolExecutor(1) as executor:
        pending = executor.submit(
            client.verify,
            "dd" * 32,
            deadline_ms=3000,
            correlation_id="cancel",
            cancel=cancel,
        )
        assert worker.entered.wait(1)
        cancel.set()
        with pytest.raises(LocalDeviceFailure) as err:
            pending.result(timeout=1)
        assert err.value.code == "LOCAL_DEVICE_CANCELLED"
        assert worker.cancelled.wait(1)


def test_local_deadline_reaches_executor_and_refuses_late_result(local_transport):
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, worker, make = local_transport
    start = monotonic()
    with pytest.raises(LocalDeviceFailure) as err:
        make().verify("dd" * 32, deadline_ms=150, correlation_id="deadline")
    assert err.value.code == "LOCAL_DEVICE_DEADLINE_EXCEEDED"
    assert monotonic() - start < 1 and worker.cancelled.wait(1)


def test_local_untrusted_exception_is_fixed(local_transport):
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, worker, make = local_transport
    worker.error = RuntimeError("PRIVATE-DETAIL")
    with pytest.raises(LocalDeviceFailure) as err:
        make().verify("01" * 32, deadline_ms=3000, correlation_id="throw")
    assert err.value.code == "LOCAL_DEVICE_UNAVAILABLE" and "PRIVATE" not in str(
        err.value
    )


@pytest.fixture
def local_api(monkeypatch):
    import sys
    from contextlib import contextmanager
    from datetime import timedelta
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from wso_api.auth import AuthService, WebSession, token_digest
    from wso_api.main import create_app
    from wso_api.tvt import local_devices

    app = create_app()
    service = object.__new__(AuthService)
    service.settings = SimpleNamespace(public_origin="https://app.example.test")
    principal = WebSession(
        "issuer",
        "subject",
        UUID(int=9),
        token_digest("csrf-test"),
        datetime.now(UTC) + timedelta(hours=1),
    )
    service.sessions = SimpleNamespace(
        get=lambda digest: principal if digest == token_digest("opaque-test") else None
    )
    app.state.auth_service = service
    events = []
    state = {"change": {}, "error": None}

    @contextmanager
    def tenant(action, tenant_id, **kwargs):
        assert action in (
            "connections:write",
            "connections:read",
        ) and tenant_id == UUID(int=5)
        assert kwargs == {"service": service, "principal": principal}
        events.append("begin")
        yield SimpleNamespace(session="scoped-session")
        events.append("commit")

    class Issuer:
        def __init__(self, session, remaining):
            assert session == "scoped-session" and 0 < remaining() <= 20000

        def issue(self, digest, connection_id, body):
            assert digest == token_digest("opaque-test") and connection_id == UUID(
                int=1
            )
            events.append("issue")
            return "01" * 32

    class Reader:
        def __init__(self, session):
            assert session == "scoped-session"

        def list(self, store_id, *, correlation_id):
            return (local_view(correlation_id),)

        def get(self, connection_id, store_id, *, correlation_id):
            return local_view(correlation_id)

    # Isolate API seam; real admission SQL belongs to owned integration tests.
    monkeypatch.setitem(
        sys.modules,
        "wso_core.tvt.local_admission",
        SimpleNamespace(
            LocalDeviceTicketIssuer=Issuer, LocalDeviceInventoryReader=Reader
        ),
    )

    class Worker:
        def verify(self, ticket, **kwargs):
            assert events[-1] == "commit" and ticket == "01" * 32
            assert 0 < kwargs["deadline_ms"] <= 20000 and not kwargs["cancel"].is_set()
            events.append("rpc")
            if state["error"]:
                raise state["error"]
            return local_view(kwargs["correlation_id"]).model_copy(
                update=state["change"]
            )

    app.state.tvt_local_device_worker = Worker()
    monkeypatch.setattr(local_devices, "require_tenant", tenant)
    http = TestClient(app)
    http.cookies.set("__Host-wso-session", "opaque-test")
    return http, events, state


def api_verify(http, **kwargs):
    return http.post(
        "/api/v1/tvt/local-devices/00000000-0000-0000-0000-000000000001/verify",
        params=kwargs.pop("params", {"tenant_id": str(UUID(int=5))}),
        json=kwargs.pop(
            "json", {"store_id": str(UUID(int=3)), "expected_generation": 1}
        ),
        headers=kwargs.pop(
            "headers",
            {"Origin": "https://app.example.test", "X-CSRF-Token": "csrf-test"},
        ),
        **kwargs,
    )


def test_local_api_commits_before_rpc_and_returns_no_store(local_api):
    http, events, _ = local_api
    response = api_verify(http)
    assert response.status_code == 200, response.text
    assert events == ["begin", "issue", "commit", "rpc"]
    assert (
        response.headers["cache-control"] == "no-store"
        and response.headers["vary"] == "Cookie"
    )
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_local_api_authentication_and_csrf_precede_parsing(local_api):
    http, events, _ = local_api
    http.cookies.clear()
    assert (
        api_verify(
            http, json={"expected_generation": "bad"}, params={"tenant_id": "bad"}
        ).status_code
        == 401
    )
    http.cookies.set("__Host-wso-session", "opaque-test")
    assert api_verify(http, headers={}).status_code == 403
    assert events == []


@pytest.mark.parametrize(
    "body",
    [
        {"store_id": str(UUID(int=3)), "expected_generation": True},
        {"store_id": str(UUID(int=3)), "expected_generation": 1, "serial": "PRIVATE"},
        {"store_id": str(UUID(int=3)), "expected_generation": 0},
    ],
)
def test_local_api_strict_body_before_sql(local_api, body):
    http, events, _ = local_api
    assert api_verify(http, json=body).status_code == 422 and events == []


@pytest.mark.parametrize(
    "change",
    [
        {"connection_id": UUID(int=20)},
        {"store_id": UUID(int=20)},
        {"connection_generation": 2},
        {"serial": "PRIVATE"},
    ],
)
def test_local_api_rejects_wrong_scope_and_hidden_raw_worker_fields(local_api, change):
    http, _, state = local_api
    state["change"] = change
    response = api_verify(http)
    assert (
        response.status_code == 502
        and response.json()["error"]["code"] == "LOCAL_DEVICE_PROTOCOL_INVALID"
    )
    assert "PRIVATE" not in response.text


def test_local_api_saved_inventory_requires_no_worker(local_api):
    http, events, _ = local_api
    http.app.state.tvt_local_device_worker = None
    params = {"tenant_id": str(UUID(int=5)), "store_id": str(UUID(int=3))}
    for path in (
        "/api/v1/tvt/local-devices",
        "/api/v1/tvt/local-devices/00000000-0000-0000-0000-000000000001/channels",
    ):
        response = http.get(path, params=params)
        assert response.status_code == 200, response.text
    assert "rpc" not in events and "issue" not in events


@pytest.mark.parametrize("deadline", [0, 20001, True])
def test_local_invalid_deadline_does_not_dispatch(local_transport, deadline):
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, worker, make = local_transport
    with pytest.raises(LocalDeviceFailure) as err:
        make().verify("01" * 32, deadline_ms=deadline, correlation_id="input")
    assert err.value.code == "LOCAL_DEVICE_INPUT_INVALID" and worker.calls == []


def test_local_unknown_protobuf_authority_is_rejected_before_worker(local_transport):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.generated import tvt_bridge_pb2_grpc as rpc

    _, worker, make = local_transport
    client = make()
    request = pb.LocalDeviceVerifyRequest(
        context=pb.RpcContext(
            protocol_version=1,
            ticket="01" * 32,
            deadline_ms=3000,
            correlation_id="injected",
        )
    )
    # Field2 on the Verify message is deliberately undefined, never a selector.
    request.ParseFromString(request.SerializeToString() + b"\x12\x06secret")
    result = rpc.LocalDeviceBridgeV1Stub(client._channel).Verify(request, timeout=3)
    assert result.failure_code == "LOCAL_DEVICE_INPUT_INVALID" and worker.calls == []


def test_local_capacity_refuses_second_original_worker(local_transport):
    from wso_core.tvt.local_service import LocalDeviceFailure

    # The real shared client registry is also bounded and never invents authority.
    _, worker, make = local_transport
    client = make()
    slots = [client._registry.admit(f"held-{i}") for i in range(32)]
    try:
        with pytest.raises(LocalDeviceFailure) as err:
            client.verify("01" * 32, deadline_ms=3000, correlation_id="capacity")
        assert err.value.code == "LOCAL_DEVICE_BUSY" and worker.calls == []
    finally:
        for slot in slots:
            client._registry.settle(slot)


def test_local_rpc_client_close_cancels_original_executor(local_transport):
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, worker, make = local_transport
    client = make()
    with ThreadPoolExecutor(1) as executor:
        pending = executor.submit(
            client.verify, "dd" * 32, deadline_ms=3000, correlation_id="closed"
        )
        assert worker.entered.wait(1)
        client.close()
        with pytest.raises(LocalDeviceFailure) as err:
            pending.result(timeout=1)
        assert err.value.code == "LOCAL_DEVICE_CANCELLED" and worker.cancelled.wait(1)


def test_local_api_body_limit_and_duplicate_keys_before_sql(local_api):
    http, events, _ = local_api
    path = "/api/v1/tvt/local-devices/00000000-0000-0000-0000-000000000001/verify"
    headers = {
        "Origin": "https://app.example.test",
        "X-CSRF-Token": "csrf-test",
        "Content-Type": "application/json",
    }
    for content in ('{"store_id":"x","store_id":"y"}', " " * 1025):
        response = http.post(
            path,
            params={"tenant_id": str(UUID(int=5))},
            content=content,
            headers=headers,
        )
        assert response.status_code == 422 and events == []


@pytest.mark.parametrize("enabled", [False, True])
def test_local_worker_bootstrap_constructs_admission_only_for_configured_provider(
    monkeypatch, enabled
):
    import sys
    from types import SimpleNamespace

    from wso_api.tvt import session_service
    from wso_core import secrets
    from wso_core.tvt import local_admission, local_service, token_vault
    from wso_tvt_bridge import server

    for key in tuple(server.os.environ):
        if key.startswith("WSO_"):
            monkeypatch.delenv(key)
    env = {
        "WSO_TVT_BRIDGE_CLIENT_SANS_JSON": '["api.test"]',
        "WSO_TVT_BRIDGE_BIND": "localhost:0",
        "WSO_TVT_BRIDGE_CA_FILE": "ca",
        "WSO_TVT_BRIDGE_SERVER_CERT_FILE": "cert",
        "WSO_TVT_BRIDGE_SERVER_KEY_FILE": "key",
        "WSO_CONNECTION_KEY_FILE": "key",
        "WSO_WORKER_DATABASE_URL": "synthetic-worker-url",
    }
    if enabled:
        env["WSO_TVT_WINDOWS_LOCAL_INVENTORY_ENABLED"] = "1"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    events = []
    provider = SimpleNamespace(encryption_key=lambda: b"v" * 32)
    monkeypatch.setattr(secrets, "FileKeyProvider", lambda path: provider)
    monkeypatch.setattr(
        token_vault,
        "TokenVault",
        lambda *a: SimpleNamespace(close=lambda: events.append("vault-close")),
    )
    monkeypatch.setattr(session_service, "load_account_endpoints", lambda: ())
    monkeypatch.setattr(session_service, "AccountWorkerExecutor", lambda *a: object())
    monkeypatch.setattr(server, "pem", lambda path: b"synthetic")
    native = object()

    def loader():
        events.append("provider-loaded")
        return native

    monkeypatch.setitem(
        sys.modules,
        "wso_tvt_bridge.local_inventory_config",
        SimpleNamespace(load_local_inventory_provider=loader),
    )

    class Admission:
        def __init__(self, url, key_provider):
            assert url == "synthetic-worker-url" and key_provider is provider
            events.append("admission-created")

        def shutdown(self):
            events.append("admission-close")

    monkeypatch.setattr(local_admission, "LocalDeviceAdmission", Admission)
    executor = object()

    def create_executor(admission, native_provider):
        assert isinstance(admission, Admission) and native_provider is native
        events.append("executor-created")
        return executor

    monkeypatch.setattr(local_service, "LocalVerificationExecutor", create_executor)

    class Server:
        def __init__(
            self, config, worker, *, dispose, flow_worker, local_device_worker=None
        ):
            assert (local_device_worker is executor) == enabled
            self.dispose = dispose

    monkeypatch.setattr(server, "AccountRpcServer", Server)
    owned = server.create_server_from_environment()
    owned.dispose()
    owned.dispose()
    assert events == (
        [
            "provider-loaded",
            "admission-created",
            "executor-created",
            "admission-close",
            "vault-close",
        ]
        if enabled
        else ["vault-close"]
    )


def test_local_api_expired_auth_budget_creates_no_unawaited_body(
    local_api, monkeypatch
):
    import gc
    import warnings

    from wso_api.tvt import local_devices

    http, events, _ = local_api
    authenticate = local_devices._authenticate

    def expired_after_authentication(request):
        current = authenticate(request)
        request.state.local_device_budget.deadline_monotonic = monotonic() - 1
        return current

    monkeypatch.setattr(local_devices, "_authenticate", expired_after_authentication)
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always", RuntimeWarning)
        response = api_verify(http)
        gc.collect()
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "LOCAL_DEVICE_DEADLINE_EXCEEDED"
    assert events == []
    assert not [
        warning for warning in recorded if issubclass(warning.category, RuntimeWarning)
    ]
