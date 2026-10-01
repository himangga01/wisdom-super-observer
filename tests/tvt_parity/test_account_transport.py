"""NEW1: APK account bytes and bounded HTTPS behavior, with no network IO."""

import importlib
import json
import ssl
from concurrent.futures import ThreadPoolExecutor

import pytest


def modules():
    return (
        importlib.import_module("wso_core.tvt.account_protocol"),
        importlib.import_module("wso_core.tvt.account_transport"),
    )


ASCII_PASSWORD = (
    "eb416273135bc8c526de60f9ad329ee308ad3d6ab1ebb159c34b0488f137c66eeb"
    "62da7903974ba112258c4df122823466dff913e87f5b65285530bb6972322e"
)
ASCII_UUID = (
    "b1f0c3acc92912c57f7abb451c25c6b3fd60c20cdc1f94c2b2073189647006989"
    "bec36216b59607588508ca10a7d31f7930b17d35b22c73bc3bcacfb0e4b86cb"
)
BMP_PASSWORD = (
    "d4eed7619b8e37d5622180977f30d9088530fbda8b6bdec660679249b1c195a4dd"
    "320f0fd069ee4c454517d96b9eb635ee186bbf03743e1149222ec73a9e7dbf"
)
BMP_UUID = (
    "6e4c13c6b50b42483824c2828394062a3949b3dc84426700c765a37cf0c4c8a97"
    "f3eaea3f2bdcd7f293084706f4e910dda4aa841b1d068ceda1ed23862e6f3c3"
)


def builder(p, *, timestamp=1700000000, nonce=123456789):
    return p.AccountProtocol(
        task_ids=p.SessionTaskIds(), clock=lambda: timestamp, nonce=lambda: nonce
    )


def login(p, **changes):
    values = {
        "login_type": 1,
        "account": "alice@example.invalid",
        "password": "P@ssw0rd!",
        "uuid": "demo-uuid-0001",
        "language": "en",
        "app_version": "1.18.1",
        "country": "US",
    }
    values.update(changes)
    return p.LoginInput(**values)


def test_login_emits_exact_ascii_apk_proofs_and_native_types():
    p, _ = modules()
    request = builder(p).login(login(p))
    assert request.path == "/user/login"
    assert json.loads(request.body) == {
        "basic": {"ver": "1.1", "id": "1", "time": 1700000000, "nonce": 123456789},
        "data": {
            "type": 1,
            "userName": "alice@example.invalid",
            "password": ASCII_PASSWORD,
            "uuid": ASCII_UUID,
            "lang": "en",
            "appVersion": "1.18.1",
            "country": "US",
        },
    }
    assert "P@ssw0rd!" not in repr(request)
    assert "alice@example.invalid" not in repr(login(p))


def test_bmp_utf8_proofs_and_conditional_login_fields():
    p, _ = modules()
    request = builder(p, timestamp=1700000001, nonce=987654321).login(
        login(
            p,
            account="홍길동@example.invalid",
            password="비밀P@ss1",
            uuid="기기-0001",
            image_code="AB12",
            image_id="challenge-private",
            customer_app_id="customer",
            customer_mark="mark",
            terminal_id="terminal",
            double_check_code="otp",
        )
    )
    data = json.loads(request.body)["data"]
    assert data["password"] == BMP_PASSWORD
    assert data["uuid"] == BMP_UUID
    assert {
        key: data[key]
        for key in (
            "idCode",
            "imgCode",
            "customerAppId",
            "customerMark",
            "terminalId",
            "doubleCheckCode",
        )
    } == {
        "idCode": "challenge-private",
        "imgCode": "AB12",
        "customerAppId": "customer",
        "customerMark": "mark",
        "terminalId": "terminal",
        "doubleCheckCode": "otp",
    }
    data = json.loads(builder(p).login(login(p, image_id="stored")).body)["data"]
    assert "idCode" not in data and "imgCode" not in data


@pytest.mark.parametrize(
    "operation,version", [("profile", "1.0"), ("renew", "1.1"), ("logout", "1.0")]
)
def test_authenticated_requests_are_basic_only(operation, version):
    p, _ = modules()
    request = getattr(builder(p), operation)("account-private-token")
    assert (
        request.path
        == {
            "profile": "/user/info/get",
            "renew": "/user/token/renewal",
            "logout": "/user/logout",
        }[operation]
    )
    assert json.loads(request.body) == {
        "basic": {
            "ver": version,
            "id": "1",
            "token": "account-private-token",
            "time": 1700000000,
            "nonce": 123456789,
        }
    }
    assert "account-private-token" not in repr(request)


def test_challenge_known_shapes_and_business_routes():
    p, _ = modules()
    protocol = builder(p)
    image = protocol.image_challenge(customer_app_id="customer")
    assert image.path == "/user/img-code/get"
    assert json.loads(image.body)["data"] == {"customerAppId": "customer"}
    empty = protocol.image_challenge()
    assert "data" not in json.loads(empty.body)
    check = protocol.check_image("id-private", "AB12", customer_app_id="customer")
    assert check.path == "/user/img-code/check"
    assert json.loads(check.body)["data"] == {
        "idCode": "id-private",
        "imgCode": "AB12",
        "customerAppId": "customer",
    }
    for business in (1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 16):
        request = protocol.sms_challenge(
            p.SmsChallengeInput(
                login_name="alice@example.invalid",
                login_type=2,
                business_type=business,
                language="en",
                image_id="id-private",
                image_code="AB12",
                customer_app_id="customer",
                customer_mark="mark",
            ),
            token="token-private",
        )
        assert request.path == (
            "/user/sms-code/get" if business <= 5 else "/user/sms-code/no-token/get"
        )
        assert json.loads(request.body)["data"] == {
            "loginName": "alice@example.invalid",
            "loginType": 2,
            "businessType": business,
            "lang": "en",
            "idCode": "id-private",
            "imgCode": "AB12",
            "customerAppId": "customer",
            "customerMark": "mark",
        }
    with pytest.raises(p.AccountProtocolError):
        protocol.sms_challenge(p.SmsChallengeInput("alice", 1, 6, "en"))


@pytest.mark.parametrize(
    "changes",
    [
        {"account": "a\x00b"},
        {"password": "😀"},
        {"uuid": "\ud800"},
        {"login_type": True},
        {"login_type": 2**31},
        {"account": "x" * 4097},
    ],
)
def test_unsupported_jni_representations_and_native_bounds_are_rejected(changes):
    p, _ = modules()
    with pytest.raises(p.AccountProtocolError) as error:
        builder(p).login(login(p, **changes))
    assert str(error.value) == "Invalid account protocol input."
    assert "alice" not in repr(error.value)


@pytest.mark.parametrize(
    "timestamp,nonce",
    [
        (True, 123456789),
        (float("nan"), 123456789),
        (1700000000, 99999999),
        (1700000000, True),
    ],
)
def test_injected_clock_and_nonce_validate_native_integer_types(timestamp, nonce):
    p, _ = modules()
    with pytest.raises(p.AccountProtocolError):
        builder(p, timestamp=timestamp, nonce=nonce).profile("token-private")


def test_session_counter_is_decimal_unique_threadsafe_and_bounded():
    p, _ = modules()
    allocator = p.SessionTaskIds()
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: allocator.next_id(), range(128)))
    assert set(ids) == {str(number) for number in range(1, 129)}
    edge = p.SessionTaskIds(start=2147483647)
    assert edge.next_id() == "2147483647"
    with pytest.raises(p.AccountProtocolError):
        edge.next_id()
    assert 100000000 <= p.secure_nonce() <= 999999999


def test_login_response_preserves_token_roles_and_requires_success():
    p, _ = modules()
    reply = p.parse_response(
        200,
        b'{"basic":{"msgcode":200},"data":'
        b'{"token":"account-private","p2pId":"p2p-private","tid":"fallback"}}',
    )
    result = p.parse_login(reply)
    assert result.token == "account-private" and result.p2p_token == "p2p-private"
    assert "private" not in repr(result) and "private" not in repr(reply)
    fallback = p.parse_login(
        p.parse_response(
            201,
            b'{"basic":{"msgcode":200},"data":'
            b'{"token":"account-private","tid":"fallback"}}',
        )
    )
    assert fallback.p2p_token == "fallback"
    for status, body in [
        (503, b'{"basic":{"msgcode":200}}'),
        (200, b'{"basic":{"msgcode":900004}}'),
        (200, b'{"basic":{"msgcode":200},"data":{"token":""}}'),
    ]:
        reply = p.parse_response(status, body)
        assert reply.http_status == status
        with pytest.raises(p.AccountProtocolError):
            p.parse_login(reply)


@pytest.mark.parametrize(
    "body",
    [
        b'{"basic":{"msgcode":true}}',
        b'{"basic":{"msgcode":200,"msgcode":200}}',
        b'{"basic":{"msgcode":NaN}}',
        b'{"basic":{"msgcode":200},"data":Infinity}',
        b"[]",
        b"\xff",
        b"{",
        b'{"basic":{"msgcode":200.0}}',
        b'{"basic":{"msgcode":2147483648}}',
    ],
)
def test_response_parser_rejects_ambiguous_or_malformed_json(body):
    p, _ = modules()
    with pytest.raises(p.AccountProtocolError) as error:
        p.parse_response(200, body)
    assert str(error.value) == "Invalid account response."


def test_private_payload_remains_bounded_without_invented_normalization():
    p, _ = modules()
    raw = b'{"basic":{"msgcode":200},"data":{"unknownImage":"private"}}'
    reply = p.parse_response(200, raw, max_body_bytes=128)
    assert reply.private_body == raw
    reply.require_success()
    with pytest.raises(p.AccountProtocolError):
        p.parse_response(200, raw, max_body_bytes=8)
    failure = p.parse_response(401, b'{"basic":{"msgcode":900004}}')
    assert failure.http_status == 401 and failure.native_msgcode == 900004
    with pytest.raises(p.AccountProtocolError):
        failure.require_success()


class SocketPeer:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, timeout):
        self.timeouts.append(timeout)


class ResponsePeer:
    def __init__(self, status, body):
        self.status, self.body = status, body
        self.read_sizes = []

    def read1(self, size):
        self.read_sizes.append(size)
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


class ConnectionPeer:
    def __init__(self, response, *, failure=None):
        self.response, self.failure = response, failure
        self.sock = SocketPeer()
        self.calls = []
        self.closed = False

    def connect(self):
        if self.failure:
            raise self.failure

    def request(self, method, path, body=None, headers=None):
        self.calls.append((method, path, body, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def transport(
    t,
    monkeypatch,
    *,
    status=200,
    body=b'{"basic":{"msgcode":200}}',
    failure=None,
    max_body_bytes=256,
    clock=None,
):
    peer = ConnectionPeer(ResponsePeer(status, body), failure=failure)
    constructed = []

    def factory(host, port, *, timeout, context):
        constructed.append((host, port, timeout, context))
        return peer

    monkeypatch.setattr(t.http.client, "HTTPSConnection", factory)
    policy = t.OriginPolicy(
        {
            "synthetic": frozenset(
                {
                    "https://account.example.invalid",
                    "https://dc.example.invalid:8443/mobile_v1.0",
                }
            )
        }
    )
    client = t.HttpsAccountTransport(
        policy,
        region="synthetic",
        origin="https://account.example.invalid",
        timeout_seconds=5,
        max_body_bytes=max_body_bytes,
        **({"monotonic": clock} if clock else {}),
    )
    return client, peer, constructed, policy


def test_actual_stdlib_transport_serializes_post_header_tls_and_closes(monkeypatch):
    p, t = modules()
    client, peer, constructed, _ = transport(t, monkeypatch)
    request = builder(p).login(login(p))
    reply = client.send(request)
    assert reply.native_msgcode == 200
    assert peer.calls == [
        (
            "POST",
            "/user/login",
            request.body,
            {"Content-Type": "application/json;charset=UTF-8"},
        )
    ]
    assert json.loads(peer.calls[0][2])["data"]["password"] == ASCII_PASSWORD
    host, port, timeout, context = constructed[0]
    assert (host, port, timeout) == ("account.example.invalid", 443, 5)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert peer.closed and len(constructed) == 1


@pytest.mark.parametrize(
    "origin",
    [
        "http://account.example.invalid",
        "https://evil.invalid",
        "https://account.example.invalid:444",
        "https://user@account.example.invalid",
        "https://account.example.invalid?secret=private",
        "https://account.example.invalid/other",
        "https://account.example.invalid/#private",
    ],
)
def test_origin_denial_precedes_connection_creation(monkeypatch, origin):
    _, t = modules()
    calls = []
    monkeypatch.setattr(
        t.http.client, "HTTPSConnection", lambda *a, **kw: calls.append(a)
    )
    policy = t.OriginPolicy(
        {"synthetic": frozenset({"https://account.example.invalid"})}
    )
    with pytest.raises(t.AccountTransportError) as error:
        t.HttpsAccountTransport(policy, region="synthetic", origin=origin)
    assert str(error.value) == "Invalid account transport configuration."
    assert not calls
    with pytest.raises(t.AccountTransportError):
        t.HttpsAccountTransport(
            policy, region="unknown", origin="https://account.example.invalid"
        )


def test_response_limit_stops_read_and_transport_failure_never_retries(monkeypatch):
    p, t = modules()
    client, peer, made, _ = transport(
        t, monkeypatch, body=b"x" * 100, max_body_bytes=32
    )
    with pytest.raises(t.AccountTransportError) as error:
        client.send(builder(p).profile("token-private"))
    assert str(error.value) == "Account response exceeded its limit."
    assert peer.response.read_sizes == [33] and peer.closed and len(made) == 1
    client, peer, made, _ = transport(t, monkeypatch, failure=OSError("secret-private"))
    with pytest.raises(t.AccountTransportError) as error:
        client.send(builder(p).profile("token-private"))
    assert str(error.value) == "Account transport failed."
    assert "private" not in repr(error.value) and error.value.__suppress_context__
    assert peer.closed and len(made) == 1


@pytest.mark.parametrize("timeout", [0, -1, 61, True, float("inf"), float("nan")])
def test_timeout_configuration_is_finite_and_bounded(timeout):
    _, t = modules()
    policy = t.OriginPolicy(
        {"synthetic": frozenset({"https://account.example.invalid"})}
    )
    with pytest.raises(t.AccountTransportError):
        t.HttpsAccountTransport(
            policy,
            region="synthetic",
            origin="https://account.example.invalid",
            timeout_seconds=timeout,
        )


def test_total_deadline_interrupts_without_retry(monkeypatch):
    p, t = modules()
    ticks = iter([0, 0, 0, 6])
    client, peer, made, _ = transport(t, monkeypatch, clock=lambda: next(ticks))
    with pytest.raises(t.AccountTransportError) as error:
        client.send(builder(p).profile("token-private"))
    assert str(error.value) == "Account request deadline exceeded."
    assert peer.closed and len(made) == 1


def test_dc_candidate_is_allowlisted_pending_once_and_never_followed(monkeypatch):
    p, t = modules()
    raw = (
        b'{"basic":{"msgcode":404},"data":{"chain":"private-chain",'
        b'"domain":"dc.example.invalid","dcPort":8443,"httpPrefix":"https://"}}'
    )
    client, peer, made, policy = transport(t, monkeypatch, status=200, body=raw)
    reply = client.send(builder(p).profile("token-private"))
    pending = t.PendingDcRedirect()
    candidate = pending.offer(reply, policy, region="synthetic")
    assert candidate.origin == "https://dc.example.invalid:8443/mobile_v1.0"
    assert "private-chain" not in repr(candidate)
    assert len(made) == 1 and len(peer.calls) == 1
    assert client.origin == "https://account.example.invalid"
    with pytest.raises(t.AccountTransportError):
        pending.offer(reply, policy, region="synthetic")
    bad = p.parse_response(
        404,
        b'{"basic":{"msgcode":404},"data":'
        b'{"domain":"evil.invalid","httpPrefix":"https://"}}',
    )
    with pytest.raises(t.AccountTransportError):
        t.PendingDcRedirect().offer(bad, policy, region="synthetic")


def test_http_redirect_is_returned_without_following_and_fixed_path_enforced(
    monkeypatch,
):
    p, t = modules()
    client, peer, made, _ = transport(t, monkeypatch, status=302)
    reply = client.send(builder(p).profile("token-private"))
    assert reply.http_status == 302 and reply.native_msgcode == 200
    with pytest.raises(p.AccountProtocolError):
        reply.require_success()
    assert len(made) == 1 and len(peer.calls) == 1
    for path in (
        "/sdk/user/login",
        "/user/login?private",
        "https://evil.invalid/user/login",
    ):
        with pytest.raises(t.AccountTransportError):
            client.send(p.AccountRequest(path, b"{}"))
    assert len(made) == 1


def test_dc_zero_port_uses_native_fallback_and_configured_prefix(monkeypatch):
    p, t = modules()
    client, peer, made, policy = transport(t, monkeypatch)
    reply = p.parse_response(
        404,
        b'{"basic":{"msgcode":404},"data":'
        b'{"domain":"","dcIp":"","ip":"dc.example.invalid",'
        b'"dcPort":0,"port":8443,"httpPrefix":"https://"}}',
    )
    candidate = t.PendingDcRedirect().offer(reply, policy, region="synthetic")
    assert candidate.origin == "https://dc.example.invalid:8443/mobile_v1.0"
    redirected = t.HttpsAccountTransport(
        policy, region="synthetic", origin=candidate.origin
    )
    redirected.send(builder(p).logout("token-private"))
    assert made[0][:2] == ("dc.example.invalid", 8443)
    assert peer.calls[0][1] == "/mobile_v1.0/user/logout"
    assert client.origin == "https://account.example.invalid"


def test_oversized_integer_timeout_has_fixed_safe_configuration_error():
    _, t = modules()
    policy = t.OriginPolicy(
        {"synthetic": frozenset({"https://account.example.invalid"})}
    )
    with pytest.raises(t.AccountTransportError) as error:
        t.HttpsAccountTransport(
            policy,
            region="synthetic",
            origin="https://account.example.invalid",
            timeout_seconds=10**1000,
        )
    assert str(error.value) == "Invalid account transport configuration."


def test_response_rejects_float_overflow_and_nested_duplicate_keys():
    p, _ = modules()
    for body in (
        b'{"basic":{"msgcode":200},"data":{"x":1e9999}}',
        b'{"basic":{"msgcode":200},"data":{"x":1,"x":2}}',
    ):
        with pytest.raises(p.AccountProtocolError):
            p.parse_response(200, body)


def test_safe_errors_do_not_retain_secret_parser_or_network_exception_context(
    monkeypatch,
):
    p, t = modules()
    with pytest.raises(p.AccountProtocolError) as error:
        p.parse_response(200, b'{"token":"private-secret",')
    assert error.value.__context__ is None
    client, _, _, _ = transport(t, monkeypatch, failure=OSError("private-secret"))
    with pytest.raises(t.AccountTransportError) as error:
        client.send(builder(p).profile("private-secret"))
    assert error.value.__context__ is None
    with pytest.raises(t.AccountTransportError) as error:
        t.OriginPolicy(
            {"synthetic": frozenset({"https://account.example.invalid:private-secret"})}
        )
    assert error.value.__context__ is None
