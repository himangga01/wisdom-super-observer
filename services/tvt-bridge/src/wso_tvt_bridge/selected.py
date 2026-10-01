"""Closed transport schema, bounded wire data and public failure vocabulary."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from google.protobuf.message import Message
from pydantic import BaseModel
from wso_contracts.tvt.account import AccountLogin, AccountRefresh, ImageCheckRequest
from wso_core.tvt.account_projection import AccountFailure

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 524288
MAX_REQUEST_BYTES = 32768
MAX_DEADLINE_MS = 20000
GRPC_OPTIONS = (
    ("grpc.max_receive_message_length", MAX_FRAME_BYTES),
    ("grpc.max_send_message_length", MAX_FRAME_BYTES),
    ("grpc.enable_retries", 0),
)
FAILURES = {
    "ACCOUNT_UNAVAILABLE": 503,
    "ACCOUNT_INPUT_INVALID": 422,
    "ACCOUNT_PROTOCOL_INVALID": 502,
    "ACCOUNT_DENIED": 404,
    "ACCOUNT_DEADLINE_EXCEEDED": 504,
    "ACCOUNT_UPSTREAM_REJECTED": 502,
    "ACCOUNT_DC_PENDING": 502,
    "CAPABILITY_UNSUPPORTED": 409,
    "CHALLENGE_EXPIRED": 409,
    "RENEWAL_OUTCOME_UNKNOWN": 409,
    "SESSION_BUSY": 409,
    "UNKNOWN_OUTCOME": 504,
    "AUTH_REQUIRED": 401,
    "TOKEN_EXPIRED": 401,
    "FORBIDDEN": 403,
    "RATE_LIMITED": 429,
    "UPSTREAM_TIMEOUT": 504,
}


def failure(code: str) -> AccountFailure:
    safe = code if code in FAILURES else "ACCOUNT_UNAVAILABLE"
    return AccountFailure(safe, FAILURES[safe])


def encode_input(body: AccountLogin | ImageCheckRequest | AccountRefresh) -> bytes:
    # Only entering credentials. Never recursively serialize arbitrary SecretStr.
    value = body.model_dump(mode="json")
    if type(body) is AccountLogin:
        for name in ("account", "secret", "image_code", "second_code"):
            secret = getattr(body, name)
            value[name] = secret.get_secret_value() if secret is not None else None
    elif type(body) is ImageCheckRequest:
        value["image_code"] = body.image_code.get_secret_value()
    elif type(body) is not AccountRefresh:
        raise failure("ACCOUNT_INPUT_INVALID")
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise failure("ACCOUNT_INPUT_INVALID")
    return encoded


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise ValueError
        value[name] = item
    return value


def decode_input[T: BaseModel](payload: bytes, model: type[T]) -> T:
    result = None
    try:
        if not 0 < len(payload) <= MAX_REQUEST_BYTES:
            raise ValueError
        value = json.loads(payload, object_pairs_hook=_pairs)
        result = model.model_validate(value)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        pass
    if result is None:
        raise failure("ACCOUNT_INPUT_INVALID") from None
    return cast(T, result)


def reject_unknown(message: Message) -> None:
    clean = type(message)()
    clean.CopyFrom(message)
    clean.DiscardUnknownFields()
    if clean.SerializeToString(deterministic=True) != message.SerializeToString(
        deterministic=True
    ):
        raise failure("ACCOUNT_INPUT_INVALID")


def validate_request(request: Any) -> None:
    reject_unknown(request)
    ctx = request.context
    if ctx.protocol_version != PROTOCOL_VERSION:
        raise failure("ACCOUNT_PROTOCOL_INVALID")
    if (
        request.ByteSize() > MAX_REQUEST_BYTES
        or re.fullmatch(r"[0-9a-f]{64}", ctx.ticket) is None
        or not 1 <= ctx.deadline_ms <= MAX_DEADLINE_MS
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", ctx.correlation_id)
        is None
    ):
        raise failure("ACCOUNT_INPUT_INVALID")


class Budget:
    def __init__(self, milliseconds: int) -> None:
        if type(milliseconds) is not int or not 1 <= milliseconds <= MAX_DEADLINE_MS:
            raise failure("ACCOUNT_INPUT_INVALID")
        self.end = time.monotonic() + milliseconds / 1000

    def remaining(self) -> int:
        left = int((self.end - time.monotonic()) * 1000)
        if left < 1:
            raise failure("ACCOUNT_DEADLINE_EXCEEDED")
        return left


def endpoint(value: str, *, bind: bool = False) -> str:
    # Explicit DNS hostname or IP and port only; no arbitrary resolver schemes.
    found = re.fullmatch(
        r"([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9a-fA-F:]+\]):([0-9]{1,5})",
        value,
    )
    if not found or not (0 if bind else 1) <= int(found[2]) <= 65535:
        raise failure("ACCOUNT_UNAVAILABLE")
    return value


def required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value:
        raise failure("ACCOUNT_UNAVAILABLE")
    return value


def pem(path: str) -> bytes:
    value = None
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(65537)
        if 0 < len(data) <= 65536:
            value = data
    except (OSError, ValueError):
        pass
    if value is None:
        raise failure("ACCOUNT_UNAVAILABLE") from None
    return value
