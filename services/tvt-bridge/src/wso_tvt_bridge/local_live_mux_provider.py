"""Retained shared-recorder originals and their publication custodians.

Native bootstrap and IPC composition are private. No caller-provided booleans
or SQL generation can establish a wire identity or an original cleanup receipt.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event, RLock
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol, cast
from uuid import UUID, uuid4

from wso_core.tvt.local_credentials import LocalDeviceCredentials
from wso_core.tvt.local_live import PrivateLiveFrame
from wso_core.tvt.local_media_admission import LocalMediaLease
from wso_core.tvt.local_media_mux_types import (
    _CUSTODY_SEAL,
    _NATIVE_BINDING_SEAL,
    EpochCleanupReceipt,
    IngressCut,
    MasterLoginProof,
    MasterReservation,
    MuxEpochIdentity,
    MuxOriginalReservation,
    MuxPurpose,
    MuxScopeKey,
    MuxSlotIdentity,
    MuxValidatedFrame,
    OriginalMuxBinding,
    SlotRetentionGrant,
    TransportGrant,
    ViewerCleanupReceipt,
    ViewerGrant,
)
from wso_core.tvt.local_media_service import LocalLiveProof, LocalMediaChannel
from wso_core.tvt.local_service import (
    LocalDeviceFailure,
    LocalInventoryChannel,
    LocalVerifyBudget,
)

from .local_inventory_ipc import decode
from .local_live_diagnostics import (
    NativeFirstKeyRecord,
    NativeMuxIngressFailureRecord,
    NativeMuxTerminalRecord,
    project_mux_ingress_failure,
)
from .local_live_mux_ipc import (
    RAW_STAGING_BYTES,
    MediaCreditToken,
    MuxParentAuthority,
    make_mux_worker_input,
    release_media_credit,
    reserve_media_credit,
)
from .local_live_mux_ownership import MuxOriginalBudget, MuxOriginalCustodian
from .local_live_provider import OwnedLocalLiveSession
from .windows_socket import (
    ChildOwner,
    ProviderError,
    WindowsSocketProvider,
    fail,
    register_pending_owner,
    remove_confirmed_owner,
)

if TYPE_CHECKING:
    from wso_core.tvt.local_media_mux_admission import SqlMuxAdmission


class NativeLocalMuxProvider:
    def __init__(
        self,
        native: WindowsSocketProvider,
        *,
        budget: MuxOriginalBudget,
        admission: SqlMuxAdmission,
        clock: Callable[[], float] = time.monotonic,
        first_key_debug: Callable[
            [
                NativeFirstKeyRecord
                | NativeMuxTerminalRecord
                | NativeMuxIngressFailureRecord
            ],
            None,
        ]
        | None = None,
    ) -> None:
        if (
            type(native) is not WindowsSocketProvider
            or type(budget) is not MuxOriginalBudget
        ):
            fail()
        self.native, self.budget, self.admission, self.clock = (
            native,
            budget,
            admission,
            clock,
        )
        self.first_key_debug = first_key_debug

    def prepare_master(
        self,
        reservation: MasterReservation,
        original: MuxOriginalReservation,
    ) -> OriginalRecorderMaster:
        if type(reservation) is not MasterReservation or original.kind != "base":
            fail()
        custodian = self.budget.prepare(
            original,
            scope=reservation.scope,
            master_id=reservation.master_id,
            native_generation=reservation.transport.native_generation,
        )
        return OriginalRecorderMaster(self, reservation, custodian)

    def prepare_dedicated(
        self,
        lease: LocalMediaLease,
        scope: MuxScopeKey,
        original_budget: MuxOriginalReservation,
        registration: UUID,
    ) -> PreparedDedicatedMain:
        if (
            lease.id is None
            or original_budget.kind != "main"
            or lease.worker_epoch != scope.worker_epoch
        ):
            fail()
        custodian = self.budget.prepare(
            original_budget,
            scope=scope,
            master_id=lease.id,
            native_generation=lease.native_generation,
        )
        return PreparedDedicatedMain(self, lease, registration, custodian)


@dataclass(frozen=True, slots=True)
class _TransportSnapshot:
    grant: TransportGrant
    owner: ChildOwner
    child: Any
    custodian: MuxOriginalCustodian
    ready: bool
    parent: MuxParentAuthority | None


@dataclass(frozen=True, slots=True)
class _IngressConsumer:
    thread: threading.Thread
    stop: Event
    finished: Event
    start_finished: Event
    parent: MuxParentAuthority
    owner: ChildOwner
    custodian: MuxOriginalCustodian
    io_lock: Any
    epoch: MuxEpochIdentity | None


class OriginalRecorderMaster:
    def __init__(
        self,
        provider: NativeLocalMuxProvider,
        reservation: MasterReservation,
        custodian: MuxOriginalCustodian,
    ) -> None:
        self.provider, self.reservation, self.custodian = (
            provider,
            reservation,
            custodian,
        )
        self._lock = RLock()
        self.io_lock = RLock()
        self._closed = False
        self._operations: set[object] = set()
        self._closing = False
        self._started = False
        self._bindings: dict[bytes, OriginalMuxBinding] = {}
        # The exact empty original is retained before any pipe, file, Job or child.
        owner = ChildOwner(None, None, cast(tuple[BinaryIO, BinaryIO], ()))
        self.owner = owner
        register_pending_owner(owner)
        custodian.register(owner)
        self.native = WindowsSocketProvider(
            mux_config=provider.native._mux_config, mux_custodian=custodian
        )
        self.native.owner = owner
        self._transport = reservation.transport
        self._parent: MuxParentAuthority | None = None
        self._epoch: MuxEpochIdentity | None = None
        self._ready = False
        self._binding_parent = False
        self._channels: dict[bytes, LocalMediaChannel] = {}
        self._slots: dict[bytes, SlotRetentionGrant] = {}
        self._viewers: dict[UUID, MuxSlotViewer] = {}
        self._sequence = 5
        self._next_heartbeat = provider.clock() + 6.0
        self._bootstrap_credit: MediaCreditToken | None = None
        self._issuer = object()
        self._ingress_stop = Event()
        self._ingress_finished = Event()
        self._ingress_start_finished = Event()
        self._ingress_thread: threading.Thread | None = None
        self._ingress_original: _IngressConsumer | None = None
        self._ingress_start_attempted = False
        self._ingress_start_returned = False
        self._ingress_joined = False
        self._terminal_diagnostic_attempted = False
        self.proof = LocalLiveProof(False, False, False, False, False)

    def _start_ingress_consumer(self) -> None:
        with self._lock:
            if self._closed or not self._ready or self._ingress_thread is not None:
                fail()
            parent, owner, custodian, io_lock, epoch = (
                self.parent,
                self.owner,
                self.custodian,
                self.io_lock,
                self._epoch,
            )
            thread = threading.Thread(
                target=lambda: self._consume_parked_ingress(original),
                name="mux-retained-ingress",
                daemon=False,
            )
            # Keep the exact original and attempted state before Thread.start.
            self._ingress_thread = thread
            original = _IngressConsumer(
                thread,
                self._ingress_stop,
                self._ingress_finished,
                self._ingress_start_finished,
                parent,
                owner,
                custodian,
                io_lock,
                epoch,
            )
            self._ingress_original = original
            self._ingress_start_attempted = True
        try:
            thread.start()
            with self._lock:
                self._ingress_start_returned = True
        finally:
            original.start_finished.set()

    def _ingress_matches(self, original: _IngressConsumer) -> bool:
        return (
            self._ingress_original is original
            and self._ingress_thread is original.thread
            and self._ingress_stop is original.stop
            and self._ingress_finished is original.finished
            and self._ingress_start_finished is original.start_finished
            and self._ingress_start_attempted
            and self._parent is original.parent
            and self.owner is original.owner
            and self.custodian is original.custodian
            and self.io_lock is original.io_lock
            and self._epoch is original.epoch
        )

    def _consume_parked_ingress(
        self,
        original: _IngressConsumer,
    ) -> None:
        parent, owner, io_lock = original.parent, original.owner, original.io_lock
        try:
            while not original.stop.is_set():
                # Busy foreground IO is scheduling contention, never denial.
                if not io_lock.acquire(blocking=False):
                    original.stop.wait(0.01)
                    continue
                try:
                    if original.stop.is_set():
                        break
                    with self._invocation(), self.authority_operation():
                        with self._lock:
                            if not self._ready or not self._ingress_matches(original):
                                fail()
                        # Active readers retain their existing consumption path.
                        # Cuts, park and refresh all share this original IO lock.
                        if parent._opened and not parent._cuts:
                            until = min(
                                self.provider.clock() + 0.25,
                                self._transport.expires_monotonic,
                                parent.deadline,
                            )
                            slice_end = self.provider.clock() + 0.05
                            with _serialized_io(self, until):
                                for _ in range(16):
                                    if (
                                        original.stop.is_set()
                                        or self.provider.clock() >= slice_end
                                    ):
                                        break
                                    if not parent.pump(owner, deadline_monotonic=until):
                                        break
                finally:
                    io_lock.release()
                original.stop.wait(0.01)
        except BaseException as error:  # noqa: BLE001 -- retain failure, no exception text
            if not original.stop.is_set():
                callback = self.provider.first_key_debug
                if callback is not None:
                    try:
                        callback(project_mux_ingress_failure(error))
                    except BaseException:  # noqa: BLE001,S110 -- optional diagnostics only
                        pass
                with self._lock:
                    self._closed = True
                parent._fence()
                owner.request_stop()
        finally:
            original.finished.set()

    def _settle_ingress_consumer(self) -> bool:
        with self._lock:
            original = self._ingress_original
            if original is None:
                return (
                    self._ingress_thread is None and not self._ingress_start_attempted
                )
            thread = original.thread
            if (
                not self._ingress_matches(original)
                or not original.start_finished.is_set()
                or not original.finished.is_set()
                or thread is threading.current_thread()
            ):
                return False
        try:
            thread.join(0.2)
            if thread.is_alive():
                return False
        except BaseException:  # noqa: BLE001 -- uncertain join retains custody
            return False
        with self._lock:
            if not self._ingress_matches(original):
                return False
            self._ingress_joined = True
            return True

    @contextmanager
    def _invocation(self) -> Iterator[None]:
        token = object()
        with self._lock:
            if self._closed:
                fail()
            self._operations.add(token)
        try:
            yield
        finally:
            with self._lock:
                self._operations.remove(token)

    def _snapshot(self) -> _TransportSnapshot:
        with self._lock:
            return _TransportSnapshot(
                self._transport,
                self.owner,
                self.owner.child,
                self.custodian,
                self._ready,
                self._parent,
            )

    def _snapshot_matches(self, snapshot: _TransportSnapshot) -> bool:
        def retained(now: float) -> bool:
            return (
                not self._closed
                and self._transport is snapshot.grant
                and self.owner is snapshot.owner
                and self.owner.child is snapshot.child
                and self.custodian is snapshot.custodian
                and self._ready == snapshot.ready
                and self._parent is snapshot.parent
                and not snapshot.owner.confirmed
                and not snapshot.owner.kill_attempted
                and now < snapshot.grant.expires_monotonic
            )

        now = self.provider.clock()
        with self._lock:
            if not retained(now):
                return False
        if snapshot.ready and (
            snapshot.child is None
            or snapshot.child.poll() is not None
            or not snapshot.custodian.resources_current()
            or snapshot.child.poll() is not None
        ):
            return False
        now = self.provider.clock()
        with self._lock:
            return retained(now)

    @contextmanager
    def authority_operation(
        self, *, budget: LocalVerifyBudget | None = None
    ) -> Iterator[None]:
        """Serialize exact grant snapshots and suppliers with grant replacement.

        This is the original IO operation mutex, never the short state lock.
        Taking it before refresh drains already-entered checks and native IO;
        their nested checks are reentrant. No SQL callback runs under _lock.
        """
        now = self.provider.clock()
        parent = self._parent
        until = min(now + 5, self._transport.expires_monotonic)
        if parent is not None and parent.deadline:
            until = min(until, parent.deadline)
            if parent._supplier_deadline is not None:
                until = min(until, parent._supplier_deadline)
            if parent._operation_deadline is not None:
                until = min(until, parent._operation_deadline)

        def check() -> None:
            if budget is not None:
                budget.remaining_ms()
            if (
                self._closed
                or self._parent is not parent
                or self.provider.clock() >= until
                or self.owner.confirmed
                or self.owner.kill_attempted
                or parent is not None
                and (
                    parent.failed
                    or parent.cancel.is_set()
                    or parent._supplier_cancel is not None
                    and parent._supplier_cancel.is_set()
                    or parent._operation_cancel is not None
                    and parent._operation_cancel.is_set()
                )
            ):
                fail()

        while True:
            check()
            if self.io_lock.acquire(timeout=0.01):
                break
        try:
            check()
            yield
            check()
        finally:
            self.io_lock.release()

    @contextmanager
    def refresh_grants(self, *, budget: LocalVerifyBudget) -> Iterator[None]:
        """Original-scoped barrier held before admission invalidates any grant."""
        with self._invocation(), self.authority_operation(budget=budget):
            try:
                yield
                budget.remaining_ms()
            except BaseException:
                # Partial replacement cannot escape while still looking healthy.
                with self._lock:
                    self._closed = True
                    parent = self._parent
                if parent is not None:
                    parent._fence()
                self.owner.request_stop()
                raise

    def binding_for(self, channel: bytes) -> OriginalMuxBinding | None:
        try:
            with self._invocation(), self.authority_operation():
                return self._binding_for(channel)
        except (ProviderError, LocalDeviceFailure):
            return None

    def _binding_for(self, channel: bytes) -> OriginalMuxBinding | None:
        with self._lock:
            if self._closed or not self._ready:
                return None
            binding = self._bindings.get(channel)
        snapshot = self._snapshot()
        if not self._transport_current() or not self._snapshot_matches(snapshot):
            return None
        with self._lock:
            return (
                binding
                if not self._closed and self._bindings.get(channel) is binding
                else None
            )

    @property
    def parent(self) -> MuxParentAuthority:
        if self._parent is None:
            fail()
        return self._parent

    def _transport_current(self) -> bool:
        try:
            with self._invocation(), self.authority_operation():
                return self._transport_current_once()
        except (ProviderError, LocalDeviceFailure):
            return False

    def _transport_current_once(self) -> bool:
        token = object()
        with self._lock:
            if self._closed:
                return False
            self._operations.add(token)
        try:
            snapshot = self._snapshot()
            if not self._snapshot_matches(snapshot):
                return False
            allowed = self.provider.admission.current_transport(snapshot.grant)
            return allowed is True and self._snapshot_matches(snapshot)
        finally:
            with self._lock:
                self._operations.remove(token)

    def _authorize(
        self,
        purpose: MuxPurpose,
        slot: MuxSlotIdentity | None,
        registration: UUID | None,
    ) -> bool:
        try:
            with self._invocation(), self.authority_operation():
                return self._authorize_once(purpose, slot, registration)
        except (ProviderError, LocalDeviceFailure):
            return False

    def _authorize_once(
        self,
        purpose: MuxPurpose,
        slot: MuxSlotIdentity | None,
        registration: UUID | None,
    ) -> bool:
        if not self._transport_current():
            return False
        if purpose is MuxPurpose.TRANSPORT:
            return slot is None and registration is None
        if slot is None or slot.epoch != self._epoch:
            return False
        grant = self._slots.get(slot.channel)
        if (
            grant is None
            or grant.slot != slot
            or self.provider.clock() >= grant.expires_monotonic
            or not self.provider.admission.current_slot(grant)
            or self._slots.get(slot.channel) is not grant
            or not self._transport_current()
        ):
            return False
        if purpose in (MuxPurpose.SLOT_CONTROL, MuxPurpose.SLOT_RETENTION):
            return registration is None
        viewer = self._viewers.get(registration) if registration is not None else None
        return viewer is not None and self.viewer_current(viewer.current_grant())

    def viewer_current(self, grant: ViewerGrant) -> bool:
        try:
            with self._invocation(), self.authority_operation():
                return self._viewer_current_once(grant)
        except (ProviderError, LocalDeviceFailure):
            return False

    def _viewer_current_once(self, grant: ViewerGrant) -> bool:
        token = object()
        with self._lock:
            if self._closed:
                return False
            self._operations.add(token)
            viewer = self._viewers.get(grant.registration)
        try:
            if (
                viewer is None
                or viewer.current_grant() is not grant
                or viewer._stopping
                or self.provider.clock() >= grant.expires_monotonic
                or not self._authorize(MuxPurpose.SLOT_RETENTION, grant.slot, None)
            ):
                return False
            snapshot = self._snapshot()
            allowed = self.provider.admission.current_viewer(grant)
            if allowed is not True or not self._snapshot_matches(snapshot):
                return False
            now = self.provider.clock()
            with self._lock:
                slot = self._slots.get(grant.slot.channel)
                return (
                    self._viewers.get(grant.registration) is viewer
                    and viewer.current_grant() is grant
                    and not viewer._stopping
                    and now < grant.expires_monotonic
                    and slot is not None
                    and slot.slot == grant.slot
                    and now < slot.expires_monotonic
                    and not self._closed
                )
        finally:
            with self._lock:
                self._operations.remove(token)

    def start(
        self,
        credentials: LocalDeviceCredentials,
        grant: TransportGrant,
        *,
        budget: LocalVerifyBudget,
    ) -> MasterLoginProof:
        try:
            with self._invocation():
                with self._lock:
                    if (
                        self._started
                        or self._closed
                        or grant is not self.reservation.transport
                    ):
                        fail()
                    self._started = True
                return self._start_native(credentials, grant, budget=budget)
        except BaseException as error:
            pipe = self.custodian.pipe
            failure = None if pipe is None else pipe.failure
            self.close()
            if isinstance(error, ProviderError) and failure in ("protocol", "closed"):
                busy = self.native.recover_retired_login_busy()
                if busy is not None:
                    budget.remaining_ms()
                    allowed = self.provider.admission.current_transport(grant)
                    budget.remaining_ms()
                    if allowed:
                        raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429) from None
            raise

    def _start_native(
        self,
        credentials: LocalDeviceCredentials,
        grant: TransportGrant,
        *,
        budget: LocalVerifyBudget,
    ) -> MasterLoginProof:
        generation = secrets.randbelow((1 << 63) - 1) + 1
        budget.remaining_ms()
        self._bootstrap_credit = reserve_media_credit(
            slot=None,
            registration=self.reservation.master_id,
            frames=0,
            bytes=RAW_STAGING_BYTES,
            stage="raw",
        )
        if self._bootstrap_credit is None:
            raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)
        self.native.open_mux(
            make_mux_worker_input(
                credentials,
                generation=generation,
                initial_expiry_ms=budget.remaining_ms(),
            ),
            deadline_monotonic=budget.deadline_monotonic,
            current=self._transport_current,
            cancel=budget.cancel,
        )
        del credentials
        with self.custodian.external_operation(
            deadline=budget.deadline_monotonic, cancel=budget.cancel
        ):
            pipe = self.custodian.pipe
            if pipe is None or pipe is not self.owner.service:
                fail()
            while pipe.observation is None:
                budget.remaining_ms()
                if (
                    not pipe.tick(self._transport_current)
                    or self.owner.child is None
                    or self.owner.child.poll() is not None
                ):
                    fail()
                time.sleep(0.005)
            data = decode(pipe.observation)
            if set(data) != {
                "session",
                "callback_generation",
                "peer_capability",
                "login_accepted",
                "same_original_session",
                "serial_matched",
                "inventory_session_matched",
                "channels",
            }:
                fail()
            if (
                data["callback_generation"] != generation
                or any(
                    data[field] is not True
                    for field in (
                        "login_accepted",
                        "same_original_session",
                        "serial_matched",
                        "inventory_session_matched",
                    )
                )
                or type(data["session"]) is not str
                or len(data["session"]) != 32
                or type(data["channels"]) is not list
                or len(data["channels"]) > 256
            ):
                fail()
            epoch = MuxEpochIdentity(generation, bytes.fromhex(data["session"]))
            proof = MasterLoginProof(
                data["login_accepted"],
                data["same_original_session"],
                data["serial_matched"],
                data["serial_matched"],
                data["inventory_session_matched"],
                data["peer_capability"],
            )
            for row in data["channels"]:
                if (
                    type(row) is not dict
                    or set(row)
                    != {
                        "guid",
                        "raw_index",
                        "window_index",
                        "ordinal",
                        "kind",
                        "basis",
                    }
                    or row["basis"] not in ("legacy_no_group", "explicit_lp")
                ):
                    fail()
                channel = LocalInventoryChannel(
                    bytes.fromhex(row["guid"]),
                    row["raw_index"],
                    row["window_index"],
                    row["ordinal"],
                    row["kind"],
                )
                if (
                    channel.guid in self._channels
                    or not -128 <= channel.raw_index <= 255
                    or any(
                        existing.raw_index == channel.raw_index
                        or existing.ordinal == channel.ordinal
                        for existing in self._channels.values()
                    )
                ):
                    fail()
                self._channels[channel.guid] = LocalMediaChannel(
                    channel.guid,
                    channel.raw_index,
                    channel.window_index,
                    channel.ordinal,
                    channel.kind,
                    "sub",
                )
                self._bindings[channel.guid] = OriginalMuxBinding(
                    scope=self.reservation.scope,
                    master_id=self.reservation.master_id,
                    native_generation=grant.native_generation,
                    epoch=epoch,
                    channel=channel.guid,
                    proof=proof,
                    _authority=self._issuer,
                    _seal=_NATIVE_BINDING_SEAL,
                )
            self._epoch = epoch
            parent = MuxParentAuthority(
                epoch=epoch, authorize=self._authorize, clock=self.provider.clock
            )
            self._parent = parent
            self.custodian.attach_parent(
                parent,
                epoch=epoch,
                peer_capability=proof.peer_capability,
                deadline_monotonic=budget.deadline_monotonic,
                cancel=Event(),
            )
            with parent.caller_operation(
                deadline_monotonic=budget.deadline_monotonic, cancel=budget.cancel
            ):
                parent.renew(
                    deadline_monotonic=min(
                        grant.expires_monotonic, self.provider.clock() + 30
                    )
                )
            budget.remaining_ms()
            if not self._transport_current() or not self.custodian.resources_current():
                fail()
            if self._bootstrap_credit is not None:
                release_media_credit(self._bootstrap_credit)
                self._bootstrap_credit = None
            with self._lock:
                if self._closed or self._transport is not grant:
                    fail()
                self._ready = True
                self.proof = LocalLiveProof(True, True, True, True, True)
            self._start_ingress_consumer()
            return proof

    def _slot_operation_current(
        self,
        parent: MuxParentAuthority,
        owner: ChildOwner,
        grant: SlotRetentionGrant,
        budget: LocalVerifyBudget,
    ) -> None:
        budget.remaining_ms()
        with self._lock:
            if (
                self._closed
                or not self._ready
                or self._parent is not parent
                or self.owner is not owner
                or self._slots.get(grant.slot.channel) is not grant
            ):
                fail()

    def open_slot(
        self,
        selection: LocalMediaChannel,
        grant: SlotRetentionGrant,
        *,
        budget: LocalVerifyBudget,
    ) -> MuxSlotIdentity:
        with self._invocation():
            budget.remaining_ms()
            with self._lock:
                if (
                    not self._ready
                    or self._closed
                    or type(grant) is not SlotRetentionGrant
                    or grant.scope != self.reservation.scope
                    or grant.slot.epoch != self._epoch
                    or self._channels.get(selection.guid) != selection
                    or selection.stream != "sub"
                    or grant.slot.channel != selection.guid
                    or selection.guid in self._slots
                ):
                    fail()
                self._slots[selection.guid] = grant
                self._sequence += 1
                sequence, parent, owner = self._sequence, self.parent, self.owner
            with _serialized_io(self, budget.deadline_monotonic):
                self._slot_operation_current(parent, owner, grant, budget)
                self.provider.budget.register_slot(
                    self.custodian.reservation, grant.slot
                )
                with parent.caller_operation(
                    deadline_monotonic=budget.deadline_monotonic, cancel=budget.cancel
                ):
                    parent.register_slot(
                        grant.slot, channel_number=selection.raw_index & 255
                    )
                    self._slot_operation_current(parent, owner, grant, budget)
                    parent.prepare_open(
                        grant.slot, request_guid=uuid4().bytes_le, sequence=sequence
                    )
                    self._slot_operation_current(parent, owner, grant, budget)
                    parent.send_open(
                        grant.slot,
                        deadline_monotonic=budget.deadline_monotonic,
                        cancel=budget.cancel,
                    )
                    self._slot_operation_current(parent, owner, grant, budget)
                    while not parent.open_acknowledged(grant.slot):
                        self._slot_operation_current(parent, owner, grant, budget)
                        parent.pump(owner, deadline_monotonic=budget.deadline_monotonic)
                    self._slot_operation_current(parent, owner, grant, budget)
                    return grant.slot

    def heartbeat(self, deadline: float) -> None:
        if self.provider.clock() >= self._next_heartbeat:
            self.parent.heartbeat(deadline_monotonic=deadline)
            self._next_heartbeat = self.provider.clock() + 6.0

    def prepare_viewer(self, grant: ViewerGrant) -> MuxSlotViewer:
        with self._lock:
            retained = self._slots.get(grant.slot.channel)
            if (
                type(grant) is not ViewerGrant
                or self._closed
                or not self._ready
                or grant.scope != self.reservation.scope
                or retained is None
                or retained.slot != grant.slot
                or grant.registration in self._viewers
                or any(
                    not viewer._stopping and viewer.current_grant().slot == grant.slot
                    for viewer in self._viewers.values()
                )
            ):
                fail()
            viewer = MuxSlotViewer(self, grant)
            self._viewers[grant.registration] = viewer
            return viewer

    def attach_viewer(
        self, grant: ViewerGrant, *, budget: LocalVerifyBudget
    ) -> MuxSlotViewer:
        viewer = self.prepare_viewer(grant)
        viewer.start(budget=budget)
        return viewer

    def replace_grant(
        self,
        old: TransportGrant | SlotRetentionGrant | ViewerGrant,
        new: TransportGrant | SlotRetentionGrant | ViewerGrant,
    ) -> None:
        with self._invocation():
            parent: MuxParentAuthority | None = None
            with self._lock:
                if (
                    type(old) is not type(new)
                    or old.scope != new.scope
                    or old._authority is not new._authority
                    or new.scope != self.reservation.scope
                    or self._closed
                ):
                    fail()
                if type(old) is TransportGrant and type(new) is TransportGrant:
                    if (
                        self._transport is not old
                        or old.native_generation != new.native_generation
                    ):
                        fail()
                    self._transport, parent = new, self.parent
                elif type(old) is ViewerGrant and type(new) is ViewerGrant:
                    viewer = self._viewers.get(old.registration)
                    if (
                        viewer is None
                        or viewer.current_grant() is not old
                        or old.registration != new.registration
                        or old.lease_id != new.lease_id
                        or old.slot != new.slot
                    ):
                        fail()
                    with viewer._lock:
                        if viewer._stopping or viewer._grant is not old:
                            fail()
                        viewer._grant = new
                elif (
                    type(old) is SlotRetentionGrant and type(new) is SlotRetentionGrant
                ):
                    if (
                        self._slots.get(old.slot.channel) is not old
                        or old.slot != new.slot
                    ):
                        fail()
                    self._slots[old.slot.channel] = new
                else:
                    fail()
            if parent is not None:
                with _serialized_io(self, new.expires_monotonic):
                    with self._lock:
                        if (
                            self._closed
                            or self._transport is not new
                            or self._parent is not parent
                        ):
                            fail()
                    parent.renew(
                        deadline_monotonic=min(
                            new.expires_monotonic, self.provider.clock() + 30
                        )
                    )
                    with self._lock:
                        if (
                            self._closed
                            or self._transport is not new
                            or self._parent is not parent
                        ):
                            fail()
                    self.heartbeat(new.expires_monotonic)

    def issued_receipt(self) -> EpochCleanupReceipt | None:
        if not self._settle_ingress_consumer():
            return None
        with self._lock:
            if self._operations:
                return None
            custodian = self.custodian
        receipt = custodian.receipt()
        with self._lock:
            return (
                receipt
                if not self._operations and self.custodian is custodian
                else None
            )

    def _publish_original_terminal(self, owner: ChildOwner) -> None:
        callback = self.provider.first_key_debug
        if callback is None:
            return
        with self._lock:
            if (
                self._terminal_diagnostic_attempted
                or self.owner is not owner
                or not owner.confirmed
                or self.native.owner is not owner
                or self.custodian.owner is not owner
            ):
                return
            self._terminal_diagnostic_attempted = True
        # Exact retired result I/O and the finite sink run outside custody locks.
        try:
            record = self.native.original_mux_terminal()
            if record is not None:
                callback(record)
        except BaseException:  # noqa: BLE001,S110 -- optional diagnostics only
            pass

    def close(self) -> EpochCleanupReceipt | None:
        with self._lock:
            self._closed = True
            if self._ingress_original is not None:
                self._ingress_original.stop.set()
            else:
                self._ingress_stop.set()
            owner, custodian = self.owner, self.custodian
            pending = bool(self._operations) or self._closing
            if not pending:
                self._closing = True
        if custodian.owner is not owner:
            return None
        owner.request_stop()
        if pending:
            return None
        try:
            if not self._settle_ingress_consumer():
                return None
            if not custodian._constructor_finished and not custodian._active:
                with custodian.constructing():
                    pass
            if not owner.finish(0.2):
                return None
            receipt = custodian.receipt()
            with self._lock:
                if (
                    self._operations
                    or self.owner is not owner
                    or self.custodian is not custodian
                ):
                    return None
                credit = self._bootstrap_credit if receipt is not None else None
                if receipt is not None:
                    self._bootstrap_credit = None
            if credit is not None:
                release_media_credit(credit)
            if receipt is not None:
                remove_confirmed_owner(owner)
                self._publish_original_terminal(owner)
            return receipt
        finally:
            with self._lock:
                self._closing = False


# Viewer adapters deliberately retain only references to already-charged IPC frames.
# They own neither a second FIFO nor a second host-memory accounting authority.


class _ViewerMaster(Protocol):
    io_lock: Any

    @property
    def parent(self) -> MuxParentAuthority: ...

    owner: ChildOwner
    proof: LocalLiveProof

    def viewer_current(self, grant: ViewerGrant) -> bool: ...
    def heartbeat(self, deadline: float) -> None: ...


@contextmanager
def _serialized_io(master: _ViewerMaster, deadline: float) -> Iterator[None]:
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not master.io_lock.acquire(timeout=remaining):
        raise LocalDeviceFailure("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504)
    try:
        if time.monotonic() >= deadline:
            raise LocalDeviceFailure("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504)
        yield
    finally:
        master.io_lock.release()


class MuxSlotViewer:
    def __init__(self, master: _ViewerMaster, grant: ViewerGrant) -> None:
        self.master, self._grant = master, grant
        self._original_master, self._original_parent = master, master.parent
        self._original_owner, self._original_io_lock = master.owner, master.io_lock
        self._lock = RLock()
        self._cut: IngressCut | None = None
        self._started = False
        self._start_attempted = False
        self._stopping = False
        self._parked = False
        self._operations: set[object] = set()
        self._releasing: set[int] = set()
        self._batches: dict[int, tuple[MuxValidatedFrame, ...]] = {}
        self._retirement: Callable[[], ViewerCleanupReceipt | None] | None = None
        self._receipt: ViewerCleanupReceipt | None = None
        self._proof = master.proof

    @property
    def registration(self) -> UUID:
        return self._grant.registration

    @property
    def cut(self) -> IngressCut:
        if self._cut is None:
            fail()
        return self._cut

    @property
    def proof(self) -> LocalLiveProof:
        return self._proof

    def current_grant(self) -> ViewerGrant:
        return self._grant

    def _claim(self, *, cleanup: bool = False) -> object | None:
        token = object()
        with self._lock:
            if (self._stopping and not cleanup) or self._receipt is not None:
                return None
            self._operations.add(token)
        return token

    def _leave(self, token: object) -> None:
        with self._lock:
            self._operations.remove(token)

    def _matches(self, grant: ViewerGrant, child: Any) -> bool:
        master, parent, owner = (
            self._original_master,
            self._original_parent,
            self._original_owner,
        )
        if (
            self.master is not master
            or master.parent is not parent
            or master.owner is not owner
            or master.io_lock is not self._original_io_lock
            or parent.failed
            or owner.confirmed
        ):
            return False
        if getattr(owner, "child", None) is not child:
            return False
        if child is not None and child.poll() is not None:
            return False
        now = time.monotonic()
        with self._lock:
            return (
                now < grant.expires_monotonic
                and self._grant is grant
                and not self._stopping
                and self._receipt is None
                and self.master is master
                and getattr(owner, "child", None) is child
                and not parent.failed
                and not owner.confirmed
            )

    def current(self) -> bool:
        token = self._claim()
        if token is None:
            return False
        try:
            with _serialized_io(self._original_master, time.monotonic() + 5):
                return self._current_once()
        except (ProviderError, LocalDeviceFailure):
            return False
        finally:
            self._leave(token)

    def _current_once(self) -> bool:
        token = self._claim()
        if token is None:
            return False
        try:
            with self._lock:
                grant = self._grant
            child = getattr(self._original_owner, "child", None)
            if not self._matches(grant, child):
                return False
            allowed = self._original_master.viewer_current(grant)
            return allowed is True and self._matches(grant, child)
        finally:
            self._leave(token)

    def start(self, *, budget: LocalVerifyBudget) -> None:
        token = self._claim()
        if token is None:
            fail()
        try:
            with self._lock:
                if self._start_attempted or self._cut is not None:
                    fail()
                self._start_attempted = True
                grant = self._grant
            child = getattr(self._original_owner, "child", None)
            with _serialized_io(self._original_master, budget.deadline_monotonic):
                budget.remaining_ms()
                if not self.current() or not self._matches(grant, child):
                    fail()
                cut = self._original_parent.admission_cut(
                    grant.slot,
                    registration=grant.registration,
                    deadline_monotonic=budget.deadline_monotonic,
                    cancel=budget.cancel,
                )
                with self._lock:
                    self._cut = (
                        cut  # Retain a returned cut even if Stop won its callback.
                    )
                budget.remaining_ms()
                if not self.current() or not self._matches(grant, child):
                    fail()
                budget.remaining_ms()
                with self._lock:
                    if self._stopping or self._grant is not grant:
                        fail()
                    self._started = True
        finally:
            self._leave(token)

    def read_frames(
        self, *, max_frames: int, max_bytes: int, deadline_monotonic: float
    ) -> tuple[MuxValidatedFrame, ...]:
        token = self._claim()
        if token is None:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        frames: tuple[MuxValidatedFrame, ...] = ()
        handed_off = False
        parent = self._original_parent
        try:
            with _serialized_io(self._original_master, deadline_monotonic):
                # Read the current immutable object only after refresh's IO
                # barrier. An old snapshot acquired while waiting cannot publish.
                with self._lock:
                    if not self._started or self._cut is None:
                        fail()
                    grant, cut = self._grant, self._cut
                child = getattr(self._original_owner, "child", None)
                if not self.current() or not self._matches(grant, child):
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                self._original_master.heartbeat(deadline_monotonic)
                parent.pump(self._original_owner, deadline_monotonic=deadline_monotonic)
                frames = parent.read_frames(
                    grant.slot,
                    cut=cut,
                    max_frames=max_frames,
                    max_bytes=max_bytes,
                    deadline_monotonic=deadline_monotonic,
                )
                if not self.current() or not self._matches(grant, child):
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                if any(
                    frame.slot != grant.slot or frame.ingress.first <= cut.after_ordinal
                    for frame in frames
                ):
                    fail()
                if time.monotonic() >= deadline_monotonic:
                    raise LocalDeviceFailure("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504)
                with self._lock:
                    if (
                        self._stopping
                        or self._grant is not grant
                        or self._cut is not cut
                    ):
                        fail()
                    if frames:
                        self._batches[id(frames)] = frames
                        frame = frames[-1].frame
                        codec = frame.summary().codec
                        self._proof = LocalLiveProof(
                            self._proof.login_accepted,
                            self._proof.same_original_session,
                            self._proof.serial_matched,
                            self._proof.channel_matched,
                            self._proof.live_permission,
                            codec in ("h264", "h265"),
                            bool(frame.source_header.private_bytes()),
                            frame.device_timestamp.unix_microseconds is not None,
                            "hevc" if codec == "h265" else "h264",
                        )
                    handed_off = True
                return frames
        finally:
            try:
                if frames and not handed_off:
                    with self._original_io_lock:
                        parent.release_frames(frames)
                    with self._lock:
                        self._batches.pop(id(frames), None)
            finally:
                self._leave(token)

    def release_frames(self, frames: tuple[MuxValidatedFrame, ...]) -> None:
        if not frames:
            return
        token = self._claim(cleanup=True)
        if token is None:
            fail()
        claimed = False
        try:
            with self._lock:
                if (
                    self._batches.get(id(frames)) is not frames
                    or id(frames) in self._releasing
                ):
                    fail()
                self._releasing.add(id(frames))
                claimed = True
            with self._original_io_lock:
                self._original_parent.release_frames(frames)
            with self._lock:
                del self._batches[id(frames)]
        finally:
            with self._lock:
                if claimed:
                    self._releasing.remove(id(frames))
            self._leave(token)

    def attach_retirement(
        self, check: Callable[[], ViewerCleanupReceipt | None]
    ) -> None:
        with self._lock:
            if self._retirement is not None or not callable(check) or self._receipt:
                fail()
            self._retirement = check

    def issued_receipt(self) -> ViewerCleanupReceipt | None:
        with self._lock:
            return self._receipt

    def close(self) -> ViewerCleanupReceipt | None:
        token = object()
        with self._lock:
            self._stopping = True
            if self._receipt is not None:
                return self._receipt
            if self._operations:
                return None
            self._operations.add(token)
            grant, cut, parked = self._grant, self._cut, self._parked
            check, started = self._retirement, self._started
        parent = self._original_parent
        try:
            if not parked:
                if not self._original_io_lock.acquire(blocking=False):
                    return None
                try:
                    if cut is not None:
                        try:
                            parent.park(grant.slot)
                        except Exception:  # noqa: BLE001 -- retain failed original cleanup
                            if not parent.failed or not parent.close(0):
                                return None
                    with self._lock:
                        self._parked = True
                finally:
                    self._original_io_lock.release()
            receipt: ViewerCleanupReceipt | None
            if check is None:
                if started:
                    return None
                receipt = ViewerCleanupReceipt(
                    lease_id=grant.lease_id,
                    registration_id=grant.registration,
                    decoder_settled=True,
                    peer_settled=True,
                    media_cleared=True,
                    _authority=object(),
                    _seal=_CUSTODY_SEAL,
                )
            else:
                receipt = check()
            with self._lock:
                if (
                    self._operations != {token}
                    or self._batches
                    or self._grant is not grant
                    or self._cut is not cut
                    or self._retirement is not check
                    or type(receipt) is not ViewerCleanupReceipt
                    or receipt.lease_id != grant.lease_id
                    or receipt.registration_id != grant.registration
                ):
                    return None
                self._receipt = receipt
                return receipt
        finally:
            self._leave(token)


class _NativeIssuer:
    def __init__(self, owner: PreparedDedicatedMain) -> None:
        self.owner = owner

    def issued_receipt(self) -> EpochCleanupReceipt | None:
        return self.owner.custodian.receipt()


class _ViewerIssuer:
    def __init__(self) -> None:
        self.receipt: ViewerCleanupReceipt | None = None

    def issued_receipt(self) -> ViewerCleanupReceipt | None:
        return self.receipt


class _DedicatedSession:
    def __init__(
        self, prepared: PreparedDedicatedMain, session: OwnedLocalLiveSession
    ) -> None:
        self.prepared, self.session = prepared, session
        self.proof = session.proof

    def current(
        self, *, deadline_monotonic: float, current: Callable[[], bool]
    ) -> bool:
        with self.prepared.custodian.external_operation():
            if self.prepared._stopping:
                return False
            return self.session.current(
                deadline_monotonic=deadline_monotonic,
                current=lambda: not self.prepared._stopping and current(),
            )

    def read_frames(
        self,
        *,
        max_frames: int,
        max_bytes: int,
        deadline_monotonic: float,
        current: Callable[[], bool],
    ) -> tuple[PrivateLiveFrame, ...]:
        with self.prepared.custodian.external_operation():
            if self.prepared._stopping:
                fail()
            return self.session.read_frames(
                max_frames=max_frames,
                max_bytes=max_bytes,
                deadline_monotonic=deadline_monotonic,
                current=lambda: not self.prepared._stopping and current(),
            )

    def close(self) -> bool:
        return self.prepared.close_native() is not None


class PreparedDedicatedMain:
    def __init__(
        self,
        provider: NativeLocalMuxProvider,
        lease: LocalMediaLease,
        registration: UUID,
        custodian: MuxOriginalCustodian,
    ) -> None:
        self.provider, self.lease, self.registration, self.custodian = (
            provider,
            lease,
            registration,
            custodian,
        )
        self.native_issuer = _NativeIssuer(self)
        self.viewer_issuer = _ViewerIssuer()
        self._started = False
        self._stopping = False
        self._retirement: Callable[[], ViewerCleanupReceipt | None] | None = None
        self._raw_credit: MediaCreditToken | None = None
        self._session: OwnedLocalLiveSession | None = None
        self.owner = ChildOwner(None, None, cast(tuple[BinaryIO, BinaryIO], ()))
        register_pending_owner(self.owner)
        custodian.register(self.owner)
        self.native = WindowsSocketProvider(
            mux_config=provider.native._mux_config, mux_custodian=custodian
        )
        self.native.owner = self.owner

    def start(
        self,
        credentials: LocalDeviceCredentials,
        selection: LocalMediaChannel,
        *,
        budget: LocalVerifyBudget,
    ) -> _DedicatedSession:
        from .local_live_ipc import LiveParentAuthority
        from .local_live_provider import LiveSelection, failure
        from .windows_socket import PrivateRequest

        if self._started or self._stopping or selection.stream != "main":
            fail()
        self._started = True
        authority = LiveParentAuthority(
            budget.deadline_monotonic,
            budget.cancel,
            LiveSelection(
                selection.guid,
                selection.raw_index,
                selection.window_index,
                selection.ordinal,
                "main",
            ),
            diagnostics=self.provider.first_key_debug is not None,
        )

        def current() -> bool:
            budget.remaining_ms()
            return (
                not self._stopping
                and self.provider.admission.current_dedicated_startup(
                    self.lease, self.registration, selection, budget=budget
                )
            )

        try:
            with self.custodian.constructing():
                budget.remaining_ms()
                self._raw_credit = reserve_media_credit(
                    slot=None,
                    registration=self.registration,
                    frames=0,
                    bytes=RAW_STAGING_BYTES,
                    stage="raw",
                )
                if self._raw_credit is None:
                    raise LocalDeviceFailure("LOCAL_DEVICE_BUSY", 429)
                config = self.provider.native._mux_config
                if config is None:
                    fail()
                result = self.native.run(
                    config,
                    PrivateRequest(
                        "live",
                        credentials.country,
                        credentials.serial,
                        credentials.username,
                        credentials.password,
                        metadata_read_opt_in=True,
                        live_read_opt_in=True,
                        store_ref="SERVICE",
                        channel_position=selection.ordinal,
                        stream=1,
                    ),
                    service=authority,
                    current=current,
                )
                if not authority.handed_off or not current():
                    raise failure(authority.failure or result.failure)
                self._session = OwnedLocalLiveSession(self.owner, authority)
            return _DedicatedSession(self, self._session)
        except BaseException:
            retired_native_receipt = self.close_native()
            # Only the exact original known login BUSY after confirmed reap.
            busy = self.native.recover_retired_login_busy()
            if (
                busy is not None
                and retired_native_receipt is not None
                and authority.failure in ("protocol", "closed")
            ):
                budget.remaining_ms()
                if self.provider.admission.current_dedicated_startup(
                    self.lease,
                    self.registration,
                    selection,
                    budget=budget,
                    retired_native_receipt=retired_native_receipt,
                ):
                    budget.remaining_ms()
                    raise failure("device_busy") from None
            raise

        finally:
            # One original startup summary after run/failed cleanup, outside
            # constructing and authority locks. Never replace its outcome.
            callback = self.provider.first_key_debug
            if callback is not None:
                try:
                    record = authority.first_key_snapshot()
                    if record is not None:
                        callback(record)
                except BaseException:  # noqa: BLE001,S110 -- optional diagnostic only
                    pass

    def close_native(self) -> EpochCleanupReceipt | None:
        self._stopping = True
        self.owner.request_stop()
        if not self.custodian._constructor_finished and not self.custodian._active:
            with self.custodian.constructing():
                pass
        if not self.owner.finish(0.2):
            return None
        receipt = self.native_issuer.issued_receipt()
        if receipt is not None:
            if self._raw_credit is not None:
                release_media_credit(self._raw_credit)
                self._raw_credit = None
            remove_confirmed_owner(self.owner)
        return receipt

    def attach_retirement(
        self, check: Callable[[], ViewerCleanupReceipt | None]
    ) -> None:
        if self._retirement is not None or not callable(check):
            fail()
        self._retirement = check

    def close_viewer(self) -> ViewerCleanupReceipt | None:
        if self.viewer_issuer.receipt is not None:
            return self.viewer_issuer.receipt
        if self._retirement is None:
            if self._session is None and self.custodian.constructor_settled():
                assert self.lease.id is not None
                self.viewer_issuer.receipt = ViewerCleanupReceipt(
                    lease_id=self.lease.id,
                    registration_id=self.registration,
                    decoder_settled=True,
                    peer_settled=True,
                    media_cleared=True,
                    _authority=object(),
                    _seal=_CUSTODY_SEAL,
                )
            return self.viewer_issuer.receipt
        receipt = self._retirement()
        if (
            type(receipt) is ViewerCleanupReceipt
            and receipt.lease_id == self.lease.id
            and receipt.registration_id == self.registration
        ):
            self.viewer_issuer.receipt = receipt
        return self.viewer_issuer.receipt
