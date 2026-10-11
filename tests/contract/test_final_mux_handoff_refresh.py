"""Final composition regressions. Synthetic custody only; no native/SQL IO."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, RLock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_local_live_mux_provider import viewer_rig
from wso_core.tvt.local_media_mux_service import MuxMediaExecutor
from wso_core.tvt.local_media_mux_types import MuxEpochIdentity, MuxPurpose
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget
from wso_tvt_bridge.local_live_mux_ipc import MuxIpcError
from wso_tvt_bridge.windows_socket import ProviderError
from wso_tvt_media import native_source, worker
from wso_tvt_media.mux_budget import MediaCreditLedger
from wso_tvt_media.mux_source import MuxSourceFactory

from tests.tvt_parity.test_local_media_mux_service import attached_pair, setup
from tests.tvt_parity.test_local_media_source import open_source
from tests.tvt_parity.test_local_media_worker import Core, settle


@pytest.mark.parametrize("boundary", ["before_hook", "after_hook", "before_prepare"])
def test_i1_shutdown_at_executor_handoff_retires_same_started_viewer(boundary):
    viewer, master, _, _ = viewer_rig(started=False)
    lease_id = viewer.current_grant().lease_id
    lease = SimpleNamespace(id=lease_id)
    view = Core().view.model_copy(update={"id": lease_id})
    owned = SimpleNamespace(
        lease=lease,
        handle=viewer,
        grant=viewer.current_grant(),
        stopping=False,
        starting=False,
        view=view,
    )
    coordinator = SimpleNamespace(
        _lock=RLock(),
        _viewers={lease_id: owned},
        _dedicated={},
        current=lambda ident: ident in coordinator._viewers and not owned.stopping,
    )

    def attach(*args, **kwargs):
        if boundary == "before_hook":
            owner._stopping.set()
        retain = kwargs.get("retain_local")
        if retain is not None:
            viewer.attach_retirement(retain(lease_id, viewer.registration))
        if boundary == "after_hook":
            owner._stopping.set()
        viewer.start(budget=kwargs["budget"])
        # Native viewer has started. Ordinary worker shutdown wins at handoff.
        owner._stopping.set()
        return viewer

    def close(original):
        original.stopping = True
        if viewer.close() is None:
            return False
        coordinator._viewers.pop(lease_id, None)
        return True

    coordinator.attach = attach
    coordinator._close_viewer = close
    coordinator.shutdown = lambda: not coordinator._viewers
    admission = SimpleNamespace(
        redeem=lambda *a, **k: lease,
        prepare_viewer=lambda *a, **k: SimpleNamespace(stream="sub"),
        view=lambda _: view,
    )
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    owner = worker.LocalMediaWorker(
        executor,
        decoder_executable=Path(__file__).resolve(),
        source_factory=MuxSourceFactory(executor, MediaCreditLedger()),
    )
    try:
        with pytest.raises(LocalDeviceFailure):
            owner.start("a" * 64, deadline_ms=1000, correlation_id="handoff")
        assert viewer._retirement is not None, "started viewer lost local supplier"
        settle(owner)
        receipt = viewer.issued_receipt()
        assert receipt is not None and viewer.close() is receipt
        assert receipt.lease_id == lease_id
        assert receipt.registration_id == viewer.registration
        assert not master.owner.confirmed
    finally:
        # Failure teardown supplies a genuine known-empty owner solely for this rig.
        if viewer._retirement is None:
            from wso_core.tvt.local_media_mux_types import (
                _CUSTODY_SEAL,
                ViewerCleanupReceipt,
            )

            receipt = ViewerCleanupReceipt(
                lease_id=lease_id,
                registration_id=viewer.registration,
                decoder_settled=True,
                peer_settled=True,
                media_cleared=True,
                _authority=object(),
                _seal=_CUSTODY_SEAL,
            )
            viewer.attach_retirement(lambda: receipt)
            executor.close(lease_id)
        settle(owner)
        master.owner.confirmed = True
        assert master.parent.close()


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("mode", ["legacy", "shared"])
async def test_i2_uncertain_source_start_waits_for_same_late_target_and_join(
    monkeypatch, position, mode
):
    from uuid import uuid4

    originals = []

    class Thread:
        def __init__(self, *, target, **kwargs):
            self.target, self.ident, self.joined = target, None, 0
            self.index = len(originals)
            originals.append(self)

        def start(self):
            if self.index == position:
                raise RuntimeError("interrupted after possible acquisition")

        def is_alive(self):
            return False

        def join(self, *args, **kwargs):
            self.joined += 1

    monkeypatch.setattr(native_source.threading, "Thread", Thread)

    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(worker.asyncio, "to_thread", inline)
    source = open_source(SimpleNamespace())
    if mode == "shared":
        source.registration = uuid4()
        source.frame_source = SimpleNamespace(current=lambda: True)
        source.media_credit = MediaCreditLedger()
    with pytest.raises(RuntimeError):
        source.start()
    owner = object.__new__(worker.LocalMediaWorker)
    owner._loop = asyncio.get_running_loop()
    owner._guard, owner._sources, owner._peers = Lock(), {source.lease_id: source}, {}
    owner._closing, owner._runtime_closed, owner._startups = {}, {}, {}
    owner._quarantined = set()
    owner._source_factory = object() if mode == "shared" else None
    supplier = owner._retain_local(source.lease_id, source.registration or uuid4())
    owner._startups[source.lease_id].prepared.set()
    receipts = []
    owner.executor = SimpleNamespace(
        close=lambda _: receipts.append(supplier()) or True
    )
    closing = asyncio.create_task(owner._close_entry(source.lease_id))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    was_pending = not closing.done() and not source._ended
    assert source.lease_id in owner._sources
    assert source.lease_id in owner._runtime_closed
    assert supplier() is None and not receipts
    for original in originals[: position + 1]:
        original.ident = original.index + 1
        original.target()  # Same late original sees the already-set stop.
    await asyncio.wait_for(closing, 1)
    assert was_pending, "uncertain attempted source was certified empty"
    assert all(t.joined for t in originals[: position + 1])
    assert all(not t.joined for t in originals[position + 1 :])
    assert receipts and receipts[0] is supplier()
    assert not owner._sources and not owner._runtime_closed


@pytest.mark.parametrize("phase", ["attaching", "opening"])
def test_i3_heartbeat_waits_for_healthy_attachment_then_really_renews(phase):
    coordinator, admission, provider, _, first, _, _, _ = attached_pair()
    record = next(iter(coordinator._records.values()))
    setattr(record, phase, 1 if phase == "attaching" else True)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(
            coordinator.heartbeat, "heartbeat", budget=LocalVerifyBudget(1500)
        )
        time.sleep(0.03)  # ordering assertion only
        waited = not future.done()
        assert coordinator.current(first.id)
        setattr(record, phase, 0 if phase == "attaching" else False)
        outcome = None
        try:
            outcome = future.result()
        except LocalDeviceFailure:
            pass
    provider.prepared.can_close = True
    assert coordinator.shutdown()
    assert waited, "healthy construction produced terminal BUSY"
    assert outcome == admission.scope.wall_id and len(admission.refreshes) == 5


def test_i4_native_check_defers_superseded_grant_until_exact_replacement(monkeypatch):
    from wso_tvt_bridge.local_live_mux_ipc import MuxParentAuthority
    from wso_tvt_bridge.local_live_mux_provider import OriginalRecorderMaster

    from tests.integration.test_local_media_mux_admission import unit_transport

    gate, reservation = unit_transport()
    monkeypatch.setattr(
        gate,
        "_observe",
        lambda _: {"expires_at": datetime.now(UTC) + timedelta(seconds=20)},
    )
    master = object.__new__(OriginalRecorderMaster)
    master._lock, master.io_lock = RLock(), RLock()
    master._closed, master._operations = False, set()
    master._transport, master._ready = reservation.transport, False
    master.reservation = reservation
    master.owner = SimpleNamespace(
        child=None,
        confirmed=False,
        kill_attempted=False,
        request_stop=lambda: None,
    )
    master.custodian = SimpleNamespace()
    master.provider = SimpleNamespace(clock=lambda: 1.0, admission=gate)
    parent = MuxParentAuthority(
        epoch=MuxEpochIdentity(1, bytes(range(16))),
        authorize=master._authorize,
        clock=lambda: 1.0,
    )
    parent.deadline = 25.0
    master._parent = parent
    entered, release = Event(), Event()

    def refresh():
        barrier = getattr(master, "refresh_grants", lambda **_: nullcontext())
        with barrier(budget=LocalVerifyBudget(1500)):
            fresh = gate.refresh_grant(reservation.transport)
            entered.set()
            assert release.wait(1)
            with master._lock:
                master._transport = fresh

    with ThreadPoolExecutor(2) as pool:
        renewing = pool.submit(refresh)
        assert entered.wait(1)
        checking = pool.submit(parent._check, MuxPurpose.TRANSPORT)
        time.sleep(0.03)
        waited = not checking.done()
        release.set()
        renewing.result()
        try:
            checking.result()
        except MuxIpcError:
            pass
    gate._engine.dispose()
    assert waited, "native authority crossed immutable replacement gap"
    assert not parent.failed
    assert not gate.current_transport(reservation.transport)


@pytest.mark.parametrize("position", [0, 1, 2])
async def test_i2_proven_unattempted_start_needs_no_target(monkeypatch, position):
    originals = []

    class Thread:
        def __init__(self, *, target, **kwargs):
            self.target, self.ident, self.joined = target, None, 0
            self.index = len(originals)
            originals.append(self)

        @property
        def start(self):
            if self.index == position:
                raise RuntimeError("failure before acquiring start callable")
            return lambda: None

        def is_alive(self):
            return False

        def join(self):
            self.joined += 1

    monkeypatch.setattr(native_source.threading, "Thread", Thread)
    source = open_source(SimpleNamespace())
    with pytest.raises(RuntimeError):
        source.start()
    for original in originals[:position]:
        original.target()
    await asyncio.wait_for(source.close(), 1)
    assert all(t.joined == 1 for t in originals[:position])
    assert all(t.joined == 0 for t in originals[position:])
    assert source._ended


@pytest.mark.parametrize("phase", ["initial", "additional"])
def test_i3_actual_constructor_and_slot_open_share_heartbeat_result(phase):
    coordinator, admission, provider, budget, first = setup()
    entered, release = Event(), Event()
    first_handle = None
    if phase == "initial":
        entered, release = provider.prepared.entered, provider.prepared.release
        opening = first
    else:
        provider.prepared.release.set()
        first_handle = coordinator.attach(first, budget=LocalVerifyBudget(2000))
        opening = replace(first, id=uuid4(), token="b" * 64)
        actual_open = provider.prepared.open_slot

        def held_open(*args, **kwargs):
            entered.set()
            assert release.wait(1)
            return actual_open(*args, **kwargs)

        provider.prepared.open_slot = held_open
    with ThreadPoolExecutor(2) as pool:
        attaching = pool.submit(
            coordinator.attach, opening, budget=LocalVerifyBudget(1500)
        )
        assert entered.wait(1)
        heartbeat = pool.submit(
            coordinator.heartbeat, "heartbeat", budget=LocalVerifyBudget(1500)
        )
        time.sleep(0.03)
        assert not heartbeat.done()
        if first_handle is not None:
            assert first_handle.current() and coordinator.current(first.id)
        release.set()
        handle = attaching.result()
        assert heartbeat.result() == admission.scope.wall_id
        assert coordinator.current(opening.id)
        assert handle is provider.prepared.handles[-1]
        assert provider.calls == 1 and len(budget.reservations) == 1
        assert len(admission.refreshes) == (3 if phase == "initial" else 5)
    provider.prepared.can_close = True
    assert coordinator.shutdown()


@pytest.mark.parametrize("failure", ["deadline", "cancel", "expiry", "denial", "stop"])
def test_i3_blocked_construction_never_reports_renewal(failure):
    coordinator, admission, provider, _, _first, _, _, _ = attached_pair()
    record = next(iter(coordinator._records.values()))
    record.attaching = 1
    cancel = Event()
    deadline = LocalVerifyBudget(100, cancel=cancel)
    with ThreadPoolExecutor(1) as pool:
        heartbeat = pool.submit(coordinator.heartbeat, "heartbeat", budget=deadline)
        time.sleep(0.025)
        if failure == "cancel":
            cancel.set()
        elif failure == "expiry":
            coordinator._clock = lambda: 1e13
        elif failure == "denial":
            admission.refresh_grant = lambda _: (_ for _ in ()).throw(
                LocalDeviceFailure()
            )
            record.attaching = 0
        elif failure == "stop":
            coordinator.stop_wall(
                admission.scope.wall_id, budget=LocalVerifyBudget(1000)
            )
        with pytest.raises(LocalDeviceFailure):
            heartbeat.result()
    record.attaching = 0
    assert not admission.refreshes
    provider.prepared.can_close = True
    assert coordinator.shutdown()


def authority_rig(monkeypatch):
    """Real admission/provider/IPC methods with sealed inert originals and SQL seam."""
    from uuid import uuid4

    from wso_core.tvt.local_media_mux_types import (
        _GRANT_SEAL,
        MuxSlotIdentity,
        SlotRetentionGrant,
        ViewerGrant,
    )
    from wso_core.tvt.local_media_service import LocalLiveProof
    from wso_tvt_bridge.local_live_mux_ipc import MuxParentAuthority
    from wso_tvt_bridge.local_live_mux_provider import (
        MuxSlotViewer,
        OriginalRecorderMaster,
    )

    from tests.integration.test_local_media_mux_admission import unit_transport

    gate, reservation = unit_transport()
    gate._clock = time.monotonic
    transport = gate._remember(
        replace(
            reservation.transport,
            expires_monotonic=time.monotonic() + 30,
            _seal=_GRANT_SEAL,
        ),
        "a" * 64,
        reservation.master_id,
        reservation.transport.native_generation,
    )
    reservation = replace(
        reservation,
        transport=transport,
        deadline_monotonic=transport.expires_monotonic,
        _seal=_GRANT_SEAL,
    )
    gate._masters[reservation.master_id] = reservation
    gate._master_grants[reservation.master_id] = transport
    monkeypatch.setattr(
        gate,
        "_observe",
        lambda _: {"expires_at": datetime.now(UTC) + timedelta(seconds=20)},
    )
    master = object.__new__(OriginalRecorderMaster)
    master._lock, master.io_lock = RLock(), RLock()
    master._closed, master._operations = False, set()
    master._transport, master._ready = reservation.transport, False
    master.reservation = reservation
    master.stops = []
    master.owner = SimpleNamespace(
        child=None,
        confirmed=False,
        kill_attempted=False,
        request_stop=lambda: master.stops.append(True),
    )
    master.custodian = SimpleNamespace()
    master.provider = SimpleNamespace(clock=time.monotonic, admission=gate)
    master._epoch = MuxEpochIdentity(1, uuid4().bytes)
    master.proof = LocalLiveProof(True, True, True, True, True)
    parent = MuxParentAuthority(
        epoch=master._epoch, authorize=master._authorize, clock=time.monotonic
    )
    parent.deadline = time.monotonic() + 25
    parent._owner = master.owner
    master._parent = parent
    slot = MuxSlotIdentity(master._epoch, uuid4().bytes, uuid4().bytes, 2)
    retention = gate._remember(
        SlotRetentionGrant(
            scope=reservation.scope,
            slot=slot,
            expires_monotonic=time.monotonic() + 30,
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "b" * 64,
        reservation.master_id,
        reservation.transport.native_generation,
    )
    grant = gate._remember(
        ViewerGrant(
            scope=reservation.scope,
            slot=slot,
            expires_monotonic=time.monotonic() + 30,
            lease_id=uuid4(),
            registration=uuid4(),
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "c" * 64,
        reservation.master_id,
        reservation.transport.native_generation,
    )
    master._slots = {slot.channel: retention}
    viewer = MuxSlotViewer(master, grant)
    master._viewers = {grant.registration: viewer}
    # Native IPC transport is inert; retain actual IPC purpose validation.
    parent.renew = lambda **_: parent._check(MuxPurpose.TRANSPORT)
    master.heartbeat = lambda _: None
    return gate, master, parent, viewer, (reservation.transport, retention, grant)


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("point", ["before", "after"])
def test_i4_each_original_purpose_waits_through_actual_facade_replacement(
    monkeypatch, index, point
):
    from wso_core.tvt.local_media_mux_types import _GRANT_SEAL

    gate, master, parent, viewer, grants = authority_rig(monkeypatch)
    entered, release = Event(), Event()
    current = (gate.current_transport, gate.current_slot, gate.current_viewer)[index]
    purpose = (MuxPurpose.TRANSPORT, MuxPurpose.SLOT_RETENTION, MuxPurpose.VIEWER)[
        index
    ]
    args = (
        ()
        if index == 0
        else (grants[1].slot,)
        if index == 1
        else (grants[1].slot, viewer.registration)
    )
    fresh = []

    def renew():
        with master.refresh_grants(budget=LocalVerifyBudget(1500)):
            if point == "before":
                entered.set()
                assert release.wait(1)
            replacement = gate.refresh_grant(grants[index])
            fresh.append(replacement)
            if point == "after":
                entered.set()
                assert release.wait(1)
            master.replace_grant(grants[index], replacement)

    with ThreadPoolExecutor(2) as pool:
        refreshing = pool.submit(renew)
        assert entered.wait(1)
        checking = pool.submit(parent._check, purpose, *args)
        time.sleep(0.025)
        assert not checking.done()
        release.set()
        refreshing.result()
        checking.result()
    assert not parent.failed and not master.stops
    assert current(fresh[0])
    assert not current(grants[index])
    assert not current(replace(fresh[0], _seal=_GRANT_SEAL))
    assert not current(replace(fresh[0], _authority=object(), _seal=_GRANT_SEAL))
    parent._check(purpose, *args)
    gate._engine.dispose()


@pytest.mark.parametrize(
    "purpose", [MuxPurpose.TRANSPORT, MuxPurpose.SLOT_RETENTION, MuxPurpose.VIEWER]
)
def test_i4_already_entered_original_check_settles_before_refresh(monkeypatch, purpose):
    gate, master, parent, viewer, grants = authority_rig(monkeypatch)
    entered, release, refreshing = Event(), Event(), Event()
    original = gate._observe

    def observed(record):
        if not entered.is_set():
            entered.set()
            assert release.wait(1)
        return original(record)

    monkeypatch.setattr(gate, "_observe", observed)
    args = (
        ()
        if purpose is MuxPurpose.TRANSPORT
        else (grants[1].slot,)
        if purpose is MuxPurpose.SLOT_RETENTION
        else (grants[1].slot, viewer.registration)
    )

    def renew():
        with master.refresh_grants(budget=LocalVerifyBudget(1500)):
            refreshing.set()
            for old in grants:
                master.replace_grant(old, gate.refresh_grant(old))

    with ThreadPoolExecutor(2) as pool:
        checking = pool.submit(parent._check, purpose, *args)
        assert entered.wait(1)
        heartbeat = pool.submit(renew)
        time.sleep(0.025)
        assert not refreshing.is_set()
        release.set()
        checking.result()
        heartbeat.result()
    assert not parent.failed and not master.stops
    parent._check(purpose, *args)
    gate._engine.dispose()


@pytest.mark.parametrize("failure", ["revocation", "deadline", "cancel", "stop"])
def test_i4_refresh_failure_stays_fenced_before_waiting_check_resumes(
    monkeypatch, failure
):
    gate, master, parent, viewer, grants = authority_rig(monkeypatch)
    entered, release, cancel = Event(), Event(), Event()
    budget = LocalVerifyBudget(1500, cancel=cancel)

    def renew():
        with master.refresh_grants(budget=budget):
            master.replace_grant(grants[0], gate.refresh_grant(grants[0]))
            entered.set()
            assert release.wait(1)
            if failure == "revocation":
                monkeypatch.setattr(gate, "_observe", lambda _: None)
                gate.refresh_grant(grants[1])
            budget.remaining_ms()

    with ThreadPoolExecutor(2) as pool:
        heartbeat = pool.submit(renew)
        assert entered.wait(1)
        checking = pool.submit(
            parent._check, MuxPurpose.VIEWER, grants[1].slot, viewer.registration
        )
        time.sleep(0.025)
        if failure == "cancel":
            cancel.set()
        elif failure == "deadline":
            budget.deadline_monotonic = 0
        elif failure == "stop":
            master._closed = True
            parent._fence()
        release.set()
        with pytest.raises((LocalDeviceFailure, ProviderError)):
            heartbeat.result()
        with pytest.raises(MuxIpcError):
            checking.result()
    assert parent.failed and master.stops
    assert not master.viewer_current(viewer.current_grant())
    gate._engine.dispose()


def test_i1_cancelled_held_preparation_keeps_same_supplier_and_source_charged(
    monkeypatch,
):
    from tests.tvt_parity.test_local_media_worker import Peer, Source

    viewer, master, _, _ = viewer_rig(started=False)
    lease_id = viewer.current_grant().lease_id
    lease = SimpleNamespace(id=lease_id)
    view = Core().view.model_copy(update={"id": lease_id})
    record = SimpleNamespace(
        lease=lease, handle=viewer, grant=viewer.current_grant(), stopping=False
    )
    coordinator = SimpleNamespace(
        _lock=RLock(),
        _viewers={lease_id: record},
        _dedicated={},
        current=lambda ident: ident in coordinator._viewers and not record.stopping,
    )

    def attach(*args, **kwargs):
        viewer.attach_retirement(kwargs["retain_local"](lease_id, viewer.registration))
        viewer.start(budget=kwargs["budget"])
        return viewer

    def close(original):
        original.stopping = True
        if viewer.close() is None:
            return False
        coordinator._viewers.pop(lease_id, None)
        return True

    coordinator.attach, coordinator._close_viewer = attach, close
    coordinator.shutdown = lambda: not coordinator._viewers
    admission = SimpleNamespace(
        redeem=lambda *a, **k: lease,
        prepare_viewer=lambda *a, **k: SimpleNamespace(stream="sub"),
        view=lambda _: view,
    )
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    preparing, prepared, closing, closed, cancel = (Event() for _ in range(5))

    class HeldSource(Source):
        async def close(self):
            closing.set()
            while not closed.is_set():
                await asyncio.sleep(0.005)
            self.closed = True

    original_source = HeldSource()

    class Factory(MuxSourceFactory):
        async def __call__(self, *args, **kwargs):
            preparing.set()
            while not prepared.is_set():
                await asyncio.sleep(0.005)
            return original_source

    monkeypatch.setattr(worker, "LocalWebRtcSession", Peer)
    owner = worker.LocalMediaWorker(
        executor,
        decoder_executable=Path(__file__).resolve(),
        source_factory=Factory(executor, MediaCreditLedger()),
    )
    try:
        with ThreadPoolExecutor(1) as pool:
            starting = pool.submit(
                owner.start,
                "a" * 64,
                deadline_ms=1500,
                correlation_id="held",
                cancel=cancel,
            )
            assert preparing.wait(1)
            supplier = viewer._retirement
            cancel.set()
            with pytest.raises(LocalDeviceFailure):
                starting.result()
            assert not owner.shutdown()
            assert lease_id in owner._runtime_closed and supplier() is None
            assert viewer.close() is None
            prepared.set()
            assert closing.wait(1)
            assert viewer._retirement is supplier and supplier() is None
            assert lease_id in owner._runtime_closed and not original_source.closed
            closed.set()
        settle(owner)
        assert original_source.closed
        assert viewer.issued_receipt() is supplier()
        assert not owner._runtime_closed and not master.owner.confirmed
    finally:
        prepared.set()
        closed.set()
        settle(owner)
        master.owner.confirmed = True
        assert master.parent.close()


@pytest.mark.parametrize("case", ["healthy", "stop", "denial", "copy"])
def test_i4_media_binding_snapshot_spanning_healthy_refresh_does_not_fence(case):
    from wso_core.tvt.local_media_mux_types import _GRANT_SEAL
    from wso_tvt_media.mux_source import MuxFrameSource

    coordinator, admission, provider, _, first, _, handle, _ = attached_pair()
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    original = handle.current_grant
    held = [True]

    def snapshot():
        grant = original()
        if held[0]:
            held[0] = False
            coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(1000))
            if case == "stop":
                coordinator._viewers[first.id].stopping = True
            elif case == "denial":
                admission.denied = True
            elif case == "copy":
                handle.grant = replace(handle.grant, _seal=_GRANT_SEAL)
        return grant

    source = MuxFrameSource(
        handle,
        handle.grant,
        handle.registration,
        handle.cut,
        MediaCreditLedger(),
        binding=lambda: executor.mux_binding(first.id),
    )
    handle.current_grant = snapshot
    try:
        assert source.current() is (case == "healthy")
        if case == "healthy":
            assert source.grant is handle.grant and not source._stopped
        else:
            assert source._stopped and not source.current()
        assert provider.calls == 1
    finally:
        provider.prepared.can_close = True
        assert coordinator.shutdown()
