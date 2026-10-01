"""Public account contracts. Upstream credentials and identifiers stay private."""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from wso_contracts.models import WireModel
from wso_contracts.tvt.identity import ScopeLabel, SessionState, TokenKind

PrivateText = Annotated[SecretStr, Field(min_length=1, max_length=4096, repr=False)]
VerificationText = Annotated[SecretStr, Field(min_length=1, max_length=256)]


class AccountSelection(WireModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    region: ScopeLabel
    brand: ScopeLabel


class AccountLogin(AccountSelection):
    # Both APK phone and email password presenters call loginMode=1.
    mode: Literal["email", "phone"]
    account: Annotated[SecretStr, Field(min_length=1, max_length=512, repr=False)]
    secret: PrivateText
    challenge_id: UUID | None = None
    image_code: VerificationText | None = Field(default=None, repr=False)
    second_code: VerificationText | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def checked(self) -> "AccountLogin":
        value = self.account.get_secret_value()
        pattern = (
            r"[^\s@]+@[^\s@]+\.[^\s@]+" if self.mode == "email" else r"\+?[0-9]{4,32}"
        )
        if re.fullmatch(pattern, value) is None or (self.challenge_id is None) != (
            self.image_code is None
        ):
            raise ValueError("invalid account input")
        for secret in (self.account, self.secret, self.image_code, self.second_code):
            if secret is not None and any(
                ord(c) == 0 or ord(c) > 0xFFFF or 0xD800 <= ord(c) <= 0xDFFF
                for c in secret.get_secret_value()
            ):
                raise ValueError("unsupported account input")
        return self


class ImageCheckRequest(AccountSelection):
    challenge_id: UUID
    image_code: VerificationText = Field(repr=False)


class AccountRefresh(WireModel):
    kind: TokenKind = TokenKind.USER
    expected_generation: Annotated[StrictInt, Field(ge=1)]
    reason: Literal["manual", "upstream_expired", "reconnect"] = "manual"


class AccountIdentity(WireModel):
    identity_id: UUID
    region: ScopeLabel
    brand: ScopeLabel
    state: SessionState
    generation: Annotated[StrictInt, Field(ge=1)]
    request_id: StrictStr


class AccountProfileFields(WireModel):
    account_type: StrictInt = 0
    user_name: StrictStr = Field(default="", max_length=4096, repr=False)
    nickname: StrictStr = Field(default="", max_length=4096, repr=False)
    email: StrictStr = Field(default="", max_length=4096, repr=False)
    mobile: StrictStr = Field(default="", max_length=4096, repr=False)
    address: StrictStr = Field(default="", max_length=4096, repr=False)
    no_password: StrictBool = False
    avatar_available: StrictBool = False
    # APK image is a private path relative to BaseImageHttpClient. A browser
    # does not receive that path or a server URL. No remote fetch is implied.
    avatar_url: None = None


class AccountProfileView(AccountIdentity):
    profile: AccountProfileFields


class ImageChallengeView(WireModel):
    challenge_id: UUID
    media_type: Literal["image/jpeg", "image/png"]
    image_base64: Annotated[StrictStr, Field(max_length=90000, repr=False)]
    expires_in_seconds: Literal[120] = 120
    request_id: StrictStr


class ImageCheckView(WireModel):
    checked: Literal[True] = True
    request_id: StrictStr


class AccountLogoutView(WireModel):
    identity_id: UUID
    state: Literal["CLOSED"] = "CLOSED"
    upstream_outcome: Literal["confirmed", "unknown", "not_attempted"]
    request_id: StrictStr


class AccountError(WireModel):
    code: StrictStr
    message: StrictStr


class AccountErrorEnvelope(WireModel):
    error: AccountError
    request_id: StrictStr
