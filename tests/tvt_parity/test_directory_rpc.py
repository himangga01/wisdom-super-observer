"""Fixed directory transport proof; synthetic workers do not prove SQL authority."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import pytest
from wso_contracts.tvt.directory import (
    REQUEST_TYPES,
    DeviceListRequest,
    DirectoryView,
    ObservationField,
    ObservationObject,
)
from wso_core.tvt.account_projection import AccountFailure

SCOPE = {
    "identity_id": UUID("00000000-0000-4000-8000-000000000001"),
    "region": "eu",
    "brand": "tvt",
}
EXTRA = {
    "channel_list": {"sn_list": ("synthetic-selector",)},
    "device_detail": {"sn": "synthetic-selector"},
    "channel_detail": {"sn": "synthetic-selector", "chl_index": 0},
}


def body(method="device_list"):
    return REQUEST_TYPES[method](**SCOPE, **EXTRA.get(method, {}))


class SyntheticDirectory:
    def __init__(self):
        self.calls = []
        self.entered, self.release = Event(), Event()
        self.change = {}

    def execute(self, method, ticket, request, *, deadline_ms, correlation_id):
        assert type(request) is REQUEST_TYPES[method]
        assert 0 < deadline_ms <= 10000
        self.calls.append((method, request))
        if ticket.startswith("dd"):
            self.entered.set()
            self.release.wait(2)
        if ticket.startswith("ee"):
            raise AccountFailure("TOKEN_EXPIRED", 401)
        if ticket.startswith("ff"):
            raise ValueError("PRIVATE-DETAIL")
        return DirectoryView(
            **SCOPE, method=method, generation=1, request_id=correlation_id, records=()
        ).model_copy(update=self.change)


@pytest.fixture
def transport(tmp_path, request):
    from test_bridge_mtls import StrictExecutor, certs
    from wso_tvt_bridge.client import AccountRpcClient, ClientConfig
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig

    certs(tmp_path)
    worker, disposed = SyntheticDirectory(), []
    config = ServerConfig(
        "localhost:0",
        (tmp_path / "ca.pem").read_bytes(),
        (tmp_path / "server.pem").read_bytes(),
        (tmp_path / "server.key").read_bytes(),
        frozenset({"api.test"}),
        1,
    )
    server = AccountRpcServer(
        config,
        StrictExecutor(tmp_path),
        directory_worker=worker if getattr(request, "param", True) else None,
        dispose=lambda: disposed.append("closed"),
    )
    port = server.start()
    clients = []

    def make(label="client", ca=None, endpoint=None):
        client = AccountRpcClient(
            ClientConfig(
                endpoint or f"localhost:{port}",
                ca or config.ca,
                (tmp_path / f"{label}.pem").read_bytes(),
                (tmp_path / f"{label}.key").read_bytes(),
            )
        )
        clients.append(client)
        return client

    try:
        yield server, worker, make, disposed
    finally:
        worker.release.set()
        for client in clients:
            client.close()
        server.close()
        for path in tmp_path.rglob("*"):
            if path.is_file() and path.suffix in {".pem", ".key"}:
                path.unlink()


def test_fixed_six_on_one_verified_channel(transport):
    server, worker, make, _ = transport
    client = make()
    channel = client._channel
    for method in REQUEST_TYPES:
        result = getattr(client, "directory_" + method)(
            "01" * 32, body(method), deadline_ms=3000, correlation_id=method
        )
        assert result.method == method and result.identity_id == SCOPE["identity_id"]
        assert result.complete is None and result.grants_operations is False
        assert client._channel is channel
    assert [call[0] for call in worker.calls] == list(REQUEST_TYPES)
    assert server.pool.registry.active_count == 0


@pytest.mark.parametrize(
    "change",
    [
        {"identity_id": UUID(int=2)},
        {"region": "us"},
        {"brand": "other"},
        {"method": "sent_shares"},
        {"generation": 0},
        {"request_id": "wrong"},
        {"complete": True},
        {"grants_operations": True},
        {
            "records": (
                ObservationObject(
                    fields=(
                        ObservationField(name="sn", state="missing", value="secret"),
                    )
                ),
            )
        },
    ],
)
def test_worker_result_is_revalidated_and_bound_to_scope(transport, change):
    _, worker, make, _ = transport
    worker.change = change
    with pytest.raises(AccountFailure, match="ACCOUNT_PROTOCOL_INVALID"):
        make().directory_device_list(
            "01" * 32, body(), deadline_ms=3000, correlation_id="scope"
        )


@pytest.mark.parametrize(
    "payload",
    [
        b'{"method":"device_list","method":"device_list"}',
        b'{"token":"secret"}',
        b'{"page_num":NaN}',
        b"[" * 10000,
        b"x" * 65537,
    ],
    ids=["duplicate", "extra", "nonfinite", "depth", "bound"],
)
def test_closed_query_rejects_malformed_duplicate_nonfinite_extra_and_bound(payload):
    from wso_tvt_bridge.selected import decode_directory_input

    with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
        decode_directory_input(payload, "device_list")


def test_canonical_query_uses_65536_policy_and_exact_type():
    from wso_contracts.tvt.directory import canonical_request
    from wso_tvt_bridge.selected import decode_directory_input, encode_directory_input

    value = body("channel_list")
    assert encode_directory_input("channel_list", value) == canonical_request(
        "channel_list", value
    ).encode("ascii")
    assert (
        decode_directory_input(
            encode_directory_input("channel_list", value), "channel_list"
        )
        == value
    )
    for bad in (
        body(),
        body("channel_list").model_copy(update={"method": "device_list"}),
    ):
        with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
            encode_directory_input("channel_list", bad)


def canonical_overbound_utf8_query():
    from wso_contracts.tvt.directory import ChannelListRequest, canonical_request

    request = ChannelListRequest(
        **SCOPE, sn_list=tuple(str(index) + "\uac00" * 1000 for index in range(12))
    )
    value = request.model_dump(mode="json")
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    canonical = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    assert len(payload) < 65536 < len(canonical)
    with pytest.raises(ValueError, match="directory query exceeds local byte policy"):
        canonical_request("channel_list", request)
    return payload


def test_decoder_rejects_utf8_query_over_canonical_ascii_bound():
    from wso_tvt_bridge.selected import decode_directory_input

    with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
        decode_directory_input(canonical_overbound_utf8_query(), "channel_list")


def test_fixed_tls_canonical_overbound_query_never_invokes_worker(transport):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb

    server, worker, make, _ = transport
    request = pb.DirectoryChannelListRequest(
        context=pb.RpcContext(
            protocol_version=1,
            ticket="01" * 32,
            deadline_ms=3000,
            correlation_id="canonical-bound",
        ),
        query_json=canonical_overbound_utf8_query(),
    )
    reply = make()._directory_stub.ChannelList(request, timeout=3)
    assert reply.failure_code == "ACCOUNT_INPUT_INVALID" and not reply.public_json
    assert worker.calls == []
    assert server.pool.registry.active_count == 0


@pytest.mark.parametrize(
    "ticket,code", [("ee", "TOKEN_EXPIRED"), ("ff", "ACCOUNT_UNAVAILABLE")]
)
def test_safe_failure_and_expiry_distinction(transport, ticket, code):
    with pytest.raises(AccountFailure, match=code) as caught:
        transport[2]().directory_device_list(
            ticket * 32, body(), deadline_ms=3000, correlation_id="failure"
        )
    assert "PRIVATE" not in str(caught.value)


def test_budget_shared_capacity_and_close_during_request(transport):
    server, worker, make, disposed = transport
    client = make()
    with ThreadPoolExecutor(max_workers=1) as threads:
        pending = threads.submit(
            client.directory_device_list,
            "dd" * 32,
            body(),
            deadline_ms=100,
            correlation_id="slow",
        )
        assert worker.entered.wait(1)
        with pytest.raises(AccountFailure, match="UNKNOWN_OUTCOME"):
            pending.result(2)
        with pytest.raises(AccountFailure, match="SESSION_BUSY"):
            client.profile("02" * 32, deadline_ms=1000, correlation_id="shared")
        assert server.close(grace=0) is False and disposed == []
        worker.release.set()
    end = time.monotonic() + 2
    while server.pool.registry.active_count and time.monotonic() < end:
        time.sleep(0.01)
    assert disposed == ["closed"] and server.close(grace=0)


@pytest.mark.parametrize("transport", [False], indirect=True)
def test_optional_worker_absent_returns_safe_unavailable(transport):
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        transport[2]().directory_device_list(
            "01" * 32, body(), deadline_ms=3000, correlation_id="absent"
        )


def test_false_disposal_is_not_proved(transport):
    server = transport[0]
    server._dispose = lambda: False
    assert server.close(grace=0) is False
    assert server.close(grace=0) is False


def test_optional_closed_policy_loader(tmp_path):
    from wso_api.tvt.session_service import AccountEndpoint
    from wso_tvt_bridge.directory_config import load_directory_configuration

    endpoints = (
        AccountEndpoint("eu", "tvt", "https://example.invalid", "en", "US", "1.18.1"),
    )
    assert load_directory_configuration({}, endpoints) is None
    path = tmp_path / "profiles.json"
    env = {"WSO_TVT_DIRECTORY_PROFILE_FILE": str(path)}
    valid = {
        "region": "eu",
        "brand": "tvt",
        "profile_id": "profile",
        "consent_version": "v1",
    }
    path.write_text(json.dumps([valid]))
    policies = load_directory_configuration(env, endpoints)
    assert type(policies) is tuple and policies[0].profile_id == "profile"
    for value in (
        [],
        [valid, valid],
        [valid | {"token": "secret"}],
        [valid | {"brand": "other"}],
        [{k: v for k, v in valid.items() if k != "profile_id"}],
    ):
        path.write_text(json.dumps(value))
        with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
            load_directory_configuration(env, endpoints)


@pytest.mark.parametrize(
    "case",
    [
        "extra",
        "nested-extra",
        "unknown-name",
        "duplicate",
        "nonfinite",
        "both",
        "unknown-proto",
        "bound",
        "subclass",
    ],
)
def test_hostile_public_reply_never_crosses_client(transport, case):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.selected import encode_directory_input

    value = DirectoryView(
        **SCOPE, method="device_list", generation=1, request_id="reply", records=()
    ).model_dump(mode="json")
    if case == "extra":
        value["Actor"] = {"token": "secret"}
    elif case in {"nested-extra", "unknown-name", "nonfinite"}:
        value["records"] = [
            {
                "fields": [
                    {
                        "name": "token" if case == "unknown-name" else "sn",
                        "state": "value",
                        "value": float("nan") if case == "nonfinite" else "safe",
                        **({"cookie": "secret"} if case == "nested-extra" else {}),
                    }
                ]
            }
        ]
    raw = json.dumps(value).encode()
    if case == "duplicate":
        raw = raw[:-1] + b',"request_id":"reply"}'
    if case == "bound":
        raw = b"x" * 1048577
    reply = pb.DirectoryReply(public_json=raw)
    if case == "both":
        reply.failure_code = "TOKEN_EXPIRED"
    if case == "unknown-proto":
        reply = pb.DirectoryReply.FromString(reply.SerializeToString() + b"\x18\x01")
    if case == "subclass":

        class Extended(DirectoryView):
            token: str = "secret"

        transport[1].change = {}
        transport[1].execute = lambda *args, **kwargs: Extended(**value)
        with pytest.raises(AccountFailure, match="ACCOUNT_PROTOCOL_INVALID"):
            transport[2]().directory_device_list(
                "01" * 32, body(), deadline_ms=3000, correlation_id="reply"
            )
        return

    class Pending:
        def result(self):
            return reply

        def cancel(self):
            return True

    class Source:
        def future(self, request, *, timeout, wait_for_ready):
            assert request.query_json == encode_directory_input("device_list", body())
            assert not wait_for_ready and timeout <= 3
            return Pending()

    client = transport[2]()
    client._directory_stub.DeviceList = Source()
    with pytest.raises(AccountFailure) as caught:
        client.directory_device_list(
            "01" * 32, body(), deadline_ms=3000, correlation_id="reply"
        )
    assert caught.value.code in {"ACCOUNT_PROTOCOL_INVALID", "ACCOUNT_INPUT_INVALID"}
    assert "secret" not in str(caught.value)


def test_nested_constructed_private_field_is_rejected(transport):
    field = ObservationField.model_construct(name="sn", state="value", value="safe")
    field.__dict__["cookie"] = "secret"
    transport[1].change = {"records": (ObservationObject(fields=(field,)),)}
    with pytest.raises(AccountFailure, match="ACCOUNT_PROTOCOL_INVALID"):
        transport[2]().directory_device_list(
            "01" * 32, body(), deadline_ms=3000, correlation_id="nested"
        )


@pytest.mark.parametrize(
    "label,ca,endpoint",
    [("other", None, None), ("client", "foreign", None), ("client", None, "127.0.0.1")],
)
def test_tls_requires_ca_san_and_server_name(transport, tmp_path, label, ca, endpoint):
    from test_bridge_mtls import certs

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    certs(foreign)
    client = transport[2](
        label=label,
        ca=(foreign / "ca.pem").read_bytes() if ca else None,
        endpoint=f"{endpoint}:{transport[0]._port}" if endpoint else None,
    )
    with pytest.raises(AccountFailure) as caught:
        client.directory_device_list(
            "01" * 32, body(), deadline_ms=1000, correlation_id="tls"
        )
    assert caught.value.code in {"ACCOUNT_DENIED", "UNKNOWN_OUTCOME"}
    assert transport[1].calls == []


@pytest.mark.parametrize(
    "case",
    [
        "absent",
        "valid",
        "partial",
        "executor",
        "server",
        "close-false",
        "close-raise",
        "startup-quarantine",
    ],
)
def test_worker_bootstrap_cleans_all_resources_and_never_half_starts(
    tmp_path, monkeypatch, case
):
    from wso_api.tvt import device_service, session_service
    from wso_core import secrets
    from wso_core.tvt import directory_admission, token_vault
    from wso_tvt_bridge import server as module

    for name in tuple(module.os.environ):
        if name.startswith("WSO_"):
            monkeypatch.delenv(name)
    path = tmp_path / "profiles"
    path.write_text(
        json.dumps(
            [
                {
                    "region": "eu",
                    "brand": "tvt",
                    "profile_id": "profile",
                    "consent_version": "v1",
                }
            ]
        )
    )
    settings = {
        "WSO_TVT_BRIDGE_CLIENT_SANS_JSON": '["api.test"]',
        "WSO_TVT_BRIDGE_BIND": "localhost:0",
        "WSO_TVT_BRIDGE_CA_FILE": "ca",
        "WSO_TVT_BRIDGE_SERVER_CERT_FILE": "cert",
        "WSO_TVT_BRIDGE_SERVER_KEY_FILE": "key",
        "WSO_CONNECTION_KEY_FILE": "vault-key",
        "WSO_WORKER_DATABASE_URL": "synthetic-worker",
    }
    if case != "absent":
        settings["WSO_TVT_DIRECTORY_PROFILE_FILE"] = (
            "" if case == "partial" else str(path)
        )
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    events = []
    quarantine_before = len(getattr(module, "_BOOTSTRAP_QUARANTINE", ()))

    class Provider:
        def __init__(self, path):
            pass

        def encryption_key(self):
            return b"v" * 32

    class Vault:
        def __init__(self, *args):
            events.append("vault-created")

        def close(self):
            events.append("vault-closed")

    class Admission:
        def __init__(self, url, policies, provider):
            assert policies[0].profile_id == "profile"
            events.append("admission-created")

        def close(self):
            events.append("admission-closed")

    class Executor:
        def __init__(self, *args):
            if case == "executor":
                raise ValueError("PRIVATE")
            events.append("worker-created")

        def close(self, *, deadline_ms):
            assert deadline_ms == 1000
            events.append("worker-closed")
            if case == "close-raise":
                raise AccountFailure("ACCOUNT_QUARANTINED", 503)
            return False if case in {"close-false", "startup-quarantine"} else None

    class Server:
        def __init__(
            self, config, worker, *, dispose, flow_worker, directory_worker=None
        ):
            self.dispose = dispose
            events.append("server-created")
            assert (directory_worker is None) == (case == "absent")
            if case in {"server", "startup-quarantine"}:
                dispose()
                raise ValueError("PRIVATE")

    monkeypatch.setattr(module, "pem", lambda path: b"synthetic")
    monkeypatch.setattr(secrets, "FileKeyProvider", Provider)
    monkeypatch.setattr(token_vault, "TokenVault", Vault)
    monkeypatch.setattr(directory_admission, "DirectoryAdmission", Admission)
    monkeypatch.setattr(device_service, "DirectoryWorkerExecutor", Executor)
    monkeypatch.setattr(session_service, "AccountWorkerExecutor", lambda *a: object())
    monkeypatch.setattr(
        session_service,
        "load_account_endpoints",
        lambda: (
            session_service.AccountEndpoint(
                "eu", "tvt", "https://example.invalid", "en", "US", "1.18.1"
            ),
        ),
    )
    monkeypatch.setattr(module, "AccountRpcServer", Server)
    if case in {"partial", "executor", "server", "startup-quarantine"}:
        with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
            module.create_server_from_environment()
    else:
        result = module.create_server_from_environment()
        if case.startswith("close-"):
            with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
                result.dispose()
            assert result.dispose() is False
        else:
            result.dispose()
            result.dispose()
    assert events.count("vault-closed") == events.count("vault-created") == 1
    for resource in ("admission", "worker"):
        assert events.count(resource + "-closed") == events.count(resource + "-created")
    if case == "partial":
        assert "server-created" not in events
    if case == "startup-quarantine":
        import gc
        import weakref

        owned = [ref for ref in module._BOOTSTRAP_QUARANTINE[quarantine_before:]]
        assert len(owned) == 1
        admission_refs = [
            weakref.ref(resource.__self__)
            for resource in owned[0]
            if getattr(resource, "__self__", None) is not None
        ]
        gc.collect()
        assert admission_refs and all(ref() is not None for ref in admission_refs)


@pytest.mark.parametrize(
    "case",
    [
        "method",
        "uuid",
        "purpose",
        "unknown-context",
        "ticket",
        "correlation",
        "deadline",
        "bound",
    ],
)
def test_actual_tls_rejects_raw_malformed_fixed_request_before_worker(transport, case):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.selected import encode_directory_input

    query = json.loads(encode_directory_input("device_list", body()))
    ctx = pb.RpcContext(
        protocol_version=1, ticket="01" * 32, deadline_ms=3000, correlation_id="raw"
    )
    if case == "method":
        query["method"] = "sent_shares"
    elif case == "uuid":
        query["identity_id"] = "not-uuid"
    elif case == "purpose":
        query["purpose"] = "account_login"
    elif case == "unknown-context":
        ctx = pb.RpcContext.FromString(ctx.SerializeToString() + b"\x28\x01")
    elif case == "ticket":
        ctx.ticket = "private-invalid"
    elif case == "correlation":
        ctx.correlation_id = "invalid space"
    elif case == "deadline":
        ctx.deadline_ms = 10001
    payload = json.dumps(query).encode() if case != "bound" else b"x" * 65537
    reply = transport[2]()._directory_stub.DeviceList(
        pb.DirectoryDeviceListRequest(context=ctx, query_json=payload), timeout=3
    )
    assert reply.failure_code == "ACCOUNT_INPUT_INVALID" and not reply.public_json
    assert transport[1].calls == []


def test_large_safe_query_and_projection_have_directory_bounds(transport):
    from wso_contracts.tvt.directory import ChannelListRequest

    worker, client = transport[1], transport[2]()
    query = ChannelListRequest(
        **SCOPE, sn_list=tuple(str(index) + "x" * 4000 for index in range(10))
    )
    record = ObservationObject(
        fields=(ObservationField(name="sn", state="value", value="x" * 4000),)
    )
    worker.change = {"records": (record,) * 150}
    result = client.directory_channel_list(
        "01" * 32, query, deadline_ms=3000, correlation_id="large"
    )
    assert len(result.model_dump_json()) > 524288 and len(result.records) == 150
    assert worker.calls[0][1] == query


def test_client_encoding_consumes_original_budget_without_dispatch(
    transport, monkeypatch
):
    from wso_tvt_bridge import client as module

    original = module.encode_directory_input

    def slow(*args):
        time.sleep(0.06)
        return original(*args)

    monkeypatch.setattr(module, "encode_directory_input", slow)
    with pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"):
        transport[2]().directory_device_list(
            "01" * 32, body(), deadline_ms=30, correlation_id="encoding"
        )
    assert transport[1].calls == []


def test_server_decoding_consumes_original_budget_without_worker(
    transport, monkeypatch
):
    from wso_tvt_bridge import server as module

    original = module.decode_directory_input

    def slow(*args):
        time.sleep(0.06)
        return original(*args)

    monkeypatch.setattr(module, "decode_directory_input", slow)
    with pytest.raises(AccountFailure) as caught:
        transport[2]().directory_device_list(
            "01" * 32, body(), deadline_ms=30, correlation_id="decoding"
        )
    assert caught.value.code in {"UNKNOWN_OUTCOME", "ACCOUNT_DEADLINE_EXCEEDED"}
    time.sleep(0.08)
    assert transport[1].calls == []


def test_client_close_cancels_pending_and_owns_channel_once(transport):
    worker, client = transport[1], transport[2]()
    with ThreadPoolExecutor(max_workers=1) as threads:
        pending = threads.submit(
            client.directory_device_list,
            "dd" * 32,
            body(),
            deadline_ms=3000,
            correlation_id="closing",
        )
        assert worker.entered.wait(1)
        client.close()
        client.close()
        with pytest.raises(AccountFailure, match="UNKNOWN_OUTCOME"):
            pending.result(2)
        worker.release.set()


def test_failure_allowlist_keeps_old_surface_closed():
    from wso_tvt_bridge.selected import directory_failure, failure, flow_failure

    for original in (failure, flow_failure):
        assert (
            original("DIRECTORY_REAUTHENTICATION_REQUIRED").code
            == "ACCOUNT_UNAVAILABLE"
        )
    assert directory_failure("DIRECTORY_REAUTHENTICATION_REQUIRED").status == 401
    assert directory_failure("ACCOUNT_QUARANTINED").status == 503
    assert directory_failure("PRIVATE").code == "ACCOUNT_UNAVAILABLE"


def test_directory_does_not_widen_old_request_or_reply_bounds(transport):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.selected import validate_request

    ctx = pb.RpcContext(
        protocol_version=1, ticket="01" * 32, deadline_ms=3000, correlation_id="legacy"
    )
    request = pb.LoginRequest(context=ctx, account_login_json=b"x" * 32768)
    with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
        validate_request(request)
    client = transport[2]()

    class Pending:
        def result(self):
            return pb.AccountReply(public_json=b"x" * 524288)

        def cancel(self):
            return True

    class Source:
        def future(self, *args, **kwargs):
            return Pending()

    client._stub.Profile = Source()
    with pytest.raises(AccountFailure, match="ACCOUNT_PROTOCOL_INVALID"):
        client.profile("01" * 32, deadline_ms=3000, correlation_id="legacy")


@pytest.mark.parametrize("milliseconds", [0, 10001, True])
def test_directory_only_original_10000ms_budget_allowed(transport, milliseconds):
    with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
        transport[2]().directory_device_list(
            "01" * 32, body(), deadline_ms=milliseconds, correlation_id="budget"
        )
    assert transport[1].calls == []


def test_exact_request_subclass_and_private_construct_extras_are_rejected():
    from wso_tvt_bridge.selected import encode_directory_input

    class Extended(DeviceListRequest):
        token: str = "secret"

    value = body()
    value.__dict__["provider"] = "secret"
    for request in (value, Extended(**SCOPE)):
        with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
            encode_directory_input("device_list", request)


@pytest.mark.parametrize("value", [False, "unproved"])
def test_uncertain_disposer_never_returns_healthy(transport, value):
    server = transport[0]
    server._dispose = lambda: value
    assert server.close(grace=0) is False
