"""Synthetic W06 private flow proofs; no APK or TVT server acceptance."""

import base64
import importlib
import json
import threading
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from wso_contracts.tvt.identity import AccountScope
from wso_core.tvt.account_protocol import (
    AccountProtocol,
    SessionTaskIds,
    parse_response,
)
from wso_core.tvt.ports import AccountClientError


def subject():
    assert importlib.util.find_spec("wso_core.tvt.account_flows") is not None, (
        "Concrete prelogin flows must serialize source register/reset and bind runtime keys"
    )
    return importlib.import_module("wso_core.tvt.account_flows")


def scope():
    return AccountScope(
        tenant_id=UUID(int=1),
        actor_user_id=UUID(int=2),
        region="host-test",
        brand="demo",
    )


def protocol():
    return AccountProtocol(
        task_ids=SessionTaskIds(),
        clock=lambda: 1700000000,
        nonce=lambda: 123456789,
    )


def response(data=None, code=200, status=200):
    return parse_response(
        status, json.dumps({"basic": {"msgcode": code}, "data": data}).encode()
    )


@pytest.fixture
def key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = base64.b64encode(
        private.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode()
    return private, public


def build(
    monkeypatch,
    replies,
    *,
    purpose="REGISTER",
    mode="EMAIL",
    account="alice@example.invalid",
    **options,
):
    f = subject()
    import wso_core.tvt.account_client as client

    requests = []
    queue = iter(replies)

    class Boundary:
        def send(self, request):
            requests.append(request)
            value = next(queue)
            if callable(value):
                value = value(request)
            if isinstance(value, Exception):
                raise value
            return value

        def close(self):
            pass

    monkeypatch.setattr(client, "ProcessAccountTransport", lambda *a, **k: Boundary())
    flow = f.PreloginAccountFlow(
        scope(),
        f.AccountBinding(f.AccountMode[mode], account),
        f.FlowPurpose[purpose],
        f.OriginPolicy(
            {
                "host-test": frozenset(
                    {"https://localhost:1", "https://localhost:1/mobile_v1.0"}
                )
            }
        ),
        origin="https://localhost:1",
        protocol=protocol(),
        **options,
    )
    return f, flow, requests


def call(flow, method, *args, supplied_scope=None, **kwargs):
    return getattr(flow, method)(
        supplied_scope or scope(),
        *args,
        deadline_ms=3000,
        correlation_id="flow-test",
        **kwargs,
    )


@pytest.mark.parametrize(
    "mode,account,path,key_name",
    [
        ("PHONE", "82+1012345678", "/user/info/phone/is-exist", "mobile"),
        ("EMAIL", "alice@example.invalid", "/user/info/email/is-exist", "email"),
    ],
)
@pytest.mark.parametrize("exists", [True, False])
def test_existence_exact_wire_and_strict_false(
    monkeypatch, mode, account, path, key_name, exists
):
    f, flow, requests = build(
        monkeypatch,
        [response({"isExist": exists})],
        mode=mode,
        account=account,
        customer_app_id="demo-app",
    )
    result = call(flow, "exists")
    assert result.state is f.FlowState.EXISTENCE and result.exists is exists
    assert requests[0].path == path
    assert json.loads(requests[0].body) == {
        "basic": {"ver": "1.0", "id": "1", "time": 1700000000, "nonce": 123456789},
        "data": {key_name: account, "customerAppId": "demo-app"},
    }


@pytest.mark.parametrize(
    "data", [None, {}, {"isExist": None}, {"isExist": 0}, {"isExist": "false"}, []]
)
def test_existence_missing_is_not_false(monkeypatch, data):
    _, flow, _ = build(monkeypatch, [response(data)])
    with pytest.raises(AccountClientError) as error:
        call(flow, "exists")
    assert error.value.code == "ACCOUNT_PROTOCOL_INVALID"
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    "password,code,md5,sign",
    [
        (
            "Demo_Pass9!",
            "246810",
            "6b1c65a3262e953bfabf2d0a84b95cf8",
            "4521e811acf7717cb94ed3bae370c59e9163a8415a67d29cb6bd2d2ac65e961d57456e63a330d746b0162dd2953fc03065848e4c548598530a470d33f9254403",
        ),
        (
            "비밀P@ss1",
            "135790",
            "a8a4d24739b112b09df78cdba8ad7273",
            "b1f8eca77f40cdd844e701daedb96d5700a58b6a47f7f40f73befa9d3c6db081114650ca952171c906e96cf3b578b287e1d03e057f81fde6d5e9cd38a4e8bb54",
        ),
    ],
)
def test_register_exact_proof_and_independent_rsa_plaintext(
    monkeypatch, key, password, code, md5, sign
):
    f, flow, requests = build(
        monkeypatch,
        [response({"publicKey": key[1]}), response({"token": "must-not-mint"})],
        country="KR",
        customer_app_id="demo-app",
        terminal_id="terminal",
    )
    assert call(flow, "image").state is f.FlowState.IMAGE_AVAILABLE
    result = call(flow, "register", password, code)
    assert result.state is f.FlowState.COMPLETE and result.return_to_login
    envelope = json.loads(requests[1].body)
    assert envelope["basic"] == {
        "ver": "1.1",
        "id": "2",
        "time": 1700000000,
        "nonce": 123456789,
        "sign": sign,
    }
    data = envelope["data"]
    ciphertext = base64.b64decode(data.pop("password"), validate=True)
    assert key[0].decrypt(ciphertext, padding.PKCS1v15()) == md5.encode("ascii")
    numbers = key[0].private_numbers()
    block = pow(
        int.from_bytes(ciphertext), numbers.d, numbers.public_numbers.n
    ).to_bytes(256, "big")
    assert block[:2] == b"\x00\x02" and block.index(b"\x00", 2) >= 10
    assert block.split(b"\x00", 2)[2] == md5.encode("ascii")
    assert data == {
        "loginName": "alice@example.invalid",
        "loginType": 2,
        "lang": "en",
        "customerMark": "d41d8cd98f00b204e9800998ecf8427e",
        "country": "KR",
        "customerAppId": "demo-app",
        "terminalId": "terminal",
    }
    assert requests[1].path == "/user/register"
    assert not any(
        v in repr(result) + repr(flow)
        for v in (password, code, key[1], "must-not-mint")
    )
    with pytest.raises(f.FlowError) as duplicate:
        call(flow, "register", password, code)
    assert duplicate.value.code == "FLOW_CONSUMED" and len(requests) == 2


@pytest.mark.parametrize(
    "domain,mark", [("", None), ("example.invalid", "bacfc77a8608429e45caf98484cd712c")]
)
def test_recover_plain_md5_without_rsa_sign_or_register_fields(
    monkeypatch, domain, mark
):
    f, flow, requests = build(
        monkeypatch, [response({})], purpose="RECOVER", default_domain=domain
    )
    result = call(flow, "recover", "Demo_Pass9!", "246810")
    assert result.state is f.FlowState.COMPLETE and result.return_to_login
    envelope = json.loads(requests[0].body)
    assert envelope["basic"] == {
        "ver": "1.1",
        "id": "1",
        "time": 1700000000,
        "nonce": 123456789,
    }
    expected = {
        "loginName": "alice@example.invalid",
        "dynamicCode": "246810",
        "newPassword": "6b1c65a3262e953bfabf2d0a84b95cf8",
        "lang": "en",
    }
    if mark is not None:
        expected["customerMark"] = mark
    assert envelope["data"] == expected
    assert requests[0].path == "/user/info/password/reset"


@pytest.mark.parametrize(
    "purpose,code,state",
    [
        ("REGISTER", 200, "CODE_SENT"),
        ("REGISTER", 1007, "IMAGE_REQUIRED"),
        ("REGISTER", 1005, "IMAGE_REJECTED"),
        ("RECOVER", 1007, "IMAGE_REQUIRED"),
        ("RECOVER", 1005, "FAILED"),
        ("REGISTER", 1008, "FAILED"),
    ],
)
def test_dynamic_typed_states_exact_pair_and_purpose(
    monkeypatch, key, purpose, code, state
):
    f, flow, requests = build(
        monkeypatch,
        [
            response({"idCode": "image-id", "imgCodeImgData": "fetched"}),
            response(
                {
                    "idCode": "new-id",
                    "imgData": "dynamic",
                    "imgCodeImgData": "wrong",
                    "publicKey": key[1],
                },
                code,
            ),
        ],
        purpose=purpose,
    )
    image = call(flow, "image")
    assert image.challenge.private_image_data == "fetched"
    result = call(flow, "issue_code", image_code="1234")
    assert result.state is f.FlowState[state] and result.native_msgcode == code
    assert not result.return_to_login
    if state.startswith("IMAGE_"):
        assert (
            result.challenge.image_id == "new-id"
            and result.challenge.private_image_data == "dynamic"
        )
    assert requests[1].path == "/user/sms-code/no-token/get"
    assert json.loads(requests[1].body)["data"] == {
        "loginName": "alice@example.invalid",
        "loginType": 2,
        "businessType": 15 if purpose == "REGISTER" else 12,
        "lang": "en",
        "idCode": "image-id",
        "imgCode": "1234",
    }


@pytest.mark.parametrize(
    "code,status,data",
    [
        (1007, 200, None),
        (1005, 200, None),
        (1007, 503, {"idCode": "id", "imgData": "image"}),
        (200, 401, {}),
    ],
)
def test_dynamic_no_data_or_non2xx_never_challenge_success(
    monkeypatch, code, status, data
):
    f, flow, _ = build(monkeypatch, [response(data, code, status)])
    result = call(flow, "issue_code")
    assert result.state is f.FlowState.FAILED and result.challenge is None
    assert result.http_status == status and result.native_msgcode == code


@pytest.mark.parametrize(
    "value",
    [None, "", "not-base64", "-----BEGIN PUBLIC KEY-----", "A" * 8193],
    ids=["missing", "empty", "malformed", "pem", "oversized"],
)
def test_missing_or_malformed_runtime_key_prevents_registration_dispatch(
    monkeypatch, value
):
    f, flow, requests = build(
        monkeypatch, [response({} if value is None else {"publicKey": value})]
    )
    if value is None:
        call(flow, "image")
    else:
        with pytest.raises(AccountClientError):
            call(flow, "image")
    with pytest.raises(f.FlowError) as error:
        call(flow, "register", "Demo_Pass9!", "246810")
    assert error.value.code == "FLOW_KEY_MISSING" and len(requests) == 1


def test_scope_replacement_expiry_and_foreign_client_cannot_reuse_key(monkeypatch, key):
    now = [10.0]
    f, flow, requests = build(
        monkeypatch,
        [response({"publicKey": key[1]})],
        lifetime_seconds=2,
        monotonic=lambda: now[0],
    )
    call(flow, "image")
    foreign = scope().model_copy(update={"brand": "other"})
    with pytest.raises(AccountClientError):
        call(flow, "register", "Demo_Pass9!", "246810", supplied_scope=foreign)
    with pytest.raises(f.FlowError) as missing:
        call(flow, "register", "Demo_Pass9!", "246810")
    assert missing.value.code == "FLOW_KEY_MISSING"
    now[0] = 12
    with pytest.raises(f.FlowError) as expired:
        call(flow, "image")
    assert expired.value.code == "FLOW_EXPIRED" and len(requests) == 1
    _, other, other_requests = build(monkeypatch, [])
    with pytest.raises(f.FlowError):
        call(other, "register", "Demo_Pass9!", "246810")
    assert not other_requests


@pytest.mark.parametrize(
    "method,purpose", [("issue_code", "REGISTER"), ("recover", "RECOVER")]
)
def test_uncertain_write_is_unknown_and_cannot_replay(monkeypatch, method, purpose):
    from wso_core.tvt.account_process import AccountProcessError

    f, flow, requests = build(
        monkeypatch,
        [AccountProcessError("Account process deadline exceeded.")],
        purpose=purpose,
    )
    args = () if method == "issue_code" else ("Demo_Pass9!", "246810")
    result = call(flow, method, *args)
    assert result.state is f.FlowState.UNKNOWN_OUTCOME
    assert result.error_code == "ACCOUNT_DEADLINE_EXCEEDED"
    with pytest.raises(f.FlowError):
        call(flow, method, *args)
    assert len(requests) == 1


def test_close_and_inflight_suppress_late_key_and_success(monkeypatch, key):
    entered, release = threading.Event(), threading.Event()

    def delayed(request):
        entered.set()
        assert release.wait(3)
        return response({"publicKey": key[1]})

    f, flow, requests = build(monkeypatch, [delayed])
    errors = []

    def run():
        try:
            call(flow, "image")
        except (AccountClientError, f.FlowError) as error:
            errors.append(error.code)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(2)
    with pytest.raises(AccountClientError) as busy:
        call(flow, "image")
    assert busy.value.code == "ACCOUNT_UNAVAILABLE"
    flow.close()
    release.set()
    worker.join(3)
    assert not worker.is_alive() and errors == ["ACCOUNT_CANCELLED"]
    with pytest.raises(f.FlowError):
        call(flow, "register", "Demo_Pass9!", "246810")
    assert len(requests) == 1


def test_true200_dynamic_retains_native_image_id_separately_from_ui_challenge(
    monkeypatch,
):
    f, flow, requests = build(
        monkeypatch, [response({"idCode": "native-cached-id"}), response({})]
    )
    sent = call(flow, "issue_code")
    assert sent.state is f.FlowState.CODE_SENT and sent.challenge is None
    call(flow, "issue_code", image_code="1234")
    assert json.loads(requests[1].body)["data"]["idCode"] == "native-cached-id"


def test_malformed_replacement_invalidates_admitted_runtime_key(monkeypatch, key):
    f, flow, requests = build(
        monkeypatch,
        [response({"publicKey": key[1]}), response({"publicKey": "malformed"})],
    )
    call(flow, "image")
    with pytest.raises(AccountClientError) as malformed:
        call(flow, "image")
    assert malformed.value.code == "ACCOUNT_PROTOCOL_INVALID"
    with pytest.raises(f.FlowError) as absent:
        call(flow, "register", "Demo_Pass9!", "246810")
    assert absent.value.code == "FLOW_KEY_MISSING" and len(requests) == 2


@pytest.mark.parametrize("kind", ["pkcs1", "private", "ec", "newline", "trailing"])
def test_only_standard_base64_der_spki_rsa_is_admitted(monkeypatch, key, kind):
    from cryptography.hazmat.primitives.asymmetric import ec

    der = base64.b64decode(key[1])
    values = {
        "pkcs1": base64.b64encode(
            key[0]
            .public_key()
            .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.PKCS1)
        ).decode(),
        "private": base64.b64encode(
            key[0].private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        ).decode(),
        "ec": base64.b64encode(
            ec.generate_private_key(ec.SECP256R1())
            .public_key()
            .public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).decode(),
        "newline": key[1] + "\n",
        "trailing": base64.b64encode(der + b"extra").decode(),
    }
    f, flow, requests = build(monkeypatch, [response({"publicKey": values[kind]})])
    with pytest.raises(AccountClientError):
        call(flow, "image")
    with pytest.raises(f.FlowError):
        call(flow, "register", "Demo_Pass9!", "246810")
    assert len(requests) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("password", ""),
        ("code", ""),
        ("password", "nul\x00P@ss1"),
        ("password", "\U0001f600P@ss1"),
        ("password", "\ud800"),
        ("code", "x" * 4097),
    ],
)
def test_invalid_final_inputs_never_dispatch_or_leak_context(monkeypatch, field, value):
    _, flow, requests = build(monkeypatch, [], purpose="RECOVER")
    password = value if field == "password" else "Demo_Pass9!"
    code = value if field == "code" else "246810"
    with pytest.raises(AccountClientError) as error:
        call(flow, "recover", password, code)
    assert error.value.code == "ACCOUNT_PROTOCOL_INVALID"
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert value not in repr(error.value) if value else True
    assert not requests


def test_phone_format_keeps_locale_country_and_configured_domain_separate(monkeypatch):
    f, flow, requests = build(
        monkeypatch,
        [response({})],
        mode="PHONE",
        account="82+1012345678",
        country="US",
        default_domain="example.invalid",
        customer_app_id="demo-app",
    )
    assert f.AccountBinding.phone("82", "1012345678").account == "82+1012345678"
    call(flow, "issue_code")
    envelope = json.loads(requests[0].body)
    assert envelope["data"] == {
        "loginName": "82+1012345678",
        "loginType": 1,
        "businessType": 15,
        "lang": "en",
        "customerMark": "bacfc77a8608429e45caf98484cd712c",
        "customerAppId": "demo-app",
    }
    assert set(envelope["basic"]) == {"ver", "id", "time", "nonce"}


def test_local_rate_policy_has_no_server_ttl_claim(monkeypatch):
    now = [10.0]
    f, flow, requests = build(
        monkeypatch,
        [response({}), response({})],
        code_interval_seconds=3,
        monotonic=lambda: now[0],
    )
    call(flow, "issue_code")
    with pytest.raises(f.FlowError) as rate:
        call(flow, "issue_code")
    assert rate.value.code == "FLOW_RATE_LIMITED" and len(requests) == 1
    now[0] = 13
    assert call(flow, "issue_code").state is f.FlowState.CODE_SENT


@pytest.mark.parametrize(
    "mode,purpose,account",
    [
        (1, "REGISTER", "a"),
        ("EMAIL", 15, "a"),
        ("EMAIL", "REGISTER", ""),
        ("EMAIL", "REGISTER", "a\x00"),
    ],
)
def test_unsupported_modes_purposes_and_empty_account_rejected_before_boundary(
    monkeypatch, mode, purpose, account
):
    f = subject()
    import wso_core.tvt.account_client as client

    launches = []
    monkeypatch.setattr(
        client, "ProcessAccountTransport", lambda *a, **k: launches.append(a)
    )
    with pytest.raises(AccountClientError):
        f.PreloginAccountFlow(
            scope(),
            f.AccountBinding(
                f.AccountMode[mode] if isinstance(mode, str) else mode, account
            ),
            f.FlowPurpose[purpose] if isinstance(purpose, str) else purpose,
            f.OriginPolicy({"host-test": frozenset({"https://localhost:1"})}),
            origin="https://localhost:1",
        )
    assert not launches


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", UUID(int=8)),
        ("actor_user_id", UUID(int=9)),
        ("region", "other"),
        ("brand", "other"),
        ("identity_id", UUID(int=3)),
    ],
)
def test_all_scope_dimensions_invalidate_flow_state(monkeypatch, key, field, value):
    f, flow, requests = build(monkeypatch, [response({"publicKey": key[1]})])
    call(flow, "image")
    with pytest.raises(AccountClientError) as error:
        call(
            flow,
            "register",
            "Demo_Pass9!",
            "246810",
            supplied_scope=scope().model_copy(update={field: value}),
        )
    assert error.value.code == "ACCOUNT_SCOPE_INVALID"
    with pytest.raises(f.FlowError):
        call(flow, "register", "Demo_Pass9!", "246810")
    assert len(requests) == 1


def test_expiry_during_owned_precursor_never_admits_late_key(monkeypatch, key):
    now = [10.0]

    def late(request):
        now[0] = 12
        return response({"publicKey": key[1]})

    f, flow, requests = build(
        monkeypatch, [late], lifetime_seconds=2, monotonic=lambda: now[0]
    )
    with pytest.raises(f.FlowError) as expired:
        call(flow, "image")
    assert expired.value.code == "FLOW_EXPIRED"
    with pytest.raises(f.FlowError):
        call(flow, "register", "Demo_Pass9!", "246810")
    assert len(requests) == 1


def test_dc_candidate_pending_without_replay_or_key_admission(monkeypatch):
    f, flow, requests = build(
        monkeypatch,
        [
            response(
                {
                    "domain": "localhost",
                    "port": 1,
                    "httpPrefix": "https://",
                    "publicKey": "not-admitted",
                },
                404,
            )
        ],
    )
    result = call(flow, "issue_code")
    assert result.state is f.FlowState.FAILED and result.native_msgcode == 404
    assert result.error_code == "ACCOUNT_DC_PENDING"
    assert result.dc.origin == "https://localhost:1/mobile_v1.0" and len(requests) == 1


def test_quarantine_retains_boundary_owner_and_zero_followup_sends(monkeypatch):
    import gc
    import weakref

    import wso_core.tvt.account_client as client
    from wso_core.tvt.account_process import AccountProcessError

    f = subject()
    refs, requests = [], []

    class Boundary:
        def send(self, request):
            requests.append(request)
            raise AccountProcessError("Account process settlement could not be proved.")

        def close(self):
            pass

    def create(*a, **k):
        owned = Boundary()
        refs.append(weakref.ref(owned))
        return owned

    monkeypatch.setattr(client, "ProcessAccountTransport", create)
    flow = f.PreloginAccountFlow(
        scope(),
        f.AccountBinding(f.AccountMode.EMAIL, "alice@example.invalid"),
        f.FlowPurpose.RECOVER,
        f.OriginPolicy({"host-test": frozenset({"https://localhost:1"})}),
        origin="https://localhost:1",
    )
    result = call(flow, "recover", "Demo_Pass9!", "246810")
    assert (
        result.state is f.FlowState.UNKNOWN_OUTCOME
        and result.error_code == "ACCOUNT_QUARANTINED"
    )
    gc.collect()
    assert refs[0]() is not None
    with pytest.raises(f.FlowError):
        call(flow, "recover", "Demo_Pass9!", "246810")
    assert len(requests) == 1


def test_actual_owned_verified_tls_prelogin_register_and_separate_recovery(
    monkeypatch, tmp_path, key
):
    import ssl
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import wso_core.tvt.account_process as process
    from test_account_process import (
        assert_settled,
        child_processes,
        tls_peer,
        trust_host_peer,
    )

    f = subject()
    # Reuse source-owned certificate creation and narrow normal-CA injection.
    cert_fixture = tls_peer.__wrapped__(tmp_path)
    _, certificate, _, _, _ = next(cert_fixture)
    children_fixture = child_processes.__wrapped__(monkeypatch)
    children, launches = next(children_fixture)
    received = []
    replies = iter(
        [
            {"isExist": False},
            {"idCode": "host-id", "imgCodeImgData": "host-image"},
            {"idCode": "host-id", "imgData": "host-challenge", "publicKey": key[1]},
            {},
            {},
            {},
        ]
    )
    codes = iter([200, 200, 1007, 200, 200, 200])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, self.headers["Content-Type"], body))
            payload = json.dumps(
                {"basic": {"msgcode": next(codes)}, "data": next(replies)}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, tmp_path / "host-key.pem")
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, name="w06-owned-tls")
    worker.start()
    trust_host_peer(monkeypatch, process, certificate)
    origin = f"https://localhost:{server.server_port}"
    policy = f.OriginPolicy({"host-test": frozenset({origin})})
    register = f.PreloginAccountFlow(
        scope(),
        f.AccountBinding(f.AccountMode.EMAIL, "alice@example.invalid"),
        f.FlowPurpose.REGISTER,
        policy,
        origin=origin,
        protocol=protocol(),
        country="KR",
    )
    recovery = f.PreloginAccountFlow(
        scope(),
        f.AccountBinding.phone("82", "1012345678"),
        f.FlowPurpose.RECOVER,
        policy,
        origin=origin,
        protocol=protocol(),
    )
    try:
        assert call(register, "exists").exists is False
        assert call(register, "image").state is f.FlowState.IMAGE_AVAILABLE
        assert call(register, "issue_code").state is f.FlowState.IMAGE_REQUIRED
        assert call(register, "register", "Demo_Pass9!", "246810").return_to_login
        assert call(recovery, "issue_code").state is f.FlowState.CODE_SENT
        assert call(recovery, "recover", "Demo_Pass9!", "246810").return_to_login
        assert [p for p, _, _ in received] == [
            "/user/info/email/is-exist",
            "/user/img-code/get",
            "/user/sms-code/no-token/get",
            "/user/register",
            "/user/sms-code/no-token/get",
            "/user/info/password/reset",
        ]
        assert all(
            content == "application/json;charset=UTF-8" for _, content, _ in received
        )
        envelopes = [json.loads(body) for _, _, body in received]
        assert [e["basic"]["id"] for e in envelopes] == ["1", "2", "3", "4", "1", "2"]
        assert [e["basic"]["ver"] for e in envelopes] == [
            "1.0",
            "1.0",
            "1.0",
            "1.1",
            "1.0",
            "1.1",
        ]
        assert all("token" not in e["basic"] for e in envelopes)
        assert (
            envelopes[2]["data"]["businessType"] == 15
            and envelopes[4]["data"]["businessType"] == 12
        )
        assert (
            key[0].decrypt(
                base64.b64decode(envelopes[3]["data"]["password"]), padding.PKCS1v15()
            )
            == b"6b1c65a3262e953bfabf2d0a84b95cf8"
        )
        assert envelopes[5]["data"] == {
            "loginName": "82+1012345678",
            "dynamicCode": "246810",
            "newPassword": "6b1c65a3262e953bfabf2d0a84b95cf8",
            "lang": "en",
        }
        for flow, method in ((register, "register"), (recovery, "recover")):
            with pytest.raises(f.FlowError):
                call(flow, method, "Demo_Pass9!", "246810")
        assert len(children) == 6 and len(received) == 6
        assert_settled(children)
        assert all(
            not any(
                private in repr(args) for private in ("Demo_Pass9!", "246810", key[1])
            )
            for args, _ in launches
        )
    finally:
        register.close()
        recovery.close()
        server.shutdown()
        server.server_close()
        worker.join(2)
        assert not worker.is_alive()
        with pytest.raises(StopIteration):
            next(children_fixture)
        with pytest.raises(StopIteration):
            next(cert_fixture)
        certificate.unlink()
        (tmp_path / "host-key.pem").unlink()
        assert not certificate.exists() and not (tmp_path / "host-key.pem").exists()


def test_cancel_after_final_submission_is_unknown_with_zero_duplicate_sends(
    monkeypatch,
):
    entered, release = threading.Event(), threading.Event()

    def delayed(request):
        entered.set()
        assert release.wait(3)
        return response({})

    f, flow, requests = build(monkeypatch, [delayed], purpose="RECOVER")
    results = []
    worker = threading.Thread(
        target=lambda: results.append(call(flow, "recover", "Demo_Pass9!", "246810"))
    )
    worker.start()
    try:
        assert entered.wait(2)
        flow.close()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive() and len(results) == 1
    assert (
        results[0].state is f.FlowState.UNKNOWN_OUTCOME
        and results[0].error_code == "ACCOUNT_CANCELLED"
    )
    with pytest.raises(f.FlowError):
        call(flow, "recover", "Demo_Pass9!", "246810")
    assert len(requests) == 1


@pytest.mark.parametrize("late_exchange", [False, True])
def test_flow_whole_budget_suppresses_late_final_success(monkeypatch, late_exchange):
    from types import SimpleNamespace

    import wso_core.tvt.account_client as client

    f, flow, requests = build(monkeypatch, [response({})], purpose="RECOVER")
    now = [100.0]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(f, "time", clock)
    monkeypatch.setattr(client, "time", clock)
    if late_exchange:

        def late(request):
            now[0] += 0.2
            return response({})

        # Replace only the slow boundary exchange; keep request/response real.
        _, flow, requests = build(monkeypatch, [late], purpose="RECOVER")
    else:

        def serializer_clock():
            now[0] += 0.2
            return 1700000000

        flow._client._protocol = AccountProtocol(
            task_ids=SessionTaskIds(), clock=serializer_clock, nonce=lambda: 123456789
        )
    result = flow.recover(
        scope(), "Demo_Pass9!", "246810", deadline_ms=100, correlation_id="flow-test"
    )
    assert (
        result.state is f.FlowState.UNKNOWN_OUTCOME
        and result.error_code == "ACCOUNT_DEADLINE_EXCEEDED"
    )
    assert len(requests) == int(late_exchange)
    with pytest.raises(f.FlowError):
        call(flow, "recover", "Demo_Pass9!", "246810")


def test_local_expiry_after_final_send_is_unknown_and_consumed(monkeypatch):
    now = [10.0]

    def late(request):
        now[0] = 12
        return response({})

    f, flow, requests = build(
        monkeypatch,
        [late],
        purpose="RECOVER",
        lifetime_seconds=2,
        monotonic=lambda: now[0],
    )
    result = call(flow, "recover", "Demo_Pass9!", "246810")
    assert result.state is f.FlowState.UNKNOWN_OUTCOME and not result.return_to_login
    assert result.http_status == 200 and result.native_msgcode == 200
    with pytest.raises(f.FlowError):
        call(flow, "recover", "Demo_Pass9!", "246810")
    assert len(requests) == 1


@pytest.mark.parametrize(
    "status,code",
    [(200, 7019), (200, 7006), (200, 7023), (200, 1008), (503, 200), (200, 404)],
)
def test_final_rejections_remain_failures_and_locally_consumed(
    monkeypatch, key, status, code
):
    f, flow, requests = build(
        monkeypatch,
        [
            response({"publicKey": key[1]}),
            response({"token": "no-session"}, code, status),
        ],
    )
    call(flow, "image")
    result = call(flow, "register", "Demo_Pass9!", "246810")
    assert result.state is f.FlowState.FAILED and not result.return_to_login
    assert result.http_status == status and result.native_msgcode == code
    with pytest.raises(f.FlowError):
        call(flow, "register", "Demo_Pass9!", "246810")
    assert len(requests) == 2 and "no-session" not in repr(result)


def test_public_key_in_non_precursor_response_does_not_admit_registration_key(
    monkeypatch, key
):
    f, flow, requests = build(
        monkeypatch, [response({"isExist": False, "publicKey": key[1]})]
    )
    call(flow, "exists")
    with pytest.raises(f.FlowError) as error:
        call(flow, "register", "Demo_Pass9!", "246810")
    assert error.value.code == "FLOW_KEY_MISSING" and len(requests) == 1


def test_foreign_scope_during_precursor_cannot_admit_late_key(monkeypatch, key):
    entered, release = threading.Event(), threading.Event()

    def delayed(request):
        entered.set()
        assert release.wait(3)
        return response({"publicKey": key[1]})

    f, flow, requests = build(monkeypatch, [delayed])
    errors = []

    def run():
        try:
            call(flow, "image")
        except AccountClientError as error:
            errors.append(error.code)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(AccountClientError):
            call(
                flow,
                "image",
                supplied_scope=scope().model_copy(update={"brand": "foreign"}),
            )
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive() and errors == ["ACCOUNT_SCOPE_INVALID"]
    with pytest.raises(f.FlowError):
        call(flow, "register", "Demo_Pass9!", "246810")
    assert len(requests) == 1


@pytest.mark.parametrize("deadline", [0, -1, True, 1.5, 60001])
def test_invalid_deadlines_reject_before_serialization_or_boundary(
    monkeypatch, deadline
):
    _, flow, requests = build(monkeypatch, [], purpose="RECOVER")
    with pytest.raises(AccountClientError) as error:
        flow.recover(
            scope(),
            "Demo_Pass9!",
            "246810",
            deadline_ms=deadline,
            correlation_id="flow-test",
        )
    assert error.value.code == "ACCOUNT_INPUT_INVALID" and not requests


@pytest.mark.parametrize("correlation", [None, "", "unsafe\nbody", "x" * 129])
def test_invalid_correlations_are_not_reflected_or_dispatched(monkeypatch, correlation):
    _, flow, requests = build(monkeypatch, [], purpose="RECOVER")
    with pytest.raises(AccountClientError) as error:
        flow.recover(
            scope(),
            "Demo_Pass9!",
            "246810",
            deadline_ms=3000,
            correlation_id=correlation,
        )
    assert error.value.correlation_id is None and not requests


@pytest.mark.parametrize(
    "purpose,code,status,data",
    [
        (
            "RECOVER",
            1005,
            200,
            {
                "imgData": "private-rejected-image",
                "publicKey": "must-not-parse",
                "token": "must-not-mint",
            },
        ),
        ("REGISTER", 1005, 200, None),
        ("REGISTER", 1007, 200, []),
        ("RECOVER", 1007, 200, "private-nonobject"),
        ("RECOVER", 1005, 200, 7),
        (
            "REGISTER",
            1008,
            200,
            {"privateEvidence": "private-error", "publicKey": "must-not-parse"},
        ),
        (
            "REGISTER",
            1007,
            503,
            {"imgData": "private-http-error", "publicKey": "must-not-parse"},
        ),
        (
            "RECOVER",
            200,
            401,
            {"publicKey": "must-not-parse", "token": "must-not-mint"},
        ),
        (
            "REGISTER",
            404,
            200,
            {
                "domain": "localhost",
                "port": 1,
                "httpPrefix": "https://",
                "publicKey": "must-not-parse",
            },
        ),
    ],
)
def test_fix1_rejected_dynamic_retains_bounded_private_body_without_key_admission(
    monkeypatch, key, purpose, code, status, data
):
    # Rejecting evidence must survive the real parser/executor/result path, even
    # when the operation decoder is skipped. Key admission must remain absent.
    rejected = response(data, code, status)
    f, flow, requests = build(
        monkeypatch,
        [response({"publicKey": key[1], "idCode": "old-private-id"}), rejected],
        purpose=purpose,
    )
    call(flow, "image")
    result = call(flow, "issue_code")
    assert result.state is f.FlowState.FAILED and result.challenge is None
    assert result.http_status == status and result.native_msgcode == code
    assert result.private_body == rejected.private_body
    assert result.error_code == (
        "ACCOUNT_DC_PENDING" if code == 404 else "ACCOUNT_UPSTREAM_REJECTED"
    )
    assert not result.return_to_login
    assert not any(
        private in repr(result) + repr(flow)
        for private in ("private-", "must-not-parse", "must-not-mint", key[1])
    )
    if purpose == "REGISTER":
        with pytest.raises(f.FlowError) as missing:
            call(flow, "register", "Demo_Pass9!", "246810")
        assert missing.value.code == "FLOW_KEY_MISSING"
    with pytest.raises(AccountClientError) as cleared_image:
        call(flow, "issue_code", image_code="1234")
    assert cleared_image.value.code == "ACCOUNT_PROTOCOL_INVALID"
    assert cleared_image.value.__context__ is None
    assert len(requests) == 2


@pytest.mark.parametrize(
    "raw", [b"null", b"{", b'{"basic":{}}', b'{"basic":{"msgcode":true},"data":null}']
)
def test_fix1_unvalidated_dynamic_response_never_retains_raw_bytes(monkeypatch, raw):
    from wso_core.tvt.account_protocol import AccountResponse

    f, flow, requests = build(monkeypatch, [AccountResponse(200, 200, raw)])
    result = call(flow, "issue_code")
    assert result.state is f.FlowState.UNKNOWN_OUTCOME
    assert (
        result.error_code == "ACCOUNT_PROTOCOL_INVALID" and result.private_body == b""
    )
    assert result.http_status is None and result.native_msgcode is None
    assert raw.decode() not in repr(result)
    with pytest.raises(f.FlowError):
        call(flow, "issue_code")
    assert len(requests) == 1


def test_fix1_oversized_dynamic_body_cannot_enter_private_evidence(monkeypatch):
    too_large = response({"privateEvidence": "x" * 129}, 1008)
    assert len(too_large.private_body) > 128
    f, flow, requests = build(monkeypatch, [too_large], max_body_bytes=128)
    result = call(flow, "issue_code")
    assert result.state is f.FlowState.UNKNOWN_OUTCOME
    assert (
        result.error_code == "ACCOUNT_PROTOCOL_INVALID" and result.private_body == b""
    )
    assert result.http_status is None and result.native_msgcode is None
    with pytest.raises(f.FlowError):
        call(flow, "issue_code")
    assert len(requests) == 1


def test_fix1_private_evidence_accepts_exact_original_body_cap(monkeypatch):
    rejected = response({"privateEvidence": "opaque"}, 1008)
    f, flow, _ = build(
        monkeypatch, [rejected], max_body_bytes=len(rejected.private_body)
    )
    result = call(flow, "issue_code")
    assert (
        result.state is f.FlowState.FAILED
        and result.private_body == rejected.private_body
    )


@pytest.mark.parametrize("code", [1005, 1007])
def test_fix1_absent_dynamic_data_retains_exact_observed_body(monkeypatch, code):
    observed = parse_response(200, json.dumps({"basic": {"msgcode": code}}).encode())
    f, flow, requests = build(monkeypatch, [observed])
    result = call(flow, "issue_code")
    assert result.state is f.FlowState.FAILED and result.challenge is None
    assert result.http_status == 200 and result.native_msgcode == code
    assert result.private_body == observed.private_body
    assert result.error_code == "ACCOUNT_UPSTREAM_REJECTED" and len(requests) == 1
