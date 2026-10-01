"""Internal event references; raw upstream payloads stay outside this contract."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import model_validator

from wso_contracts.models import WireModel
from wso_contracts.tvt.device import DeviceRef
from wso_contracts.tvt.identity import OpaqueIdentifier, UtcDateTime


class PublicEventKind(StrEnum):
    ALARM = "ALARM"
    CALL = "CALL"
    OPERATION = "OPERATION"
    LEASE_STATE = "LEASE_STATE"


class TvtEvent(WireModel):
    """Unknown subtypes remain opaque; source IDs confer no authority."""

    event_id: UUID
    source_id: OpaqueIdentifier
    device: DeviceRef
    channel: UUID | None = None
    subtype: OpaqueIdentifier
    occurred_at: UtcDateTime
    payload_ref: UUID | None = None

    @model_validator(mode="after")
    def consistent_channel(self) -> Self:
        if (
            self.channel is not None
            and self.device.channel_id is not None
            and self.channel != self.device.channel_id
        ):
            raise ValueError("event channel must match the scoped device channel")
        return self
