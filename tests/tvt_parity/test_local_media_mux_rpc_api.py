"""Offline mux contracts, exact purpose calls and authenticated HTTP boundaries."""

import importlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from wso_contracts.tvt.local_media import LocalLiveRequest, LocalLiveResponse
from wso_core.tvt.local_service import LocalDeviceFailure


def mux_module(name):
    assert importlib.util.find_spec(name) is not None, "mux implementation missing"
    return importlib.import_module(name)


def selector(**changes):
    return dict(
        store_id=uuid4(),
        device_id=uuid4(),
        channel_id=uuid4(),
        expected_generation=1,
        inventory_revision=2,
        **changes,
    )


def test_shared_selector_wall_ref_and_session_scope():
    wall, focus = uuid4(), uuid4()
    request = LocalLiveRequest(**selector(wall_id=wall, focus_ref_id=focus))
    assert request.wall_id == wall and request.focus_ref_id == focus
    assert request.stream == "main"
    assert set(LocalLiveResponse.model_fields) == {"lease", "request_id"}


@pytest.mark.parametrize(
    "field", ["actor_id", "session_digest", "native_generation", "task_id", "authority"]
)
def test_no_body_authority_or_unknown_public_fields(field):
    with pytest.raises(ValidationError):
        LocalLiveRequest(**(selector() | {field: "private-marker"}))


def test_focus_body_is_explicitly_validated():
    contracts = mux_module("wso_contracts.tvt.local_media_mux")
    assert contracts.LocalFocusRequest(direction="FORWARD").direction == "FORWARD"
    for value in [
        {},
        {"direction": "forward"},
        {"direction": "RETURN", "deadline_at": "2026-10-06T00:00:00Z"},
    ]:
        with pytest.raises(ValidationError):
            contracts.LocalFocusRequest.model_validate(value)


def test_client_cannot_settle_attached_or_native_cleanup():
    contracts = mux_module("wso_contracts.tvt.local_media_mux")
    for value in [
        {"outcome": "ATTACHED"},
        {"outcome": "CANCELLED", "cleanup_confirmed": True},
        {"outcome": "FAILED", "native_receipt": {}},
    ]:
        with pytest.raises(ValidationError):
            contracts.LocalFocusSettleRequest.model_validate(value)
    assert contracts.LocalFocusSettleRequest(outcome="FAILED").outcome == "FAILED"


def test_shared_mode_rejects_legacy_bypass():
    api = mux_module("wso_api.tvt.local_media_mux")
    with pytest.raises(LocalDeviceFailure) as failure:
        api.validate_mode_request(True, LocalLiveRequest(**selector()))
    assert failure.value.status == 422
    api.validate_mode_request(False, LocalLiveRequest(**selector()))
    with pytest.raises(LocalDeviceFailure):
        api.validate_mode_request(False, LocalLiveRequest(**selector(wall_id=uuid4())))


def test_no_body_authority_or_unknown_rpc_fields():
    rpc = mux_module("wso_tvt_bridge.local_media_mux_rpc")
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb

    request = pb.LocalMediaMuxRequest(
        context=pb.RpcContext(
            protocol_version=1,
            ticket="a" * 64,
            deadline_ms=1000,
            correlation_id="mux-test",
        )
    )
    rpc.validate_mux_request(request)
    foreign = pb.LocalMediaMuxRequest.FromString(
        request.SerializeToString() + b"\x12\x01x"
    )
    with pytest.raises(LocalDeviceFailure):
        rpc.validate_mux_request(foreign)
    nested = pb.LocalMediaMuxRequest.FromString(request.SerializeToString())
    nested.context.MergeFromString(b"\x2a\x01x")
    with pytest.raises(LocalDeviceFailure):
        rpc.validate_mux_request(nested)
    request.context.correlation_id = "x" * 1024
    with pytest.raises(LocalDeviceFailure):
        rpc.validate_mux_request(request)


def test_exact_wall_purpose_and_frozen_sql_arity():
    api = mux_module("wso_api.tvt.local_media_mux")

    class Session:
        def __init__(self):
            self.calls = []

        def execute(self, statement, parameters=None):
            self.calls.append((str(statement), parameters))
            return SimpleNamespace(scalar_one=lambda: "b" * 64)

    session = Session()
    issuer = api.LocalMuxTicketIssuer(session, lambda: 1000)
    wall = uuid4()
    assert issuer.issue_wall_control("a" * 64, wall, "heartbeat") == "b" * 64
    calls = [call for call in session.calls if "wall_control_issue" in call[0]]
    assert calls[-1][1] == {"s": "a" * 64, "wall": wall, "purpose": "WALL_HEARTBEAT"}
    assert "wall_control_issue(:s,:wall,:purpose)" in calls[-1][0]
    issuer.issue_wall_control("a" * 64, wall, "stop")
    assert [call for call in session.calls if "wall_control_issue" in call[0]][-1][1][
        "purpose"
    ] == "WALL_STOP"
    before = len(session.calls)
    with pytest.raises(LocalDeviceFailure):
        issuer.issue_wall_control("a" * 64, wall, "ATTACHED")
    assert len(session.calls) == before


def test_shared_issue_retains_exact_selectors_and_frozen_arity():
    api = mux_module("wso_api.tvt.local_media_mux")
    calls = []

    class Session:
        def execute(self, statement, parameters):
            calls.append((str(statement), parameters))
            return SimpleNamespace(scalar_one=lambda: "b" * 64)

    issuer = api.LocalMuxTicketIssuer(Session(), lambda: 1000)
    connection, wall, focus = uuid4(), uuid4(), uuid4()
    request = LocalLiveRequest(**selector(wall_id=wall, focus_ref_id=focus))
    assert issuer.issue_shared("a" * 64, connection, request) == "b" * 64
    issue = [call for call in calls if "shared_issue" in call[0]]
    assert len(issue) == 1
    assert (
        "shared_issue(:s,:c,:store,:device,:channel,:gen,:rev,:stream,:ttl,:wall,:focus)"
        in issue[0][0]
    )
    assert issue[0][1] == {
        "s": "a" * 64,
        "c": connection,
        "store": request.store_id,
        "device": request.device_id,
        "channel": request.channel_id,
        "gen": 1,
        "rev": 2,
        "stream": "main",
        "ttl": 30,
        "wall": wall,
        "focus": focus,
    }
    with pytest.raises(LocalDeviceFailure):
        issuer.issue_shared("a" * 64, connection, LocalLiveRequest(**selector()))
    assert len([call for call in calls if "shared_issue" in call[0]]) == 1


def test_wall_routes_authenticate_before_body_and_default_off():
    from fastapi.testclient import TestClient
    from wso_api.main import create_app

    app = create_app()
    assert app.state.tvt_local_media_shared_enabled is False
    client = TestClient(app)
    tenant, wall, lease, reference = (str(uuid4()) for _ in range(4))
    paths = [
        f"/live-walls?tenant_id={tenant}",
        f"/live-walls/{wall}/heartbeat?tenant_id={tenant}",
        f"/live-walls/{wall}/stop?tenant_id={tenant}",
        f"/live-sessions/{lease}/focus-reservations?tenant_id={tenant}",
        f"/live-walls/{wall}/focus-reservations/{reference}/settle?tenant_id={tenant}",
    ]
    for path in paths:
        response = client.post(
            "/api/v1/tvt" + path,
            content=b"private-marker",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 401 and "private-marker" not in response.text


def test_last_wall_stop_remains_stopping_until_epoch_receipt():
    api = mux_module("wso_api.tvt.local_media_mux")
    tenant, wall = uuid4(), uuid4()
    view = api.public_wall(
        {
            "id": str(wall),
            "state": "STOPPING",
            "expires_at": datetime.now(UTC).isoformat(),
        },
        tenant,
        wall,
    )
    assert view.state == "STOPPING"
    with pytest.raises(LocalDeviceFailure):
        api.public_wall(
            {
                "id": str(uuid4()),
                "state": "CLOSED",
                "expires_at": datetime.now(UTC).isoformat(),
            },
            tenant,
            wall,
        )


def test_mux_response_is_bounded_closed_and_correlated():
    rpc = mux_module("wso_tvt_bridge.local_media_mux_rpc")
    payload = {"id": str(uuid4()), "request_id": "mux-test"}
    assert rpc.checked_mux_json(
        json.dumps(payload).encode(), "focus_reserve", "mux-test"
    ).id
    for bad in [
        payload | {"request_id": "foreign"},
        payload | {"master_id": str(uuid4())},
    ]:
        with pytest.raises(LocalDeviceFailure):
            rpc.checked_mux_json(json.dumps(bad).encode(), "focus_reserve", "mux-test")
    with pytest.raises(LocalDeviceFailure):
        rpc.checked_mux_json(b" " * 262145, "focus_reserve", "mux-test")


def test_server_focus_deadline_is_clipped_and_not_public():
    api = mux_module("wso_api.tvt.local_media_mux")
    now = datetime.now(UTC)
    assert api.focus_deadline(now, now + timedelta(seconds=5)) == now + timedelta(
        seconds=5
    )
    assert api.focus_deadline(now, now + timedelta(minutes=5)) == now + timedelta(
        seconds=20
    )


def test_stop_wall_result_preserves_exact_one_shot_identity():
    from wso_core.tvt.local_media_mux_service import DeviceEpochCoordinator
    from wso_core.tvt.local_service import LocalVerifyBudget

    assert hasattr(DeviceEpochCoordinator, "stop_wall_result"), "identity port missing"
    wall = uuid4()
    calls = []
    coordinator = object.__new__(DeviceEpochCoordinator)
    coordinator.admission = SimpleNamespace(
        redeem_wall_stop=lambda ticket, *, budget: (
            calls.append(("redeem", ticket)) or wall
        )
    )
    coordinator.stop_wall = lambda identity, *, budget: (
        calls.append(("stop", identity)) or False
    )
    assert coordinator.stop_wall_result("a" * 64, budget=LocalVerifyBudget(1000)) == (
        wall,
        False,
    )
    assert calls == [("redeem", "a" * 64), ("stop", wall)]


def test_rpc_mux_registered_and_legacy_start_denied_in_shared_mode(tmp_path):
    from wso_contracts.tvt.local_media import LocalLiveResponse
    from wso_tvt_bridge.client import AccountRpcClient, ClientConfig
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig

    from tests.tvt_parity.test_bridge_mtls import StrictExecutor, certs
    from tests.tvt_parity.test_local_media_rpc_api import public_view

    rpc = mux_module("wso_tvt_bridge.local_media_mux_rpc")
    wall, focus = uuid4(), uuid4()
    calls = []

    class Worker:
        def start_shared(self, ticket, **kwargs):
            calls.append(("start", ticket))
            return LocalLiveResponse.model_validate(
                public_view() | {"request_id": kwargs["correlation_id"]}
            )

        def wall_heartbeat(self, ticket, **kwargs):
            calls.append(("heartbeat", ticket))
            return rpc.LocalMuxAck(id=wall, request_id=kwargs["correlation_id"])

        def stop_wall(self, ticket, **kwargs):
            calls.append(("stop", ticket))
            return rpc.LocalMuxAck(id=wall, request_id=kwargs["correlation_id"])

        def focus_reserve(self, ticket, **kwargs):
            calls.append(("reserve", ticket))
            return rpc.LocalMuxAck(id=focus, request_id=kwargs["correlation_id"])

        def focus_settle(self, ticket, **kwargs):
            calls.append(("settle", ticket))
            return rpc.LocalMuxAck(id=focus, request_id=kwargs["correlation_id"])

    class Legacy:
        def start(self, *args, **kwargs):
            raise AssertionError("shared profile reached legacy admission")

    certs(tmp_path)
    server = AccountRpcServer(
        ServerConfig(
            "localhost:0",
            (tmp_path / "ca.pem").read_bytes(),
            (tmp_path / "server.pem").read_bytes(),
            (tmp_path / "server.key").read_bytes(),
            frozenset({"api.test"}),
            2,
        ),
        StrictExecutor(tmp_path),
        local_media_worker=Legacy(),
        local_media_mux_worker=Worker(),
        shared_media_enabled=True,
    )
    port = server.start()
    client = AccountRpcClient(
        ClientConfig(
            f"localhost:{port}",
            (tmp_path / "ca.pem").read_bytes(),
            (tmp_path / "client.pem").read_bytes(),
            (tmp_path / "client.key").read_bytes(),
        )
    )
    mux = rpc.LocalMuxRpcClient(client)
    try:
        with pytest.raises(LocalDeviceFailure) as failure:
            client.live_start(
                "a" * 64, deadline_ms=1000, correlation_id="legacy-bypass"
            )
        assert failure.value.code == "LOCAL_DEVICE_INPUT_INVALID"
        assert (
            mux.start_shared(
                "b" * 64, deadline_ms=1000, correlation_id="shared-start"
            ).lease.kind
            == "live"
        )
        for action, expected in [
            ("wall_heartbeat", wall),
            ("stop_wall", wall),
            ("focus_reserve", focus),
            ("focus_settle", focus),
        ]:
            assert (
                getattr(mux, action)(
                    "c" * 64, deadline_ms=1000, correlation_id=action
                ).id
                == expected
            )
        assert [call[0] for call in calls] == [
            "start",
            "heartbeat",
            "stop",
            "reserve",
            "settle",
        ]
    finally:
        client.close()
        assert server.close()


def test_worker_adapter_uses_exact_purpose_coordinator_ports():
    rpc = mux_module("wso_tvt_bridge.local_media_mux_rpc")
    wall, focus = uuid4(), uuid4()
    calls = []
    grant = object()

    class Coordinator:
        def heartbeat(self, ticket, *, budget):
            calls.append(("heartbeat", ticket))
            return wall

        def reserve_focus(self, ticket, *, budget):
            calls.append(("reserve", ticket))
            return grant

        def settle_focus_control(self, ticket, *, budget):
            calls.append(("settle", ticket))
            return focus

        def stop_wall_result(self, ticket, *, budget):
            calls.append(("stop", ticket))
            return wall, False

    admission = SimpleNamespace(
        focus_identity=lambda value: (
            (focus, wall)
            if value is grant
            else (_ for _ in ()).throw(AssertionError("copied grant"))
        )
    )
    adapter = rpc.LocalMuxWorkerAdapter(
        SimpleNamespace(
            executor=SimpleNamespace(coordinator=Coordinator(), admission=admission)
        )
    )
    for action, expected in [
        ("wall_heartbeat", wall),
        ("focus_reserve", focus),
        ("focus_settle", focus),
        ("stop_wall", wall),
    ]:
        assert (
            getattr(adapter, action)(
                "a" * 64, deadline_ms=1000, correlation_id="test"
            ).id
            == expected
        )
    assert [call[0] for call in calls] == ["heartbeat", "reserve", "settle", "stop"]


@pytest.mark.parametrize(
    "state",
    [
        "PENDING",
        "MAIN_ACTIVE",
        "ATTACHED",
        "CONSUMED",
        "CANCELLED",
        "FAILED",
        "EXPIRED",
    ],
)
def test_focus_public_readback_derives_scope_from_sql_and_maps_actual_state(
    monkeypatch, state
):
    api = mux_module("wso_api.tvt.local_media_mux")
    from tests.tvt_parity.test_local_media_rpc_api import public_view

    lease = LocalLiveResponse.model_validate(public_view()).lease
    focus, wall = uuid4(), uuid4()
    row = {
        "id": str(focus),
        "wall_id": str(wall),
        "lease_id": str(lease.id),
        "direction": "FORWARD",
        "state": state,
        "expires_at": datetime.now(UTC).isoformat(),
    }
    issuer = SimpleNamespace(
        read_focus=lambda digest, reference: row,
        _session=object(),
        _remaining=lambda: 1000,
    )
    monkeypatch.setattr(
        api,
        "LocalMediaReader",
        lambda *args: SimpleNamespace(get=lambda digest, identity: lease),
    )
    view = api._public_focus(
        issuer,
        "a" * 64,
        focus,
        lease.owner.tenant_id,
        lease.owner.actor_user_id,
        wall=wall,
        source=lease.id,
        direction="FORWARD",
    )
    assert view.state == {"PENDING": "PENDING", "MAIN_ACTIVE": "ACTIVE"}.get(
        state, "CLOSED"
    )
    assert (
        view.connection_id == lease.owner.connection_id
        and view.channel_id == lease.channel
    )
    with pytest.raises(LocalDeviceFailure):
        api._public_focus(issuer, "a" * 64, focus, uuid4(), lease.owner.actor_user_id)
    with pytest.raises(LocalDeviceFailure):
        api._public_focus(
            issuer,
            "a" * 64,
            focus,
            lease.owner.tenant_id,
            lease.owner.actor_user_id,
            wall=uuid4(),
        )


def test_focus_settle_uses_scoped_wall_before_exact_three_argument_issue():
    api = mux_module("wso_api.tvt.local_media_mux")
    contracts = mux_module("wso_contracts.tvt.local_media_mux")
    wall, reference = uuid4(), uuid4()
    calls = []

    class Session:
        def execute(self, statement, parameters):
            calls.append((str(statement), parameters))
            row = {
                "id": str(reference),
                "wall_id": str(wall),
                "lease_id": str(uuid4()),
                "direction": "FORWARD",
                "state": "PENDING",
                "expires_at": datetime.now(UTC).isoformat(),
            }
            return SimpleNamespace(
                scalar_one=lambda: row if "focus_read" in str(statement) else "b" * 64
            )

    issuer = api.LocalMuxTicketIssuer(Session(), lambda: 1000)
    body = contracts.LocalFocusSettleRequest(outcome="CANCELLED")
    assert issuer.issue_focus_settle("a" * 64, wall, reference, body) == "b" * 64
    issue = [call for call in calls if "focus_settle_issue" in call[0]]
    assert issue == [
        (
            "SELECT public.wso_tvt_local_media_focus_settle_issue(:s,:focus,:outcome)",
            {"s": "a" * 64, "focus": reference, "outcome": "CANCELLED"},
        )
    ]
    with pytest.raises(LocalDeviceFailure):
        issuer.issue_focus_settle("a" * 64, uuid4(), reference, body)
    assert len([call for call in calls if "focus_settle_issue" in call[0]]) == 1


def test_generated_public_contracts_describe_only_public_mux_fields():
    from wso_api.main import create_app

    schema = create_app().openapi()
    models = schema["components"]["schemas"]
    assert models["LocalFocusRequest"]["additionalProperties"] is False
    assert set(models["LocalFocusRequest"]["properties"]) == {"direction"}
    assert set(models["LocalFocusSettleRequest"]["properties"]) == {"outcome"}
    assert set(models["LocalWallView"]["properties"]) == {
        "id",
        "tenant_id",
        "expires_at",
        "state",
    }
    assert set(models["LocalLiveResponse"]["properties"]) == {"lease", "request_id"}
    assert {"wall_id", "focus_ref_id"} <= set(models["LocalLiveRequest"]["properties"])
    assert (
        "/api/v1/tvt/live-walls/{wall_id}/focus-reservations/{reference_id}/settle"
        in schema["paths"]
    )


def test_api_wall_reader_uses_terminal_readonly_port():
    api = mux_module("wso_api.tvt.local_media_mux")
    calls = []
    wall = uuid4()

    class Session:
        def execute(self, statement, parameters):
            calls.append((str(statement), parameters))
            return SimpleNamespace(
                scalar_one=lambda: {
                    "id": str(wall),
                    "state": "STOPPING",
                    "expires_at": datetime.now(UTC).isoformat(),
                }
            )

    assert (
        api.LocalMuxTicketIssuer(Session(), lambda: 1000).read_wall("a" * 64, wall)[
            "state"
        ]
        == "STOPPING"
    )
    assert any(
        statement == "SELECT public.wso_tvt_local_media_wall_view(:s,:wall)"
        and parameters == {"s": "a" * 64, "wall": wall}
        for statement, parameters in calls
    )


@pytest.mark.parametrize("body", [{"direction": "FORWARD"}, {"direction": "RETURN"}])
def test_http_focus_body_is_validated_before_ticket_dispatch(monkeypatch, body):
    from fastapi.testclient import TestClient
    from wso_api.main import create_app
    from wso_api.tvt import local_media

    api = mux_module("wso_api.tvt.local_media_mux")
    authenticated = SimpleNamespace(
        user_id=uuid4(), expires_at=datetime.now(UTC) + timedelta(minutes=1)
    )
    monkeypatch.setattr(
        local_media, "_authenticate", lambda request: (object(), authenticated)
    )
    calls = []

    def dispatched(request, tenant_id, current, action, **kwargs):
        calls.append(kwargs["body"])
        raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)

    monkeypatch.setattr(api, "dispatch_mux", dispatched)
    client = TestClient(create_app(shared_media_enabled=True))
    path = f"/api/v1/tvt/live-sessions/{uuid4()}/focus-reservations?tenant_id={uuid4()}"
    assert client.post(path, json=body).status_code == 429
    assert calls[0].direction == body["direction"]
    for bad in [
        body | {"actor_id": str(uuid4())},
        {"direction": "forward"},
        {"direction": "FORWARD", "deadline_at": "2026-10-06T00:00:00Z"},
    ]:
        assert client.post(path, json=bad).status_code == 422
    assert len(calls) == 1


def test_http_control_bodies_are_empty_and_bounded(monkeypatch):
    from fastapi.testclient import TestClient
    from wso_api.main import create_app
    from wso_api.tvt import local_media

    monkeypatch.setattr(local_media, "_authenticate", lambda request: (None, None))
    client = TestClient(create_app())
    path = f"/api/v1/tvt/live-walls?tenant_id={uuid4()}"
    assert client.post(path, json={}).status_code == 404
    for body in [
        b'{"actor_id":"private-marker"}',
        b"{}" + b" " * 4095,
        b"[]",
        b"null",
        b'{"a":1,"a":1}',
    ]:
        response = client.post(
            path, content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422 and "private-marker" not in response.text
    assert (
        client.post(
            path,
            content=b"{}" + b" " * 4094,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 404
    )


def test_http_shared_start_missing_wall_fails_before_worker_or_sql(monkeypatch):
    from fastapi.testclient import TestClient
    from wso_api.main import create_app
    from wso_api.tvt import local_media

    monkeypatch.setattr(local_media, "_authenticate", lambda request: (None, None))
    client = TestClient(create_app(shared_media_enabled=True))
    path = f"/api/v1/tvt/live-sessions?tenant_id={uuid4()}&connection_id={uuid4()}"
    body = {
        key: str(value) if hasattr(value, "hex") else value
        for key, value in selector().items()
    }
    assert client.post(path, json=body).status_code == 422
    assert client.post(path, json=body | {"wall_id": str(uuid4())}).status_code == 422


def test_stop_response_uses_fresh_scoped_stopping_readback(monkeypatch):
    from contextlib import contextmanager

    from starlette.requests import Request
    from wso_api.auth import SESSION_COOKIE
    from wso_core.tvt.local_service import LocalVerifyBudget

    api = mux_module("wso_api.tvt.local_media_mux")
    rpc = mux_module("wso_tvt_bridge.local_media_mux_rpc")
    tenant, actor, wall = uuid4(), uuid4(), uuid4()
    events = []
    active = [False]

    @contextmanager
    def tenant_scope(*args, **kwargs):
        active[0] = True
        events.append("scope-enter")
        try:
            yield SimpleNamespace(session=object())
        finally:
            active[0] = False
            events.append("scope-commit")

    class Issuer:
        def __init__(self, *args):
            pass

        def issue_wall_control(self, digest, identity, purpose):
            assert active[0] and identity == wall and purpose == "stop"
            return "a" * 64

        def read_wall(self, digest, identity):
            assert active[0] and identity == wall
            events.append("readback")
            return {
                "id": str(wall),
                "state": "STOPPING",
                "expires_at": datetime.now(UTC).isoformat(),
            }

    def stopped(ticket, **kwargs):
        assert not active[0]
        events.append("worker")
        return rpc.LocalMuxAck(id=wall, request_id=kwargs["correlation_id"])

    app = SimpleNamespace(
        state=SimpleNamespace(
            tvt_local_media_shared_enabled=True,
            tvt_local_media_mux_worker=SimpleNamespace(stop_wall=stopped),
        )
    )
    request = Request(
        {
            "type": "http",
            "headers": [(b"cookie", f"{SESSION_COOKIE}=synthetic-cookie".encode())],
            "app": app,
            "state": {
                "local_media_budget": LocalVerifyBudget(1000),
                "request_id": "stop-test",
            },
        }
    )
    monkeypatch.setattr(api, "require_tenant", tenant_scope)
    monkeypatch.setattr(api, "LocalMuxTicketIssuer", Issuer)
    view = api.dispatch_mux(
        request,
        tenant,
        (None, SimpleNamespace(user_id=actor)),
        "stop_wall",
        wall_id=wall,
    )
    assert view.wall.state == "STOPPING"
    assert events == [
        "scope-enter",
        "scope-commit",
        "worker",
        "scope-enter",
        "readback",
        "scope-commit",
    ]
    monkeypatch.setattr(
        app.state.tvt_local_media_mux_worker,
        "stop_wall",
        lambda ticket, **kwargs: rpc.LocalMuxAck(
            id=uuid4(), request_id=kwargs["correlation_id"]
        ),
    )
    with pytest.raises(LocalDeviceFailure) as failure:
        api.dispatch_mux(
            request,
            tenant,
            (None, SimpleNamespace(user_id=actor)),
            "stop_wall",
            wall_id=wall,
        )
    assert failure.value.status == 502


def test_timed_out_rpc_retains_original_active_call_until_worker_returns():
    from threading import Event, Thread

    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.session_pool import SessionPool

    rpc = mux_module("wso_tvt_bridge.local_media_mux_rpc")
    entered, release = Event(), Event()
    disposed = []
    results = []
    wall = uuid4()

    class Worker:
        def stop_wall(self, ticket, **kwargs):
            entered.set()
            assert release.wait(2)
            return rpc.LocalMuxAck(id=wall, request_id=kwargs["correlation_id"])

    class Context:
        active = True
        callback = None

        def auth_context(self):
            return {
                "transport_security_type": [b"ssl"],
                "x509_subject_alternative_name": [b"api.test"],
            }

        def peer_identity_key(self):
            return "x509_subject_alternative_name"

        def time_remaining(self):
            return 1

        def is_active(self):
            return self.active

        def add_callback(self, callback):
            self.callback = callback
            return True

    pool = SessionPool(capacity=1, dispose=lambda: disposed.append("closed"))
    context = Context()
    service = rpc.LocalMediaMuxRpcService(
        Worker(), SimpleNamespace(client_sans={"api.test"}), pool
    )
    request = pb.LocalMediaMuxRequest(
        context=pb.RpcContext(
            protocol_version=1,
            ticket="a" * 64,
            deadline_ms=1000,
            correlation_id="retained",
        )
    )
    thread = Thread(target=lambda: results.append(service.StopWall(request, context)))
    thread.start()
    try:
        assert entered.wait(1)
        context.active = False
        context.callback()
        assert pool.close(grace=0) is False
        assert pool.registry.active_count == 1 and disposed == []
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and disposed == ["closed"]
    assert results[0].failure_code == "LOCAL_DEVICE_CANCELLED"


@pytest.mark.parametrize("mode", ["sub", "main"])
def test_source_mode_is_explicit_and_requires_completed_retained_entry(mode):
    from wso_core.tvt.local_media_mux_service import MuxMediaExecutor

    from tests.tvt_parity.test_local_media_mux_service import attached_pair, main_setup

    assert hasattr(MuxMediaExecutor, "source_mode"), (
        "explicit source discriminator missing"
    )
    if mode == "sub":
        coordinator, admission, _, _, lease, _, _, _ = attached_pair()
        entry = coordinator._viewers[lease.id]
    else:
        coordinator, admission, _, _, _, lease, _ = main_setup()
        entry = coordinator._dedicated[lease.id]
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    assert executor.source_mode(lease.id) == mode
    with pytest.raises(LocalDeviceFailure):
        executor.source_mode(uuid4())
    entry.starting = True
    with pytest.raises(LocalDeviceFailure):
        executor.source_mode(lease.id)
    entry.starting = False
    entry.stopping = True
    with pytest.raises(LocalDeviceFailure):
        executor.source_mode(lease.id)


def test_empty_wall_controls_redeem_without_native_operations():
    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.tvt_parity.test_local_media_mux_service import setup

    coordinator, admission, provider, budget, _ = setup()
    wall = admission.scope.wall_id
    admission.redeem_wall_stop = lambda ticket, *, budget: wall
    assert coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(1000)) == wall
    assert coordinator.stop_wall_result("stop", budget=LocalVerifyBudget(1000)) == (
        wall,
        True,
    )
    assert provider.calls == admission.login_calls == len(budget.reservations) == 0
    with pytest.raises(LocalDeviceFailure):
        coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(1000))


def test_empty_stop_fences_original_pending_reservation_before_native_start():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.tvt_parity.test_local_media_mux_service import setup

    coordinator, admission, provider, budget, lease = setup()
    entered, release = Event(), Event()
    original = admission.reserve_master

    def held_reserve(viewer, *, budget, attempt=None):
        reservation = original(viewer, budget=budget, attempt=attempt)
        entered.set()
        assert release.wait(2)
        return reservation

    admission.reserve_master = held_reserve
    admission.redeem_wall_stop = lambda ticket, *, budget: admission.scope.wall_id
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(coordinator._master, lease, LocalVerifyBudget(2000))
        try:
            assert entered.wait(1)
            assert coordinator.stop_wall_result(
                "stop", budget=LocalVerifyBudget(1000)
            ) == (admission.scope.wall_id, False)
            assert provider.calls == len(budget.reservations) == 0
        finally:
            release.set()
        with pytest.raises(LocalDeviceFailure):
            pending.result()
    assert provider.calls == admission.login_calls == len(budget.reservations) == 0
    assert coordinator._records == {}
    assert coordinator.stop_wall_result("stop", budget=LocalVerifyBudget(1000)) == (
        admission.scope.wall_id,
        False,
    )
    assert any(
        held is admission.reservation
        for held in coordinator._unadopted_reservations.values()
    )
    from dataclasses import replace

    _new_wall_reservation(admission)
    provider.prepared.release.set()
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(
            replace(lease, id=uuid4(), native_generation=uuid4()),
            LocalVerifyBudget(1000),
        )
    assert provider.calls == 0
    assert coordinator.shutdown() is False


def test_shutdown_keeps_pending_sql_reservation_charged_after_late_callback():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.tvt_parity.test_local_media_mux_service import setup

    coordinator, admission, provider, _, lease = setup()
    entered, release = Event(), Event()
    original = admission.reserve_master

    def held_reserve(viewer, *, budget, attempt=None):
        reservation = original(viewer, budget=budget, attempt=attempt)
        entered.set()
        assert release.wait(2)
        return reservation

    admission.reserve_master = held_reserve
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(coordinator._master, lease, LocalVerifyBudget(2000))
        try:
            assert entered.wait(1)
            assert coordinator.shutdown() is False
        finally:
            release.set()
        with pytest.raises(LocalDeviceFailure):
            pending.result()
    assert coordinator.shutdown() is False
    assert provider.calls == 0


def test_wall_controls_preserve_bound_wall_affinity_and_closed_guard():
    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.tvt_parity.test_local_media_mux_service import attached_pair, setup

    coordinator, admission, provider, _, _, _, _, _ = attached_pair()
    foreign = uuid4()
    admission.redeem_wall_heartbeat = lambda ticket, *, budget: foreign
    admission.redeem_wall_stop = lambda ticket, *, budget: foreign
    with pytest.raises(LocalDeviceFailure):
        coordinator.heartbeat("foreign", budget=LocalVerifyBudget(1000))
    with pytest.raises(LocalDeviceFailure):
        coordinator.stop_wall_result("foreign", budget=LocalVerifyBudget(1000))
    assert not provider.prepared.closing
    fresh, admission, provider, _, _ = setup()
    admission.redeem_wall_stop = lambda ticket, *, budget: admission.scope.wall_id
    fresh._closed = True
    with pytest.raises(LocalDeviceFailure):
        fresh.heartbeat("heartbeat", budget=LocalVerifyBudget(1000))
    with pytest.raises(LocalDeviceFailure):
        fresh.stop_wall_result("stop", budget=LocalVerifyBudget(1000))
    assert provider.calls == 0


def _new_wall_reservation(admission, *, foreign_actor=False):
    from dataclasses import replace

    from wso_core.tvt.local_media_mux_types import _GRANT_SEAL

    scope = replace(
        admission.scope,
        wall_id=uuid4(),
        actor_user_id=uuid4() if foreign_actor else admission.scope.actor_user_id,
    )
    admission.scope = scope
    admission.transport = replace(
        admission.transport, scope=scope, native_generation=uuid4(), _seal=_GRANT_SEAL
    )
    admission.reservation = replace(
        admission.reservation,
        scope=scope,
        transport=admission.transport,
        master_id=uuid4(),
        _seal=_GRANT_SEAL,
    )
    admission.calls = 0
    admission.registered = None
    return scope.wall_id


def test_new_same_session_wall_waits_for_exact_completed_originals():
    from dataclasses import replace

    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.tvt_parity.test_local_media_mux_service import attached_pair

    coordinator, admission, provider, budget, first, _, _, _ = attached_pair()
    old_wall = admission.scope.wall_id
    provider.prepared.can_close = True
    admission.redeem_wall_stop = lambda ticket, *, budget: old_wall
    assert coordinator.stop_wall_result("stop", budget=LocalVerifyBudget(1000)) == (
        old_wall,
        True,
    )
    new_wall = _new_wall_reservation(admission)
    new_lease = replace(first, id=uuid4(), native_generation=uuid4())
    result = coordinator._master(new_lease, LocalVerifyBudget(1000))
    assert result.scope.wall_id == new_wall
    assert coordinator._actor[4] == new_wall
    assert old_wall in coordinator._stopped_walls
    assert len(budget.reservations) == 1


@pytest.mark.parametrize("boundary", ["unsettled", "pending", "foreign_actor"])
def test_new_wall_cannot_reset_pending_or_foreign_original_affinity(boundary):
    from dataclasses import replace

    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.tvt_parity.test_local_media_mux_service import attached_pair

    coordinator, admission, provider, _, first, _, _, _ = attached_pair()
    old_actor = coordinator._actor
    if boundary != "unsettled":
        provider.prepared.can_close = True
        assert coordinator.stop_wall(old_actor[4], budget=LocalVerifyBudget(1000))
    _new_wall_reservation(admission, foreign_actor=boundary == "foreign_actor")
    if boundary == "pending":
        coordinator._pending_reservations = 1
    new_lease = replace(first, id=uuid4(), native_generation=uuid4())
    calls = provider.calls
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(new_lease, LocalVerifyBudget(1000))
    assert coordinator._actor == old_actor and provider.calls == calls
    assert any(
        held is admission.reservation
        for held in coordinator._unadopted_reservations.values()
    )
    if boundary == "pending":
        # Complete the other inert operation; the returned denied reservation
        # must still independently block shutdown and affinity reuse.
        coordinator._pending_reservations = 0
    assert coordinator.shutdown() is False


def test_fix_r1_retains_each_same_master_reservation_without_replacing_original():
    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.tvt_parity.test_local_media_mux_service import setup

    coordinator, admission, provider, _, lease = setup()
    coordinator._stopped_walls.add(admission.scope.wall_id)
    returned = []
    original = admission.reserve_master

    def returning(viewer, *, budget, attempt=None):
        reservation = original(viewer, budget=budget, attempt=attempt)
        returned.append(reservation)
        return reservation

    admission.reserve_master = returning
    for _ in range(2):
        with pytest.raises(LocalDeviceFailure):
            coordinator._master(lease, LocalVerifyBudget(1000))
    assert returned[0] is not returned[1]
    assert returned[0].master_id == returned[1].master_id
    assert all(
        any(
            held is reservation for held in coordinator._unadopted_reservations.values()
        )
        for reservation in returned
    )
    assert coordinator.shutdown() is False and provider.calls == 0


def test_fix_r1_identity_rejection_retains_returned_reservation_and_original():
    from dataclasses import replace

    from wso_core.tvt.local_media_mux_types import _GRANT_SEAL
    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.tvt_parity.test_local_media_mux_service import attached_pair

    coordinator, admission, provider, _, _, _, _, _ = attached_pair()
    original = coordinator._records[admission.reservation.master_id]
    creator = original.reservation
    transport = original.transport
    changed_scope = replace(admission.scope, secret_version=uuid4())
    changed_grant = replace(transport, scope=changed_scope, _seal=_GRANT_SEAL)
    returned = replace(
        admission.reservation,
        scope=changed_scope,
        transport=changed_grant,
        _seal=_GRANT_SEAL,
    )
    admission.reserve_master = lambda viewer, *, budget, attempt=None: returned
    from wso_core.tvt.local_media_admission import _SEAL, LocalMediaLease

    lease = LocalMediaLease(
        "a" * 64, admission.scope.worker_epoch, uuid4(), uuid4(), _SEAL
    )
    calls = provider.calls
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    assert original.reservation is creator and original.transport is transport
    assert any(
        held is returned for held in coordinator._unadopted_reservations.values()
    )
    assert coordinator.shutdown() is False and provider.calls == calls


def test_fix_r1_authentic_admission_exception_retains_exact_operation():
    from threading import BoundedSemaphore, Lock

    from wso_core.tvt.local_media_mux_admission import SqlMuxAdmission
    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.tvt_parity.test_local_media_mux_service import setup

    coordinator, next_admission, provider, _, lease = setup()
    admission = object.__new__(SqlMuxAdmission)
    admission.worker_epoch = lease.worker_epoch
    admission._mux_lock = Lock()
    admission._startup_slots = BoundedSemaphore(1)
    admission._pending_reservations = {}
    admission._clock = lambda: 1.0
    admission._mux_closed = admission._authority_closed = False
    admission._issuer = object()
    admission._issued_leases = {id(lease): lease}
    admission._attempts = {}
    admission._attempt_leases = {}
    admission._lease_cleanup = set()
    admission._lease_masters = {}
    admission._denied_masters = set()
    admission._authority_lock = Lock()
    admission._tombstones = {}
    admission._authorities = {}

    def uncertain_sql(*args):
        raise LocalDeviceFailure("LOCAL_DEVICE_UNAVAILABLE", 503)

    admission._sql = uncertain_sql
    coordinator.admission = admission
    budget = LocalVerifyBudget(1000)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, budget)
    assert len(admission._pending_reservations) == 1
    assert next(iter(admission._pending_reservations.values()))[0] is lease
    assert coordinator._pending_reservations == 1
    operations = tuple(coordinator._reservation_operations.values())
    assert len(operations) == 1 and operations[0].viewer is lease
    assert operations[0].budget is budget and operations[0].failed is True
    assert getattr(operations[0], "admission", None) is admission
    assert coordinator._affinity_settled() is False
    # Another successful admission reply cannot make the earlier uncertain
    # operation disappear or let an unbound coordinator adopt a new wall.
    _new_wall_reservation(next_admission)
    coordinator.admission = next_admission
    provider.prepared.release.set()
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    assert next(iter(coordinator._reservation_operations.values())) is operations[0]
    assert coordinator.shutdown() is False and provider.calls == 0


def test_mux_routes_enforce_real_session_csrf_and_origin_before_parse():
    from fastapi.testclient import TestClient
    from wso_api.auth import SESSION_COOKIE, AuthService, WebSession, token_digest
    from wso_api.main import create_app

    app = create_app()
    service = object.__new__(AuthService)
    service.settings = SimpleNamespace(public_origin="https://app.example.test")
    principal = WebSession(
        "issuer",
        "subject",
        uuid4(),
        token_digest("synthetic-csrf"),
        datetime.now(UTC) + timedelta(minutes=1),
    )
    service.sessions = SimpleNamespace(
        get=lambda digest: (
            principal if digest == token_digest("synthetic-cookie") else None
        )
    )
    app.state.auth_service = service
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, "synthetic-cookie")
    paths = [
        "/api/v1/tvt/live-walls?tenant_id=bad",
        f"/api/v1/tvt/live-sessions/{uuid4()}/focus-reservations?tenant_id=bad",
        f"/api/v1/tvt/live-walls/{uuid4()}/focus-reservations/{uuid4()}/settle?tenant_id=bad",
    ]
    for path in paths:
        for headers in [
            {},
            {
                "Origin": "https://foreign.example.test",
                "X-CSRF-Token": "synthetic-csrf",
            },
            {"Origin": "https://app.example.test", "X-CSRF-Token": "wrong"},
        ]:
            response = client.post(path, content=b"private-marker", headers=headers)
            assert response.status_code == 403 and "private-marker" not in response.text
            assert response.headers["cache-control"] == "no-store"
        response = client.post(
            path,
            content=b"private-marker",
            headers={
                "Origin": "https://app.example.test",
                "X-CSRF-Token": "synthetic-csrf",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 422
