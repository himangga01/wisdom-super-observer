from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantScope(WireModel):
    scope_kind: Literal["TENANT"] = "TENANT"
    tenant_id: UUID


class StoreScope(WireModel):
    scope_kind: Literal["STORE"] = "STORE"
    tenant_id: UUID
    store_id: UUID


JobScope = Annotated[TenantScope | StoreScope, Field(discriminator="scope_kind")]


class Money(WireModel):
    amount_minor: int = Field(ge=0)
    currency: Literal["KRW"] = "KRW"


class SignedMoney(WireModel):
    amount_minor: int
    currency: Literal["KRW"] = "KRW"


class VariantOption(WireModel):
    name: str
    value: str


class ProductCandidate(WireModel):
    id: UUID
    tenant_id: UUID
    revision: int = Field(ge=1)
    barcode: str | None
    name: str | None
    purchase_price: Money | None
    sale_price: Money | None
    variant_options: list[VariantOption] = Field(default_factory=list)
    sellable_unit: str | None = None
    pack_quantity: int | None = Field(default=None, ge=1)
    purchase_price_basis: Literal["PER_PACK", "PER_SELLABLE_UNIT", "UNKNOWN"] = (
        "UNKNOWN"
    )
    sale_price_basis: Literal["PER_SELLABLE_UNIT", "UNKNOWN"] = "UNKNOWN"
    purchase_tax_basis: Literal["INCLUSIVE", "EXCLUSIVE", "EXEMPT", "UNKNOWN"] = (
        "UNKNOWN"
    )
    sale_tax_basis: Literal["INCLUSIVE", "EXCLUSIVE", "EXEMPT", "UNKNOWN"] = "UNKNOWN"
    registration_schema_id: str | None = None
    registration_fields: dict[str, StrictStr | StrictInt | StrictBool] = Field(
        default_factory=dict
    )
    source_kind: Literal["TEXT", "PHOTO", "PRODUCT_PAGE", "ORDER_HISTORY"]
    source_ref: str
    confidence: float = Field(ge=0, le=1)
    errors: list[str]


class EventEnvelope(WireModel):
    event_id: UUID
    event_type: str
    schema_version: Literal[1] = 1
    tenant_id: UUID
    store_id: UUID | None
    occurred_at: datetime
    correlation_id: UUID
    payload: dict[str, object]


class IncidentSummary(WireModel):
    incident_id: UUID
    verdict: Literal["SUPPORTED", "UNCERTAIN", "NOT_SUPPORTED"]
    summary_ko: str
    visible_person_count: int | None = Field(ge=0)
    observed_actions: list[str]
    uncertainty_reasons: list[str]
    evidence_ids: list[UUID]
    suggested_warning_ko: str | None = None
