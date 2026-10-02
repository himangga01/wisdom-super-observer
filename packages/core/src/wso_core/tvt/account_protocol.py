"""Private, source-derived account JSON; live server acceptance is unverified.

Evidence: SuperLive Plus 1.18.1 arm64 userLogin (0x329fd4), createPostJson
(0x2cc3f0), getTokenFromJson (0x2d2cd0), and the W04 report addendum.
JNI encoding for NUL/non-BMP inputs is unverified: reject instead of guessing.
No browser DTO, signing extension, expiry inference, or token persistence here.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

type JsonValue = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
MAX_BODY_BYTES = 1_048_576
MAX_STRING_BYTES = 4096
MAX_NATIVE_INT = 2**31 - 1
KNOWN_PATHS = frozenset(
    {
        "/user/login",
        "/user/img-code/get",
        "/user/img-code/check",
        "/user/sms-code/get",
        "/user/sms-code/no-token/get",
        "/user/info/get",
        "/user/token/renewal",
        "/user/logout",
        "/user/info/phone/is-exist",
        "/user/info/email/is-exist",
        "/user/register",
        "/user/info/password/reset",
    }
)


class AccountProtocolError(ValueError):
    """Fixed messages only; upstream bytes and credential values are private."""


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise AccountProtocolError("Invalid account protocol input.")
    return value


def _text(value: object, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise AccountProtocolError("Invalid account protocol input.")
    if (
        any(
            ord(char) == 0 or 0xD800 <= ord(char) <= 0xDFFF or ord(char) > 0xFFFF
            for char in value
        )
        or len(value.encode("utf-8")) > MAX_STRING_BYTES
    ):
        raise AccountProtocolError("Invalid account protocol input.")
    return value


def _body_bound(value: object) -> int:
    return _integer(value, 1, MAX_BODY_BYTES)


class TaskIdAllocator(Protocol):
    def next_id(self) -> str: ...


class SessionTaskIds:
    """Inject one allocator per session; native task-ID width is bounded here."""

    def __init__(self, *, start: int = 1) -> None:
        self._next = _integer(start, 1, MAX_NATIVE_INT)
        self._lock = threading.Lock()

    def next_id(self) -> str:
        with self._lock:
            value = _integer(self._next, 1, MAX_NATIVE_INT)
            self._next += 1
            return str(value)


def secure_nonce() -> int:
    """Nine decimal digits, first nonzero; use OS entropy rather than APK rand."""
    return 100_000_000 + secrets.randbelow(900_000_000)


def _unix_seconds() -> int:
    return int(time.time())


@dataclass(frozen=True, slots=True, repr=False)
class LoginInput:
    login_type: int
    account: str
    password: str
    uuid: str
    language: str
    app_version: str
    country: str
    image_id: str = ""
    image_code: str = ""
    customer_app_id: str = ""
    customer_mark: str = ""
    terminal_id: str = ""
    double_check_code: str = ""


@dataclass(frozen=True, slots=True, repr=False)
class SmsChallengeInput:
    login_name: str
    login_type: int
    business_type: int
    language: str
    image_id: str = ""
    image_code: str = ""
    customer_app_id: str = ""
    customer_mark: str = ""


@dataclass(frozen=True, slots=True)
class AccountRequest:
    path: str = field(repr=False)
    body: bytes = field(repr=False)


def _proof(account: str, value: str, nonce: int, timestamp: int) -> str:
    digest = hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()
    source = f"{nonce}#{timestamp}#{account}#{digest}".encode()
    return hashlib.sha512(source).hexdigest()


class AccountProtocol:
    def __init__(
        self,
        *,
        task_ids: TaskIdAllocator,
        clock: Callable[[], int] = _unix_seconds,
        nonce: Callable[[], int] = secure_nonce,
    ) -> None:
        self._task_ids = task_ids
        self._clock = clock
        self._nonce = nonce

    def _basic(self, *, version: str = "1.0", token: str = "") -> dict[str, JsonValue]:
        token = _text(token)
        timestamp = _integer(self._clock(), 0, 2**63 - 1)
        nonce = _integer(self._nonce(), 100_000_000, 999_999_999)
        task_id = _text(self._task_ids.next_id(), nonempty=True)
        if not task_id.isascii() or not task_id.isdecimal() or len(task_id) > 10:
            raise AccountProtocolError("Invalid account protocol input.")
        if str(_integer(int(task_id), 1, MAX_NATIVE_INT)) != task_id:
            raise AccountProtocolError("Invalid account protocol input.")
        basic: dict[str, JsonValue] = {"ver": version, "id": task_id}
        if token:
            basic["token"] = token
        basic.update(time=timestamp, nonce=nonce)
        return basic

    @staticmethod
    def _request(
        path: str, basic: dict[str, JsonValue], data: dict[str, JsonValue] | None = None
    ) -> AccountRequest:
        envelope: dict[str, JsonValue] = {"basic": basic}
        if data:
            envelope["data"] = data
        body = json.dumps(
            envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(body) > MAX_BODY_BYTES:
            raise AccountProtocolError("Invalid account protocol input.")
        return AccountRequest(path, body)

    def login(self, credentials: LoginInput) -> AccountRequest:
        account = _text(credentials.account)
        password = _text(credentials.password)
        uuid = _text(credentials.uuid)
        login_type = _integer(credentials.login_type, -(2**31), MAX_NATIVE_INT)
        data: dict[str, JsonValue] = {
            "type": login_type,
            "userName": account,
            "lang": _text(credentials.language),
            "appVersion": _text(credentials.app_version),
            "country": _text(credentials.country),
        }
        image_code, image_id = (
            _text(credentials.image_code),
            _text(credentials.image_id),
        )
        if image_code:
            data.update(idCode=image_id, imgCode=image_code)
        for key, value in (
            ("customerAppId", credentials.customer_app_id),
            ("customerMark", credentials.customer_mark),
            ("terminalId", credentials.terminal_id),
            ("doubleCheckCode", credentials.double_check_code),
        ):
            text = _text(value)
            if text:
                data[key] = text
        basic = self._basic(version="1.1")
        timestamp, nonce = cast(int, basic["time"]), cast(int, basic["nonce"])
        data["password"] = _proof(account, password, nonce, timestamp)
        data["uuid"] = _proof(account, uuid, nonce, timestamp)
        return self._request("/user/login", basic, data)

    def _prelogin_request(
        self,
        path: str,
        data: dict[str, JsonValue],
        *,
        version: str = "1.0",
        sign: str = "",
    ) -> AccountRequest:
        """Private shared envelope helper; token is deliberately unavailable."""
        basic = self._basic(version=version)
        if sign:
            basic["sign"] = sign
        return self._request(path, basic, data)

    def image_challenge(self, *, customer_app_id: str = "") -> AccountRequest:
        data: dict[str, JsonValue] = {}
        customer = _text(customer_app_id)
        if customer:
            data["customerAppId"] = customer
        return self._request("/user/img-code/get", self._basic(), data)

    def check_image(
        self, image_id: str, image_code: str, *, customer_app_id: str = ""
    ) -> AccountRequest:
        data: dict[str, JsonValue] = {
            "idCode": _text(image_id),
            "imgCode": _text(image_code),
        }
        customer = _text(customer_app_id)
        if customer:
            data["customerAppId"] = customer
        return self._request("/user/img-code/check", self._basic(), data)

    def sms_challenge(
        self, challenge: SmsChallengeInput, *, token: str = ""
    ) -> AccountRequest:
        business = _integer(challenge.business_type, 1, 16)
        if business not in (1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 16):
            raise AccountProtocolError("Invalid account protocol input.")
        data: dict[str, JsonValue] = {
            "loginName": _text(challenge.login_name),
            "loginType": _integer(challenge.login_type, -(2**31), MAX_NATIVE_INT),
            "businessType": business,
            "lang": _text(challenge.language),
        }
        image_id, image_code = _text(challenge.image_id), _text(challenge.image_code)
        if image_code:
            data.update(idCode=image_id, imgCode=image_code)
        for key, value in (
            ("customerAppId", challenge.customer_app_id),
            ("customerMark", challenge.customer_mark),
        ):
            text = _text(value)
            if text:
                data[key] = text
        path = "/user/sms-code/get" if business <= 5 else "/user/sms-code/no-token/get"
        return self._request(path, self._basic(token=token), data)

    def profile(self, token: str) -> AccountRequest:
        return self._request(
            "/user/info/get", self._basic(token=_text(token, nonempty=True))
        )

    def renew(self, token: str) -> AccountRequest:
        return self._request(
            "/user/token/renewal",
            self._basic(version="1.1", token=_text(token, nonempty=True)),
        )

    def logout(self, token: str) -> AccountRequest:
        return self._request(
            "/user/logout", self._basic(token=_text(token, nonempty=True))
        )


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _no_constant(value: str) -> JsonValue:
    raise ValueError


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError
    return number


def private_json(body: bytes) -> dict[str, JsonValue]:
    """Internal parser only. Do not pass this unnormalized object to public DTOs."""
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_no_constant,
            parse_float=_finite_float,
        )
        if not isinstance(value, dict):
            raise TypeError
        return cast(dict[str, JsonValue], value)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        pass
    # Raising after the except block discards JSONDecodeError.doc as well as
    # suppressing its display; `from None` inside the handler would retain it.
    raise AccountProtocolError("Invalid account response.") from None


@dataclass(frozen=True, slots=True)
class AccountResponse:
    http_status: int
    native_msgcode: int
    private_body: bytes = field(repr=False)

    def require_success(self) -> None:
        if not 200 <= self.http_status <= 299 or self.native_msgcode != 200:
            raise AccountProtocolError("Account operation did not succeed.")


def parse_response(
    http_status: int, body: bytes, *, max_body_bytes: int = MAX_BODY_BYTES
) -> AccountResponse:
    try:
        bound, status = _body_bound(max_body_bytes), _integer(http_status, 100, 599)
        if not isinstance(body, bytes) or len(body) > bound:
            raise ValueError
        basic = private_json(body).get("basic")
        if not isinstance(basic, dict):
            raise TypeError
        msgcode = _integer(basic.get("msgcode"), -(2**31), MAX_NATIVE_INT)
        return AccountResponse(status, msgcode, body)
    except (ValueError, TypeError):
        pass
    raise AccountProtocolError("Invalid account response.") from None


@dataclass(frozen=True, slots=True)
class LoginResult:
    token: str = field(repr=False)
    p2p_token: str = field(repr=False)


def parse_login(response: AccountResponse) -> LoginResult:
    response.require_success()
    try:
        data = private_json(response.private_body).get("data")
        if not isinstance(data, dict):
            raise TypeError
        token, p2p = (
            _text(data.get("token"), nonempty=True),
            _text(data.get("p2pId", "")),
        )
        if not p2p:
            p2p = _text(data.get("tid", ""))
        return LoginResult(token, p2p)
    except (ValueError, TypeError):
        pass
    raise AccountProtocolError("Invalid account login response.") from None
