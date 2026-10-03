"""Private fixed USER serializers; structural checks do not grant write authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from .account_protocol import (
    MAX_NATIVE_INT,
    AccountProtocol,
    AccountProtocolError,
    AccountRequest,
    JsonValue,
    SmsChallengeInput,
    _integer,
    _text,
)


@dataclass(frozen=True, slots=True, repr=False)
class ProfileUpdate:
    nickname: str
    account_type: int
    # Explicit empty strings represent the Java constructor's unset members.
    name: str
    address: str


@dataclass(frozen=True, slots=True, repr=False)
class PhoneBind:
    mobile: str
    dynamic_code: str


@dataclass(frozen=True, slots=True, repr=False)
class EmailBind:
    email: str
    dynamic_code: str


@dataclass(frozen=True, slots=True, repr=False)
class PhoneChange:
    old_mobile_code: str
    new_mobile: str
    new_mobile_code: str


@dataclass(frozen=True, slots=True, repr=False)
class EmailChange:
    old_email_code: str
    new_email: str
    new_email_code: str


@dataclass(frozen=True, slots=True, repr=False)
class PasswordUpdate:
    login_type: int
    dynamic_code: str
    raw_password: str


class CodePurpose(IntEnum):
    PASSWORD = 1
    REMOVAL_PREPARATION = 2
    EMAIL = 3
    PHONE = 4


class CodeStage(StrEnum):
    CURRENT = "CURRENT"
    OLD = "OLD"
    NEW = "NEW"


@dataclass(frozen=True, slots=True, repr=False)
class SecurityCode:
    purpose: CodePurpose
    stage: CodeStage
    login_type: int
    account: str
    language: str
    image_id: str = ""
    image_code: str = ""


def _exact[T](value: T, kind: type[T]) -> T:
    if type(value) is not kind:
        raise AccountProtocolError("Invalid security input.")
    return value


class SecurityProtocol:
    def __init__(
        self,
        account: AccountProtocol,
        *,
        customer_app_id: str = "",
        default_domain: str = "",
    ) -> None:
        self._account = _exact(account, AccountProtocol)
        self._app = _text(customer_app_id)
        domain = _text(default_domain)
        self._mark = (
            hashlib.md5(domain.encode("utf-8"), usedforsecurity=False).hexdigest()
            if domain
            else ""
        )

    def _request(
        self, path: str, token: str, data: dict[str, JsonValue] | None = None
    ) -> AccountRequest:
        return self._account._request(
            path, self._account._basic(token=_text(token, nonempty=True)), data
        )

    def update_profile(self, token: str, value: ProfileUpdate) -> AccountRequest:
        _exact(value, ProfileUpdate)
        if value.name != "" or value.address != "":
            raise AccountProtocolError("Invalid security input.")
        data: dict[str, JsonValue] = {
            "nickName": _text(value.nickname),
            "name": _text(value.name),
            "address": _text(value.address),
        }
        kind = _integer(value.account_type, -(2**31), MAX_NATIVE_INT)
        if kind > 0:
            data["type"] = kind
        return self._request("/user/info/update", token, data)

    def bind_phone(self, token: str, value: PhoneBind) -> AccountRequest:
        _exact(value, PhoneBind)
        return self._request(
            "/user/info/phone/bind",
            token,
            {
                "mobile": _text(value.mobile, nonempty=True),
                "dynamicCode": _text(value.dynamic_code, nonempty=True),
            },
        )

    def bind_email(self, token: str, value: EmailBind) -> AccountRequest:
        _exact(value, EmailBind)
        return self._request(
            "/user/info/email/bind",
            token,
            {
                "email": _text(value.email, nonempty=True),
                "dynamicCode": _text(value.dynamic_code, nonempty=True),
            },
        )

    def change_phone(self, token: str, value: PhoneChange) -> AccountRequest:
        _exact(value, PhoneChange)
        return self._request(
            "/user/info/phone/update",
            token,
            {
                "oldMobileCode": _text(value.old_mobile_code, nonempty=True),
                "newMobile": _text(value.new_mobile, nonempty=True),
                "newMobileCode": _text(value.new_mobile_code, nonempty=True),
            },
        )

    def change_email(self, token: str, value: EmailChange) -> AccountRequest:
        _exact(value, EmailChange)
        return self._request(
            "/user/info/email/update",
            token,
            {
                "oldEmailCode": _text(value.old_email_code, nonempty=True),
                "newEmail": _text(value.new_email, nonempty=True),
                "newEmailCode": _text(value.new_email_code, nonempty=True),
            },
        )

    def login_types(self, token: str) -> AccountRequest:
        return self._request("/user/info/login-type/list", token)

    def issue_code(self, token: str, value: SecurityCode) -> AccountRequest:
        _exact(value, SecurityCode)
        purpose = _exact(value.purpose, CodePurpose)
        stage = _exact(value.stage, CodeStage)
        mode = _integer(value.login_type, 1, 2)
        account = _text(value.account)
        if (
            purpose is CodePurpose.EMAIL
            and mode != 2
            or purpose is CodePurpose.PHONE
            and mode != 1
            or purpose in (CodePurpose.EMAIL, CodePurpose.PHONE)
            and stage is CodeStage.CURRENT
            or purpose in (CodePurpose.PASSWORD, CodePurpose.REMOVAL_PREPARATION)
            and stage is not CodeStage.CURRENT
            or stage is CodeStage.NEW
            and not account
            or stage is not CodeStage.NEW
            and account
        ):
            raise AccountProtocolError("Invalid security input.")
        image_id, image_code = _text(value.image_id), _text(value.image_code)
        if image_code and not image_id:
            raise AccountProtocolError("Invalid security input.")
        return self._account.sms_challenge(
            SmsChallengeInput(
                account,
                mode,
                int(purpose),
                _text(value.language),
                image_id,
                image_code,
                self._app,
                self._mark,
            ),
            token=_text(token, nonempty=True),
        )

    def _password(
        self, token: str, value: PasswordUpdate, encrypted: str
    ) -> AccountRequest:
        _exact(value, PasswordUpdate)
        return self._request(
            "/user/info/password/update",
            token,
            {
                "loginType": _integer(value.login_type, -(2**31), MAX_NATIVE_INT),
                "dynamicCode": _text(value.dynamic_code, nonempty=True),
                "newPassword": _text(encrypted, nonempty=True),
            },
        )
