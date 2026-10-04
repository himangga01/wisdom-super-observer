"""Private invented replies: capture is structural evidence, never authority."""

import base64
import importlib
import json
from dataclasses import replace
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from test_account_client import build, credentials, identity, scope
from wso_contracts.tvt.identity import TokenKind
from wso_core.tvt.account_client import _login, _renew
from wso_core.tvt.account_protocol import AccountProtocolError, AccountResponse
from wso_core.tvt.ports import (
    AccountErrorCode,
    AccountRenewal,
    AccountResult,
    AccountTokens,
    PrivateToken,
)
from wso_core.tvt.security_crypto import SecurityKeyState

USER = "invented-capture-user"
RAW = " new P@ssword9! "
MD5 = b"e793da4d0caaec1246527ba4b1cb35d4"


def subject():
    assert importlib.util.find_spec("wso_core.tvt.sid_capture") is not None, (
        "Private SID capture missing"
    )
    return importlib.import_module("wso_core.tvt.sid_capture")


def user(value=USER, ref=None, kind=TokenKind.USER):
    return PrivateToken(ref or identity(), kind, value)


def sid(plain=b"fedcba9876543210"):
    cipher = Cipher(algorithms.AES(MD5), modes.ECB()).encryptor()
    return base64.b64encode(cipher.update(plain) + cipher.finalize()).decode()


def body(data=None, code=200):
    return json.dumps({"basic": {"msgcode": code}, "data": data}).encode()


def result(data=None, *, code=200, status=200, error=None, raw=None):
    data = (
        data
        if data is not None
        else {
            "token": USER,
            "p2pId": "invented-p2p",
            "sid": sid(),
            "tokenId": "capture-id",
        }
    )
    return AccountResult(
        status,
        code,
        "sid-test",
        AccountTokens(USER, "invented-p2p", raw or body(data)),
        error_code=error,
    )


def capture():
    return subject().capture_login(scope(), result())


def test_login_decoder_retains_original_private_body_without_changing_tokens():
    raw = body(
        {"token": USER, "tid": "invented-p2p", "sid": sid(), "tokenId": "capture-id"}
    )
    value = _login(AccountResponse(200, 200, raw))
    assert getattr(value, "private_body", None) == raw
    assert value.account_token == USER and value.p2p_token == "invented-p2p"
    assert USER not in repr(value) and sid() not in repr(value)


def test_old_token_constructors_remain_sid_free():
    assert getattr(AccountTokens(USER, ""), "private_body", None) == b""
    assert AccountRenewal().private_body == b""


def test_successful_unbound_capture_can_bind_actual_generation_and_admit_existing_state():
    captured = capture()
    binding = captured.binding(scope(), identity(), 7, user())
    config = captured.password_temporary_config(binding, user(), RAW)
    assert config.temporary_key(binding) == MD5
    state = SecurityKeyState(binding, user(), config)
    with pytest.raises(AccountProtocolError):
        state.encrypt(binding, user(), "changed9!")
    state = SecurityKeyState(binding, user(), config)
    captured.admit(state, binding, user())
    encrypted = state.encrypt(binding, user(), RAW)
    decryptor = Cipher(algorithms.AES(b"fedcba9876543210"), modes.ECB()).decryptor()
    assert decryptor.update(base64.b64decode(encrypted)) + decryptor.finalize() == MD5
    for private in [USER, sid(), "capture-id", RAW, MD5.decode()]:
        assert private not in repr(captured) + repr(binding) + repr(config) + str(
            captured
        )
    assert not hasattr(captured, "ok") and not hasattr(captured, "generation")


@pytest.mark.parametrize(
    "data",
    [
        {"token": USER, "p2pId": "invented-p2p"},
        {"token": USER, "p2pId": "invented-p2p", "sid": ""},
        {"token": USER, "p2pId": "invented-p2p", "sid": sid()},
        {"token": USER, "p2pId": "invented-p2p", "sid": sid(), "tokenId": ""},
    ],
)
def test_valid_sid_free_login_returns_unavailable_capture(data):
    assert subject().capture_login(scope(), result(data)) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"status": 401},
        {"code": 7000},
        {"error": AccountErrorCode.UPSTREAM_REJECTED},
        {"raw": body({"token": USER}, code=7000)},
    ],
)
def test_failed_or_spoofed_success_never_captures(changes):
    with pytest.raises(AccountProtocolError) as caught:
        subject().capture_login(scope(), result(**changes))
    assert caught.value.__context__ is None
    assert USER not in str(caught.value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("sid", None),
        ("sid", 1),
        ("sid", True),
        ("sid", []),
        ("tokenId", {}),
        ("tokenId", None),
        ("sid", "\x00"),
        ("sid", "\ud800"),
        ("tokenId", "x" * 4097),
        ("sid", "x" * 4097),
    ],
)
def test_nonstring_or_overbound_key_fields_rejected(key, value):
    data = {
        "token": USER,
        "p2pId": "invented-p2p",
        "sid": sid(),
        "tokenId": "capture-id",
    }
    data[key] = value
    with pytest.raises(AccountProtocolError):
        subject().capture_login(scope(), result(data))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"basic":{"msgcode":200},"data":{"token":"x","sid":"a","sid":"b"}}',
        b'{"basic":{"msgcode":200},"data":{"sid":NaN}}',
        b'{"basic":{"msgcode":200},"data":{"sid":1e999}}',
        b'{"basic":{"msgcode":200}} {}',
        b" " * 1048577,
        b'{"basic":{"msgcode":200},"data":' + b"[" * 1100 + b"]" * 1100 + b"}",
        body('{"sid":"a","tokenId":"capture-id"}'),
        body('{"sid":"a"},"other":1'),
    ],
    ids=[
        "duplicate",
        "nan",
        "overflow",
        "trailing",
        "body-bound",
        "depth",
        "text-object",
        "text-injection",
    ],
)
def test_malformed_duplicate_nonfinite_depth_or_json_text_data_is_not_sid_evidence(raw):
    with pytest.raises(AccountProtocolError) as caught:
        subject().capture_login(scope(), result(raw=raw))
    assert caught.value.__context__ is None


def test_projection_foreign_token_or_p2p_cannot_replace_original_association():
    s = subject()
    for value in [
        replace(result().value, account_token="foreign"),
        replace(result().value, p2p_token="foreign"),
    ]:
        with pytest.raises(AccountProtocolError):
            s.capture_login(scope(), replace(result(), value=value))
    captured = capture()
    for token in [
        user("foreign"),
        user(kind=TokenKind.P2P),
        user(ref=identity().model_copy(update={"identity_id": UUID(int=9)})),
    ]:
        with pytest.raises(AccountProtocolError):
            captured.binding(scope(), identity(), 7, token)


def test_scope_and_known_identity_are_snapshots_and_never_userid_guesses():
    s = subject()
    original = scope(identity=True)
    known = identity()
    captured = s.capture_login(original, result(), known_identity=known)
    original.region = "foreign"
    known.identity_id = UUID(int=9)
    assert captured.binding(scope(identity=True), identity(), 7, user()).generation == 7
    with pytest.raises(AccountProtocolError):
        captured.binding(original, identity(), 7, user())
    with pytest.raises(AccountProtocolError):
        captured.binding(scope(identity=True), known, 7, user(ref=known))


@pytest.mark.parametrize(
    "changes",
    [
        {"region": "foreign"},
        {"brand": "foreign"},
        {"actor_user_id": UUID(int=9)},
        {"tenant_id": UUID(int=9)},
    ],
)
def test_binding_rejects_foreign_scope(changes):
    with pytest.raises(AccountProtocolError):
        capture().binding(scope().model_copy(update=changes), identity(), 7, user())


@pytest.mark.parametrize("generation", [0, True, 2**63, "7"])
def test_binding_requires_actual_positive_integer_generation(generation):
    with pytest.raises(AccountProtocolError):
        capture().binding(scope(), identity(), generation, user())


def test_password_temporary_input_is_exact_raw_utf8_and_config_is_binding_scoped():
    captured = capture()
    binding = captured.binding(scope(), identity(), 7, user())
    config = captured.password_temporary_config(binding, user(), RAW)
    binding.scope.region = "foreign"
    correct = captured.binding(scope(), identity(), 7, user())
    assert config.temporary_key(correct) == MD5
    with pytest.raises(AccountProtocolError):
        config.temporary_key(binding)
    with pytest.raises(AccountProtocolError):
        config.temporary_key(replace(correct, generation=8))
    for invalid in [None, "", "\x00", "\ud800", "x" * 4097]:
        with pytest.raises(AccountProtocolError):
            captured.password_temporary_config(correct, user(), invalid)


def test_renewal_without_replacement_keeps_only_explicit_current_user_association():
    raw = body({"sid": sid(), "tokenId": "capture-id"})
    renewal = AccountResult(
        200, 200, "sid-test", _renew(AccountResponse(200, 200, raw))
    )
    assert renewal.value.account_token is None
    captured = subject().capture_renewal(scope(identity=True), user(), renewal)
    assert captured.binding(scope(identity=True), identity(), 8, user()).generation == 8
    with pytest.raises(AccountProtocolError):
        captured.binding(scope(identity=True), identity(), 8, user("foreign"))


def test_renewal_replacement_binds_new_token_and_does_not_reuse_old_generation_metadata():
    raw = body({"token": "replacement", "sid": sid(), "tokenId": "replacement-id"})
    renewal = AccountResult(
        200, 200, "sid-test", _renew(AccountResponse(200, 200, raw))
    )
    captured = subject().capture_renewal(scope(identity=True), user(), renewal)
    binding = captured.binding(scope(identity=True), identity(), 8, user("replacement"))
    assert binding.token_id == "replacement-id"
    with pytest.raises(AccountProtocolError):
        captured.binding(scope(identity=True), identity(), 8, user())
    with pytest.raises(AccountProtocolError):
        captured.admit(
            SecurityKeyState(
                binding,
                user("replacement"),
                captured.password_temporary_config(binding, user("replacement"), RAW),
            ),
            replace(binding, generation=7),
            user("replacement"),
        )


def test_sid_shape_capture_is_not_cryptographic_admission_and_failure_closes_state():
    captured = subject().capture_login(
        scope(),
        result(
            {
                "token": USER,
                "p2pId": "invented-p2p",
                "sid": "bad=",
                "tokenId": "capture-id",
            }
        ),
    )
    binding = captured.binding(scope(), identity(), 7, user())
    state = SecurityKeyState(
        binding, user(), captured.password_temporary_config(binding, user(), RAW)
    )
    with pytest.raises(AccountProtocolError):
        captured.admit(state, binding, user())
    with pytest.raises(AccountProtocolError):
        state.encrypt(binding, user(), RAW)


def test_affected_login_client_preserves_success_body_and_rejected_result(monkeypatch):
    raw = body({"token": USER, "sid": sid(), "tokenId": "capture-id"})
    c, client, _, _ = build(monkeypatch, AccountResponse(200, 200, raw))
    got = client.login(
        scope(), credentials(c), deadline_ms=3000, correlation_id="sid-test"
    )
    assert got.value.private_body == raw
    assert subject().capture_login(scope(), got) is not None
    c, client, _, _ = build(monkeypatch, AccountResponse(401, 200, raw))
    got = client.login(
        scope(), credentials(c), deadline_ms=3000, correlation_id="sid-test"
    )
    assert not got.ok and got.value is None


def test_body_limit_is_inherited_and_original_bytes_are_not_normalized():
    raw = body(
        {"token": USER, "p2pId": "invented-p2p", "sid": sid(), "tokenId": "capture-id"}
    )
    raw += b" " * (1048576 - len(raw))
    captured = subject().capture_login(scope(), result(raw=raw))
    binding = captured.binding(scope(), identity(), 1, user())
    state = SecurityKeyState(
        binding, user(), captured.password_temporary_config(binding, user(), RAW)
    )
    captured.admit(state, binding, user())
    assert len(state.encrypt(binding, user(), RAW)) == 44


@pytest.mark.parametrize("data", [None, {}, {"p2pId": "ignored"}, {"token": ""}])
def test_successful_renewal_without_sid_has_no_capture(data):
    raw = body(data)
    renewal = AccountResult(
        200, 200, "sid-test", _renew(AccountResponse(200, 200, raw))
    )
    assert subject().capture_renewal(scope(identity=True), user(), renewal) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"http_status": 401},
        {"native_msgcode": 7000},
        {"error_code": AccountErrorCode.UPSTREAM_REJECTED},
    ],
)
def test_failed_renewal_is_not_key_evidence(changes):
    raw = body({"sid": sid(), "tokenId": "capture-id"})
    renewal = AccountResult(
        200, 200, "sid-test", _renew(AccountResponse(200, 200, raw))
    )
    with pytest.raises(AccountProtocolError):
        subject().capture_renewal(
            scope(identity=True), user(), replace(renewal, **changes)
        )


def test_renewal_projection_cannot_invent_replacement_or_accept_non_user():
    raw = body({"sid": sid(), "tokenId": "capture-id"})
    renewal = AccountResult(
        200, 200, "sid-test", AccountRenewal("foreign", private_body=raw)
    )
    with pytest.raises(AccountProtocolError):
        subject().capture_renewal(scope(identity=True), user(), renewal)
    renewal = replace(renewal, value=AccountRenewal(private_body=raw))
    with pytest.raises(AccountProtocolError):
        subject().capture_renewal(
            scope(identity=True), user(kind=TokenKind.P2P), renewal
        )


def test_scope_construct_bypass_and_foreign_known_identity_are_rejected():
    invalid = scope().model_copy(update={"region": "bad region"})
    with pytest.raises(AccountProtocolError) as caught:
        subject().capture_login(invalid, result())
    assert caught.value.__context__ is None
    with pytest.raises(AccountProtocolError):
        subject().capture_login(
            scope(identity=True),
            result(),
            known_identity=identity().model_copy(update={"identity_id": UUID(int=9)}),
        )


def test_capture_failure_closes_even_an_already_admitted_state():
    captured = capture()
    binding = captured.binding(scope(), identity(), 7, user())
    state = SecurityKeyState(
        binding, user(), captured.password_temporary_config(binding, user(), RAW)
    )
    captured.admit(state, binding, user())
    with pytest.raises(AccountProtocolError):
        captured.admit(state, binding, user("foreign"))
    with pytest.raises(AccountProtocolError):
        state.encrypt(binding, user(), RAW)
