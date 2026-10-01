"""Public startup DTOs; independent from private TVT transport and credentials."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, StrictStr, field_validator

from wso_contracts.models import WireModel

Locale = Annotated[
    StrictStr, Field(pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$", max_length=35)
]
Version = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")]


class PreferenceUpdate(WireModel):
    locale: Locale
    timezone: Annotated[StrictStr, Field(min_length=1, max_length=64)]

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown IANA timezone") from exc
        return value


class ConsentUpdate(WireModel):
    version: Version
    decision: Literal["accepted", "declined"]


class PolicyReference(WireModel):
    source_reference: Literal[
        "agreement/ServiceTerms_en.html",
        "agreement/PrivacyStatement_en.html",
        "agreement/ServiceTerms_zh-Hans.html",
        "agreement/PrivacyStatement_zh-Hans.html",
    ]
    url: StrictStr


class StartupConsent(WireModel):
    version: Version
    status: Literal["pending", "accepted", "declined"]
    decided_at: datetime | None
    terms: PolicyReference
    privacy: PolicyReference


class StartupAccount(WireModel):
    id: UUID
    brand: StrictStr
    region: StrictStr


class StartupIdentity(WireModel):
    state: Literal["unlinked", "linked"]
    accounts: list[StartupAccount]


class StartupMenuEntry(WireModel):
    id: Literal["local-settings"]
    label: Literal["Settings"]
    path: Literal["/tvt/settings"]


class StartupBootstrap(WireModel):
    selected_tenant_id: UUID
    profile_id: Version
    brand: Literal["SuperLivePlus"]
    region: Version
    locale: Locale
    timezone: StrictStr
    supported_locales: list[Locale]
    consent: StartupConsent
    identity: StartupIdentity
    menu: list[StartupMenuEntry]


class StartupErrorDetails(WireModel):
    code: str
    message: str


class StartupErrorEnvelope(WireModel):
    error: StartupErrorDetails
    request_id: str
