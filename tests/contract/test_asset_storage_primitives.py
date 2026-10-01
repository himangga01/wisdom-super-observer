from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest


def test_namespace_and_strict_owned_inverse() -> None:
    from wso_core.storage import (
        InstallationNamespace,
        ObjectLocator,
        object_key,
        parse_object_key,
    )

    ns = InstallationNamespace(UUID(int=1), "private-assets")
    locator = ObjectLocator(ns.installation_id, UUID(int=2), UUID(int=3), UUID(int=4))
    key = (
        "wso-assets/v1/"
        + "0" * 31
        + "1/objects/"
        + "0" * 31
        + "2/"
        + "0" * 31
        + "3/"
        + "0" * 31
        + "4.wso"
    )
    assert object_key(locator) == key
    assert parse_object_key(ns, key) == locator
    assert parse_object_key(ns, key.upper()) is None
    assert parse_object_key(ns, key + "/extra") is None
    assert parse_object_key(ns, key.replace("1/objects", "9/objects")) is None


def make_aad(data: bytes):
    from wso_core.storage import AssetAAD

    return AssetAAD(
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        None,
        None,
        "IMPORT_PHOTO",
        len(data),
        "image/png",
        hashlib.sha256(data).hexdigest(),
    )


def test_independent_aad_vector() -> None:
    from wso_core.asset_crypto import encode_asset_aad, encode_wrap_aad

    aad = replace(make_aad(b"abc"), checksum_sha256="ab" * 32)
    vector = (
        b"WSOASSET-AAD-v1\0"
        + bytes.fromhex("00" * 15 + "01" + "00" * 15 + "02" + "00" * 15 + "03")
        + b"\0\0\1"
        + bytes.fromhex("0000000000000003")
        + b"\2"
        + b"\xab" * 32
    )
    assert encode_asset_aad(aad) == vector
    assert encode_wrap_aad(aad, "k1") == b"WSOASSET-WRAP-v1\0" + vector + b"\2k1"


def test_independent_aad_present_optional_identifiers_vector() -> None:
    from wso_core.asset_crypto import encode_asset_aad

    aad = replace(
        make_aad(b"abc"),
        store_id=UUID(int=4),
        parent_asset_id=UUID(int=5),
        purpose="IMPORT_CROP",
        content_type="image/jpeg",
        checksum_sha256="00" * 32,
    )
    uuid_bytes = bytes.fromhex("00" * 15)
    vector = (
        b"WSOASSET-AAD-v1\0"
        + uuid_bytes
        + b"\1"
        + uuid_bytes
        + b"\2"
        + uuid_bytes
        + b"\3"
        + b"\1"
        + uuid_bytes
        + b"\4"
        + b"\1"
        + uuid_bytes
        + b"\5"
        + b"\2"
        + bytes.fromhex("0000000000000003")
        + b"\1"
        + b"\0" * 32
    )
    assert encode_asset_aad(aad) == vector


class MemoryKeys:
    def active_key_id(self):
        return "key1"

    def wrap(self, key_id, dek, aad):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from wso_core.storage import WrappedKey

        nonce = b"w" * 12
        return WrappedKey(nonce, AESGCM(b"k" * 32).encrypt(nonce, dek, aad))

    def unwrap(self, key_id, envelope, aad):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return AESGCM(b"k" * 32).decrypt(envelope.wrap_nonce, envelope.ciphertext, aad)


def encrypted(data: bytes):
    from wso_core.asset_crypto import AssetCipher
    from wso_core.storage import AssetLease, ObjectLocator, ReadManifest

    cipher = AssetCipher(MemoryKeys())
    aad = make_aad(data)
    prepared = cipher.prepare(aad)
    stream = cipher.start(prepared)
    raw = stream.header() + stream.update(data) + stream.finish().tail
    lease = AssetLease(
        UUID(int=4), 1, datetime.now(UTC) + timedelta(seconds=30), 30000, "a" * 64
    )
    manifest = ReadManifest(
        "VALIDATE",
        ObjectLocator(UUID(int=5), aad.tenant_id, aad.asset_id, aad.attempt_id),
        aad,
        prepared.envelope,
        lease,
        1,
        None,
        1,
    )
    return cipher, prepared, stream, raw, manifest


def test_crypto_roundtrip_and_single_use() -> None:
    from wso_core.asset_crypto import AssetCryptoFailure
    from wso_core.storage import IOBudget

    data = b"private bytes"
    cipher, prepared, stream, raw, manifest = encrypted(data)
    assert data not in raw
    result = cipher.decrypt_verified(
        manifest, [raw[:17], raw[17:]], budget=IOBudget(time.monotonic() + 5)
    )
    assert result.data == data
    for action in (
        lambda: cipher.start(prepared),
        stream.header,
        stream.finish,
        lambda: stream.update(b"x"),
    ):
        with pytest.raises(AssetCryptoFailure):
            action()


@pytest.mark.parametrize(
    "mode", ["tag", "header", "nonce", "truncated", "extra", "aad", "hash", "length"]
)
def test_crypto_tamper_never_returns_plaintext(mode: str) -> None:
    from wso_core.asset_crypto import AssetCryptoFailure
    from wso_core.storage import IOBudget

    cipher, _, _, raw, manifest = encrypted(b"secret")
    if mode == "tag":
        raw = raw[:-1] + bytes([raw[-1] ^ 1])
    elif mode == "header":
        raw = b"X" + raw[1:]
    elif mode == "nonce":
        raw = raw[:8] + bytes([raw[8] ^ 1]) + raw[9:]
    elif mode == "truncated":
        raw = raw[:-1]
    elif mode == "extra":
        raw += b"X"
    else:
        changes = {
            "aad": {"tenant_id": UUID(int=99)},
            "hash": {"checksum_sha256": "0" * 64},
            "length": {"byte_size": 5},
        }[mode]
        if mode == "aad":
            manifest = replace(
                manifest,
                aad=replace(manifest.aad, **changes),
                locator=replace(manifest.locator, tenant_id=UUID(int=99)),
            )
        else:
            manifest = replace(manifest, aad=replace(manifest.aad, **changes))
    with pytest.raises(AssetCryptoFailure):
        cipher.decrypt_verified(manifest, [raw], budget=IOBudget(time.monotonic() + 5))


def test_crypto_nonce_tamper_rejects_original_x(monkeypatch) -> None:
    from wso_core import asset_crypto

    random_bytes = asset_crypto.os.urandom

    def nonce_with_original_x(size):
        value = random_bytes(size)
        return b"X" + value[1:] if size == 12 else value

    monkeypatch.setattr(asset_crypto.os, "urandom", nonce_with_original_x)
    test_crypto_tamper_never_returns_plaintext("nonce")


def test_declared_plaintext_constraints_before_completion() -> None:
    from wso_core.asset_crypto import AssetCipher, AssetCryptoFailure

    cipher = AssetCipher(MemoryKeys())
    stream = cipher.start(cipher.prepare(make_aad(b"abc")))
    stream.header()
    with pytest.raises(AssetCryptoFailure):
        stream.update(b"abcd")
    stream = cipher.start(cipher.prepare(make_aad(b"abc")))
    stream.header()
    stream.update(b"abd")
    with pytest.raises(AssetCryptoFailure):
        stream.finish()


def test_strict_configuration_and_command_fields() -> None:
    from wso_core.storage import InstallationNamespace, S3Credentials, S3RuntimeConfig

    ns = InstallationNamespace(UUID(int=1), "private-assets")
    credentials = S3Credentials("access", "secret")
    for endpoint in (
        "http://example.com",
        "https://u:p@example.com",
        "https://example.com/?x=1",
        "https://example.com/#a",
        "https://example.com?",
        "https://example.com#",
        "https://exam\nple.com",
        "https://example.com:0",
    ):
        with pytest.raises(ValueError):
            S3RuntimeConfig(endpoint, "us-east-1", credentials, ns, True)
    assert "secret" not in repr(credentials)


def test_image_decoder_loads_real_bytes_and_rejects_truncation() -> None:
    import io

    from PIL import Image
    from wso_core.asset_images import ImageValidationFailure, ImageValidator
    from wso_core.storage import AssetPolicy, IOBudget, VerifiedPlaintext

    buf = io.BytesIO()
    Image.new("RGB", (11, 7), "red").save(buf, format="PNG")
    raw = buf.getvalue()
    validator = ImageValidator(policy=AssetPolicy(version=1))
    assert validator.sniff(raw[:32]) == "image/png"

    def validate(data):
        return validator.validate(
            VerifiedPlaintext(data, len(data), hashlib.sha256(data).hexdigest()),
            expected_type="image/png",
            budget=IOBudget(time.monotonic() + 10),
        )

    info = validate(raw)
    assert (info.width, info.height, info.frame_count) == (11, 7, 1)
    with pytest.raises(ImageValidationFailure):
        validate(raw[:-10])
