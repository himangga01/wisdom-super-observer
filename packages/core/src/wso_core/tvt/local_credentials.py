"""Private versioned local-device storage input; no transport or authority.

Only to_encrypt_bytes exports credentials, for the existing authenticated
encryption boundary. Worker callers must retain this type inside their scope.
"""

from __future__ import annotations

import json
import re
from typing import Any, NoReturn, SupportsIndex

from wso_core.tvt.device_qr import DeviceInfoQrError, parse_device_info_qr
from wso_core.tvt.local_bootstrap import _AREAS
from wso_core.tvt.local_n9000 import CodecError, Credentials

# The exact reviewed bootstrap resource memberships; no fallback/endpoint input.
KNOWN_LOCAL_COUNTRIES = frozenset(
    country for _, _, countries in _AREAS for country in countries.split()
)
_KEYS = {"schema_version", "kind", "serial", "country", "username", "password"}


class LocalCredentialError(ValueError):
    """Fixed input-required error, without raw input or decoder context."""


def _fail() -> LocalCredentialError:
    return LocalCredentialError("Local device credentials require valid input.")


def _valid_credentials(username: str, password: str) -> bool:
    if type(username) is not str or type(password) is not str:
        return False
    try:
        Credentials(username, password)
    except CodecError:
        return False
    return True


def _qr_matches(payload: str, serial: str, username: str) -> bool:
    if type(payload) is not str:
        return False
    try:
        qr = parse_device_info_qr(payload)
    except DeviceInfoQrError:
        return False
    return qr.serial.upper() == serial and qr.username == username


class LocalDeviceCredentials:
    __slots__ = ("country", "password", "serial", "username")
    serial: str
    country: str
    username: str
    password: str

    def __init__(
        self,
        *,
        serial: str,
        country: str = "KR",
        username: str,
        password: str,
        qr_payload: str | None = None,
    ) -> None:
        if (
            type(serial) is not str
            or re.fullmatch(r"[A-Za-z0-9]{1,63}", serial) is None
            or type(country) is not str
            or country not in KNOWN_LOCAL_COUNTRIES
            or not _valid_credentials(username, password)
        ):
            raise _fail()
        serial = serial.upper()
        if qr_payload is not None and not _qr_matches(qr_payload, serial, username):
            raise _fail()
        for name, value in (
            ("serial", serial),
            ("country", country),
            ("username", username),
            ("password", password),
        ):
            object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        return "<LocalDeviceCredentials: private>"

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("private local credentials are immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("private local credentials are immutable")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("private local credentials cannot be serialized")

    def to_encrypt_bytes(self) -> bytes:
        """Explicit encrypt-only serialization; never send to logs/public DTOs."""
        return json.dumps(
            {
                "schema_version": 1,
                "kind": "TVT_DEVICE",
                "serial": self.serial,
                "country": self.country,
                "username": self.username,
                "password": self.password,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _decode(raw: bytes) -> object:
    try:
        return json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_unique_object
        )
    except (ValueError, UnicodeError, RecursionError):
        return None


def parse_local_device_credentials(raw: bytes) -> LocalDeviceCredentials:
    """Reject legacy/malformed/duplicate/noncanonical data as input-required."""
    if type(raw) is not bytes or len(raw) > 4096:
        raise _fail()
    body = _decode(raw)
    if (
        type(body) is not dict
        or set(body) != _KEYS
        or type(body["schema_version"]) is not int
        or body["schema_version"] != 1
        or body["kind"] != "TVT_DEVICE"
        or any(
            type(body[key]) is not str
            for key in ("serial", "country", "username", "password")
        )
        or body["serial"] != body["serial"].upper()
    ):
        raise _fail()
    return LocalDeviceCredentials(
        serial=body["serial"],
        country=body["country"],
        username=body["username"],
        password=body["password"],
    )
