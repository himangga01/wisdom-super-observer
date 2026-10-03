"""Invented private inputs; source bytes, bounded projections, sole containment."""

import importlib
import json
from uuid import UUID

import pytest
from wso_contracts.tvt.identity import AccountScope, TokenKind, TvtIdentityRef
from wso_core.tvt.account_client import AccountClient
from wso_core.tvt.account_protocol import (
    AccountProtocol,
    AccountProtocolError,
    SessionTaskIds,
    parse_response,
)
from wso_core.tvt.account_transport import OriginPolicy
from wso_core.tvt.ports import AccountClientError, PrivateToken


def subject(part):
    name = "wso_core.tvt.security_" + part
    assert importlib.util.find_spec(name) is not None, (
        "Private security adapter missing"
    )
    return importlib.import_module(name)


def identity():
    return TvtIdentityRef(
        tenant_id=UUID(int=1), actor_user_id=UUID(int=2), identity_id=UUID(int=3)
    )


def scope():
    return AccountScope(**identity().model_dump(), region="host-test", brand="demo")


def token():
    return PrivateToken(identity(), TokenKind.USER, "synthetic-user")


def protocol():
    return subject("protocol").SecurityProtocol(
        AccountProtocol(
            task_ids=SessionTaskIds(), clock=lambda: 1700000000, nonce=lambda: 123456789
        )
    )


def reply(data=None, code=200, status=200):
    return parse_response(
        status, json.dumps({"basic": {"msgcode": code}, "data": data}).encode()
    )


def cases():
    s = subject("protocol")
    return [
        (
            "update_profile",
            s.ProfileUpdate("한글", 4, "", ""),
            "/user/info/update",
            {"nickName": "한글", "name": "", "address": "", "type": 4},
        ),
        (
            "bind_phone",
            s.PhoneBind("82+1012345678", "123456"),
            "/user/info/phone/bind",
            {"mobile": "82+1012345678", "dynamicCode": "123456"},
        ),
        (
            "bind_email",
            s.EmailBind("a@example.invalid", "234567"),
            "/user/info/email/bind",
            {"email": "a@example.invalid", "dynamicCode": "234567"},
        ),
        (
            "change_phone",
            s.PhoneChange("111111", "82+1098765432", "222222"),
            "/user/info/phone/update",
            {
                "oldMobileCode": "111111",
                "newMobile": "82+1098765432",
                "newMobileCode": "222222",
            },
        ),
        (
            "change_email",
            s.EmailChange("333333", "b@example.invalid", "444444"),
            "/user/info/email/update",
            {
                "oldEmailCode": "333333",
                "newEmail": "b@example.invalid",
                "newEmailCode": "444444",
            },
        ),
    ]


def test_exact_fixed_serializers_and_generic_user_bytes():
    for method, value, path, data in cases():
        request = getattr(protocol(), method)("synthetic-user", value)
        expected = {
            "basic": {
                "ver": "1.0",
                "id": "1",
                "token": "synthetic-user",
                "time": 1700000000,
                "nonce": 123456789,
            },
            "data": data,
        }
        assert request.path == path
        assert (
            request.body
            == json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode()
        )
        assert "synthetic-user" not in repr(request) + repr(value)
    request = protocol().login_types("synthetic-user")
    assert request.path == "/user/info/login-type/list"
    assert "data" not in json.loads(request.body)


@pytest.mark.parametrize("kind", [-(2**31), -1, 0, 1, 4, 2**31 - 1])
def test_signed_profile_type_presence_and_no_annotated_fields(kind):
    s = subject("protocol")
    data = json.loads(
        protocol()
        .update_profile("synthetic-user", s.ProfileUpdate("nickname", kind, "", ""))
        .body
    )["data"]
    assert data == (
        {"nickName": "nickname", "name": "", "address": "", "type": kind}
        if kind > 0
        else {"nickName": "nickname", "name": "", "address": ""}
    )


@pytest.mark.parametrize("value", [True, 2**31, -(2**31) - 1, "1"])
def test_profile_rejects_non_native_type(value):
    s = subject("protocol")
    with pytest.raises(AccountProtocolError):
        protocol().update_profile(
            "synthetic-user", s.ProfileUpdate("nickname", value, "", "")
        )


def test_contact_inputs_are_not_interchangeable_and_fields_cannot_be_empty():
    s = subject("protocol")
    with pytest.raises(AccountProtocolError):
        protocol().bind_phone(
            "synthetic-user", s.EmailBind("a@example.invalid", "123456")
        )
    for args in [
        ("", "new", "222222"),
        ("111111", "", "222222"),
        ("111111", "new", ""),
    ]:
        with pytest.raises(AccountProtocolError):
            protocol().change_phone("synthetic-user", s.PhoneChange(*args))
    with pytest.raises(AccountProtocolError):
        protocol().update_profile("", s.ProfileUpdate("nickname", 0, "", ""))


@pytest.mark.parametrize(
    "purpose,mode,stage,account",
    [
        (1, 2, "CURRENT", ""),
        (2, 1, "CURRENT", ""),
        (3, 2, "OLD", ""),
        (3, 2, "NEW", "new@example.invalid"),
        (4, 1, "OLD", ""),
        (4, 1, "NEW", "82+1012345678"),
    ],
)
def test_dynamic_purpose_stage_selector_and_image_presence(
    purpose, mode, stage, account
):
    s = subject("protocol")
    value = s.SecurityCode(
        s.CodePurpose(purpose),
        s.CodeStage[stage],
        mode,
        account,
        "en",
        image_id="image-1",
        image_code="ABCD",
    )
    request = protocol().issue_code("synthetic-user", value)
    assert request.path == "/user/sms-code/get"
    assert json.loads(request.body)["data"] == {
        "loginName": account,
        "loginType": mode,
        "businessType": purpose,
        "lang": "en",
        "idCode": "image-1",
        "imgCode": "ABCD",
    }
    value = s.SecurityCode(
        s.CodePurpose(purpose),
        s.CodeStage[stage],
        mode,
        account,
        "en",
        image_id="ignored",
    )
    data = json.loads(protocol().issue_code("synthetic-user", value).body)["data"]
    assert "idCode" not in data and "imgCode" not in data


@pytest.mark.parametrize(
    "purpose,mode,stage,account",
    [
        (3, 2, "OLD", "new@example.invalid"),
        (3, 2, "NEW", ""),
        (3, 1, "NEW", "new"),
        (4, 2, "NEW", "new"),
        (1, 1, "NEW", "new"),
        (2, 1, "OLD", ""),
    ],
)
def test_dynamic_rejects_wrong_stage_account_or_mode(purpose, mode, stage, account):
    s = subject("protocol")
    with pytest.raises(AccountProtocolError):
        protocol().issue_code(
            "synthetic-user",
            s.SecurityCode(
                s.CodePurpose(purpose), s.CodeStage[stage], mode, account, "en"
            ),
        )


def test_inventory_is_typed_bounded_and_empty_requires_explicit_list():
    s = subject("projection")
    assert s.parse_login_types(reply([])).entries == ()
    parsed = s.parse_login_types(
        reply([{"userId": "id-A", "loginName": "a@example.invalid", "loginType": 2}])
    )
    assert parsed.entries[0].user_id == "id-A"
    assert parsed.entries[0].login_name == "a@example.invalid"
    assert parsed.entries[0].login_type == 2
    assert "a@example.invalid" not in repr(parsed)


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        "",
        {"array": []},
        [{}],
        [{"userId": "u", "loginName": "a", "loginType": True}],
        [{"userId": "u", "loginName": "a", "loginType": "2"}],
        [{"userId": "u", "loginName": "a", "loginType": 2}] * 2,
        [{"userId": "u", "loginName": "a" * 4097, "loginType": 2}],
    ],
)
def test_inventory_missing_malformed_duplicates_are_unavailable(data):
    with pytest.raises(AccountProtocolError):
        subject("projection").parse_login_types(reply(data))


def test_inventory_overbound_and_missing_data_no_array_fallback():
    with pytest.raises(AccountProtocolError):
        subject("projection").parse_login_types(
            reply(
                [
                    {"userId": "u", "loginName": str(i), "loginType": 2}
                    for i in range(65)
                ]
            )
        )
    with pytest.raises(AccountProtocolError):
        subject("projection").parse_login_types(
            parse_response(200, b'{"basic":{"msgcode":200},"array":[]}')
        )


def test_acknowledgement_discards_private_body_and_challenge_is_distinct():
    s = subject("projection")
    result = s.parse_acknowledgement(
        reply({"sid": "private-value", "token": "private-value"})
    )
    assert result.acknowledged and "private-value" not in repr(result)
    assert s.parse_code(reply()).state == "CODE_SENT"
    for code, state in [(1007, "IMAGE_REQUIRED"), (1005, "IMAGE_REJECTED")]:
        parsed = s.parse_code(
            reply({"idCode": "image-1", "imgData": "private-image"}, code)
        )
        assert (
            parsed.state == state
            and parsed.image_id == "image-1"
            and parsed.private_image_data == "private-image"
        )
        assert "private-image" not in repr(parsed)
    for bad in [
        reply(None, 1007),
        reply({"idCode": "i", "imgCodeImgData": "wrong"}, 1005),
        reply(None, 200, 500),
        reply(None, 7000),
    ]:
        with pytest.raises(AccountProtocolError):
            s.parse_code(bad)


def build(monkeypatch, response):
    from wso_core.tvt import account_client

    requests = []
    launches = []

    class Boundary:
        def send(self, request):
            requests.append(request)
            if isinstance(response, Exception):
                raise response
            return response

        def close(self):
            pass

    def launch(*args, **kwargs):
        launches.append(kwargs)
        return Boundary()

    monkeypatch.setattr(account_client, "ProcessAccountTransport", launch)
    account = AccountClient(
        scope(),
        OriginPolicy(
            {
                "host-test": frozenset(
                    {"https://localhost:1", "https://localhost:1/mobile_v1.0"}
                )
            }
        ),
        origin="https://localhost:1",
        identity=identity(),
    )
    return subject("client").SecurityClient(account), requests, launches


def test_client_scope_rejection_precedes_dispatch(monkeypatch):
    client, requests, launches = build(monkeypatch, reply())
    bad = PrivateToken(identity(), TokenKind.P2P, "synthetic-user")
    with pytest.raises(AccountClientError):
        client.bind_phone(
            identity(),
            bad,
            subject("protocol").PhoneBind("new", "123456"),
            deadline_ms=1000,
            correlation_id="scope-1",
        )
    assert not requests and not launches


@pytest.mark.parametrize(
    "error",
    [
        "Account process deadline exceeded.",
        "Account process request cancelled.",
        "Account process settlement could not be proved.",
    ],
)
def test_possible_write_dispatch_failure_is_unknown_and_never_replayed(
    monkeypatch, error
):
    from wso_core.tvt.account_process import AccountProcessError

    client, requests, launches = build(monkeypatch, AccountProcessError(error))
    result = client.bind_phone(
        identity(),
        token(),
        subject("protocol").PhoneBind("new", "123456"),
        deadline_ms=1000,
        correlation_id="write-1",
    )
    assert result.state == "UNKNOWN_OUTCOME" and not result.ok
    assert len(requests) == len(launches) == 1


def test_client_challenge_and_business_failure_do_not_become_acknowledged(monkeypatch):
    client, _, _ = build(
        monkeypatch, reply({"idCode": "image-1", "imgData": "image-bytes"}, 1007)
    )
    s = subject("protocol")
    result = client.issue_code(
        identity(),
        token(),
        s.SecurityCode(
            s.CodePurpose.EMAIL, s.CodeStage.NEW, 2, "new@example.invalid", "en"
        ),
        deadline_ms=1000,
        correlation_id="code-1",
    )
    assert result.state == "IMAGE_REQUIRED" and not result.ok
    client, _, _ = build(monkeypatch, reply(None, 7000))
    result = client.bind_email(
        identity(),
        token(),
        s.EmailBind("new@example.invalid", "123456"),
        deadline_ms=1000,
        correlation_id="reject-1",
    )
    assert result.state == "REJECTED" and not result.ok


def test_source_json_text_inventory_and_challenge_are_decoded_safely():
    s = subject("projection")
    result = s.parse_login_types(
        reply('[{"userId":"u","loginName":"a","loginType":2}]')
    )
    assert result.entries[0].login_name == "a"
    assert (
        s.parse_code(reply('{"idCode":"image-1","imgData":"bytes"}', 1007)).image_id
        == "image-1"
    )
    with pytest.raises(AccountProtocolError):
        s.parse_login_types(
            reply('[{"userId":"u","userId":"foreign","loginName":"a","loginType":2}]')
        )


@pytest.mark.parametrize(
    "parser,data,code",
    [
        ("parse_login_types", '[],"extra":0', 200),
        ("parse_code", '{"idCode":"image-1","imgData":"bytes"},"extra":0', 1007),
    ],
)
def test_json_text_trailing_wrapper_members_are_malformed(parser, data, code):
    with pytest.raises(AccountProtocolError) as error:
        getattr(subject("projection"), parser)(reply(data, code))
    assert error.value.__context__ is None
    assert "extra" not in str(error.value)


@pytest.mark.parametrize("challenge", [False, True])
def test_client_json_text_wrapper_escape_never_proves_empty_or_challenge(
    monkeypatch, challenge
):
    data = (
        '{"idCode":"image-1","imgData":"bytes"},"extra":0'
        if challenge
        else '[],"extra":0'
    )
    client, requests, launches = build(
        monkeypatch, reply(data, 1007 if challenge else 200)
    )
    if challenge:
        s = subject("protocol")
        result = client.issue_code(
            identity(),
            token(),
            s.SecurityCode(
                s.CodePurpose.EMAIL, s.CodeStage.NEW, 2, "a@example.invalid", "en"
            ),
            deadline_ms=1000,
            correlation_id="wrapper-challenge",
        )
        assert result.state == "UNKNOWN_OUTCOME"
        assert result.error_code == "ACCOUNT_PROTOCOL_INVALID" and result.value is None
    else:
        with pytest.raises(AccountClientError) as error:
            client.login_types(
                identity(), token(), deadline_ms=1000, correlation_id="wrapper-list"
            )
        assert error.value.code == "ACCOUNT_PROTOCOL_INVALID"
        assert error.value.__context__ is None
    assert len(requests) == len(launches) == 1


def test_constructor_unset_profile_fields_cannot_become_editable_fields():
    s = subject("protocol")
    for name, address in [("editable-name", ""), ("", "editable-address")]:
        with pytest.raises(AccountProtocolError):
            protocol().update_profile(
                "synthetic-user", s.ProfileUpdate("nickname", 1, name, address)
            )


@pytest.mark.parametrize("text", ["\x00", "\U0001f600", "\ud800", "x" * 4097])
def test_native_string_bounds_reject_unsupported_representation_before_request(text):
    s = subject("protocol")
    with pytest.raises(AccountProtocolError):
        protocol().bind_email("synthetic-user", s.EmailBind(text, "123456"))


def test_config_customer_fields_use_source_md5_domain_and_image_requires_id():
    s = subject("protocol")
    p = s.SecurityProtocol(
        protocol()._account,
        customer_app_id="synthetic-app",
        default_domain="example.invalid",
    )
    value = s.SecurityCode(
        s.CodePurpose.EMAIL, s.CodeStage.NEW, 2, "a@example.invalid", "en"
    )
    data = json.loads(p.issue_code("synthetic-user", value).body)["data"]
    assert data["customerAppId"] == "synthetic-app"
    assert data["customerMark"] == "bacfc77a8608429e45caf98484cd712c"
    with pytest.raises(AccountProtocolError):
        p.issue_code(
            "synthetic-user",
            s.SecurityCode(
                s.CodePurpose.EMAIL,
                s.CodeStage.NEW,
                2,
                "a@example.invalid",
                "en",
                image_code="ABCD",
            ),
        )


def test_unknown_write_protocol_failure_discards_private_exception_context(monkeypatch):
    client, requests, _ = build(
        monkeypatch, reply({"idCode": "private-id", "imgData": None}, 1007)
    )
    s = subject("protocol")
    result = client.issue_code(
        identity(),
        token(),
        s.SecurityCode(
            s.CodePurpose.EMAIL, s.CodeStage.NEW, 2, "new@example.invalid", "en"
        ),
        deadline_ms=1000,
        correlation_id="invalid-reply",
    )
    assert (
        result.state == "UNKNOWN_OUTCOME"
        and result.error_code == "ACCOUNT_PROTOCOL_INVALID"
    )
    assert len(requests) == 1 and "private-id" not in repr(result)


def test_dc_hint_is_pending_once_without_origin_adoption_or_retry(monkeypatch):
    client, requests, launches = build(
        monkeypatch,
        reply({"domain": "localhost", "dcPort": 1, "httpPrefix": "https://"}, 404),
    )
    s = subject("protocol")

    def call():
        return client.bind_email(
            identity(),
            token(),
            s.EmailBind("new@example.invalid", "123456"),
            deadline_ms=1000,
            correlation_id="dc-1",
        )

    first = call()
    second = call()
    assert (
        first.error_code == "ACCOUNT_DC_PENDING"
        and second.error_code == "ACCOUNT_UPSTREAM_REJECTED"
    )
    assert first.state == second.state == "REJECTED"
    assert len(requests) == len(launches) == 2
    assert all(row["origin"] == "https://localhost:1" for row in launches)


def test_password_unadmitted_or_foreign_key_rejected_without_process(monkeypatch):
    from test_security_key_state import Config, binding, crypto

    client, requests, launches = build(monkeypatch, reply())
    key = crypto().SecurityKeyState(binding(), token(), Config())
    with pytest.raises(AccountClientError) as error:
        client.update_password(
            identity(),
            token(),
            subject("protocol").PasswordUpdate(2, "123456", "Password9!"),
            key,
            binding(),
            deadline_ms=1000,
            correlation_id="no-key",
        )
    assert (
        error.value.code == "ACCOUNT_PROTOCOL_INVALID"
        and error.value.__context__ is None
    )
    assert not requests and not launches


def test_password_requires_admitted_scope_key_and_exact_encrypted_body(monkeypatch):
    from test_security_key_state import binding, state

    s = subject("protocol")
    client, requests, _ = build(monkeypatch, reply())
    key = state()
    result = client.update_password(
        identity(),
        token(),
        s.PasswordUpdate(2, "123456", " new P@ssword9! "),
        key,
        binding(),
        deadline_ms=1000,
        correlation_id="password-1",
    )
    assert result.state == "ACKNOWLEDGED"
    data = json.loads(requests[0].body)["data"]
    assert set(data) == {"loginType", "dynamicCode", "newPassword"}
    assert data["loginType"] == 2 and data["dynamicCode"] == "123456"
    assert len(data["newPassword"]) == 44
    with pytest.raises(AccountProtocolError):
        key.encrypt(binding(), token(), "Password9!")


@pytest.fixture
def security_peer(tmp_path):
    import ssl
    import threading
    from datetime import UTC, datetime, timedelta
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
        .sign(key, hashes.SHA256())
    )
    certificate = tmp_path / "peer.pem"
    key_path = tmp_path / "key.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    received = []
    entered = threading.Event()
    release = threading.Event()
    control = {"block": False, "redirect": False, "code": 200}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append(
                (
                    self.path,
                    dict(self.headers),
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            entered.set()
            if control["block"]:
                release.wait(12)
            data = [] if self.path.endswith("/login-type/list") else None
            if control["code"] == 1007:
                data = {"idCode": "image-1", "imgData": "image-bytes"}
            body = json.dumps(
                {"basic": {"msgcode": control["code"]}, "data": data}
            ).encode()
            try:
                self.send_response(302 if control["redirect"] else 200)
                if control["redirect"]:
                    self.send_header("Location", "https://localhost:1/forbidden")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ssl.SSLError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield (
        f"https://localhost:{server.server_port}",
        certificate,
        received,
        control,
        entered,
        release,
    )
    release.set()
    server.shutdown()
    server.server_close()
    thread.join(3)
    assert not thread.is_alive()


def real_client(monkeypatch, peer, *, trust=True):
    import subprocess

    from test_account_process import trust_host_peer
    from wso_core.tvt import account_process

    origin, certificate, *_ = peer
    if trust:
        trust_host_peer(monkeypatch, account_process, certificate)
    children = []
    original = subprocess.Popen

    def launch(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(account_process.subprocess, "Popen", launch)
    account = AccountClient(
        scope(),
        OriginPolicy({"host-test": frozenset({origin})}),
        origin=origin,
        identity=identity(),
        protocol=protocol()._account,
    )
    return subject("client").SecurityClient(account), children


def test_actual_contained_verified_https_all_eight_paths_and_cleanup(
    monkeypatch, security_peer
):
    from test_account_process import assert_settled
    from test_security_key_state import binding, state

    s = subject("protocol")
    client, children = real_client(monkeypatch, security_peer)
    try:
        for method, value, _, _ in cases():
            result = getattr(client, method)(
                identity(),
                token(),
                value,
                deadline_ms=4000,
                correlation_id="real-" + method,
            )
            assert result.ok and result.state == "ACKNOWLEDGED"
        assert (
            client.login_types(
                identity(), token(), deadline_ms=4000, correlation_id="real-list"
            ).value.entries
            == ()
        )
        assert (
            client.issue_code(
                identity(),
                token(),
                s.SecurityCode(
                    s.CodePurpose.PHONE, s.CodeStage.NEW, 1, "82+1012345678", "en"
                ),
                deadline_ms=4000,
                correlation_id="real-code",
            ).state
            == "CODE_SENT"
        )
        assert (
            client.update_password(
                identity(),
                token(),
                s.PasswordUpdate(2, "123456", "Password9!"),
                state(),
                binding(),
                deadline_ms=4000,
                correlation_id="real-password",
            ).state
            == "ACKNOWLEDGED"
        )
        received = security_peer[2]
        assert [row[0] for row in received] == [row[2] for row in cases()] + [
            "/user/info/login-type/list",
            "/user/sms-code/get",
            "/user/info/password/update",
        ]
        for i, (_, headers, body) in enumerate(received, 1):
            assert body["basic"] == {
                "ver": "1.0",
                "id": str(i),
                "token": "synthetic-user",
                "time": 1700000000,
                "nonce": 123456789,
            }
            assert headers["Content-Type"] == "application/json;charset=UTF-8"
            assert "Authorization" not in headers and "Cookie" not in headers
        assert [row[2]["data"] for row in received[:5]] == [row[3] for row in cases()]
        assert len(children) == 8
        assert_settled(children)
    finally:
        client.close()


@pytest.mark.parametrize(
    "mode", ["timeout", "cancel", "untrusted", "redirect", "challenge"]
)
def test_actual_https_uncertain_writes_tls_redirect_and_challenge(
    monkeypatch, security_peer, mode
):
    import threading

    from test_account_process import assert_settled

    client, children = real_client(
        monkeypatch, security_peer, trust=mode != "untrusted"
    )
    _, _, received, control, entered, release = security_peer
    control["block"] = mode in ("timeout", "cancel")
    control["redirect"] = mode == "redirect"
    control["code"] = 1007 if mode == "challenge" else 200
    s = subject("protocol")
    results = []

    def call():
        results.append(
            client.issue_code(
                identity(),
                token(),
                s.SecurityCode(
                    s.CodePurpose.EMAIL, s.CodeStage.NEW, 2, "new@example.invalid", "en"
                ),
                deadline_ms=6000 if mode == "timeout" else 4000,
                correlation_id="real-" + mode,
            )
        )

    try:
        if mode == "cancel":
            thread = threading.Thread(target=call)
            thread.start()
            assert entered.wait(3)
            client.close()
            thread.join(3)
            assert not thread.is_alive()
        else:
            call()
        assert len(results) == 1 and not results[0].ok
        expected = {"challenge": "IMAGE_REQUIRED", "redirect": "REJECTED"}.get(
            mode, "UNKNOWN_OUTCOME"
        )
        assert results[0].state == expected
        assert len(received) == (0 if mode == "untrusted" else 1)
        assert len(children) == 1
        assert_settled(children)
    finally:
        release.set()
        client.close()
