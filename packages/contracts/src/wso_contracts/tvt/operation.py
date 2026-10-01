"""Typed internal intent views; persistence and reconciliation belong to services."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from wso_contracts.models import WireModel
from wso_contracts.tvt.device import DeviceRef
from wso_contracts.tvt.identity import OpaqueIdentifier, TvtIdentityRef
from wso_contracts.tvt.tyco import TycoIdentityRef, TycoPanelRef

IntentLabel = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]
PayloadHash = Annotated[
    str,
    StringConstraints(
        strict=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    ),
]


class OperationState(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMING = "CONFIRMING"
    SUBMITTED = "SUBMITTED"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


class TvtAccountTarget(WireModel):
    target_kind: Literal["account"]
    identity: TvtIdentityRef


class TvtDeviceTarget(WireModel):
    target_kind: Literal["device"]
    device: DeviceRef


class TycoAccountTarget(WireModel):
    target_kind: Literal["account"]
    identity: TycoIdentityRef


class TycoPanelTarget(WireModel):
    target_kind: Literal["panel"]
    panel: TycoPanelRef


class TvtOperationTarget(WireModel):
    target_domain: Literal["TVT"]
    target: Annotated[
        TvtAccountTarget | TvtDeviceTarget, Field(discriminator="target_kind")
    ]


class TycoOperationTarget(WireModel):
    target_domain: Literal["TYCO"]
    target: Annotated[
        TycoAccountTarget | TycoPanelTarget, Field(discriminator="target_kind")
    ]


OperationTarget = Annotated[
    TvtOperationTarget | TycoOperationTarget, Field(discriminator="target_domain")
]


class OperationView(WireModel):
    """Internal opaque refs must be projected away by a later public API DTO."""

    intent_id: UUID
    idempotency_key: IntentLabel
    actor_user_id: UUID
    target: OperationTarget
    kind: IntentLabel
    payload_hash: PayloadHash
    state: OperationState
    upstream_ref: OpaqueIdentifier | None = None
    readback_ref: OpaqueIdentifier | None = None

    @model_validator(mode="after")
    def consistent_actor(self) -> Self:
        target = self.target.target
        if isinstance(target, (TvtAccountTarget, TycoAccountTarget)):
            actor_user_id = target.identity.actor_user_id
        elif isinstance(target, TvtDeviceTarget):
            actor_user_id = target.device.identity.actor_user_id
        else:
            actor_user_id = target.panel.identity.actor_user_id
        if self.actor_user_id != actor_user_id:
            raise ValueError("operation actor must match its scoped target identity")
        return self
