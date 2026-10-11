"""Owned mux-probe preparation only: fake ports, never DB/native execution."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def probe():
    path = ROOT / "scripts/test-local-devices/mux-probe.py"
    assert path.is_file(), "bounded original mux probe is not implemented"
    spec = importlib.util.spec_from_file_location("fixture_mux_probe", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module._test_observers = []
    yield module
    for observer in module._test_observers:
        observer.close()


@pytest.mark.parametrize(
    "channels,seconds",
    [((1, 1), 120), ((1,), 120), ((1, 2, 3), 120), ((1, 2), 121), ((True, 2), 120)],
)
def test_probe_plan_rejects_duplicate_wrong_count_or_unbounded_live(
    probe, channels, seconds
):
    with pytest.raises(ValueError):
        probe.MuxProbePlan(channels, seconds)


def test_probe_plan_accepts_two_then_four_distinct_bounded_channels(probe):
    assert probe.MuxProbePlan((1, 2), 120).channels == (1, 2)
    assert probe.MuxProbePlan((1, 2, 3, 4), 120).max_seconds == 120


def test_probe_owner_blocks_receipt_for_original_read_and_exact_batch(probe):
    lease, registration = uuid4(), uuid4()
    handle = SimpleNamespace(registration=registration)
    calls = []
    batch = (object(),)
    core = SimpleNamespace(
        attach_retirement=lambda lease, callback: calls.append(callback),
        release_mux_frames=lambda lease, frames: None,
    )
    owner = probe.ProbeViewerOwner(core, lease, registration, handle)
    calls.append(owner.original_retire)
    owner.begin_read()
    assert calls[0]() is None
    owner.returned(batch)
    assert calls[0]() is None
    with pytest.raises(ValueError):
        owner.release((*batch,))
    owner.release(batch)
    receipt = calls[0]()
    assert receipt.registration_id == registration and receipt.lease_id == lease
    assert calls[0]() is receipt


def test_probe_owner_foreign_registration_or_failed_release_never_certifies(probe):
    handle = SimpleNamespace(registration=uuid4())
    calls = []

    def fail(*args):
        raise RuntimeError("private-secret")

    core = SimpleNamespace(
        attach_retirement=lambda lease, callback: calls.append(callback),
        release_mux_frames=fail,
    )
    owner = probe.ProbeViewerOwner(core, uuid4(), handle.registration, handle)
    calls.append(owner.original_retire)
    owner.begin_read()
    batch = (object(),)
    owner.returned(batch)
    with pytest.raises(RuntimeError):
        owner.release(batch)
    assert calls[0]() is None
    handle.registration = uuid4()
    assert calls[0]() is None


def test_probe_ticket_issuance_uses_reviewed_issuer_in_short_transaction(probe):
    from contextlib import contextmanager

    from wso_contracts.tvt.local_media import LocalLiveRequest
    from wso_core.tvt.local_service import LocalVerifyBudget

    active = []
    queries = []

    @contextmanager
    def transaction():
        active.append(True)

        class Session:
            def execute(self, statement, values):
                assert active
                queries.append(str(statement))
                return SimpleNamespace(scalar_one=lambda: "a" * 64)

        try:
            yield Session()
        finally:
            active.pop()

    tickets = probe.SqlProbeTickets(transaction, "b" * 64, uuid4(), uuid4())
    request = LocalLiveRequest(
        store_id=uuid4(),
        device_id=uuid4(),
        channel_id=uuid4(),
        expected_generation=1,
        inventory_revision=1,
        stream="sub",
    )
    assert tickets.start(request, uuid4(), LocalVerifyBudget(1000)) == "a" * 64
    assert not active
    assert any("wso_tvt_local_media_shared_issue" in query for query in queries)


def fake_probe_runtime(probe, *, cleanup=True, channels=(1, 2)):
    import time

    from wso_contracts.tvt.local_media import LocalLiveRequest
    from wso_core.tvt.local_live import LiveIdentity
    from wso_core.tvt.local_media_mux_types import (
        _WIRE_SEAL,
        IngressCut,
        IngressSpan,
        MasterLoginProof,
        MuxEpochIdentity,
        MuxSlotIdentity,
        MuxValidatedFrame,
    )

    from tests.contract import test_local_media_observation as observation_tests
    from tests.tvt_parity.test_local_media_source import PROOF, frame

    clock = [time.monotonic()]
    wall = uuid4()
    events, owners, closed = [], {}, set()
    store, device = uuid4(), uuid4()
    requests = {
        i: LocalLiveRequest(
            store_id=store,
            device_id=device,
            channel_id=uuid4(),
            expected_generation=1,
            inventory_revision=1,
            stream="sub",
        )
        for i in channels
    }
    module = observation_tests.observation.__wrapped__()
    observer = module.MediaObservation(
        lambda value: None, shared=True, clock=lambda: clock[0]
    )
    probe._test_observers.append(observer)
    observer.start()

    class Tickets:
        def wall(self, budget):
            events.append("wall_ticket")
            return wall

        def start(self, request, wall_id, budget):
            assert wall_id == wall
            channel = next(i for i, value in requests.items() if value is request)
            events.append(("start_ticket", channel))
            return str(channel)

        def control(self, wall_id, purpose, budget):
            events.append(("control_ticket", purpose))
            return purpose

        def state(self, wall_id, budget):
            return "CLOSED" if cleanup else "STOPPING"

    class Master:
        def __init__(self):
            self.opened = {}
            self.media = set()
            self.parent = SimpleNamespace(wire_observation=self.wire)

        def wire(self, slot):
            if slot not in self.opened:
                return None, None
            return (
                (2, 1, 0x10000505, self.opened[slot], False),
                (0, 1, 65537, 0) if slot in self.media else None,
            )

        def start(self, *args, **kwargs):
            return MasterLoginProof(True, True, True, True, True, 6)

        def open_slot(self, selection, grant, **kwargs):
            self.opened[grant.slot] = selection.ordinal
            return grant.slot

        def prepare_viewer(self, grant):
            return owners[grant.lease_id].handle

        def close(self):
            return None

        def binding_for(self, *args):
            return None

        def issued_receipt(self):
            return None

    master = Master()
    provider = observer.wrap_mux_provider(
        SimpleNamespace(prepare_master=lambda *a: master)
    )
    reservation = SimpleNamespace(master_id=uuid4())

    class Handle:
        def __init__(self, lease, registration, slot, channel):
            self.master = master
            self.lease, self.registration = lease, registration
            self.cut = IngressCut(slot.epoch, slot, registration, channel, 1, 1e12)

        def start(self, **kwargs):
            assert owners[self.lease].callback is not None

        def read_frames(self, **limits):
            item = owners[self.lease]
            item.reads += 1
            raw = frame(index=item.reads, channel=item.grant.slot.channel)
            object.__setattr__(
                raw,
                "identity",
                LiveIdentity(
                    generation=4,
                    session=b"s" * 16,
                    channel=item.grant.slot.channel,
                    task=item.grant.slot.task,
                ),
            )
            object.__setattr__(raw, "source_context", (3, 2, 0, 0, 0))
            clock[0] += 0.01
            master.media.add(item.grant.slot)
            return (
                MuxValidatedFrame(
                    raw,
                    item.grant.slot,
                    IngressSpan(item.reads + 1, item.reads + 1),
                    1000000 + 24 * (item.reads - 1),
                    item.reads,
                    _seal=_WIRE_SEAL,
                ),
            )

        def close(self):
            receipt = owners[self.lease].callback()
            return receipt if cleanup else None

    class Executor:
        def __init__(self):
            self.coordinator = self
            self.prepared = False
            self.original_master = master
            self.test_owners = owners

        def start(self, ticket, **kwargs):
            channel = int(ticket)
            if not self.prepared:
                assert provider.prepare_master(reservation, object()) is master
                master.start()
                self.prepared = True
            lease, registration = uuid4(), uuid4()
            slot = MuxSlotIdentity(
                MuxEpochIdentity(4, b"s" * 16),
                bytes([channel]) * 16,
                bytes([channel + 20]) * 16,
                2,
            )
            handle = Handle(lease, registration, slot, channel)
            grant = SimpleNamespace(
                slot=slot, registration=registration, lease_id=lease
            )
            owners[lease] = SimpleNamespace(
                handle=handle, grant=grant, callback=None, reads=0, channel=channel
            )
            owners[lease].callback = kwargs["retain_local"](lease, registration)
            master.open_slot(SimpleNamespace(ordinal=channel), grant)
            assert master.prepare_viewer(grant) is handle
            handle.start()
            events.append(("start", channel))
            return SimpleNamespace(lease=SimpleNamespace(id=lease))

        def mux_binding(self, lease):
            item = owners[lease]
            return item.handle, item.grant

        def attach_retirement(self, lease, callback):
            raise AssertionError("post-start retirement attachment refused")

        def current(self, lease):
            return lease not in closed

        def read_mux_frames(self, lease, **limits):
            return owners[lease].handle.read_frames(**limits)

        def release_mux_frames(self, lease, batch):
            events.append(("release", owners[lease].channel))

        def proof(self, lease):
            assert owners[lease].reads
            return PROOF

        def heartbeat(self, ticket, **kwargs):
            assert ticket == "heartbeat"
            return wall

        def stop_wall_result(self, ticket, **kwargs):
            assert ticket == "stop"
            return wall, self.stop_wall(wall, **kwargs)

        def stop_wall(self, wall_id, **kwargs):
            for lease, item in owners.items():
                receipt = item.handle.close()
                if cleanup and receipt is not None:
                    closed.add(lease)
            return cleanup and len(closed) == len(owners)

        def finish_stop(self, lease, **kwargs):
            assert lease in closed
            return SimpleNamespace(lease=SimpleNamespace(state="CLOSED"))

    return Executor(), Tickets(), observer, requests, clock, events


def test_two_channel_probe_redeems_tickets_releases_batches_and_reports_only_closed_projection(
    probe,
):
    import json

    core, tickets, observer, requests, clock, events = fake_probe_runtime(probe)
    runner = probe.MuxProbeRunner(
        core,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    result = runner.run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
    assert result["status"] == "RAW_GATE_RETIRED"
    assert result["closed_viewers"] == 2 and result["frame_counts"] == [2, 2]
    assert events.index(("start_ticket", 1)) < events.index(("start", 1))
    assert events.count(("release", 1)) == 2
    text = json.dumps(result)
    assert "private" not in text and all(
        str(r.channel_id) not in text for r in requests.values()
    )


def test_probe_cleanup_deadline_retains_exact_owners_without_closed_claim(probe):
    core, tickets, observer, requests, clock, _ = fake_probe_runtime(
        probe, cleanup=False
    )
    runner = probe.MuxProbeRunner(
        core,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    result = runner.run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
    assert result["status"] == "FAILED_RETAINED" and result["closed_viewers"] == 0
    assert len(runner.owners) == 2


def test_probe_missing_ack_is_failed_evidence_even_when_cleanup_succeeds(probe):
    core, tickets, observer, requests, clock, _ = fake_probe_runtime(probe)
    core.original_master.parent.wire_observation = lambda slot: (None, None)
    runner = probe.MuxProbeRunner(
        core,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda n: clock.__setitem__(0, clock[0] + n),
    )
    result = runner.run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
    assert result["status"] == "FAILED" and result["closed_viewers"] == 2
    assert result["failure"] == "WIRE_EVIDENCE_UNAVAILABLE"


def test_four_channel_probe_requires_prior_two_gate_before_any_ticket(probe):
    core, tickets, observer, requests, _clock, events = fake_probe_runtime(probe)
    for channel in (3, 4):
        requests[channel] = requests[1].model_copy(update={"channel_id": uuid4()})
    with pytest.raises(ValueError):
        probe.MuxProbeRunner(core, tickets, observer).run(
            probe.MuxProbePlan((1, 2, 3, 4), 120), requests
        )
    assert events == []


def test_probe_late_observation_failure_cannot_report_raw_gate_success(probe):
    core, tickets, observer, requests, clock, _ = fake_probe_runtime(probe)
    seen = [False]
    stop = core.stop_wall_result

    def stopped(*a, **k):
        result = stop(*a, **k)
        seen[0] = True
        return result

    core.stop_wall_result = stopped
    snapshot = observer.snapshot
    observer.snapshot = lambda: snapshot() | {"observation_failures": int(seen[0])}
    runner = probe.MuxProbeRunner(
        core,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda n: clock.__setitem__(0, clock[0] + n),
    )
    result = runner.run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
    assert result["status"] == "FAILED" and result["closed_viewers"] == 2


def test_four_channel_probe_consumes_prior_gate_and_retires_all_four(probe):
    core, tickets, observer, requests, clock, events = fake_probe_runtime(
        probe, channels=(1, 2, 3, 4)
    )
    runner = probe.MuxProbeRunner(
        core,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda n: clock.__setitem__(0, clock[0] + n),
    )
    result = runner.run(
        probe.MuxProbePlan((1, 2, 3, 4), 120),
        requests,
        cleanup_seconds=1,
        prior_two_complete=True,
    )
    assert result["status"] == "RAW_GATE_RETIRED" and result["closed_viewers"] == 4
    assert result["frame_counts"] == [2, 2, 2, 2]
    assert (
        len(
            [
                event
                for event in events
                if isinstance(event, tuple) and event[0] == "start"
            ]
        )
        == 4
    )


def test_r1_wire_snapshot_consuming_live_deadline_is_failed_with_cleanup(probe):
    core, tickets, observer, requests, clock, _ = fake_probe_runtime(probe)
    snapshot = observer.snapshot
    first = [True]

    def delayed():
        value = snapshot()
        if first[0]:
            first[0] = False
            clock[0] += 2
        return value

    observer.snapshot = delayed
    result = probe.MuxProbeRunner(
        core,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda n: clock.__setitem__(0, clock[0] + n),
    ).run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
    assert result["status"] == "FAILED" and result["failure"] == "deadline"
    assert (
        result["closed_viewers"] == 2
        and result["cleanup_scope"] == "LAST_VIEWER_AND_DEVICE_EPOCH"
    )


def test_r1_old_complete_observer_is_rejected_before_new_tickets(probe):
    from wso_core.tvt.local_media_mux_types import MuxSlotIdentity

    from tests.contract import test_local_media_observation as observation_tests

    module = observation_tests.observation.__wrapped__()
    written = []
    old = module.MediaObservation(written.append, shared=True)
    provider, master, _, reservation, _, grant = (
        observation_tests.shared_prepared_fixture()
    )
    master.open_slot = lambda selection, current, **kwargs: current.slot
    master.parent.wire_observation = lambda slot: (
        (2, 1, 0x10000505, 9, False),
        (0, 1, 65537, 0),
    )
    old.wrap_mux_provider(provider).prepare_master(reservation, object())
    master.start(object(), object())
    for ordinal in (1, 2):
        slot = MuxSlotIdentity(
            grant.slot.epoch, bytes([ordinal]) * 16, bytes([ordinal + 20]) * 16, 2
        )
        master.open_slot(SimpleNamespace(ordinal=ordinal), SimpleNamespace(slot=slot))
    old.start()
    terminal = old.close()
    before = old.snapshot()
    assert module.complete_observation(before, terminal)
    core, tickets, _unused, requests, clock, events = fake_probe_runtime(probe)
    with pytest.raises(ValueError):
        probe.MuxProbeRunner(core, tickets, old, clock=lambda: clock[0]).run(
            probe.MuxProbePlan((1, 2), 1), requests
        )
    assert events == []
    assert old.snapshot() == before and old.close() == terminal


@pytest.mark.parametrize("replacement", ["cut", "registration"])
def test_r1_final_original_binding_substitution_cannot_qualify(probe, replacement):
    from dataclasses import replace

    core, tickets, observer, requests, clock, _ = fake_probe_runtime(probe)
    snapshot = observer.snapshot
    changed = [False]

    def substituted():
        value = snapshot()
        if (
            not changed[0]
            and len(core.test_owners) == 2
            and all(owner.reads == 2 for owner in core.test_owners.values())
        ):
            changed[0] = True
            handle = next(iter(core.test_owners.values())).handle
            if replacement == "cut":
                handle.cut = replace(handle.cut)
            else:
                handle.registration = uuid4()
        return value

    observer.snapshot = substituted
    result = probe.MuxProbeRunner(
        core,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda n: clock.__setitem__(0, clock[0] + n),
    ).run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
    assert changed[0]
    assert result["status"] in {"FAILED", "FAILED_RETAINED"}
    assert result["status"] != "RAW_GATE_RETIRED"


def test_r1_active_observer_without_current_original_hooks_is_unbound(probe):
    from tests.contract import test_local_media_observation as observation_tests

    core, tickets, _bound, requests, clock, _ = fake_probe_runtime(probe)
    module = observation_tests.observation.__wrapped__()
    unbound = module.MediaObservation(
        lambda value: None, shared=True, clock=lambda: clock[0]
    )
    probe._test_observers.append(unbound)
    unbound.start()
    result = probe.MuxProbeRunner(
        core,
        tickets,
        unbound,
        clock=lambda: clock[0],
        pause=lambda n: clock.__setitem__(0, clock[0] + n),
    ).run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
    assert result["status"] == "FAILED"
    assert all(owner.reads == 0 for owner in core.test_owners.values())
    assert unbound.snapshot()["mux"]["viewers"] == []


def test_r1_observer_stopping_during_cleanup_cannot_report_success(probe):
    core, tickets, observer, requests, clock, _ = fake_probe_runtime(probe)
    stop = core.stop_wall_result
    terminals = []

    def stopped(*args, **kwargs):
        result = stop(*args, **kwargs)
        terminals.append(observer.close())
        return result

    core.stop_wall_result = stopped
    result = probe.MuxProbeRunner(
        core,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda n: clock.__setitem__(0, clock[0] + n),
    ).run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
    assert result["status"] == "FAILED" and result["closed_viewers"] == 2
    assert observer.close() == terminals[0]


@pytest.mark.parametrize("boundary", ["before_start", "after_cut", "after_start"])
def test_r188_real_executor_cancel_before_return_retains_original_raw_supplier(
    probe, boundary
):
    from threading import Event, RLock

    from test_local_live_mux_provider import viewer_rig
    from wso_core.tvt.local_media_mux_service import MuxMediaExecutor

    from tests.tvt_parity.test_local_media_worker import Core

    viewer, master, _, _ = viewer_rig(started=False)
    lease_id = viewer.current_grant().lease_id
    lease = SimpleNamespace(id=lease_id)
    view = Core().view.model_copy(update={"id": lease_id})
    record = SimpleNamespace(
        lease=lease, handle=viewer, grant=viewer.current_grant(), stopping=False
    )
    _fake, tickets, observer, requests, clock, _ = fake_probe_runtime(probe)
    tickets.start = lambda *args: "a" * 64
    coordinator = SimpleNamespace(
        _lock=RLock(), _viewers={lease_id: record}, _dedicated={}, _closed_views={}
    )
    coordinator.current = lambda ident: (
        ident in coordinator._viewers and not record.stopping
    )
    cancel = Event()
    retained = []
    original_cut = master.parent.admission_cut

    def cut(*args, **kwargs):
        result = original_cut(*args, **kwargs)
        if boundary == "after_cut":
            cancel.set()
        return result

    master.parent.admission_cut = cut

    def attach(*args, **kwargs):
        kwargs["budget"].cancel = cancel
        retain = kwargs.get("retain_local")
        if retain is not None:
            supplier = retain(lease_id, viewer.registration)
            retained.append(supplier)
            assert runner.owners[lease_id].handle is None
            viewer.attach_retirement(supplier)
        if boundary == "before_start":
            cancel.set()
        viewer.start(budget=kwargs["budget"])
        if boundary == "after_start":
            cancel.set()
        return viewer

    def close(original):
        original.stopping = True
        receipt = viewer.close()
        if receipt is None:
            return False
        coordinator._viewers.pop(lease_id, None)
        coordinator._closed_views[lease_id] = view.model_copy(
            update={"state": "CLOSED"}
        )
        return True

    coordinator.attach, coordinator._close_viewer = attach, close
    # Local viewer retirement cannot supply this separate native epoch receipt.
    coordinator.stop_wall_result = lambda *a, **k: (tickets.wall(None), False)
    coordinator.stop_wall = lambda *a, **k: False
    admission = SimpleNamespace(
        redeem=lambda *a, **k: lease,
        prepare_viewer=lambda *a, **k: SimpleNamespace(stream="sub"),
        view=lambda _: view,
    )
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    runner = probe.MuxProbeRunner(
        executor,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda n: clock.__setitem__(0, clock[0] + n),
    )
    try:
        result = runner.run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
        assert len(retained) == 1, "raw probe omitted pre-start local retention"
        owner = runner.owners[lease_id]
        assert viewer._retirement is retained[0] is owner.original_retire
        assert owner.handle is None  # Core never returned a response/binding.
        receipt = viewer.issued_receipt()
        assert receipt is not None and viewer.close() is retained[0]() is receipt
        assert receipt.lease_id == lease_id
        assert receipt.registration_id == viewer.registration
        assert not coordinator._viewers
        assert viewer._start_attempted
        assert (viewer._cut is not None) == (boundary != "before_start")
        assert viewer._started == (boundary == "after_start")
        assert not master.owner.confirmed
        assert result["status"] == "FAILED_RETAINED"
        assert result["frame_counts"] == [] and result["closed_viewers"] == 0
    finally:
        master.owner.confirmed = True
        assert master.parent.close()


@pytest.mark.parametrize("attempt", ["read", "foreign_bind"])
def test_r188_unbound_owner_attempt_cannot_certify_known_empty(probe, attempt):
    lease, registration = uuid4(), uuid4()
    owner = probe.ProbeViewerOwner(SimpleNamespace(), lease, registration)
    if attempt == "read":
        with pytest.raises(ValueError):
            owner.begin_read()
    else:
        with pytest.raises(ValueError):
            owner.bind(SimpleNamespace(registration=uuid4()), registration)
    assert owner.original_retire() is None


def test_r188_original_registration_is_required_before_read_and_no_second_bind(probe):
    registration = uuid4()
    handle = SimpleNamespace(registration=registration)
    owner = probe.ProbeViewerOwner(SimpleNamespace(), uuid4(), registration)
    with pytest.raises(ValueError):
        owner.bind(handle, uuid4())
    assert owner.handle is None and owner.original_retire() is None
    owner = probe.ProbeViewerOwner(SimpleNamespace(), uuid4(), registration)
    supplier = owner.original_retire
    owner.bind(handle, registration)
    with pytest.raises(ValueError):
        owner.bind(handle, registration)
    assert owner.original_retire is supplier and supplier() is None


def test_r188_known_empty_before_binding_issues_same_receipt_and_blocks_late_bind(
    probe,
):
    lease, registration = uuid4(), uuid4()
    owner = probe.ProbeViewerOwner(SimpleNamespace(), lease, registration)
    supplier = owner.original_retire
    receipt = supplier()
    assert receipt.lease_id == lease and receipt.registration_id == registration
    assert supplier() is receipt
    with pytest.raises(ValueError):
        owner.bind(SimpleNamespace(registration=registration), registration)
    assert supplier() is None


@pytest.mark.parametrize("bound", [False, True])
def test_r188_failed_read_keeps_original_owner_uncertain(probe, bound):
    registration = uuid4()
    owner = probe.ProbeViewerOwner(SimpleNamespace(), uuid4(), registration)
    if bound:
        owner.bind(SimpleNamespace(registration=registration), registration)
        owner.begin_read()
    owner.read_failed()
    assert owner.original_retire() is None


def test_r188_binding_exception_cannot_certify_unattempted_empty(probe):
    registration = uuid4()
    owner = probe.ProbeViewerOwner(SimpleNamespace(), uuid4(), registration)

    class Handle:
        @property
        def registration(self):
            raise RuntimeError("private-secret")

    with pytest.raises(RuntimeError):
        owner.bind(Handle(), registration)
    assert owner.handle is None and owner.original_retire() is None


@pytest.fixture
def genuine_viewer():
    from test_local_live_mux_provider import viewer_rig

    originals = []

    def prepare(*, started=True):
        result = viewer_rig(started=started)
        originals.append(result[1])
        return result

    yield prepare
    for master in originals:
        master.owner.confirmed = True
        assert master.parent.close()


def test_r188_genuine_registration_substitution_keeps_same_supplier_unsettled(
    probe, genuine_viewer
):
    from dataclasses import replace

    from wso_core.tvt.local_media_mux_types import _GRANT_SEAL

    viewer, _master, _callback, _slot = genuine_viewer()
    grant = viewer.current_grant()
    owner = probe.ProbeViewerOwner(
        SimpleNamespace(), grant.lease_id, grant.registration
    )
    supplier = owner.original_retire
    viewer.attach_retirement(supplier)
    owner.bind(viewer, grant.registration)
    viewer._grant = replace(grant, registration=uuid4(), _seal=_GRANT_SEAL)
    assert supplier() is None and viewer.close() is None
    assert viewer._retirement is supplier and viewer.issued_receipt() is None


def test_r188_genuine_blocked_read_and_exact_held_batch_prevent_retirement(
    probe, genuine_viewer
):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from test_local_mux_callback import invoke, key

    viewer, master, callback, slot = genuine_viewer()
    grant = viewer.current_grant()
    executor = SimpleNamespace(
        release_mux_frames=lambda lease, batch: viewer.release_frames(batch)
    )
    owner = probe.ProbeViewerOwner(executor, grant.lease_id, grant.registration)
    viewer.attach_retirement(owner.original_retire)
    owner.bind(viewer, grant.registration)
    entered, release = Event(), Event()
    original_read = master.parent.read_frames

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(1)
        return original_read(*args, **kwargs)

    master.parent.read_frames = held
    batch = ()
    try:
        invoke(callback, key(slot))
        owner.begin_read()
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(
                viewer.read_frames,
                max_frames=1,
                max_bytes=1 << 20,
                deadline_monotonic=time.monotonic() + 2,
            )
            assert entered.wait(1)
            assert owner.original_retire() is None
            release.set()
            batch = pending.result()
        owner.returned(batch)
        assert batch and owner.original_retire() is None
        assert viewer.close() is None
        with pytest.raises(ValueError):
            owner.release((*batch,))
        owner.release(batch)
        batch = ()
        receipt = owner.original_retire()
        assert receipt is not None and viewer.close() is receipt
        assert not master.owner.confirmed
    finally:
        release.set()
        if batch:
            owner.release(batch)
        master.owner.confirmed = True
        assert master.parent.close()


@pytest.mark.parametrize("getter", ["current_grant", "registration", "cut"])
def test_r188_fix1_runner_genuine_binding_lookup_failure_never_certifies_empty(
    probe, genuine_viewer, monkeypatch, getter
):
    from threading import RLock

    from wso_core.tvt.local_media_mux_service import EpochState, MuxMediaExecutor

    from tests.tvt_parity.test_local_media_worker import Core

    viewer, master, _, _ = genuine_viewer(started=False)
    grant = viewer.current_grant()
    lease = SimpleNamespace(id=grant.lease_id)
    view = Core().view.model_copy(update={"id": lease.id})
    original = getattr(type(viewer), getter)
    failed_lookup = []
    active = [False]

    def access(current):
        if active[0]:
            failed_lookup.append(getter)
            raise RuntimeError("private-secret")
        if getter == "current_grant":
            return original(current)
        return original.fget(current)

    monkeypatch.setattr(
        type(viewer), getter, access if getter == "current_grant" else property(access)
    )
    master.refresh_version, master.refreshing = 0, False
    master.state, master.scope = EpochState.ACTIVE, grant.scope
    record = SimpleNamespace(
        lease=lease, handle=viewer, grant=grant, master=master, stopping=False
    )
    coordinator = SimpleNamespace(
        _lock=RLock(),
        _viewers={lease.id: record},
        _dedicated={},
        _closed_views={},
        _closed=False,
    )
    coordinator.current = lambda ident: (
        ident in coordinator._viewers and not record.stopping
    )
    supplied = []

    def attach(*args, **kwargs):
        supplier = kwargs["retain_local"](lease.id, viewer.registration)
        supplied.append(supplier)
        viewer.attach_retirement(supplier)
        viewer.start(budget=kwargs["budget"])
        record.cut = viewer.cut
        active[0] = True
        return viewer

    receipts, cleanup_local = [], []

    def close(original_record):
        original_record.stopping = True
        cleanup_local.append(supplied[0]())
        receipt = viewer.close()
        receipts.append(receipt)
        if receipt is None:
            return False
        coordinator._viewers.pop(lease.id, None)
        return True

    coordinator.attach, coordinator._close_viewer = attach, close
    _fake, tickets, observer, requests, clock, _ = fake_probe_runtime(probe)
    tickets.start = lambda *args: "a" * 64

    def stop(*args, **kwargs):
        executor.close(lease.id)
        return False  # Native epoch custody is independent and still held.

    coordinator.stop_wall = stop
    coordinator.stop_wall_result = lambda *a, **k: (tickets.wall(None), stop())
    admission = SimpleNamespace(
        redeem=lambda *a, **k: lease,
        prepare_viewer=lambda *a, **k: SimpleNamespace(stream="sub"),
        view=lambda _: view,
    )
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    reads = []
    executor.read_mux_frames = lambda *a, **k: reads.append(True)
    runner = probe.MuxProbeRunner(
        executor,
        tickets,
        observer,
        clock=lambda: clock[0],
        pause=lambda n: clock.__setitem__(0, clock[0] + n),
    )
    result = runner.run(probe.MuxProbePlan((1, 2), 1), requests, cleanup_seconds=1)
    owner = runner.owners[lease.id]
    assert failed_lookup == [getter] and viewer._started
    assert owner.handle is None and owner.original_retire() is None
    assert cleanup_local and all(receipt is None for receipt in cleanup_local)
    assert receipts and all(receipt is None for receipt in receipts)
    assert viewer.issued_receipt() is None and not master.owner.confirmed
    assert (
        len(supplied) == 1
        and viewer._retirement is supplied[0] is owner.original_retire
    )
    assert lease.id in coordinator._viewers and not reads
    assert result["status"] == "FAILED_RETAINED" and result["closed_viewers"] == 0
