"""Device and recording selectors with explicit observed capabilities."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from wso_contracts.models import WireModel
from wso_contracts.tvt.identity import (
    OpaqueIdentifier,
    ScopeLabel,
    TvtIdentityRef,
    UtcDateTime,
)

ObservedName = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[^\x00-\x1f\x7f]*\S[^\x00-\x1f\x7f]*$",
    ),
]


class DeviceState(StrEnum):
    UNKNOWN = "UNKNOWN"
    CONNECTING = "CONNECTING"
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    UNAUTHORIZED = "UNAUTHORIZED"


class DeviceRef(WireModel):
    """A store is mandatory; selectors must later pass server authorization."""

    identity: TvtIdentityRef
    store_id: UUID
    device_id: UUID
    channel_id: UUID | None = None


class RecordRef(WireModel):
    """Internal upstream recording identifier, scoped through its device."""

    device: DeviceRef
    upstream_record_id: OpaqueIdentifier
    source_kind: Literal["local", "cloud"]


class CapabilitySet(WireModel):
    """Flags are observed names, without inferred support or permission."""

    model: ObservedName
    firmware: ObservedName
    flags: tuple[ScopeLabel, ...] = Field(max_length=64)
    source_time: UtcDateTime
