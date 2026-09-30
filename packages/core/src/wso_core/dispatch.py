"""Projection-only dispatcher; PostgreSQL retains the delivery watchdog."""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from wso_contracts.jobs import DispatchReference

from wso_core.jobs import DEFAULT_REGISTRY, JobFailure, JobRegistry


class Dispatcher:
    def __init__(
        self,
        url: str,
        publisher: Callable[[DispatchReference, str], None],
        worker_id: str = "dispatcher",
        registry: JobRegistry = DEFAULT_REGISTRY,
    ) -> None:
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("explicit dispatcher PostgreSQL URL required")
        self.engine = create_engine(url, hide_parameters=True, pool_pre_ping=True)
        self.factory = sessionmaker(self.engine)
        self.publisher, self.worker_id, self.registry = publisher, worker_id, registry

    @staticmethod
    def _check(db: Session) -> None:
        if db.execute(text("SELECT current_user")).scalar_one() != "wso_dispatcher":
            raise JobFailure(403)

    def claim_dispatch_batch(
        self, limit: int = 100, worker_id: str | None = None
    ) -> list[DispatchReference]:
        return [reference for reference, _ in self._claim_metadata(limit, worker_id)]

    def _claim_metadata(
        self, limit: int = 100, worker_id: str | None = None
    ) -> list[tuple[DispatchReference, str]]:
        with self.factory.begin() as db:
            self._check(db)
            rows = db.execute(
                text("SELECT * FROM public.wso_claim_dispatch_batch(:limit,:worker)"),
                {"limit": limit, "worker": worker_id or self.worker_id},
            ).mappings()
            claimed = []
            for row in rows:
                fields = dict(row)
                queue = str(fields.pop("queue"))
                claimed.append((DispatchReference.model_validate(fields), queue))
            return claimed

    def ack(
        self, outbox_id: UUID, dispatch_generation: int, worker_id: str | None = None
    ) -> None:
        with self.factory.begin() as db:
            self._check(db)
            db.execute(
                text("SELECT public.wso_ack_dispatch(:id,:generation,:worker)"),
                {
                    "id": outbox_id,
                    "generation": dispatch_generation,
                    "worker": worker_id or self.worker_id,
                },
            )

    def nack(
        self,
        outbox_id: UUID,
        dispatch_generation: int,
        worker_id: str | None = None,
        error_code: str = "PUBLISH_FAILED",
    ) -> None:
        with self.factory.begin() as db:
            self._check(db)
            db.execute(
                text("SELECT public.wso_nack_dispatch(:id,:generation,:worker,:error)"),
                {
                    "id": outbox_id,
                    "generation": dispatch_generation,
                    "worker": worker_id or self.worker_id,
                    "error": error_code,
                },
            )

    def run_once(self) -> int:
        published = 0
        for reference, queue in self._claim_metadata():
            try:
                if self.registry.get(reference.kind).queue != queue:
                    raise JobFailure(422, "REGISTRY_QUEUE_MISMATCH")
                self.publisher(reference, queue)
            except Exception:  # noqa: BLE001 - transport failures are persisted as sanitized retry state
                self.nack(reference.outbox_id, reference.lease_generation)
            else:
                self.ack(reference.outbox_id, reference.lease_generation)
                published += 1
        return published
