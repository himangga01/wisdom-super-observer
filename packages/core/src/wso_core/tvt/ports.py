"""Private account ports, not public DTOs or an authorization mechanism.

The caller derives the actor from protected context and admits postlogin bytes
through W02 CredentialProvider/T04. W05 owns persistence and single-flight
rotation. These objects prove structural consistency only. Future device,
media and event adapters need their own decoded contracts and result types;
this module does not manufacture success or native handles for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from wso_contracts.tvt.identity import AccountScope, TokenKind, TvtIdentityRef

from .account_protocol import LoginInput, SmsChallengeInput


class AccountErrorCode(StrEnum):
    INPUT_INVALID = "ACCOUNT_INPUT_INVALID"
    SCOPE_INVALID = "ACCOUNT_SCOPE_INVALID"
    PROTOCOL_INVALID = "ACCOUNT_PROTOCOL_INVALID"
    TRANSPORT_FAILED = "ACCOUNT_TRANSPORT_FAILED"
    DEADLINE_EXCEEDED = "ACCOUNT_DEADLINE_EXCEEDED"
    CANCELLED = "ACCOUNT_CANCELLED"
    UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
    QUARANTINED = "ACCOUNT_QUARANTINED"
    UPSTREAM_REJECTED = "ACCOUNT_UPSTREAM_REJECTED"
    DC_PENDING = "ACCOUNT_DC_PENDING"


class AccountClientError(ValueError):
    """Fixed adapter codes only; no upstream strings or exception context."""

    def __init__(
        self,
        code: AccountErrorCode,
        correlation_id: str | None = None,
        *,
        http_status: int | None = None,
        native_msgcode: int | None = None,
    ) -> None:
        self.code = code
        self.correlation_id = correlation_id
        self.http_status = http_status
        self.native_msgcode = native_msgcode
        super().__init__(code.value)


@dataclass(frozen=True, slots=True, repr=False)
class PrivateToken:
    identity: TvtIdentityRef
    kind: TokenKind
    value: str


@dataclass(frozen=True, slots=True, repr=False)
class ImageChallenge:
    customer_app_id: str = ""


@dataclass(frozen=True, slots=True, repr=False)
class ImageCheck:
    """Decoded native path; standalone APK UI reachability is unproven."""

    image_id: str
    image_code: str
    customer_app_id: str = ""


type ChallengeInput = ImageChallenge | ImageCheck | SmsChallengeInput


@dataclass(frozen=True, slots=True)
class AccountTokens:
    account_token: str = field(repr=False)
    p2p_token: str = field(repr=False)
    # Original bounded successful reply for private, unbound SID capture only.
    private_body: bytes = field(default=b"", repr=False)


@dataclass(frozen=True, slots=True)
class AccountChallenge:
    image_id: str | None = field(default=None, repr=False)
    # Java ws.java:100 extracts this string. No image encoding is inferred.
    private_image_data: str | None = field(default=None, repr=False)
    private_body: bytes = field(default=b"", repr=False)


@dataclass(frozen=True, slots=True)
class AccountProfile:
    # UserInfoBeanNew/wf2 confirm this optional field; remaining data is opaque.
    user_id: str | None = field(default=None, repr=False)
    private_body: bytes = field(default=b"", repr=False)


@dataclass(frozen=True, slots=True)
class AccountRenewal:
    # Missing tokens mean no observed replacement, never inferred expiration.
    account_token: str | None = field(default=None, repr=False)
    p2p_token: str | None = field(default=None, repr=False)
    private_body: bytes = field(default=b"", repr=False)


@dataclass(frozen=True, slots=True)
class AccountDc:
    origin: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AccountResult[T]:
    http_status: int
    native_msgcode: int
    correlation_id: str
    value: T | None = field(default=None, repr=False)
    error_code: AccountErrorCode | None = None
    dc: AccountDc | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return (
            200 <= self.http_status <= 299
            and self.native_msgcode == 200
            and self.error_code is None
        )


class AccountPort(Protocol):
    """deadline_ms is a relative total budget, integer 1..60000 milliseconds.

    The adapter enforces one inflight request per client. Authority and secret
    admission precede every call; a matching Python scope cannot grant either.
    Tokens/results are private and require a separate reviewed public projection.
    """

    def login(
        self,
        scope: AccountScope,
        credentials: LoginInput,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[AccountTokens]: ...

    def challenge(
        self,
        scope: AccountScope,
        challenge: ChallengeInput,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[AccountChallenge]: ...

    def profile(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[AccountProfile]: ...

    def renew(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[AccountRenewal]: ...

    def logout(
        self,
        scope: TvtIdentityRef,
        token: PrivateToken,
        *,
        deadline_ms: int,
        correlation_id: str,
    ) -> AccountResult[None]: ...

    def close(self) -> None: ...
