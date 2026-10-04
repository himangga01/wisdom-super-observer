"""Synthetic inputs only: canonical private registration and worker parser."""

import json
import pickle
from dataclasses import asdict
from uuid import uuid4

import pytest


def codec():
    from wso_core.tvt import local_credentials

    return local_credentials


def make(**changes):
    values = {
        "serial": "inert123",
        "country": "KR",
        "username": "fixture-user",
        "password": "fixture-password",
    }
    values.update(changes)
    return codec().LocalDeviceCredentials(**values)


def test_canonical_versioned_roundtrip_is_private_and_encrypt_only(tmp_path):
    value = make()
    raw = value.to_encrypt_bytes()
    assert json.loads(raw) == {
        "schema_version": 1,
        "kind": "TVT_DEVICE",
        "serial": "INERT123",
        "country": "KR",
        "username": "fixture-user",
        "password": "fixture-password",
    }
    parsed = codec().parse_local_device_credentials(raw)
    assert parsed.to_encrypt_bytes() == raw
    assert "INERT123" not in repr(parsed) and "fixture-" not in str(parsed)
    with pytest.raises(TypeError):
        pickle.dumps(parsed)
    with pytest.raises(TypeError):
        asdict(parsed)
    with pytest.raises(TypeError):
        vars(parsed)
    from wso_core.secrets import FileKeyProvider, SecretCipher

    key = tmp_path / "key"
    key.write_bytes(bytes(range(32)))
    cipher = SecretCipher(FileKeyProvider(key))
    tenant, connection, version = uuid4(), uuid4(), uuid4()
    sealed = cipher.seal(tenant, connection, version, raw)
    assert b"INERT123" not in sealed.ciphertext
    assert b"fixture-password" not in sealed.ciphertext
    assert cipher.open(tenant, connection, version, sealed) == raw


@pytest.mark.parametrize(
    "changes",
    [
        {"serial": ""},
        {"serial": "x" * 64},
        {"serial": "aa-bb"},
        {"serial": "한글"},
        {"serial": 5},
        {"country": "ZZ"},
        {"country": "AP"},
        {"country": "kr"},
        {"username": ""},
        {"password": ""},
        {"username": "a\0b"},
        {"password": "a\0b"},
        {"username": "한" * 22},
        {"password": "a" * 64},
        {"password": "\ud800"},
        {"username": None},
    ],
)
def test_invalid_input_fixed_private_error(changes):
    with pytest.raises(codec().LocalCredentialError) as caught:
        make(**changes)
    assert str(caught.value) == "Local device credentials require valid input."
    assert caught.value.__context__ is None


def test_utf8_boundary_and_immutable_value():
    value = make(username="한" * 21, password="a" * 63, serial="x" * 63)
    with pytest.raises((AttributeError, TypeError)):
        value.password = "change"


def test_qr_revalidation_rejects_contradictions_and_sharing():
    assert (
        make(qr_payload="<sn>INERT123</sn><user>fixture-user</user>").serial
        == "INERT123"
    )
    with pytest.raises(codec().LocalCredentialError):
        make(qr_payload=b"<sn>INERT123</sn><user>fixture-user</user>")
    for payload in [
        "<sn>OTHER</sn><user>fixture-user</user>",
        "<sn>INERT123</sn><user>other</user>",
        '{"v":"QR10"}',
        "malformed",
    ]:
        with pytest.raises(codec().LocalCredentialError) as caught:
            make(qr_payload=payload)
        assert caught.value.__context__ is None
    assert "qr_payload" not in json.loads(
        make(qr_payload="<sn>INERT123</sn><user>fixture-user</user>").to_encrypt_bytes()
    )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"username":"private","password":"private"}',
        b"{",
        b"\xff",
        b'{"schema_version":1,"schema_version":1}',
        b"[]",
        b"null",
        b"0",
        b'"private"',
    ],
)
def test_parser_rejects_malformed_duplicate_and_legacy_inputs_without_context(raw):
    with pytest.raises(codec().LocalCredentialError) as caught:
        codec().parse_local_device_credentials(raw)
    assert caught.value.__context__ is None
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"kind": "TVT_ACCOUNT"},
        {"serial": "inert123"},
        {"extra": "private"},
        {"username": 1},
    ],
)
def test_parser_rejects_schema_type_kind_unknown_and_noncanonical(changes):
    value = json.loads(make().to_encrypt_bytes())
    value.update(changes)
    with pytest.raises(codec().LocalCredentialError):
        codec().parse_local_device_credentials(json.dumps(value).encode())


def test_duplicate_key_in_otherwise_valid_document_is_rejected():
    raw = (
        make()
        .to_encrypt_bytes()
        .replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
    )
    with pytest.raises(codec().LocalCredentialError) as caught:
        codec().parse_local_device_credentials(raw)
    assert caught.value.__context__ is None
