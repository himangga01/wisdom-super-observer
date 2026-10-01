"""Job-bound execution. No tenant authorization or connection ciphertext access."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from wso_contracts.jobs import DispatchReference

from wso_core.jobs import (
    DEFAULT_REGISTRY,
    JobFailure,
    JobRegistry,
    bounded_json,
    db_error,
)

JOB_STEP_ACTIVE: ContextVar[bool] = ContextVar("wso_job_step_active", default=False)


@dataclass(frozen=True)
class JobLease:
    job_id: UUID
    token: str = field(repr=False)
    generation: int
    expires_at: datetime
    reconcile: bool = False


@dataclass
class JobStep:
    session: Session
    lease: JobLease
    payload: BaseModel
    completed: bool = False

    def record_item(
        self,
        item_key: str,
        state: str,
        result: dict[str, Any],
        failure_code: str | None = None,
    ) -> None:
        self.session.execute(
            text(
                "SELECT public.wso_record_job_item(:id,:token,:key,:state,CAST(:result AS jsonb),:code)"
            ),
            {
                "id": self.lease.job_id,
                "token": self.lease.token,
                "key": item_key,
                "state": state,
                "result": bounded_json(result),
                "code": failure_code,
            },
        )

    def complete(
        self,
        result: dict[str, Any],
        state: str = "SUCCEEDED",
        failure_code: str | None = None,
    ) -> None:
        self.session.execute(
            text(
                "SELECT public.wso_complete_job(:id,:token,CAST(:result AS jsonb),:state,:code)"
            ),
            {
                "id": self.lease.job_id,
                "token": self.lease.token,
                "result": bounded_json(result),
                "state": state,
                "code": failure_code,
            },
        )
        self.completed = True

    def mark_submitted(self) -> None:
        self.session.execute(
            text("SELECT public.wso_mark_job_submitted(:id,:token)"),
            {"id": self.lease.job_id, "token": self.lease.token},
        )


class JobWorker:
    def __init__(
        self,
        url: str,
        registry: JobRegistry = DEFAULT_REGISTRY,
        worker_id: str = "worker",
    ) -> None:
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("explicit job worker PostgreSQL URL required")
        self.engine = create_engine(url, hide_parameters=True, pool_pre_ping=True)
        self.factory = sessionmaker(self.engine)
        self.registry, self.worker_id = registry, worker_id
        try:
            with self.factory.begin() as db:
                self._check(db)
                registry.validate_database(db)
        except BaseException:
            self.engine.dispose()
            raise

    @staticmethod
    def _check(db: Session) -> None:
        if db.execute(text("SELECT current_user")).scalar_one() != "wso_job_worker":
            raise JobFailure(403)

    def claim(
        self,
        job_id: UUID,
        worker_id: str | None = None,
        *,
        reference: DispatchReference,
    ) -> JobLease | None:
        reference = DispatchReference.model_validate(reference)
        if job_id != reference.job_id:
            raise JobFailure(422, "INVALID_REFERENCE")
        try:
            with self.factory.begin() as db:
                self._check(db)
                row = (
                    db.execute(
                        text(
                            "SELECT * FROM public.wso_claim_job(:id,:worker,:outbox,:tenant,:kind,:generation)"
                        ),
                        {
                            "id": job_id,
                            "worker": worker_id or self.worker_id,
                            "outbox": reference.outbox_id,
                            "tenant": reference.tenant_id,
                            "kind": reference.kind,
                            "generation": reference.lease_generation,
                        },
                    )
                    .mappings()
                    .first()
                )
                return None if row is None else JobLease(job_id=job_id, **dict(row))
        except DBAPIError as exc:
            raise db_error(exc) from None

    @contextmanager
    def step(self, lease: JobLease) -> Iterator[JobStep]:
        try:
            with self.factory.begin() as db:
                self._check(db)
                db.execute(
                    text("SELECT public.wso_begin_job_step(:id,:token)"),
                    {"id": lease.job_id, "token": lease.token},
                )
                row = db.execute(
                    text("SELECT kind,payload FROM public.jobs WHERE id=:id"),
                    {"id": lease.job_id},
                ).one()
                payload = self.registry.get(row.kind).payload_model.model_validate(
                    row.payload
                )
                step = JobStep(db, lease, payload)
                active = JOB_STEP_ACTIVE.set(True)
                try:
                    yield step
                finally:
                    JOB_STEP_ACTIVE.reset(active)
                if (
                    not step.completed
                    and db.execute(
                        text("SELECT public.wso_current_job_id()")
                    ).scalar_one()
                    != lease.job_id
                ):
                    raise JobFailure(403, "STEP_EXPIRED")
        except DBAPIError as exc:
            raise db_error(exc) from None

    def heartbeat(self, job_id: UUID, lease_token: str) -> None:
        self._call("SELECT public.wso_heartbeat_job(:id,:token)", job_id, lease_token)

    def _call(self, sql: str, job_id: UUID, token: str, **extra: Any) -> None:
        try:
            with self.factory.begin() as db:
                self._check(db)
                db.execute(text(sql), {"id": job_id, "token": token, **extra})
        except DBAPIError as exc:
            raise db_error(exc) from None

    def complete(self, job_id: UUID, lease_token: str, result: dict[str, Any]) -> None:
        self._call(
            "SELECT public.wso_complete_job(:id,:token,CAST(:result AS jsonb),'SUCCEEDED',NULL)",
            job_id,
            lease_token,
            result=bounded_json(result),
        )

    def fail(
        self, job_id: UUID, lease_token: str, code: str, state: str = "FAILED"
    ) -> None:
        self._call(
            "SELECT public.wso_complete_job(:id,:token,'{}'::jsonb,:state,:code)",
            job_id,
            lease_token,
            state=state,
            code=code,
        )

    def recover(self, reference: DispatchReference) -> JobLease | None:
        return self.claim(reference.job_id, reference=reference)

    def issue_connection_handle(self, lease: JobLease, connection_id: UUID) -> str:
        # Own short transaction. Never call while a separate step holds its job lock.
        if JOB_STEP_ACTIVE.get():
            raise JobFailure(403, "NESTED_SECRET_TRANSACTION")
        try:
            with self.factory.begin() as db:
                self._check(db)
                handle: str | None = db.execute(
                    text(
                        "SELECT public.wso_issue_job_connection_handle(:id,:token,:connection)"
                    ),
                    {
                        "id": lease.job_id,
                        "token": lease.token,
                        "connection": connection_id,
                    },
                ).scalar_one()
                if handle is None:
                    raise JobFailure(403)
                return str(handle)
        except DBAPIError as exc:
            raise db_error(exc) from None

    def publish_operation_readback(self, lease: JobLease, evidence: object) -> None:
        """Trusted backend evidence only; SQL verifies the current lease and domain."""
        from wso_core.tvt.domain_jobs import AuthoritativeReadback

        if JOB_STEP_ACTIVE.get() or type(evidence) is not AuthoritativeReadback:
            raise JobFailure(403, "INVALID_READBACK")
        self._call(
            "SELECT public.wso_operation_readback(:id,:token,:generation,:outcome,:reference)",
            lease.job_id,
            lease.token,
            generation=lease.generation,
            outcome=evidence.outcome,
            reference=evidence.reference,
        )

    def execute(self, reference: DispatchReference | dict[str, Any]) -> None:
        reference = DispatchReference.model_validate(reference)
        lease = self.claim(reference.job_id, reference=reference)
        if lease is None:
            return
        submitted = lease.reconcile
        try:
            definition = self.registry.get(reference.kind)
            if definition.handler is None:
                self.fail(lease.job_id, lease.token, "HANDLER_UNAVAILABLE")
                return
            if (
                definition.effect_mode == "EXTERNAL_WRITE"
                and definition.reconcile is None
            ):
                self.fail(
                    lease.job_id,
                    lease.token,
                    "UNKNOWN_REMOTE_STATE" if submitted else "HANDLER_UNAVAILABLE",
                    "NEEDS_USER_INPUT" if submitted else "FAILED",
                )
                return
            if definition.credential_use:
                # This executor owns one bounded job transaction. Credential
                # callbacks require the explicit separate-secret transaction
                # workflow, supplied by a future credential-owning executor.
                self.fail(lease.job_id, lease.token, "CAPABILITY_UNSUPPORTED")
                return
            if definition.effect_mode == "EXTERNAL_WRITE" and not lease.reconcile:
                # Durable intent precedes any remote callback. A lost response can
                # only enter the reconcile path under the next execution fence.
                self._call(
                    "SELECT public.wso_mark_job_submitted(:id,:token)",
                    lease.job_id,
                    lease.token,
                )
                submitted = True
            with self.step(lease) as step:
                callback = (
                    definition.reconcile if lease.reconcile else definition.handler
                )
                result = None if callback is None else callback(step)
                if not step.completed:
                    if result is None:
                        step.complete({}, "NEEDS_USER_INPUT", "UNKNOWN_REMOTE_STATE")
                    else:
                        step.complete(result)
        except (ValidationError, JobFailure):
            # Fenced failures cannot overwrite cancellation or a newer attempt.
            try:
                self.fail(
                    lease.job_id,
                    lease.token,
                    "UNKNOWN_REMOTE_STATE" if submitted else "INVALID_JOB_PAYLOAD",
                    "NEEDS_USER_INPUT" if submitted else "FAILED",
                )
            except JobFailure:
                pass
        except Exception:  # noqa: BLE001 - isolate trusted handlers; never log payload exceptions
            if submitted:
                try:
                    self.fail(
                        lease.job_id,
                        lease.token,
                        "UNKNOWN_REMOTE_STATE",
                        "NEEDS_USER_INPUT",
                    )
                except JobFailure:
                    pass
            # Local/read transactions rolled back. Leave RUNNING durable state;
            # PostgreSQL watchdog schedules bounded retry after lease expiry.
