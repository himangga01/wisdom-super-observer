"""Sealed quotas retain pending originals until their actual custodian settles."""

from __future__ import annotations

import multiprocessing
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, BinaryIO, Literal, cast
from uuid import UUID, uuid4

from wso_core.tvt.local_media_mux_types import (
    _CUSTODY_SEAL,
    EpochCleanupReceipt,
    MuxEpochIdentity,
    MuxOriginalReservation,
    MuxScopeKey,
    MuxSlotIdentity,
)

from .local_inventory_ipc import ParentAuthority
from .local_live_mux_ipc import MuxParentAuthority
from .windows_socket import (
    ChildOwner,
    OwnedJob,
    ProviderBusy,
    fail,
    pending_owner_snapshot,
)

_CONSTRUCTOR_SEAL = object()


class MuxOriginalBudget:
    def __init__(self, *, worker_epoch: UUID) -> None:
        if type(worker_epoch) is not UUID or not worker_epoch.int:
            fail()
        self.worker_epoch = worker_epoch
        self._issuer = object()
        self._lock = threading.RLock()
        self._reservations: dict[UUID, MuxOriginalReservation] = {}
        self._custodians: dict[UUID, MuxOriginalCustodian] = {}
        self._slots: dict[UUID, set[MuxSlotIdentity]] = {}

    def reserve(self, kind: Literal["base", "main"]) -> MuxOriginalReservation:
        if kind not in ("base", "main"):
            fail()
        with self._lock:
            if kind == "main" and self._physical_slots() >= 16:
                raise ProviderBusy()
            if sum(r.kind == kind for r in self._reservations.values()) >= (
                2 if kind == "base" else 1
            ):
                raise ProviderBusy()
            reservation = MuxOriginalReservation(
                id=uuid4(),
                kind=kind,
                worker_epoch=self.worker_epoch,
                _authority=self._issuer,
                _seal=_CUSTODY_SEAL,
            )
            self._reservations[reservation.id] = reservation
            self._slots[reservation.id] = set()
            return reservation

    def _physical_slots(self) -> int:
        return sum(map(len, self._slots.values())) + sum(
            r.kind == "main" for r in self._reservations.values()
        )

    def _require(self, reservation: MuxOriginalReservation) -> None:
        if (
            type(reservation) is not MuxOriginalReservation
            or reservation._authority is not self._issuer
            or self._reservations.get(reservation.id) is not reservation
            or reservation.worker_epoch != self.worker_epoch
        ):
            fail()

    def prepare(
        self,
        reservation: MuxOriginalReservation,
        *,
        scope: MuxScopeKey,
        master_id: UUID,
        native_generation: UUID,
    ) -> MuxOriginalCustodian:
        with self._lock:
            self._require(reservation)
            if reservation.id in self._custodians:
                fail()
            custodian = MuxOriginalCustodian(
                self,
                reservation,
                scope,
                master_id,
                native_generation,
                _seal=_CONSTRUCTOR_SEAL,
            )
            self._custodians[reservation.id] = custodian
            return custodian

    def bind_original(
        self, reservation: MuxOriginalReservation, owner: ChildOwner
    ) -> None:
        with self._lock:
            self._require(reservation)
            custodian = self._custodians.get(reservation.id)
            if custodian is None:
                fail()
            custodian._bind(owner)

    def register_slot(
        self, reservation: MuxOriginalReservation, slot: MuxSlotIdentity
    ) -> None:
        """Physical opens, including future parked/tombstoned tasks, stay charged."""
        with self._lock:
            self._require(reservation)
            if type(slot) is not MuxSlotIdentity or reservation.kind != "base":
                fail()
            slots = self._slots[reservation.id]
            if slot in slots:
                return
            if self._physical_slots() >= 16:
                raise ProviderBusy()
            slots.add(slot)

    def release_confirmed(
        self,
        reservation: MuxOriginalReservation,
        receipt: EpochCleanupReceipt,
    ) -> None:
        with self._lock:
            self._require(reservation)
            custodian = self._custodians.get(reservation.id)
            if (
                custodian is None
                or type(receipt) is not EpochCleanupReceipt
                or receipt._authority is not custodian._issuer
                or receipt is not custodian._receipt
                or receipt.worker_epoch != self.worker_epoch
                or receipt.master_id != custodian.master_id
                or receipt.native_generation != custodian.native_generation
                or not custodian._settled()
            ):
                fail()
            del self._reservations[reservation.id]
            del self._custodians[reservation.id]
            del self._slots[reservation.id]


class MuxOriginalCustodian:
    """One registered constructor; no receipt can replace actual retained handles.

    Task7 must attach the exact parent before it can issue native/IPC operations.
    An interrupted Popen call with no returned original is permanently uncertain.
    """

    def __init__(
        self,
        budget: MuxOriginalBudget,
        reservation: MuxOriginalReservation,
        scope: MuxScopeKey,
        master_id: UUID,
        native_generation: UUID,
        *,
        _seal: object,
    ) -> None:
        if (
            _seal is not _CONSTRUCTOR_SEAL
            or type(scope) is not MuxScopeKey
            or scope.worker_epoch != reservation.worker_epoch
            or any(
                type(v) is not UUID or not v.int for v in (master_id, native_generation)
            )
        ):
            fail()
        self.budget, self.reservation, self.scope = budget, reservation, scope
        self.master_id, self.native_generation = master_id, native_generation
        self._issuer = object()
        self._lock = threading.RLock()
        self.owner: ChildOwner | None = None
        self._original_owner: ChildOwner | None = None
        self.parent: MuxParentAuthority | None = None
        self.pipe: Any = None
        self._child: subprocess.Popen[bytes] | None = None
        self._process_attempted = False
        self._acquisition_started = False
        self._active = False
        self._external_operations: set[object] = set()
        self._bootstrap_watchdog: threading.Thread | None = None
        self._bootstrap_stop = threading.Event()
        self._legacy_parent: Any = None
        self._constructor_finished = False
        self._receipt: EpochCleanupReceipt | None = None
        self._outputs: tuple[BinaryIO, ...] = ()
        self._job: OwnedJob | None = None
        self._writer: threading.Thread | None = None
        self._pipe: ParentAuthority | None = None
        self._connection: Any = None
        self._worker_connection: Any = None
        self._pipe_attempted = False
        self._pipe_ready = False
        self._parent: MuxParentAuthority | None = None
        self._parent_epoch: MuxEpochIdentity | None = None
        self._parent_binding = False
        self._callback_generation: int | None = None
        self._original_scope = (scope, master_id, native_generation)
        self._launch_stop = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._watchdog_start_attempted = False

    def register(self, owner: ChildOwner) -> None:
        self.budget.bind_original(self.reservation, owner)

    def _bind(self, owner: ChildOwner) -> None:
        with self._lock:
            if (
                type(owner) is not ChildOwner
                or self.owner is not None
                or owner.child is not None
                or owner.job is not None
                or owner.writer is not None
                or owner.confirmed
                or not any(candidate is owner for candidate in pending_owner_snapshot())
            ):
                fail()
            self.owner = owner
            self._original_owner = owner
            self._outputs = tuple(owner.outputs)
            owner.mux_custodian = self

    def _resources_match(self) -> bool:
        owner = self.owner
        if (
            owner is None
            or owner is not self._original_owner
            or owner.mux_custodian is not self
            or owner.child is not self._child
            or owner.job is not self._job
            or owner.writer is not self._writer
            or self.pipe is not self._pipe
            or len(owner.outputs) != len(self._outputs)
            or any(
                a is not b for a, b in zip(owner.outputs, self._outputs, strict=True)
            )
            or self.scope is not self._original_scope[0]
            or (self.master_id, self.native_generation) != self._original_scope[1:]
            or self.parent is not self._parent
            or self._parent_binding
        ):
            return False
        if self._pipe_attempted and not self._pipe_ready:
            return False
        if self._pipe is None:
            if owner.service is not None:
                return False
        elif (
            self._pipe.generation != self.native_generation.hex
            or self._connection is None
            or self._worker_connection is None
            or not (
                self._pipe.connection is self._connection
                or self._pipe.connection is None
                and self._connection.closed
            )
            or not (
                self._pipe.worker_connection is self._worker_connection
                or self._pipe.worker_connection is None
                and self._worker_connection.closed
            )
            or not (
                owner.service is self._pipe
                or owner.service is None
                and self._connection.closed
                and self._worker_connection.closed
            )
        ):
            return False
        return self._parent is None or (
            self._parent._owner is owner
            and self._parent.connection is self._connection
            and self._parent.epoch is self._parent_epoch
            and self._parent_epoch is not None
            and self._parent_epoch.generation == self._callback_generation
        )

    def resources_current(self) -> bool:
        with self._lock:
            return self._resources_match()

    def configure_input(self, generation: int) -> None:
        with self._lock:
            if (
                not self._active
                or self._callback_generation is not None
                or type(generation) is not int
                or not 1 <= generation < 1 << 63
            ):
                fail()
            self._callback_generation = generation

    def retain_output(self, output: BinaryIO) -> None:
        with self._lock:
            valid = self._active and self._resources_match()
            # Preserve the returned original even if a previous resource changed.
            self._outputs = (*self._outputs, output)
            if not valid or self.owner is None:
                fail()
            self.owner.outputs = cast(tuple[BinaryIO, BinaryIO], self._outputs)

    def retain_job(self, job: OwnedJob) -> None:
        with self._lock:
            if type(job) is not OwnedJob or self._job is not None:
                fail()
            valid = self._active and self._resources_match()
            self._job = job
            if not valid or self.owner is None:
                fail()
            self.owner.job = job

    def retain_writer(self, writer: threading.Thread) -> None:
        with self._lock:
            if type(writer) is not threading.Thread or self._writer is not None:
                fail()
            valid = self._active and self._resources_match()
            self._writer = writer
            if not valid or self.owner is None:
                fail()
            self.owner.writer = writer

    def create_pipe(self, deadline: float, cancel: threading.Event) -> ParentAuthority:
        with self._lock:
            if (
                not self._active
                or self._pipe is not None
                or not self._resources_match()
            ):
                fail()
            assert self.owner is not None
            self._pipe = ParentAuthority(deadline, cancel)
            self.pipe = self.owner.service = self._pipe
            self._pipe.generation = self.native_generation.hex
            self._pipe_attempted = True
            # Retain the returned pair before any endpoint escapes to a wrapper.
            self._connection, self._worker_connection = multiprocessing.Pipe(
                duplex=True
            )
            self._pipe.connection = self._connection
            self._pipe.worker_connection = self._worker_connection
            self._pipe_ready = True
            return self._pipe

    def create_legacy_pipe(self, authority: Any) -> None:
        from .local_live_ipc import LiveParentAuthority

        with self._lock:
            if (
                type(authority) is not LiveParentAuthority
                or self.reservation.kind != "main"
                or authority.generation
                or authority.connection is not None
                or authority.worker_connection is not None
                or authority._watchdog is not None
                or not self._active
                or self._pipe is not None
                or self.owner is None
                or not self._resources_match()
            ):
                fail()
            self._legacy_parent = authority
            self._pipe = self.pipe = self.owner.service = authority
            authority.generation = self.native_generation.hex
            self._pipe_attempted = True
            self._connection, self._worker_connection = multiprocessing.Pipe(
                duplex=True
            )
            authority.connection, authority.worker_connection = (
                self._connection,
                self._worker_connection,
            )
            self._pipe_ready = True

    @contextmanager
    def external_operation(
        self, *, deadline: float | None = None, cancel: threading.Event | None = None
    ) -> Iterator[None]:
        token = object()
        with self._lock:
            if (
                self._receipt is not None
                or not self._resources_match()
                or self.owner is None
                or self.owner.confirmed
            ):
                fail()
            self._external_operations.add(token)
        watched = deadline is not None
        try:
            if watched:
                with self._lock:
                    if (
                        self._bootstrap_watchdog is not None
                        or type(cancel) is not threading.Event
                    ):
                        fail()
                    owner = self.owner

                    def watch() -> None:
                        assert (
                            deadline is not None
                            and cancel is not None
                            and owner is not None
                        )
                        while not self._bootstrap_stop.wait(0.01):
                            if cancel.is_set() or time.monotonic() >= deadline:
                                owner.request_stop()
                                return

                    self._bootstrap_watchdog = threading.Thread(
                        target=watch, name="mux-bootstrap-watchdog", daemon=False
                    )
                    self._bootstrap_watchdog.start()
            yield
        finally:
            if watched:
                self._bootstrap_stop.set()
                watcher = self._bootstrap_watchdog
                if watcher is not None and watcher.ident is not None:
                    watcher.join(0.2)
            with self._lock:
                self._external_operations.remove(token)

    def ipc_custody_current(self) -> bool:
        with self._lock:
            return bool(
                self._resources_match() and self._pipe is not None and self._pipe_ready
            )

    def constructor_settled(self) -> bool:
        with self._lock:
            return (
                self._constructor_finished
                and not self._active
                and not self._external_operations
                and (
                    self._bootstrap_watchdog is None
                    or self._bootstrap_watchdog.ident is not None
                    and not self._bootstrap_watchdog.is_alive()
                )
                and not (self._process_attempted and self._child is None)
                and self._resources_match()
                and (
                    self._watchdog is None
                    or (
                        self._watchdog.ident is not None
                        and not self._watchdog.is_alive()
                    )
                )
            )

    def owns_process(self, child: subprocess.Popen[bytes]) -> bool:
        with self._lock:
            return child is self._child and self._child is not None

    def _budget_current(self) -> bool:
        with self.budget._lock:
            return (
                self.budget._custodians.get(self.reservation.id) is self
                and self.budget._reservations.get(self.reservation.id)
                is self.reservation
                and self.reservation._authority is self.budget._issuer
            )

    def safe_prepared(self, owner: ChildOwner) -> bool:
        if not self._budget_current():
            return False
        with self._lock:
            return bool(
                self.owner is owner
                and self._original_owner is owner
                and not owner.confirmed
                and not owner.kill_attempted
                and self._resources_match()
                and not self._constructor_finished
                and not self._acquisition_started
                and not self._process_attempted
                and not self._pipe_attempted
                and self._child is None
                and self._job is None
                and self._writer is None
                and self._pipe is None
                and self._parent is None
                and self._legacy_parent is None
                and self._outputs == ()
                and self._callback_generation is None
                and self._receipt is None
                and not self._external_operations
            )

    def begin_acquisition(self) -> None:
        with self._lock:
            if (
                not self._active
                or self._acquisition_started
                or not self._resources_match()
            ):
                fail()
            self._acquisition_started = True

    def healthy(self) -> bool:
        if not self._budget_current():
            return False
        with self._lock:
            owner, child = self.owner, self._child
            if (
                not self.constructor_settled()
                or owner is None
                or owner.child is not child
                or child is None
                or child.poll() is not None
                or owner.kill_attempted
                or owner.confirmed
            ):
                return False
            legacy = self._legacy_parent
            if legacy is not None:
                from .local_live_ipc import LiveParentAuthority

                valid = (
                    type(legacy) is LiveParentAuthority
                    and self.reservation.kind == "main"
                    and legacy is self._pipe
                    and legacy is owner.service
                    and self.parent is None
                    and legacy.handed_off
                    and legacy.ready
                    and legacy.codec is not None
                    and legacy.identity is not None
                    and not legacy.failure
                    and not legacy.cancel.is_set()
                    and not legacy._stop.is_set()
                    and time.monotonic() < legacy.deadline
                )
            else:
                parent = self.parent
                valid = (
                    parent is not None
                    and parent is self._parent
                    and parent._owner is owner
                    and not parent.failed
                    and parent.codec is not None
                    and not parent.cancel.is_set()
                    and time.monotonic() < parent.deadline
                )
            return bool(
                valid
                and self.owner is owner
                and self._child is child
                and child.poll() is None
                and self._resources_match()
            )

    def can_coexist(self, owner: ChildOwner) -> bool:
        if owner is not self.owner or owner is not self._original_owner:
            return False
        return self.safe_prepared(owner) or self.healthy()

    @contextmanager
    def constructing(self) -> Iterator[None]:
        with self._lock:
            if self.owner is None or self._active or self._constructor_finished:
                fail()
            self._active = True
        try:
            yield
        finally:
            self._launch_stop.set()
            if self._watchdog is not None and self._watchdog.ident is not None:
                self._watchdog.join(0.2)
            with self._lock:
                self._active = False
                self._constructor_finished = True

    def watch_launch(self, deadline: float, cancel: threading.Event) -> None:
        with self._lock:
            if not self._active or self._watchdog is not None or self.owner is None:
                fail()
            owner = self.owner

            def watch() -> None:
                while not self._launch_stop.wait(0.01):
                    if cancel.is_set() or time.monotonic() >= deadline:
                        owner.request_stop()
                        return

            self._watchdog = threading.Thread(
                target=watch, name="mux-launch-watchdog", daemon=False
            )
            self._watchdog_start_attempted = True
            self._watchdog.start()

    def begin_process_creation(self) -> None:
        with self._lock:
            if not self._active or self._process_attempted:
                fail()
            self._process_attempted = True

    def retain_process(self, child: subprocess.Popen[bytes]) -> None:
        with self._lock:
            if (
                not self._active
                or not self._process_attempted
                or self._child is not None
                or self.owner is None
                or self.owner.child is not child
                or type(child) is not subprocess.Popen
            ):
                fail()
            self._child = child

    def attach_parent(
        self,
        parent: MuxParentAuthority,
        *,
        epoch: MuxEpochIdentity | None = None,
        peer_capability: int = 0,
        deadline_monotonic: float = 0,
        cancel: threading.Event | None = None,
    ) -> None:
        with self._lock:
            if (
                type(parent) is not MuxParentAuthority
                or self._parent is not None
                or self.parent is not None
                or self.owner is None
                or parent._owner is not None
                or parent.connection is not None
                or parent._watchdog is not None
                or parent.codec is not None
                or parent.failed
                or not self._resources_match()
                or self._connection is None
                or self._connection.closed
                or self._callback_generation is None
                or type(epoch) is not MuxEpochIdentity
                or parent.epoch is not epoch
                or epoch.generation != self._callback_generation
                or type(cancel) is not threading.Event
                or self._receipt is not None
            ):
                fail()
            self._parent = self.parent = parent
            self._parent_epoch = epoch
            self._parent_binding = True
            owner, connection = self.owner, self._connection
        try:
            # Retained before this call can start a watchdog or invoke a supplier.
            parent.bind_original(
                owner,
                connection=connection,
                peer_capability=peer_capability,
                deadline_monotonic=deadline_monotonic,
                cancel=cancel,
            )
        finally:
            with self._lock:
                self._parent_binding = False
        with self._lock:
            if not self._resources_match():
                fail()

    def close_parent(self, timeout: float) -> bool:
        with self._lock:
            if not self._resources_match():
                return False
            parent = self._parent
        closed = parent is None or parent.close(timeout)
        with self._lock:
            return closed and self._resources_match()

    def _settled(self) -> bool:
        with self._lock:
            owner = self.owner
            parent, pipe = self._parent, self._pipe
            if (
                owner is None
                or not self.constructor_settled()
                or not owner.confirmed
                or owner.child is not self._child
                or self._process_attempted
                and self._child is None
                or owner.job is not None
                and not owner.job.closed
                or owner.writer is not None
                and (
                    owner.writer.is_alive()
                    or owner.writer_start_attempted
                    and owner.writer.ident is None
                )
                or any(not output.closed for output in owner.outputs)
                or owner.service is not None
            ):
                return False
            if self._child is not None and (
                self._child.poll() is None
                or self._child.returncode is None
                or self._child.stdin is not None
                and not self._child.stdin.closed
                or not self.ipc_custody_current()
            ):
                return False
            if self._legacy_parent is not None:
                legacy = self._legacy_parent
                if legacy is not pipe or not self._legacy_parent.wait_retirement(0.2):
                    return False
                if legacy is not self._legacy_parent or not self._resources_match():
                    return False
            if parent is not None and not parent.confirmed_closed():
                return False
            # Confirmation can invoke original cleanup callbacks. Reject any
            # substituted wrapper/endpoint before another cleanup can erase that
            # evidence (for example by replacing a foreign endpoint with None).
            if (
                parent is not self._parent
                or pipe is not self._pipe
                or not self._resources_match()
            ):
                return False
            return (pipe is None or pipe.close(0.2) is True) and self._resources_match()

    def receipt(self) -> EpochCleanupReceipt | None:
        with self._lock:
            if not self._settled():
                return None
            if self._receipt is None:
                self._receipt = EpochCleanupReceipt(
                    master_id=self.master_id,
                    worker_epoch=self.scope.worker_epoch,
                    native_generation=self.native_generation,
                    original_state="REAPED"
                    if self._child is not None
                    else "NOT_CREATED",
                    callback_settled=True,
                    ipc_settled=True,
                    job_settled=True,
                    _authority=self._issuer,
                    _seal=_CUSTODY_SEAL,
                )
            return self._receipt
