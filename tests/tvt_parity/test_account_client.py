"""Private composition proofs; invented inputs, actual host TLS, no remote account."""

import importlib
import json
import threading
from uuid import UUID

import pytest
from wso_contracts.tvt.identity import AccountScope, TokenKind, TvtIdentityRef
from wso_core.tvt.account_protocol import (
    AccountProtocol,
    SessionTaskIds,
    parse_response,
)

TENANT = UUID(int=1)
ACTOR = UUID(int=2)
IDENTITY = UUID(int=3)
CORRELATION = "host-account-1"
PRIVATE = "invented-account-private"


def subject():
    assert importlib.util.find_spec("wso_core.tvt.account_client") is not None, (
        "Account composition must admit scoped requests and normalize private results"
    )
    return importlib.import_module("wso_core.tvt.account_client")


def scope(*, identity=False):
    return AccountScope(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        region="host-test",
        brand="demo",
        identity_id=IDENTITY if identity else None,
    )


def identity():
    return TvtIdentityRef(tenant_id=TENANT, actor_user_id=ACTOR, identity_id=IDENTITY)


def protocol():
    return AccountProtocol(
        task_ids=SessionTaskIds(), clock=lambda: 1700000000, nonce=lambda: 123456789
    )


def reply(data=None, *, status=200, code=200):
    value = {"basic": {"msgcode": code}, "data": data}
    return parse_response(status, json.dumps(value).encode())


class Boundary:
    """Only the slow process exchange is replaced; serializers/parsers remain real."""

    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def send(self, request):
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def close(self):
        self.closed = True


def build(monkeypatch, response, *, linked=False):
    c = subject()
    boundary = Boundary(response)
    launches = []

    def create(policy, **kwargs):
        launches.append(kwargs)
        return boundary

    monkeypatch.setattr(c, "ProcessAccountTransport", create)
    client = c.AccountClient(
        scope(),
        c.OriginPolicy({"host-test": frozenset({"https://localhost:1"})}),
        origin="https://localhost:1",
        identity=identity() if linked else None,
        protocol=protocol(),
    )
    return c, client, boundary, launches


def credentials(c):
    return c.LoginInput(
        1, "alice@example.invalid", "P@ssw0rd!", "demo-uuid-0001", "en", "1.18.1", "US"
    )


def token(c, *, kind=TokenKind.USER, ref=None):
    return c.PrivateToken(ref or identity(), kind, PRIVATE)


def test_prelogin_scope_without_identity_or_store_sends_exact_login(monkeypatch):
    c, client, boundary, launches = build(
        monkeypatch, reply({"token": PRIVATE, "p2pId": "invented-p2p"})
    )
    result = client.login(
        scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
    )
    assert result.ok and result.native_msgcode == 200 and result.http_status == 200
    assert result.correlation_id == CORRELATION
    assert result.value.account_token == PRIVATE
    assert result.value.p2p_token == "invented-p2p"
    assert result.value.account_token != result.value.p2p_token
    assert boundary.closed and len(boundary.requests) == 1
    request = boundary.requests[0]
    assert request.path == "/user/login"
    assert json.loads(request.body) == {
        "basic": {"ver": "1.1", "id": "1", "time": 1700000000, "nonce": 123456789},
        "data": {
            "type": 1,
            "userName": "alice@example.invalid",
            "lang": "en",
            "appVersion": "1.18.1",
            "country": "US",
            "password": "eb416273135bc8c526de60f9ad329ee308ad3d6ab1ebb159c34b0488f137c66eeb62da7903974ba112258c4df122823466dff913e87f5b65285530bb6972322e",
            "uuid": "b1f0c3acc92912c57f7abb451c25c6b3fd60c20cdc1f94c2b2073189647006989bec36216b59607588508ca10a7d31f7930b17d35b22c73bc3bcacfb0e4b86cb",
        },
    }
    assert 0 < launches[0]["timeout_seconds"] <= 3
    assert launches[0]["region"] == "host-test"
    assert not any(secret in repr(result) for secret in (PRIVATE, "invented-p2p"))


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": UUID(int=8)},
        {"actor_user_id": UUID(int=8)},
        {"region": "other"},
        {"brand": "other"},
        {"identity_id": IDENTITY},
        {"tenant_id": "malformed"},
        {"scope_kind": "STORE"},
        {"region": "bad value"},
    ],
)
def test_scope_mismatch_and_construct_bypass_rejected_before_exchange(
    monkeypatch, changes, recwarn
):
    c, client, boundary, launches = build(monkeypatch, reply({"token": PRIVATE}))
    invalid = scope().model_copy(update=changes)
    with pytest.raises(c.AccountClientError) as error:
        client.login(
            invalid, credentials(c), deadline_ms=3000, correlation_id=CORRELATION
        )
    assert error.value.code == "ACCOUNT_SCOPE_INVALID"
    assert error.value.correlation_id == CORRELATION
    assert error.value.__context__ is None
    assert not boundary.requests and not launches
    assert not recwarn.list


@pytest.mark.parametrize("deadline", [0, -1, True, 1.5, 60001, "3000"])
def test_invalid_deadline_does_not_create_process(monkeypatch, deadline):
    c, client, boundary, launches = build(monkeypatch, reply({"token": PRIVATE}))
    with pytest.raises(c.AccountClientError) as error:
        client.login(
            scope(), credentials(c), deadline_ms=deadline, correlation_id=CORRELATION
        )
    assert error.value.code == "ACCOUNT_INPUT_INVALID"
    assert not launches and not boundary.requests


@pytest.mark.parametrize("correlation", [None, "", "line\nsecret", "a" * 129, 12])
def test_invalid_correlation_not_reflected_in_error(monkeypatch, correlation):
    c, client, boundary, launches = build(monkeypatch, reply({"token": PRIVATE}))
    with pytest.raises(c.AccountClientError) as error:
        client.login(
            scope(), credentials(c), deadline_ms=3000, correlation_id=correlation
        )
    assert error.value.correlation_id is None
    assert error.value.__context__ is None
    assert not launches and not boundary.requests


@pytest.mark.parametrize(
    "operation,path,version",
    [
        ("profile", "/user/info/get", "1.0"),
        ("renew", "/user/token/renewal", "1.1"),
        ("logout", "/user/logout", "1.0"),
    ],
)
def test_authenticated_methods_use_identity_bound_user_token(
    monkeypatch, operation, path, version
):
    c, client, boundary, _ = build(
        monkeypatch,
        reply(
            {"userId": "source-id", "token": "invented-renewed", "tid": "invented-p2p"}
        ),
        linked=True,
    )
    result = getattr(client, operation)(
        identity(), token(c), deadline_ms=3000, correlation_id=CORRELATION
    )
    assert result.ok
    assert boundary.requests[0].path == path
    assert json.loads(boundary.requests[0].body) == {
        "basic": {
            "ver": version,
            "id": "1",
            "time": 1700000000,
            "nonce": 123456789,
            "token": PRIVATE,
        }
    }
    if operation == "profile":
        assert result.value.user_id == "source-id"
    if operation == "renew":
        assert result.value.account_token == "invented-renewed"
        assert result.value.p2p_token == "invented-p2p"
    if operation == "logout":
        assert result.value is None
    assert PRIVATE not in repr(token(c))


@pytest.mark.parametrize("kind", [TokenKind.P2P, TokenKind.DEVICE, "USER"])
def test_wrong_token_kind_cannot_be_used_as_account_token(monkeypatch, kind):
    c, client, boundary, launches = build(monkeypatch, reply({}), linked=True)
    with pytest.raises(c.AccountClientError) as error:
        client.profile(
            identity(),
            token(c, kind=kind),
            deadline_ms=3000,
            correlation_id=CORRELATION,
        )
    assert error.value.code == "ACCOUNT_SCOPE_INVALID"
    assert not launches and not boundary.requests


def test_postlogin_scope_and_token_identity_must_match_bound_connection(monkeypatch):
    c, client, boundary, launches = build(monkeypatch, reply({}), linked=True)
    wrong = identity().model_copy(update={"identity_id": UUID(int=99)})
    for ref, supplied in [
        (wrong, token(c)),
        (identity(), token(c, ref=wrong)),
        (scope(), token(c)),
    ]:
        with pytest.raises(c.AccountClientError):
            client.profile(ref, supplied, deadline_ms=3000, correlation_id=CORRELATION)
    assert not launches and not boundary.requests


def test_prelogin_connection_cannot_mint_postlogin_identity(monkeypatch):
    c, client, boundary, launches = build(monkeypatch, reply({}))
    with pytest.raises(c.AccountClientError):
        client.profile(
            identity(), token(c), deadline_ms=3000, correlation_id=CORRELATION
        )
    assert not launches and not boundary.requests


@pytest.mark.parametrize("status,code", [(200, 900004), (401, 200), (503, -17)])
def test_error_status_does_not_parse_or_return_tokens(monkeypatch, status, code):
    c, client, _, _ = build(
        monkeypatch, reply({"token": PRIVATE}, status=status, code=code)
    )
    result = client.login(
        scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
    )
    assert not result.ok and result.value is None and result.dc is None
    assert result.http_status == status and result.native_msgcode == code
    assert result.error_code == "ACCOUNT_UPSTREAM_REJECTED"
    assert PRIVATE not in repr(result)


def test_dc_candidate_is_allowlisted_and_never_retried(monkeypatch):
    c, client, boundary, _ = build(
        monkeypatch,
        reply(
            {
                "domain": "localhost",
                "port": 1,
                "httpPrefix": "https://",
                "chain": PRIVATE,
            },
            code=404,
        ),
    )
    # Both bootstrap and source-derived DC prefix must be trusted explicitly.
    client = c.AccountClient(
        scope(),
        c.OriginPolicy(
            {
                "host-test": frozenset(
                    {
                        "https://localhost:1",
                        "https://localhost:1/mobile_v1.0",
                    }
                )
            }
        ),
        origin="https://localhost:1",
        protocol=protocol(),
    )
    result = client.login(
        scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
    )
    assert not result.ok and result.native_msgcode == 404 and result.value is None
    assert result.dc.origin == "https://localhost:1/mobile_v1.0"
    assert result.error_code == "ACCOUNT_DC_PENDING"
    assert len(boundary.requests) == 1
    assert PRIVATE not in repr(result)


def test_unapproved_dc_preserves_business_status_without_exchange_retry(monkeypatch):
    c, client, boundary, _ = build(
        monkeypatch,
        reply(
            {
                "domain": "unapproved.invalid",
                "httpPrefix": "https://",
                "chain": PRIVATE,
            },
            code=404,
        ),
    )
    result = client.login(
        scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
    )
    assert not result.ok and result.native_msgcode == 404 and result.http_status == 200
    assert result.dc is None and result.value is None
    assert result.error_code == "ACCOUNT_UPSTREAM_REJECTED"
    assert len(boundary.requests) == 1


@pytest.mark.parametrize(
    "data", [None, {}, {"token": 12}, {"token": PRIVATE, "p2pId": []}]
)
def test_malformed_login_success_becomes_sanitized_failure(monkeypatch, data):
    c, client, _, _ = build(monkeypatch, reply(data))
    with pytest.raises(c.AccountClientError) as error:
        client.login(
            scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
        )
    assert error.value.code == "ACCOUNT_PROTOCOL_INVALID"
    assert error.value.http_status == 200 and error.value.native_msgcode == 200
    assert PRIVATE not in str(error.value) and PRIVATE not in repr(error.value)
    assert error.value.__context__ is None and error.value.__cause__ is None


def test_challenge_sends_confirmed_paths_and_keeps_payload_private(monkeypatch):
    c, client, boundary, _ = build(
        monkeypatch, reply({"idCode": PRIVATE, "imgCodeImgData": "opaque-image"})
    )
    image = client.challenge(
        scope(), c.ImageChallenge(), deadline_ms=3000, correlation_id=CORRELATION
    )
    assert image.ok and image.value.image_id == PRIVATE
    assert image.value.private_image_data == "opaque-image"
    assert PRIVATE not in repr(image) and "opaque-image" not in repr(image)
    sms = c.SmsChallengeInput("alice@example.invalid", 1, 11, "en", PRIVATE, "1234")
    result = client.challenge(
        scope(), sms, deadline_ms=3000, correlation_id=CORRELATION
    )
    assert result.ok
    assert [request.path for request in boundary.requests] == [
        "/user/img-code/get",
        "/user/sms-code/no-token/get",
    ]
    assert json.loads(boundary.requests[1].body)["data"] == {
        "loginName": "alice@example.invalid",
        "loginType": 1,
        "businessType": 11,
        "lang": "en",
        "idCode": PRIVATE,
        "imgCode": "1234",
    }


@pytest.mark.parametrize(
    "message,code,permanent",
    [
        ("Account process request cancelled.", "ACCOUNT_CANCELLED", False),
        ("Account process admission is closed or busy.", "ACCOUNT_UNAVAILABLE", False),
        (
            "Account process settlement could not be proved.",
            "ACCOUNT_QUARANTINED",
            True,
        ),
        ("Account process deadline exceeded.", "ACCOUNT_DEADLINE_EXCEEDED", False),
        (PRIVATE, "ACCOUNT_TRANSPORT_FAILED", False),
    ],
)
def test_process_failures_are_fixed_safe_and_quarantine_is_permanent(
    monkeypatch, message, code, permanent
):
    from wso_core.tvt.account_process import AccountProcessError

    c, client, _, launches = build(monkeypatch, AccountProcessError(message))
    with pytest.raises(c.AccountClientError) as error:
        client.login(
            scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
        )
    assert error.value.code == code and error.value.correlation_id == CORRELATION
    assert PRIVATE not in str(error.value) and PRIVATE not in repr(error.value)
    assert error.value.__context__ is None and error.value.__cause__ is None
    if permanent:
        with pytest.raises(c.AccountClientError) as quarantined:
            client.login(
                scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
            )
        assert quarantined.value.code == "ACCOUNT_QUARANTINED" and len(launches) == 1


def test_close_cancels_active_boundary_and_suppresses_late_success(monkeypatch):
    c, client, boundary, launches = build(monkeypatch, reply({"token": PRIVATE}))
    reached, release = threading.Event(), threading.Event()
    results = []

    def blocked(request):
        reached.set()
        assert release.wait(3)
        return boundary.response

    boundary.send = blocked

    def invoke():
        try:
            client.login(
                scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
            )
        except c.AccountClientError as error:
            results.append(error.code)

    thread = threading.Thread(target=invoke)
    thread.start()
    assert reached.wait(2)
    with pytest.raises(c.AccountClientError) as busy:
        client.login(
            scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
        )
    assert busy.value.code == "ACCOUNT_UNAVAILABLE" and len(launches) == 1
    client.close()
    assert boundary.closed
    release.set()
    thread.join(3)
    assert not thread.is_alive() and results == ["ACCOUNT_CANCELLED"]
    with pytest.raises(c.AccountClientError) as closed:
        client.login(
            scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
        )
    assert closed.value.code == "ACCOUNT_UNAVAILABLE"


def test_actual_loopback_tls_login_profile_renew_logout(monkeypatch, tmp_path):
    # Reuse host trust/server machinery, not any production containment replacement.
    import wso_core.tvt.account_process as process
    from test_account_process import (
        assert_settled,
        child_processes,
        tls_peer,
        trust_host_peer,
    )

    c = subject()
    fixture = tls_peer.__wrapped__(tmp_path)
    process_fixture = child_processes.__wrapped__(monkeypatch)
    children, launches = next(process_fixture)
    origin, certificate, received, _, _ = next(fixture)
    trust_host_peer(monkeypatch, process, certificate)
    client = c.AccountClient(
        scope(),
        c.OriginPolicy({"host-test": frozenset({origin})}),
        origin=origin,
        identity=identity(),
        protocol=protocol(),
    )
    try:
        login = client.login(
            scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
        )
        assert login.ok and login.value.account_token == "host-private-token"
        credential = c.PrivateToken(
            identity(), TokenKind.USER, login.value.account_token
        )
        profile = client.profile(
            identity(), credential, deadline_ms=3000, correlation_id=CORRELATION
        )
        renew = client.renew(
            identity(), credential, deadline_ms=3000, correlation_id=CORRELATION
        )
        logout = client.logout(
            identity(), credential, deadline_ms=3000, correlation_id=CORRELATION
        )
        assert profile.ok and renew.ok and logout.ok
        assert (
            renew.value.account_token == "host-private-token" and logout.value is None
        )
        assert [path for path, _, _ in received] == [
            "/user/login",
            "/user/info/get",
            "/user/token/renewal",
            "/user/logout",
        ]
        assert all(
            content == "application/json;charset=UTF-8" for _, content, _ in received
        )
        assert [json.loads(body)["basic"]["id"] for _, _, body in received] == [
            "1",
            "2",
            "3",
            "4",
        ]
        assert [json.loads(body)["basic"]["ver"] for _, _, body in received] == [
            "1.1",
            "1.0",
            "1.1",
            "1.0",
        ]
        assert all(
            json.loads(body)
            == {
                "basic": {
                    "ver": version,
                    "id": str(index),
                    "time": 1700000000,
                    "nonce": 123456789,
                    "token": "host-private-token",
                }
            }
            for index, ((_, _, body), version) in enumerate(
                zip(received[1:], ["1.0", "1.1", "1.0"], strict=True), 2
            )
        )
        assert "host-private-token" not in repr(
            (login, credential, profile, renew, logout)
        )
        assert len(children) == 4
        assert_settled(children)
        assert all("host-private-token" not in repr(args) for args, _ in launches)
        assert not [
            t for t in threading.enumerate() if t.name.startswith("account-process-")
        ]
    finally:
        client.close()
        with pytest.raises(StopIteration):
            next(fixture)
        with pytest.raises(StopIteration):
            next(process_fixture)


def test_quarantine_retains_boundary_resource_ownership(monkeypatch):
    import gc
    import weakref

    from wso_core.tvt.account_process import AccountProcessError

    c = subject()
    owned = []

    def create(*args, **kwargs):
        boundary = Boundary(
            AccountProcessError("Account process settlement could not be proved.")
        )
        owned.append(weakref.ref(boundary))
        return boundary

    monkeypatch.setattr(c, "ProcessAccountTransport", create)
    client = c.AccountClient(
        scope(),
        c.OriginPolicy({"host-test": frozenset({"https://localhost:1"})}),
        origin="https://localhost:1",
        protocol=protocol(),
    )
    with pytest.raises(c.AccountClientError):
        client.login(
            scope(), credentials(c), deadline_ms=3000, correlation_id=CORRELATION
        )
    # The factory holds only a weak reference. The client must retain ownership
    # of the boundary containing any unsettled process/channels.
    gc.collect()
    assert owned[0]() is not None


@pytest.mark.parametrize("late_exchange", [False, True])
def test_total_deadline_includes_serializer_and_result_handling(
    monkeypatch, late_exchange
):
    c, client, boundary, launches = build(monkeypatch, reply({"token": PRIVATE}))
    now = [100.0]
    monkeypatch.setattr(c.time, "monotonic", lambda: now[0])
    if late_exchange:
        original = boundary.send

        def send(request):
            now[0] += 0.2
            return original(request)

        boundary.send = send
    else:

        def clock():
            now[0] += 0.2
            return 1700000000

        client._protocol = AccountProtocol(
            task_ids=SessionTaskIds(), clock=clock, nonce=lambda: 123456789
        )
    with pytest.raises(c.AccountClientError) as error:
        client.login(
            scope(), credentials(c), deadline_ms=100, correlation_id=CORRELATION
        )
    assert error.value.code == "ACCOUNT_DEADLINE_EXCEEDED"
    assert len(launches) == int(late_exchange)


def test_image_check_is_explicit_native_path_and_sms_type_selects_other_path(
    monkeypatch,
):
    c, client, boundary, _ = build(monkeypatch, reply({}))
    result = client.challenge(
        scope(),
        c.ImageCheck(PRIVATE, "1234", "demo-app"),
        deadline_ms=3000,
        correlation_id=CORRELATION,
    )
    assert result.ok and result.value.private_image_data is None
    client.challenge(
        scope(),
        c.SmsChallengeInput("alice@example.invalid", 1, 1, "en"),
        deadline_ms=3000,
        correlation_id=CORRELATION,
    )
    assert [request.path for request in boundary.requests] == [
        "/user/img-code/check",
        "/user/sms-code/get",
    ]
    assert json.loads(boundary.requests[0].body)["data"] == {
        "idCode": PRIVATE,
        "imgCode": "1234",
        "customerAppId": "demo-app",
    }


@pytest.mark.parametrize("data", [None, {}, {"tid": PRIVATE}, {"token": ""}])
def test_renewal_without_account_replacement_does_not_infer_p2p_or_expiry(
    monkeypatch, data
):
    c, client, _, _ = build(monkeypatch, reply(data), linked=True)
    result = client.renew(
        identity(), token(c), deadline_ms=3000, correlation_id=CORRELATION
    )
    assert (
        result.ok
        and result.value.account_token is None
        and result.value.p2p_token is None
    )
    assert result.value.private_body
    assert PRIVATE not in repr(result.value)


@pytest.mark.parametrize("private_input", [None, "unsafe", 12])
def test_invalid_private_input_has_no_context_or_exchange(monkeypatch, private_input):
    c, client, boundary, launches = build(monkeypatch, reply({"token": PRIVATE}))
    for method in [client.login, client.challenge]:
        with pytest.raises(c.AccountClientError) as error:
            method(scope(), private_input, deadline_ms=3000, correlation_id=CORRELATION)
        assert error.value.code == "ACCOUNT_PROTOCOL_INVALID"
        assert error.value.__context__ is None
    assert not launches and not boundary.requests


def test_trusted_configuration_rejects_unapproved_origin_and_identity(monkeypatch):
    c = subject()
    policy = c.OriginPolicy({"host-test": frozenset({"https://localhost:1"})})
    for arguments in [
        {"origin": "https://unapproved.invalid"},
        {
            "origin": "https://localhost:1",
            "identity": identity().model_copy(update={"actor_user_id": UUID(int=99)}),
        },
        {"origin": "https://localhost:1", "identity": scope()},
    ]:
        with pytest.raises(c.AccountClientError) as error:
            c.AccountClient(scope(), policy, **arguments)
        assert error.value.__context__ is None
