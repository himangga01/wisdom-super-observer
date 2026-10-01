"""Internal cloud recording references with consistent device ownership."""

from typing import Self
from uuid import UUID

from pydantic import model_validator

from wso_contracts.models import WireModel
from wso_contracts.tvt.device import DeviceRef
from wso_contracts.tvt.identity import OpaqueIdentifier, TvtIdentityRef, UtcDateTime


class CloudRecordRef(WireModel):
    identity: TvtIdentityRef
    device: DeviceRef
    channel: UUID | None = None
    upstream_record_id: OpaqueIdentifier
    starts_at: UtcDateTime
    ends_at: UtcDateTime

    @model_validator(mode="after")
    def consistent_scope_and_interval(self) -> Self:
        if self.identity != self.device.identity:
            raise ValueError(
                "cloud identity must match device tenant, actor and identity"
            )
        if (
            self.device.channel_id is not None
            and self.channel != self.device.channel_id
        ):
            raise ValueError("cloud channel must match the scoped device channel")
        if self.ends_at < self.starts_at:
            raise ValueError("record interval cannot end before it starts")
        return self
