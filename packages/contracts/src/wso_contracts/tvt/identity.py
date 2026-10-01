"""Structural identity selectors; constructing a scope never grants authority."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, StringConstraints

from wso_contracts.models import TenantScope

ScopeLabel = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]
OpaqueIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=1, max_length=256, pattern=r"^[^\x00-\x20\x7f]+$"
    ),
]


def _normalize_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDateTime = Annotated[AwareDatetime, AfterValidator(_normalize_utc)]


class TokenKind(StrEnum):
    USER = "USER"
    P2P = "P2P"
    DEVICE = "DEVICE"


class SessionState(StrEnum):
    NEW = "NEW"
    AUTHENTICATING = "AUTHENTICATING"
    READY = "READY"
    REFRESHING = "REFRESHING"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class AccountScope(TenantScope):
    """Pre-login context; labels do not select arbitrary vendor endpoints."""

    actor_user_id: UUID
    region: ScopeLabel
    brand: ScopeLabel
    identity_id: UUID | None = None


class TvtIdentityRef(TenantScope):
    actor_user_id: UUID
    identity_id: UUID
