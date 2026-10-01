"""Media lifecycle views without worker handles or transport assumptions."""

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from wso_contracts.models import WireModel
from wso_contracts.tvt.device import DeviceRef
from wso_contracts.tvt.identity import TvtIdentityRef, UtcDateTime


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
    owner: TvtIdentityRef
    device: DeviceRef
    channel: UUID | None = None
    kind: Literal["live", "playback", "talk"]
    state: MediaState
    expires_at: UtcDateTime
    heartbeat_at: UtcDateTime

    @model_validator(mode="after")
    def consistent_scope_and_lifetime(self) -> Self:
        if self.owner != self.device.identity:
            raise ValueError("owner must match device tenant, actor and identity")
        if (
            self.device.channel_id is not None
            and self.channel != self.device.channel_id
        ):
            raise ValueError("channel must match the scoped device channel")
        if self.heartbeat_at > self.expires_at:
            raise ValueError("heartbeat cannot occur after lease expiry")
        return self
