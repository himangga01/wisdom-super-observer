"""Invented known answers and source fixture comparison, never vendor secrets."""

import base64
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from test_security_adapter import identity, reply, scope, token
from wso_core.tvt.account_protocol import AccountProtocolError


def crypto():
    name = "wso_core.tvt.security_crypto"
    assert importlib.util.find_spec(name) is not None, "Scoped SID key state missing"
    return importlib.import_module(name)


def test_nist_aes128_ecb_known_answer_sid_derivation():
    s = crypto()
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    ciphertext = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    assert s.derive_key_text(ciphertext, key) == base64.b64encode(
        bytes.fromhex("00112233445566778899aabbccddeeff")
    )


def test_source_original_eight_private_fixtures_without_publishing_constants():
    path = (
        Path(__file__).resolve().parents[2]
        / ".superpowers/verification/apk-account-flows/postlogin-vectors-private.json"
    )
    if not path.exists():
        pytest.skip("Private accepted source packet unavailable")
    cases = json.loads(path.read_text())["cases"]
    assert len(cases) == 8
    s = crypto()
    for case in cases:
        derived = s.derive_key_text(
            case["sid"].encode(), base64.b64decode(case["temp_b64"])
        )
        assert derived.decode() == case["expected_key_b64"], case["case"]
        assert (
            s.encrypt_password("Synthetic_Changed8!", derived)
            == case["expected_update"]
        ), case["case"]


def synthetic_sid(temp=b"0123456789abcdef", plain=b"fedcba9876543210"):
    enc = Cipher(algorithms.AES(temp), modes.ECB()).encryptor()
    return base64.b64encode(enc.update(plain) + enc.finalize()).decode()


def binding(generation=1, token_id="token-id-1"):
    return crypto().KeyBinding(scope(), identity(), generation, token_id)


class Config:
    def temporary_key(self, binding):
        return b"0123456789abcdef"


def state():
    s = crypto().SecurityKeyState(binding(), token(), Config())
    s.admit(
        binding(), token(), reply({"sid": synthetic_sid(), "tokenId": "token-id-1"})
    )
    return s


def test_admitted_key_encrypts_raw_utf8_md5_no_padding_and_is_redacted():
    s = state()
    encrypted = s.encrypt(binding(), token(), " new P@ssword9! ")
    assert len(encrypted) == 44 and len(base64.b64decode(encrypted)) == 32
    dec = Cipher(algorithms.AES(b"fedcba9876543210"), modes.ECB()).decryptor()
    assert (
        dec.update(base64.b64decode(encrypted)) + dec.finalize()
    ).decode() == "e793da4d0caaec1246527ba4b1cb35d4"
    assert "0123456789abcdef" not in repr(s) and "token-id-1" not in repr(binding())


@pytest.mark.parametrize(
    "changed", [{"generation": 2}, {"token_id": "foreign"}, {"scope": None}]
)
def test_stale_or_mismatched_binding_clears_key(changed):
    s = state()
    with pytest.raises(AccountProtocolError):
        s.encrypt(replace(binding(), **changed), token(), "Password9!")
    with pytest.raises(AccountProtocolError):
        s.encrypt(binding(), token(), "Password9!")


@pytest.mark.parametrize(
    "data,code",
    [
        (None, 200),
        ({"sid": "", "tokenId": "token-id-1"}, 200),
        ({"sid": "invalid=", "tokenId": "token-id-1"}, 200),
        ({"sid": synthetic_sid(), "tokenId": "foreign"}, 200),
        ({"sid": synthetic_sid(), "tokenId": "token-id-1"}, 7000),
    ],
)
def test_failed_admission_cannot_reuse_previous_key(data, code):
    s = state()
    with pytest.raises(AccountProtocolError):
        s.admit(binding(), token(), reply(data, code))
    with pytest.raises(AccountProtocolError):
        s.encrypt(binding(), token(), "Password9!")


def test_same_nonempty_token_id_preserves_admitted_key_and_close_invalidates():
    s = state()
    before = s.encrypt(binding(), token(), "Password9!")
    s.admit(
        binding(),
        token(),
        reply(
            {"sid": synthetic_sid(plain=b"aaaaaaaaaaaaaaaa"), "tokenId": "token-id-1"}
        ),
    )
    assert s.encrypt(binding(), token(), "Password9!") == before
    s.close()
    with pytest.raises(AccountProtocolError):
        s.encrypt(binding(), token(), "Password9!")


def test_empty_or_foreign_configuration_never_admits_key():
    for value in [b"", b"bad", None, "0123456789abcdef"]:

        class InvalidConfig:
            def temporary_key(self, binding, value=value):
                return value

        with pytest.raises(AccountProtocolError):
            s = crypto().SecurityKeyState(binding(), token(), InvalidConfig())
            s.admit(
                binding(),
                token(),
                reply({"sid": synthetic_sid(), "tokenId": "token-id-1"}),
            )


def test_original_mutable_scope_cannot_rebind_admitted_key():
    original = binding()
    s = crypto().SecurityKeyState(original, token(), Config())
    s.admit(original, token(), reply({"sid": synthetic_sid(), "tokenId": "token-id-1"}))
    original.scope.region = "foreign-region"
    with pytest.raises(AccountProtocolError):
        s.encrypt(original, token(), "Password9!")


@pytest.mark.parametrize("field,value", [("region", "foreign"), ("brand", "foreign")])
def test_region_brand_mismatch_rejected_and_terminal(field, value):
    s = state()
    b = binding()
    foreign = replace(b, scope=b.scope.model_copy(update={field: value}))
    with pytest.raises(AccountProtocolError):
        s.encrypt(foreign, token(), "Password9!")
    with pytest.raises(AccountProtocolError):
        s.encrypt(binding(), token(), "Password9!")


def test_token_bytes_and_non_user_kind_do_not_establish_key_consistency():
    from wso_contracts.tvt.identity import TokenKind
    from wso_core.tvt.ports import PrivateToken

    for foreign in [
        PrivateToken(identity(), TokenKind.USER, "foreign"),
        PrivateToken(identity(), TokenKind.P2P, "synthetic-user"),
    ]:
        s = state()
        with pytest.raises(AccountProtocolError):
            s.encrypt(binding(), foreign, "Password9!")


def test_raw_and_base64_heuristic_with_zero_extension_and_final_length_guard():
    s = crypto()
    raw = bytes(range(16))
    assert s.derive_key_text(raw, b"0123456789abcdef") == s.derive_key_text(
        base64.b64encode(raw), base64.b64encode(b"0123456789abcdef")
    )
    # Native zero-extension is mathematical behavior; admission must reject it.
    assert len(base64.b64decode(s.derive_key_text(b"x", b"0123456789abcdef"))) == 16
    key = s.SecurityKeyState(binding(), token(), Config())
    with pytest.raises(AccountProtocolError):
        key.admit(binding(), token(), reply({"sid": "x", "tokenId": "token-id-1"}))
    # A valid 48-byte decrypted SID is not an AES key and cannot be admitted.
    enc = Cipher(algorithms.AES(b"0123456789abcdef"), modes.ECB()).encryptor()
    sid = base64.b64encode(enc.update(b"x" * 48) + enc.finalize()).decode()
    key = s.SecurityKeyState(binding(), token(), Config())
    with pytest.raises(AccountProtocolError):
        key.admit(binding(), token(), reply({"sid": sid, "tokenId": "token-id-1"}))


def test_admission_revalidates_response_status_consistency_and_byte_bound():
    from wso_core.tvt.account_protocol import AccountResponse

    for response in [
        AccountResponse(
            200,
            200,
            reply({"sid": synthetic_sid(), "tokenId": "token-id-1"}, 7000).private_body,
        ),
        AccountResponse(200, 200, b" " * 1048577),
    ]:
        key = state()
        with pytest.raises(AccountProtocolError):
            key.admit(binding(), token(), response)
        with pytest.raises(AccountProtocolError):
            key.encrypt(binding(), token(), "Password9!")
