"""Private bounded responses; acknowledgement never proves persisted state."""

from dataclasses import dataclass, field
from enum import StrEnum

from .account_protocol import (
    MAX_NATIVE_INT,
    AccountProtocolError,
    AccountResponse,
    JsonValue,
    _integer,
    _text,
    private_json,
)


@dataclass(frozen=True, slots=True, repr=False)
class LoginType:
    user_id: str
    login_name: str
    login_type: int


@dataclass(frozen=True, slots=True)
class LoginTypes:
    entries: tuple[LoginType, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    acknowledged: bool = True


class SecurityState(StrEnum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    READ = "READ"
    CODE_SENT = "CODE_SENT"
    IMAGE_REQUIRED = "IMAGE_REQUIRED"
    IMAGE_REJECTED = "IMAGE_REJECTED"
    REJECTED = "REJECTED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


@dataclass(frozen=True, slots=True)
class CodeChallenge:
    state: SecurityState
    image_id: str | None = field(default=None, repr=False)
    private_image_data: str | None = field(default=None, repr=False)


def _decoded(data: JsonValue) -> JsonValue:
    # JSONObject.optString also accepts an already JSON-encoded string. Keep
    # duplicate-member/nonfinite rejection and the outer response's byte bound.
    if type(data) is str:
        wrapped = private_json(b'{"value":' + data.encode("utf-8") + b"}")
        if set(wrapped) != {"value"}:
            raise AccountProtocolError("Invalid security response.")
        return wrapped["value"]
    return data


def parse_login_types(response: AccountResponse) -> LoginTypes:
    response.require_success()
    data = _decoded(private_json(response.private_body).get("data"))
    if type(data) is not list or len(data) > 64:
        raise AccountProtocolError("Security inventory unavailable.")
    entries: list[LoginType] = []
    for row in data:
        if type(row) is not dict:
            raise AccountProtocolError("Security inventory unavailable.")
        entry = LoginType(
            _text(row.get("userId"), nonempty=True),
            _text(row.get("loginName"), nonempty=True),
            _integer(row.get("loginType"), -(2**31), MAX_NATIVE_INT),
        )
        if entry in entries:
            raise AccountProtocolError("Security inventory unavailable.")
        entries.append(entry)
    return LoginTypes(tuple(entries))


def parse_acknowledgement(response: AccountResponse) -> Acknowledgement:
    response.require_success()
    return Acknowledgement()


def parse_code(response: AccountResponse) -> CodeChallenge:
    if not 200 <= response.http_status <= 299:
        raise AccountProtocolError("Invalid security response.")
    if response.native_msgcode == 200:
        return CodeChallenge(SecurityState.CODE_SENT)
    if response.native_msgcode not in (1007, 1005):
        raise AccountProtocolError("Invalid security response.")
    envelope = private_json(response.private_body)
    raw = envelope.get("data")
    if raw is None or raw == "":
        raw = envelope.get("array")
    data = _decoded(raw)
    if type(data) is not dict:
        raise AccountProtocolError("Invalid security response.")
    return CodeChallenge(
        SecurityState.IMAGE_REQUIRED
        if response.native_msgcode == 1007
        else SecurityState.IMAGE_REJECTED,
        _text(data.get("idCode"), nonempty=True),
        _text(data.get("imgData"), nonempty=True),
    )
