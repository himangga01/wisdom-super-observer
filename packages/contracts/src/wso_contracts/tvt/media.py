"""Media lifecycle views without worker handles or transport assumptions."""

from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from wso_contracts.models import WireModel
from wso_contracts.tvt.device import DeviceRef
from wso_contracts.tvt.identity import TvtIdentityRef, UtcDateTime
from wso_contracts.tvt.local_device import LocalDeviceRef


class LocalMediaOwnerRef(WireModel):
    tenant_id: UUID
    actor_user_id: UUID
    connection_id: UUID
    store_id: UUID


class MediaState(StrEnum):
    REQUESTED = "REQUESTED"
    NEGOTIATING = "NEGOTIATING"
    PLAYING = "PLAYING"
    STALLED = "STALLED"
    RECONNECTING = "RECONNECTING"
    STOPPING = "STOPPING"
    CLOSED = "CLOSED"


class TalkState(StrEnum):
    IDLE = "IDLE"
    REQUESTING = "REQUESTING"
    ACTIVE = "ACTIVE"
    BUSY = "BUSY"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


class MediaLease(WireModel):
    id: UUID
    owner: TvtIdentityRef | LocalMediaOwnerRef
    device: DeviceRef | LocalDeviceRef
    channel: UUID | None = None
    kind: Literal["live", "playback", "talk"]
    state: MediaState
    expires_at: UtcDateTime
    heartbeat_at: UtcDateTime
    connection_generation: int | None = Field(
        default=None, strict=True, ge=1, le=2**53 - 1
    )
    inventory_revision: int | None = Field(
        default=None, strict=True, ge=1, le=2**53 - 1
    )
    grant_revision: int | None = Field(default=None, strict=True, ge=1, le=2**53 - 1)

    @model_serializer(mode="wrap")
    def compatible_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        wire: dict[str, Any] = handler(self)
        if isinstance(self.device, DeviceRef):
            for key in (
                "connection_generation",
                "inventory_revision",
                "grant_revision",
            ):
                wire.pop(key, None)
        return wire

    @model_validator(mode="after")
    def consistent_scope_and_lifetime(self) -> Self:
        if isinstance(self.device, LocalDeviceRef):
            if not isinstance(self.owner, LocalMediaOwnerRef) or any(
                getattr(self.owner, key) != getattr(self.device, key)
                for key in ("tenant_id", "actor_user_id", "connection_id", "store_id")
            ):
                raise ValueError("local owner must match the device scope")
            if (
                self.kind != "live"
                or self.channel is None
                or self.device.channel_id is None
                or any(
                    value is None
                    for value in (
                        self.connection_generation,
                        self.inventory_revision,
                        self.grant_revision,
                    )
                )
            ):
                raise ValueError("local live requires a channel and revision fences")
        elif (
            not isinstance(self.owner, TvtIdentityRef)
            or self.owner != self.device.identity
        ):
            raise ValueError("owner must match device tenant, actor and identity")
        if (
            self.device.channel_id is not None
            and self.channel != self.device.channel_id
        ):
            raise ValueError("channel must match the scoped device channel")
        if self.heartbeat_at > self.expires_at:
            raise ValueError("heartbeat cannot occur after lease expiry")
        return self
