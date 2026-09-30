"""Key-free, sequential private-object cleanup with durable database fences."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from wso_core.assets import AssetEvent, AssetEventCallback, AssetFailure, _lease
from wso_core.storage import (
    CleanupWork,
    IOBudget,
    MultipartEntry,
    ObjectEntry,
    ObjectLocator,
    PrivateObjectStore,
    StorageFailure,
    opaque_valid,
)

_LOG = logging.getLogger(__name__)


def _work(row: Mapping[str, Any], objects: PrivateObjectStore) -> CleanupWork:
    try:
        locator = ObjectLocator(
            row["installation_id"], row["tenant_id"], row["asset_id"], row["attempt_id"]
        )
        if locator.installation_id != objects.namespace.installation_id:
            raise ValueError("namespace mismatch")
        return CleanupWork(
            row["work_id"], locator, row["operation"], row["multipart_id"], _lease(row)
        )
    except (TypeError, KeyError, ValueError):
        raise AssetFailure(503, "ASSET_INTEGRITY") from None


class AssetMaintenance:
    def __init__(
        self,
        *,
        transactions: Callable[[], AbstractContextManager[Session]],
        objects: PrivateObjectStore,
        worker_id: str,
        on_event: AssetEventCallback | None,
    ) -> None:
        opaque_valid(worker_id, 128)
        self.transactions, self.objects = transactions, objects
        self.worker_id, self.on_event = worker_id, on_event

    def _scalar(self, statement: str, values: dict[str, Any]) -> Any:
        with self.transactions() as session:
            if (
                session.execute(text("SELECT current_user")).scalar_one()
                != "wso_asset_maintenance"
            ):
                raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
            return session.execute(text(statement), values).scalar_one()

    def _candidate(self, entry: ObjectEntry | MultipartEntry) -> bool:
        locator = entry.locator
        candidate = {
            name: str(getattr(locator, name))
            for name in ("installation_id", "tenant_id", "asset_id", "attempt_id")
        }
        if isinstance(entry, MultipartEntry):
            candidate["multipart_id"] = entry.upload_id
            observed = entry.initiated_at
        else:
            observed = entry.last_modified
        return (
            self._scalar(
                "SELECT public.wso_reconcile_asset_candidate(CAST(:locator AS jsonb),:observed)",
                {"locator": json.dumps(candidate), "observed": observed},
            )
            is True
        )

    def _objects(self, work: CleanupWork, budget: IOBudget) -> list[ObjectEntry]:
        entries: list[ObjectEntry] = []
        cursor = None
        seen = set()
        while True:
            budget.remaining_seconds()
            page = self.objects.list_objects(
                locator=work.locator, cursor=cursor, budget=budget
            )
            entries.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return entries
            if cursor in seen:
                raise StorageFailure("INTEGRITY")
            seen.add(cursor)

    def _multiparts(self, work: CleanupWork, budget: IOBudget) -> list[MultipartEntry]:
        entries: list[MultipartEntry] = []
        cursor = None
        seen = set()
        while True:
            budget.remaining_seconds()
            page = self.objects.list_multipart(
                locator=work.locator, cursor=cursor, budget=budget
            )
            entries.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return entries
            if cursor in seen:
                raise StorageFailure("INTEGRITY")
            seen.add(cursor)

    def _perform(self, work: CleanupWork, budget: IOBudget) -> bool:
        # Preserve a positive late-object observation before deleting it. An
        # absence observation alone never clears unknown remote-write authority.
        for entry in self._objects(work, budget):
            if not self._candidate(entry):
                raise StorageFailure("DENIED")
        if work.operation == "DELETE_OBJECT":
            self.objects.delete(work.locator, budget=budget)
        else:
            assert work.multipart_id is not None
            self.objects.abort_multipart(work.locator, work.multipart_id, budget=budget)
        if self.on_event is not None:
            self.on_event(
                AssetEvent("CLEANUP_EFFECT_BEFORE_ACK", work.locator.asset_id, work.id)
            )
        budget.remaining_seconds()
        objects = self._objects(work, budget)
        multiparts = self._multiparts(work, budget)
        for part in multiparts:
            self._candidate(part)
        return not objects and not multiparts

    def run_once(self, limit: int = 100) -> int:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid maintenance limit")
        self._scalar("SELECT public.wso_sweep_assets(:limit)", {"limit": limit})
        completed = 0
        for _ in range(limit):
            started = time.monotonic()
            with self.transactions() as session:
                if (
                    session.execute(text("SELECT current_user")).scalar_one()
                    != "wso_asset_maintenance"
                ):
                    raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
                rows = (
                    session.execute(
                        text(
                            "SELECT * FROM public.wso_claim_asset_cleanup(:limit,:worker)"
                        ),
                        {"limit": 1, "worker": self.worker_id},
                    )
                    .mappings()
                    .all()
                )
            if not rows:
                break
            if len(rows) != 1:
                raise AssetFailure(503, "ASSET_INTEGRITY")
            work = _work(dict(rows[0]), self.objects)
            values = {
                "id": work.id,
                "generation": work.lease.generation,
                "token": work.lease.token,
            }
            budget = IOBudget(
                min(started + 20, started + work.lease.remaining_ms / 1000)
            )
            code = "REMOTE_UNKNOWN"
            try:
                absent = self._perform(work, budget)
                budget.remaining_seconds()
                accepted = self._scalar(
                    "SELECT public.wso_finish_asset_cleanup(:id,:generation,:token,:absent)",
                    {**values, "absent": absent},
                )
                if accepted is True:
                    completed += 1
                    continue
            except StorageFailure as error:
                code = error.code
            except (SQLAlchemyError, AssetFailure):
                code = "UNAVAILABLE"
            finally:
                if not self.objects.local_cleanup_complete():
                    raise AssetFailure(503, "ASSET_LOCAL_CLEANUP_UNAVAILABLE")
            try:
                self._scalar(
                    "SELECT public.wso_retry_asset_cleanup(:id,:generation,:token,:error)",
                    {**values, "error": code},
                )
            except (SQLAlchemyError, AssetFailure):
                _LOG.warning("Asset cleanup lease acknowledgment deferred")
        try:
            self._scalar(
                "SELECT public.wso_flush_asset_audits(:limit)", {"limit": limit}
            )
        except (SQLAlchemyError, AssetFailure):
            _LOG.warning("Asset maintenance audit projection deferred")
        return completed

    def run(self) -> None:
        next_reconciliation = 0.0
        while True:
            if time.monotonic() >= next_reconciliation:
                self.reconcile_once()
                next_reconciliation = time.monotonic() + 300
            self.run_once()
            time.sleep(1)

    def reconcile_once(self, limit: int = 100) -> int:
        """Checkpoint at most one provider page of each listing per call."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid reconciliation page limit")
        with self.transactions() as session:
            if (
                session.execute(text("SELECT current_user")).scalar_one()
                != "wso_asset_maintenance"
            ):
                raise AssetFailure(503, "ASSET_CONFIGURATION_UNAVAILABLE")
            state = (
                session.execute(
                    text("SELECT * FROM public.wso_asset_reconciliation_state()")
                )
                .mappings()
                .one()
            )
        budget = IOBudget(time.monotonic() + 20)
        processed = 0
        for kind, name in (
            ("OBJECTS", "object_cursor"),
            ("MULTIPART", "multipart_cursor"),
        ):
            cursor = state[name]
            entries: tuple[ObjectEntry, ...] | tuple[MultipartEntry, ...]
            if kind == "OBJECTS":
                page = self.objects.list_objects(
                    cursor=cursor, limit=limit, budget=budget
                )
                entries = page.items
            else:
                multipart_page = self.objects.list_multipart(
                    cursor=cursor, limit=limit, budget=budget
                )
                entries = multipart_page.items
            for entry in entries:
                budget.remaining_seconds()
                self._candidate(entry)
                processed += 1
            next_cursor = (
                page.next_cursor if kind == "OBJECTS" else multipart_page.next_cursor
            )
            budget.remaining_seconds()
            self._scalar(
                "SELECT public.wso_checkpoint_asset_reconciliation(:kind,:expected,:next)",
                {"kind": kind, "expected": cursor, "next": next_cursor},
            )
        return processed
