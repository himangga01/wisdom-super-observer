"""Short SQL media admission; no credentials or transaction span streaming."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from threading import RLock
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


class LocalMediaAdmission:
    def __init__(self, worker_url: str, keys: KeyProvider) -> None:
        if not worker_url.startswith("postgresql+psycopg://"):
            raise LocalDeviceFailure()
        self._cipher = SecretCipher(keys)
        self.worker_epoch = uuid4()
        self._cleanup_lock = RLock()
        self._pending_cleanup: dict[str, LocalMediaLease] = {}
        # Pooled unlike other admissions: media cadence needs fresh per-check SQL
        # without connect cost; settings stay transaction-local and role is rechecked.
        self._engine = create_engine(
            worker_url,
            hide_parameters=True,
            poolclass=QueuePool,
            pool_size=4,
            max_overflow=4,
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
        with self._engine.begin() as db:
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
        if function not in {"activate", "current", "worker_view", "playing"}:
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

    @_boundary
    def current(self, lease: object) -> bool:
        return self._query(lease, "current") is True

    @_boundary
    def view(self, lease: object) -> MediaLease:
        value = self._query(lease, "worker_view")
        if value is None:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return MediaLease.model_validate(value)

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
        if not self.retry_cleanup():
            return False
        self._engine.dispose()
        return True
