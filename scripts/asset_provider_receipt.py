"""Pure canonical RustFS provider receipt factory and strict JSON boundary."""

import json
import re

_INVALID = "provider receipt is invalid"
_CANONICAL: dict[str, object] = {
    "provider": "RustFS",
    "version": "1.0.0",
    "security_profile": "rustfs-inert-acl-dedicated-bucket-v1",
    "artifact_kind": "official-zip-server-local-scratch-image",
    "archive_sha256": "c30a95b76546f25122c9ca387090ddb30c391ca5605621b0d7c881703c0f21c8",
    "archive_bytes": 194469895,
    "binary_sha256": "222eedc3d9baabf6516702d9fbf230270c3ca49b50f562d3461c96e2cc6ae6ad",
    "binary_bytes": 264596736,
    "source_commit": "d47f54bfb2f39f48bd1adda334bd27e151fe85b8",
    "image_id": "",
    "admin_bootstrap": "native-sigv4-iam-zip-v1",
    "capabilities": "private IAM/put/get/head/delete/multipart/list/abort/presign-expiry/durable-prefix-pagination/restart",
    "owned_resource_mapping": True,
}


def make_provider_receipt(*, image_id: str) -> dict[str, object]:
    """Return fresh public provider evidence for a validated local image ID."""
    value = _CANONICAL.copy()
    value["image_id"] = image_id
    return validate_provider_receipt(value)


def validate_provider_receipt(value: object) -> dict[str, object]:
    """Reject substitutions and return a fresh dictionary in canonical order."""
    if (
        type(value) is not dict
        or any(type(key) is not str for key in value)
        or value.keys() != _CANONICAL.keys()
    ):
        raise ValueError(_INVALID)
    for key, fixed in _CANONICAL.items():
        observed = value[key]
        if type(observed) is not type(fixed):
            raise ValueError(_INVALID)
        if key == "image_id":
            if (
                type(observed) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", observed) is None
            ):
                raise ValueError(_INVALID)
        elif observed != fixed:
            raise ValueError(_INVALID)
    result = _CANONICAL.copy()
    result["image_id"] = value["image_id"]
    return result


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(_INVALID)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(_INVALID)


def parse_provider_receipt(payload: bytes) -> dict[str, object]:
    """Parse standalone provider JSON with bounded strict UTF-8 decoding."""
    if type(payload) is not bytes or len(payload) > 16 * 1024:
        raise ValueError(_INVALID)
    try:
        decoded = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_keys,
            parse_constant=_reject_nonfinite,
        )
        return validate_provider_receipt(decoded)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError(_INVALID) from None
