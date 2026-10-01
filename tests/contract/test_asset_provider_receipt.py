"""Offline receipt contracts do not establish actual provider acceptance."""

import json

import pytest

from scripts.asset_provider_receipt import (
    make_provider_receipt,
    parse_provider_receipt,
    validate_provider_receipt,
)

IMAGE_ID = "sha256:" + "a" * 64
CANONICAL = {
    "provider": "RustFS",
    "version": "1.0.0",
    "security_profile": "rustfs-inert-acl-dedicated-bucket-v1",
    "artifact_kind": "official-zip-server-local-scratch-image",
    "archive_sha256": "c30a95b76546f25122c9ca387090ddb30c391ca5605621b0d7c881703c0f21c8",
    "archive_bytes": 194469895,
    "binary_sha256": "222eedc3d9baabf6516702d9fbf230270c3ca49b50f562d3461c96e2cc6ae6ad",
    "binary_bytes": 264596736,
    "source_commit": "d47f54bfb2f39f48bd1adda334bd27e151fe85b8",
    "image_id": IMAGE_ID,
    "admin_bootstrap": "native-sigv4-iam-zip-v1",
    "capabilities": "private IAM/put/get/head/delete/multipart/list/abort/presign-expiry/durable-prefix-pagination/restart",
    "owned_resource_mapping": True,
}


class TextSubclass(str):
    pass


class IntSubclass(int):
    pass


class DictSubclass(dict):
    pass


class BytesSubclass(bytes):
    pass


def assert_rejected(call, value):
    with pytest.raises(ValueError) as failure:
        call(value)
    assert str(failure.value) == "provider receipt is invalid"
    assert failure.value.__cause__ is None


def test_factory_produces_exact_receipt_in_canonical_order_and_fresh_copies():
    first = make_provider_receipt(image_id=IMAGE_ID)
    second = make_provider_receipt(image_id=IMAGE_ID)
    assert first == CANONICAL
    assert list(first) == list(CANONICAL)
    assert first is not second
    first["provider"] = "PRIVATE_SENTINEL"
    assert second == CANONICAL
    assert make_provider_receipt(image_id=IMAGE_ID) == CANONICAL


def test_validator_returns_independent_canonical_copy_without_mutating_input():
    supplied = dict(reversed(list(CANONICAL.items())))
    before = supplied.copy()
    validated = validate_provider_receipt(supplied)
    assert validated == CANONICAL
    assert list(validated) == list(CANONICAL)
    assert validated is not supplied
    assert supplied == before
    validated["version"] = "PRIVATE_SENTINEL"
    assert supplied == before


@pytest.mark.parametrize("key", list(CANONICAL))
def test_each_required_field_cannot_be_missing(key):
    supplied = CANONICAL.copy()
    del supplied[key]
    assert_rejected(validate_provider_receipt, supplied)


@pytest.mark.parametrize("key", list(CANONICAL))
def test_each_field_rejects_wrong_type_and_private_values_without_mutation(key):
    supplied = CANONICAL.copy()
    supplied[key] = {"PRIVATE_SENTINEL": "private"}
    before = supplied.copy()
    assert_rejected(validate_provider_receipt, supplied)
    assert supplied == before


@pytest.mark.parametrize("key", list(CANONICAL))
def test_each_fixed_field_and_image_grammar_rejects_wrong_value(key):
    supplied = CANONICAL.copy()
    current = supplied[key]
    supplied[key] = (
        "PRIVATE_SENTINEL"
        if type(current) is str
        else False
        if type(current) is bool
        else current + 1
    )
    assert_rejected(validate_provider_receipt, supplied)


@pytest.mark.parametrize(
    "key,value",
    [
        ("archive_bytes", True),
        ("binary_bytes", True),
        ("archive_bytes", 194469895.0),
        ("binary_bytes", 264596736.0),
        ("archive_bytes", IntSubclass(194469895)),
        ("binary_bytes", IntSubclass(264596736)),
        ("owned_resource_mapping", 1),
    ],
)
def test_native_integer_and_bool_types_are_required(key, value):
    supplied = CANONICAL.copy()
    supplied[key] = value
    assert_rejected(validate_provider_receipt, supplied)


@pytest.mark.parametrize("key", [k for k, v in CANONICAL.items() if type(v) is str])
def test_string_subclasses_are_refused_even_when_equal(key):
    supplied = CANONICAL.copy()
    supplied[key] = TextSubclass(supplied[key])
    assert_rejected(validate_provider_receipt, supplied)


def test_string_key_subclasses_are_refused_even_when_equal():
    supplied = CANONICAL.copy()
    del supplied["provider"]
    supplied[TextSubclass("provider")] = "RustFS"
    assert_rejected(validate_provider_receipt, supplied)


@pytest.mark.parametrize(
    "value", [None, [], DictSubclass(CANONICAL), "PRIVATE_SENTINEL"]
)
def test_only_native_dict_is_accepted(value):
    assert_rejected(validate_provider_receipt, value)


@pytest.mark.parametrize("extra", ["endpoint", "client_version", "PRIVATE_SENTINEL"])
def test_extra_fields_are_never_returned(extra):
    supplied = CANONICAL.copy()
    supplied[extra] = "PRIVATE_SENTINEL"
    assert_rejected(validate_provider_receipt, supplied)


@pytest.mark.parametrize(
    "provider,profile",
    [
        ("SeaweedFS", "seaweedfs-private-iam-ownership-v1"),
        ("MinIO", "minio-inert-acl-dedicated-bucket-v1"),
        ("MinIO", "minio-inert-acl-dedicated-bucket-v2"),
        ("RustFS", "unknown"),
    ],
)
def test_rejected_legacy_and_unknown_profiles_cannot_be_canonical(provider, profile):
    supplied = CANONICAL.copy()
    supplied.update(provider=provider, security_profile=profile)
    assert_rejected(validate_provider_receipt, supplied)


@pytest.mark.parametrize(
    "image_id",
    [
        None,
        True,
        b"sha256:" + b"a" * 64,
        TextSubclass(IMAGE_ID),
        "sha256:" + "A" * 64,
        "sha256:" + "g" * 64,
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 65,
        IMAGE_ID + "\n",
        " " + IMAGE_ID,
        "rustfs:local",
        "rustfs@" + IMAGE_ID,
        "sha256:" + "\uff41" * 64,
    ],
)
def test_factory_refuses_non_native_or_noncanonical_image_identity(image_id):
    assert_rejected(lambda value: make_provider_receipt(image_id=value), image_id)


def test_image_identity_is_the_only_variable_receipt_field():
    image_id = "sha256:" + "0123456789abcdef" * 4
    expected = CANONICAL.copy()
    expected["image_id"] = image_id
    assert make_provider_receipt(image_id=image_id) == expected


def test_parser_accepts_json_whitespace_reordered_keys_and_exact_size_boundary():
    payload = json.dumps(dict(reversed(list(CANONICAL.items())))).encode("utf-8")
    payload += b" " * (16 * 1024 - len(payload))
    parsed = parse_provider_receipt(payload)
    assert parsed == CANONICAL
    assert list(parsed) == list(CANONICAL)
    assert_rejected(parse_provider_receipt, payload + b" ")


@pytest.mark.parametrize(
    "value",
    [
        None,
        "PRIVATE_SENTINEL",
        bytearray(b"{}"),
        memoryview(b"{}"),
        BytesSubclass(b"{}"),
        b"\xef\xbb\xbf{}",
        b"\xffPRIVATE_SENTINEL",
        b"",
        json.dumps(CANONICAL).encode("utf-16"),
        json.dumps(CANONICAL).encode("utf-32"),
        b"[" * 2000 + b"]" * 2000,
        b'{"PRIVATE_SENTINEL":',
    ],
)
def test_parser_refuses_wrong_bytes_encoding_bom_and_deep_malformed_json(value):
    assert_rejected(parse_provider_receipt, value)


@pytest.mark.parametrize("key", list(CANONICAL))
def test_parser_refuses_duplicate_canonical_keys_before_dict_construction(key):
    payload = json.dumps(CANONICAL)
    extra = json.dumps(key) + ":" + json.dumps(CANONICAL[key])
    assert_rejected(parse_provider_receipt, (payload[:-1] + "," + extra + "}").encode())


@pytest.mark.parametrize(
    "invalid",
    [
        '{"PRIVATE_SENTINEL":{"x":1,"x":1}}',
        '{"PRIVATE_SENTINEL":[{"x":1,"x":1}]}',
        '{"PRIVATE_SENTINEL":NaN}',
        '{"PRIVATE_SENTINEL":Infinity}',
        '{"PRIVATE_SENTINEL":-Infinity}',
    ],
)
def test_parser_refuses_nested_duplicates_and_nonfinite_numbers(invalid):
    assert_rejected(parse_provider_receipt, invalid.encode())


def test_parser_does_not_accept_an_outer_red_receipt():
    payload = json.dumps({"schema_version": 1, "provider": CANONICAL}).encode()
    assert_rejected(parse_provider_receipt, payload)
