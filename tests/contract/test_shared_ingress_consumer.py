"""Real callback/codec/pump controls with inert original child ports."""

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_local_live_mux_ipc import admit, read, rig
from test_local_live_mux_provider import Admission, prepared_inputs, provider_module
from test_local_mux_callback import invoke, key
from wso_core.tvt.local_media_mux_types import (
    _GRANT_SEAL,
    SlotRetentionGrant,
    ViewerGrant,
)
from wso_core.tvt.local_service import LocalVerifyBudget
from wso_tvt_bridge import windows_socket as windows


def wait_until(predicate, timeout=2):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        time.sleep(0.001)
    assert predicate()


@pytest.fixture
def consumer_rig(monkeypatch):
    monkeypatch.setattr(windows, "PENDING_OWNERS", [])
    module = provider_module()
    budget, reservation = prepared_inputs()
    master = module.NativeLocalMuxProvider(
        windows.WindowsSocketProvider(), budget=budget, admission=Admission()
    ).prepare_master(reservation, budget.reserve("base"))
    parent, remote, callback, old_owner, (slot,) = rig()
    master._ready, master._parent, master._epoch = True, parent, slot.epoch
    master.owner.child = SimpleNamespace(poll=lambda: None)
    master.custodian.resources_current = lambda: True
    parent._owner = master.owner
    parent.authorize = master._authorize
    grant = SlotRetentionGrant(
        scope=reservation.scope,
        expires_monotonic=reservation.transport.expires_monotonic,
        slot=slot,
        _authority=object(),
        _seal=_GRANT_SEAL,
    )
    master._slots[slot.channel] = grant
    yield master, parent, remote, callback, slot
    stop = getattr(master, "_ingress_stop", None)
    if stop is not None:
        stop.set()
    thread = getattr(master, "_ingress_thread", None)
    if thread is not None and thread.ident is not None:
        thread.join(2)
    parent._owner = old_owner
    old_owner.confirmed = True
    assert parent.close()
    master.owner.child = None
    master._ready = False
    master.close()


def test_without_consumer_original_callback_fails_on_chunk_257(consumer_rig):
    _, _, _, callback, slot = consumer_rig
    for index in range(1, 257):
        assert invoke(callback, key(slot, index)) > 0
    assert invoke(callback, key(slot, 257)) == 0 and callback.failed


def test_ready_without_open_slots_keeps_startup_ingress_foreground(consumer_rig):
    master, parent, _, callback, slot = consumer_rig
    parent._opened.clear()
    master._slots.clear()
    master._start_ingress_consumer()
    invoke(callback, key(slot))
    time.sleep(0.05)
    assert callback.used > 0 and not parent.failed


def test_sustained_parked_callback_ingress_drains_and_refunds(consumer_rig):
    master, parent, _, callback, slot = consumer_rig
    master._start_ingress_consumer()
    for index in range(1, 1025):
        assert invoke(callback, key(slot, index)) > 0
        wait_until(lambda: callback.used == 0 and not parent._raw)
        assert parent.credit_usage(slot) == (0, 0)
    assert not callback.failed and not parent.failed


def test_active_cut_handoff_preserves_precut_partial_and_fresh_key(consumer_rig):
    master, parent, _, callback, slot = consumer_rig
    raw = key(slot)
    master._start_ingress_consumer()
    invoke(callback, raw[:31])
    wait_until(lambda: callback.used == 0)
    with master.io_lock:
        from uuid import uuid4

        grant = ViewerGrant(
            scope=master.reservation.scope,
            expires_monotonic=master._transport.expires_monotonic,
            slot=slot,
            lease_id=uuid4(),
            registration=uuid4(),
            _authority=object(),
            _seal=_GRANT_SEAL,
        )
        master._viewers[grant.registration] = SimpleNamespace(
            _stopping=False, current_grant=lambda: grant
        )
        cut = admit(parent, slot, grant.registration)
        invoke(callback, raw[31:])
        parent.pump(master.owner, deadline_monotonic=time.monotonic() + 1)
        assert read(parent, slot, cut) == ()
    invoke(callback, key(slot, 2))
    time.sleep(0.04)
    assert callback.used > 0, "consumer stole foreground active ingress"
    with master.io_lock:
        parent.pump(master.owner, deadline_monotonic=time.monotonic() + 1)
        frames = read(parent, slot, cut)
        assert len(frames) == 1 and frames[0].ingress.first > cut.after_ordinal
        parent.release_frames(frames)
        parent.park(slot)
    invoke(callback, key(slot, 3))
    wait_until(lambda: callback.used == 0)
    assert parent.credit_usage(slot) == (0, 0)


def test_busy_refresh_barrier_skips_pump_without_fencing(consumer_rig):
    master, parent, _, callback, slot = consumer_rig
    with master.refresh_grants(budget=LocalVerifyBudget(1000)):
        master._start_ingress_consumer()
        invoke(callback, key(slot))
        time.sleep(0.05)
        assert callback.used > 0 and not parent.failed
        old = master._slots[slot.channel]
        master.replace_grant(
            old,
            replace(
                old, expires_monotonic=old.expires_monotonic + 1, _seal=_GRANT_SEAL
            ),
        )
    wait_until(lambda: callback.used == 0)
    assert not parent.failed


@pytest.mark.parametrize("returned", [True, False])
def test_late_or_uncertain_start_retains_original_until_target_and_join(
    consumer_rig, monkeypatch, returned
):
    master, _, _, _, _ = consumer_rig
    originals = []

    class Thread:
        ident = None

        def __init__(self, *, target, **kwargs):
            self.target, self.joined = target, False
            originals.append(self)

        def start(self):
            if not returned:
                raise RuntimeError("uncertain original start")

        def is_alive(self):
            return False

        def join(self, *args):
            self.joined = True

    monkeypatch.setattr(threading, "Thread", Thread)
    if returned:
        master._start_ingress_consumer()
    else:
        with pytest.raises(RuntimeError):
            master._start_ingress_consumer()
    assert master.close() is None and master.issued_receipt() is None
    original = originals[0]
    original.ident = 1
    original.target()
    master.owner.child = None
    assert master.close() is not None and original.joined


def test_blocked_original_pump_prevents_receipt_until_unwind_and_join(consumer_rig):
    master, parent, _, _, _ = consumer_rig
    entered, release = threading.Event(), threading.Event()
    real_pump = parent.pump

    def pump(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        # Stop won; existing parent owns any later fence, not this test gate.
        if not master._closed:
            return real_pump(*args, **kwargs)
        return False

    parent.pump = pump
    master._start_ingress_consumer()
    assert entered.wait(1)
    try:
        assert master.close() is None and master.issued_receipt() is None
        assert master._operations and not master._ingress_finished.is_set()
    finally:
        release.set()
    wait_until(master._ingress_finished.is_set)
    master.owner.child = None
    assert master.close() is not None
    assert not master._ingress_thread.is_alive() and master._ingress_joined


@pytest.mark.parametrize("alias", ["thread", "stop", "finished", "start_finished"])
def test_receipt_cannot_adopt_replaced_consumer_alias(consumer_rig, alias):
    master, _, _, _, _ = consumer_rig
    master._start_ingress_consumer()
    master._ingress_stop.set()
    wait_until(master._ingress_finished.is_set)
    master._ingress_thread.join(1)
    attribute = "_ingress_" + alias
    original = getattr(master, attribute)
    if alias == "thread":
        foreign = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: False)
    else:
        foreign = threading.Event()
        foreign.set()
    setattr(master, attribute, foreign)
    try:
        master.owner.child = None
        assert master.close() is None and master.issued_receipt() is None
    finally:
        setattr(master, attribute, original)
    assert master.close() is not None


def test_finished_target_during_unreturned_start_cannot_settle(
    consumer_rig, monkeypatch
):
    master, _, _, _, _ = consumer_rig
    real_thread = threading.Thread
    entered, target_finished, return_start = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    class Thread:
        ident = 1

        def __init__(self, *, target, **kwargs):
            self.target, self.joined = target, False

        def start(self):
            entered.set()
            self.target()
            target_finished.set()
            assert return_start.wait(2)

        def is_alive(self):
            return False

        def join(self, *args):
            self.joined = True

    monkeypatch.setattr(threading, "Thread", Thread)
    starter = real_thread(target=master._start_ingress_consumer)
    starter.start()
    assert entered.wait(1)
    try:
        assert master.close() is None
        assert target_finished.wait(1)
        master.owner.child = None
        assert master.issued_receipt() is None and master.close() is None
    finally:
        return_start.set()
        starter.join(2)
    assert master.close() is not None and master._ingress_thread.joined


def test_failed_join_retains_original_receipt(consumer_rig, monkeypatch):
    master, _, _, _, _ = consumer_rig
    master._start_ingress_consumer()
    master._ingress_stop.set()
    wait_until(master._ingress_finished.is_set)
    thread = master._ingress_thread
    join = thread.join

    def interrupted(*args):
        raise RuntimeError("original join interrupted")

    monkeypatch.setattr(thread, "join", interrupted)
    master.owner.child = None
    assert master.close() is None and master.issued_receipt() is None
    monkeypatch.setattr(thread, "join", join)
    assert master.close() is not None
