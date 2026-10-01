"""Typed job tickets; reuses T04 encryption without generic managed-token handles."""

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from wso_core.secrets import Envelope, KeyProvider, SecretCipher, SecretRejected
from wso_core.worker import JOB_STEP_ACTIVE, JobLease, JobWorker


@dataclass(frozen=True)
class OperationCredentialLease:
    value: str = field(repr=False)


def issue_operation_ticket(worker: JobWorker, lease: JobLease) -> str:
    if JOB_STEP_ACTIVE.get():
        raise SecretRejected()
    try:
        with worker.factory.begin() as db:
            worker._check(db)
            ticket: str | None = db.execute(
                text("SELECT public.wso_operation_ticket(:id,:token,:generation)"),
                {
                    "id": lease.job_id,
                    "token": lease.token,
                    "generation": lease.generation,
                },
            ).scalar_one()
    except SQLAlchemyError:
        raise SecretRejected() from None
    if type(ticket) is not str or len(ticket) != 64:
        raise SecretRejected()
    return ticket


class OperationCredentialStore:
    def __init__(self, worker_url: str, provider: KeyProvider) -> None:
        if not worker_url.startswith("postgresql+psycopg://"):
            raise SecretRejected()
        self.engine = create_engine(
            worker_url,
            hide_parameters=True,
            connect_args={
                "connect_timeout": 5,
                "options": "-c statement_timeout=10000 -c lock_timeout=3000",
            },
        )
        self.cipher = SecretCipher(provider)

    def close(self) -> None:
        self.engine.dispose()

    def redeem(self, ticket: str) -> OperationCredentialLease:
        lease = secrets.token_hex(32)
        try:
            with self.engine.begin() as db:
                if (
                    db.execute(text("SELECT current_user")).scalar_one()
                    != "wso_connection_worker"
                ):
                    raise SecretRejected()
                if not db.execute(
                    text("SELECT public.wso_operation_redeem(:ticket,:lease)"),
                    {"ticket": ticket, "lease": lease},
                ).scalar_one():
                    raise SecretRejected()
        except SQLAlchemyError:
            raise SecretRejected() from None
        return OperationCredentialLease(lease)

    def use(
        self, lease: OperationCredentialLease, callback: Callable[[bytes], object]
    ) -> None:
        """No callback result leaves this boundary. Admission rechecks before and after use."""
        if JOB_STEP_ACTIVE.get() or type(lease) is not OperationCredentialLease:
            raise SecretRejected()
        failed = False
        try:
            with self.engine.begin() as db:
                if (
                    db.execute(text("SELECT current_user")).scalar_one()
                    != "wso_connection_worker"
                ):
                    raise SecretRejected()
                row = (
                    db.execute(
                        text("SELECT * FROM public.wso_operation_secret(:lease)"),
                        {"lease": lease.value},
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise SecretRejected()
                value = self.cipher.open(
                    row["tenant_id"],
                    row["connection_id"],
                    row["version_id"],
                    Envelope(row["nonce"], row["ciphertext"]),
                )
                try:
                    result = callback(value)
                    if (
                        result is not None
                        or not db.execute(
                            text(
                                "SELECT public.wso_operation_credential_check(:lease)"
                            ),
                            {"lease": lease.value},
                        ).scalar_one()
                    ):
                        raise SecretRejected()
                finally:
                    del value
        except Exception:  # noqa: BLE001 - redact credential-bearing callback exceptions
            # Transport errors may embed credentials; never propagate callback text.
            failed = True
        if failed:
            try:
                with self.engine.begin() as db:
                    db.execute(
                        text("SELECT public.wso_operation_uncertain(:lease)"),
                        {"lease": lease.value},
                    )
            except SQLAlchemyError:
                # If the database is unavailable, the durable hold and T05
                # watchdog still prevent another write attempt.
                pass
            raise SecretRejected() from None
