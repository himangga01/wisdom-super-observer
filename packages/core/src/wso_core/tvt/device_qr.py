"""Private SN_USER input parsing; no credential, authority, or connection effect."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

MAX_DEVICE_INFO_QR_BYTES = 4096  # Local input policy, not an APK/native limit.
CONNECT_BY_TOKEN_DEVICE_ID_BYTES = 32
_SERIAL = re.compile(r"[a-zA-Z0-9]{1,128}")
_PAYLOAD = re.compile(r"<sn>([a-zA-Z0-9]{1,128})</sn><user>([^<>]+)</user>")
_QR10 = re.compile(r'"v"\s*:\s*"QR10"')


class DeviceInfoQrError(ValueError):
    """Fixed private validation error; never includes raw data or decoder errors."""


class UnsupportedDeviceQr(DeviceInfoQrError):
    """The separate QR10 sharing family is not supported by this parser."""


def _fail() -> DeviceInfoQrError:
    return DeviceInfoQrError("Private device information QR is invalid.")


def _utf8(value: str) -> bytes | None:
    # Raise outside decoder handlers so even __context__ carries no private data.
    try:
        return value.encode("utf-8", errors="strict")
    except UnicodeError:
        return None


def _valid_fields(serial: str, username: str) -> bool:
    if (
        type(serial) is not str
        or type(username) is not str
        or _SERIAL.fullmatch(serial) is None
        or not username
        or len(username) > MAX_DEVICE_INFO_QR_BYTES
        or any(char in username for char in ("\0", "<", ">"))
    ):
        return False
    encoded = _utf8(username)
    return (
        encoded is not None
        and len(serial) + len(encoded) + 22 <= MAX_DEVICE_INFO_QR_BYTES
    )


@dataclass(frozen=True, slots=True)
class DeviceInfoQr:
    """Private parsed connection input, never proof of identity or device access.

    Read fields only inside the authorized worker. Repr/str omit private values;
    callers must not serialize the object or send its fields to public/log APIs.
    """

    serial: str = field(repr=False)
    username: str = field(repr=False)

    def __post_init__(self) -> None:
        if not _valid_fields(self.serial, self.username):
            raise _fail()

    @property
    def status(self) -> Literal["not_connected"]:
        return "not_connected"


def parse_device_info_qr(payload: str | bytes) -> DeviceInfoQr:
    """Parse exactly two literal sequential tags from bounded strict UTF-8 text.

    No XML parser, entity expansion, whitespace removal, Unicode normalization,
    URL route, password default, persistence, logging, or network call is used.
    The 1..128 ASCII serial classifier is distinct from native dispatch limits.
    """

    text: str | None = None
    if type(payload) is str:
        if len(payload) > MAX_DEVICE_INFO_QR_BYTES:
            raise _fail()
        encoded = _utf8(payload)
        if encoded is not None and len(encoded) <= MAX_DEVICE_INFO_QR_BYTES:
            text = payload
    elif type(payload) is bytes and len(payload) <= MAX_DEVICE_INFO_QR_BYTES:
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeError:
            pass
    if text is None or "\0" in text:
        raise _fail()
    if text.lstrip().startswith("{") and _QR10.search(text) is not None:
        raise UnsupportedDeviceQr("QR10 sharing QR is unsupported.")
    match = _PAYLOAD.fullmatch(text)
    if match is None:
        raise _fail()
    return DeviceInfoQr(match[1], match[2])


def validate_connect_by_token_device_info(value: DeviceInfoQr) -> DeviceInfoQr:
    """Check the selected NetClientProtocal.ConnectDevByToken device-ID bound.

    Select the route first: this 32-byte check does not validate manual QR,
    NatTraveral, LAN, or sharing connection routes. The caller still needs
    authorized credentials, actor/store/channel checks and actual login evidence.
    This only validates private input; username ABI checks remain with the adapter.
    """

    if (
        type(value) is not DeviceInfoQr
        or not _valid_fields(value.serial, value.username)
        or len(value.serial.encode("ascii")) > CONNECT_BY_TOKEN_DEVICE_ID_BYTES
    ):
        raise _fail()
    return value
