"""Validated job requests; database functions own authority and atomic writes."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from wso_contracts.jobs import (
    ImportJobPayload,
    JobItemView,
    JobView,
    RegistrationJobPayload,
)
from wso_contracts.models import JobScope, StoreScope, TenantScope

if TYPE_CHECKING:
    from wso_core.worker import JobStep


class JobFailure(Exception):
    def __init__(self, status: int, code: str = "JOB_REJECTED") -> None:
        self.status, self.code = status, code
        super().__init__("job request failed")


@dataclass(frozen=True)
class JobKind:
    kind: str
    payload_model: type[BaseModel]
    scope_kind: Literal["TENANT", "STORE"]
    permission: str = "OWNER"
    queue: str = "wso.default"
    effect_mode: Literal["LOCAL_ATOMIC", "READ", "EXTERNAL_WRITE"] = "LOCAL_ATOMIC"
    max_attempts: int = 3
    credential_use: bool = False
    handler: Callable[[JobStep], dict[str, Any]] | None = None
    reconcile: Callable[[JobStep], dict[str, Any] | None] | None = None


@dataclass(frozen=True, init=False)
class JobRegistry:
    kinds: Mapping[str, JobKind]

    def __init__(self, kinds: tuple[JobKind, ...]) -> None:
        if len({kind.kind for kind in kinds}) != len(kinds):
            raise ValueError("duplicate job kind")
        object.__setattr__(self, "kinds", MappingProxyType({k.kind: k for k in kinds}))

    def get(self, kind: str) -> JobKind:
        try:
            return self.kinds[kind]
        except KeyError:
            raise JobFailure(422, "UNKNOWN_JOB_KIND") from None

    def validate_database(self, session: Session) -> None:
        definitions = [
            {
                "kind": k.kind,
                "payload_version": 1,
                "scope_kind": k.scope_kind,
                "permission": k.permission,
                "queue": k.queue,
                "effect_mode": k.effect_mode,
                "max_attempts": k.max_attempts,
                "credential_use": k.credential_use,
            }
            for k in self.kinds.values()
        ]
        accepted: bool = session.execute(
            text(
                "SELECT public.wso_validate_job_registry(CAST(:definitions AS jsonb))"
            ),
            {"definitions": json.dumps(definitions)},
        ).scalar_one()
        if not accepted:
            raise JobFailure(503, "REGISTRY_MISMATCH")


DEFAULT_REGISTRY = JobRegistry(
    (
        JobKind(
            "IMPORT",
            ImportJobPayload,
            "TENANT",
            queue="wso.browser",
            effect_mode="READ",
            credential_use=True,
        ),
        JobKind(
            "REGISTRATION",
            RegistrationJobPayload,
            "STORE",
            queue="wso.browser",
            effect_mode="EXTERNAL_WRITE",
            max_attempts=1,
            credential_use=True,
        ),
    )
)


def bounded_json(value: Any) -> str:
    def inspect(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).lower() in {
                    "password",
                    "secret",
                    "credential",
                    "credentials",
                    "token",
                    "lease_token",
                    "capability",
                    "handle",
                    "ciphertext",
                    "presigned_url",
                }:
                    raise JobFailure(422, "INVALID_JOB_DATA")
                inspect(child)
        elif isinstance(item, list):
            for child in item:
                inspect(child)

    inspect(value)
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise JobFailure(422, "INVALID_JOB_DATA") from None
    if len(encoded.encode("utf-8")) > 65536:
        raise JobFailure(422, "INVALID_JOB_DATA")
    return encoded


def db_error(exc: DBAPIError) -> JobFailure:
    return JobFailure(
        {
            "P0002": 404,
            "42501": 403,
            "40001": 409,
            "22023": 422,
            "22P02": 422,
            "23514": 422,
        }.get(getattr(exc.orig, "sqlstate", ""), 503)
    )


def view(row: Mapping[str, Any]) -> JobView:
    scope = (
        TenantScope(tenant_id=row["tenant_id"])
        if row["scope_kind"] == "TENANT"
        else StoreScope(tenant_id=row["tenant_id"], store_id=row["store_id"])
    )
    fields = {
        name: row[name]
        for name in (
            "id",
            "kind",
            "state",
            "attempts",
            "created_at",
            "updated_at",
            "heartbeat_at",
            "cancel_requested_at",
            "failure_code",
        )
    }
    return JobView(scope=scope, result=row["result"] or {}, **fields)


class JobService:
    def __init__(
        self, session: Session, registry: JobRegistry = DEFAULT_REGISTRY
    ) -> None:
        self.session, self.registry = session, registry
        registry.validate_database(session)

    def enqueue(
        self,
        scope: JobScope,
        kind: str,
        payload: BaseModel | dict[str, Any],
        idempotency_key: str,
    ) -> JobView:
        from wso_core.tvt.domain_jobs import DOMAIN_KINDS

        if kind in DOMAIN_KINDS:
            raise JobFailure(403, "CHECKED_OPERATION_REQUIRED")
        definition = self.registry.get(kind)
        if (
            scope.scope_kind != definition.scope_kind
            or not 1 <= len(idempotency_key) <= 200
        ):
            raise JobFailure(422, "INVALID_JOB_SCOPE")
        try:
            validated = definition.payload_model.model_validate(
                payload.model_dump() if isinstance(payload, BaseModel) else payload
            )
        except ValidationError:
            raise JobFailure(422, "INVALID_JOB_PAYLOAD") from None
        data = validated.model_dump(mode="json")
        try:
            job_id: UUID = self.session.execute(
                text(
                    "SELECT public.wso_enqueue_job(:tenant,:scope,:store,:kind,:version,CAST(:payload AS jsonb),:key)"
                ),
                {
                    "tenant": scope.tenant_id,
                    "scope": scope.scope_kind,
                    "store": getattr(scope, "store_id", None),
                    "kind": kind,
                    "version": data.get("schema_version"),
                    "payload": bounded_json(data),
                    "key": idempotency_key,
                },
            ).scalar_one()
        except DBAPIError as exc:
            raise db_error(exc) from None
        return self.get(job_id)

    def get(self, job_id: UUID) -> JobView:
        row = (
            self.session.execute(
                text("SELECT * FROM public.jobs WHERE id=:id"), {"id": job_id}
            )
            .mappings()
            .first()
        )
        if row is None:
            raise JobFailure(404)
        return view(dict(row))

    def cancel(self, job_id: UUID) -> JobView:
        try:
            self.session.execute(
                text("SELECT public.wso_cancel_job(:id)"), {"id": job_id}
            )
        except DBAPIError as exc:
            raise db_error(exc) from None
        return self.get(job_id)

    def items(
        self, job_id: UUID, cursor: str | None = None, limit: int = 50
    ) -> tuple[list[JobItemView], str | None]:
        self.get(job_id)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise JobFailure(422, "INVALID_CURSOR")
        after = ""
        if cursor is not None:
            try:
                if len(cursor) > 1200:
                    raise ValueError()
                decoded = base64.b64decode(
                    cursor, altchars=b"-_", validate=True
                ).decode("utf-8")
                identity, after = decoded.split(":", 1)
                if identity != str(job_id) or not 1 <= len(after) <= 200:
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise JobFailure(422, "INVALID_CURSOR") from None
        rows = (
            self.session.execute(
                text(
                    "SELECT item_key,state,failure_code,result FROM public.job_items WHERE job_id=:id AND item_key>:after ORDER BY item_key LIMIT :limit"
                ),
                {"id": job_id, "after": after, "limit": limit + 1},
            )
            .mappings()
            .all()
        )
        items = [
            JobItemView(
                item_key=row["item_key"],
                state=row["state"],
                failure_code=row["failure_code"],
                result=row["result"] or {},
            )
            for row in rows[:limit]
        ]
        next_cursor = (
            base64.urlsafe_b64encode(f"{job_id}:{items[-1].item_key}".encode()).decode()
            if len(rows) > limit
            else None
        )
        return items, next_cursor
