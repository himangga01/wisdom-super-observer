"""Safe local live selectors; construction alone grants no media authority."""

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from wso_contracts.models import WireModel


class LocalLiveRequest(WireModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    store_id: UUID
    device_id: UUID
    channel_id: UUID
    expected_generation: int = Field(strict=True, ge=1, le=2**53 - 1)
    inventory_revision: int = Field(strict=True, ge=1, le=2**53 - 1)
    stream: Literal["main", "sub"] = "main"
    wall_id: UUID | None = None
    focus_ref_id: UUID | None = None


from wso_contracts.tvt.media import LocalMediaOwnerRef, MediaLease  # noqa: F401


class LocalLiveResponse(WireModel):
    lease: MediaLease
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


class LocalLiveOfferRequest(WireModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal["offer"] = "offer"
    sdp: str = Field(strict=True, min_length=1, max_length=131072)
    offer_id: UUID


class LocalLiveOfferResponse(WireModel):
    type: Literal["answer"] = "answer"
    sdp: str = Field(strict=True, min_length=1, max_length=131072)
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


class LocalLiveStartedRequest(WireModel):
    """Browser observation; neither this counter nor construction grants live."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    decoded_frames: int = Field(strict=True, ge=1, le=2**53 - 1)
