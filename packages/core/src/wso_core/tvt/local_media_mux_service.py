"""Recorder epoch coordination with retained original construction ownership.

Provider preparation allocates custodians only. Native work starts only after
the exact binding and receipt issuers have been registered with admission.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import Enum
from threading import Event, RLock, Thread, get_ident
from typing import TYPE_CHECKING, Literal, Protocol, cast
from uuid import UUID, uuid4

from wso_contracts.tvt.local_media import LocalLiveResponse
from wso_contracts.tvt.media import MediaLease

from .local_credentials import LocalDeviceCredentials
from .local_live import PrivateLiveFrame
from .local_media_admission import LocalMediaLease
from .local_media_mux_admission import (
    MainRetentionObserver,
    MasterAttemptResolution,
    MasterReserveAttempt,
    SqlMuxAdmission,
    UnstartedMasterClaim,
    UnstartedMasterClosure,
    ViewerReceiptIssuer,
)
from .local_media_mux_types import (
    CleanupScope,
    EpochCleanupReceipt,
    EpochReceiptIssuer,
    FocusGrant,
    IngressCut,
    MasterLoginProof,
    MasterReservation,
    MuxOriginalBudgetPort,
    MuxOriginalReservation,
    MuxScopeKey,
    MuxSlotIdentity,
    MuxValidatedFrame,
    MuxViewerHandle,
    OriginalMuxBinding,
    OwnedRecorderMaster,
    SlotRetentionGrant,
    TransportGrant,
    ViewerCleanupReceipt,
    ViewerGrant,
)
from .local_media_service import (
    LocalLiveProof,
    LocalMediaChannel,
    LocalMediaExecutor,
    OwnedLocalLiveSession,
)
from .local_service import LocalDeviceFailure, LocalVerifyBudget

if TYPE_CHECKING:
    from .local_media_mux_admission import FocusSettlement


class PreparedRecorderMaster(OwnedRecorderMaster, Protocol):
    """One original supplier, retained before any native acquisition.

    close/issued_receipt must retain the same pre-registered custodian even if
    start fails halfway. Neither operation may rediscover an owner by PID.
    """

    def start(
        self,
        credentials: LocalDeviceCredentials,
        grant: TransportGrant,
        *,
        budget: LocalVerifyBudget,
    ) -> MasterLoginProof: ...
    def binding_for(self, channel: bytes) -> OriginalMuxBinding | None: ...
    def issued_receipt(self) -> EpochCleanupReceipt | None: ...
    def prepare_viewer(self, grant: ViewerGrant) -> PreparedMuxViewer: ...
    def refresh_grants(
        self, *, budget: LocalVerifyBudget
    ) -> AbstractContextManager[None]: ...
    def replace_grant(
        self,
        old: TransportGrant | SlotRetentionGrant | ViewerGrant,
        new: TransportGrant | SlotRetentionGrant | ViewerGrant,
    ) -> None: ...


class PreparedMuxViewer(MuxViewerHandle, Protocol):
    def start(self, *, budget: LocalVerifyBudget) -> None: ...
    def issued_receipt(self) -> ViewerCleanupReceipt | None: ...
    def release_frames(self, frames: tuple[MuxValidatedFrame, ...]) -> None: ...
    def current_grant(self) -> ViewerGrant: ...


class RecorderMasterPort(Protocol):
    def prepare_master(
        self, reservation: MasterReservation, original: MuxOriginalReservation
    ) -> PreparedRecorderMaster:
        """Prepare and retain original custody; perform no native work."""
        ...

    def prepare_dedicated(
        self,
        lease: LocalMediaLease,
        scope: MuxScopeKey,
        original_budget: MuxOriginalReservation,
        registration: UUID,
    ) -> PreparedDedicatedMain: ...


class PreparedDedicatedMain(Protocol):
    @property
    def native_issuer(self) -> EpochReceiptIssuer: ...
    @property
    def viewer_issuer(self) -> ViewerReceiptIssuer: ...
    def start(
        self,
        credentials: LocalDeviceCredentials,
        selection: LocalMediaChannel,
        *,
        budget: LocalVerifyBudget,
    ) -> OwnedLocalLiveSession: ...
    def close_native(self) -> EpochCleanupReceipt | None: ...
    def close_viewer(self) -> ViewerCleanupReceipt | None: ...
    def attach_retirement(
        self, check: Callable[[], ViewerCleanupReceipt | None]
    ) -> None: ...


class EpochState(Enum):
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    STOPPING = "STOPPING"
    QUARANTINED = "QUARANTINED"
    CLOSED = "CLOSED"


class FocusStartupPhase(Enum):
    PENDING = "PENDING"
    SETTLING = "SETTLING"
    ACKNOWLEDGED = "ACKNOWLEDGED"


def _ready_event() -> Event:
    event = Event()
    event.set()
    return event


@dataclass(slots=True, repr=False)
class OriginalConstructorRecord:
    scope: MuxScopeKey
    master_id: UUID
    transport: TransportGrant
    state: EpochState = EpochState.STARTING
    reservation: MasterReservation | None = None
    original: MuxOriginalReservation | None = None
    prepared: PreparedRecorderMaster | None = None
    binding_for: Callable[[bytes], OriginalMuxBinding | None] | None = None
    issued_receipt: Callable[[], EpochCleanupReceipt | None] | None = None
    done: Event = field(default_factory=Event)
    retiring: bool = False
    slots: dict[bytes, SlotRecord] = field(default_factory=dict)
    opening: bool = False
    attaching: int = 0
    refreshing: bool = False
    refresh_owner: int | None = None
    refresh_version: int = 0
    refresh_done: Event = field(default_factory=_ready_event)


@dataclass(slots=True, repr=False)
class SlotRecord:
    selection: LocalMediaChannel
    grant: SlotRetentionGrant
    identity: MuxSlotIdentity
    viewer: UUID | None = None


@dataclass(slots=True, repr=False)
class ViewerRecord:
    lease: LocalMediaLease
    master: OriginalConstructorRecord
    slot: SlotRecord
    grant: ViewerGrant
    handle: PreparedMuxViewer
    issuer: Callable[[], ViewerCleanupReceipt | None]
    stopping: bool = False
    closing: bool = False
    local_settled: bool = False
    cleanup_scope: CleanupScope = CleanupScope.VIEWER
    cut: IngressCut | None = None
    view: MediaLease | None = None
    starting: bool = True
    startup_budget: LocalVerifyBudget | None = None


@dataclass(slots=True, repr=False)
class DedicatedRecord:
    lease: LocalMediaLease
    master: OriginalConstructorRecord
    registration: UUID
    selection: LocalMediaChannel
    original: MuxOriginalReservation | None = None
    prepared: PreparedDedicatedMain | None = None
    native_issuer: EpochReceiptIssuer | None = None
    viewer_issuer: ViewerReceiptIssuer | None = None
    native_receipt: Callable[[], EpochCleanupReceipt | None] | None = None
    viewer_receipt: Callable[[], ViewerCleanupReceipt | None] | None = None
    session: OwnedLocalLiveSession | None = None
    starting: bool = True
    stopping: bool = False
    closing: bool = False
    native_settled: bool = False
    local_settled: bool = False
    view: MediaLease | None = None
    startup_budget: LocalVerifyBudget | None = None
    startup_focus: FocusGrant | None = None
    focus_phase: FocusStartupPhase = FocusStartupPhase.PENDING
    focus_version: int = 0


def _denied() -> LocalDeviceFailure:
    return LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)


@dataclass(slots=True, repr=False)
class OriginalReservationOperation:
    """Retain the exact reserve invocation when SQL completion is unresolved."""

    admission: SqlMuxAdmission
    viewer: LocalMediaLease
    budget: LocalVerifyBudget
    failed: bool = False
    attempt: MasterReserveAttempt | None = None
    provider: RecorderMasterPort | None = None
    original_budget: MuxOriginalBudgetPort | None = None
    running: bool = True
    recovering: bool = False
    reservation: MasterReservation | None = None


@dataclass(slots=True, repr=False)
class UnstartedRecovery:
    operation: OriginalReservationOperation
    reservation: MasterReservation
    admission: SqlMuxAdmission
    provider: RecorderMasterPort
    original_budget: MuxOriginalBudgetPort
    viewer: LocalMediaLease
    claim: UnstartedMasterClaim | None = None
    original: MuxOriginalReservation | None = None
    prepared: PreparedRecorderMaster | None = None
    binding_for: Callable[[bytes], OriginalMuxBinding | None] | None = None
    issued_receipt: Callable[[], EpochCleanupReceipt | None] | None = None
    close: Callable[[], EpochCleanupReceipt | None] | None = None
    receipt: EpochCleanupReceipt | None = None
    closure: UnstartedMasterClosure | None = None
    budget_attempted: bool = False
    factory_attempted: bool = False
    released: bool = False
    running: bool = False
    registered: bool = False


class DeviceEpochCoordinator:
    """One fixed actor/session wall; pending originals consume base capacity."""

    def __init__(
        self,
        admission: SqlMuxAdmission,
        provider: RecorderMasterPort,
        budget: MuxOriginalBudgetPort,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.admission, self.provider, self.budget = admission, provider, budget
        self._clock = clock
        self._lock = RLock()
        self._records: dict[UUID, OriginalConstructorRecord] = {}
        self._actor: tuple[UUID, int, UUID, bytes, UUID, UUID] | None = None
        self._closed = False
        self._viewers: dict[UUID, ViewerRecord] = {}
        self._focus: dict[int, FocusGrant] = {}
        self._main_refs: dict[UUID, OriginalConstructorRecord] = {}
        self._main_acks: dict[UUID, tuple[FocusGrant, FocusSettlement]] = {}
        self._dedicated: dict[UUID, DedicatedRecord] = {}
        self._focus_channels: dict[int, bytes] = {}
        self._closed_views: dict[UUID, MediaLease] = {}
        self._pending_reservations = 0
        self._reservation_operations: dict[int, OriginalReservationOperation] = {}
        self._stopped_walls: set[UUID] = set()
        self._unadopted_reservations: dict[int, MasterReservation] = {}
        self._unadopted_operations: dict[int, OriginalReservationOperation] = {}
        self._unstarted_recovery: dict[int, UnstartedRecovery] = {}

    def _affinity_settled(self, *, candidate: MasterReservation | None = None) -> bool:
        """Called under our lock; no callback or SQL charge may be forgotten."""
        if (
            candidate is not None
            and self._unadopted_reservations.get(id(candidate)) is not candidate
        ):
            return False
        return (
            not self._pending_reservations
            and not self._reservation_operations
            and not self._unstarted_recovery
            and not any(key != id(candidate) for key in self._unadopted_operations)
            and not any(
                r is not candidate for r in self._unadopted_reservations.values()
            )
            and not self._viewers
            and not self._dedicated
            and not self._focus
            and not self._main_refs
            and not self._main_acks
            and all(
                r.state is EpochState.CLOSED
                and r.done.is_set()
                and not r.attaching
                and not r.opening
                and not r.refreshing
                and not r.retiring
                for r in self._records.values()
            )
        )

    def _remember_closed(self, view: MediaLease | None) -> None:
        if view is None:
            return
        with self._lock:
            self._closed_views[view.id] = view.model_copy(update={"state": "CLOSED"})
            while len(self._closed_views) > 32:
                self._closed_views.pop(next(iter(self._closed_views)))

    def _attempt_retained(
        self,
        operation: OriginalReservationOperation,
        admission: SqlMuxAdmission,
        viewer: LocalMediaLease,
        attempt: MasterReserveAttempt,
    ) -> bool:
        with self._lock:
            return (
                self._reservation_operations.get(id(operation)) is operation
                and operation.admission is admission
                and operation.viewer is viewer
                and operation.attempt is attempt
                and not operation.running
            )

    def _recover_attempt(
        self, operation: OriginalReservationOperation, budget: LocalVerifyBudget
    ) -> None:
        with self._lock:
            if (
                operation.running
                or operation.recovering
                or not operation.failed
                or operation.attempt is None
            ):
                return
            operation.recovering = True
            admission, viewer, attempt = (
                operation.admission,
                operation.viewer,
                operation.attempt,
            )
        try:
            budget.remaining_ms()
            resolution = admission.resolve_master_attempt(attempt, budget=budget)
            if type(
                resolution
            ) is not MasterAttemptResolution or not self._attempt_retained(
                operation, admission, viewer, attempt
            ):
                return
            if admission.master_resolution_current(attempt, resolution) is not True:
                return
            if resolution.outcome == "ABSENT":
                closure = admission.finish_absent_attempt(
                    attempt, resolution, budget=budget
                )
                if (
                    admission.absent_attempt_closed(attempt, resolution, closure)
                    is not True
                ):
                    return
                if closure.lease_id != viewer.id or closure.master_id is not None:
                    return
            elif (
                resolution.outcome != "RESERVED"
                or type(resolution.reservation) is not MasterReservation
            ):
                return
            budget.remaining_ms()
            if admission.master_resolution_current(attempt, resolution) is not True:
                return
            with self._lock:
                if not self._attempt_retained(operation, admission, viewer, attempt):
                    return
                if resolution.reservation is not None:
                    reservation = resolution.reservation
                    previous = self._unadopted_operations.get(id(reservation))
                    if previous is not None and previous is not operation:
                        return
                    # Transfer, never adopt: stopped/foreign walls cannot start here.
                    operation.reservation = reservation
                    self._unadopted_reservations[id(reservation)] = reservation
                    self._unadopted_operations[id(reservation)] = operation
                del self._reservation_operations[id(operation)]
                self._pending_reservations -= 1
        except Exception:  # noqa: BLE001 -- Unknown completion retains the exact operation.
            return
        finally:
            with self._lock:
                operation.recovering = False

    def _unadopted_retained(
        self, reservation: MasterReservation, operation: OriginalReservationOperation
    ) -> bool:
        with self._lock:
            return (
                self._unadopted_reservations.get(id(reservation)) is reservation
                and self._unadopted_operations.get(id(reservation)) is operation
                and operation.reservation is reservation
                and not operation.running
            )

    def _empty_retained(self, recovery: UnstartedRecovery) -> bool:
        with self._lock:
            operation = recovery.operation
            return (
                self._unstarted_recovery.get(id(recovery.reservation)) is recovery
                and self._unadopted_retained(recovery.reservation, operation)
                and operation.admission is recovery.admission
                and operation.provider is recovery.provider
                and operation.original_budget is recovery.original_budget
                and operation.viewer is recovery.viewer
            )

    def _empty_current(self, recovery: UnstartedRecovery) -> bool:
        with self._lock:
            prepared = recovery.prepared
            binding, issued, close = (
                recovery.binding_for,
                recovery.issued_receipt,
                recovery.close,
            )
        if prepared is None:
            return False
        matched = (
            prepared.binding_for == binding
            and prepared.issued_receipt == issued
            and prepared.close == close
        )
        with self._lock:
            return (
                matched
                and self._empty_retained(recovery)
                and recovery.prepared is prepared
                and recovery.binding_for is binding
                and recovery.issued_receipt is issued
                and recovery.close is close
            )

    def _recover_creator(
        self,
        reservation: MasterReservation,
        operation: OriginalReservationOperation,
        budget: LocalVerifyBudget,
    ) -> None:
        with self._lock:
            if (
                not self._unadopted_retained(reservation, operation)
                or operation.provider is None
                or operation.original_budget is None
            ):
                return
            recovery = self._unstarted_recovery.get(id(reservation))
            if recovery is None:
                recovery = UnstartedRecovery(
                    operation,
                    reservation,
                    operation.admission,
                    operation.provider,
                    operation.original_budget,
                    operation.viewer,
                )
                self._unstarted_recovery[id(reservation)] = recovery
            if recovery.running:
                return
            recovery.running = True
        try:
            budget.remaining_ms()
            if recovery.claim is None:
                claim = recovery.admission.claim_unstarted_master(reservation)
                with self._lock:
                    if (
                        not self._empty_retained(recovery)
                        or type(claim) is not UnstartedMasterClaim
                        or claim.reservation is not reservation
                    ):
                        return
                    recovery.claim = claim
            claim = recovery.claim
            if recovery.original is None:
                with self._lock:
                    if recovery.budget_attempted:
                        return
                    recovery.budget_attempted = True
                original = recovery.original_budget.reserve("base")
                with self._lock:
                    recovery.original = original
            original = recovery.original
            budget.remaining_ms()
            if not self._empty_retained(recovery):
                return
            if recovery.prepared is None:
                with self._lock:
                    if recovery.factory_attempted:
                        return
                    recovery.factory_attempted = True
                prepared = recovery.provider.prepare_master(reservation, original)
                # Retain partial construction before reading supplier properties.
                with self._lock:
                    recovery.prepared = prepared
                binding, issued, close = (
                    prepared.binding_for,
                    prepared.issued_receipt,
                    prepared.close,
                )
                with self._lock:
                    if not self._empty_retained(recovery):
                        return
                    recovery.binding_for, recovery.issued_receipt, recovery.close = (
                        binding,
                        issued,
                        close,
                    )
            if not recovery.registered and self._empty_current(recovery):
                prepared = recovery.prepared
                assert prepared is not None
                try:
                    recovery.admission.register_unstarted_original(
                        claim, prepared, prepared
                    )
                except Exception:  # noqa: BLE001 -- Finish independently verifies whether exact registration completed.
                    registered = False
                else:
                    registered = True
                with self._lock:
                    recovery.registered = registered
            if (
                not self._empty_current(recovery)
                or recovery.close is None
                or recovery.issued_receipt is None
            ):
                return
            receipt = recovery.receipt
            if receipt is None:
                receipt = recovery.close()
                if type(receipt) is not EpochCleanupReceipt or not self._empty_current(
                    recovery
                ):
                    return
                actual = recovery.issued_receipt()
                if (
                    actual is not receipt
                    or not self._empty_current(recovery)
                    or receipt.original_state != "NOT_CREATED"
                    or (
                        receipt.master_id,
                        receipt.worker_epoch,
                        receipt.native_generation,
                    )
                    != (
                        reservation.master_id,
                        reservation.scope.worker_epoch,
                        reservation.transport.native_generation,
                    )
                ):
                    return
                with self._lock:
                    recovery.receipt = receipt
            budget.remaining_ms()
            if recovery.closure is None:
                closure = recovery.admission.finish_unstarted_master(
                    claim, receipt, budget=budget
                )
                if recovery.admission.unstarted_master_closed(
                    claim, closure
                ) is not True or not self._empty_current(recovery):
                    return
                with self._lock:
                    recovery.closure = closure
            closure = recovery.closure
            if (
                recovery.admission.unstarted_master_closed(claim, closure) is not True
                or recovery.viewer.id not in closure.lease_ids
                or not self._empty_current(recovery)
            ):
                return
            budget.remaining_ms()
            if not recovery.released:
                recovery.original_budget.release_confirmed(original, receipt)
                with self._lock:
                    recovery.released = True
            if (
                not self._empty_current(recovery)
                or recovery.admission.unstarted_master_closed(claim, closure)
                is not True
            ):
                return
            with self._lock:
                if not self._empty_retained(recovery):
                    return
                # SQL may have closed several never-admitted lease rows, but
                # each follower still needs its own exact operation/pair check.
                del self._unadopted_reservations[id(reservation)]
                del self._unadopted_operations[id(reservation)]
                del self._unstarted_recovery[id(reservation)]
        except Exception:  # noqa: BLE001 -- Retain claims and all partial actual original custody for retry.
            return
        finally:
            with self._lock:
                recovery.running = False

    def _recover_follower(
        self,
        reservation: MasterReservation,
        operation: OriginalReservationOperation,
        budget: LocalVerifyBudget,
    ) -> None:
        with self._lock:
            if operation.recovering or not self._unadopted_retained(
                reservation, operation
            ):
                return
            operation.recovering = True
            admission, viewer = operation.admission, operation.viewer
        try:
            budget.remaining_ms()
            closure = admission.finish_unadopted_follower(
                viewer, reservation, budget=budget
            )
            if (
                admission.unadopted_viewer_closed(viewer, reservation, closure)
                is not True
            ):
                return
            budget.remaining_ms()
            with self._lock:
                if (
                    self._unadopted_retained(reservation, operation)
                    and operation.admission is admission
                    and operation.viewer is viewer
                    and closure.lease_id == viewer.id
                    and closure.master_id == reservation.master_id
                ):
                    del self._unadopted_reservations[id(reservation)]
                    del self._unadopted_operations[id(reservation)]
        except Exception:  # noqa: BLE001 -- No follower owns a replacement original.
            return
        finally:
            with self._lock:
                operation.recovering = False

    def recover_reservations(self, *, budget: LocalVerifyBudget) -> bool:
        """Internal failed-start cleanup. It never authorizes reservation adoption."""
        with self._lock:
            operations = tuple(self._reservation_operations.values())
        for operation in operations:
            self._recover_attempt(operation, budget)
        with self._lock:
            returned = tuple(self._unadopted_reservations.values())
        for reservation in sorted(returned, key=lambda r: not r.creator):
            with self._lock:
                context = self._unadopted_operations.get(id(reservation))
            if context is None:
                continue
            if reservation.creator:
                self._recover_creator(reservation, context, budget)
            else:
                self._recover_follower(reservation, context, budget)
        with self._lock:
            return (
                not self._reservation_operations
                and not self._pending_reservations
                and not self._unadopted_reservations
                and not self._unstarted_recovery
            )

    def _retained(self, record: OriginalConstructorRecord) -> bool:
        with self._lock:
            return (
                self._records.get(record.master_id) is record
                and record.prepared is not None
                and record.reservation is not None
                and record.scope == record.reservation.scope == record.transport.scope
                and record.transport.native_generation
                == record.reservation.transport.native_generation
            )

    def _original_current(self, record: OriginalConstructorRecord) -> bool:
        """Read supplier attributes outside the lock, then validate our snapshot."""
        with self._lock:
            prepared = record.prepared
            binding, receipt = record.binding_for, record.issued_receipt
        if prepared is None:
            return False
        same_methods = (
            prepared.binding_for == binding and prepared.issued_receipt == receipt
        )
        with self._lock:
            return (
                same_methods
                and self._retained(record)
                and record.prepared is prepared
                and record.binding_for is binding
                and record.issued_receipt is receipt
            )

    def _master(
        self, viewer: LocalMediaLease, budget: LocalVerifyBudget
    ) -> OriginalConstructorRecord:
        budget.remaining_ms()
        operation = OriginalReservationOperation(
            self.admission,
            viewer,
            budget,
            provider=self.provider,
            original_budget=self.budget,
        )
        with self._lock:
            if self._closed:
                raise _denied()
            self._pending_reservations += 1
            self._reservation_operations[id(operation)] = operation
        try:
            attempt = operation.admission.begin_master_attempt(viewer)
            with self._lock:
                operation.attempt = attempt
            reservation = operation.admission.reserve_master(
                viewer, budget=budget, attempt=attempt
            )
        except BaseException:
            with self._lock:
                # An exception cannot distinguish no SQL reservation from an
                # uncertain commit. Retain this exact owner until authentic
                # admission/custody resolution; never expire it by a timer.
                operation.failed = True
                operation.running = False
            raise
        creator = False
        with self._lock:
            # Returned objects are retained before every later rejection. A
            # follower or colliding ID cannot replace an existing original.
            self._unadopted_reservations[id(reservation)] = reservation
            operation.running = False
            operation.reservation = reservation
            self._unadopted_operations[id(reservation)] = operation
            del self._reservation_operations[id(operation)]
            self._pending_reservations -= 1
            scope = reservation.scope
            actor = (
                scope.tenant_id,
                scope.tenant_epoch,
                scope.actor_user_id,
                scope.session_digest,
                scope.wall_id,
                scope.worker_epoch,
            )
            if scope.wall_id in self._stopped_walls:
                raise _denied()
            if self._closed:
                raise _denied()
            if (
                self.admission is not operation.admission
                or self.provider is not operation.provider
                or self.budget is not operation.original_budget
            ):
                raise _denied()
            if any(held.failed for held in self._reservation_operations.values()):
                raise _denied()
            if any(
                held is not reservation
                for held in self._unadopted_reservations.values()
            ):
                raise _denied()
            if self._actor not in (None, actor):
                old = self._actor
                if (
                    old is None
                    or old[:4] + old[5:] != actor[:4] + actor[5:]
                    or not self._affinity_settled(candidate=reservation)
                ):
                    raise _denied()
            self._actor = actor
            record = self._records.get(reservation.master_id)
            if record is None:
                if (
                    sum(
                        r.state is not EpochState.CLOSED for r in self._records.values()
                    )
                    >= 2
                ):
                    raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)
                record = OriginalConstructorRecord(
                    scope, reservation.master_id, reservation.transport
                )
                self._records[record.master_id] = record
            if (
                record.scope != scope
                or record.transport.native_generation
                != reservation.transport.native_generation
            ):
                raise _denied()
            if reservation.creator and record.reservation is None:
                record.reservation = reservation
                creator = True
            del self._unadopted_reservations[id(reservation)]
            del self._unadopted_operations[id(reservation)]
        if creator:
            try:
                original = self.budget.reserve("base")
                with self._lock:
                    record.original = original
                prepared = self.provider.prepare_master(reservation, original)
                binding_for, issued_receipt = (
                    prepared.binding_for,
                    prepared.issued_receipt,
                )
                with self._lock:
                    record.prepared = prepared
                    record.binding_for = binding_for
                    record.issued_receipt = issued_receipt
                self.admission.register_original(reservation, prepared, prepared)
                if not self._original_current(record):
                    raise _denied()
                credentials, grant = self.admission.prepare_login(
                    reservation, budget=budget
                )
                try:
                    budget.remaining_ms()
                    with self._lock:
                        if self._closed or record.state is not EpochState.STARTING:
                            raise _denied()
                    proof = prepared.start(credentials, grant, budget=budget)
                finally:
                    del credentials
                if not self._original_current(record):
                    raise _denied()
                with self._lock:
                    if (
                        self._closed
                        or record.state is not EpochState.STARTING
                        or not self._retained(record)
                    ):
                        raise _denied()
                transport = self.admission.activate_master(
                    reservation, proof, budget=budget
                )
                budget.remaining_ms()
                if not self.admission.current_transport(transport):
                    raise _denied()
                with self._lock:
                    if self._closed or record.state is not EpochState.STARTING:
                        raise _denied()
                    record.transport = transport
                    record.state = EpochState.ACTIVE
            except BaseException:
                with self._lock:
                    record.state = EpochState.QUARANTINED
                raise
            finally:
                record.done.set()
                if record.state is EpochState.QUARANTINED:
                    self._retire_master(record)
        else:
            while not record.done.wait(min(0.05, budget.remaining_ms() / 1000)):
                budget.remaining_ms()
        budget.remaining_ms()
        with self._lock:
            if self._closed or record.state is not EpochState.ACTIVE:
                raise _denied()
        if not self.admission.current_transport(record.transport):
            raise _denied()
        with self._lock:
            if self._closed or record.state is not EpochState.ACTIVE:
                raise _denied()
        return record

    def _retire_master(self, record: OriginalConstructorRecord) -> bool:
        with self._lock:
            if record.state is EpochState.CLOSED:
                return True
            if (
                record.retiring
                or not record.done.is_set()
                or record.attaching
                or record.opening
            ):
                return False
            record.state = EpochState.STOPPING
            record.retiring = True
            prepared, original = record.prepared, record.original
        settled = False
        try:
            if (
                prepared is None
                or original is None
                or not self._original_current(record)
            ):
                return False
            receipt = prepared.close()
            if (
                receipt is None
                or not self._original_current(record)
                or record.issued_receipt is None
            ):
                return False
            actual = record.issued_receipt()
            if actual is not receipt or not self._original_current(record):
                return False
            self.admission.finish_epoch(record.transport, receipt)
            self.budget.release_confirmed(original, receipt)
            settled = True
            return True
        except Exception:  # noqa: BLE001 -- Callback failures deny and retain custody.
            return False
        finally:
            with self._lock:
                record.retiring = False
                record.state = EpochState.CLOSED if settled else EpochState.QUARANTINED

    def _active(self, record: OriginalConstructorRecord) -> bool:
        with self._lock:
            return (
                self._records.get(record.master_id) is record
                and record.state is EpochState.ACTIVE
                and not record.refreshing
                and not self._closed
                and self._retained(record)
            )

    def _slot(
        self,
        viewer: LocalMediaLease,
        selection: LocalMediaChannel,
        record: OriginalConstructorRecord,
        budget: LocalVerifyBudget,
    ) -> SlotRecord:
        # The operation flag serializes opens without holding a lock over SQL,
        # native work, or arbitrary provider callbacks.
        while True:
            budget.remaining_ms()
            with self._lock:
                if not self._active(record):
                    raise _denied()
                if not record.opening:
                    record.opening = True
                    break
            budget.cancel.wait(min(0.01, budget.remaining_ms() / 1000))
        try:
            with self._lock:
                existing = record.slots.get(selection.guid)
            if existing is not None:
                if not self.admission.current_slot(existing.grant) or not self._active(
                    record
                ):
                    raise _denied()
                prepared, reservation = record.prepared, record.reservation
                if prepared is None or reservation is None:
                    raise _denied()
                binding = prepared.binding_for(selection.guid)
                if binding is None or not self._active(record):
                    raise _denied()
                # The physical slot is retained, but each new SQL lease still
                # requires its own authoritative association with that slot.
                rebound = self.admission.reserve_slot(
                    viewer, reservation, binding=binding, budget=budget
                )
                if (
                    rebound is not existing.grant
                    or rebound.slot != existing.identity
                    or not self._active(record)
                    or not self.admission.current_slot(rebound)
                ):
                    raise _denied()
                return existing
            prepared, reservation = record.prepared, record.reservation
            if prepared is None or reservation is None:
                raise _denied()
            binding = prepared.binding_for(selection.guid)
            if binding is None or not self._active(record):
                raise _denied()
            grant = self.admission.reserve_slot(
                viewer, reservation, binding=binding, budget=budget
            )
            if not self._active(record) or not self.admission.current_slot(grant):
                raise _denied()
            slot = SlotRecord(selection, grant, grant.slot)
            with self._lock:
                if self._physical_slots() >= 16:
                    raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)
                record.slots[selection.guid] = slot
            identity = prepared.open_slot(selection, grant, budget=budget)
            budget.remaining_ms()
            if (
                identity != grant.slot
                or not self._active(record)
                or not self.admission.current_slot(grant)
            ):
                raise _denied()
            return slot
        except BaseException:
            self._fence(record)
            raise
        finally:
            with self._lock:
                record.opening = False

    def attach(
        self,
        viewer: LocalMediaLease,
        *,
        budget: LocalVerifyBudget,
        retain_local: Callable[[UUID, UUID], Callable[[], ViewerCleanupReceipt | None]]
        | None = None,
    ) -> MuxViewerHandle:
        if viewer.id is None:
            raise _denied()
        selection = self.admission.prepare_viewer(viewer, budget=budget)
        if selection.stream != "sub":
            raise _denied()
        with self._lock:
            if any(
                d.selection.guid == selection.guid for d in self._dedicated.values()
            ):
                raise _denied()
        record = self._master(viewer, budget)
        with self._lock:
            if not self._active(record) or viewer.id in self._viewers:
                raise _denied()
            if (
                len(self._viewers)
                + len(self._dedicated)
                + sum(r.attaching for r in self._records.values())
                >= 12
            ):
                raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)
            record.attaching += 1
        owned: ViewerRecord | None = None
        slot: SlotRecord | None = None
        try:
            slot = self._slot(viewer, selection, record, budget)
            with self._lock:
                if not self._active(record) or slot.viewer is not None:
                    raise _denied()
                slot.viewer = viewer.id
            grant = self.admission.admit_viewer(
                viewer, slot.grant, registration=uuid4(), budget=budget
            )
            prepared = record.prepared
            if prepared is None or not self._active(record):
                raise _denied()
            handle = prepared.prepare_viewer(grant)
            owned = ViewerRecord(
                viewer, record, slot, grant, handle, handle.issued_receipt
            )
            owned.startup_budget = budget
            with self._lock:
                self._viewers[viewer.id] = owned
            self.admission.register_viewer_custodian(grant, handle)
            if retain_local is not None:
                # The exact returned provider (including its observation facade)
                # is retained before start, cancellation, or native acquisition.
                attach_retirement = handle.attach_retirement
                attach_retirement(retain_local(viewer.id, grant.registration))
            if not self._active(record):
                raise _denied()
            handle.start(budget=budget)
            budget.remaining_ms()
            with self._lock:
                if (
                    self._viewers.get(viewer.id) is not owned
                    or owned.stopping
                    or not self._active(record)
                ):
                    raise _denied()
            if (
                handle.registration != grant.registration
                or handle.cut.slot != grant.slot
                or handle.cut.registration != grant.registration
            ):
                raise _denied()
            owned.cut = handle.cut
            owned.view = self.admission.activate_viewer(
                grant, handle.proof, budget=budget
            )
            budget.remaining_ms()
            with self._lock:
                if (
                    self._viewers.get(viewer.id) is not owned
                    or owned.stopping
                    or not self._active(record)
                ):
                    raise _denied()
                owned.starting = False
            if not self.current(viewer.id):
                raise _denied()
            with self._lock:
                returning = next(
                    (
                        g
                        for g in self._focus.values()
                        if g.direction == "RETURN"
                        and self._focus_channels[id(g)] == selection.guid
                    ),
                    None,
                )
            if returning is not None:
                self.settle_focus(returning, "ATTACHED", viewer_id=viewer.id)
            return handle
        except BaseException:
            if owned is not None:
                self._close_viewer(owned)
            elif slot is not None:
                with self._lock:
                    if slot.viewer == viewer.id:
                        slot.viewer = None
            raise
        finally:
            with self._lock:
                record.attaching -= 1
                if owned is not None:
                    owned.starting = False
            if owned is not None and owned.stopping:
                self._close_viewer(owned)
            self._retire_if_unused(record)

    def current(self, lease_id: UUID) -> bool:
        # A refresh invalidates immutable old objects before their replacements
        # reach every holder. Wait outside the registry; never interpret that
        # internal pause as a terminal viewer revocation.
        until = time.monotonic() + 5
        while time.monotonic() < until:
            with self._lock:
                shared = self._viewers.get(lease_id)
                dedicated = self._dedicated.get(lease_id)
                record = (
                    shared.master
                    if shared is not None
                    else dedicated.master
                    if dedicated is not None
                    else None
                )
                if record is None:
                    return False
                version = record.refresh_version
                refreshing = record.refreshing
                if refreshing and record.refresh_owner == get_ident():
                    return False
            if refreshing:
                record.refresh_done.wait(min(0.05, max(0, until - time.monotonic())))
                continue
            accepted = self._current_once(lease_id, deadline_monotonic=until)
            with self._lock:
                if record.refresh_version == version and not record.refreshing:
                    return accepted
        return False

    def _current_once(
        self, lease_id: UUID, *, deadline_monotonic: float | None = None
    ) -> bool:
        with self._lock:
            dedicated = self._dedicated.get(lease_id)
        if dedicated is not None:
            return self._current_dedicated(
                dedicated, deadline_monotonic=deadline_monotonic
            )
        with self._lock:
            owned = self._viewers.get(lease_id)
            if (
                owned is None
                or owned.stopping
                or owned.starting
                or not self._active(owned.master)
            ):
                return False
            grant, handle = owned.grant, owned.handle
        try:
            current = (
                self.admission.current_viewer(grant)
                and handle.current()
                and self._original_current(owned.master)
            )
            registration, cut = handle.registration, handle.cut
        except Exception:  # noqa: BLE001 -- Callback failures deny and retain custody.
            return False
        with self._lock:
            return (
                current
                and self._viewers.get(lease_id) is owned
                and owned.grant is grant
                and owned.handle is handle
                and not owned.stopping
                and self._active(owned.master)
                and registration == grant.registration
                and cut is owned.cut
            )

    def _has_refs(self, record: OriginalConstructorRecord) -> bool:
        return (
            record.attaching > 0
            or any(
                v.master is record and not v.stopping for v in self._viewers.values()
            )
            or any(g.scope == record.scope for g in self._focus.values())
            or any(r is record for r in self._main_refs.values())
        )

    def _retire_if_unused(self, record: OriginalConstructorRecord) -> bool:
        with self._lock:
            if self._has_refs(record):
                return False
            if record.state is EpochState.ACTIVE:
                record.state = EpochState.STOPPING
        return self._retire_master(record)

    def _close_viewer(self, owned: ViewerRecord) -> bool:
        with self._lock:
            if owned.closing:
                return False
            owned.stopping = True
            if owned.starting:
                return False
            owned.closing = True
            if not self._has_refs(owned.master):
                owned.cleanup_scope = CleanupScope.LAST_VIEWER_AND_DEVICE_EPOCH
                if owned.master.state is EpochState.ACTIVE:
                    owned.master.state = EpochState.STOPPING
        try:
            if not owned.local_settled:
                receipt = owned.handle.close()
                if receipt is not None:
                    if owned.handle.issued_receipt != owned.issuer:
                        return False
                    actual = owned.issuer()
                    with self._lock:
                        retained = self._viewers.get(owned.grant.lease_id) is owned
                    if (
                        actual is not receipt
                        or not retained
                        or owned.handle.issued_receipt != owned.issuer
                    ):
                        return False
                    self.admission.finish_viewer(
                        owned.grant, receipt, scope=owned.cleanup_scope
                    )
                    owned.local_settled = True
            self._retire_if_unused(owned.master)
            settled = owned.local_settled and (
                owned.cleanup_scope is CleanupScope.VIEWER
                or owned.master.state is EpochState.CLOSED
            )
            if settled:
                self._remember_closed(owned.view)
                with self._lock:
                    if self._viewers.get(owned.grant.lease_id) is owned:
                        del self._viewers[owned.grant.lease_id]
                    if owned.slot.viewer == owned.grant.lease_id:
                        owned.slot.viewer = None
            return settled
        except Exception:  # noqa: BLE001 -- Callback failures deny and retain custody.
            return False
        finally:
            with self._lock:
                owned.closing = False

    def detach(self, lease_id: UUID, *, budget: LocalVerifyBudget) -> CleanupScope:
        budget.remaining_ms()
        with self._lock:
            dedicated = self._dedicated.get(lease_id)
            owned = self._viewers.get(lease_id)
        if dedicated is not None:
            self._close_dedicated(dedicated)
            return CleanupScope.DEDICATED_NATIVE
        if owned is None:
            raise _denied()
        self._close_viewer(owned)
        return owned.cleanup_scope

    def _fence(self, record: OriginalConstructorRecord) -> None:
        with self._lock:
            if record.state is not EpochState.CLOSED:
                record.state = EpochState.STOPPING
            viewers = tuple(v for v in self._viewers.values() if v.master is record)
            for viewer in viewers:
                viewer.stopping = True
        for viewer in viewers:
            self._close_viewer(viewer)
        self._retire_master(record)

    def reserve_focus(self, ticket: str, *, budget: LocalVerifyBudget) -> FocusGrant:
        """Redeem a purpose ticket issued in the protected application scope."""
        budget.remaining_ms()
        grant = self.admission.redeem_focus(ticket, budget=budget)
        try:
            self.retain_focus(grant)
            budget.remaining_ms()
            return grant
        except BaseException:
            outcome: Literal["EXPIRED", "FAILED"] = (
                "EXPIRED" if self._clock() >= grant.expires_monotonic else "FAILED"
            )
            with self._lock:
                retained = self._focus.get(id(grant)) is grant
                main = (
                    self._dedicated.get(grant.lease_id)
                    if grant.direction == "RETURN"
                    else None
                )
            if retained:
                self.settle_focus(grant, outcome, viewer_id=None)
            else:
                ack = self.admission.settle_focus(grant, outcome)
                if (
                    ack is None
                    or self.admission.focus_settlement_current(grant, ack, outcome)
                    is not True
                ):
                    raise _denied() from None
                if main is not None and main.master.scope == grant.scope:
                    self._close_dedicated(main)
            raise

    def retain_focus(self, grant: FocusGrant) -> None:
        if type(grant) is not FocusGrant or not self.admission.current_focus(grant):
            raise _denied()
        if grant.direction == "FORWARD":
            if not self.current(grant.lease_id):
                raise _denied()
        else:
            with self._lock:
                returning_main = self._dedicated.get(grant.lease_id)
            if (
                returning_main is None
                or not self.admission.current(returning_main.lease)
                or not self._dedicated_retained(returning_main)
            ):
                raise _denied()
        # Source callbacks can consume/cancel the pending reference. Observe it
        # again before committing the short local reference swap.
        if not self.admission.current_focus(grant):
            raise _denied()
        with self._lock:
            record = next(
                (r for r in self._records.values() if r.scope == grant.scope), None
            )
            source = self._viewers.get(grant.lease_id)
            main = self._dedicated.get(grant.lease_id)
            if (
                record is None
                or not self._active(record)
                or self._clock() >= grant.expires_monotonic
                or self._focus
                or (
                    grant.direction == "FORWARD"
                    and (
                        source is None or source.master is not record or source.stopping
                    )
                )
                or (
                    grant.direction == "RETURN"
                    and (
                        self._main_refs.get(grant.lease_id) is not record
                        or main is None
                        or main.stopping
                    )
                )
            ):
                raise _denied()
            # SQL has already consumed MAIN_ACTIVE before returning this ticket.
            # The local swap is one short mutation with no lifetime gap.
            self._focus[id(grant)] = grant
            if grant.direction == "FORWARD":
                assert source is not None
                self._focus_channels[id(grant)] = source.slot.identity.channel
            else:
                assert main is not None
                self._focus_channels[id(grant)] = main.selection.guid
            if grant.direction == "RETURN":
                del self._main_refs[grant.lease_id]
                self._main_acks.pop(grant.lease_id, None)
                assert main is not None
                main.focus_version += 1

    def settle_focus(
        self,
        grant: FocusGrant,
        outcome: Literal["ATTACHED", "CANCELLED", "FAILED", "EXPIRED"],
        *,
        viewer_id: UUID | None,
    ) -> None:
        if outcome not in ("ATTACHED", "CANCELLED", "FAILED", "EXPIRED"):
            raise _denied()
        with self._lock:
            if self._focus.get(id(grant)) is not grant:
                raise _denied()
            record = next(
                (r for r in self._records.values() if r.scope == grant.scope), None
            )
        if record is None:
            raise _denied()
        if outcome == "ATTACHED" and (
            viewer_id is None
            or self._clock() >= grant.expires_monotonic
            or not self.admission.current_focus(grant)
        ):
            raise _denied()
        target: ViewerRecord | DedicatedRecord | None = None
        transition_version: int | None = None
        if outcome == "ATTACHED":
            with self._lock:
                target_main = self._dedicated.get(cast(UUID, viewer_id))
                target_sub = self._viewers.get(cast(UUID, viewer_id))
                channel = self._focus_channels[id(grant)]
                if grant.direction == "FORWARD":
                    target = target_main
                    valid_target = (
                        target_main is not None
                        and target_main.master is record
                        and target_main.session is not None
                        and not target_main.stopping
                        and target_main.selection.guid == channel
                        and target_main.startup_focus is grant
                        and target_main.focus_phase is FocusStartupPhase.PENDING
                    )
                    if valid_target:
                        assert target_main is not None
                        # SQL retires the pending grant before its acknowledgement
                        # returns. Mark this exact transition before that callback.
                        target_main.focus_phase = FocusStartupPhase.SETTLING
                        target_main.focus_version += 1
                        transition_version = target_main.focus_version
                else:
                    target = target_sub
                    valid_target = (
                        target_sub is not None
                        and target_sub.master is record
                        and not target_sub.stopping
                        and target_sub.slot.identity.channel == channel
                    )
            if not valid_target:
                raise _denied()
        ack = self.admission.settle_focus(grant, outcome, viewer=viewer_id)
        acknowledged = (
            ack is not None
            and self.admission.focus_settlement_current(
                grant, ack, outcome, viewer=viewer_id
            )
            is True
        )
        unexpired = self._clock() < grant.expires_monotonic
        with self._lock:
            retained = self._focus.get(id(grant)) is grant
            target_current = True
            if outcome == "ATTACHED":
                if isinstance(target, DedicatedRecord):
                    target_current = (
                        self._dedicated.get(cast(UUID, viewer_id)) is target
                        and not target.stopping
                        and target.master is record
                        and target.selection.guid == channel
                        and grant.lease_id not in self._viewers
                        and target.focus_phase is FocusStartupPhase.SETTLING
                        and target.focus_version == transition_version
                    )
                elif isinstance(target, ViewerRecord):
                    target_current = (
                        self._viewers.get(cast(UUID, viewer_id)) is target
                        and not target.stopping
                        and target.master is record
                        and target.slot.identity.channel == channel
                        and grant.lease_id not in self._dedicated
                    )
                else:
                    target_current = False
                target_current = target_current and unexpired and self._active(record)
            applied = acknowledged and retained and target_current
            if applied:
                del self._focus[id(grant)]
                self._focus_channels.pop(id(grant), None)
                if outcome == "ATTACHED" and grant.direction == "FORWARD":
                    assert viewer_id is not None
                    self._main_refs[viewer_id] = record
                    self._main_acks[viewer_id] = (grant, ack)
                    assert isinstance(target, DedicatedRecord)
                    target.focus_phase = FocusStartupPhase.ACKNOWLEDGED
                    target.focus_version += 1
        if not applied:
            if outcome == "ATTACHED":
                try:
                    if retained:
                        self.settle_focus(
                            grant,
                            "EXPIRED" if not unexpired else "CANCELLED",
                            viewer_id=None,
                        )
                finally:
                    if isinstance(target, DedicatedRecord):
                        self._close_dedicated(target)
                    elif isinstance(target, ViewerRecord):
                        self._close_viewer(target)
            raise _denied()
        self._retire_if_unused(record)

    def attach_dedicated(
        self,
        viewer: LocalMediaLease,
        *,
        budget: LocalVerifyBudget,
        retain_local: Callable[[UUID, UUID], Callable[[], ViewerCleanupReceipt | None]]
        | None = None,
    ) -> OwnedLocalLiveSession:
        if viewer.id is None:
            raise _denied()
        selection = self.admission.prepare_viewer(viewer, budget=budget)
        with self._lock:
            focus = next(
                (g for g in self._focus.values() if g.direction == "FORWARD"), None
            )
            if focus is None or self._dedicated or selection.stream != "main":
                raise _denied()
            record = next(
                (r for r in self._records.values() if r.scope == focus.scope), None
            )
            if (
                record is None
                or not self._active(record)
                or focus.lease_id in self._viewers
                or selection.guid != self._focus_channels[id(focus)]
            ):
                raise _denied()
            owned = DedicatedRecord(viewer, record, uuid4(), selection)
            owned.startup_budget, owned.startup_focus = budget, focus
            self._dedicated[viewer.id] = owned
        try:
            if (
                not self.admission.current_focus(focus)
                or self._clock() >= focus.expires_monotonic
            ):
                raise _denied()
            with self._lock:
                # This dedicated record already accounts for its own main slot.
                if self._physical_slots() > 16:
                    raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)
            owned.original = self.budget.reserve("main")
            prepared = self.provider.prepare_dedicated(
                viewer, record.scope, owned.original, owned.registration
            )
            owned.prepared = prepared
            owned.native_issuer, owned.viewer_issuer = (
                prepared.native_issuer,
                prepared.viewer_issuer,
            )
            owned.native_receipt = owned.native_issuer.issued_receipt
            owned.viewer_receipt = owned.viewer_issuer.issued_receipt
            if retain_local is not None:
                attach_retirement = prepared.attach_retirement
                attach_retirement(retain_local(viewer.id, owned.registration))
            self.admission.register_dedicated(
                viewer,
                owned.native_issuer,
                owned.viewer_issuer,
                registration=owned.registration,
                budget=budget,
            )
            credentials, actual = self.admission.prepare_dedicated(
                viewer, budget=budget
            )
            try:
                if (
                    actual != selection
                    or not self._active(record)
                    or not self.admission.current_focus(focus)
                    or not self._dedicated_retained(owned)
                    or owned.stopping
                ):
                    raise _denied()
                owned.session = prepared.start(credentials, actual, budget=budget)
            finally:
                del credentials
            budget.remaining_ms()
            if (
                not self._active(record)
                or owned.stopping
                or self._clock() >= focus.expires_monotonic
                or not self._dedicated_retained(owned)
            ):
                raise _denied()
            owned.view = self.admission.activate(
                viewer, owned.session.proof, budget=budget
            )
            self.settle_focus(focus, "ATTACHED", viewer_id=viewer.id)
            budget.remaining_ms()
            if (
                not self.admission.current(viewer)
                or owned.stopping
                or not self._dedicated_retained(owned)
                or not self._active(record)
            ):
                raise _denied()
            return owned.session
        except BaseException:
            with self._lock:
                owned.stopping = True
            raise
        finally:
            with self._lock:
                owned.starting = False
            if owned.stopping:
                self._close_dedicated(owned)
                with self._lock:
                    still_pending = self._focus.get(id(focus)) is focus
                if still_pending:
                    self.settle_focus(
                        focus,
                        "EXPIRED"
                        if self._clock() >= focus.expires_monotonic
                        else "FAILED",
                        viewer_id=None,
                    )

    def _current_dedicated(
        self, owned: DedicatedRecord, *, deadline_monotonic: float | None = None
    ) -> bool:
        # Dedicated sweep and native suppliers need the same refresh barrier as
        # public current(). Share its total deadline when called from that path.
        until = min(
            time.monotonic() + 5,
            deadline_monotonic if deadline_monotonic is not None else float("inf"),
        )
        focus_changes = 0
        while time.monotonic() < until:
            with self._lock:
                record = owned.master
                if (
                    self._closed
                    or owned.stopping
                    or owned.starting
                    or self._dedicated.get(cast(UUID, owned.lease.id)) is not owned
                    or not self._retained(record)
                    or record.state is not EpochState.ACTIVE
                ):
                    return False
                version = owned.focus_version
                refresh_version, refreshing = record.refresh_version, record.refreshing
                if refreshing and record.refresh_owner == get_ident():
                    return False
            if refreshing:
                record.refresh_done.wait(min(0.05, max(0, until - time.monotonic())))
                continue
            accepted = self._current_dedicated_once(owned)
            if time.monotonic() >= until:
                return False
            with self._lock:
                if (
                    self._closed
                    or owned.stopping
                    or self._dedicated.get(cast(UUID, owned.lease.id)) is not owned
                    or not self._retained(record)
                    or record.state is not EpochState.ACTIVE
                ):
                    return False
                if record.refreshing or record.refresh_version != refresh_version:
                    continue
                if owned.focus_version == version:
                    return accepted
                focus_changes += 1
                if focus_changes >= 2:
                    return False
        return False

    def _current_dedicated_once(self, owned: DedicatedRecord) -> bool:
        with self._lock:
            if owned.stopping or owned.starting or not self._active(owned.master):
                return False
            active = self._main_acks.get(cast(UUID, owned.lease.id))
            pending = next(
                (
                    g
                    for g in self._focus.values()
                    if g.direction == "RETURN" and g.lease_id == owned.lease.id
                ),
                None,
            )
        if active is None and pending is None:
            return False
        try:
            if pending is not None:
                accepted_ref = (
                    self._clock() < pending.expires_monotonic
                    and self.admission.current_focus(pending)
                )
            else:
                assert active is not None
                accepted_ref = cast(
                    MainRetentionObserver, self.admission
                ).current_main_retention(owned.lease, active[0], active[1])
            accepted = accepted_ref and self.admission.current(owned.lease)
            retained_original = self._dedicated_retained(owned)
        except Exception:  # noqa: BLE001 -- Callback failures deny and retain custody.
            return False
        with self._lock:
            return (
                accepted
                and self._dedicated.get(cast(UUID, owned.lease.id)) is owned
                and not owned.stopping
                and self._active(owned.master)
                and retained_original
                and self._main_acks.get(cast(UUID, owned.lease.id)) is active
                and (pending is None or self._focus.get(id(pending)) is pending)
            )

    def _dedicated_retained(self, owned: DedicatedRecord) -> bool:
        with self._lock:
            prepared = owned.prepared
            native, viewer = owned.native_issuer, owned.viewer_issuer
            native_receipt, viewer_receipt = owned.native_receipt, owned.viewer_receipt
        if prepared is None or native is None or viewer is None:
            return False
        same_issuers = (
            prepared.native_issuer is native and prepared.viewer_issuer is viewer
        )
        same_methods = (
            native.issued_receipt == native_receipt
            and viewer.issued_receipt == viewer_receipt
        )
        original_current = self._original_current(owned.master)
        with self._lock:
            return (
                self._dedicated.get(cast(UUID, owned.lease.id)) is owned
                and same_issuers
                and same_methods
                and original_current
                and owned.prepared is prepared
                and owned.native_issuer is native
                and owned.viewer_issuer is viewer
                and owned.native_receipt is native_receipt
                and owned.viewer_receipt is viewer_receipt
                and self._retained(owned.master)
            )

    def _close_dedicated(self, owned: DedicatedRecord) -> bool:
        with self._lock:
            owned.stopping = True
            self._main_refs.pop(cast(UUID, owned.lease.id), None)
            self._main_acks.pop(cast(UUID, owned.lease.id), None)
            if owned.starting or owned.closing:
                return False
            owned.closing = True
        try:
            prepared = owned.prepared
            if (
                prepared is None
                or owned.native_issuer is None
                or owned.viewer_issuer is None
                or owned.original is None
            ):
                return False
            if (
                prepared.native_issuer is not owned.native_issuer
                or prepared.viewer_issuer is not owned.viewer_issuer
                or not self._dedicated_retained(owned)
            ):
                return False
            if not owned.local_settled:
                local_receipt = prepared.close_viewer()
                if (
                    local_receipt is not None
                    and owned.viewer_issuer.issued_receipt() is local_receipt
                    and self._dedicated_retained(owned)
                ):
                    self.admission.finish_dedicated_viewer(owned.lease, local_receipt)
                    owned.local_settled = True
            if not owned.native_settled:
                native_receipt = prepared.close_native()
                if (
                    native_receipt is not None
                    and owned.native_issuer.issued_receipt() is native_receipt
                    and self._dedicated_retained(owned)
                ):
                    self.admission.finish_dedicated(owned.lease, native_receipt)
                    self.budget.release_confirmed(owned.original, native_receipt)
                    owned.native_settled = True
            if owned.local_settled and owned.native_settled:
                self._remember_closed(owned.view)
                with self._lock:
                    if self._dedicated.get(cast(UUID, owned.lease.id)) is owned:
                        del self._dedicated[cast(UUID, owned.lease.id)]
                return True
            return False
        except Exception:  # noqa: BLE001 -- Callback failures deny and retain custody.
            return False
        finally:
            with self._lock:
                owned.closing = False
            self._retire_if_unused(owned.master)

    def _physical_slots(self) -> int:
        return len(self._dedicated) + sum(
            len(r.slots)
            for r in self._records.values()
            if r.state is not EpochState.CLOSED
        )

    def _check_replacement(
        self,
        old: TransportGrant | SlotRetentionGrant | ViewerGrant,
        new: TransportGrant | SlotRetentionGrant | ViewerGrant,
    ) -> None:
        if (
            type(old) is not type(new)
            or old.scope != new.scope
            or old._authority is not new._authority
            or new.expires_monotonic <= self._clock()
        ):
            raise _denied()
        if isinstance(old, TransportGrant):
            if (
                not isinstance(new, TransportGrant)
                or old.native_generation != new.native_generation
            ):
                raise _denied()
        elif isinstance(new, SlotRetentionGrant) and old.slot is not new.slot:
            raise _denied()
        if isinstance(old, ViewerGrant) and (
            not isinstance(new, ViewerGrant)
            or old.lease_id != new.lease_id
            or old.registration != new.registration
        ):
            raise _denied()

    def heartbeat(self, ticket: str, *, budget: LocalVerifyBudget) -> UUID:
        wall = self.admission.redeem_wall_heartbeat(ticket, budget=budget)
        while True:
            budget.remaining_ms()
            with self._lock:
                if (
                    self._closed
                    or wall in self._stopped_walls
                    or (self._actor is not None and self._actor[4] != wall)
                ):
                    raise _denied()
                records = tuple(
                    r
                    for r in self._records.values()
                    if r.scope.wall_id == wall and r.state is not EpochState.CLOSED
                )
                if any(
                    r.state not in (EpochState.STARTING, EpochState.ACTIVE)
                    or self._clock() >= r.transport.expires_monotonic
                    for r in records
                ):
                    raise _denied()
                pending = self._pending_reservations or any(
                    r.state is EpochState.STARTING
                    or r.refreshing
                    or r.attaching
                    or r.opening
                    for r in records
                )
                if not pending:
                    for record in records:
                        record.refreshing = True
                        record.refresh_owner = get_ident()
                        record.refresh_version += 1
                        record.refresh_done.clear()
                    break
            budget.cancel.wait(min(0.01, budget.remaining_ms() / 1000))
        try:
            for record in records:
                with self._lock:
                    slots = tuple(record.slots.values())
                    viewers = tuple(
                        v
                        for v in self._viewers.values()
                        if v.master is record and not v.stopping
                    )
                try:
                    prepared = record.prepared
                    if prepared is None:
                        raise _denied()
                    # Native IO and purpose checks settle BEFORE any immutable
                    # admission capability is invalidated. State locks remain short.
                    with prepared.refresh_grants(budget=budget):
                        budget.remaining_ms()
                        old_transport = record.transport
                        transport = self.admission.refresh_grant(old_transport)
                        self._check_replacement(old_transport, transport)
                        prepared.replace_grant(old_transport, transport)
                        with self._lock:
                            record.transport = transport
                        for slot in slots:
                            budget.remaining_ms()
                            old_slot = slot.grant
                            fresh_slot = self.admission.refresh_grant(old_slot)
                            self._check_replacement(old_slot, fresh_slot)
                            prepared.replace_grant(old_slot, fresh_slot)
                            with self._lock:
                                slot.grant = fresh_slot
                        for viewer in viewers:
                            budget.remaining_ms()
                            old_viewer = viewer.grant
                            fresh_viewer = self.admission.refresh_grant(old_viewer)
                            self._check_replacement(old_viewer, fresh_viewer)
                            prepared.replace_grant(old_viewer, fresh_viewer)
                            with self._lock:
                                viewer.grant = fresh_viewer
                        budget.remaining_ms()
                        with self._lock:
                            if record.state is not EpochState.ACTIVE or self._closed:
                                raise _denied()
                except BaseException:
                    self._fence(record)
                    raise
        finally:
            with self._lock:
                for record in records:
                    record.refreshing = False
                    record.refresh_owner = None
                    record.refresh_version += 1
                    record.refresh_done.set()
        return wall

    def settle_focus_control(self, ticket: str, *, budget: LocalVerifyBudget) -> UUID:
        focus_id, wall_id, outcome = self.admission.redeem_focus_settle(
            ticket, budget=budget
        )
        with self._lock:
            candidates = tuple(
                g for g in self._focus.values() if g.scope.wall_id == wall_id
            )
        for grant in candidates:
            if self.admission.focus_identity(grant) == (focus_id, wall_id):
                self.settle_focus(grant, outcome, viewer_id=None)
                return focus_id
        raise _denied()

    def stop_wall_ticket(self, ticket: str, *, budget: LocalVerifyBudget) -> bool:
        return self.stop_wall_result(ticket, budget=budget)[1]

    def stop_wall_result(
        self, ticket: str, *, budget: LocalVerifyBudget
    ) -> tuple[UUID, bool]:
        """Exact one-use redemption identity for scope-correlated RPC readback."""
        wall_id = self.admission.redeem_wall_stop(ticket, budget=budget)
        return wall_id, self.stop_wall(wall_id, budget=budget)

    def stop_wall(self, wall_id: UUID, *, budget: LocalVerifyBudget) -> bool:
        """Internal disposal port; remote callers must use stop_wall_ticket."""
        budget.remaining_ms()
        with self._lock:
            if self._closed or (self._actor is not None and self._actor[4] != wall_id):
                raise _denied()
            self._stopped_walls.add(wall_id)
            pending = bool(self._pending_reservations)
            records = tuple(
                r for r in self._records.values() if r.scope.wall_id == wall_id
            )
            focus = tuple(g for g in self._focus.values() if g.scope.wall_id == wall_id)
            mains = tuple(
                d for d in self._dedicated.values() if d.master.scope.wall_id == wall_id
            )
            for record in records:
                if record.state is not EpochState.CLOSED:
                    record.state = EpochState.STOPPING
        for grant in focus:
            self.settle_focus(
                grant,
                "EXPIRED" if self._clock() >= grant.expires_monotonic else "CANCELLED",
                viewer_id=None,
            )
        for main in mains:
            self._close_dedicated(main)
        for record in records:
            self._fence(record)
        self.recover_reservations(budget=budget)
        with self._lock:
            return (
                not pending
                and not self._pending_reservations
                and not any(
                    r.scope.wall_id == wall_id
                    for r in self._unadopted_reservations.values()
                )
                and all(
                    r.state is EpochState.CLOSED
                    and r.done.is_set()
                    and not r.attaching
                    and not r.opening
                    and not r.refreshing
                    and not r.retiring
                    for r in records
                )
                and not any(v.master in records for v in self._viewers.values())
                and not any(d.master in records for d in self._dedicated.values())
                and not any(g.scope.wall_id == wall_id for g in self._focus.values())
                and not any(
                    r.scope.wall_id == wall_id for r in self._main_refs.values()
                )
            )

    def sweep(self) -> None:
        self.recover_reservations(budget=LocalVerifyBudget(1000, clock=self._clock))
        with self._lock:
            records = tuple(self._records.values())
            viewers = tuple(self._viewers.values())
            focus = tuple(self._focus.values())
            dedicated = tuple(self._dedicated.values())
        for grant in focus:
            if self._clock() >= grant.expires_monotonic:
                try:
                    self.settle_focus(grant, "EXPIRED", viewer_id=None)
                except Exception:  # noqa: BLE001 -- Callback failures deny and retain custody.
                    # Keep an unsettled SQL reference visible for retries.
                    for record in records:
                        if record.scope == grant.scope:
                            self._fence(record)
        for record in records:
            with self._lock:
                if record.refreshing:
                    continue
                active = record.state is EpochState.ACTIVE
                version, transport = record.refresh_version, record.transport
                slots = tuple((slot, slot.grant) for slot in record.slots.values())
            if not active:
                self._retire_master(record)
                continue
            try:
                valid = self.admission.current_transport(transport)
                for _slot, slot_grant in slots:
                    valid = self.admission.current_slot(slot_grant) and valid
            except Exception:  # noqa: BLE001 -- Callback failures deny and retain custody.
                valid = False
            with self._lock:
                if (
                    not self._retained(record)
                    or record.refreshing
                    or record.refresh_version != version
                    or record.transport is not transport
                    or any(slot.grant is not grant for slot, grant in slots)
                    or record.state is not EpochState.ACTIVE
                ):
                    continue
                if not valid:
                    # Claim denial before a new refresh can begin.
                    record.state = EpochState.STOPPING
            if not valid:
                self._fence(record)
        for owned in viewers:
            if owned.starting:
                if not self._pending_current(owned):
                    self._close_viewer(owned)
                continue
            if owned.stopping or not self.current(owned.grant.lease_id):
                self._close_viewer(owned)
        for main in dedicated:
            if main.starting:
                if not self._pending_current(main):
                    self._close_dedicated(main)
                continue
            if main.master.refreshing:
                continue
            accepted = not main.stopping and self._current_dedicated(main)
            if accepted and main.session is not None:

                def still_current(original: DedicatedRecord = main) -> bool:
                    return self._current_dedicated(original)

                try:
                    accepted = main.session.current(
                        deadline_monotonic=self._clock() + 30,
                        current=still_current,
                    ) and self._current_dedicated(main)
                except Exception:  # noqa: BLE001 -- Uncertain native maintenance denies.
                    accepted = False
            if not accepted:
                self._close_dedicated(main)

    def _pending_current(self, owned: ViewerRecord | DedicatedRecord) -> bool:
        with self._lock:
            if (
                owned.stopping
                or self._closed
                or owned.master.state is not EpochState.ACTIVE
            ):
                return False
            budget = owned.startup_budget
            version, refreshing = owned.master.refresh_version, owned.master.refreshing
            focus_version = (
                owned.focus_version if isinstance(owned, DedicatedRecord) else None
            )
            phase = owned.focus_phase if isinstance(owned, DedicatedRecord) else None
        try:
            if budget is None:
                return False
            budget.remaining_ms()
            if refreshing:
                accepted = True  # Defer observation of temporarily superseded grants.
            elif isinstance(owned, ViewerRecord):
                accepted = self.admission.current_viewer(owned.grant)
            else:
                with self._lock:
                    focus = owned.startup_focus
                    pending = focus is not None and self._focus.get(id(focus)) is focus
                    active_ack = self._main_acks.get(cast(UUID, owned.lease.id))
                    transport = owned.master.transport
                    slot = owned.master.slots.get(owned.selection.guid)
                    slot_grant = None if slot is None else slot.grant
                if phase is FocusStartupPhase.SETTLING:
                    # This defers only the obsolete pending-reference observation
                    # while the exact ATTACHED call/ack observer is in flight.
                    # It cannot publish MAIN_ACTIVE. Keep checking real authority,
                    # original custody and both bounded startup deadlines.
                    accepted = (
                        pending
                        and focus is not None
                        and self._clock() < focus.expires_monotonic
                        and slot_grant is not None
                        and self.admission.current_transport(transport)
                        and self.admission.current_slot(slot_grant)
                        and self.admission.current(owned.lease)
                        and self._dedicated_retained(owned)
                    )
                elif phase is FocusStartupPhase.ACKNOWLEDGED:
                    accepted = (
                        active_ack is not None
                        and self.admission.focus_settlement_current(
                            active_ack[0],
                            active_ack[1],
                            "ATTACHED",
                            viewer=owned.lease.id,
                        )
                        and self.admission.current(owned.lease)
                    )
                else:
                    accepted = (
                        pending
                        and focus is not None
                        and self.admission.current_focus(focus)
                    )
            budget.remaining_ms()
        except Exception:  # noqa: BLE001 -- Actual startup denial remains terminal.
            accepted = False
        with self._lock:
            retained = (
                self._viewers.get(owned.grant.lease_id) is owned
                if isinstance(owned, ViewerRecord)
                else self._dedicated.get(cast(UUID, owned.lease.id)) is owned
            )
            if (
                not retained
                or owned.stopping
                or self._closed
                or owned.master.state is not EpochState.ACTIVE
            ):
                return False
            became_active = not owned.starting
            if not became_active:
                if owned.master.refresh_version != version:
                    return True
                if (
                    isinstance(owned, DedicatedRecord)
                    and owned.focus_version != focus_version
                ):
                    # A pending-phase answer cannot judge a later exact transition.
                    # Its constructor/current-phase observer owns that decision.
                    return True
                if not accepted:
                    # Claim real pending denial before the constructor publishes.
                    owned.stopping = True
                return accepted
        # A constructor that completed during SQL observation now has the active
        # lease lifetime. Its obsolete startup timer cannot retire that viewer.
        return self.current(cast(UUID, owned.lease.id))

    def shutdown(self) -> bool:
        with self._lock:
            self._closed = True
            records = tuple(self._records.values())
            viewers = tuple(self._viewers.values())
            dedicated = tuple(self._dedicated.values())
            focus = tuple(self._focus.values())
        for grant in focus:
            try:
                self.settle_focus(
                    grant,
                    "EXPIRED"
                    if self._clock() >= grant.expires_monotonic
                    else "CANCELLED",
                    viewer_id=None,
                )
            except Exception:  # noqa: BLE001,S112 -- Pending focus keeps shutdown False.
                continue
        for main in dedicated:
            self._close_dedicated(main)
        for owned in viewers:
            self._close_viewer(owned)
        self.recover_reservations(budget=LocalVerifyBudget(1000, clock=self._clock))
        results = [self._retire_master(record) for record in records]
        for owned in viewers:
            self._close_viewer(owned)
        with self._lock:
            return all(results) and self._affinity_settled()


class MuxMediaExecutor:
    """Explicit shared profile; only the dedicated main path reads raw frames."""

    def __init__(
        self,
        admission: SqlMuxAdmission,
        coordinator: DeviceEpochCoordinator,
        *,
        clock: Callable[[], float] = time.monotonic,
        monitor_interval: float = 1.0,
    ) -> None:
        if not 0 <= monitor_interval <= 1:
            raise ValueError("invalid mux monitor interval")
        self.admission, self.coordinator, self._clock = admission, coordinator, clock
        self._stop = Event()
        self._closed: dict[UUID, MediaLease] = {}
        self._thread: Thread | None = None
        if monitor_interval:

            def monitor() -> None:
                while not self._stop.wait(monitor_interval):
                    self.coordinator.sweep()

            self._thread = Thread(
                target=monitor, daemon=True, name="mux-media-authority"
            )
            self._thread.start()

    def _lease(self, lease_id: UUID, *, current: bool = True) -> LocalMediaLease:
        if current and not self.current(lease_id):
            raise _denied()
        with self.coordinator._lock:
            viewer = self.coordinator._viewers.get(lease_id)
            main = self.coordinator._dedicated.get(lease_id)
            if viewer is not None:
                return viewer.lease
            if main is not None:
                return main.lease
        raise _denied()

    def start(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: Event | None = None,
        retain_local: Callable[[UUID, UUID], Callable[[], ViewerCleanupReceipt | None]]
        | None = None,
    ) -> LocalLiveResponse:
        LocalMediaExecutor._input(ticket, correlation_id)
        if self._stop.is_set():
            raise _denied()
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock, cancel=cancel)
        lease = self.admission.redeem(ticket, budget=budget)
        if lease.id is None:
            raise _denied()
        try:
            selection = self.admission.prepare_viewer(lease, budget=budget)
            options = {} if retain_local is None else {"retain_local": retain_local}
            if selection.stream == "sub":
                self.coordinator.attach(lease, budget=budget, **options)
            elif selection.stream == "main":
                self.coordinator.attach_dedicated(lease, budget=budget, **options)
            else:
                raise _denied()
            budget.remaining_ms()
            if not self.current(lease.id):
                raise _denied()
            return LocalLiveResponse(
                lease=self.lease(lease.id), request_id=correlation_id
            )
        except BaseException:
            self.close(lease.id)
            raise

    def current(self, lease_id: UUID) -> bool:
        return not self._stop.is_set() and self.coordinator.current(lease_id)

    def source_mode(self, lease_id: UUID) -> Literal["sub", "main"]:
        """Select the exact completed entry's reader; grants no read authority."""
        lease = self._lease(lease_id)
        with self.coordinator._lock:
            viewer = self.coordinator._viewers.get(lease_id)
            main = self.coordinator._dedicated.get(lease_id)
            if (
                viewer is not None
                and main is None
                and viewer.lease is lease
                and not viewer.starting
                and not viewer.stopping
                and viewer.view is not None
            ):
                return "sub"
            if (
                main is not None
                and viewer is None
                and main.lease is lease
                and not main.starting
                and not main.stopping
                and main.view is not None
                and main.session is not None
            ):
                return "main"
        raise _denied()

    def mux_binding(self, lease_id: UUID) -> tuple[PreparedMuxViewer, ViewerGrant]:
        until = time.monotonic() + 5
        while time.monotonic() < until:
            with self.coordinator._lock:
                original = self.coordinator._viewers.get(lease_id)
                if original is None or original.stopping:
                    raise _denied()
                master, handle, grant = original.master, original.handle, original.grant
                version = master.refresh_version
                refreshing = master.refreshing
            if refreshing:
                master.refresh_done.wait(min(0.01, max(0, until - time.monotonic())))
                continue
            result = None
            try:
                result = self._mux_binding_once(lease_id)
            except LocalDeviceFailure:
                # Only a proven same-original refresh can supersede this snapshot.
                # Denial without that generation change is never retryable.
                with self.coordinator._lock:
                    if master.refresh_version == version and not master.refreshing:
                        raise
            with self.coordinator._lock:
                if (
                    self.coordinator._viewers.get(lease_id) is not original
                    or original.master is not master
                    or original.handle is not handle
                    or original.stopping
                    or master.state is not EpochState.ACTIVE
                    or self.coordinator._closed
                    or time.monotonic() >= grant.expires_monotonic
                ):
                    raise _denied()
                changed = master.refresh_version != version or master.refreshing
                replacement = original.grant
            if changed:
                if replacement is not grant:
                    self.coordinator._check_replacement(grant, replacement)
                continue
            if result is not None and time.monotonic() < until:
                return result
            raise _denied()
        raise _denied()

    def _mux_binding_once(
        self, lease_id: UUID
    ) -> tuple[PreparedMuxViewer, ViewerGrant]:
        self._lease(lease_id)
        with self.coordinator._lock:
            owned = self.coordinator._viewers.get(lease_id)
            if owned is None:
                raise _denied()
            handle, grant = owned.handle, owned.grant
        actual = handle.current_grant()
        if actual is not grant or not self.current(lease_id):
            raise _denied()
        registration, cut = handle.registration, handle.cut
        with self.coordinator._lock:
            if (
                self.coordinator._viewers.get(lease_id) is not owned
                or owned.handle is not handle
                or owned.grant is not grant
                or owned.stopping
                or grant.scope != owned.master.scope
                or grant.registration != registration
                or cut is not owned.cut
            ):
                raise _denied()
        return handle, grant

    def registration(self, lease_id: UUID) -> UUID:
        """Cleanup identity only; STOPPING does not authorize publication."""
        with self.coordinator._lock:
            viewer = self.coordinator._viewers.get(lease_id)
            main = self.coordinator._dedicated.get(lease_id)
            if viewer is not None:
                return viewer.grant.registration
            if main is not None:
                return main.registration
        raise _denied()

    def lease(self, lease_id: UUID) -> MediaLease:
        return self.admission.view(self._lease(lease_id))

    def proof(self, lease_id: UUID) -> LocalLiveProof:
        self._lease(lease_id)
        with self.coordinator._lock:
            viewer = self.coordinator._viewers.get(lease_id)
            main = self.coordinator._dedicated.get(lease_id)
        if viewer is not None:
            proof = viewer.handle.proof
        elif main is not None and main.session is not None:
            proof = main.session.proof
        else:
            raise _denied()
        proof.validate(delivery=True)
        if not self.current(lease_id):
            raise _denied()
        return proof

    def binding_proof(self, lease_id: UUID) -> LocalLiveProof:
        """Initial identity/permission binding; never decoded delivery evidence."""
        self._lease(lease_id)
        with self.coordinator._lock:
            viewer = self.coordinator._viewers.get(lease_id)
            main = self.coordinator._dedicated.get(lease_id)
            source: MuxViewerHandle | OwnedLocalLiveSession | None = (
                viewer.handle
                if viewer is not None
                else main.session
                if main is not None
                else None
            )
        if source is None:
            raise _denied()
        proof = source.proof
        if type(proof) is not LocalLiveProof:
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        proof.validate(delivery=False)
        if not self.current(lease_id):
            raise _denied()
        with self.coordinator._lock:
            if viewer is not None:
                retained = (
                    self.coordinator._viewers.get(lease_id) is viewer
                    and viewer.handle is source
                    and not viewer.stopping
                )
            else:
                retained = (
                    main is not None
                    and self.coordinator._dedicated.get(lease_id) is main
                    and main.session is source
                    and not main.stopping
                )
            if not retained:
                raise _denied()
        return proof

    def attach_retirement(
        self,
        lease_id: UUID,
        check: Callable[[], ViewerCleanupReceipt | None],
    ) -> None:
        self._lease(lease_id)
        with self.coordinator._lock:
            viewer = self.coordinator._viewers.get(lease_id)
            main = self.coordinator._dedicated.get(lease_id)
        if viewer is not None:
            viewer.handle.attach_retirement(check)
        elif main is not None and main.prepared is not None:
            main.prepared.attach_retirement(check)
        else:
            raise _denied()
        if not self.current(lease_id):
            self.close(lease_id)
            raise _denied()

    @staticmethod
    def _read_limits(max_frames: int, max_bytes: int) -> None:
        if (
            type(max_frames) is not int
            or not 1 <= max_frames <= 16
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 8 * 1024 * 1024
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)

    def read_frames(
        self,
        lease_id: UUID,
        *,
        max_frames: int,
        max_bytes: int,
        deadline_ms: int,
    ) -> tuple[PrivateLiveFrame, ...]:
        raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)

    def read_mux_frames(
        self,
        lease_id: UUID,
        *,
        max_frames: int,
        max_bytes: int,
        deadline_ms: int,
    ) -> tuple[MuxValidatedFrame, ...]:
        self._read_limits(max_frames, max_bytes)
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock)
        self._lease(lease_id)
        with self.coordinator._lock:
            owned = self.coordinator._viewers.get(lease_id)
        if owned is None:
            raise _denied()
        frames: tuple[MuxValidatedFrame, ...] | None = None
        try:
            frames = owned.handle.read_frames(
                max_frames=max_frames,
                max_bytes=max_bytes,
                deadline_monotonic=budget.deadline_monotonic,
            )
            budget.remaining_ms()
            if not self.current(lease_id):
                raise _denied()
            if (
                type(frames) is not tuple
                or len(frames) > max_frames
                or any(
                    type(frame) is not MuxValidatedFrame
                    or frame.slot != owned.slot.identity
                    or frame.ingress.first <= owned.handle.cut.after_ordinal
                    for frame in frames
                )
                or sum(len(f.frame.private_bytes()) for f in frames) > max_bytes
            ):
                raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
            return frames
        except BaseException:
            try:
                if frames is not None:
                    owned.handle.release_frames(frames)
            finally:
                self.close(lease_id)
            raise

    def release_mux_frames(
        self, lease_id: UUID, frames: tuple[MuxValidatedFrame, ...]
    ) -> None:
        # Cleanup only: exact outstanding batches remain releasable in STOPPING.
        with self.coordinator._lock:
            owned = self.coordinator._viewers.get(lease_id)
        if owned is None:
            raise _denied()
        owned.handle.release_frames(frames)

    def read_dedicated_frames(
        self,
        lease_id: UUID,
        *,
        max_frames: int,
        max_bytes: int,
        deadline_ms: int,
    ) -> tuple[PrivateLiveFrame, ...]:
        self._read_limits(max_frames, max_bytes)
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock)
        self._lease(lease_id)
        with self.coordinator._lock:
            owned = self.coordinator._dedicated.get(lease_id)
        if owned is None or owned.session is None:
            raise _denied()
        try:
            frames = owned.session.read_frames(
                max_frames=max_frames,
                max_bytes=max_bytes,
                deadline_monotonic=budget.deadline_monotonic,
                current=lambda: self.current(lease_id),
            )
            budget.remaining_ms()
            if not self.current(lease_id):
                raise _denied()
            if (
                type(frames) is not tuple
                or len(frames) > max_frames
                or any(type(frame) is not PrivateLiveFrame for frame in frames)
                or sum(len(f.private_bytes()) for f in frames) > max_bytes
            ):
                raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
            return frames
        except BaseException:
            self.close(lease_id)
            raise

    def authorize_control(
        self,
        ticket: str,
        purpose: str,
        *,
        deadline_ms: int,
        cancel: Event | None = None,
    ) -> UUID:
        LocalMediaExecutor._input(ticket, "control")
        if purpose not in {"offer", "stop", "playing"}:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock, cancel=cancel)
        lease_id = self.admission.redeem_control(ticket, purpose, budget=budget)
        if purpose != "stop":
            self._lease(lease_id)
        budget.remaining_ms()
        return lease_id

    def playing(self, lease_id: UUID, proof: LocalLiveProof) -> MediaLease:
        proof.validate(delivery=True)
        return self.admission.playing(self._lease(lease_id), proof)

    def close(self, lease_id: UUID) -> bool:
        with self.coordinator._lock:
            owned = self.coordinator._viewers.get(lease_id)
            main = self.coordinator._dedicated.get(lease_id)
        if owned is not None:
            return self.coordinator._close_viewer(owned)
        if main is not None:
            return self.coordinator._close_dedicated(main)
        return lease_id in self._closed

    def finish_stop(self, lease_id: UUID, *, correlation_id: str) -> LocalLiveResponse:
        LocalMediaExecutor._input("0" * 64, correlation_id)
        with self.coordinator._lock:
            closed = self.coordinator._closed_views.get(lease_id)
        if closed is not None:
            return LocalLiveResponse(lease=closed, request_id=correlation_id)
        if lease_id in self._closed:
            return LocalLiveResponse(
                lease=self._closed[lease_id], request_id=correlation_id
            )
        self._lease(lease_id, current=False)
        if not self.close(lease_id):
            raise LocalDeviceFailure()
        with self.coordinator._lock:
            view = self.coordinator._closed_views.get(lease_id)
        if view is None or view.state != "CLOSED":
            raise LocalDeviceFailure()
        self._closed[lease_id] = view
        while len(self._closed) > 32:
            self._closed.pop(next(iter(self._closed)))
        return LocalLiveResponse(lease=view, request_id=correlation_id)

    def stop(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: Event | None = None,
    ) -> LocalLiveResponse:
        LocalMediaExecutor._input(ticket, correlation_id)
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock, cancel=cancel)
        lease_id = self.authorize_control(
            ticket, "stop", deadline_ms=budget.remaining_ms(), cancel=cancel
        )
        response = self.finish_stop(lease_id, correlation_id=correlation_id)
        budget.remaining_ms()
        return response

    def shutdown(self) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        return self.coordinator.shutdown() and (
            self._thread is None or not self._thread.is_alive()
        )
