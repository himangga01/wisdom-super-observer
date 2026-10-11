"""Inert coordinator concurrency checks; no native or database acceptance."""

import importlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from threading import Event, Lock
from uuid import uuid4

import pytest
from wso_core.tvt.local_media_admission import _SEAL, LocalMediaLease
from wso_core.tvt.local_media_mux_types import (
    _CUSTODY_SEAL,
    _GRANT_SEAL,
    _NATIVE_BINDING_SEAL,
    CleanupScope,
    EpochCleanupReceipt,
    FocusGrant,
    IngressCut,
    MasterLoginProof,
    MasterReservation,
    MuxEpochIdentity,
    MuxOriginalReservation,
    MuxScopeKey,
    MuxSlotIdentity,
    OriginalMuxBinding,
    SlotRetentionGrant,
    TransportGrant,
    ViewerCleanupReceipt,
    ViewerGrant,
)
from wso_core.tvt.local_media_service import LocalLiveProof, LocalMediaChannel
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget


def service():
    name = "wso_core.tvt.local_media_mux_service"
    assert importlib.util.find_spec(name), (
        "coordinator construction ownership is missing"
    )
    return importlib.import_module(name)


class Budget:
    def __init__(self, epoch):
        self.epoch = epoch
        self.reservations = []

    def reserve(self, kind):
        item = MuxOriginalReservation(
            id=uuid4(),
            kind=kind,
            worker_epoch=self.epoch,
            _authority=object(),
            _seal=_CUSTODY_SEAL,
        )
        self.reservations.append(item)
        return item

    def release_confirmed(self, reservation, receipt):
        self.reservations.remove(reservation)


class Admission:
    """Models only the sealed creator/follower and pre-start registration ports."""

    def __init__(self):
        self.scope = MuxScopeKey(
            uuid4(),
            1,
            uuid4(),
            bytes(32),
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            1,
            uuid4(),
            1,
            uuid4(),
        )
        self.transport = TransportGrant(
            scope=self.scope,
            expires_monotonic=1e12,
            native_generation=uuid4(),
            _authority=object(),
            _seal=_GRANT_SEAL,
        )
        self.reservation = MasterReservation(
            scope=self.scope,
            master_id=uuid4(),
            creator=True,
            transport=self.transport,
            deadline_monotonic=1e12,
            _seal=_GRANT_SEAL,
        )
        self.lock = Lock()
        self.calls = 0
        self.registered = None
        self.login_calls = 0
        self.activate_calls = 0
        self.channels = {}
        self.slots = {}
        self.viewers = {}
        self.finished = {}
        self.epoch_finished = False
        self.denied = False
        self.tickets = {}
        self.focus_current = set()
        self.focus_settled = []
        self.focus_acknowledgements = {}
        self.dedicated = {}
        self.dedicated_finished = set()
        self.refreshes = []
        self.attempts = {}

    def begin_master_attempt(self, viewer):
        from wso_core.tvt.local_media_mux_admission import MasterReserveAttempt

        handle = MasterReserveAttempt(object())
        self.attempts[id(handle)] = (handle, viewer)
        return handle

    def resolve_master_attempt(self, attempt, *, budget):
        return None

    def reserve_master(self, viewer, *, budget, attempt=None):
        with self.lock:
            self.calls += 1
            return (
                self.reservation
                if self.calls == 1
                else replace(
                    self.reservation,
                    creator=False,
                    _seal=_GRANT_SEAL,
                )
            )

    def register_original(self, reservation, issuer, custody):
        assert self.registered is None
        self.registered = issuer, custody

    def prepare_login(self, reservation, *, budget):
        assert reservation is self.reservation
        self.login_calls += 1
        return object(), self.transport

    def activate_master(self, reservation, proof, *, budget):
        self.activate_calls += 1
        return self.transport

    def current_transport(self, grant):
        return grant is self.transport and not self.denied

    def redeem_wall_heartbeat(self, ticket, *, budget):
        return self.scope.wall_id

    def refresh_grant(self, grant):
        new = replace(grant, expires_monotonic=1e12 + 1, _seal=_GRANT_SEAL)
        self.refreshes.append((grant, new))
        if grant is self.transport:
            self.transport = new
        return new

    def prepare_viewer(self, lease, *, budget):
        return self.channels.setdefault(
            lease.id, LocalMediaChannel(uuid4().bytes, 1, 1, 1, "digital", "sub")
        )

    def reserve_slot(self, viewer, reservation, *, binding, budget):
        if binding.channel not in self.slots:
            self.slots[binding.channel] = SlotRetentionGrant(
                scope=self.scope,
                slot=MuxSlotIdentity(binding.epoch, binding.channel, uuid4().bytes, 2),
                expires_monotonic=1e12,
                _authority=object(),
                _seal=_GRANT_SEAL,
            )
        return self.slots[binding.channel]

    def admit_viewer(self, viewer, slot, *, registration, budget):
        return ViewerGrant(
            scope=self.scope,
            slot=slot.slot,
            lease_id=viewer.id,
            registration=registration,
            expires_monotonic=1e12,
            _authority=object(),
            _seal=_GRANT_SEAL,
        )

    def register_viewer_custodian(self, grant, custody):
        assert grant.lease_id not in self.viewers
        self.viewers[grant.lease_id] = custody

    def current_slot(self, grant):
        return not self.denied

    def current_viewer(self, grant):
        return not self.denied and grant.lease_id not in self.finished

    def activate_viewer(self, grant, proof, *, budget):
        proof.validate(delivery=True)
        return self.view_for(grant.lease_id)

    def view_for(self, identifier):
        from wso_contracts.tvt.media import MediaLease

        from tests.tvt_parity.test_local_media_contracts import local_values

        return MediaLease(**local_values()).model_copy(update={"id": identifier})

    def view(self, lease):
        if lease.id in self.finished or lease.id in self.dedicated_finished:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return self.view_for(lease.id)

    def finish_viewer(self, grant, receipt, *, scope):
        assert self.viewers[grant.lease_id].issued_receipt() is receipt
        self.finished[grant.lease_id] = scope

    def finish_epoch(self, grant, receipt):
        assert self.registered[1].issued_receipt() is receipt
        self.epoch_finished = True

    def redeem_focus(self, ticket, *, budget):
        grant = self.tickets.pop(ticket)
        self.focus_current.add(id(grant))
        return grant

    def current_focus(self, grant):
        return id(grant) in self.focus_current and not self.denied

    def settle_focus(self, grant, transition, *, viewer=None):
        self.focus_current.discard(id(grant))
        self.focus_settled.append((grant, transition, viewer))
        ack = object()
        self.focus_acknowledgements[id(grant)] = (ack, transition, viewer)
        return ack

    def focus_settlement_current(self, grant, ack, transition, *, viewer=None):
        return self.focus_acknowledgements.get(id(grant)) == (ack, transition, viewer)

    def current_main_retention(self, lease, grant, acknowledgement):
        return self.focus_settlement_current(
            grant, acknowledgement, "ATTACHED", viewer=lease.id
        )

    def register_dedicated(
        self, lease, custody, viewer_issuer, *, registration, budget
    ):
        self.dedicated[lease.id] = custody, viewer_issuer

    def prepare_dedicated(self, lease, *, budget):
        assert lease.id in self.dedicated
        return object(), self.channels[lease.id]

    def activate(self, lease, proof, *, budget):
        proof.validate()
        return self.view_for(lease.id)

    def current(self, lease):
        return lease.id not in self.dedicated_finished

    def finish_dedicated(self, lease, receipt):
        assert self.dedicated[lease.id][0].issued_receipt() is receipt
        self.dedicated_finished.add(lease.id)

    def finish_dedicated_viewer(self, lease, receipt):
        assert self.dedicated[lease.id][1].issued_receipt() is receipt


class Prepared:
    def __init__(self, admission):
        self.admission = admission
        self.entered = Event()
        self.release = Event()
        self.calls = 0
        self.epoch = MuxEpochIdentity(1, uuid4().bytes)
        self.proof = MasterLoginProof(True, True, True, True, True, 1)
        self.bindings = {}
        self.opened = []
        self.receipt = None
        self.can_close = False
        self.closing = False
        self.handles = []
        self.swaps = []

    def start(self, credentials, grant, *, budget):
        assert self.admission.registered == (self, self)
        self.calls += 1
        self.entered.set()
        assert self.release.wait(2)
        budget.remaining_ms()
        return self.proof

    def binding_for(self, channel):
        if channel not in self.bindings:
            self.bindings[channel] = OriginalMuxBinding(
                scope=self.admission.scope,
                master_id=self.admission.reservation.master_id,
                native_generation=self.admission.transport.native_generation,
                epoch=self.epoch,
                channel=channel,
                proof=self.proof,
                _authority=object(),
                _seal=_NATIVE_BINDING_SEAL,
            )
        return self.bindings[channel]

    def issued_receipt(self):
        return self.receipt

    def close(self):
        self.closing = True
        if self.can_close and self.receipt is None:
            self.receipt = EpochCleanupReceipt(
                master_id=self.admission.reservation.master_id,
                worker_epoch=self.admission.scope.worker_epoch,
                native_generation=self.admission.transport.native_generation,
                original_state="REAPED",
                callback_settled=True,
                ipc_settled=True,
                job_settled=True,
                _authority=object(),
                _seal=_CUSTODY_SEAL,
            )
        return self.receipt

    def open_slot(self, selection, grant, *, budget):
        assert grant.slot not in self.opened
        self.opened.append(grant.slot)
        return grant.slot

    def prepare_viewer(self, grant):
        handle = Viewer(self.admission, grant)
        self.handles.append(handle)
        return handle

    def replace_grant(self, old, new):
        assert type(old) is type(new) and old.scope == new.scope
        self.swaps.append((old, new))
        for handle in self.handles:
            if handle.grant is old:
                handle.grant = new

    def refresh_grants(self, *, budget):
        budget.remaining_ms()
        return nullcontext()


class Viewer:
    def __init__(self, admission, grant):
        self.admission, self.grant = admission, grant
        self.registration = grant.registration
        self.cut = IngressCut(
            grant.slot.epoch, grant.slot, grant.registration, 1, 10, 1e12
        )
        self.proof = LocalLiveProof(
            True, True, True, True, True, True, True, True, "h264"
        )
        self.receipt = None
        self.can_close = True
        self.stopped = False
        self.batch = ()
        self.released = []

    def start(self, *, budget):
        assert self.admission.viewers[self.grant.lease_id] is self

    def current(self):
        return not self.stopped

    def current_grant(self):
        return self.grant

    def read_frames(self, **kwargs):
        return self.batch

    def release_frames(self, frames):
        assert frames is self.batch
        self.released.append(frames)

    def issued_receipt(self):
        return self.receipt

    def close(self):
        self.stopped = True
        if self.can_close and self.receipt is None:
            self.receipt = ViewerCleanupReceipt(
                lease_id=self.grant.lease_id,
                registration_id=self.registration,
                decoder_settled=True,
                peer_settled=True,
                media_cleared=True,
                _authority=object(),
                _seal=_CUSTODY_SEAL,
            )
        return self.receipt


class Provider:
    def __init__(self, admission):
        self.prepared = Prepared(admission)
        self.calls = 0
        self.main = None

    def prepare_master(self, reservation, original):
        self.calls += 1
        return self.prepared

    def prepare_dedicated(self, lease, scope, original_budget, registration):
        self.main = Main(self.prepared.admission, lease, registration)
        return self.main


class ReceiptOwner:
    def __init__(self):
        self.value = None

    def issued_receipt(self):
        return self.value


class Main:
    def __init__(self, admission, lease, registration):
        self.admission, self.lease, self.registration = admission, lease, registration
        self.native_issuer, self.viewer_issuer = ReceiptOwner(), ReceiptOwner()
        self.can_close = False
        self.can_close_viewer = True
        self.renewals = []
        self.proof = LocalLiveProof(
            True, True, True, True, True, True, True, True, "h264"
        )

    def start(self, credentials, selection, *, budget):
        assert self.admission.dedicated[self.lease.id] == (
            self.native_issuer,
            self.viewer_issuer,
        )
        return self

    def current(self, *, deadline_monotonic, current):
        accepted = current()
        if accepted:
            self.renewals.append(deadline_monotonic)
        return accepted

    def close_native(self):
        if self.can_close and self.native_issuer.value is None:
            self.native_issuer.value = EpochCleanupReceipt(
                master_id=self.lease.id,
                worker_epoch=self.lease.worker_epoch,
                native_generation=self.lease.native_generation,
                original_state="REAPED",
                callback_settled=True,
                ipc_settled=True,
                job_settled=True,
                _authority=object(),
                _seal=_CUSTODY_SEAL,
            )
        return self.native_issuer.value

    def close_viewer(self):
        if self.can_close_viewer and self.viewer_issuer.value is None:
            self.viewer_issuer.value = ViewerCleanupReceipt(
                lease_id=self.lease.id,
                registration_id=self.registration,
                decoder_settled=True,
                peer_settled=True,
                media_cleared=True,
                _authority=object(),
                _seal=_CUSTODY_SEAL,
            )
        return self.viewer_issuer.value


def setup():
    module = service()
    admission = Admission()
    provider = Provider(admission)
    budget = Budget(admission.scope.worker_epoch)
    coordinator = module.DeviceEpochCoordinator(admission, provider, budget)
    lease = LocalMediaLease(
        "a" * 64, admission.scope.worker_epoch, uuid4(), uuid4(), _SEAL
    )
    return coordinator, admission, provider, budget, lease


def test_concurrent_creators_publish_one_epoch():
    coordinator, admission, provider, budget, lease = setup()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(coordinator._master, lease, LocalVerifyBudget(2000))
        assert provider.prepared.entered.wait(1)
        second = pool.submit(coordinator._master, lease, LocalVerifyBudget(2000))
        provider.prepared.release.set()
        assert first.result() is second.result()
    assert provider.calls == provider.prepared.calls == admission.login_calls == 1
    assert admission.activate_calls == len(budget.reservations) == 1


def test_follower_cancellation_does_not_replace_or_retire_creator():
    coordinator, admission, provider, budget, lease = setup()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(coordinator._master, lease, LocalVerifyBudget(2000))
        assert provider.prepared.entered.wait(1)
        cancel = Event()
        cancel.set()
        with pytest.raises(LocalDeviceFailure):
            coordinator._master(lease, LocalVerifyBudget(2000, cancel=cancel))
        provider.prepared.release.set()
        original = first.result()
    assert coordinator._master(lease, LocalVerifyBudget(2000)) is original
    assert provider.calls == admission.activate_calls == len(budget.reservations) == 1


def test_failed_start_keeps_uncertain_original_charged():
    coordinator, _admission, provider, budget, lease = setup()
    cancel = Event()
    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(
            coordinator._master, lease, LocalVerifyBudget(2000, cancel=cancel)
        )
        assert provider.prepared.entered.wait(1)
        cancel.set()
        provider.prepared.release.set()
        with pytest.raises(LocalDeviceFailure):
            first.result()
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(2000))
    assert provider.calls == len(budget.reservations) == 1
    assert coordinator.shutdown() is False


def attached_pair():
    coordinator, admission, provider, budget, first = setup()
    provider.prepared.release.set()
    second = replace(first, id=uuid4(), token="b" * 64)
    a = coordinator.attach(first, budget=LocalVerifyBudget(2000))
    b = coordinator.attach(second, budget=LocalVerifyBudget(2000))
    return coordinator, admission, provider, budget, first, second, a, b


def test_park_keeps_slot_identity_not_rgb():
    coordinator, admission, provider, _budget, first, _second, a, b = attached_pair()
    assert (
        coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
        is CleanupScope.VIEWER
    )
    third = replace(first, id=uuid4(), token="c" * 64)
    admission.channels[third.id] = admission.channels[first.id]
    c = coordinator.attach(third, budget=LocalVerifyBudget(2000))
    assert c is not a and c.registration != a.registration
    assert c.cut.slot is a.cut.slot
    assert len(provider.prepared.opened) == 2
    assert a.stopped and b.current() and not provider.prepared.closing


@pytest.mark.parametrize("fault", ["copied_grant", "foreign_slot", "denied"])
def test_parked_replacement_rejects_changed_reservation_without_native_open(fault):
    coordinator, admission, provider, _budget, first, _second, _a, _b = attached_pair()
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    third = replace(first, id=uuid4(), token="c" * 64)
    admission.channels[third.id] = admission.channels[first.id]
    reserve = admission.reserve_slot

    def altered(*args, **kwargs):
        grant = reserve(*args, **kwargs)
        if fault == "denied":
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        if fault == "foreign_slot":
            return replace(
                grant,
                slot=replace(grant.slot, channel=uuid4().bytes),
                _seal=_GRANT_SEAL,
            )
        return replace(grant, _seal=_GRANT_SEAL)

    admission.reserve_slot = altered
    with pytest.raises(LocalDeviceFailure):
        coordinator.attach(third, budget=LocalVerifyBudget(2000))
    assert len(provider.prepared.opened) == 2


def test_parked_replacement_requires_its_own_authoritative_slot_binding():
    coordinator, admission, provider, _budget, first, _second, a, _b = attached_pair()
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    third = replace(first, id=uuid4(), token="c" * 64)
    admission.channels[third.id] = admission.channels[first.id]
    bound = set()
    reserve, admit = admission.reserve_slot, admission.admit_viewer

    def reserve_bound(viewer, *args, **kwargs):
        result = reserve(viewer, *args, **kwargs)
        bound.add((viewer.id, id(result)))
        return result

    def admit_bound(viewer, slot, **kwargs):
        if (viewer.id, id(slot)) not in bound:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return admit(viewer, slot, **kwargs)

    admission.reserve_slot, admission.admit_viewer = reserve_bound, admit_bound
    c = coordinator.attach(third, budget=LocalVerifyBudget(2000))
    assert c.cut.slot is a.cut.slot and c.registration != a.registration
    assert len(provider.prepared.opened) == 2


def test_last_detach_vs_attach_requires_original_barrier():
    coordinator, admission, provider, budget, first, second, _a, _b = attached_pair()
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    assert (
        coordinator.detach(second.id, budget=LocalVerifyBudget(2000))
        is CleanupScope.LAST_VIEWER_AND_DEVICE_EPOCH
    )
    assert provider.prepared.closing and len(budget.reservations) == 1
    third = replace(first, id=uuid4(), token="c" * 64)
    with pytest.raises(LocalDeviceFailure):
        coordinator.attach(third, budget=LocalVerifyBudget(2000))
    provider.prepared.can_close = True
    assert coordinator.shutdown() is True
    assert not budget.reservations and admission.epoch_finished


def test_local_media_uncertainty_blocks_same_channel_and_shutdown():
    coordinator, admission, provider, _budget, first, _second, a, _b = attached_pair()
    a.can_close = False
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    third = replace(first, id=uuid4(), token="c" * 64)
    admission.channels[third.id] = admission.channels[first.id]
    with pytest.raises(LocalDeviceFailure):
        coordinator.attach(third, budget=LocalVerifyBudget(2000))
    provider.prepared.can_close = True
    assert coordinator.shutdown() is False
    a.can_close = True
    assert coordinator.shutdown() is True


def test_retention_denial_fences_all_master_viewers():
    coordinator, admission, provider, _budget, first, second, a, b = attached_pair()
    admission.denied = True
    coordinator.sweep()
    assert not coordinator.current(first.id) and not coordinator.current(second.id)
    assert a.stopped and b.stopped and provider.prepared.closing


def forward_setup():
    coordinator, admission, provider, budget, first = setup()
    now = [1.0]
    coordinator._clock = lambda: now[0]
    provider.prepared.release.set()
    handle = coordinator.attach(first, budget=LocalVerifyBudget(2000))
    grant = FocusGrant(
        scope=admission.scope,
        lease_id=first.id,
        direction="FORWARD",
        admitted_monotonic=1.0,
        expires_monotonic=21.0,
        _authority=object(),
        _seal=_GRANT_SEAL,
    )
    admission.tickets["focus"] = grant
    assert coordinator.reserve_focus("focus", budget=LocalVerifyBudget(2000)) is grant
    return coordinator, admission, provider, budget, first, handle, grant, now


@pytest.mark.parametrize("outcome", ["FAILED", "CANCELLED", "EXPIRED"])
def test_failed_busy_cancel_or_expiry_last_ref_retires_master(outcome):
    coordinator, admission, provider, budget, first, _handle, grant, now = (
        forward_setup()
    )
    assert (
        coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
        is CleanupScope.VIEWER
    )
    assert not provider.prepared.closing
    if outcome == "EXPIRED":
        now[0] = 21.0
    coordinator.settle_focus(grant, outcome, viewer_id=None)
    assert provider.prepared.closing and len(budget.reservations) == 1
    assert admission.focus_settled == [(grant, outcome, None)]


def test_twenty_second_pending_never_renews():
    coordinator, admission, provider, _budget, first, _handle, grant, now = (
        forward_setup()
    )
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    now[0] = 20.999
    coordinator.sweep()
    assert not provider.prepared.closing
    now[0] = 21.0
    coordinator.sweep()
    assert provider.prepared.closing
    assert admission.focus_settled == [(grant, "EXPIRED", None)]


def test_foreign_focus_cannot_keep_original_alive():
    coordinator, _admission, provider, _budget, first, _handle, grant, _now = (
        forward_setup()
    )
    copied = replace(grant, _seal=_GRANT_SEAL)
    with pytest.raises(LocalDeviceFailure):
        coordinator.retain_focus(copied)
    coordinator.settle_focus(grant, "CANCELLED", viewer_id=None)
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    assert provider.prepared.closing


def main_setup():
    coordinator, admission, provider, budget, first, _handle, _grant, now = (
        forward_setup()
    )
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    main = replace(first, id=uuid4(), native_generation=uuid4(), token="d" * 64)
    admission.channels[main.id] = replace(admission.channels[first.id], stream="main")
    coordinator.attach_dedicated(main, budget=LocalVerifyBudget(2000))
    return coordinator, admission, provider, budget, first, main, now


def test_sole_forward_and_return_refs_cover_both_gaps():
    coordinator, admission, provider, budget, first, main, _now = main_setup()
    assert not provider.prepared.closing
    grant = FocusGrant(
        scope=admission.scope,
        lease_id=main.id,
        direction="RETURN",
        admitted_monotonic=2.0,
        expires_monotonic=22.0,
        _authority=object(),
        _seal=_GRANT_SEAL,
    )
    admission.tickets["return"] = grant
    coordinator.reserve_focus("return", budget=LocalVerifyBudget(2000))
    assert (
        coordinator.detach(main.id, budget=LocalVerifyBudget(2000))
        is CleanupScope.DEDICATED_NATIVE
    )
    sub = replace(first, id=uuid4(), token="e" * 64)
    admission.channels[sub.id] = admission.channels[first.id]
    with pytest.raises(LocalDeviceFailure):
        coordinator.attach(sub, budget=LocalVerifyBudget(2000))
    provider.main.can_close = True
    coordinator.detach(main.id, budget=LocalVerifyBudget(2000))
    result = coordinator.attach(sub, budget=LocalVerifyBudget(2000))
    assert result.cut.registration != first.id
    assert not provider.prepared.closing
    assert len(budget.reservations) == 1


def test_return_consumes_main_active_atomically():
    coordinator, admission, provider, _budget, _first, main, _now = main_setup()
    grant = FocusGrant(
        scope=admission.scope,
        lease_id=main.id,
        direction="RETURN",
        admitted_monotonic=2.0,
        expires_monotonic=22.0,
        _authority=object(),
        _seal=_GRANT_SEAL,
    )
    admission.tickets["return"] = grant
    coordinator.reserve_focus("return", budget=LocalVerifyBudget(2000))
    coordinator.settle_focus(grant, "CANCELLED", viewer_id=None)
    # The old MAIN_ACTIVE reference must not silently survive this cancellation.
    assert provider.prepared.closing
    assert coordinator.current(main.id) is False


def test_heartbeat_swaps_each_purpose_and_parked_slot_without_replacing_identity():
    coordinator, admission, provider, _budget, first, second, _a, _b = attached_pair()
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    before = tuple(provider.prepared.opened)
    coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(2000))
    assert len(admission.refreshes) == 4  # master, two slots, one viewer
    assert provider.prepared.swaps == admission.refreshes
    assert tuple(provider.prepared.opened) == before
    assert coordinator.current(second.id)


def test_failed_refresh_fences_even_previously_cached_viewers():
    coordinator, admission, provider, _budget, first, second, _a, _b = attached_pair()

    def failed(grant):
        raise LocalDeviceFailure()

    admission.refresh_grant = failed
    with pytest.raises(LocalDeviceFailure):
        coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(2000))
    assert not coordinator.current(first.id) and not coordinator.current(second.id)
    assert provider.prepared.closing


def test_mux_executor_rejects_raw_path_and_releases_invalid_exact_batch():
    coordinator, admission, _provider, _budget, first, _second, a, _b = attached_pair()
    executor = service().MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    with pytest.raises(LocalDeviceFailure):
        executor.read_frames(first.id, max_frames=1, max_bytes=1024, deadline_ms=100)
    batch = (object(),)
    a.batch = batch
    with pytest.raises(LocalDeviceFailure):
        executor.read_mux_frames(
            first.id, max_frames=1, max_bytes=1024, deadline_ms=100
        )
    assert len(a.released) == 1 and a.released[0] is batch


def test_original_receipt_callback_replacement_never_releases_budget():
    coordinator, admission, provider, budget, first = setup()
    provider.prepared.release.set()
    coordinator.attach(first, budget=LocalVerifyBudget(2000))
    provider.prepared.can_close = True
    original = provider.prepared.issued_receipt
    provider.prepared.issued_receipt = lambda: original()
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    assert not admission.epoch_finished
    assert len(budget.reservations) == 1


def test_viewer_receipt_issuer_mutation_during_callback_never_closes_sql():
    coordinator, admission, _provider, _budget, first, _second, a, _b = attached_pair()

    def changed():
        a.issued_receipt = lambda: a.receipt
        return a.receipt

    a.issued_receipt = changed
    # Simulate a callback retaining its original function, then mutating on call.
    coordinator._viewers[first.id].issuer = changed
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    assert first.id not in admission.finished


def test_shutdown_during_native_start_never_activates_late_result():
    coordinator, admission, provider, _budget, first = setup()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(coordinator._master, first, LocalVerifyBudget(2000))
        assert provider.prepared.entered.wait(1)
        assert coordinator.shutdown() is False
        provider.prepared.release.set()
        with pytest.raises(LocalDeviceFailure):
            future.result()
    assert admission.activate_calls == 0


def test_stop_wall_is_idempotent_after_original_receipt_and_local_settlement():
    coordinator, admission, provider, _budget, _first, _second, _a, _b = attached_pair()
    provider.prepared.can_close = True
    assert coordinator.stop_wall(
        admission.scope.wall_id, budget=LocalVerifyBudget(2000)
    )
    assert coordinator.stop_wall(
        admission.scope.wall_id, budget=LocalVerifyBudget(2000)
    )


def test_legacy_typed_adapter_keeps_native_and_viewer_barriers_separate():
    from test_local_media_service import Admission as LegacyAdmission
    from test_local_media_service import Provider as LegacyProvider
    from test_local_media_service import Session, executor
    from wso_core.tvt import local_media_service

    admission, session = LegacyAdmission(), Session()
    worker = executor(admission, LegacyProvider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="typed")
    registration = uuid4()
    issuer = ReceiptOwner()
    receipt = ViewerCleanupReceipt(
        lease_id=admission.view.id,
        registration_id=registration,
        decoder_settled=True,
        peer_settled=True,
        media_cleared=True,
        _authority=object(),
        _seal=_CUSTODY_SEAL,
    )
    adapter_type = getattr(local_media_service, "LocalViewerCleanupAdapter", None)
    assert adapter_type is not None, "typed legacy viewer barrier adapter is missing"
    barrier = adapter_type(
        admission.view.id, registration, lambda: issuer.value, issuer
    )
    worker.attach_retirement(admission.view.id, barrier)
    assert worker.close(admission.view.id) is False
    assert session.closed == 1
    issuer.value = receipt
    assert worker.close(admission.view.id) is True


def test_delayed_sql_activation_past_budget_never_publishes_viewer():
    coordinator, admission, provider, _budget, first = setup()
    provider.prepared.release.set()
    now = [1.0]
    caller = LocalVerifyBudget(1000, clock=lambda: now[0])
    original = admission.activate_viewer

    def delayed(grant, proof, *, budget):
        original(grant, proof, budget=budget)
        now[0] = 2.1

    admission.activate_viewer = delayed
    with pytest.raises(LocalDeviceFailure) as error:
        coordinator.attach(first, budget=caller)
    assert error.value.code == "LOCAL_DEVICE_DEADLINE_EXCEEDED"
    assert not coordinator.current(first.id)
    assert provider.prepared.handles[0].stopped


def test_concurrent_shutdown_during_credential_work_uses_short_registry_lock():
    coordinator, admission, provider, _budget, first = setup()
    entered, release = Event(), Event()
    original = admission.prepare_login

    def blocked(reservation, *, budget):
        entered.set()
        assert release.wait(2)
        return original(reservation, budget=budget)

    admission.prepare_login = blocked
    with ThreadPoolExecutor(2) as pool:
        startup = pool.submit(coordinator._master, first, LocalVerifyBudget(2000))
        assert entered.wait(1)
        stopping = pool.submit(coordinator.shutdown)
        try:
            assert stopping.result(timeout=0.5) is False
        finally:
            release.set()
        with pytest.raises(LocalDeviceFailure):
            startup.result()
    assert provider.prepared.calls == 0


def test_twelve_viewer_profile_counts_active_dedicated_main():
    coordinator, _admission, _provider, _budget, first, _main, _now = main_setup()
    for index in range(11):
        extra = replace(first, id=uuid4(), token=f"{index + 30:064x}")
        coordinator.attach(extra, budget=LocalVerifyBudget(2000))
    overflow = replace(first, id=uuid4(), token="f" * 64)
    with pytest.raises(LocalDeviceFailure) as error:
        coordinator.attach(overflow, budget=LocalVerifyBudget(2000))
    assert error.value.code == "LOCAL_DEVICE_BUSY"


def test_main_original_issuer_replacement_stays_charged():
    coordinator, admission, provider, budget, _first, main, _now = main_setup()
    provider.main.can_close = True
    original = provider.main.native_issuer.issued_receipt
    provider.main.native_issuer.issued_receipt = lambda: original()
    coordinator.detach(main.id, budget=LocalVerifyBudget(2000))
    assert main.id not in admission.dedicated_finished
    assert sum(r.kind == "main" for r in budget.reservations) == 1


def test_attached_focus_requires_exact_current_target_viewer():
    coordinator, admission, _provider, _budget, _first, _handle, grant, _now = (
        forward_setup()
    )
    with pytest.raises(LocalDeviceFailure):
        coordinator.settle_focus(grant, "ATTACHED", viewer_id=uuid4())
    assert not admission.focus_settled


def test_finish_stop_reports_closed_only_after_exact_original_and_local_receipts():
    coordinator, admission, provider, _budget, first, second, _a, _b = attached_pair()
    executor = service().MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    response = executor.finish_stop(first.id, correlation_id="stop")
    assert response.lease.state == "CLOSED"
    with pytest.raises(LocalDeviceFailure):
        executor.finish_stop(second.id, correlation_id="stop-last")
    provider.prepared.can_close = True
    response = executor.finish_stop(second.id, correlation_id="stop-last")
    assert response.lease.state == "CLOSED"
    assert (
        executor.finish_stop(second.id, correlation_id="retry").lease.state == "CLOSED"
    )


def test_mux_binding_follows_exact_refreshed_grant_and_rejects_copy():
    coordinator, admission, _provider, _budget, first, _second, a, _b = attached_pair()
    executor = service().MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    handle, old = executor.mux_binding(first.id)
    assert handle is a and old is a.grant
    coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(2000))
    handle, fresh = executor.mux_binding(first.id)
    assert fresh is a.grant and fresh is not old
    a.current_grant = lambda: replace(fresh, _seal=_GRANT_SEAL)
    with pytest.raises(LocalDeviceFailure):
        executor.mux_binding(first.id)


def test_mux_binding_reentrant_stop_denies_after_callback():
    coordinator, admission, _provider, _budget, first, _second, a, _b = attached_pair()
    executor = service().MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    a.can_close = False
    registration = executor.registration(first.id)

    def stop_then_return():
        coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
        return a.grant

    a.current_grant = stop_then_return
    with pytest.raises(LocalDeviceFailure):
        executor.mux_binding(first.id)
    assert executor.registration(first.id) == registration


def test_exact_frame_batch_credit_releases_while_stopping():
    from test_local_live_mux import feed, wire
    from wso_core.tvt.local_live_mux import MultiplexLiveCodec

    coordinator, admission, _provider, _budget, first, _second, a, _b = attached_pair()
    executor = service().MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    codec = MultiplexLiveCodec(
        epoch=a.cut.epoch, peer_capability=6, authorize=lambda _: True
    )
    codec.register_slot(a.cut.slot, channel_number=1)
    # Existing helper defaults generation=7; use its wire builder with this epoch.
    from test_local_live import REQUEST, oz, packet, yz

    codec.open_slot(a.cut.slot, request_guid=REQUEST, sequence=1)
    feed(
        codec,
        packet(
            0x10000000 | 1285,
            yz(channel=a.cut.slot.channel, task=a.cut.slot.task) + oz(0),
            sequence=1,
            declared=0,
        ),
        first=11,
        generation=1,
    )
    a.batch = feed(codec, wire(a.cut.slot), first=12, generation=1)
    result = executor.read_mux_frames(
        first.id, max_frames=1, max_bytes=1 << 20, deadline_ms=100
    )
    assert result is a.batch and len(result) == 1
    a.can_close = False
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    executor.release_mux_frames(first.id, result)
    assert a.released[0] is result


def test_current_waits_for_inflight_heartbeat_instead_of_retiring_valid_viewer():
    coordinator, admission, provider, _budget, first, _second, _a, _b = attached_pair()
    entered, release = Event(), Event()
    original = admission.refresh_grant

    def delayed(grant):
        if type(grant) is TransportGrant:
            entered.set()
            assert release.wait(2)
        return original(grant)

    admission.refresh_grant = delayed
    with ThreadPoolExecutor(2) as pool:
        heartbeat = pool.submit(
            coordinator.heartbeat, "heartbeat", budget=LocalVerifyBudget(2000)
        )
        assert entered.wait(1)
        current = pool.submit(coordinator.current, first.id)
        try:
            from concurrent.futures import TimeoutError

            with pytest.raises(TimeoutError):
                current.result(timeout=0.05)
        finally:
            release.set()
        heartbeat.result()
        assert current.result() is True
    assert not provider.prepared.closing


def test_parked_physical_slots_remain_charged_at_sixteen():
    coordinator, _admission, provider, _budget, first = setup()
    provider.prepared.release.set()
    coordinator.attach(first, budget=LocalVerifyBudget(2000))
    for index in range(15):
        extra = replace(first, id=uuid4(), token=f"{index + 100:064x}")
        coordinator.attach(extra, budget=LocalVerifyBudget(2000))
        coordinator.detach(extra.id, budget=LocalVerifyBudget(2000))
    overflow = replace(first, id=uuid4(), token="f" * 64)
    with pytest.raises(LocalDeviceFailure) as error:
        coordinator.attach(overflow, budget=LocalVerifyBudget(2000))
    assert error.value.code == "LOCAL_DEVICE_BUSY"
    assert len(provider.prepared.opened) == 16


def test_expired_heartbeat_result_fences_master_before_reporting_success():
    coordinator, admission, provider, _budget, first, _second, _a, _b = attached_pair()
    old = admission.refresh_grant

    def expired(grant):
        replacement = old(grant)
        return replace(replacement, expires_monotonic=1.0, _seal=_GRANT_SEAL)

    admission.refresh_grant = expired
    with pytest.raises(LocalDeviceFailure):
        coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(2000))
    assert not coordinator.current(first.id) and provider.prepared.closing


def test_sql_focus_ticket_does_not_override_known_local_viewer_denial():
    coordinator, admission, _provider, _budget, _first, handle, grant, _now = (
        forward_setup()
    )
    coordinator.settle_focus(grant, "CANCELLED", viewer_id=None)
    handle.stopped = True
    second_grant = replace(grant, _seal=_GRANT_SEAL)
    admission.tickets["second"] = second_grant
    with pytest.raises(LocalDeviceFailure):
        coordinator.reserve_focus("second", budget=LocalVerifyBudget(2000))


def test_dedicated_legacy_owner_maintenance_requires_current_main_reference():
    coordinator, _admission, provider, _budget, _first, main, _now = main_setup()
    coordinator.sweep()
    assert provider.main.renewals == [31.0]
    coordinator.detach(main.id, budget=LocalVerifyBudget(2000))
    coordinator.sweep()
    assert provider.main.renewals == [31.0]


def test_waiting_follower_deadline_preserves_running_creator():
    coordinator, _admission, provider, budget, first = setup()
    with ThreadPoolExecutor(1) as pool:
        creator = pool.submit(coordinator._master, first, LocalVerifyBudget(2000))
        assert provider.prepared.entered.wait(1)
        try:
            with pytest.raises(LocalDeviceFailure) as error:
                coordinator._master(first, LocalVerifyBudget(20))
            assert error.value.code == "LOCAL_DEVICE_DEADLINE_EXCEEDED"
            assert provider.calls == len(budget.reservations) == 1
            assert not provider.prepared.closing
        finally:
            provider.prepared.release.set()
        original = creator.result()
    assert coordinator._master(first, LocalVerifyBudget(1000)) is original


@pytest.mark.parametrize("purpose", ["transport", "parked_slot"])
def test_sweep_defers_superseded_heartbeat_observation(purpose):
    coordinator, admission, provider, _budget, first, second, _a, _b = attached_pair()
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    method = "current_transport" if purpose == "transport" else "current_slot"
    original = getattr(admission, method)
    injected = False

    def observed(grant):
        nonlocal injected
        if not injected:
            injected = True
            coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(2000))
            return False  # This exact old object was superseded by SQL.
        return original(grant)

    setattr(admission, method, observed)
    coordinator.sweep()
    assert coordinator.current(second.id)
    assert not provider.prepared.closing


@pytest.mark.parametrize("boundary", ["shared_start", "shared_activate", "main_start"])
@pytest.mark.parametrize("stop", [False, True])
def test_pending_start_monitor_does_not_cancel_but_explicit_stop_does(boundary, stop):
    if boundary == "main_start":
        coordinator, admission, provider, _budget, first, _handle, _grant, _now = (
            forward_setup()
        )
        coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
        lease = replace(first, id=uuid4(), native_generation=uuid4(), token="d" * 64)
        admission.channels[lease.id] = replace(
            admission.channels[first.id], stream="main"
        )
        prepare = provider.prepare_dedicated

        def prepared(*args):
            main = prepare(*args)
            start = main.start

            def start_with_tick(*args, **kwargs):
                coordinator.detach(
                    lease.id, budget=LocalVerifyBudget(2000)
                ) if stop else coordinator.sweep()
                return start(*args, **kwargs)

            main.start = start_with_tick
            return main

        provider.prepare_dedicated = prepared
        operation = coordinator.attach_dedicated
    else:
        coordinator, admission, provider, _budget, lease = setup()
        provider.prepared.release.set()
        operation = coordinator.attach

        def tick():
            coordinator.detach(
                lease.id, budget=LocalVerifyBudget(2000)
            ) if stop else coordinator.sweep()

        if boundary == "shared_activate":
            activate = admission.activate_viewer

            def activate_with_tick(*args, **kwargs):
                tick()
                return activate(*args, **kwargs)

            admission.activate_viewer = activate_with_tick
        else:
            prepare = provider.prepared.prepare_viewer

            def prepared(grant):
                handle = prepare(grant)
                start = handle.start

                def start_with_tick(*args, **kwargs):
                    tick()
                    return start(*args, **kwargs)

                handle.start = start_with_tick
                return handle

            provider.prepared.prepare_viewer = prepared
    if stop:
        with pytest.raises(LocalDeviceFailure):
            operation(lease, budget=LocalVerifyBudget(2000))
        assert not coordinator.current(lease.id)
    else:
        operation(lease, budget=LocalVerifyBudget(2000))
        assert coordinator.current(lease.id)


@pytest.mark.parametrize("kind", ["shared", "dedicated", "original"])
def test_provider_identity_getters_never_execute_under_registry_lock(kind):
    watched = []
    if kind == "dedicated":
        coordinator, _admission, provider, _budget, _first, lease, _now = main_setup()

        class GuardedMain(Main):
            @property
            def native_issuer(self):
                watched.append(coordinator._lock._is_owned())
                return self.__dict__["native_issuer"]

            @property
            def viewer_issuer(self):
                watched.append(coordinator._lock._is_owned())
                return self.__dict__["viewer_issuer"]

        provider.main.__class__ = GuardedMain
        assert coordinator.current(lease.id)
    else:
        coordinator, admission, provider, _budget, lease, _second, handle, _b = (
            attached_pair()
        )
        if kind == "shared":

            class GuardedViewer(Viewer):
                @property
                def registration(self):
                    watched.append(coordinator._lock._is_owned())
                    return self.__dict__["registration"]

                @property
                def cut(self):
                    watched.append(coordinator._lock._is_owned())
                    return self.__dict__["cut"]

            handle.__class__ = GuardedViewer
            executor = service().MuxMediaExecutor(
                admission, coordinator, monitor_interval=0
            )
            executor.mux_binding(lease.id)
        else:

            class GuardedOriginal(Prepared):
                def __getattribute__(self, name):
                    if name in {"binding_for", "issued_receipt"}:
                        watched.append(coordinator._lock._is_owned())
                    return super().__getattribute__(name)

            provider.prepared.__class__ = GuardedOriginal
            assert coordinator.current(lease.id)
    assert watched and not any(watched)


@pytest.mark.parametrize(
    "fault", ["void", "expired_ack", "expired_observation", "target_stop", "cancelled"]
)
def test_focus_transfer_requires_authoritative_ack_and_postcallback_state(fault):
    coordinator, admission, _provider, _budget, first, _handle, grant, now = (
        forward_setup()
    )
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    main = replace(first, id=uuid4(), native_generation=uuid4(), token="d" * 64)
    admission.channels[main.id] = replace(admission.channels[first.id], stream="main")
    settle, observe = admission.settle_focus, admission.focus_settlement_current

    def settlement(value, transition, *, viewer=None):
        if transition != "ATTACHED":
            return settle(value, transition, viewer=viewer)
        if fault == "void":
            return None
        ack = settle(value, transition, viewer=viewer)
        if fault == "expired_ack":
            now[0] = 21.0
        if fault == "cancelled":
            coordinator.settle_focus(grant, "CANCELLED", viewer_id=None)
        return ack

    def observed(value, ack, transition, *, viewer=None):
        result = observe(value, ack, transition, viewer=viewer)
        if transition == "ATTACHED":
            if fault == "expired_observation":
                now[0] = 21.0
            if fault == "target_stop":
                coordinator.detach(main.id, budget=LocalVerifyBudget(2000))
        return result

    admission.settle_focus, admission.focus_settlement_current = settlement, observed
    with pytest.raises(LocalDeviceFailure):
        coordinator.attach_dedicated(main, budget=LocalVerifyBudget(2000))
    assert not coordinator.current(main.id)
    assert main.id not in coordinator._main_refs


def test_return_expiry_during_settlement_cannot_publish_returned_sub():
    coordinator, admission, provider, _budget, first, main, now = main_setup()
    grant = FocusGrant(
        scope=admission.scope,
        lease_id=main.id,
        direction="RETURN",
        admitted_monotonic=2.0,
        expires_monotonic=22.0,
        _authority=object(),
        _seal=_GRANT_SEAL,
    )
    admission.tickets["return"] = grant
    coordinator.reserve_focus("return", budget=LocalVerifyBudget(2000))
    provider.main.can_close = True
    coordinator.detach(main.id, budget=LocalVerifyBudget(2000))
    sub = replace(first, id=uuid4(), token="e" * 64)
    admission.channels[sub.id] = admission.channels[first.id]
    original = admission.settle_focus

    def settlement(value, transition, *, viewer=None):
        ack = original(value, transition, viewer=viewer)
        if transition == "ATTACHED":
            now[0] = 22.0
        return ack

    admission.settle_focus = settlement
    with pytest.raises(LocalDeviceFailure):
        coordinator.attach(sub, budget=LocalVerifyBudget(2000))
    assert not coordinator.current(sub.id)


def test_main_active_requires_still_current_authoritative_ack():
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    prior = admission.focus_settled[-1][0]
    del admission.focus_acknowledgements[id(prior)]
    assert admission.current(main)  # Ordinary lease current does not imply MAIN_ACTIVE.
    assert not coordinator.current(main.id)


def test_return_consumed_main_ack_uses_exact_pending_return_authority():
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    prior = admission.focus_settled[-1][0]
    del admission.focus_acknowledgements[id(prior)]
    grant = FocusGrant(
        scope=admission.scope,
        lease_id=main.id,
        direction="RETURN",
        admitted_monotonic=2.0,
        expires_monotonic=22.0,
        _authority=object(),
        _seal=_GRANT_SEAL,
    )
    admission.tickets["return"] = grant
    assert coordinator.reserve_focus("return", budget=LocalVerifyBudget(2000)) is grant
    assert coordinator.current(main.id)


@pytest.mark.parametrize("fault", ["cancel", "deadline", "revoke"])
@pytest.mark.parametrize("dedicated", [False, True])
def test_pending_monitor_still_enforces_real_cancellation_deadline_and_revocation(
    fault, dedicated
):
    now = [1.0]
    caller = LocalVerifyBudget(1000, clock=lambda: now[0])
    if dedicated:
        coordinator, admission, provider, _budget, first, _handle, _grant, _clock = (
            forward_setup()
        )
        coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
        lease = replace(first, id=uuid4(), native_generation=uuid4(), token="d" * 64)
        admission.channels[lease.id] = replace(
            admission.channels[first.id], stream="main"
        )
        original = provider.prepare_dedicated
        destination, name = provider, "prepare_dedicated"
        operation = coordinator.attach_dedicated
    else:
        coordinator, admission, provider, _budget, lease = setup()
        provider.prepared.release.set()
        original = provider.prepared.prepare_viewer
        destination, name = provider.prepared, "prepare_viewer"
        operation = coordinator.attach

    def prepared(*args):
        owner = original(*args)
        start = owner.start

        def interrupted(*args, **kwargs):
            if fault == "cancel":
                caller.cancel.set()
            elif fault == "deadline":
                now[0] = 2.0
            else:
                admission.denied = True
            coordinator.sweep()
            return start(*args, **kwargs)

        owner.start = interrupted
        return owner

    setattr(destination, name, prepared)
    with pytest.raises(LocalDeviceFailure):
        operation(lease, budget=caller)
    assert not coordinator.current(lease.id)


@pytest.mark.parametrize("dedicated", [False, True])
def test_identity_getter_reentrant_stop_is_seen_after_callback(dedicated):
    triggered = False
    if dedicated:
        coordinator, _admission, provider, _budget, _first, lease, _now = main_setup()

        class ReentrantMain(Main):
            @property
            def native_issuer(self):
                nonlocal triggered
                assert not coordinator._lock._is_owned()
                if not triggered:
                    triggered = True
                    coordinator.detach(lease.id, budget=LocalVerifyBudget(2000))
                return self.__dict__["native_issuer"]

        provider.main.__class__ = ReentrantMain
    else:
        coordinator, _admission, _provider, _budget, lease, _second, handle, _b = (
            attached_pair()
        )

        class ReentrantViewer(Viewer):
            @property
            def cut(self):
                nonlocal triggered
                assert not coordinator._lock._is_owned()
                if not triggered:
                    triggered = True
                    coordinator.detach(lease.id, budget=LocalVerifyBudget(2000))
                return self.__dict__["cut"]

        handle.__class__ = ReentrantViewer
    assert not coordinator.current(lease.id)
    assert triggered


def test_cancelled_reserve_after_local_retention_removes_only_acknowledged_reference():
    coordinator, admission, provider, _budget, first, _handle, prior, _now = (
        forward_setup()
    )
    coordinator.settle_focus(prior, "CANCELLED", viewer_id=None)
    grant = replace(prior, _seal=_GRANT_SEAL)
    admission.tickets["cancelled"] = grant
    caller = LocalVerifyBudget(2000)
    redeem = admission.redeem_focus

    def cancelled(*args, **kwargs):
        result = redeem(*args, **kwargs)
        caller.cancel.set()
        return result

    admission.redeem_focus = cancelled
    with pytest.raises(LocalDeviceFailure):
        coordinator.reserve_focus("cancelled", budget=caller)
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    assert provider.prepared.closing
    assert id(grant) not in coordinator._focus


def test_pending_monitor_uses_active_lifetime_after_constructor_completes():
    coordinator, admission, provider, _budget, lease = setup()
    provider.prepared.release.set()
    now = [1.0]
    startup_entered, startup_release, observer_entered, observer_release = (
        Event(),
        Event(),
        Event(),
        Event(),
    )
    prepare = provider.prepared.prepare_viewer

    def prepared(grant):
        handle = prepare(grant)
        start = handle.start

        def held(*args, **kwargs):
            startup_entered.set()
            assert startup_release.wait(2)
            return start(*args, **kwargs)

        handle.start = held
        return handle

    provider.prepared.prepare_viewer = prepared
    observe = admission.current_viewer
    injected = False

    def observed(grant):
        nonlocal injected
        if not injected:
            injected = True
            observer_entered.set()
            assert observer_release.wait(2)
        return observe(grant)

    with ThreadPoolExecutor(2) as pool:
        startup = pool.submit(
            coordinator.attach,
            lease,
            budget=LocalVerifyBudget(1000, clock=lambda: now[0]),
        )
        assert startup_entered.wait(1)
        admission.current_viewer = observed
        sweep = pool.submit(coordinator.sweep)
        assert observer_entered.wait(1)
        try:
            startup_release.set()
            startup.result(timeout=1)
            now[0] = 2.1
        finally:
            observer_release.set()
            startup_release.set()
        sweep.result(timeout=1)
    assert coordinator.current(lease.id)


@pytest.mark.parametrize("boundary", ["after_sql", "ack_observer"])
@pytest.mark.parametrize(
    "fault", [None, "stop", "revoke", "caller_expiry", "focus_expiry"]
)
def test_focus_settlement_phase_preserves_valid_start_and_real_denials(boundary, fault):
    coordinator, admission, provider, _budget, first, _handle, _grant, now = (
        forward_setup()
    )
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    main = replace(first, id=uuid4(), native_generation=uuid4(), token="d" * 64)
    admission.channels[main.id] = replace(admission.channels[first.id], stream="main")
    caller = LocalVerifyBudget(2000, clock=lambda: now[0])
    injected = False

    def tick():
        nonlocal injected
        if injected:
            return
        injected = True
        if fault == "stop":
            coordinator.detach(main.id, budget=LocalVerifyBudget(2000))
        elif fault == "revoke":
            admission.denied = True
        elif fault == "caller_expiry":
            now[0] = 3.0
        elif fault == "focus_expiry":
            now[0] = 21.0
        coordinator.sweep()

    if boundary == "after_sql":
        original = admission.settle_focus

        def settled(grant, transition, *, viewer=None):
            ack = original(grant, transition, viewer=viewer)
            if transition == "ATTACHED":
                tick()
            return ack

        admission.settle_focus = settled
    else:
        original = admission.focus_settlement_current

        def observed(grant, ack, transition, *, viewer=None):
            result = original(grant, ack, transition, viewer=viewer)
            if transition == "ATTACHED":
                tick()
            return result

        admission.focus_settlement_current = observed
    if fault is None:
        coordinator.attach_dedicated(main, budget=caller)
        assert coordinator.current(main.id)
        assert not provider.prepared.closing
    else:
        with pytest.raises(LocalDeviceFailure):
            coordinator.attach_dedicated(main, budget=caller)
        assert not coordinator.current(main.id)
    assert injected


def test_old_pending_observer_finishes_after_ack_publication_without_cancelling_start():
    coordinator, admission, provider, _budget, first, _handle, _grant, _now = (
        forward_setup()
    )
    coordinator.detach(first.id, budget=LocalVerifyBudget(2000))
    main = replace(first, id=uuid4(), native_generation=uuid4(), token="d" * 64)
    admission.channels[main.id] = replace(admission.channels[first.id], stream="main")
    startup_entered, startup_release = Event(), Event()
    observer_entered, observer_release = Event(), Event()
    published, publish_release = Event(), Event()
    prepare = provider.prepare_dedicated

    def prepared(*args):
        owner = prepare(*args)
        start = owner.start

        def held(*args, **kwargs):
            startup_entered.set()
            assert startup_release.wait(2)
            return start(*args, **kwargs)

        owner.start = held
        return owner

    provider.prepare_dedicated = prepared
    current = admission.current

    def after_publish(lease):
        if lease.id == main.id and main.id in coordinator._main_refs:
            published.set()
            assert publish_release.wait(2)
        return current(lease)

    admission.current = after_publish
    original = admission.current_focus
    injected = False

    def observed(grant):
        nonlocal injected
        if not injected:
            injected = True
            observer_entered.set()
            assert observer_release.wait(2)
        return original(grant)

    with ThreadPoolExecutor(2) as pool:
        startup = pool.submit(
            coordinator.attach_dedicated, main, budget=LocalVerifyBudget(2000)
        )
        assert startup_entered.wait(1)
        admission.current_focus = observed
        sweep = pool.submit(coordinator.sweep)
        assert observer_entered.wait(1)
        try:
            startup_release.set()
            assert published.wait(1)
            observer_release.set()
            sweep.result(timeout=1)
            assert not coordinator._dedicated[main.id].stopping
        finally:
            startup_release.set()
            observer_release.set()
            publish_release.set()
        startup.result(timeout=1)
    assert coordinator.current(main.id)


class RecoveryAdmission(Admission):
    """Inert exact issuer ports; native proof comes from the actual empty owner."""

    def __init__(self):
        super().__init__()
        self.results = {}
        self.after_reserve = lambda: None
        self.lost = False
        self.absent = False
        self.unknown = False
        self.local_closure_ready = True
        self.local_closures = {}
        self.claims = {}
        self.master_closures = {}
        self.followers_closed = []
        self.originals = {}

    def reserve_master(self, viewer, *, budget, attempt=None):
        assert attempt is not None, "explicit original attempt must precede SQL"
        assert self.attempts[id(attempt)] == (attempt, viewer)
        if self.absent:
            self.results[id(attempt)] = None
            raise LocalDeviceFailure()
        result = super().reserve_master(viewer, budget=budget, attempt=attempt)
        self.results[id(attempt)] = result
        self.after_reserve()
        if self.lost:
            raise LocalDeviceFailure()
        return result

    def resolve_master_attempt(self, attempt, *, budget):
        from wso_core.tvt.local_media_mux_admission import MasterAttemptResolution

        if self.unknown or id(attempt) not in self.results:
            return None
        if not hasattr(self, "resolutions"):
            self.resolutions = {}
        if id(attempt) not in self.resolutions:
            result = self.results[id(attempt)]
            self.resolutions[id(attempt)] = MasterAttemptResolution(
                "ABSENT" if result is None else "RESERVED", result, attempt._authority
            )
        return self.resolutions[id(attempt)]

    def master_resolution_current(self, attempt, resolution):
        return (
            self.attempts[id(attempt)][0] is attempt
            and self.resolutions.get(id(attempt)) is resolution
        )

    def finish_absent_attempt(self, attempt, resolution, *, budget):
        from wso_core.tvt.local_media_mux_admission import UnadoptedViewerClosure

        assert self.master_resolution_current(attempt, resolution)
        if not self.local_closure_ready:
            raise LocalDeviceFailure()
        self.local_closures.setdefault(
            id(attempt),
            UnadoptedViewerClosure(
                None, self.attempts[id(attempt)][1].id, attempt._authority
            ),
        )
        return self.local_closures[id(attempt)]

    def absent_attempt_closed(self, attempt, resolution, closure):
        return (
            self.master_resolution_current(attempt, resolution)
            and self.local_closures.get(id(attempt)) is closure
        )

    def claim_unstarted_master(self, reservation):
        from wso_core.tvt.local_media_mux_admission import UnstartedMasterClaim

        assert reservation is self.reservation and reservation.creator
        assert not self.login_calls and not self.viewers and not self.slots
        self.claims.setdefault(
            id(reservation), UnstartedMasterClaim(reservation, object())
        )
        return self.claims[id(reservation)]

    def register_unstarted_original(self, claim, issuer, custody):
        assert self.claims[id(claim.reservation)] is claim
        assert issuer is custody
        previous = self.originals.setdefault(id(claim), issuer)
        assert previous is issuer

    def finish_unstarted_master(self, claim, receipt, *, budget):
        from wso_core.tvt.local_media_mux_admission import UnstartedMasterClosure

        original = self.originals[id(claim)]
        assert original.issued_receipt() is receipt
        assert receipt.original_state == "NOT_CREATED"
        if not self.local_closure_ready:
            raise LocalDeviceFailure()
        leases = tuple(v.id for _, v in self.attempts.values())
        self.master_closures.setdefault(
            id(claim),
            UnstartedMasterClosure(claim.reservation.master_id, leases, object()),
        )
        return self.master_closures[id(claim)]

    def unstarted_master_closed(self, claim, closure):
        return (
            self.claims[id(claim.reservation)] is claim
            and self.master_closures.get(id(claim)) is closure
        )

    def finish_unadopted_follower(self, viewer, reservation, *, budget):
        from wso_core.tvt.local_media_mux_admission import UnadoptedViewerClosure

        assert not reservation.creator
        assert any(
            v is viewer and self.results.get(key) is reservation
            for key, (_, v) in self.attempts.items()
        )
        closure = UnadoptedViewerClosure(reservation.master_id, viewer.id, object())
        self.followers_closed.append((viewer, reservation, closure))
        return closure

    def unadopted_viewer_closed(self, viewer, reservation, closure):
        return any(
            v is viewer and r is reservation and c is closure
            for v, r, c in self.followers_closed
        )


def recovery_setup(monkeypatch):
    from wso_tvt_bridge import windows_socket as windows
    from wso_tvt_bridge.local_live_mux_ownership import MuxOriginalBudget
    from wso_tvt_bridge.local_live_mux_provider import (
        NativeLocalMuxProvider,
        OriginalRecorderMaster,
    )

    def no_start(*args, **kwargs):
        raise AssertionError("recovery must never invoke native startup")

    monkeypatch.setattr(OriginalRecorderMaster, "start", no_start)
    monkeypatch.setattr(windows, "PENDING_OWNERS", [])
    admission = RecoveryAdmission()
    budget = MuxOriginalBudget(worker_epoch=admission.scope.worker_epoch)
    provider = NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=admission
    )
    coordinator = service().DeviceEpochCoordinator(admission, provider, budget)
    lease = LocalMediaLease(
        "a" * 64, admission.scope.worker_epoch, uuid4(), uuid4(), _SEAL
    )
    return coordinator, admission, provider, budget, lease, windows


def test_recovery_known_unstarted_uses_actual_empty_original_and_not_created(
    monkeypatch,
):
    coordinator, admission, _provider, budget, lease, windows = recovery_setup(
        monkeypatch
    )
    admission.after_reserve = lambda: coordinator.stop_wall(
        admission.scope.wall_id, budget=LocalVerifyBudget(1000)
    )
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    assert coordinator.shutdown()
    assert admission.login_calls == admission.activate_calls == 0
    assert len(admission.originals) == 1
    original = next(iter(admission.originals.values()))
    assert original.owner.child is original.owner.job is original.owner.writer is None
    assert original.issued_receipt().original_state == "NOT_CREATED"
    assert not budget._reservations and not windows.pending_owner_snapshot()


def test_recovery_absent_requires_separate_local_closure_and_original_admission(
    monkeypatch,
):
    coordinator, admission, _provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    admission.absent, admission.local_closure_ready = True, False
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    assert coordinator._pending_reservations == 1
    coordinator.admission = Admission()
    assert coordinator.shutdown() is False
    assert coordinator._pending_reservations == 1
    admission.local_closure_ready = True
    assert coordinator.shutdown()
    assert coordinator._pending_reservations == 0 and not budget._reservations


def test_recovery_lost_commit_stays_charged_until_exact_resolution(monkeypatch):
    coordinator, admission, _provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    admission.lost, admission.unknown = True, True
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    assert coordinator.shutdown() is False
    assert coordinator._pending_reservations == 1
    admission.unknown = False
    assert coordinator.shutdown()
    assert not coordinator._unadopted_reservations and not budget._reservations


def test_binding_proof_accepts_initial_identity_without_fabricating_delivery():
    coordinator, admission, _provider, _budget, lease, _second, handle, _b = (
        attached_pair()
    )
    initial = LocalLiveProof(True, True, True, True, True)
    handle.proof = initial
    executor = service().MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    assert executor.binding_proof(lease.id) is initial
    assert (
        not initial.codec_supported
        and not initial.framing_verified
        and not initial.timing_verified
    )
    with pytest.raises(LocalDeviceFailure):
        executor.proof(lease.id)


@pytest.mark.parametrize("change", ["stop", "substitute"])
def test_binding_proof_rechecks_exact_owner_after_provider_property(change):
    coordinator, admission, _provider, _budget, lease, _second, handle, other = (
        attached_pair()
    )
    initial = LocalLiveProof(True, True, True, True, True)

    class Changed(Viewer):
        @property
        def proof(self):
            assert not coordinator._lock._is_owned()
            if change == "stop":
                coordinator.detach(lease.id, budget=LocalVerifyBudget(1000))
            else:
                coordinator._viewers[lease.id].handle = other
            return initial

    handle.__class__ = Changed
    executor = service().MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    with pytest.raises(LocalDeviceFailure):
        executor.binding_proof(lease.id)


def test_recovery_partial_sql_closure_retries_same_expired_empty_original(monkeypatch):
    coordinator, admission, _provider, budget, lease, windows = recovery_setup(
        monkeypatch
    )
    admission.transport = replace(
        admission.transport, expires_monotonic=0.5, _seal=_GRANT_SEAL
    )
    admission.reservation = replace(
        admission.reservation,
        transport=admission.transport,
        deadline_monotonic=0.5,
        _seal=_GRANT_SEAL,
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    admission.local_closure_ready = False
    assert coordinator.shutdown() is False
    original = next(iter(admission.originals.values()))
    receipt = original.issued_receipt()
    assert receipt.original_state == "NOT_CREATED" and len(budget._reservations) == 1
    admission.local_closure_ready = True
    assert coordinator.shutdown()
    assert next(iter(admission.originals.values())) is original
    assert original.issued_receipt() is receipt and not windows.pending_owner_snapshot()


def test_recovery_late_reserve_callback_keeps_charge_until_original_returns(
    monkeypatch,
):
    coordinator, admission, _provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    entered, release = Event(), Event()

    def blocked():
        entered.set()
        assert release.wait(2)

    admission.after_reserve = blocked
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(coordinator._master, lease, LocalVerifyBudget(2000))
        assert entered.wait(1)
        try:
            assert not coordinator.shutdown()
            assert coordinator._pending_reservations == 1 and not budget._reservations
        finally:
            release.set()
        with pytest.raises(LocalDeviceFailure):
            future.result()
    assert coordinator.shutdown()
    assert len(admission.originals) == 1


def test_recovery_two_unadopted_followers_share_the_creators_empty_original(
    monkeypatch,
):
    coordinator, admission, _provider, budget, first, _windows = recovery_setup(
        monkeypatch
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    for index in range(3):
        lease = (
            first if index == 0 else replace(first, id=uuid4(), token=f"{index:064x}")
        )
        with pytest.raises(LocalDeviceFailure):
            coordinator._master(lease, LocalVerifyBudget(1000))
    assert len(coordinator._unadopted_reservations) == 3
    assert coordinator.shutdown()
    assert len(admission.originals) == 1 and not budget._reservations


def test_recovery_followers_close_exact_local_pairs_without_stopping_live_creator():
    admission = RecoveryAdmission()
    provider, budget = Provider(admission), Budget(admission.scope.worker_epoch)
    coordinator = service().DeviceEpochCoordinator(admission, provider, budget)
    keeper = LocalMediaLease(
        "a" * 64, admission.scope.worker_epoch, uuid4(), uuid4(), _SEAL
    )
    provider.prepared.release.set()
    coordinator.attach(keeper, budget=LocalVerifyBudget(1000))
    actor = coordinator._actor
    followers = []
    for index in range(2):
        lease = replace(keeper, id=uuid4(), token=f"{index + 2:064x}")
        coordinator._actor = (*actor[:4], uuid4(), actor[5])
        try:
            with pytest.raises(LocalDeviceFailure):
                coordinator._master(lease, LocalVerifyBudget(1000))
        finally:
            coordinator._actor = actor
        followers.append(lease)
    assert coordinator.recover_reservations(budget=LocalVerifyBudget(1000))
    assert [v for v, _, _ in admission.followers_closed] == followers
    assert coordinator.current(keeper.id) and not provider.prepared.closing
    assert provider.calls == len(budget.reservations) == 1


def test_recovery_reentrant_shutdown_cannot_prepare_a_second_original(monkeypatch):
    coordinator, admission, provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    prepare = provider.prepare_master
    calls = []

    def reentrant(*args):
        calls.append(args)
        assert coordinator.shutdown() is False
        return prepare(*args)

    provider.prepare_master = reentrant
    assert coordinator.shutdown()
    assert len(calls) == 1 and not budget._reservations


def test_recovery_changed_native_issuer_stays_charged_until_exact_owner_restored(
    monkeypatch,
):
    coordinator, admission, _provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    register = admission.register_unstarted_original
    retained = []

    def substituted(claim, issuer, custody):
        register(claim, issuer, custody)
        method = issuer.issued_receipt
        retained.append((issuer, method))
        issuer.issued_receipt = lambda: method()

    admission.register_unstarted_original = substituted
    assert not coordinator.shutdown()
    assert len(budget._reservations) == 1 and not admission.master_closures
    issuer, original = retained[0]
    issuer.issued_receipt = original
    admission.register_unstarted_original = register
    assert coordinator.shutdown()


def test_recovery_copied_sql_closure_cannot_release_original_and_genuine_retry_can(
    monkeypatch,
):
    coordinator, admission, _provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    finish = admission.finish_unstarted_master

    def copied(*args, **kwargs):
        return replace(finish(*args, **kwargs))

    admission.finish_unstarted_master = copied
    assert not coordinator.shutdown()
    assert len(budget._reservations) == 1
    admission.finish_unstarted_master = finish
    assert coordinator.shutdown()


@pytest.mark.parametrize("cause", ["copy", "login", "slot", "viewer"])
def test_recovery_denied_claim_never_prepares_an_empty_replacement(monkeypatch, cause):
    coordinator, admission, _provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    if cause == "copy":
        reserve = admission.reserve_master

        def copied(*args, **kwargs):
            return replace(reserve(*args, **kwargs), _seal=_GRANT_SEAL)

        admission.reserve_master = copied
    elif cause == "login":
        admission.login_calls = 1
    elif cause == "slot":
        admission.slots[b"registered"] = object()
    else:
        admission.viewers[uuid4()] = object()
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    assert coordinator.shutdown() is False
    assert not budget._reservations and not admission.originals
    assert len(coordinator._unadopted_reservations) == 1


def test_recovery_registration_failure_retries_same_prepared_original(monkeypatch):
    coordinator, admission, _provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    register = admission.register_unstarted_original
    admission.register_unstarted_original = lambda *args: (_ for _ in ()).throw(
        LocalDeviceFailure()
    )
    assert not coordinator.shutdown()
    recovery = next(iter(coordinator._unstarted_recovery.values()))
    original = recovery.prepared
    assert original.issued_receipt().original_state == "NOT_CREATED"
    assert len(budget._reservations) == 1
    admission.register_unstarted_original = register
    assert coordinator.shutdown()
    assert next(iter(admission.originals.values())) is original


def test_recovery_sql_closed_stays_charged_until_exact_budget_release(monkeypatch):
    coordinator, admission, _provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    release = budget.release_confirmed
    budget.release_confirmed = lambda *args: (_ for _ in ()).throw(LocalDeviceFailure())
    assert not coordinator.shutdown()
    assert len(admission.master_closures) == len(budget._reservations) == 1
    budget.release_confirmed = release
    assert coordinator.shutdown()


def test_recovery_cleanup_cancellation_preserves_ack_for_fresh_budget_retry(
    monkeypatch,
):
    coordinator, admission, _provider, budget, lease, _windows = recovery_setup(
        monkeypatch
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(lease, LocalVerifyBudget(1000))
    caller = LocalVerifyBudget(1000)
    finish = admission.finish_unstarted_master

    def cancelled(*args, **kwargs):
        closure = finish(*args, **kwargs)
        caller.cancel.set()
        return closure

    admission.finish_unstarted_master = cancelled
    assert not coordinator.recover_reservations(budget=caller)
    assert len(budget._reservations) == 1 and len(admission.master_closures) == 1
    assert coordinator.shutdown()


def test_recovery_creator_closure_never_clears_an_unverified_follower_copy(monkeypatch):
    coordinator, admission, _provider, budget, first, _windows = recovery_setup(
        monkeypatch
    )
    coordinator._stopped_walls.add(admission.scope.wall_id)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(first, LocalVerifyBudget(1000))
    original = admission.reserve_master
    copies = []

    def copied(*args, **kwargs):
        result = replace(original(*args, **kwargs), _seal=_GRANT_SEAL)
        copies.append(result)
        return result

    admission.reserve_master = copied
    follower = replace(first, id=uuid4(), token="b" * 64)
    with pytest.raises(LocalDeviceFailure):
        coordinator._master(follower, LocalVerifyBudget(1000))
    assert not coordinator.shutdown()
    assert coordinator._unadopted_reservations[id(copies[0])] is copies[0]
    assert len(admission.originals) == 1 and not budget._reservations
