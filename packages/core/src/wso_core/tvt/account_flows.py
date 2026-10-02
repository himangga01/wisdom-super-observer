"""Private APK-derived prelogin flows; runtime interoperability is unverified.

Scope equality is consistency only. Protected service admission must precede
construction/use. Each instance binds one actor/tenant/region/brand/account/
mode/purpose. Runtime keys enter only from its own admitted precursor replies.
Local expiry and final-submit consumption are service policy, not server TTL
or idempotency. No credentials, temporary code MD5 or session are persisted.
"""

from __future__ import annotations

import base64
import hashlib
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from wso_contracts.tvt.identity import AccountScope

from .account_client import AccountClient, _correlation, _scope
from .account_protocol import (
    AccountProtocol,
    AccountProtocolError,
    AccountRequest,
    AccountResponse,
    JsonValue,
    _text,
    private_json,
)
from .account_transport import OriginPolicy
from .ports import AccountChallenge, AccountClientError, AccountDc, AccountErrorCode


class AccountMode(IntEnum):
    PHONE = 1
    EMAIL = 2


class FlowPurpose(IntEnum):
    REGISTER = 15
    RECOVER = 12


class FlowState(StrEnum):
    EXISTENCE = "EXISTENCE"
    IMAGE_AVAILABLE = "IMAGE_AVAILABLE"
    CODE_SENT = "CODE_SENT"
    IMAGE_REQUIRED = "IMAGE_REQUIRED"
    IMAGE_REJECTED = "IMAGE_REJECTED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


class FlowError(ValueError):
    """Closed local failures; no account/key/code/password in exception state."""

    def __init__(self, code: str) -> None:
        if code not in {
            "FLOW_CLOSED",
            "FLOW_EXPIRED",
            "FLOW_CONSUMED",
            "FLOW_KEY_MISSING",
            "FLOW_PURPOSE_INVALID",
            "FLOW_IMAGE_MISSING",
            "FLOW_RATE_LIMITED",
        }:
            code = "FLOW_CLOSED"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class AccountBinding:
    mode: AccountMode
    account: str

    @classmethod
    def phone(cls, country_code: str, local_number: str) -> AccountBinding:
        country = _text(country_code, nonempty=True)
        number = _text(local_number, nonempty=True)
        return cls(AccountMode.PHONE, _text(country + "+" + number, nonempty=True))


@dataclass(frozen=True, slots=True)
class FlowResult:
    state: FlowState
    correlation_id: str
    http_status: int | None = None
    native_msgcode: int | None = None
    error_code: AccountErrorCode | None = None
    exists: bool | None = None
    challenge: AccountChallenge | None = field(default=None, repr=False)
    dc: AccountDc | None = field(default=None, repr=False)
    private_body: bytes = field(default=b"", repr=False)

    @property
    def return_to_login(self) -> bool:
        return (
            self.state is FlowState.COMPLETE
            and self.http_status is not None
            and 200 <= self.http_status <= 299
            and self.native_msgcode == 200
            and self.error_code is None
        )


@dataclass(frozen=True, slots=True, repr=False)
class _Decoded:
    state: FlowState
    exists: bool | None = None
    challenge: AccountChallenge | None = None
    key: rsa.RSAPublicKey | None = None
    image_id: str | None = None
    private_body: bytes = b""


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def _key(value: JsonValue) -> rsa.RSAPublicKey:
    checked: rsa.RSAPublicKey | None = None
    try:
        if type(value) is not str or not 1 <= len(value) <= 8192:
            raise ValueError
        der = base64.b64decode(value, validate=True)
        if len(der) > 4096 or base64.b64encode(der).decode("ascii") != value:
            raise ValueError
        parsed = serialization.load_der_public_key(der)
        if not isinstance(parsed, rsa.RSAPublicKey):
            raise TypeError
        # Canonical SPKI comparison rejects PKCS1, trailing data and private keys.
        if (
            parsed.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            != der
        ):
            raise ValueError
        checked = parsed
    except Exception:  # noqa: BLE001 -- discard key parser's private context
        checked = None
    if checked is None:
        raise AccountProtocolError("Invalid account response.") from None
    return checked


def _data(response: AccountResponse, *, required: bool = False) -> dict[str, JsonValue]:
    value = private_json(response.private_body).get("data")
    if value is None and not required:
        return {}
    if type(value) is not dict:
        raise AccountProtocolError("Invalid account response.")
    return value


def _response_text(data: dict[str, JsonValue], name: str) -> str | None:
    return _text(data[name]) if name in data else None


class PreloginAccountFlow:
    def __init__(
        self,
        scope: AccountScope,
        binding: AccountBinding,
        purpose: FlowPurpose,
        policy: OriginPolicy,
        *,
        origin: str,
        protocol: AccountProtocol | None = None,
        language: str = "en",
        country: str = "",
        customer_app_id: str = "",
        default_domain: str = "",
        terminal_id: str = "",
        lifetime_seconds: float = 300,
        code_interval_seconds: float = 0,
        monotonic: Callable[[], float] = time.monotonic,
        max_body_bytes: int = 65_536,
    ) -> None:
        checked = _scope(scope, AccountScope)
        if checked.identity_id is not None:
            raise AccountClientError(AccountErrorCode.SCOPE_INVALID)
        if (
            type(binding) is not AccountBinding
            or type(binding.mode) is not AccountMode
            or type(purpose) is not FlowPurpose
            or type(lifetime_seconds) not in (int, float)
            or not 0 < lifetime_seconds <= 86400
            or not math.isfinite(lifetime_seconds)
            or type(code_interval_seconds) not in (int, float)
            or not 0 <= code_interval_seconds <= 86400
            or not math.isfinite(code_interval_seconds)
        ):
            raise AccountClientError(AccountErrorCode.INPUT_INVALID)
        invalid = False
        try:
            account = _text(binding.account, nonempty=True)
            language = _text(language, nonempty=True)
            country, customer_app_id, default_domain, terminal_id = (
                _text(v)
                for v in (country, customer_app_id, default_domain, terminal_id)
            )
        except AccountProtocolError:
            invalid = True
        if invalid:
            raise AccountClientError(AccountErrorCode.INPUT_INVALID) from None
        self._scope = checked
        self._binding = AccountBinding(binding.mode, account)
        self._purpose = purpose
        self._language, self._country = language, country
        self._app, self._domain, self._terminal = (
            customer_app_id,
            default_domain,
            terminal_id,
        )
        self._client = AccountClient(
            checked,
            policy,
            origin=origin,
            protocol=protocol,
            max_body_bytes=max_body_bytes,
        )
        self._clock = monotonic
        self._expires = monotonic() + lifetime_seconds
        self._interval = code_interval_seconds
        self._next_code = 0.0
        self._state_lock = threading.Lock()
        self._busy = False
        self._closed = False
        self._consumed = False
        self._generation = 0
        self._rsa: rsa.RSAPublicKey | None = None
        self._image_id: str | None = None

    def _clear(self) -> None:
        self._rsa, self._image_id = None, None
        self._generation += 1

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            self._clear()
        self._client.close()

    def _live(self) -> None:
        if self._closed:
            raise FlowError("FLOW_CLOSED")
        if self._clock() >= self._expires:
            self._clear()
            raise FlowError("FLOW_EXPIRED")
        if self._consumed:
            raise FlowError("FLOW_CONSUMED")

    def _perform(
        self,
        scope: AccountScope,
        operation: str,
        *,
        password: str = "",
        dynamic_code: str = "",
        image_code: str = "",
        deadline_ms: int,
        correlation_id: str,
    ) -> FlowResult:
        correlation = _correlation(correlation_id)
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= 60_000:
            raise AccountClientError(AccountErrorCode.INPUT_INVALID, correlation)
        # This includes local admission/state work in the existing total budget.
        deadline = time.monotonic() + deadline_ms / 1000
        mismatch = False
        try:
            mismatch = _scope(scope, AccountScope) != self._scope
        except AccountClientError:
            mismatch = True
        with self._state_lock:
            if mismatch:
                self._clear()
                raise AccountClientError(
                    AccountErrorCode.SCOPE_INVALID, correlation
                ) from None
            self._live()
            if self._busy:
                raise AccountClientError(AccountErrorCode.UNAVAILABLE, correlation)
            if (
                operation == "register"
                and self._purpose is not FlowPurpose.REGISTER
                or operation == "recover"
                and self._purpose is not FlowPurpose.RECOVER
            ):
                raise FlowError("FLOW_PURPOSE_INVALID")
            if operation == "register" and self._rsa is None:
                raise FlowError("FLOW_KEY_MISSING")
            if operation == "issue_code" and self._clock() < self._next_code:
                raise FlowError("FLOW_RATE_LIMITED")
            generation = self._generation
            self._busy = True
        attempted = False
        failure: AccountClientError | None = None
        result: FlowResult | None = None
        local_failure: str | None = None
        http_status: int | None = None
        native_msgcode: int | None = None
        private_evidence = b""

        def retain_response(response: AccountResponse) -> None:
            nonlocal private_evidence
            private_evidence = response.private_body

        def request() -> AccountRequest:
            nonlocal attempted
            outgoing = self._request(operation, password, dynamic_code, image_code)
            with self._state_lock:
                self._live()
                if generation != self._generation:
                    raise AccountClientError(
                        AccountErrorCode.SCOPE_INVALID, correlation
                    )
                if operation in ("register", "recover"):
                    self._consumed = True
                    self._rsa, self._image_id = None, None
                if operation == "issue_code":
                    self._next_code = self._clock() + self._interval
                attempted = operation in ("issue_code", "register", "recover")
            return outgoing

        try:
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining < 1:
                raise AccountClientError(
                    AccountErrorCode.DEADLINE_EXCEEDED, correlation
                )
            codes = (
                frozenset({200, 1007, 1005})
                if operation == "issue_code"
                else frozenset({200})
            )
            raw = self._client._run(
                lambda: self._client._prelogin(scope),
                request,
                lambda response: self._decode(operation, response),
                deadline_ms=remaining,
                correlation_id=correlation,
                decode_codes=codes,
                response_evidence=retain_response
                if operation == "issue_code"
                else None,
            )
            http_status, native_msgcode = raw.http_status, raw.native_msgcode
            with self._state_lock:
                if self._closed:
                    raise AccountClientError(AccountErrorCode.CANCELLED, correlation)
                if self._clock() >= self._expires:
                    self._clear()
                    local_failure = "FLOW_EXPIRED"
                elif generation != self._generation:
                    raise AccountClientError(
                        AccountErrorCode.SCOPE_INVALID, correlation
                    )
                elif time.monotonic() >= deadline:
                    raise AccountClientError(
                        AccountErrorCode.DEADLINE_EXCEEDED, correlation
                    )
                else:
                    decoded = raw.value
                    if decoded is None or decoded.state is FlowState.FAILED:
                        self._clear()
                        result = FlowResult(
                            FlowState.FAILED,
                            correlation,
                            raw.http_status,
                            raw.native_msgcode,
                            raw.error_code or AccountErrorCode.UPSTREAM_REJECTED,
                            dc=raw.dc,
                            private_body=private_evidence,
                        )
                    else:
                        if operation in ("image", "issue_code"):
                            if decoded.key is not None:
                                self._rsa = decoded.key
                            # A new precursor replaces image state (including absence).
                            self._image_id = decoded.image_id
                        result = FlowResult(
                            decoded.state,
                            correlation,
                            raw.http_status,
                            raw.native_msgcode,
                            exists=decoded.exists,
                            challenge=decoded.challenge,
                            private_body=decoded.private_body,
                        )
        except AccountClientError as error:
            failure = AccountClientError(
                error.code,
                correlation,
                http_status=error.http_status
                if error.http_status is not None
                else http_status,
                native_msgcode=error.native_msgcode
                if error.native_msgcode is not None
                else native_msgcode,
            )
        finally:
            with self._state_lock:
                if failure is not None or local_failure is not None:
                    self._clear()
                    if attempted:
                        # Dispatched or possibly dispatched writes are never replayed.
                        self._consumed = True
                self._busy = False
        if local_failure is not None:
            if attempted:
                return FlowResult(
                    FlowState.UNKNOWN_OUTCOME,
                    correlation,
                    http_status,
                    native_msgcode,
                    error_code=AccountErrorCode.DEADLINE_EXCEEDED,
                    private_body=private_evidence,
                )
            raise FlowError(local_failure) from None
        if failure is not None:
            if attempted:
                return FlowResult(
                    FlowState.UNKNOWN_OUTCOME,
                    correlation,
                    failure.http_status,
                    failure.native_msgcode,
                    failure.code,
                    private_body=private_evidence,
                )
            raise failure from None
        assert result is not None
        return result

    def _request(
        self, operation: str, password: str, code: str, image: str
    ) -> AccountRequest:
        protocol = self._client._protocol
        data: dict[str, JsonValue] = {}
        account, mode = self._binding.account, int(self._binding.mode)
        if operation == "exists":
            path, member = (
                ("/user/info/phone/is-exist", "mobile")
                if mode == 1
                else ("/user/info/email/is-exist", "email")
            )
            data[member] = account
        elif operation == "image":
            path = "/user/img-code/get"
        elif operation == "issue_code":
            path = "/user/sms-code/no-token/get"
            data.update(
                loginName=account,
                loginType=mode,
                businessType=int(self._purpose),
                lang=self._language,
            )
            image = _text(image)
            if image:
                with self._state_lock:
                    image_id = self._image_id
                if not image_id:
                    raise AccountProtocolError("Invalid account protocol input.")
                data.update(idCode=image_id, imgCode=image)
            if self._domain:
                data["customerMark"] = _md5(self._domain)
        else:
            password, code = _text(password, nonempty=True), _text(code, nonempty=True)
            digest = _md5(password)
            if operation == "register":
                with self._state_lock:
                    key = self._rsa
                if key is None:
                    raise AccountProtocolError("Invalid account protocol input.")
                ciphertext = key.encrypt(digest.encode("ascii"), padding.PKCS1v15())
                data.update(
                    loginName=account,
                    loginType=mode,
                    password=base64.b64encode(ciphertext).decode("ascii"),
                    lang=self._language,
                    customerMark=_md5(self._domain),
                    country=self._country,
                )
                if self._terminal:
                    data["terminalId"] = self._terminal
                if self._app:
                    data["customerAppId"] = self._app
                sign = hashlib.sha512((digest + "#" + code).encode("utf-8")).hexdigest()
                return protocol._prelogin_request(
                    "/user/register", data, version="1.1", sign=sign
                )
            data.update(
                loginName=account,
                dynamicCode=code,
                newPassword=digest,
                lang=self._language,
            )
            if self._domain:
                data["customerMark"] = _md5(self._domain)
            if self._app:
                data["customerAppId"] = self._app
            return protocol._prelogin_request(
                "/user/info/password/reset", data, version="1.1"
            )
        if self._app:
            data["customerAppId"] = self._app
        return protocol._prelogin_request(path, data)

    def _decode(self, operation: str, response: AccountResponse) -> _Decoded:
        if operation == "exists":
            exists = _data(response, required=True).get("isExist")
            if type(exists) is not bool:
                raise AccountProtocolError("Invalid account response.")
            return _Decoded(FlowState.EXISTENCE, exists=exists)
        if operation in ("register", "recover"):
            # Generic token/key members do not establish a session or identity.
            return _Decoded(FlowState.COMPLETE)
        body = private_json(response.private_body)
        if (
            operation == "issue_code"
            and response.native_msgcode != 200
            and (
                type(body.get("data")) is not dict
                or response.native_msgcode == 1005
                and self._purpose is FlowPurpose.RECOVER
            )
        ):
            return _Decoded(FlowState.FAILED)
        data = _data(response)
        key = _key(data["publicKey"]) if "publicKey" in data else None
        name = "imgCodeImgData" if operation == "image" else "imgData"
        challenge = AccountChallenge(
            _response_text(data, "idCode"),
            _response_text(data, name),
            response.private_body,
        )
        state = (
            FlowState.IMAGE_AVAILABLE
            if operation == "image"
            else {
                200: FlowState.CODE_SENT,
                1007: FlowState.IMAGE_REQUIRED,
                1005: FlowState.IMAGE_REJECTED,
            }[response.native_msgcode]
        )
        return _Decoded(
            state,
            challenge=challenge
            if operation == "image" or response.native_msgcode != 200
            else None,
            key=key,
            image_id=challenge.image_id,
            private_body=response.private_body,
        )

    def exists(
        self, scope: AccountScope, *, deadline_ms: int, correlation_id: str
    ) -> FlowResult:
        return self._perform(
            scope, "exists", deadline_ms=deadline_ms, correlation_id=correlation_id
        )

    def image(
        self, scope: AccountScope, *, deadline_ms: int, correlation_id: str
    ) -> FlowResult:
        return self._perform(
            scope, "image", deadline_ms=deadline_ms, correlation_id=correlation_id
        )

    def issue_code(
        self,
        scope: AccountScope,
        *,
        image_code: str = "",
        deadline_ms: int,
        correlation_id: str,
    ) -> FlowResult:
        return self._perform(
            scope,
            "issue_code",
            image_code=image_code,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def register(
        self,
        scope: AccountScope,
        password: str,
        dynamic_code: str,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> FlowResult:
        return self._perform(
            scope,
            "register",
            password=password,
            dynamic_code=dynamic_code,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )

    def recover(
        self,
        scope: AccountScope,
        new_password: str,
        dynamic_code: str,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> FlowResult:
        return self._perform(
            scope,
            "recover",
            password=new_password,
            dynamic_code=dynamic_code,
            deadline_ms=deadline_ms,
            correlation_id=correlation_id,
        )
