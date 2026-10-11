"""Short SQL media admission; no credentials or transaction span streaming."""

from __future__ import annotations

import json
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import BoundedSemaphore, Condition, Lock, RLock, get_ident
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool
from wso_contracts.tvt.local_media import LocalLiveRequest
from wso_contracts.tvt.media import MediaLease

from wso_core.secrets import Envelope, KeyProvider, SecretCipher

from .local_admission import _bound, _boundary, _token
from .local_credentials import LocalDeviceCredentials, parse_local_device_credentials
from .local_media_service import (
    LocalLiveProof,
    LocalMediaChannel,
    OwnedLocalLiveSession,
)
from .local_service import LocalDeviceFailure, LocalVerifyBudget

_SEAL = object()
# R120 hot-path authority: a cached answer serves a call only while its SQL
# check began less than this long ago (and before the lease's own expiry).
AUTHORITY_FRESHNESS_SECONDS = 0.1
# Longest wait for another thread's in-flight check of the same lease.
AUTHORITY_WAIT_SECONDS = 5.0
# Most recently closed lease tokens that are denied without any SQL.
AUTHORITY_TOMBSTONES = 64
# R132: leave half the 8+8 pool available to authority and short control work.
MAX_MEDIA_STARTUP_TRANSACTIONS = 8
MEDIA_STARTUP_WAIT_SECONDS = 10.0


class LocalMediaTicketIssuer:
    """Caller commits protected tenant transaction before RPC dispatch."""

    def __init__(
        self, session: Session, remaining: Callable[[], int], *, ttl_seconds: int = 30
    ) -> None:
        if type(ttl_seconds) is not int or not 5 <= ttl_seconds <= 30:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        self._session, self._remaining, self._ttl = session, remaining, ttl_seconds

    @_boundary
    def issue(
        self, session_digest: str, connection_id: UUID, body: LocalLiveRequest
    ) -> str:
        if (
            not _token(session_digest)
            or type(connection_id) is not UUID
            or type(body) is not LocalLiveRequest
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        _bound(self._session, self._remaining)
        value: Any = self._session.execute(
            text(
                "SELECT public.wso_tvt_local_media_issue(:s,:c,:store,:device,:channel,:gen,:rev,:stream,:ttl)"
            ),
            {
                "s": session_digest,
                "c": connection_id,
                "store": body.store_id,
                "device": body.device_id,
                "channel": body.channel_id,
                "gen": body.expected_generation,
                "rev": body.inventory_revision,
                "stream": body.stream,
                "ttl": self._ttl,
            },
        ).scalar_one()
        _bound(self._session, self._remaining)
        if not _token(value):
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return str(value)

    @_boundary
    def issue_control(self, session_digest: str, lease_id: UUID, purpose: str) -> str:
        if (
            not _token(session_digest)
            or type(lease_id) is not UUID
            or purpose not in {"offer", "stop", "playing"}
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        _bound(self._session, self._remaining)
        value: Any = self._session.execute(
            text("SELECT public.wso_tvt_local_media_control_issue(:s,:id,:p)"),
            {"s": session_digest, "id": lease_id, "p": purpose},
        ).scalar_one()
        _bound(self._session, self._remaining)
        if not _token(value):
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return str(value)


class LocalMediaReader:
    def __init__(
        self, session: Session, remaining: Callable[[], int] | None = None
    ) -> None:
        self._session = session
        self._remaining = remaining or (lambda: 1000)

    @_boundary
    def get(self, session_digest: str, lease_id: UUID) -> MediaLease:
        return self._read(session_digest, lease_id, False)

    @_boundary
    def heartbeat(self, session_digest: str, lease_id: UUID) -> MediaLease:
        return self._read(session_digest, lease_id, True)

    def _read(self, session_digest: str, lease_id: UUID, heartbeat: bool) -> MediaLease:
        if not _token(session_digest) or type(lease_id) is not UUID:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        _bound(self._session, self._remaining)
        value: Any = self._session.execute(
            text("SELECT public.wso_tvt_local_media_read(:s,:id,:h)"),
            {"s": session_digest, "id": lease_id, "h": heartbeat},
        ).scalar_one()
        _bound(self._session, self._remaining)
        if value is None:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return MediaLease.model_validate(value)


@dataclass(frozen=True, slots=True, repr=False)
class LocalMediaLease:
    token: str
    worker_epoch: UUID
    native_generation: UUID
    id: UUID | None
    _seal: object = field(repr=False)


class _Authority:
    """One lease's hot-path answer; every field is guarded by its condition."""

    __slots__ = ("condition", "denied", "runner", "started", "valid_until", "value")

    def __init__(self) -> None:
        self.condition = Condition(Lock())
        self.denied = False
        self.runner: int | None = None  # Thread running the one in-flight check.
        self.started = 0.0  # Gate clock just before that published check began.
        self.valid_until = 0.0
        self.value: MediaLease | None = None

    def deny(self) -> None:
        """Permanent; the caller holds the condition."""
        self.denied = True
        self.value = None
        self.condition.notify_all()


class LocalMediaAdmission:
    def __init__(
        self,
        worker_url: str,
        keys: KeyProvider,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if not worker_url.startswith("postgresql+psycopg://"):
            raise LocalDeviceFailure()
        self._cipher = SecretCipher(keys)
        self.worker_epoch = uuid4()
        self._cleanup_lock = RLock()
        self._pending_cleanup: dict[str, LocalMediaLease] = {}
        # R120 gate state: one registry lock; each entry has its own condition.
        # No SQL or callback ever runs while either is held.
        self._clock = clock
        self._authority_lock = Lock()
        # R133: distinct sealed closed tokens re-queried after tombstone eviction
        # can retain denied entries until shutdown. This registry has no fixed cap;
        # active sticky denial is never evicted to reclaim it.
        self._authorities: dict[str, _Authority] = {}
        self._tombstones: OrderedDict[str, None] = OrderedDict()
        self._authority_closed = False
        self._startup_slots = BoundedSemaphore(MAX_MEDIA_STARTUP_TRANSACTIONS)
        # Pooled unlike other admissions: the hot-path authority check needs
        # bounded SQL without connect cost; settings stay transaction-local and
        # the role is rechecked in every transaction.
        self._engine = create_engine(
            worker_url,
            hide_parameters=True,
            poolclass=QueuePool,
            pool_size=8,
            max_overflow=8,
            pool_timeout=1,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={
                "connect_timeout": 3,
                "options": "-c statement_timeout=20000 -c lock_timeout=3000",
            },
        )

    @staticmethod
    def _lease(lease: object) -> LocalMediaLease:
        if (
            type(lease) is not LocalMediaLease
            or lease._seal is not _SEAL
            or not _token(lease.token)
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return lease

    @staticmethod
    def _args(lease: LocalMediaLease) -> dict[str, Any]:
        return {"a": lease.token, "w": lease.worker_epoch, "n": lease.native_generation}

    @staticmethod
    def _worker(db: Connection, remaining: Callable[[], int]) -> None:
        _bound(db, remaining)
        if (
            db.execute(text("SELECT current_user")).scalar_one()
            != "wso_connection_worker"
        ):
            raise LocalDeviceFailure()

    @_boundary
    def redeem(self, ticket: str, *, budget: LocalVerifyBudget) -> object:
        if not _token(ticket):
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        lease = LocalMediaLease(
            secrets.token_hex(32), self.worker_epoch, uuid4(), None, _SEAL
        )
        try:
            with self._engine.begin() as db:
                self._worker(db, budget.remaining_ms)
                identifier: Any = db.execute(
                    text("SELECT public.wso_tvt_local_media_redeem(:t,:a,:w,:n)"),
                    {**self._args(lease), "t": ticket},
                ).scalar_one()
                if type(identifier) is not UUID:
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                budget.remaining_ms()
            budget.remaining_ms()
        except BaseException:
            try:
                self.close(lease, cleanup_confirmed=True)
            except BaseException:
                # Commit completion can be uncertain even though this method
                # never returned its binding to the executor. Retain the exact
                # authority/worker/native generation for independent retries.
                with self._cleanup_lock:
                    self._pending_cleanup[lease.token] = lease
                raise
            raise
        return LocalMediaLease(
            lease.token, lease.worker_epoch, lease.native_generation, identifier, _SEAL
        )

    @contextmanager
    def _startup_scope(self, budget: LocalVerifyBudget) -> Iterator[None]:
        deadline = time.monotonic() + MEDIA_STARTUP_WAIT_SECONDS
        while True:
            # Cancellation/deadline keep their existing public failure codes.
            remaining = min(budget.remaining_ms() / 1000, deadline - time.monotonic())
            if remaining <= 0:
                raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)
            if self._startup_slots.acquire(timeout=min(0.05, remaining)):
                break
        try:
            budget.remaining_ms()
            yield
        finally:
            # The surrounding transaction has settled before this permit returns.
            self._startup_slots.release()

    @_boundary
    def open(
        self,
        lease: object,
        callback: Callable[
            [LocalDeviceCredentials, LocalMediaChannel, Callable[[], bool]],
            OwnedLocalLiveSession,
        ],
        *,
        budget: LocalVerifyBudget,
    ) -> OwnedLocalLiveSession:
        from wso_core.worker import JOB_STEP_ACTIVE

        if JOB_STEP_ACTIVE.get():
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        given = self._lease(lease)
        with self._startup_scope(budget), self._engine.begin() as db:
            self._worker(db, budget.remaining_ms)
            row = (
                db.execute(
                    text("SELECT * FROM public.wso_tvt_local_media_use(:a,:w,:n)"),
                    self._args(given),
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)

            def current() -> bool:
                _bound(db, budget.remaining_ms)
                accepted: Any = db.execute(
                    text("SELECT public.wso_tvt_local_media_current(:a,:w,:n)"),
                    self._args(given),
                ).scalar_one()
                budget.remaining_ms()
                return accepted is True

            if not current():
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            raw = self._cipher.open(
                row["tenant_id"],
                row["connection_id"],
                row["version_id"],
                Envelope(bytes(row["nonce"]), bytes(row["ciphertext"])),
            )
            credentials = None
            try:
                credentials = parse_local_device_credentials(raw)
                channel = LocalMediaChannel(
                    bytes(row["guid"]),
                    row["raw_index"],
                    row["window_index"],
                    row["ordinal"],
                    row["kind"],
                    row["stream"],
                )
                if not current():
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                session = callback(credentials, channel, current)
            finally:
                del raw, credentials
            if not current():
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            budget.remaining_ms()
        budget.remaining_ms()
        return session

    def _query(
        self,
        lease: object,
        function: str,
        *,
        budget: LocalVerifyBudget | None = None,
        proof: LocalLiveProof | None = None,
    ) -> Any:
        given = self._lease(lease)
        remaining = budget.remaining_ms if budget is not None else (lambda: 1000)
        args = self._args(given)
        suffix = ""
        if proof is not None:
            proof.validate(delivery=function == "playing")
            args["p"] = json.dumps(asdict(proof), separators=(",", ":"))
            suffix = ",CAST(:p AS jsonb)"
        # Function names are fixed internal callers, never public selectors.
        if function not in {"activate", "playing", "observe"}:
            raise LocalDeviceFailure()
        with self._engine.begin() as db:
            self._worker(db, remaining)
            value: Any = db.execute(
                text(f"SELECT public.wso_tvt_local_media_{function}(:a,:w,:n{suffix})"),
                args,
            ).scalar_one()
            remaining()
        remaining()
        return value

    @_boundary
    def activate(
        self, lease: object, proof: LocalLiveProof, *, budget: LocalVerifyBudget
    ) -> MediaLease:
        value = self._query(lease, "activate", budget=budget, proof=proof)
        if value is None:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        view = MediaLease.model_validate(value)
        if view.id != self._lease(lease).id or view.state != "NEGOTIATING":
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        return view

    def _authority(self, lease: object) -> MediaLease | None:
        """R120 hot-path authority: None denies, a view grants.

        A grant returned to a call that began at gate time c always comes from
        a non-locking observe check that began after c - F. At most one check
        per lease is in flight; others wait for it. A NULL answer, any error,
        a waiter timeout, close() or shutdown() deny the lease permanently.
        A successful in-flight check still answers its eligible callers if SQL
        latency crosses expiry; ordinary cache reuse and downstream emission
        permits are expiry-clipped. Slow success does not create sticky denial.
        """
        given = self._lease(lease)
        began = self._clock()
        with self._authority_lock:
            if self._authority_closed or given.token in self._tombstones:
                return None
            entry = self._authorities.get(given.token)
            if entry is None:
                entry = self._authorities[given.token] = _Authority()
        me = get_ident()
        waited, deadline = False, 0.0
        with entry.condition:
            while True:
                if entry.denied:
                    return None
                if entry.runner is None:
                    if entry.value is not None and (
                        self._clock() < entry.valid_until
                        or (
                            waited
                            and entry.started > began - AUTHORITY_FRESHNESS_SECONDS
                        )
                    ):
                        return entry.value
                    break
                if entry.runner == me:
                    return None  # Re-entry would wait on itself: deny this call.
                # Freshness uses the injected clock; waiter liveness uses real
                # monotonic time even if an injected test clock stops advancing.
                now = time.monotonic()
                if not waited:
                    waited, deadline = True, now + AUTHORITY_WAIT_SECONDS
                elif now >= deadline:
                    entry.deny()
                    return None
                entry.condition.wait(deadline - now)
            entry.runner = me
        # This thread runs the lease's one check, outside every lock.
        started, observed_at = self._clock(), datetime.now(UTC)
        try:
            value = self._query(given, "observe")
            view = None if value is None else MediaLease.model_validate(value)
        except BaseException:
            with entry.condition:
                entry.runner = None
                entry.deny()
            raise  # Its own caller keeps the fixed failure mapping (503).
        with entry.condition:
            entry.runner = None
            if view is None or entry.denied:
                entry.deny()
                return None
            left = (view.expires_at - observed_at).total_seconds()
            entry.value, entry.started = view, started
            entry.valid_until = min(
                started + AUTHORITY_FRESHNESS_SECONDS, started + left
            )
            entry.condition.notify_all()
            return view

    def _retire_authority(self, token: str) -> None:
        """Deny and tombstone one lease; any in-flight answer is discarded."""
        with self._authority_lock:
            self._tombstones[token] = None
            self._tombstones.move_to_end(token)
            while len(self._tombstones) > AUTHORITY_TOMBSTONES:
                self._tombstones.popitem(last=False)
            entry = self._authorities.pop(token, None)
            if entry is not None:
                with entry.condition:
                    entry.deny()

    @_boundary
    def current(self, lease: object) -> bool:
        return self._authority(lease) is not None

    @_boundary
    def view(self, lease: object) -> MediaLease:
        value = self._authority(lease)
        if value is None:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return value.model_copy(deep=True)

    @_boundary
    def playing(self, lease: object, proof: LocalLiveProof) -> MediaLease:
        value = self._query(lease, "playing", proof=proof)
        if value is None:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return MediaLease.model_validate(value)

    @_boundary
    def redeem_control(
        self, ticket: str, purpose: str, *, budget: LocalVerifyBudget
    ) -> UUID:
        if not _token(ticket) or purpose not in {"offer", "stop", "playing"}:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        with self._engine.begin() as db:
            self._worker(db, budget.remaining_ms)
            value: Any = db.execute(
                text("SELECT public.wso_tvt_local_media_control_redeem(:t,:p,:w)"),
                {"t": ticket, "p": purpose, "w": self.worker_epoch},
            ).scalar_one()
            if type(value) is not UUID:
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            budget.remaining_ms()
        budget.remaining_ms()
        return value

    @_boundary
    def close(self, lease: object, *, cleanup_confirmed: bool) -> None:
        given = self._lease(lease)
        # Deny the hot path first: nothing is granted while retirement runs.
        self._retire_authority(given.token)
        if type(cleanup_confirmed) is not bool:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        with self._engine.begin() as db:
            self._worker(db, lambda: 1000)
            db.execute(
                text("SELECT public.wso_tvt_local_media_close(:a,:w,:n,:c)"),
                {**self._args(given), "c": cleanup_confirmed},
            )

    def retry_cleanup(self) -> bool:
        # Four short attempts per sweep keep unavailable SQL from monopolizing
        # the native revocation monitor. Rotate failed tokens for fair retries.
        with self._cleanup_lock:
            leases = tuple(self._pending_cleanup.values())[:4]
        for lease in leases:
            try:
                self.close(lease, cleanup_confirmed=True)
            except Exception:  # noqa: BLE001 -- keep exact sealed retry owner.
                with self._cleanup_lock:
                    self._pending_cleanup.pop(lease.token, None)
                    self._pending_cleanup[lease.token] = lease
            else:
                with self._cleanup_lock:
                    self._pending_cleanup.pop(lease.token, None)
        with self._cleanup_lock:
            return not self._pending_cleanup

    def shutdown(self) -> bool:
        with self._authority_lock:
            self._authority_closed = True
            entries = tuple(self._authorities.values())
            self._authorities.clear()
            for entry in entries:
                with entry.condition:
                    entry.deny()
        if not self.retry_cleanup():
            return False
        self._engine.dispose()
        return True
