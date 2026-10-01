"""Internal checked operations; transaction commit belongs to the caller."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from wso_contracts.tvt.operation import OperationState, parse_intent

from wso_core.jobs import JobFailure, db_error


@dataclass(frozen=True)
class PreparedOperation:
    operation_id: UUID
    state: OperationState
    expires_at: datetime
    confirmation: str | None = field(repr=False)
    job_id: UUID | None = None


class OperationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _call(self, sql: str, **params: object) -> dict[str, Any]:
        try:
            row = self.session.execute(text(sql), params).mappings().one_or_none()
        except DBAPIError as exc:
            raise db_error(exc) from None
        if row is None:
            raise JobFailure(404)
        return dict(row)

    def prepare(self, intent: object, idempotency_key: str) -> PreparedOperation:
        typed = parse_intent(intent)
        row = self._call(
            "SELECT * FROM public.wso_operation_prepare(CAST(:intent AS jsonb),:key)",
            intent=json.dumps(typed.model_dump(mode="json")),
            key=idempotency_key,
        )
        return PreparedOperation(**row)

    def submit(
        self,
        operation_id: UUID,
        confirmation: str,
        intent: object,
        idempotency_key: str,
    ) -> dict[str, Any]:
        typed = parse_intent(intent)
        return self._call(
            "SELECT * FROM public.wso_operation_submit(:id,:confirmation,CAST(:intent AS jsonb),:key)",
            id=operation_id,
            confirmation=confirmation,
            intent=json.dumps(typed.model_dump(mode="json")),
            key=idempotency_key,
        )

    def get(self, operation_id: UUID) -> dict[str, Any]:
        return self._call(
            "SELECT * FROM public.wso_operation_get(:id)", id=operation_id
        )

    def cancel(self, operation_id: UUID) -> dict[str, Any]:
        self._call("SELECT public.wso_operation_cancel(:id)", id=operation_id)
        return self.get(operation_id)

    def reconcile(self, operation_id: UUID) -> dict[str, Any]:
        """Schedule a backend readback attempt; the caller cannot supply an outcome."""
        self._call("SELECT public.wso_operation_reconcile(:id)", id=operation_id)
        return self.get(operation_id)
