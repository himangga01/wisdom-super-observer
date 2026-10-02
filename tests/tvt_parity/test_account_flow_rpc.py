"""Flow RPC transport/config acceptance; synthetic worker is not SQL acceptance."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import grpc
import pytest
from pydantic import SecretStr
from wso_contracts.tvt.account_flows import (
    AccountDynamicCodeRequest,
    AccountFlowCancel,
    AccountFlowReference,
    AccountFlowStart,
    AccountFlowView,
    AccountRecoverySubmit,
    AccountRegistrationSubmit,
)
from wso_core.tvt.account_projection import AccountFailure

FLOW = UUID("00000000-0000-4000-8000-000000000002")
SELECT = {"region": "eu", "brand": "tvt", "purpose": "register"}


def start(**extra):
    return AccountFlowStart(
        **(SELECT | {"mode": "email", "account": "a@example.invalid"} | extra)
    )


def reference(model=AccountFlowReference, **extra):
    return model(**(SELECT | {"flow_id": FLOW} | extra))


def test_flow_secret_roundtrip_preserves_email_omission_and_phone_binding():
    from wso_tvt_bridge.selected import decode_input, encode_input

    email = start()
    payload = encode_input(email)
    assert json.loads(payload)["account"] == "a@example.invalid"
    assert "country_code" not in json.loads(payload)
    assert (
        decode_input(payload, AccountFlowStart).account.get_secret_value()
        == "a@example.invalid"
    )
    phone = start(mode="phone", account="0101234", country_code="82")
    rebuilt = decode_input(encode_input(phone), AccountFlowStart)
    assert (rebuilt.country_code, rebuilt.account.get_secret_value()) == (
        "82",
        "0101234",
    )
    for model, fields in (
        (AccountRegistrationSubmit, {"password": "password", "dynamic_code": "123456"}),
        (
            AccountRecoverySubmit,
            {
                "purpose": "recover",
                "new_password": "new-secret",
                "dynamic_code": "654321",
            },
        ),
        (
            AccountDynamicCodeRequest,
            {"challenge_id": FLOW, "challenge_generation": 1, "image_code": "1234"},
        ),
    ):
        body = reference(model, **fields)
        decoded = decode_input(encode_input(body), model)
        for name, value in fields.items():
            if isinstance(getattr(decoded, name), SecretStr):
                assert getattr(decoded, name).get_secret_value() == value


@pytest.mark.parametrize(
    "tail",
    [
        b',"worker_url":"private"}',
        b',"account":"duplicate"}',
        b',"country_code":null}',
        b',"mode":"invalid"}',
    ],
)
def test_flow_closed_payload_rejects_extra_duplicate_null_and_enum(tail):
    from wso_tvt_bridge.selected import decode_input, encode_input

    payload = encode_input(start())
    with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
        decode_input(payload[:-1] + tail, AccountFlowStart)


def test_constructed_wrong_purpose_or_native_input_cannot_cross_wire():
    from wso_tvt_bridge.selected import encode_input

    for body in (
        start().model_copy(
            update={"account": SecretStr("a\U0001f600@example.invalid")}
        ),
        reference(
            AccountRegistrationSubmit, password="password", dynamic_code="123456"
        ).model_copy(update={"purpose": "recover"}),
    ):
        with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
            encode_input(body)


class SyntheticFlow:
    def __init__(self):
        self.calls = []
        self.entered, self.release = Event(), Event()

    def run(self, operation, expected, ticket, body, *, deadline_ms, correlation_id):
        assert type(body) is expected
        assert 0 < deadline_ms <= 20000
        self.calls.append((operation, body))
        if ticket.startswith("dd"):
            self.entered.set()
            self.release.wait(2)
        if ticket.startswith("ee"):
            raise AccountFailure("FLOW_EXPIRED", 409)
        if ticket.startswith("ff"):
            raise ValueError("PRIVATE-DETAIL")
        values = body.model_dump(
            exclude={
                "mode",
                "account",
                "country_code",
                "password",
                "new_password",
                "dynamic_code",
                "image_code",
                "challenge_id",
                "challenge_generation",
            }
        )
        values["flow_id"] = FLOW
        values.update(request_id=correlation_id, state="CREATED")
        if ticket.startswith("bb"):
            values["request_id"] = "wrong"
        result = AccountFlowView(**values)
        if ticket.startswith("cc"):
            result = result.model_copy(update={"automatic_retry_permitted": True})
        if ticket.startswith("ac"):
            result = result.model_copy(update={"purpose": "recover"})
        return result

    def start(self, *a, **kw):
        return self.run("start", AccountFlowStart, *a, **kw)

    def state(self, *a, **kw):
        return self.run("state", AccountFlowReference, *a, **kw)

    def existence(self, *a, **kw):
        return self.run("existence", AccountFlowReference, *a, **kw)

    def image(self, *a, **kw):
        return self.run("image", AccountFlowReference, *a, **kw)

    def issue_code(self, *a, **kw):
        return self.run("issue_code", AccountDynamicCodeRequest, *a, **kw)

    def register(self, *a, **kw):
        return self.run("register", AccountRegistrationSubmit, *a, **kw)

    def recover(self, *a, **kw):
        return self.run("recover", AccountRecoverySubmit, *a, **kw)

    def cancel(self, *a, **kw):
        return self.run("cancel", AccountFlowCancel, *a, **kw)


@pytest.fixture
def transport(tmp_path, request):
    from test_bridge_mtls import StrictExecutor, certs
    from wso_tvt_bridge.client import AccountRpcClient, ClientConfig
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig

    certs(tmp_path)
    worker, disposed = SyntheticFlow(), []
    config = ServerConfig(
        bind="localhost:0",
        ca=(tmp_path / "ca.pem").read_bytes(),
        certificate=(tmp_path / "server.pem").read_bytes(),
        key=(tmp_path / "server.key").read_bytes(),
        client_sans=frozenset({"api.test"}),
        capacity=1,
    )
    server = AccountRpcServer(
        config,
        StrictExecutor(tmp_path),
        flow_worker=worker if getattr(request, "param", True) else None,
        dispose=lambda: disposed.append("closed"),
    )
    port = (
        server._port
        if getattr(request, "param", True) == "not-started"
        else server.start()
    )
    clients = []

    def client(label="client", ca=None):
        value = AccountRpcClient(
            ClientConfig(
                endpoint=f"localhost:{port}",
                ca=ca or config.ca,
                certificate=(tmp_path / f"{label}.pem").read_bytes(),
                key=(tmp_path / f"{label}.key").read_bytes(),
            )
        )
        clients.append(value)
        return value

    try:
        yield server, worker, client, disposed
    finally:
        worker.release.set()
        for value in clients:
            value.close()
        server.close()
        for path in tmp_path.rglob("*"):
            if path.is_file() and path.suffix in {".pem", ".key"}:
                path.unlink()


def test_all_eight_typed_flow_methods_and_old_account_on_shared_verified_tls(transport):
    _, worker, make_client, _ = transport
    client = make_client()
    bodies = [
        start(),
        reference(),
        reference(),
        reference(),
        reference(AccountDynamicCodeRequest),
        reference(
            AccountRegistrationSubmit, password="password", dynamic_code="123456"
        ),
        reference(
            AccountRecoverySubmit,
            purpose="recover",
            new_password="new-password",
            dynamic_code="654321",
        ),
        reference(AccountFlowCancel),
    ]
    for index, (method, body) in enumerate(
        zip(
            (
                "start",
                "state",
                "existence",
                "image",
                "issue_code",
                "register",
                "recover",
                "cancel",
            ),
            bodies,
            strict=True,
        )
    ):
        result = getattr(client, method)(
            f"{index + 1:02x}" * 32,
            body,
            deadline_ms=3000,
            correlation_id=f"flow-{index}",
        )
        assert type(result) is AccountFlowView and result.request_id == f"flow-{index}"
    assert [operation for operation, _ in worker.calls] == [
        "start",
        "state",
        "existence",
        "image",
        "issue_code",
        "register",
        "recover",
        "cancel",
    ]
    assert (
        client.profile(
            "09" * 32, deadline_ms=3000, correlation_id="old-profile"
        ).profile.nickname
        == "test"
    )


def test_duplicate_start_rejected_without_retiring_running_legacy_rpc(transport):
    server, _, make_client, disposed = transport
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        server.start()
    assert disposed == []
    assert (
        make_client()
        .profile("09" * 32, deadline_ms=3000, correlation_id="old-after-start")
        .profile.nickname
        == "test"
    )


@pytest.mark.parametrize(
    "ticket,code",
    [
        ("bb", "ACCOUNT_PROTOCOL_INVALID"),
        ("cc", "ACCOUNT_PROTOCOL_INVALID"),
        ("ac", "ACCOUNT_PROTOCOL_INVALID"),
        ("ee", "FLOW_EXPIRED"),
        ("ff", "ACCOUNT_UNAVAILABLE"),
    ],
)
def test_worker_results_and_failures_are_closed_and_redacted(transport, ticket, code):
    _, _, make_client, _ = transport
    with pytest.raises(AccountFailure) as caught:
        make_client().start(
            ticket * 32, start(), deadline_ms=3000, correlation_id="result"
        )
    assert str(caught.value) == code


def test_wrong_san_denied_before_flow_dispatch(transport):
    _, worker, make_client, _ = transport
    with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
        make_client("other").start(
            "01" * 32, start(), deadline_ms=3000, correlation_id="denied"
        )
    assert worker.calls == []


def test_untrusted_ca_denied_before_flow_dispatch(transport, tmp_path):
    from test_bridge_mtls import certs

    _, worker, make_client, _ = transport
    other = tmp_path / "other-ca"
    other.mkdir()
    certs(other)
    with pytest.raises(AccountFailure, match="UNKNOWN_OUTCOME"):
        make_client(ca=(other / "ca.pem").read_bytes()).start(
            "01" * 32, start(), deadline_ms=1000, correlation_id="untrusted"
        )
    assert worker.calls == []


@pytest.mark.parametrize(
    "case,code",
    [
        ("version", "ACCOUNT_PROTOCOL_INVALID"),
        ("deadline", "ACCOUNT_INPUT_INVALID"),
        ("correlation", "ACCOUNT_INPUT_INVALID"),
        ("ticket", "ACCOUNT_INPUT_INVALID"),
        ("unknown", "ACCOUNT_INPUT_INVALID"),
        ("unknown-context", "ACCOUNT_INPUT_INVALID"),
        ("size", "ACCOUNT_INPUT_INVALID"),
        ("json", "ACCOUNT_INPUT_INVALID"),
        ("duplicate", "ACCOUNT_INPUT_INVALID"),
        ("extra", "ACCOUNT_INPUT_INVALID"),
        ("null", "ACCOUNT_INPUT_INVALID"),
    ],
)
def test_malformed_flow_frames_rejected_before_worker_admission(transport, case, code):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.generated import tvt_bridge_pb2_grpc as rpc
    from wso_tvt_bridge.selected import encode_input

    _, worker, make_client, _ = transport
    request = pb.FlowStartRequest(
        context=pb.RpcContext(
            protocol_version=1,
            ticket="01" * 32,
            deadline_ms=1000,
            correlation_id="frame",
        ),
        private_json=encode_input(start()),
    )
    if case == "version":
        request.context.protocol_version = 2
    elif case == "deadline":
        request.context.deadline_ms = 20001
    elif case == "correlation":
        request.context.correlation_id = "bad space"
    elif case == "ticket":
        request.context.ticket = "PRIVATE"
    elif case == "unknown":
        request = pb.FlowStartRequest.FromString(
            request.SerializeToString() + b"\x18\x01"
        )
    elif case == "unknown-context":
        request.context.CopyFrom(
            pb.RpcContext.FromString(request.context.SerializeToString() + b"\x28\x01")
        )
    elif case == "size":
        request.private_json = b"x" * 32768
    elif case == "json":
        request.private_json = b"{"
    else:
        request.private_json = (
            request.private_json[:-1]
            + {
                "duplicate": b',"account":"duplicate"}',
                "extra": b',"authority":"private"}',
                "null": b',"country_code":null}',
            }[case]
        )
    reply = rpc.FlowBridgeV1Stub(make_client()._channel).Start(request, timeout=2)
    assert reply.failure_code == code and not reply.public_json
    assert worker.calls == []


@pytest.mark.parametrize("transport", [False], indirect=True)
def test_absent_flow_worker_fails_canonically_without_breaking_old_rpc(transport):
    _, worker, make_client, _ = transport
    client = make_client()
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        client.start("01" * 32, start(), deadline_ms=3000, correlation_id="disabled")
    assert worker.calls == []
    assert (
        client.profile(
            "09" * 32, deadline_ms=3000, correlation_id="old-disabled"
        ).profile.nickname
        == "test"
    )


@pytest.mark.parametrize(
    "case",
    ["duplicate", "extra", "state", "request", "scope", "both", "unknown", "size"],
)
def test_client_revalidates_closed_flow_reply_before_public_delivery(transport, case):
    from wso_tvt_bridge.generated import tvt_bridge_pb2 as pb
    from wso_tvt_bridge.selected import encode_input

    _, _, make_client, _ = transport
    body = start()
    raw = (
        AccountFlowView(**SELECT, flow_id=FLOW, request_id="public", state="CREATED")
        .model_dump_json()
        .encode()
    )
    reply = pb.FlowReply(public_json=raw)
    if case == "duplicate":
        reply.public_json = raw[:-1] + b',"request_id":"public"}'
    elif case == "extra":
        reply.public_json = raw[:-1] + b',"private_token":"secret"}'
    elif case in {"state", "request", "scope"}:
        value = json.loads(raw)
        value.update(
            {"state": "BOGUS"}
            if case == "state"
            else {"request_id": "wrong"}
            if case == "request"
            else {"purpose": "recover"}
        )
        reply.public_json = json.dumps(value).encode()
    elif case == "both":
        reply.failure_code = "FLOW_EXPIRED"
    elif case == "unknown":
        reply = pb.FlowReply.FromString(reply.SerializeToString() + b"\x18\x01")
    else:
        reply.public_json = b"x" * 524288

    class Pending:
        def result(self):
            return reply

        def cancel(self):
            return True

    class ReplySource:
        def future(self, request, *, timeout, wait_for_ready):
            assert request.private_json == encode_input(body)
            assert not wait_for_ready and 0 < timeout <= 3
            return Pending()

    client = make_client()
    client._flow_stub.Start = ReplySource()
    with pytest.raises(AccountFailure) as caught:
        client.start("01" * 32, body, deadline_ms=3000, correlation_id="public")
    assert caught.value.code in {"ACCOUNT_PROTOCOL_INVALID", "ACCOUNT_INPUT_INVALID"}
    assert "secret" not in str(caught.value)


def test_deadline_capacity_and_close_hold_resources_until_late_settlement(transport):
    server, worker, make_client, disposed = transport
    client = make_client()
    with ThreadPoolExecutor(max_workers=1) as threads:
        pending = threads.submit(
            client.start, "dd" * 32, start(), deadline_ms=100, correlation_id="slow"
        )
        assert worker.entered.wait(1)
        with pytest.raises(AccountFailure, match="UNKNOWN_OUTCOME"):
            pending.result(2)
        with pytest.raises(AccountFailure, match="SESSION_BUSY"):
            client.state(
                "01" * 32, reference(), deadline_ms=1000, correlation_id="capacity"
            )
        assert not server.close(grace=0)
        assert disposed == []
        worker.release.set()
    end = time.monotonic() + 2
    while server.pool.registry.active_count and time.monotonic() < end:
        time.sleep(0.01)
    assert disposed == ["closed"]
    assert server.close(grace=0) and disposed == ["closed"]


def test_flow_failure_does_not_widen_old_account_allowlist():
    from wso_tvt_bridge.selected import failure, flow_failure

    assert failure("FLOW_EXPIRED").code == "ACCOUNT_UNAVAILABLE"
    assert (flow_failure("FLOW_EXPIRED").code, flow_failure("FLOW_EXPIRED").status) == (
        "FLOW_EXPIRED",
        409,
    )
    assert flow_failure("PRIVATE-DETAIL").code == "ACCOUNT_UNAVAILABLE"


def test_drain_does_not_report_success_while_disposal_is_still_running(transport):
    server, worker, make_client, _ = transport
    entered, release, finished = Event(), Event(), Event()

    def dispose():
        entered.set()
        release.wait(2)
        finished.set()

    server._dispose = dispose
    client = make_client()
    with ThreadPoolExecutor(max_workers=1) as threads:
        pending = threads.submit(
            client.start,
            "dd" * 32,
            start(),
            deadline_ms=1000,
            correlation_id="disposing",
        )
        assert worker.entered.wait(1)
        assert server.close(grace=0) is False
        worker.release.set()
        assert entered.wait(1)
        try:
            assert server.close(grace=0) is False
        finally:
            release.set()
        assert finished.wait(1)
        with pytest.raises(AccountFailure, match="UNKNOWN_OUTCOME"):
            pending.result(2)
    assert server.close(grace=0) is True


def test_quarantined_worker_cleanup_is_not_reported_as_drained(transport):
    server, _, _, _ = transport

    def uncertain():
        raise AccountFailure("ACCOUNT_QUARANTINED", 409)

    server._dispose = uncertain
    assert server.close(grace=0) is False
    assert server.close(grace=0) is False


@pytest.mark.parametrize("stage", ["credentials", "server", "registration"])
def test_server_configuration_failure_disposes_owned_resources(
    tmp_path, monkeypatch, stage
):
    from test_bridge_mtls import StrictExecutor, certs
    from wso_tvt_bridge.server import AccountRpcServer, ServerConfig

    certs(tmp_path)
    disposed = []
    config = ServerConfig(
        bind="localhost:0",
        ca=(tmp_path / "ca.pem").read_bytes(),
        certificate=(tmp_path / "server.pem").read_bytes(),
        key=(tmp_path / "server.key").read_bytes(),
        client_sans=frozenset({"api.test"}),
    )

    def broken(*a, **kw):
        raise ValueError("PRIVATE-TLS-DETAIL")

    if stage == "credentials":
        monkeypatch.setattr(grpc, "ssl_server_credentials", broken)
    elif stage == "server":
        monkeypatch.setattr(grpc, "server", broken)
    else:
        from wso_tvt_bridge.generated import tvt_bridge_pb2_grpc

        monkeypatch.setattr(
            tvt_bridge_pb2_grpc, "add_FlowBridgeV1Servicer_to_server", broken
        )
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        AccountRpcServer(
            config, StrictExecutor(tmp_path), dispose=lambda: disposed.append("closed")
        )
    assert disposed == ["closed"]
    for path in tmp_path.iterdir():
        if path.suffix in {".pem", ".key"}:
            path.unlink()


@pytest.mark.parametrize("transport", ["not-started"], indirect=True)
def test_server_start_failure_retires_owned_epoch_and_redacts(transport, monkeypatch):
    server, _, _, disposed = transport

    def broken():
        raise ValueError("PRIVATE-START-DETAIL")

    monkeypatch.setattr(server._server, "start", broken)
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        server.start()
    assert disposed == ["closed"]
    assert server.close(grace=0)


def test_flow_config_is_optional_but_partial_configuration_fails_closed(tmp_path):
    from wso_tvt_bridge.flow_config import load_flow_configuration

    assert load_flow_configuration({}, ()) is None
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        load_flow_configuration(
            {"WSO_TVT_ACCOUNT_FLOW_KEY_FILE": str(tmp_path / "secret")}, ()
        )


@pytest.mark.parametrize(
    "case",
    [
        "disabled",
        "partial",
        "admission-failure",
        "executor-failure",
        "server-failure",
        "enabled",
        "quarantined",
    ],
)
def test_worker_factory_owns_each_resource_once_and_closes_all_after_failure(
    tmp_path, monkeypatch, case
):
    from wso_api.tvt import flow_service, session_service
    from wso_core import secrets
    from wso_core.tvt import flow_admission, token_vault
    from wso_tvt_bridge import server as module

    for name in tuple(module.os.environ):
        if name.startswith("WSO_"):
            monkeypatch.delenv(name)
    key, profile = tmp_path / "binding", tmp_path / "profile"
    key.write_bytes(b"x" * 32)
    profile.write_text('[{"region":"eu","brand":"tvt","default_domain":""}]')
    settings = {
        "WSO_TVT_BRIDGE_CLIENT_SANS_JSON": '["api.test"]',
        "WSO_TVT_BRIDGE_BIND": "localhost:0",
        "WSO_TVT_BRIDGE_CA_FILE": "synthetic-ca",
        "WSO_TVT_BRIDGE_SERVER_CERT_FILE": "synthetic-cert",
        "WSO_TVT_BRIDGE_SERVER_KEY_FILE": "synthetic-key",
        "WSO_CONNECTION_KEY_FILE": "synthetic-vault-key",
        "WSO_WORKER_DATABASE_URL": "synthetic-worker-url",
    }
    if case != "disabled":
        settings["WSO_TVT_ACCOUNT_FLOW_KEY_FILE"] = str(key)
        if case != "partial":
            settings["WSO_TVT_ACCOUNT_FLOW_PROFILE_FILE"] = str(profile)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    events = []

    class Provider:
        def __init__(self, path):
            pass

        def encryption_key(self):
            return b"v" * 32

    class Vault:
        def __init__(self, url, provider):
            events.append("vault-created")

        def close(self):
            events.append("vault-closed")

    class Admission:
        def __init__(self, url, commitment):
            import hashlib

            assert commitment == hashlib.sha256(b"x" * 32).hexdigest()
            if case == "admission-failure":
                raise ValueError("PRIVATE")
            events.append("admission-created")

        def close(self):
            events.append("admission-closed")

    class Executor:
        def __init__(self, admission, endpoints, profiles, binding):
            assert profiles[("eu", "tvt")].default_domain == "" and binding == b"x" * 32
            if case == "executor-failure":
                raise ValueError("PRIVATE")
            events.append("flow-created")

        def close(self, *, deadline_ms):
            assert deadline_ms == 1000
            events.append("flow-closed")
            if case == "quarantined":
                raise AccountFailure("ACCOUNT_QUARANTINED", 409)

    class Server:
        def __init__(self, config, worker, *, dispose, flow_worker):
            self.dispose = dispose
            assert (flow_worker is None) == (case == "disabled")
            if case == "server-failure":
                dispose()  # Constructor and factory may both invoke once guard.
                raise ValueError("PRIVATE")

    endpoints = (
        session_service.AccountEndpoint(
            region="eu",
            brand="tvt",
            origin="https://example.invalid",
            language="en",
            country="EU",
            app_version="1.18.1",
        ),
    )
    monkeypatch.setattr(module, "pem", lambda path: b"synthetic")
    monkeypatch.setattr(secrets, "FileKeyProvider", Provider)
    monkeypatch.setattr(token_vault, "TokenVault", Vault)
    monkeypatch.setattr(session_service, "load_account_endpoints", lambda: endpoints)
    monkeypatch.setattr(session_service, "AccountWorkerExecutor", lambda *a: object())
    monkeypatch.setattr(flow_admission, "FlowAdmission", Admission)
    monkeypatch.setattr(flow_service, "AccountFlowWorkerExecutor", Executor)
    monkeypatch.setattr(module, "AccountRpcServer", Server)
    if case in {"disabled", "enabled", "quarantined"}:
        value = module.create_server_from_environment()
        if case == "quarantined":
            with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
                value.dispose()
        else:
            value.dispose()
        value.dispose()
    else:
        with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
            module.create_server_from_environment()
    assert events.count("vault-closed") == 1
    for name in ("admission", "flow"):
        assert events.count(name + "-closed") == events.count(name + "-created")


@pytest.mark.parametrize(
    "invalid",
    [
        "key-short",
        "key-long",
        "profile-extra",
        "duplicate",
        "pair",
        "not-list",
        "domain-null",
        "domain-bmp",
    ],
)
def test_worker_flow_configuration_requires_closed_profile_exact_key_and_endpoint_pairs(
    tmp_path, invalid
):
    from wso_api.tvt.session_service import AccountEndpoint
    from wso_tvt_bridge.flow_config import load_flow_configuration

    endpoint = AccountEndpoint(
        region="eu",
        brand="tvt",
        origin="https://example.invalid",
        language="en",
        country="EU",
        app_version="1.18.1",
        customer_app_id="app",
    )
    key = tmp_path / "key"
    key.write_bytes(
        b"x" * (31 if invalid == "key-short" else 33 if invalid == "key-long" else 32)
    )
    value = [{"region": "eu", "brand": "tvt", "default_domain": ""}]
    if invalid == "profile-extra":
        value[0]["worker_url"] = "PRIVATE"
    if invalid == "duplicate":
        value += value
    if invalid == "pair":
        value[0]["brand"] = "other"
    if invalid == "domain-null":
        value[0]["default_domain"] = None
    if invalid == "domain-bmp":
        value[0]["default_domain"] = "\U0001f600"
    profile = tmp_path / "profile"
    profile.write_text(json.dumps({} if invalid == "not-list" else value))
    env = {
        "WSO_TVT_ACCOUNT_FLOW_KEY_FILE": str(key),
        "WSO_TVT_ACCOUNT_FLOW_PROFILE_FILE": str(profile),
    }
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        load_flow_configuration(env, (endpoint,))
    key.write_bytes(b"x" * 32)
    profile.write_text('[{"region":"eu","brand":"tvt","default_domain":""}]')
    loaded = load_flow_configuration(env, (endpoint,))
    assert loaded.binding_key == b"x" * 32
    assert loaded.profiles[("eu", "tvt")].default_domain == ""
