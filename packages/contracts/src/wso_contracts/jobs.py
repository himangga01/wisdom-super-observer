"""Versioned, secret-free wire contracts for durable jobs."""

import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, StrictInt, field_validator

from wso_contracts.models import JobScope, WireModel

POSTGRES_BIGINT_MAX = 2**63 - 1
MAX_JOB_JSON_BYTES = 64 * 1024
JobState = Literal[
    "QUEUED",
    "RUNNING",
    "SUCCEEDED",
    "PARTIAL",
    "FAILED",
    "NEEDS_USER_INPUT",
    "CANCELLED",
]


class _Versioned(WireModel):
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("unsupported job schema version")
        return value


class ImportJobPayload(_Versioned):
    """Prerequisite references; the intake handler belongs to its domain task."""

    import_id: UUID
    connection_id: UUID | None = None


class RegistrationJobPayload(_Versioned):
    registration_id: UUID
    connection_id: UUID


class DispatchReference(_Versioned):
    job_id: UUID
    outbox_id: UUID
    tenant_id: UUID
    kind: str = Field(min_length=1, max_length=100)
    lease_generation: StrictInt = Field(ge=1, le=POSTGRES_BIGINT_MAX)


class _JobOutcome(WireModel):
    state: JobState
    failure_code: str | None = Field(default=None, min_length=1, max_length=100)
    result: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("result")
    @classmethod
    def bounded_json(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > MAX_JOB_JSON_BYTES:
            raise ValueError("job result is too large")
        return value


class JobView(_JobOutcome):
    id: UUID
    scope: JobScope
    kind: str = Field(min_length=1, max_length=100)
    attempts: StrictInt = Field(ge=0, le=POSTGRES_BIGINT_MAX)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    heartbeat_at: AwareDatetime | None = None
    cancel_requested_at: AwareDatetime | None = None

    @field_validator("created_at", "updated_at", "heartbeat_at", "cancel_requested_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class JobItemView(_JobOutcome):
    item_key: str = Field(min_length=1, max_length=200)
