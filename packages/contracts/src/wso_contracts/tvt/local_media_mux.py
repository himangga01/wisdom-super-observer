"""Opaque public wall/focus references; none carries native authority."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from wso_contracts.models import WireModel


class LocalWallView(WireModel):
    id: UUID
    tenant_id: UUID
    expires_at: datetime
    state: Literal["ACTIVE", "STOPPING", "CLOSED"]


class LocalWallResponse(WireModel):
    wall: LocalWallView
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


class LocalFocusRequest(WireModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    direction: Literal["FORWARD", "RETURN"]


class LocalFocusView(WireModel):
    id: UUID
    wall_id: UUID
    lease_id: UUID
    connection_id: UUID
    channel_id: UUID
    direction: Literal["FORWARD", "RETURN"]
    expires_at: datetime
    state: Literal["PENDING", "ACTIVE", "CLOSED"]


class LocalFocusResponse(WireModel):
    reference: LocalFocusView
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


class LocalFocusSettleRequest(WireModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    outcome: Literal["CANCELLED", "FAILED"]
