"""Closed public registration/recovery schemas, not a public API implementation.

APK 1.18.1 evidence: docs/integrations/tvt-account-flows-source.md. Labels,
opaque flow UUIDs and challenge UUID/generation pairs never grant authority.
Protected service/SQL admission must bind them to the current T03 actor,
selection, account and purpose and recheck permissions/consent before EVERY
operation. Browser inputs cannot supply private RSA, idCode or token state.

Passwords implement bounded native BMP input only: exact APK yg3 complexity
equivalence remains unresolved. Six-character final codes select the supported
UI branch; native generic code inputs are broader. Numeric phone limits are
web input policy, not a complete port of country-specific Android UI rules.
Expiry/resend waits are explicit local policy, never vendor TTL evidence.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from wso_contracts.models import WireModel
from wso_contracts.tvt.account import AccountSelection

type FlowPurpose = Literal["register", "recover"]
type AccountMode = Literal["email", "phone"]


type FlowState = Literal[
    "CREATED",
    "EXISTENCE",
    "IMAGE_AVAILABLE",
    "IMAGE_REQUIRED",
    "IMAGE_REJECTED",
    "CODE_SENT",
    "COMPLETE",
    "FAILED",
    "UNKNOWN_OUTCOME",
    "CLOSED",
    "EXPIRED",
]


def _native_secret(value: SecretStr) -> SecretStr:
    text = value.get_secret_value()
    if (
        any(
            ord(char) == 0 or ord(char) > 0xFFFF or 0xD800 <= ord(char) <= 0xDFFF
            for char in text
        )
        or len(text.encode("utf-8")) > 4096
    ):
        raise ValueError("unsupported native input")
    return value


def _uuid_input(value: object) -> object:
    if not isinstance(value, UUID) and type(value) is not str:
        raise ValueError("invalid local reference")
    return value


LocalReference = Annotated[UUID, BeforeValidator(_uuid_input)]
RequestId = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]
NativePassword = Annotated[
    SecretStr,
    Field(strict=True, min_length=1, max_length=4096, repr=False),
    AfterValidator(_native_secret),
]
FinalDynamicCode = Annotated[
    SecretStr,
    Field(strict=True, min_length=6, max_length=6, repr=False),
    AfterValidator(_native_secret),
]
ImageCode = Annotated[
    SecretStr,
    Field(strict=True, min_length=1, max_length=256),
    AfterValidator(_native_secret),
]
Generation = Annotated[StrictInt, Field(ge=1, le=2**31 - 1)]
LocalExpiry = Annotated[StrictInt, Field(ge=1, le=86400)]
LocalResendWait = Annotated[StrictInt, Field(ge=0, le=3600)]
type FlowErrorCode = Literal[
    "ACCOUNT_INPUT_INVALID",
    "ACCOUNT_SCOPE_INVALID",
    "ACCOUNT_PROTOCOL_INVALID",
    "ACCOUNT_TRANSPORT_FAILED",
    "ACCOUNT_DEADLINE_EXCEEDED",
    "ACCOUNT_CANCELLED",
    "ACCOUNT_UNAVAILABLE",
    "ACCOUNT_QUARANTINED",
    "ACCOUNT_UPSTREAM_REJECTED",
    "ACCOUNT_DC_PENDING",
    "FLOW_CLOSED",
    "FLOW_EXPIRED",
    "FLOW_CONSUMED",
    "FLOW_KEY_MISSING",
    "FLOW_PURPOSE_INVALID",
    "FLOW_IMAGE_MISSING",
    "FLOW_RATE_LIMITED",
]


class _FlowSelection(AccountSelection):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, revalidate_instances="always"
    )
    purpose: FlowPurpose


class AccountFlowStart(_FlowSelection):
    mode: AccountMode
    account: Annotated[
        SecretStr,
        Field(strict=True, min_length=1, max_length=512, repr=False),
        AfterValidator(_native_secret),
    ]
    country_code: Annotated[StrictStr, Field(min_length=1, max_length=4)] | None = None

    @model_validator(mode="after")
    def checked_account(self) -> AccountFlowStart:
        text = self.account.get_secret_value()
        if self.mode == "email":
            # yg3.a, not an RFC mailbox validator; no implicit trim/case folding.
            valid = (
                "country_code" not in self.model_fields_set
                and re.fullmatch(
                    r"[-_.a-zA-Z0-9]+@[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)+", text
                )
                is not None
            )
        else:
            # Bind privately with AccountBinding.phone(country_code, account):
            # APK wire loginName is countryCode + '+' + localNumber.
            valid = (
                self.country_code is not None
                and re.fullmatch(r"[0-9]{1,4}", self.country_code) is not None
                and re.fullmatch(r"[0-9]{1,32}", text) is not None
            )
        if not valid:
            raise ValueError("invalid account input")
        return self


class AccountFlowReference(_FlowSelection):
    """Service-owned lookup selector; the handle is never an admission token."""

    flow_id: LocalReference


class AccountDynamicCodeRequest(AccountFlowReference):
    challenge_id: LocalReference | None = None
    challenge_generation: Generation | None = None
    image_code: ImageCode | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def image_pair(self) -> AccountDynamicCodeRequest:
        present = (
            self.challenge_id is not None,
            self.challenge_generation is not None,
            self.image_code is not None,
        )
        if any(present) and not all(present):
            raise ValueError("incomplete local image reference")
        return self


class AccountRegistrationSubmit(AccountFlowReference):
    purpose: Literal["register"]
    password: NativePassword
    dynamic_code: FinalDynamicCode


class AccountRecoverySubmit(AccountFlowReference):
    purpose: Literal["recover"]
    new_password: NativePassword
    dynamic_code: FinalDynamicCode


class AccountFlowCancel(AccountFlowReference):
    pass


class AccountFlowImage(WireModel):
    """Bounded inert media projection; service must first call project_image.

    Base64 syntax/size checks do not validate JPEG/PNG content or prove upstream
    challenge provenance. The service assigns local challenge references and
    generations; caller values cannot supply or replace native idCode state.
    """

    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, revalidate_instances="always"
    )
    challenge_id: LocalReference
    generation: Generation
    media_type: Literal["image/jpeg", "image/png"]
    image_base64: Annotated[
        StrictStr, Field(min_length=4, max_length=90000, repr=False)
    ]

    @field_validator("image_base64")
    @classmethod
    def bounded_base64(cls, value: str) -> str:
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("invalid image projection") from None
        if not 1 <= len(data) <= 65536 or base64.b64encode(data).decode() != value:
            raise ValueError("invalid image projection")
        return value


class AccountFlowView(AccountFlowReference):
    """Safe state projection; no raw responses or identity/session credentials."""

    request_id: RequestId
    state: FlowState
    exists: StrictBool | None = None
    image: AccountFlowImage | None = Field(default=None, repr=False)
    error_code: FlowErrorCode | None = None
    # Explicit policy values supplied by protected service; no default lifetime.
    expires_in_seconds: LocalExpiry | None = None
    resend_wait_seconds: LocalResendWait | None = None
    return_to_login: StrictBool = False
    automatic_retry_permitted: StrictBool = False

    @model_validator(mode="after")
    def consistent_state(self) -> AccountFlowView:
        if (self.state == "COMPLETE") != self.return_to_login:
            raise ValueError("inconsistent completion state")
        if self.automatic_retry_permitted:
            raise ValueError("automatic retry is not permitted")
        if (self.state == "EXISTENCE") != (self.exists is not None):
            raise ValueError("inconsistent existence state")
        image_state = self.state in {
            "IMAGE_AVAILABLE",
            "IMAGE_REQUIRED",
            "IMAGE_REJECTED",
        }
        if image_state != (self.image is not None):
            raise ValueError("inconsistent image state")
        if self.state == "IMAGE_REJECTED" and self.purpose != "register":
            raise ValueError("unsupported recovery image result")
        if self.error_code is not None and self.state not in {
            "FAILED",
            "UNKNOWN_OUTCOME",
            "CLOSED",
            "EXPIRED",
        }:
            raise ValueError("inconsistent failure state")
        return self


class AccountExistenceView(AccountFlowView):
    state: Literal["EXISTENCE"] = "EXISTENCE"
    exists: StrictBool


class AccountImageView(AccountFlowView):
    state: Literal["IMAGE_AVAILABLE", "IMAGE_REQUIRED", "IMAGE_REJECTED"]
    image: AccountFlowImage = Field(repr=False)


class AccountDynamicCodeView(AccountFlowView):
    state: Literal["CODE_SENT", "IMAGE_REQUIRED", "IMAGE_REJECTED"]
    # APK resend UI countdown only, not server code expiry or rate policy.
    ui_resend_countdown_seconds: StrictInt | None = None

    @model_validator(mode="after")
    def countdown(self) -> AccountDynamicCodeView:
        if self.state == "CODE_SENT":
            if "ui_resend_countdown_seconds" not in self.model_fields_set:
                self.ui_resend_countdown_seconds = 120
            if self.ui_resend_countdown_seconds != 120:
                raise ValueError("invalid UI countdown")
        elif self.ui_resend_countdown_seconds is not None:
            raise ValueError("image result has no resend countdown")
        return self


class AccountCompletionView(AccountFlowView):
    state: Literal["COMPLETE"] = "COMPLETE"
    return_to_login: StrictBool = True


class AccountFlowCancelView(AccountFlowView):
    state: Literal["CLOSED"] = "CLOSED"
