"""Purpose-specific SQL authority for original shared recorder custody.

Only this factory mints grants. Its retained exact-object registry is the
authority; a dataclass seal, a copied grant or a JSON receipt is insufficient.
SQL transactions end before decryption, producer calls and native work.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Condition, Lock, get_ident
from typing import Any, Literal, Protocol, TypeVar, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from wso_contracts.tvt.media import MediaLease

from wso_core.secrets import Envelope, KeyProvider

from .local_admission import _boundary, _token
from .local_credentials import LocalDeviceCredentials, parse_local_device_credentials
from .local_media_admission import (
    AUTHORITY_FRESHNESS_SECONDS,
    AUTHORITY_WAIT_SECONDS,
    LocalMediaAdmission,
    LocalMediaLease,
)
from .local_media_mux_types import (
    _GRANT_SEAL,
    CleanupScope,
    EpochCleanupReceipt,
    EpochReceiptIssuer,
    FocusGrant,
    MasterLoginProof,
    MasterReservation,
    MuxScopeKey,
    MuxSlotIdentity,
    OriginalMuxBinding,
    OriginalMuxBindingIssuer,
    SlotRetentionGrant,
    TransportGrant,
    ViewerCleanupReceipt,
    ViewerGrant,
)
from .local_media_service import (
    LocalLiveProof,
    LocalMediaChannel,
    OwnedLocalLiveSession,
)
from .local_service import LocalDeviceFailure, LocalVerifyBudget

Grant = TransportGrant | SlotRetentionGrant | ViewerGrant | FocusGrant
G = TypeVar("G", TransportGrant, SlotRetentionGrant, ViewerGrant, FocusGrant)
FocusState = Literal[
    "MAIN_ACTIVE", "ATTACHED", "CANCELLED", "FAILED", "EXPIRED", "CONSUMED"
]
_FOCUS_TERMINAL = frozenset({"CANCELLED", "FAILED", "EXPIRED", "CONSUMED"})


@dataclass(frozen=True, slots=True, repr=False)
class FocusSettlement:
    """Factory-retained SQL acknowledgement, never a native cleanup receipt."""

    focus_id: UUID
    wall_id: UUID
    state: FocusState
    attached_viewer: UUID | None
    _authority: object


class MainRetentionObserver(Protocol):
    """Maintenance only; never substitutes for a startup/transfer acknowledgement."""

    def current_main_retention(
        self,
        viewer: LocalMediaLease,
        grant: FocusGrant,
        acknowledgement: FocusSettlement,
    ) -> bool: ...


@dataclass(frozen=True, slots=True, repr=False)
class MasterReserveAttempt:
    _authority: object


@dataclass(frozen=True, slots=True, repr=False)
class MasterAttemptResolution:
    outcome: Literal["ABSENT", "RESERVED"]
    reservation: MasterReservation | None
    _authority: object


@dataclass(frozen=True, slots=True, repr=False)
class UnstartedMasterClaim:
    reservation: MasterReservation
    _authority: object


@dataclass(frozen=True, slots=True, repr=False)
class UnstartedMasterClosure:
    master_id: UUID
    lease_ids: tuple[UUID, ...]
    _authority: object


@dataclass(frozen=True, slots=True, repr=False)
class UnadoptedViewerClosure:
    master_id: UUID | None
    lease_id: UUID
    _authority: object


@dataclass(slots=True, repr=False)
class _Attempt:
    handle: MasterReserveAttempt
    viewer: LocalMediaLease
    operation: str
    authority: str
    native: UUID
    scope: MuxScopeKey | None = None
    phase: str = "NEW"
    deadline: float = 0
    reservation: MasterReservation | None = None
    resolution: MasterAttemptResolution | None = None
    closure: UnadoptedViewerClosure | None = None


@dataclass(slots=True, repr=False)
class _Unstarted:
    claim: UnstartedMasterClaim
    issuer: OriginalMuxBindingIssuer | None = None
    custody: EpochReceiptIssuer | None = None
    original: _Original | None = None
    finishing: bool = False
    closure: UnstartedMasterClosure | None = None


class ViewerReceiptIssuer(Protocol):
    def issued_receipt(self) -> ViewerCleanupReceipt | None: ...


@dataclass(slots=True, repr=False)
class _Record:
    grant: Grant
    authority: str
    master_id: UUID
    native: UUID
    lease: LocalMediaLease | None = None
    slot_id: UUID | None = None
    focus_id: UUID | None = None
    condition: Condition = field(default_factory=lambda: Condition(Lock()))
    denied: bool = False
    closed: bool = False
    runner: int | None = None
    started: float = 0
    valid_until: float = 0
    value: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True, repr=False)
class _Original:
    reservation: MasterReservation
    issuer: OriginalMuxBindingIssuer
    custody: EpochReceiptIssuer
    binding_for: Callable[[bytes], OriginalMuxBinding | None]
    issued_receipt: Callable[[], EpochCleanupReceipt | None]


@dataclass(frozen=True, slots=True, repr=False)
class _ViewerCustody:
    grant: ViewerGrant
    owner: ViewerReceiptIssuer
    issued_receipt: Callable[[], ViewerCleanupReceipt | None]


@dataclass(frozen=True, slots=True, repr=False)
class _Dedicated:
    viewer: LocalMediaLease
    registration: UUID
    scope: MuxScopeKey
    native_owner: EpochReceiptIssuer
    native_receipt: Callable[[], EpochCleanupReceipt | None]
    viewer_owner: ViewerReceiptIssuer
    viewer_receipt: Callable[[], ViewerCleanupReceipt | None]


def _deny() -> LocalDeviceFailure:
    return LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)


def _uuid(value: Any) -> UUID:
    return value if type(value) is UUID else UUID(value)


def _time(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _scope(row: dict[str, Any]) -> MuxScopeKey:
    return MuxScopeKey(
        tenant_id=_uuid(row["tenant_id"]),
        tenant_epoch=row["tenant_epoch"],
        actor_user_id=_uuid(row["actor_user_id"]),
        session_digest=bytes.fromhex(row["session_digest"]),
        wall_id=_uuid(row["wall_id"]),
        store_id=_uuid(row["store_id"]),
        device_id=_uuid(row["device_id"]),
        connection_id=_uuid(row["connection_id"]),
        connection_generation=row["connection_generation"],
        secret_version=_uuid(row["secret_version"]),
        inventory_revision=row["inventory_revision"],
        worker_epoch=_uuid(row["worker_epoch"]),
    )


class SqlMuxAdmission(LocalMediaAdmission):
    """Private worker factory; public/API callers never supply original issuers."""

    def __init__(
        self,
        worker_url: str,
        keys: KeyProvider,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        super().__init__(worker_url, keys, clock=clock)
        self._mux_lock = Lock()
        self._issuer = object()
        self._records: dict[int, _Record] = {}
        self._masters: dict[UUID, MasterReservation] = {}
        self._followers: dict[int, MasterReservation] = {}
        self._follower_attempts: dict[int, _Attempt] = {}
        self._master_grants: dict[UUID, TransportGrant] = {}
        self._creator_channels: dict[UUID, bytes] = {}
        self._originals: dict[UUID, _Original] = {}
        self._bindings: dict[UUID, tuple[OriginalMuxBinding, object]] = {}
        self._viewer_custody: dict[UUID, _ViewerCustody] = {}
        self._dedicated: dict[UUID, _Dedicated] = {}
        self._dedicated_settled: dict[UUID, set[str]] = {}
        self._pending_reservations: dict[str, tuple[LocalMediaLease, UUID]] = {}
        self._startup_held: set[UUID] = set()
        self._mux_closed = False
        self._denied_masters: set[UUID] = set()
        self._issued_leases: dict[int, LocalMediaLease] = {}
        self._lease_masters: dict[int, UUID] = {}
        self._focus_settlements: dict[int, FocusSettlement] = {}
        self._attempts: dict[int, _Attempt] = {}
        self._attempt_leases: dict[int, MasterReserveAttempt] = {}
        self._unstarted: dict[UUID, _Unstarted] = {}
        self._master_acquired: set[UUID] = set()
        self._lease_acquired: set[int] = set()
        self._lease_cleanup: set[int] = set()
        self._recovered_reservations: set[int] = set()
        self._follower_closures: dict[
            int, tuple[LocalMediaLease, MasterReservation, UnadoptedViewerClosure]
        ] = {}

    @_boundary
    def redeem(self, ticket: str, *, budget: LocalVerifyBudget) -> LocalMediaLease:
        lease = self._lease(super().redeem(ticket, budget=budget))
        with self._mux_lock:
            if self._mux_closed:
                raise _deny()
            self._issued_leases[id(lease)] = lease
        return lease

    def _known_lease(self, lease: LocalMediaLease) -> LocalMediaLease:
        given = self._lease(lease)
        with self._mux_lock:
            if (
                self._mux_closed
                or self._issued_leases.get(id(given)) is not given
                or given.worker_epoch != self.worker_epoch
                or id(given) in self._lease_cleanup
                or self._lease_masters.get(id(given)) in self._denied_masters
            ):
                raise _deny()
        with self._authority_lock:
            if self._authority_closed or given.token in self._tombstones:
                raise _deny()
            entry = self._authorities.get(given.token)
        if entry is not None:
            with entry.condition:
                if entry.denied:
                    raise _deny()
        return given

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
        given = self._known_lease(self._lease(lease))
        budget.remaining_ms()
        with self._mux_lock:
            master = self._lease_masters.get(id(given))
            if id(given) in self._lease_cleanup or master in self._unstarted:
                raise _deny()
            self._lease_acquired.add(id(given))
            if master is not None:
                self._master_acquired.add(master)
        # Preserve legacy execution behavior, but record the attempt before its
        # SQL claim or external starter can run. SQL separately persists history.
        return super().open(given, callback, budget=budget)

    @staticmethod
    def _channel(row: dict[str, Any]) -> LocalMediaChannel:
        guid = (
            bytes.fromhex(row["guid"])
            if type(row["guid"]) is str
            else bytes(row["guid"])
        )
        if (
            len(guid) != 16
            or not any(guid)
            or row["stream"] not in {"sub", "main"}
            or row["kind"] not in {"analog", "digital", "recorder"}
        ):
            raise _deny()
        for name, low, high in (
            ("raw_index", -128, 65535),
            ("window_index", -128, 65535),
            ("ordinal", 1, 256),
        ):
            if type(row[name]) is not int or not low <= row[name] <= high:
                raise _deny()
        return LocalMediaChannel(
            guid,
            row["raw_index"],
            row["window_index"],
            row["ordinal"],
            row["kind"],
            row["stream"],
        )

    def _selection(
        self, lease: LocalMediaLease, budget: LocalVerifyBudget
    ) -> LocalMediaChannel:
        self._known_lease(lease)
        row = self._sql("viewer_selection", self._args(lease), ":a,:w,:n", budget)
        if not isinstance(row, dict) or set(row) != {
            "guid",
            "raw_index",
            "window_index",
            "ordinal",
            "kind",
            "stream",
        }:
            raise _deny()
        selected = self._channel(row)
        self._known_lease(lease)
        budget.remaining_ms()
        return selected

    @_boundary
    def prepare_viewer(
        self, lease: LocalMediaLease, *, budget: LocalVerifyBudget
    ) -> LocalMediaChannel:
        given = self._known_lease(lease)
        try:
            return self._selection(given, budget)
        except BaseException:
            self._retire_authority(given.token)
            raise

    @_boundary
    def prepare_dedicated(
        self, lease: LocalMediaLease, *, budget: LocalVerifyBudget
    ) -> tuple[LocalDeviceCredentials, LocalMediaChannel]:
        given = self._known_lease(lease)
        custody = self._dedicated_owner(given)
        try:
            with self._startup_scope(budget):
                if self._selection(given, budget).stream != "main":
                    raise _deny()
                with self._engine.begin() as db:
                    self._worker(db, budget.remaining_ms)
                    raw_row = (
                        db.execute(
                            text(
                                "SELECT * FROM public.wso_tvt_local_media_use(:a,:w,:n)"
                            ),
                            self._args(given),
                        )
                        .mappings()
                        .one_or_none()
                    )
                    row = None if raw_row is None else dict(raw_row)
                    budget.remaining_ms()
                if row is None or (
                    row["tenant_id"],
                    row["connection_id"],
                    row["version_id"],
                ) != (
                    custody.scope.tenant_id,
                    custody.scope.connection_id,
                    custody.scope.secret_version,
                ):
                    raise _deny()
                self._known_lease(given)
                budget.remaining_ms()
                # The once-only claim has committed and returned its checkout.
                raw = self._cipher.open(
                    row["tenant_id"],
                    row["connection_id"],
                    row["version_id"],
                    Envelope(bytes(row["nonce"]), bytes(row["ciphertext"])),
                )
                try:
                    credentials = parse_local_device_credentials(raw)
                finally:
                    del raw
                channel = self._channel(row)
                del row, raw_row
                if (
                    self._dedicated_owner(given) is not custody
                    or self._selection(given, budget) != channel
                ):
                    raise _deny()
                self._known_lease(given)
                budget.remaining_ms()
            return credentials, channel
        except BaseException:
            self._retire_authority(given.token)
            raise

    @_boundary
    def current_dedicated_startup(
        self,
        lease: LocalMediaLease,
        registration: UUID,
        selection: LocalMediaChannel,
        *,
        budget: LocalVerifyBudget,
        retired_native_receipt: EpochCleanupReceipt | None = None,
    ) -> bool:
        """Check registered MAIN before activation without seeding hot authority.

        The short selection transaction admits LOGIN/CLAIMED and locks current
        wall, pending FORWARD focus, master and complete lease/channel scope.
        SQL registration is one-shot; its retained value and original issuers
        must still match. Selection does not project a SQL registration value.
        An exact REAPED receipt permits only the caller's login-BUSY readback;
        the native I/O callback never supplies it or regains live authority.
        """
        given = self._known_lease(lease)
        custody = self._dedicated_owner(given)
        if (
            type(registration) is not UUID
            or registration != custody.registration
            or custody.scope.worker_epoch != given.worker_epoch
            or type(selection) is not LocalMediaChannel
            or selection.stream != "main"
        ):
            raise _deny()

        def retained() -> None:
            self._known_lease(given)
            if self._dedicated_owner(given) is not custody:
                raise _deny()
            native_receipt = custody.native_receipt()
            if (
                self._dedicated_owner(given) is not custody
                or custody.viewer_receipt() is not None
            ):
                raise _deny()
            if retired_native_receipt is None:
                if native_receipt is not None:
                    raise _deny()
            elif (
                type(retired_native_receipt) is not EpochCleanupReceipt
                or native_receipt is not retired_native_receipt
                or retired_native_receipt.original_state != "REAPED"
                or retired_native_receipt.master_id != given.id
                or retired_native_receipt.worker_epoch != given.worker_epoch
                or retired_native_receipt.native_generation != given.native_generation
            ):
                raise _deny()
            if self._dedicated_owner(given) is not custody:
                raise _deny()
            self._known_lease(given)
            budget.remaining_ms()

        try:
            budget.remaining_ms()
            retained()
            if self._selection(given, budget) != selection:
                raise _deny()
            retained()
            return True
        except BaseException:
            self._retire_authority(given.token)
            raise

    def _record(
        self, grant: object, kind: type[G], *, expired: bool = False
    ) -> _Record:
        if type(grant) is not kind:
            raise _deny()
        value = cast(Grant, grant)
        with self._mux_lock:
            record = self._records.get(id(grant))
            if (
                self._mux_closed
                or record is None
                or record.grant is not grant
                or value._authority is not self._issuer
            ):
                raise _deny()
        if not expired and (
            record.denied
            or record.closed
            or record.master_id in self._denied_masters
            or self._clock() >= value.expires_monotonic
        ):
            raise _deny()
        return record

    def _remember(
        self, grant: G, authority: str, master_id: UUID, native: UUID, **kwargs: Any
    ) -> G:
        with self._mux_lock:
            if self._mux_closed:
                raise _deny()
            self._records[id(grant)] = _Record(
                grant, authority, master_id, native, **kwargs
            )
        return grant

    def _expiry(self, row: dict[str, Any], started: float, observed: datetime) -> float:
        left = (_time(row["expires_at"]) - observed).total_seconds()
        if left <= 0:
            raise _deny()
        return started + left

    def _sql(
        self,
        function: str,
        arguments: dict[str, Any],
        parameters: str,
        budget: LocalVerifyBudget | None = None,
    ) -> Any:
        if function not in {
            "master_reserve",
            "master_attempt_scope",
            "master_attempt_resolve",
            "unstarted_master_close",
            "absent_attempt_close",
            "unadopted_follower_close",
            "master_login",
            "master_activate",
            "master_observe",
            "slot_reserve",
            "slot_observe",
            "viewer_admit",
            "viewer_selection",
            "viewer_observe",
            "viewer_activate",
            "viewer_close",
            "epoch_close",
            "dedicated_close",
            "dedicated_register",
            "focus_redeem",
            "focus_observe",
            "focus_settle",
            "focus_settlement_observe",
            "main_retention_observe",
            "wall_control_redeem",
            "wall_heartbeat_redeem",
            "focus_settle_redeem",
        }:
            raise _deny()
        remaining = budget.remaining_ms if budget else (lambda: 1000)
        with self._engine.begin() as db:
            self._worker(db, remaining)
            value: Any = db.execute(
                text(f"SELECT public.wso_tvt_local_media_{function}({parameters})"),
                arguments,
            ).scalar_one()
            remaining()
        remaining()
        return value

    @staticmethod
    def _master_args(record: _Record) -> dict[str, Any]:
        return {
            "ma": record.authority,
            "w": record.grant.scope.worker_epoch,
            "mn": record.native,
        }

    def _reservation(
        self, reservation: MasterReservation, *, expired: bool = False
    ) -> _Record:
        if type(reservation) is not MasterReservation:
            raise _deny()
        with self._mux_lock:
            if not expired and (
                reservation.master_id in self._unstarted
                or id(reservation) in self._recovered_reservations
            ):
                raise _deny()
            if (
                self._masters.get(reservation.master_id) is not reservation
                and self._followers.get(id(reservation)) is not reservation
            ):
                raise _deny()
            current = self._master_grants.get(
                reservation.master_id, reservation.transport
            )
        record = self._record(current, TransportGrant, expired=expired)
        if (
            record.master_id != reservation.master_id
            or record.grant.scope != reservation.scope
        ):
            raise _deny()
        return record

    @staticmethod
    def _scope_json(scope: MuxScopeKey) -> str:
        return json.dumps(
            {
                k: str(v) if type(v) is UUID else v.hex() if type(v) is bytes else v
                for k, v in asdict(scope).items()
            },
            separators=(",", ":"),
        )

    def _cleanup_lease(self, viewer: LocalMediaLease) -> LocalMediaLease:
        given = self._lease(viewer)
        with self._mux_lock:
            if (
                self._mux_closed
                or self._issued_leases.get(id(given)) is not given
                or given.worker_epoch != self.worker_epoch
            ):
                raise _deny()
        return given

    def begin_master_attempt(self, viewer: LocalMediaLease) -> MasterReserveAttempt:
        viewer = self._known_lease(viewer)
        handle = MasterReserveAttempt(self._issuer)
        record = _Attempt(
            handle, viewer, secrets.token_hex(32), secrets.token_hex(32), uuid4()
        )
        with self._mux_lock:
            if id(viewer) in self._attempt_leases or self._mux_closed:
                raise _deny()
            self._attempts[id(handle)] = record
            self._attempt_leases[id(viewer)] = handle
        return handle

    def _attempt(self, attempt: MasterReserveAttempt) -> _Attempt:
        with self._mux_lock:
            record = self._attempts.get(id(attempt))
            if (
                type(attempt) is not MasterReserveAttempt
                or attempt._authority is not self._issuer
                or record is None
                or record.handle is not attempt
                or self._mux_closed
            ):
                raise _deny()
        self._cleanup_lease(record.viewer)
        return record

    def _bind_attempt_scope(
        self, record: _Attempt, budget: LocalVerifyBudget
    ) -> MuxScopeKey:
        if record.scope is None:
            row = self._sql(
                "master_attempt_scope", self._args(record.viewer), ":a,:w,:n", budget
            )
            if not isinstance(row, dict):
                raise _deny()
            scope = _scope(row)
            if scope.worker_epoch != self.worker_epoch:
                raise _deny()
            with self._mux_lock:
                if record.scope is not None and record.scope != scope:
                    raise _deny()
                record.scope = scope
        return record.scope

    def _operation_args(self, record: _Attempt) -> dict[str, Any]:
        if record.scope is None:
            raise _deny()
        return {
            **self._args(record.viewer),
            "op": record.operation,
            "on": record.native,
            "scope": self._scope_json(record.scope),
        }

    def _materialize_reservation(
        self, record: _Attempt, row: dict[str, Any], *, recovery: bool
    ) -> MasterReservation:
        scope = _scope(row)
        if (
            scope != record.scope
            or _uuid(row["operation_native"]) != record.native
            or _uuid(row["lease_id"]) != record.viewer.id
            or row.get("outcome") != "RESERVED"
            or type(row.get("creator")) is not bool
        ):
            raise _deny()
        identifier, native = _uuid(row["master_id"]), _uuid(row["native_generation"])
        if record.reservation is not None:
            if (
                record.reservation.master_id != identifier
                or record.reservation.creator is not row["creator"]
            ):
                raise _deny()
            return record.reservation
        with self._mux_lock:
            creator = self._masters.get(identifier)
        if row["creator"]:
            if native != record.native:
                raise _deny()
            if creator is not None:
                if (
                    creator.scope != scope
                    or creator.transport.native_generation != native
                    or self._reservation(creator, expired=True).authority
                    != record.authority
                ):
                    raise _deny()
                reservation = creator
            else:
                now = self._clock()
                expiry = (
                    now + (_time(row["expires_at"]) - datetime.now(UTC)).total_seconds()
                )
                if recovery:
                    expiry = max(0.000001, min(expiry, now - 0.000001))
                elif expiry <= now:
                    raise _deny()
                grant = self._remember(
                    TransportGrant(
                        scope=scope,
                        expires_monotonic=expiry,
                        native_generation=native,
                        _authority=self._issuer,
                        _seal=_GRANT_SEAL,
                    ),
                    record.authority,
                    identifier,
                    native,
                )
                reservation = MasterReservation(
                    scope=scope,
                    master_id=identifier,
                    creator=True,
                    transport=grant,
                    deadline_monotonic=min(expiry, record.deadline or expiry),
                    _seal=_GRANT_SEAL,
                )
                with self._mux_lock:
                    self._masters[identifier] = reservation
                    self._master_grants[identifier] = grant
                    if row.get("creator_channel") is not None:
                        self._creator_channels[identifier] = bytes.fromhex(
                            row["creator_channel"]
                        )
        else:
            if (
                creator is None
                or creator.scope != scope
                or creator.transport.native_generation != native
            ):
                raise _deny()  # Resolve the retained canonical creator first.
            transport = cast(
                TransportGrant, self._reservation(creator, expired=True).grant
            )
            reservation = MasterReservation(
                scope=scope,
                master_id=identifier,
                creator=False,
                transport=transport,
                deadline_monotonic=min(
                    transport.expires_monotonic,
                    record.deadline or transport.expires_monotonic,
                ),
                _seal=_GRANT_SEAL,
            )
            with self._mux_lock:
                self._followers[id(reservation)] = reservation
        with self._mux_lock:
            record.reservation = reservation
            if not reservation.creator:
                self._follower_attempts[id(reservation)] = record
            self._lease_masters[id(record.viewer)] = identifier
            if recovery:
                self._recovered_reservations.add(id(reservation))
            self._pending_reservations.pop(record.authority, None)
        return reservation

    @_boundary
    def reserve_master(
        self,
        viewer: LocalMediaLease,
        *,
        budget: LocalVerifyBudget,
        attempt: MasterReserveAttempt | None = None,
    ) -> MasterReservation:
        viewer = self._known_lease(viewer)
        attempt = self.begin_master_attempt(viewer) if attempt is None else attempt
        record = self._attempt(attempt)
        with self._mux_lock:
            if (
                record.viewer is not viewer
                or record.phase != "NEW"
                or id(viewer) in self._lease_cleanup
            ):
                raise _deny()
            record.phase = "RUNNING"
            self._pending_reservations[record.authority] = (viewer, record.native)
        acquired, keep = False, False
        try:
            record.deadline = self._clock() + budget.remaining_ms() / 1000
            until = time.monotonic() + 10
            while True:
                remaining = min(until - time.monotonic(), budget.remaining_ms() / 1000)
                if remaining <= 0:
                    raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)
                if self._startup_slots.acquire(timeout=min(0.05, remaining)):
                    acquired = True
                    break
            scope = self._bind_attempt_scope(record, budget)
            row = self._sql(
                "master_reserve",
                {
                    **self._args(viewer),
                    "ma": record.authority,
                    "mn": record.native,
                    "op": record.operation,
                    "scope": self._scope_json(scope),
                },
                ":a,:w,:n,:ma,:mn,:op,CAST(:scope AS jsonb)",
                budget,
            )
            if not isinstance(row, dict):
                raise _deny()
            reservation = self._materialize_reservation(record, row, recovery=False)
            if reservation.creator:
                with self._mux_lock:
                    self._startup_held.add(reservation.master_id)
                keep = True
            return reservation
        finally:
            with self._mux_lock:
                record.phase = "SETTLED"
            if acquired and not keep:
                self._startup_slots.release()

    def resolve_master_attempt(
        self, attempt: MasterReserveAttempt, *, budget: LocalVerifyBudget
    ) -> MasterAttemptResolution | None:
        record = self._attempt(attempt)
        with self._mux_lock:
            if record.phase in {"RUNNING", "RESOLVING"}:
                return None
            if record.resolution is not None:
                return record.resolution
            record.phase = "RESOLVING"  # Permanently prevents any first/late dispatch.
        try:
            self._bind_attempt_scope(record, budget)
            row = self._sql(
                "master_attempt_resolve",
                self._operation_args(record),
                ":a,:w,:n,:op,:on,CAST(:scope AS jsonb)",
                budget,
            )
            if (
                not isinstance(row, dict)
                or _scope(row) != record.scope
                or _uuid(row["operation_native"]) != record.native
                or _uuid(row["lease_id"]) != record.viewer.id
            ):
                return None
            if row.get("outcome") == "ABSENT":
                reservation = None
                outcome: Literal["ABSENT", "RESERVED"] = "ABSENT"
            elif row.get("outcome") == "RESERVED":
                reservation = self._materialize_reservation(
                    record, row, recovery=record.reservation is None
                )
                outcome = "RESERVED"
            else:
                return None
            result = MasterAttemptResolution(outcome, reservation, self._issuer)
            with self._mux_lock:
                record.resolution = result
            return result
        except Exception:  # noqa: BLE001 -- unknown lookup remains charged.
            return None
        finally:
            with self._mux_lock:
                record.phase = (
                    "RESOLVED" if record.resolution is not None else "SETTLED"
                )

    def master_resolution_current(
        self, attempt: MasterReserveAttempt, resolution: MasterAttemptResolution
    ) -> bool:
        try:
            record = self._attempt(attempt)
            return (
                type(resolution) is MasterAttemptResolution
                and resolution._authority is self._issuer
                and record.resolution is resolution
                and resolution.reservation is record.reservation
            )
        except LocalDeviceFailure:
            return False

    @_boundary
    def prepare_login(
        self, reservation: MasterReservation, *, budget: LocalVerifyBudget
    ) -> tuple[LocalDeviceCredentials, TransportGrant]:
        record = self._reservation(reservation)
        if not reservation.creator or self._clock() >= reservation.deadline_monotonic:
            raise _deny()
        self._mark_acquisition(reservation.master_id)
        row = self._sql("master_login", self._master_args(record), ":ma,:w,:mn", budget)
        if not isinstance(row, dict) or _scope(row) != reservation.scope:
            raise _deny()
        # No connection/transaction is retained across decryption or native login.
        raw = self._cipher.open(
            reservation.scope.tenant_id,
            reservation.scope.connection_id,
            reservation.scope.secret_version,
            Envelope(bytes.fromhex(row["nonce"]), bytes.fromhex(row["ciphertext"])),
        )
        try:
            credentials = parse_local_device_credentials(raw)
        finally:
            del raw, row
        if (
            self._clock() >= reservation.deadline_monotonic
            or not self.current_transport(reservation.transport)
        ):
            raise _deny()
        budget.remaining_ms()
        return credentials, reservation.transport

    def register_original(
        self,
        reservation: MasterReservation,
        issuer: OriginalMuxBindingIssuer,
        custody: EpochReceiptIssuer,
    ) -> None:
        self._reservation(reservation)
        if not reservation.creator:
            raise _deny()
        self._mark_acquisition(reservation.master_id)
        # Retain bound callables as well as objects: later method replacement is
        # a provenance change, never a replacement original.
        original = _Original(
            reservation, issuer, custody, issuer.binding_for, custody.issued_receipt
        )
        with self._mux_lock:
            if reservation.master_id in self._originals or self._mux_closed:
                raise _deny()
            self._originals[reservation.master_id] = original

    def _original(
        self, reservation: MasterReservation, *, expired: bool = False
    ) -> _Original:
        self._reservation(reservation, expired=expired)
        with self._mux_lock:
            original = self._originals.get(reservation.master_id)
        if (
            original is None
            or original.reservation is not self._masters.get(reservation.master_id)
            or original.issuer.binding_for != original.binding_for
            or original.custody.issued_receipt != original.issued_receipt
        ):
            raise _deny()
        return original

    @_boundary
    def activate_master(
        self,
        reservation: MasterReservation,
        proof: MasterLoginProof,
        *,
        budget: LocalVerifyBudget,
    ) -> TransportGrant:
        record = self._reservation(reservation)
        if not reservation.creator or self._clock() >= reservation.deadline_monotonic:
            raise _deny()
        original = self._original(reservation)
        if type(proof) is not MasterLoginProof or not all(
            (
                proof.login_accepted,
                proof.same_original_session,
                proof.serial_matched,
                proof.device_matched,
                proof.inventory_session_matched,
            )
        ):
            raise _deny()
        binding = original.binding_for(self._creator_channels[reservation.master_id])
        if (
            type(binding) is not OriginalMuxBinding
            or self._binding(reservation, binding) is not original
            or binding.proof is not proof
        ):
            raise _deny()
        row = self._sql(
            "master_activate",
            {**self._master_args(record), "proof": json.dumps(asdict(proof))},
            ":ma,:w,:mn,CAST(:proof AS jsonb)",
            budget,
        )
        if not isinstance(row, dict) or _scope(row) != reservation.scope:
            raise _deny()
        self._original(reservation)
        if self._clock() >= reservation.deadline_monotonic:
            raise _deny()
        self._release_start(reservation.master_id)
        return reservation.transport

    def _release_start(self, master_id: UUID) -> None:
        with self._mux_lock:
            held = master_id in self._startup_held
            self._startup_held.discard(master_id)
        if held:
            self._startup_slots.release()

    def _binding(
        self, reservation: MasterReservation, binding: OriginalMuxBinding
    ) -> _Original:
        original = self._original(reservation)
        if (
            type(binding) is not OriginalMuxBinding
            or binding.scope != reservation.scope
            or binding.master_id != reservation.master_id
            or binding.native_generation != reservation.transport.native_generation
        ):
            raise _deny()
        returned = original.binding_for(binding.channel)
        if returned is not binding or self._original(reservation) is not original:
            raise _deny()
        if (
            binding.scope != reservation.scope
            or binding.master_id != reservation.master_id
            or binding.native_generation != reservation.transport.native_generation
        ):
            raise _deny()
        with self._mux_lock:
            previous = self._bindings.get(reservation.master_id)
            if previous is not None and (
                previous[0].epoch != binding.epoch
                or previous[1] is not binding._authority
            ):
                raise _deny()
            self._bindings[reservation.master_id] = (binding, binding._authority)
        return original

    @_boundary
    def reserve_slot(
        self,
        viewer: LocalMediaLease,
        reservation: MasterReservation,
        *,
        binding: OriginalMuxBinding,
        budget: LocalVerifyBudget,
    ) -> SlotRetentionGrant:
        viewer = self._known_lease(viewer)
        record = self._reservation(reservation)
        self._mark_acquisition(reservation.master_id, viewer)
        original = self._binding(reservation, binding)
        token, task = secrets.token_hex(32), uuid4()
        started, observed = self._clock(), datetime.now(UTC)
        row = self._sql(
            "slot_reserve",
            {
                **self._args(viewer),
                **self._master_args(record),
                "sa": token,
                "task": task,
                "wg": binding.epoch.generation,
                "ws": binding.epoch.session,
                "ch": binding.channel,
            },
            ":a,:w,:n,:ma,:mn,:sa,:task,:wg,:ws,:ch",
            budget,
        )
        if (
            not isinstance(row, dict)
            or _scope(row) != reservation.scope
            or self._binding(reservation, binding) is not original
        ):
            raise _deny()
        slot_id = _uuid(row["slot_id"])
        with self._mux_lock:
            existing = next(
                (
                    r
                    for r in self._records.values()
                    if type(r.grant) is SlotRetentionGrant
                    and r.slot_id == slot_id
                    and not r.denied
                    and not r.closed
                ),
                None,
            )
        if existing:
            self._record(existing.grant, SlotRetentionGrant)
            return cast(SlotRetentionGrant, existing.grant)
        if (
            _uuid(row["task_id"]) != task
            or bytes.fromhex(row["channel_guid"]) != binding.channel
        ):
            raise _deny()
        slot = MuxSlotIdentity(binding.epoch, binding.channel, task.bytes_le, 2)
        expiry = min(
            record.grant.expires_monotonic,
            self._expiry(row, started, observed),
        )
        return self._remember(
            SlotRetentionGrant(
                scope=reservation.scope,
                slot=slot,
                expires_monotonic=expiry,
                _authority=self._issuer,
                _seal=_GRANT_SEAL,
            ),
            token,
            record.master_id,
            record.native,
            slot_id=slot_id,
        )

    @_boundary
    def admit_viewer(
        self,
        viewer: LocalMediaLease,
        slot: SlotRetentionGrant,
        *,
        registration: UUID,
        budget: LocalVerifyBudget,
    ) -> ViewerGrant:
        viewer = self._known_lease(viewer)
        record = self._record(slot, SlotRetentionGrant)
        self._mark_acquisition(record.master_id, viewer)
        if (
            viewer.worker_epoch != slot.scope.worker_epoch
            or type(registration) is not UUID
        ):
            raise _deny()
        started, observed = self._clock(), datetime.now(UTC)
        row = self._sql(
            "viewer_admit",
            {**self._args(viewer), "r": registration, "sa": record.authority},
            ":a,:w,:n,:r,:sa",
            budget,
        )
        if (
            not isinstance(row, dict)
            or _scope(row) != slot.scope
            or _uuid(row["lease_id"]) != viewer.id
            or _uuid(row["registration"]) != registration
        ):
            raise _deny()
        expiry = min(slot.expires_monotonic, self._expiry(row, started, observed))
        return self._remember(
            ViewerGrant(
                scope=slot.scope,
                slot=slot.slot,
                lease_id=viewer.id,
                registration=registration,
                expires_monotonic=expiry,
                _authority=self._issuer,
                _seal=_GRANT_SEAL,
            ),
            viewer.token,
            record.master_id,
            viewer.native_generation,
            lease=viewer,
            slot_id=record.slot_id,
        )

    def _observe(self, record: _Record) -> dict[str, Any] | None:
        grant = record.grant
        if type(grant) is TransportGrant:
            value = self._sql("master_observe", self._master_args(record), ":ma,:w,:mn")
        elif type(grant) is SlotRetentionGrant:
            value = self._sql(
                "slot_observe",
                {
                    "sa": record.authority,
                    "w": grant.scope.worker_epoch,
                    "mn": record.native,
                },
                ":sa,:w,:mn",
            )
        elif type(grant) is ViewerGrant:
            if record.lease is None:
                raise _deny()
            value = self._sql(
                "viewer_observe",
                {**self._args(record.lease), "r": grant.registration},
                ":a,:w,:n,:r",
            )
        elif type(grant) is FocusGrant:
            value = self._sql(
                "focus_observe",
                {"fa": record.authority, "w": grant.scope.worker_epoch},
                ":fa,:w",
            )
        else:
            raise _deny()
        if value is not None:
            if (
                not isinstance(value, dict)
                or _scope(value) != grant.scope
                or _uuid(value["master_id"]) != record.master_id
            ):
                raise _deny()
            if (
                type(grant) is TransportGrant
                and _uuid(value["native_generation"]) != grant.native_generation
            ):
                raise _deny()
            if type(grant) is SlotRetentionGrant and (
                _uuid(value["task_id"]).bytes_le != grant.slot.task
                or bytes.fromhex(value["channel_guid"]) != grant.slot.channel
            ):
                raise _deny()
        return cast(dict[str, Any] | None, value)

    def _current(self, grant: object, kind: type[G]) -> bool:
        try:
            record = self._record(grant, kind)
        except LocalDeviceFailure:
            with self._mux_lock:
                denied = self._records.get(id(grant))
            if denied is not None and denied.grant is grant and type(grant) is kind:
                self._fence_for(denied)
            return False
        began, me = self._clock(), get_ident()
        waited, deadline = False, 0.0
        with record.condition:
            while True:
                if (
                    record.denied
                    or record.closed
                    or record.master_id in self._denied_masters
                ):
                    return False
                if record.runner is None:
                    if record.value is not None and (
                        self._clock() < record.valid_until
                        or (
                            waited
                            and record.started > began - AUTHORITY_FRESHNESS_SECONDS
                        )
                    ):
                        return True
                    break
                if record.runner == me:
                    return False
                now = time.monotonic()
                if not waited:
                    waited, deadline = True, now + AUTHORITY_WAIT_SECONDS
                elif now >= deadline:
                    record.denied = True
                    record.condition.notify_all()
                    self._fence_for(record)
                    return False
                record.condition.wait(deadline - now)
            record.runner = me
        started, observed = self._clock(), datetime.now(UTC)
        try:
            value = self._observe(record)
        except BaseException:  # noqa: BLE001 -- every failed authority check permanently denies.
            with record.condition:
                record.runner = None
                record.denied = True
                record.condition.notify_all()
            self._fence_for(record)
            return False
        with record.condition:
            record.runner = None
            if (
                value is None
                or record.denied
                or record.closed
                or record.master_id in self._denied_masters
            ):
                record.denied = True
                record.condition.notify_all()
                self._fence_for(record)
                return False
            left = (_time(value["expires_at"]) - observed).total_seconds()
            record.value, record.started = value, started
            record.valid_until = min(
                started + AUTHORITY_FRESHNESS_SECONDS,
                started + left,
                record.grant.expires_monotonic,
            )
            record.condition.notify_all()
            # R120 slow success answers only its eligible invocation; the cache
            # remains anchored at check start and may already have expired.
            return True

    def _fence_for(self, record: _Record) -> None:
        # A known retained-slot/transport denial dominates cached answers for
        # this exact registered original. Other masters remain independent.
        if (
            type(record.grant) in (TransportGrant, SlotRetentionGrant)
            and not record.closed
        ):
            with self._mux_lock:
                self._denied_masters.add(record.master_id)

    def current_transport(self, grant: TransportGrant) -> bool:
        return self._current(grant, TransportGrant)

    def current_slot(self, grant: SlotRetentionGrant) -> bool:
        return self._current(grant, SlotRetentionGrant)

    def current_viewer(self, grant: ViewerGrant) -> bool:
        return self._current(grant, ViewerGrant)

    def current_focus(self, grant: FocusGrant) -> bool:
        return self._current(grant, FocusGrant)

    @_boundary
    def activate_viewer(
        self, grant: ViewerGrant, proof: LocalLiveProof, *, budget: LocalVerifyBudget
    ) -> MediaLease:
        record = self._record(grant, ViewerGrant)
        if type(proof) is not LocalLiveProof or record.lease is None:
            raise _deny()
        proof.validate(delivery=False)
        row = self._sql(
            "viewer_activate",
            {
                **self._args(record.lease),
                "r": grant.registration,
                "p": json.dumps(asdict(proof)),
            },
            ":a,:w,:n,:r,CAST(:p AS jsonb)",
            budget,
        )
        if row is None:
            raise _deny()
        view = MediaLease.model_validate(row)
        if view.id != grant.lease_id or view.state != "NEGOTIATING":
            raise _deny()
        return view

    def register_viewer_custodian(
        self, grant: ViewerGrant, custody: ViewerReceiptIssuer
    ) -> None:
        self._record(grant, ViewerGrant)
        record = _ViewerCustody(grant, custody, custody.issued_receipt)
        with self._mux_lock:
            if grant.lease_id in self._viewer_custody:
                raise _deny()
            self._viewer_custody[grant.lease_id] = record

    @_boundary
    def finish_viewer(
        self, grant: ViewerGrant, receipt: ViewerCleanupReceipt, *, scope: CleanupScope
    ) -> None:
        record = self._record(grant, ViewerGrant, expired=True)
        with self._mux_lock:
            custody = self._viewer_custody.get(grant.lease_id)
        if (
            type(receipt) is not ViewerCleanupReceipt
            or type(scope) is not CleanupScope
            or custody is None
            or custody.grant is not grant
            or custody.owner.issued_receipt != custody.issued_receipt
        ):
            raise _deny()
        actual = custody.issued_receipt()
        self._record(grant, ViewerGrant, expired=True)
        with self._mux_lock:
            retained = self._viewer_custody.get(grant.lease_id)
        if (
            actual is not receipt
            or retained is not custody
            or custody.owner.issued_receipt != custody.issued_receipt
            or receipt.lease_id != grant.lease_id
            or receipt.registration_id != grant.registration
            or record.lease is None
        ):
            raise _deny()
        self._retire(record)
        payload = {
            "lease_id": str(receipt.lease_id),
            "registration_id": str(receipt.registration_id),
            "decoder_settled": receipt.decoder_settled,
            "peer_settled": receipt.peer_settled,
            "media_cleared": receipt.media_cleared,
        }
        self._sql(
            "viewer_close",
            {
                **self._args(record.lease),
                "r": grant.registration,
                "scope": scope.value,
                "receipt": json.dumps(payload),
            },
            ":a,:w,:n,:r,:scope,CAST(:receipt AS jsonb)",
        )
        # CLOSED here records viewer receipt delivery only. Epoch disposal below
        # still requires its separately registered original custodian.
        record.closed = True

    @staticmethod
    def _retire(record: _Record) -> None:
        with record.condition:
            record.denied = True
            record.value = None
            record.condition.notify_all()

    @_boundary
    def finish_epoch(self, grant: TransportGrant, receipt: EpochCleanupReceipt) -> None:
        record = self._record(grant, TransportGrant, expired=True)
        if type(receipt) is not EpochCleanupReceipt:
            raise _deny()
        with self._mux_lock:
            reservation = self._masters.get(record.master_id)
        if reservation is None:
            raise _deny()
        original = self._original(reservation, expired=True)
        actual = original.issued_receipt()
        if (
            self._original(reservation, expired=True) is not original
            or actual is not receipt
            or receipt.master_id != record.master_id
            or receipt.worker_epoch != grant.scope.worker_epoch
            or receipt.native_generation != grant.native_generation
        ):
            raise _deny()
        self._retire(record)
        payload = {
            key: str(value) if isinstance(value, UUID) else value
            for key, value in asdict(receipt).items()
            if key != "_authority"
        }
        self._sql(
            "epoch_close",
            {**self._master_args(record), "receipt": json.dumps(payload)},
            ":ma,:w,:mn,CAST(:receipt AS jsonb)",
        )
        record.closed = True
        self._release_start(record.master_id)
        with self._mux_lock:
            related = [
                r
                for r in self._records.values()
                if r.master_id == record.master_id
                and r.native == receipt.native_generation
                and r.grant.scope.worker_epoch == receipt.worker_epoch
            ]
        for other in related:
            self._retire(other)
            # Refresh may register a new transport before Core's native
            # replacement succeeds. The exact confirmed original epoch receipt
            # settles every retained transport variant, never viewer custody.
            if type(other.grant) in (TransportGrant, SlotRetentionGrant):
                other.closed = True

    @_boundary
    def redeem_focus(self, ticket: str, *, budget: LocalVerifyBudget) -> FocusGrant:
        started, observed = self._clock(), datetime.now(UTC)
        row = self._sql(
            "focus_redeem", {"t": ticket, "w": self.worker_epoch}, ":t,:w", budget
        )
        if not isinstance(row, dict):
            raise _deny()
        expiry = min(started + 20, self._expiry(row, started, observed))
        scope = _scope(row)
        grant = FocusGrant(
            scope=scope,
            lease_id=_uuid(row["lease_id"]),
            direction=row["direction"],
            admitted_monotonic=started,
            expires_monotonic=expiry,
            _authority=self._issuer,
            _seal=_GRANT_SEAL,
        )
        return self._remember(
            grant,
            row["authority"],
            _uuid(row["master_id"]),
            _uuid(row["native_generation"]),
            focus_id=_uuid(row["focus_id"]),
        )

    @_boundary
    def settle_focus(
        self, grant: FocusGrant, transition: str, *, viewer: UUID | None = None
    ) -> FocusSettlement:
        if transition not in {"ATTACHED", "CANCELLED", "FAILED", "EXPIRED"}:
            raise _deny()
        record = self._record(grant, FocusGrant, expired=transition != "ATTACHED")
        if transition == "ATTACHED" and (type(viewer) is not UUID or not viewer.int):
            raise _deny()
        row = self._sql(
            "focus_settle",
            {
                "fa": record.authority,
                "w": grant.scope.worker_epoch,
                "t": transition,
                "v": viewer,
            },
            ":fa,:w,:t,:v",
        )
        acknowledgement = self._focus_ack(record, grant, row, transition, viewer)
        # NULL/error/declined transitions never retire a still-pending record.
        # A successful but late acknowledgement remains available for terminal
        # cleanup. The coordinator checks its own deadline/target after observing.
        with self._mux_lock:
            if self._mux_closed or self._records.get(id(grant)) is not record:
                raise _deny()
            self._focus_settlements[id(grant)] = acknowledgement
        self._retire(record)
        record.closed = True
        return acknowledgement

    def _focus_ack(
        self,
        record: _Record,
        grant: FocusGrant,
        row: Any,
        transition: str,
        viewer: UUID | None,
    ) -> FocusSettlement:
        try:
            if (
                not isinstance(row, dict)
                or _scope(row) != grant.scope
                or _uuid(row["master_id"]) != record.master_id
                or _uuid(row["native_generation"]) != record.native
                or _uuid(row["focus_id"]) != record.focus_id
                or _uuid(row["lease_id"]) != grant.lease_id
                or row["direction"] != grant.direction
            ):
                raise _deny()
            state = row["state"]
            attached = (
                None
                if row["attached_viewer"] is None
                else _uuid(row["attached_viewer"])
            )
            if transition == "ATTACHED":
                expected = "MAIN_ACTIVE" if grant.direction == "FORWARD" else "ATTACHED"
                if state != expected or attached != viewer or viewer is None:
                    raise _deny()
            elif (
                transition not in {"CANCELLED", "FAILED", "EXPIRED"}
                or state not in _FOCUS_TERMINAL
                or (viewer is not None and attached is not None and attached != viewer)
            ):
                raise _deny()
            return FocusSettlement(
                record.focus_id,
                grant.scope.wall_id,
                cast(FocusState, state),
                attached,
                self._issuer,
            )
        except (KeyError, TypeError, ValueError):
            raise _deny() from None

    def focus_settlement_current(
        self,
        grant: FocusGrant,
        acknowledgement: FocusSettlement,
        transition: str,
        *,
        viewer: UUID | None = None,
    ) -> bool:
        try:
            record = self._record(grant, FocusGrant, expired=True)
            with self._mux_lock:
                if (
                    type(acknowledgement) is not FocusSettlement
                    or acknowledgement._authority is not self._issuer
                    or self._focus_settlements.get(id(grant)) is not acknowledgement
                ):
                    return False
            row = self._sql(
                "focus_settlement_observe",
                {"fa": record.authority, "w": grant.scope.worker_epoch},
                ":fa,:w",
            )
            current = self._focus_ack(record, grant, row, transition, viewer)
            self._record(grant, FocusGrant, expired=True)
            with self._mux_lock:
                accepted = (
                    self._focus_settlements.get(id(grant)) is acknowledgement
                    and current == acknowledgement
                )
                if (
                    not accepted
                    and self._focus_settlements.get(id(grant)) is acknowledgement
                ):
                    del self._focus_settlements[id(grant)]
                return accepted
        except Exception:  # noqa: BLE001 -- failed current observation cannot authorize a transfer.
            with self._mux_lock:
                if self._focus_settlements.get(id(grant)) is acknowledgement:
                    del self._focus_settlements[id(grant)]
            return False

    def current_main_retention(
        self,
        viewer: LocalMediaLease,
        grant: FocusGrant,
        acknowledgement: FocusSettlement,
    ) -> bool:
        """Fresh exact original MAIN authority across a current SQL RETURN."""
        try:
            given = self._known_lease(viewer)
            custody = self._dedicated_owner(given)
            record = self._record(grant, FocusGrant, expired=True)
            with self._mux_lock:
                if (
                    type(acknowledgement) is not FocusSettlement
                    or acknowledgement._authority is not self._issuer
                    or self._focus_settlements.get(id(grant)) is not acknowledgement
                    or grant.direction != "FORWARD"
                    or acknowledgement.state != "MAIN_ACTIVE"
                    or acknowledgement.attached_viewer != given.id
                    or custody.scope != grant.scope
                ):
                    return False
            started, observed = self._clock(), datetime.now(UTC)
            row = self._sql(
                "main_retention_observe",
                {"fa": record.authority, "w": grant.scope.worker_epoch, "v": given.id},
                ":fa,:w,:v",
            )
            if (
                not isinstance(row, dict)
                or _scope(row) != grant.scope
                or _uuid(row["master_id"]) != record.master_id
                or _uuid(row["native_generation"]) != record.native
                or _uuid(row["focus_id"]) != record.focus_id
                or _uuid(row["wall_id"]) != grant.scope.wall_id
                or _uuid(row["lease_id"]) != grant.lease_id
                or row["direction"] != "FORWARD"
                or _uuid(row["attached_viewer"]) != given.id
                or _uuid(row["main_id"]) != given.id
                or _uuid(row["dedicated_native_generation"]) != given.native_generation
                or (
                    row["retention_state"] == "MAIN_ACTIVE"
                    and (
                        row["state"] != "MAIN_ACTIVE"
                        or row["return_focus_id"] is not None
                    )
                )
                or (
                    row["retention_state"] == "RETURN_PENDING"
                    and (
                        row["state"] != "CONSUMED"
                        or not _uuid(row["return_focus_id"]).int
                        or _uuid(row["return_focus_id"]) == record.focus_id
                    )
                )
                or row["retention_state"] not in {"MAIN_ACTIVE", "RETURN_PENDING"}
                or self._clock() >= self._expiry(row, started, observed)
            ):
                return False
            self._record(grant, FocusGrant, expired=True)
            if (
                self._known_lease(given) is not given
                or self._dedicated_owner(given) is not custody
            ):
                return False
            with self._mux_lock:
                return self._focus_settlements.get(id(grant)) is acknowledgement
        except Exception:  # noqa: BLE001 -- no retention from unknown/stale observations
            return False

    def shutdown(self) -> bool:
        return self.dispose()

    def _mark_acquisition(
        self, master_id: UUID, viewer: LocalMediaLease | None = None
    ) -> None:
        with self._mux_lock:
            if (
                self._mux_closed
                or master_id in self._unstarted
                or (viewer is not None and id(viewer) in self._lease_cleanup)
            ):
                raise _deny()
            self._master_acquired.add(master_id)
            if viewer is not None:
                self._lease_acquired.add(id(viewer))

    def claim_unstarted_master(
        self, reservation: MasterReservation
    ) -> UnstartedMasterClaim:
        self._reservation(reservation, expired=True)
        with self._mux_lock:
            if (
                self._masters.get(reservation.master_id) is not reservation
                or not reservation.creator
                or reservation.master_id in self._master_acquired
                or reservation.master_id in self._originals
                or reservation.master_id in self._bindings
                or any(
                    r.master_id == reservation.master_id
                    and type(r.grant) in (SlotRetentionGrant, ViewerGrant)
                    for r in self._records.values()
                )
            ):
                raise _deny()
            existing = self._unstarted.get(reservation.master_id)
            if existing is not None:
                return existing.claim
            claim = UnstartedMasterClaim(reservation, self._issuer)
            self._unstarted[reservation.master_id] = _Unstarted(claim)
            self._denied_masters.add(reservation.master_id)
            return claim

    def _unstarted_claim(self, claim: UnstartedMasterClaim) -> _Unstarted:
        if (
            type(claim) is not UnstartedMasterClaim
            or claim._authority is not self._issuer
        ):
            raise _deny()
        self._reservation(claim.reservation, expired=True)
        with self._mux_lock:
            record = self._unstarted.get(claim.reservation.master_id)
            if record is None or record.claim is not claim:
                raise _deny()
        return record

    def register_unstarted_original(
        self,
        claim: UnstartedMasterClaim,
        issuer: OriginalMuxBindingIssuer,
        custody: EpochReceiptIssuer,
    ) -> None:
        record = self._unstarted_claim(claim)
        with self._mux_lock:
            if record.issuer is not None and (
                record.issuer is not issuer or record.custody is not custody
            ):
                raise _deny()
            record.issuer, record.custody = issuer, custody
            if record.original is not None:
                raise _deny()
        # Retain the original supplier identities before invoking any getters.
        original = _Original(
            claim.reservation,
            issuer,
            custody,
            issuer.binding_for,
            custody.issued_receipt,
        )
        self._unstarted_claim(claim)
        with self._mux_lock:
            if (
                record.issuer is not issuer
                or record.custody is not custody
                or record.original is not None
                or claim.reservation.master_id in self._originals
            ):
                raise _deny()
            record.original = original
            self._originals[claim.reservation.master_id] = original

    @_boundary
    def finish_unstarted_master(
        self,
        claim: UnstartedMasterClaim,
        receipt: EpochCleanupReceipt,
        *,
        budget: LocalVerifyBudget,
    ) -> UnstartedMasterClosure:
        record = self._unstarted_claim(claim)
        with self._mux_lock:
            if record.finishing:
                raise _deny()
            record.finishing = True
        try:
            original = self._original(claim.reservation, expired=True)
            if (
                original is not record.original
                or type(receipt) is not EpochCleanupReceipt
                or original.issued_receipt() is not receipt
                or self._original(claim.reservation, expired=True) is not original
                or receipt.original_state != "NOT_CREATED"
                or (receipt.master_id, receipt.worker_epoch, receipt.native_generation)
                != (
                    claim.reservation.master_id,
                    claim.reservation.scope.worker_epoch,
                    claim.reservation.transport.native_generation,
                )
            ):
                raise _deny()
            self._unstarted_claim(claim)
            if record.closure is not None:
                return record.closure
            transport = self._reservation(claim.reservation, expired=True)
            payload = {
                k: str(v) if type(v) is UUID else v
                for k, v in asdict(receipt).items()
                if k != "_authority"
            }
            row = self._sql(
                "unstarted_master_close",
                {
                    **self._master_args(transport),
                    "scope": self._scope_json(claim.reservation.scope),
                    "receipt": json.dumps(payload),
                },
                ":ma,:w,:mn,CAST(:scope AS jsonb),CAST(:receipt AS jsonb)",
                budget,
            )
            if (
                not isinstance(row, dict)
                or _scope(row) != claim.reservation.scope
                or _uuid(row["master_id"]) != claim.reservation.master_id
                or _uuid(row["native_generation"]) != receipt.native_generation
                or row.get("closed") is not True
                or not isinstance(row.get("lease_ids"), list)
            ):
                raise _deny()
            closure = UnstartedMasterClosure(
                receipt.master_id,
                tuple(_uuid(v) for v in row["lease_ids"]),
                self._issuer,
            )
            if not closure.lease_ids:
                raise _deny()
            self._unstarted_claim(claim)
            with self._mux_lock:
                record.closure = closure
                related = [
                    r
                    for r in self._records.values()
                    if r.master_id == receipt.master_id
                ]
                leases = [
                    v for v in self._issued_leases.values() if v.id in closure.lease_ids
                ]
                for v in leases:
                    self._lease_cleanup.add(id(v))
            for r in related:
                self._retire(r)
                r.closed = True
            for v in leases:
                self._retire_authority(v.token)
            self._release_start(receipt.master_id)
            return closure
        finally:
            with self._mux_lock:
                record.finishing = False

    def unstarted_master_closed(
        self, claim: UnstartedMasterClaim, closure: UnstartedMasterClosure
    ) -> bool:
        try:
            record = self._unstarted_claim(claim)
            return (
                type(closure) is UnstartedMasterClosure
                and closure._authority is self._issuer
                and record.closure is closure
                and closure.master_id == claim.reservation.master_id
            )
        except LocalDeviceFailure:
            return False

    @_boundary
    def finish_absent_attempt(
        self,
        attempt: MasterReserveAttempt,
        resolution: MasterAttemptResolution,
        *,
        budget: LocalVerifyBudget,
    ) -> UnadoptedViewerClosure:
        record = self._attempt(attempt)
        if (
            not self.master_resolution_current(attempt, resolution)
            or resolution.outcome != "ABSENT"
            or record.scope is None
        ):
            raise _deny()
        with self._mux_lock:
            if (
                id(record.viewer) in self._lease_acquired
                or id(record.viewer) in self._lease_masters
            ):
                raise _deny()
            self._lease_cleanup.add(id(record.viewer))
            if record.closure is not None:
                return record.closure
        row = self._sql(
            "absent_attempt_close",
            self._operation_args(record),
            ":a,:w,:n,:op,:on,CAST(:scope AS jsonb)",
            budget,
        )
        if (
            not isinstance(row, dict)
            or _scope(row) != record.scope
            or row.get("master_id") is not None
            or _uuid(row["lease_id"]) != record.viewer.id
            or row.get("closed") is not True
        ):
            raise _deny()
        closure = UnadoptedViewerClosure(None, _uuid(row["lease_id"]), self._issuer)
        with self._mux_lock:
            record.closure = closure
            self._pending_reservations.pop(record.authority, None)
        self._retire_authority(record.viewer.token)
        return closure

    def absent_attempt_closed(
        self,
        attempt: MasterReserveAttempt,
        resolution: MasterAttemptResolution,
        closure: UnadoptedViewerClosure,
    ) -> bool:
        try:
            record = self._attempt(attempt)
            return (
                self.master_resolution_current(attempt, resolution)
                and resolution.outcome == "ABSENT"
                and type(closure) is UnadoptedViewerClosure
                and closure._authority is self._issuer
                and record.closure is closure
                and closure.master_id is None
                and closure.lease_id == record.viewer.id
            )
        except LocalDeviceFailure:
            return False

    def _follower_operation_locked(
        self, viewer: LocalMediaLease, reservation: MasterReservation
    ) -> _Attempt:
        operation = self._follower_attempts.get(id(reservation))
        if (
            reservation.creator
            or self._followers.get(id(reservation)) is not reservation
            or operation is None
            or operation.viewer is not viewer
            or operation.reservation is not reservation
            or operation.scope != reservation.scope
            or self._attempts.get(id(operation.handle)) is not operation
            or operation.handle._authority is not self._issuer
            or operation.phase in {"NEW", "RUNNING", "RESOLVING"}
            or self._lease_masters.get(id(viewer)) != reservation.master_id
        ):
            raise _deny()
        return operation

    @_boundary
    def finish_unadopted_follower(
        self,
        viewer: LocalMediaLease,
        reservation: MasterReservation,
        *,
        budget: LocalVerifyBudget,
    ) -> UnadoptedViewerClosure:
        viewer = self._cleanup_lease(viewer)
        transport = self._reservation(reservation, expired=True)
        with self._mux_lock:
            operation = self._follower_operation_locked(viewer, reservation)
        creator = self._masters[reservation.master_id]
        original = self._original(creator, expired=True)
        with self._mux_lock:
            if (
                self._follower_operation_locked(viewer, reservation) is not operation
                or id(viewer) in self._lease_acquired
            ):
                raise _deny()
            self._lease_cleanup.add(id(viewer))
            prior = self._follower_closures.get(id(reservation))
            if prior is not None:
                if prior[0] is not viewer:
                    raise _deny()
                return prior[2]
        row = self._sql(
            "unadopted_follower_close",
            {
                **self._args(viewer),
                **self._master_args(transport),
                "scope": self._scope_json(reservation.scope),
                "op": operation.operation,
                "on": operation.native,
            },
            ":a,:w,:n,:ma,:mn,CAST(:scope AS jsonb),:op,:on",
            budget,
        )
        if (
            not isinstance(row, dict)
            or _scope(row) != reservation.scope
            or _uuid(row["master_id"]) != reservation.master_id
            or _uuid(row["lease_id"]) != viewer.id
            or row.get("closed") is not True
            or self._original(creator, expired=True) is not original
        ):
            raise _deny()
        closure = UnadoptedViewerClosure(
            reservation.master_id, _uuid(row["lease_id"]), self._issuer
        )
        with self._mux_lock:
            if self._follower_operation_locked(viewer, reservation) is not operation:
                raise _deny()
            self._follower_closures[id(reservation)] = (viewer, reservation, closure)
        self._retire_authority(viewer.token)
        return closure

    def unadopted_viewer_closed(
        self,
        viewer: LocalMediaLease,
        reservation: MasterReservation,
        closure: UnadoptedViewerClosure,
    ) -> bool:
        try:
            self._cleanup_lease(viewer)
            self._reservation(reservation, expired=True)
            with self._mux_lock:
                self._follower_operation_locked(viewer, reservation)
                entry = self._follower_closures.get(id(reservation))
            return (
                entry is not None
                and entry[0] is viewer
                and entry[1] is reservation
                and entry[2] is closure
                and type(closure) is UnadoptedViewerClosure
                and closure._authority is self._issuer
                and closure.lease_id == viewer.id
                and closure.master_id == reservation.master_id
            )
        except LocalDeviceFailure:
            return False

    def dispose(self) -> bool:
        with self._mux_lock:
            if (
                self._pending_reservations
                or any(
                    r.phase in {"NEW", "RUNNING", "RESOLVING"}
                    or (r.reservation is None and r.closure is None)
                    for r in self._attempts.values()
                )
                or self._startup_held
                or any(not r.closed for r in self._records.values())
                or any(
                    parts != {"viewer", "native"}
                    for parts in self._dedicated_settled.values()
                )
            ):
                return False
            self._mux_closed = True
        return super().shutdown()

    @_boundary
    def register_dedicated(
        self,
        viewer: LocalMediaLease,
        custody: EpochReceiptIssuer,
        viewer_custody: ViewerReceiptIssuer,
        *,
        registration: UUID,
        budget: LocalVerifyBudget,
    ) -> None:
        viewer = self._lease(viewer)
        if viewer.id is None or viewer.worker_epoch != self.worker_epoch:
            raise _deny()
        with self._mux_lock:
            if viewer.id in self._dedicated or self._mux_closed:
                raise _deny()
        native_receipt, viewer_receipt = (
            custody.issued_receipt,
            viewer_custody.issued_receipt,
        )
        row = self._sql(
            "dedicated_register",
            {**self._args(viewer), "r": registration},
            ":a,:w,:n,:r",
            budget,
        )
        if (
            not isinstance(row, dict)
            or _uuid(row["lease_id"]) != viewer.id
            or _uuid(row["dedicated_native_generation"]) != viewer.native_generation
        ):
            raise _deny()
        record = _Dedicated(
            viewer,
            registration,
            _scope(row),
            custody,
            native_receipt,
            viewer_custody,
            viewer_receipt,
        )
        with self._mux_lock:
            if viewer.id in self._dedicated or self._mux_closed:
                raise _deny()
            self._dedicated[viewer.id] = record
            self._dedicated_settled[viewer.id] = set()
            self._lease_masters[id(viewer)] = _uuid(row["master_id"])

    def _dedicated_owner(self, viewer: LocalMediaLease) -> _Dedicated:
        self._lease(viewer)
        with self._mux_lock:
            record = self._dedicated.get(cast(UUID, viewer.id))
        if (
            record is None
            or record.viewer is not viewer
            or record.native_owner.issued_receipt != record.native_receipt
            or record.viewer_owner.issued_receipt != record.viewer_receipt
        ):
            raise _deny()
        return record

    @_boundary
    def finish_dedicated(
        self, viewer: LocalMediaLease, receipt: EpochCleanupReceipt
    ) -> None:
        record = self._dedicated_owner(viewer)
        if (
            type(receipt) is not EpochCleanupReceipt
            or record.native_receipt() is not receipt
            or self._dedicated_owner(viewer) is not record
            or receipt.master_id != viewer.id
            or receipt.worker_epoch != viewer.worker_epoch
            or receipt.native_generation != viewer.native_generation
        ):
            raise _deny()
        payload = {
            k: str(v) if isinstance(v, UUID) else v
            for k, v in asdict(receipt).items()
            if k != "_authority"
        }
        self._sql(
            "dedicated_close",
            {
                **self._args(viewer),
                "r": record.registration,
                "receipt": json.dumps(payload),
            },
            ":a,:w,:n,:r,CAST(:receipt AS jsonb)",
        )
        with self._mux_lock:
            self._dedicated_settled[viewer.id].add("native")

    @_boundary
    def finish_dedicated_viewer(
        self, viewer: LocalMediaLease, receipt: ViewerCleanupReceipt
    ) -> None:
        record = self._dedicated_owner(viewer)
        if (
            type(receipt) is not ViewerCleanupReceipt
            or record.viewer_receipt() is not receipt
            or self._dedicated_owner(viewer) is not record
            or receipt.lease_id != viewer.id
            or receipt.registration_id != record.registration
        ):
            raise _deny()
        payload = {
            k: str(v) if isinstance(v, UUID) else v
            for k, v in asdict(receipt).items()
            if k != "_authority"
        }
        self._sql(
            "viewer_close",
            {
                **self._args(viewer),
                "r": record.registration,
                "scope": "DEDICATED_NATIVE",
                "receipt": json.dumps(payload),
            },
            ":a,:w,:n,:r,:scope,CAST(:receipt AS jsonb)",
        )
        with self._mux_lock:
            self._dedicated_settled[viewer.id].add("viewer")

    def _wall_control(
        self, ticket: str, function: str, purpose: str, budget: LocalVerifyBudget
    ) -> UUID:
        if not _token(ticket) or self._mux_closed:
            raise _deny()
        row = self._sql(
            function, {"t": ticket, "w": self.worker_epoch}, ":t,:w", budget
        )
        if (
            not isinstance(row, dict)
            or set(row) != {"wall_id", "purpose"}
            or row["purpose"] != purpose
        ):
            raise _deny()
        wall = _uuid(row["wall_id"])
        if not wall.int:
            raise _deny()
        budget.remaining_ms()
        return wall

    @_boundary
    def redeem_wall_stop(self, ticket: str, *, budget: LocalVerifyBudget) -> UUID:
        return self._wall_control(ticket, "wall_control_redeem", "WALL_STOP", budget)

    @_boundary
    def redeem_wall_heartbeat(self, ticket: str, *, budget: LocalVerifyBudget) -> UUID:
        return self._wall_control(
            ticket, "wall_heartbeat_redeem", "WALL_HEARTBEAT", budget
        )

    @_boundary
    def redeem_focus_settle(
        self, ticket: str, *, budget: LocalVerifyBudget
    ) -> tuple[UUID, UUID, Literal["CANCELLED", "FAILED"]]:
        if not _token(ticket) or self._mux_closed:
            raise _deny()
        row = self._sql(
            "focus_settle_redeem",
            {"t": ticket, "w": self.worker_epoch},
            ":t,:w",
            budget,
        )
        if (
            not isinstance(row, dict)
            or set(row) != {"focus_id", "wall_id", "transition"}
            or row["transition"] not in {"CANCELLED", "FAILED"}
        ):
            raise _deny()
        focus, wall = _uuid(row["focus_id"]), _uuid(row["wall_id"])
        if not focus.int or not wall.int:
            raise _deny()
        budget.remaining_ms()
        return focus, wall, cast(Literal["CANCELLED", "FAILED"], row["transition"])

    @_boundary
    def focus_identity(self, grant: FocusGrant) -> tuple[UUID, UUID]:
        record = self._record(grant, FocusGrant, expired=True)
        if record.focus_id is None:
            raise _deny()
        return record.focus_id, grant.scope.wall_id

    @_boundary
    def refresh_grant(self, grant: G) -> G:
        """Snapshot an already-renewed SQL expiry; never renew pending focus."""
        if type(grant) is FocusGrant:
            raise _deny()
        try:
            return self._refresh_current_grant(grant)
        except BaseException:
            # Failed refresh is itself an observed denial. Do not require a
            # subsequent current() call to invalidate cached sibling authority.
            # Exact retained identity excludes copies; _fence_for deliberately
            # excludes a capability already superseded by a successful refresh.
            with self._mux_lock:
                record = self._records.get(id(grant))
            if record is not None and record.grant is grant:
                self._retire(record)
                self._fence_for(record)
            raise

    def _refresh_current_grant(self, grant: G) -> G:
        from dataclasses import replace

        record = self._record(grant, type(grant))
        started, observed = self._clock(), datetime.now(UTC)
        row = self._observe(record)
        if row is None:
            self._retire(record)
            raise _deny()
        # Slow success cannot revive or extend an object that expired in flight.
        self._record(grant, type(grant))
        fresh = replace(
            grant,
            expires_monotonic=self._expiry(row, started, observed),
            _seal=_GRANT_SEAL,
        )
        with self._mux_lock:
            if (
                self._mux_closed
                or record.denied
                or record.closed
                or record.master_id in self._denied_masters
            ):
                raise _deny()
            self._records[id(fresh)] = _Record(
                fresh,
                record.authority,
                record.master_id,
                record.native,
                lease=record.lease,
                slot_id=record.slot_id,
                focus_id=record.focus_id,
            )
            if type(fresh) is TransportGrant:
                self._master_grants[record.master_id] = fresh
            if type(fresh) is ViewerGrant:
                custody = self._viewer_custody.get(fresh.lease_id)
                if custody is not None:
                    self._viewer_custody[fresh.lease_id] = _ViewerCustody(
                        fresh, custody.owner, custody.issued_receipt
                    )
            record.closed = True  # Superseded capability, not an SQL cleanup claim.
        self._retire(record)
        return fresh
