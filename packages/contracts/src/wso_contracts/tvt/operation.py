"""Typed internal intent views; persistence and reconciliation belong to services."""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, TypeAdapter, model_validator

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


class BusinessIntent(WireModel):
    """Actor and tenant are deliberately absent: protected SQL supplies them."""

    identity_id: UUID
    domain: str

    def business_parts(self) -> tuple[object, ...]:
        raise NotImplementedError

    def business_key(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.business_parts(), default=str, separators=(",", ":")
            ).encode()
        ).hexdigest()

    def payload_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()

    def job_kind(self) -> str:
        if self.domain == "TYCO":
            return "TYCO_OPERATION"
        return (
            "TVT_DEVICE_OPERATION"
            if getattr(self, "device_id", None)
            else "TVT_ACCOUNT_OPERATION"
        )


class PaymentIntent(BusinessIntent):
    kind: Literal["payment"]
    domain: Literal["TVT"]
    product: IntentLabel
    term: IntentLabel
    quoted_price_version: IntentLabel
    device_id: UUID | None = None
    channel_id: UUID | None = None
    store_id: UUID | None = None

    @model_validator(mode="after")
    def scoped(self) -> Self:
        if (self.device_id is None) != (self.store_id is None) or (
            self.channel_id and not self.device_id
        ):
            raise ValueError("device and store scope required together")
        return self

    def business_parts(self) -> tuple[object, ...]:
        return (
            self.kind,
            self.identity_id,
            self.product,
            self.device_id,
            self.channel_id,
            self.term,
            self.quoted_price_version,
        )


class FirmwareIntent(BusinessIntent):
    kind: Literal["firmware"]
    domain: Literal["TVT"]
    device_id: UUID
    store_id: UUID
    target_version: IntentLabel

    def business_parts(self) -> tuple[object, ...]:
        return (self.kind, self.identity_id, self.device_id, self.target_version)


class TycoIntent(BusinessIntent):
    kind: Literal["tyco"]
    domain: Literal["TYCO"]
    panel_id: UUID
    action: Literal["unlock", "relay", "arm", "disarm"]
    target: IntentLabel
    requested_state: IntentLabel

    def business_parts(self) -> tuple[object, ...]:
        return (
            self.kind,
            self.identity_id,
            self.panel_id,
            self.action,
            self.target,
            self.requested_state,
        )


class DeleteIntent(BusinessIntent):
    kind: Literal["delete"]
    domain: Literal["TVT", "TYCO"]
    target_kind: Literal["account", "device", "panel"]
    target_id: UUID
    device_id: UUID | None = None
    store_id: UUID | None = None
    panel_id: UUID | None = None

    @model_validator(mode="after")
    def exact_target(self) -> Self:
        valid = False
        if self.target_kind == "account":
            valid = self.target_id == self.identity_id and not any(
                (self.device_id, self.store_id, self.panel_id)
            )
        elif self.target_kind == "device":
            valid = (
                self.domain == "TVT"
                and self.device_id == self.target_id
                and self.store_id is not None
                and self.panel_id is None
            )
        elif self.target_kind == "panel":
            valid = (
                self.domain == "TYCO"
                and self.panel_id == self.target_id
                and self.device_id is None
                and self.store_id is None
            )
        if not valid:
            raise ValueError("delete target must exactly match scope")
        return self

    def business_parts(self) -> tuple[object, ...]:
        return (
            self.kind,
            self.domain,
            self.identity_id,
            self.target_kind,
            self.target_id,
        )


OperationIntent = Annotated[
    PaymentIntent | FirmwareIntent | TycoIntent | DeleteIntent,
    Field(discriminator="kind"),
]
_INTENT: TypeAdapter[PaymentIntent | FirmwareIntent | TycoIntent | DeleteIntent] = (
    TypeAdapter(OperationIntent)
)


def parse_intent(
    value: object,
) -> PaymentIntent | FirmwareIntent | TycoIntent | DeleteIntent:
    if isinstance(value, BusinessIntent):
        value = value.model_dump()
    return _INTENT.validate_python(value)


class OperationJobPayload(WireModel):
    schema_version: Literal[1] = 1
    operation_id: UUID
