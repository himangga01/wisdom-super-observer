"""Local connection selectors and safe inventory; no cloud identity or grant."""

from typing import Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from wso_contracts.models import WireModel
from wso_contracts.tvt.identity import UtcDateTime


class LocalVerifyRequest(WireModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    store_id: UUID
    expected_generation: int = Field(strict=True, ge=1, le=2**53 - 1)


class LocalDeviceRef(WireModel):
    tenant_id: UUID
    actor_user_id: UUID
    connection_id: UUID
    store_id: UUID
    device_id: UUID
    channel_id: UUID | None = None


class LocalChannelView(WireModel):
    id: UUID
    ordinal: int = Field(strict=True, ge=1, le=256)
    label: str = Field(pattern=r"^Channel [1-9][0-9]{0,2}$")

    @model_validator(mode="after")
    def generated_label(self) -> Self:
        if self.label != f"Channel {self.ordinal}":
            raise ValueError("invalid channel label")
        return self


class LocalDeviceView(WireModel):
    connection_id: UUID
    device_id: UUID | None = None
    store_id: UUID
    connection_generation: int = Field(strict=True, ge=1, le=2**53 - 1)
    inventory_revision: int = Field(strict=True, ge=0, le=2**53 - 1)
    inventory_state: Literal["UNAVAILABLE", "AVAILABLE", "STALE"]
    observed_at: UtcDateTime | None = None
    channels: tuple[LocalChannelView, ...] = Field(default=(), max_length=256)
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")

    @model_validator(mode="after")
    def current_inventory(self) -> Self:
        if self.inventory_state == "AVAILABLE":
            if (
                self.device_id is None
                or self.observed_at is None
                or self.inventory_revision < 1
            ):
                raise ValueError("available inventory requires an observation")
        elif self.channels:
            raise ValueError("unavailable inventory cannot expose channels")
        if len({c.id for c in self.channels}) != len(self.channels) or len(
            {c.ordinal for c in self.channels}
        ) != len(self.channels):
            raise ValueError("duplicate channels")
        return self
