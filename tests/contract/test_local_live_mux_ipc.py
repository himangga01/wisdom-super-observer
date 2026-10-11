"""Original-pipe mux contracts using inert callback memory, never a native login."""

import importlib
import importlib.util
import struct
import threading
import time
from dataclasses import replace
from threading import Event
from uuid import UUID

import pytest
from test_local_mux_callback import invoke, key, packet
from wso_core.tvt.local_media_mux_types import (
    MuxEpochIdentity,
    MuxPurpose,
    MuxSlotIdentity,
)
from wso_tvt_bridge.windows_socket_worker import CallbackOwner

PARENTS = []


@pytest.fixture(autouse=True)
def retire_inert_originals():
    yield
    for parent in PARENTS:
        parent.release_frames(
            tuple(
                item[0]
                for item in parent._held.values()
                if all(item[0] not in q for q in parent._queues.values())
            )
        )
        parent._owner.confirmed = True
        parent.close()
    PARENTS.clear()


def api():
    name = "wso_tvt_bridge.local_live_mux_ipc"
    assert importlib.util.find_spec(name), "purpose-bound mux IPC is missing"
    return importlib.import_module(name)


class Owner:
    confirmed = False
    stopped = False

    def request_stop(self):
        self.stopped = True


class Pipe:
    def __init__(self, remote):
        self.remote = remote
        self.answer = None
        self.closed = False

    def send_bytes(self, raw):
        assert self.answer is None, "more than one pending control"
        self.answer = self.remote.handle(raw)

    def poll(self, timeout=0):
        return self.answer is not None

    def recv_bytes(self, maximum):
        raw, self.answer = self.answer, None
        assert len(raw) <= maximum
        return raw

    def close(self):
        self.closed = True


def rig(count=1, authorize=lambda purpose, slot, registration: True):
    m = api()
    epoch = MuxEpochIdentity(7, b"s" * 16)
    callback = CallbackOwner(7, 7)
    callback.bind_mux_epoch(epoch)
    remote = m.MuxRemoteAuthority(
        epoch=epoch, callback=callback, deadline_monotonic=time.monotonic() + 30
    )
    parent = m.MuxParentAuthority(
        epoch=epoch, authorize=authorize, clock=time.monotonic
    )
    PARENTS.append(parent)
    owner = Owner()
    parent.bind_original(
        owner,
        connection=Pipe(remote),
        peer_capability=4,
        deadline_monotonic=time.monotonic() + 25,
        cancel=Event(),
    )
    slots = []
    for i in range(count):
        slot = MuxSlotIdentity(epoch, bytes([i + 1]) * 16, bytes([i + 65]) * 16, 2)
        parent.register_slot(slot, channel_number=i)
        parent.prepare_open(slot, request_guid=b"r" * 16, sequence=i + 1)
        invoke(callback, packet(0x10000501, sequence=i + 1))
        assert parent.pump(owner, deadline_monotonic=time.monotonic() + 1)
        slots.append(slot)
    return parent, remote, callback, owner, slots


def admit(parent, slot, registration=None, cancel=None):
    return parent.admission_cut(
        slot,
        registration=UUID(int=1) if registration is None else registration,
        deadline_monotonic=time.monotonic() + 5,
        cancel=cancel or Event(),
    )


def read(parent, slot, cut):
    return parent.read_frames(
        slot,
        cut=cut,
        max_frames=16,
        max_bytes=4 << 20,
        deadline_monotonic=time.monotonic() + 1,
    )


@pytest.mark.parametrize("held", ["callback", "ipc", "partial", "returned"])
def test_provenance_survives_callback_batch_ipc_and_fragments(held):
    p, _r, cb, owner, (slot,) = rig()
    raw = key(slot)
    old_cut = admit(p, slot)
    invoke(cb, raw[:31] if held == "partial" else raw)
    if held in ("ipc", "partial", "returned"):
        assert p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    previous = read(p, slot, old_cut) if held == "returned" else ()
    p.park(slot)
    cut = admit(p, slot, UUID(int=2))
    if held == "partial":
        invoke(cb, raw[31:])
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    assert read(p, slot, cut) == ()
    assert all(f.ingress.first <= cut.after_ordinal for f in previous)
    invoke(cb, key(slot, 2))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    (frame,) = read(p, slot, cut)
    assert frame.ingress.first > cut.after_ordinal
    assert frame.slot == slot and frame.slot_ordinal == 2


@pytest.mark.parametrize(
    "field", ["epoch", "registration", "control_sequence", "expiry", "copy"]
)
def test_cut_rejects_foreign_epoch_registration_sequence_expiry(field):
    p, _r, _cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    if field == "epoch":
        epoch = MuxEpochIdentity(8, b"z" * 16)
        forged = replace(cut, epoch=epoch, slot=replace(slot, epoch=epoch))
    elif field == "expiry":
        forged = replace(cut, expires_monotonic=cut.expires_monotonic + 1)
    elif field == "copy":
        forged = replace(cut)
    else:
        forged = replace(
            cut, **{field: UUID(int=9) if field == "registration" else 999}
        )
    with pytest.raises(api().MuxIpcError):
        read(p, slot, forged)
    assert owner.stopped


def test_no_credit_has_bounded_control_progress():
    p, _r, cb, owner, (slot, sibling) = rig(2)
    cut = admit(p, slot)
    for index in range(1, 17):
        invoke(cb, key(slot, index))
        p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    held = read(p, slot, cut)
    assert len(held) == 16 and p.credit_usage(slot)[0] == 16
    # Returned frames remain charged; the cut control still crosses the pipe.
    other = admit(p, sibling, UUID(int=2))
    assert other.slot == sibling
    invoke(cb, key(slot, 17) + key(sibling))
    assert not p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    assert p.credit_usage(slot)[0] == 16
    p.release_frames(held)
    assert p.pump(owner, deadline_monotonic=time.monotonic() + 1)


def test_stalled_slot_cannot_allocate_hidden_batch():
    p, _r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    invoke(cb, b"".join(key(slot, n) for n in range(1, 19)))
    for _ in range(18):
        p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    frames = read(p, slot, cut)
    assert len(frames) == 16
    assert p.credit_usage(slot)[0] == 16
    assert p.pending_raw_bytes <= 1 << 20


def test_unknown_slot_tombstone_and_deadline_fence():
    p, _r, _cb, owner, (slot,) = rig()
    p.tombstone(slot)
    with pytest.raises(api().MuxIpcError):
        admit(p, slot)
    assert owner.stopped and not p.confirmed_closed()
    owner.confirmed = True
    assert p.confirmed_closed()


def test_transport_true_cannot_authorize_viewer():
    p, _r, _cb, owner, (slot,) = rig(
        authorize=lambda purpose, slot, registration: purpose is not MuxPurpose.VIEWER
    )
    with pytest.raises(api().MuxIpcError):
        admit(p, slot)
    assert owner.stopped


def test_cancellation_during_cut_callback_wins():
    p, _r, cb, owner, (slot,) = rig()
    cancel = Event()
    original = cb.cut_mux_ingress

    def cancelled(**kwargs):
        value = original(**kwargs)
        cancel.set()
        return value

    cb.cut_mux_ingress = cancelled
    with pytest.raises(api().MuxIpcError):
        admit(p, slot, cancel=cancel)
    assert owner.stopped


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 2),
        ("version", True),
        ("generation", 8),
        ("sequence", 999),
        ("sequence", True),
        ("purpose", "TRANSPORT"),
        ("registration", UUID(int=99).hex),
        ("slot", None),
        ("expiry", 1),
        ("extra", "forbidden"),
    ],
)
def test_foreign_or_changed_cut_reply_fences_original(field, value):
    p, _r, _cb, owner, (slot,) = rig()
    original = p.connection.recv_bytes

    def altered(maximum):
        message, raw = api()._decode(original(maximum))
        message[field] = value
        return api()._encode(message, raw)

    p.connection.recv_bytes = altered
    with pytest.raises(api().MuxIpcError):
        admit(p, slot)
    assert owner.stopped


@pytest.mark.parametrize(
    "field,value",
    [
        ("purpose", "TRANSPORT"),
        ("registration", None),
        ("generation", 8),
        ("sequence", 0),
        ("sequence", True),
        ("version", 2),
        ("slot", None),
        ("expiry", 1),
    ],
)
def test_remote_rejects_cross_purpose_or_scope_request(field, value):
    p, r, _cb, owner, (slot,) = rig()
    original = p.connection.send_bytes

    def altered(raw):
        message, data = api()._decode(raw)
        message[field] = value
        return original(api()._encode(message, data))

    p.connection.send_bytes = altered
    with pytest.raises(api().MuxIpcError):
        admit(p, slot)
    assert r.closed and owner.stopped


def test_twelve_slots_keep_sibling_order_and_exact_credit():
    p, _r, cb, owner, slots = rig(12)
    cuts = [admit(p, s, UUID(int=i + 1)) for i, s in enumerate(slots)]
    for index in range(1, 4):
        for slot in reversed(slots):
            invoke(cb, key(slot, index))
            p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    for slot, cut in zip(slots, cuts, strict=True):
        frames = read(p, slot, cut)
        assert [f.frame.frame_index for f in frames] == [1, 2, 3]
        assert p.credit_usage(slot) == (3, sum(len(key(slot, n)) for n in range(1, 4)))
        p.release_frames(frames)
        assert p.credit_usage(slot) == (0, 0)


def test_inflight_cancel_before_credit_and_double_release_fence():
    p, _r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    invoke(cb, key(slot))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    frames = read(p, slot, cut)
    p.release_frames(frames)
    with pytest.raises(api().MuxIpcError):
        p.release_frames(frames)
    assert owner.stopped


def test_worker_input_is_closed_bounded_and_dispatch_inert():
    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_tvt_bridge import windows_socket_worker as worker

    credentials = LocalDeviceCredentials(
        serial="INERT01", username="inert", password="inert"
    )
    raw = api().make_mux_worker_input(credentials, generation=7, initial_expiry_ms=1000)
    assert len(raw) <= 16384
    decoded, generation, ttl = api().parse_mux_worker_input(raw)
    assert type(decoded) is LocalDeviceCredentials and generation == 7 and ttl == 1000
    epoch = MuxEpochIdentity(7, b"s" * 16)
    callback = CallbackOwner(7, 7)
    callback.bind_mux_epoch(epoch)
    dispatcher = worker.make_mux_dispatch(
        raw, epoch=epoch, callback=callback, deadline_monotonic=time.monotonic() + 0.5
    )
    assert dispatcher.epoch == epoch and not dispatcher.closed


@pytest.mark.parametrize(
    "change",
    ["actor", "extra_credential", "bool_generation", "ttl", "oversize", "duplicate"],
)
def test_worker_input_rejects_extra_authority_or_invalid_input(change):
    import json

    from wso_core.tvt.local_credentials import LocalDeviceCredentials

    credentials = LocalDeviceCredentials(
        serial="INERT01", username="inert", password="inert"
    )
    raw = api().make_mux_worker_input(credentials, generation=7, initial_expiry_ms=1000)
    body = json.loads(raw)
    if change == "actor":
        body["actor"] = "forbidden"
    elif change == "extra_credential":
        body["credentials"]["scope"] = "forbidden"
    elif change == "bool_generation":
        body["generation"] = True
    elif change == "ttl":
        body["initial_expiry_ms"] = 30001
    if change == "oversize":
        raw = b" " * 16385
    elif change == "duplicate":
        raw = raw[:-1] + b',"generation":7}'
    else:
        raw = json.dumps(body).encode()
    with pytest.raises(api().MuxIpcError):
        api().parse_mux_worker_input(raw)


def test_renewal_is_purpose_bound_and_expired_original_cannot_revive():
    p, r, _cb, owner, (_slot,) = rig()
    old = p.deadline
    p.renew(deadline_monotonic=old + 1)
    assert p.deadline == r.deadline == old + 1
    p.cancel.set()
    with pytest.raises(api().MuxIpcError):
        p.renew(deadline_monotonic=old + 2)
    assert owner.stopped


@pytest.mark.parametrize("reason", ["cancel", "caller_expiry"])
def test_cancel_stops_original_while_authority_supplier_blocked(reason):
    p, _r, _cb, owner, (slot,) = rig()
    entered, release = Event(), Event()
    failures = []

    def authorize(purpose, slot, registration):
        entered.set()
        release.wait(1)
        return True

    p.authorize = authorize

    def cut():
        try:
            p.admission_cut(
                slot,
                registration=UUID(int=1),
                cancel=Event(),
                deadline_monotonic=time.monotonic()
                + (0.03 if reason == "caller_expiry" else 5),
            )
        except api().MuxIpcError:
            failures.append(True)

    thread = threading.Thread(target=cut)
    thread.start()
    try:
        assert entered.wait(1)
        if reason == "cancel":
            p.cancel.set()
        until = time.monotonic() + 0.2
        while not owner.stopped and time.monotonic() < until:
            time.sleep(0.005)
        assert owner.stopped
    finally:
        release.set()
        thread.join(1)
    assert failures == [True]


def fragments(raw):
    inner = raw[8:]
    middle = len(inner) // 2
    return tuple(
        struct.pack("<Ii6i", 825307441, -1, 3, 2, len(inner), i, len(part), 0) + part
        for i, part in enumerate((inner[:middle], inner[middle:]), 1)
    )


def test_fragment_cut_and_exact_credit_include_all_fragment_headers():
    p, _r, cb, owner, (slot,) = rig()
    first, second = fragments(key(slot))
    invoke(cb, first)
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    cut = admit(p, slot)
    invoke(cb, second)
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    assert read(p, slot, cut) == () and p.credit_usage(slot) == (0, 0)
    first, second = fragments(key(slot, 2))
    invoke(cb, first)
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    invoke(cb, second)
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    (frame,) = read(p, slot, cut)
    assert p.credit_usage(slot) == (1, len(first) + len(second))
    assert frame.ingress.first > cut.after_ordinal
    assert p.scratch_bytes == 0
    p.release_frames((frame,))


def large_key(slot, index):
    payload = b"\0\0\0\1\x67sps\0\0\0\1\x68pps\0\0\0\1\x65" + bytes(900000)
    raw = bytearray(key(slot, index)[:109] + payload + bytes((-len(payload)) % 4))
    struct.pack_into("<I", raw, 4, len(raw) - 8)
    struct.pack_into("<I", raw, 20, len(raw) - 24)
    struct.pack_into("<i", raw, 48, len(raw) - 68)
    struct.pack_into("<i", raw, 72, len(payload))
    return bytes(raw)


def test_four_mib_budget_is_reserved_before_frame_materialization():
    p, _r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    for index in range(1, 6):
        invoke(cb, large_key(slot, index))
        progress = p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    assert not progress
    frames = read(p, slot, cut)
    assert [f.frame.frame_index for f in frames] == [1, 2, 3, 4]
    assert p.credit_usage(slot) == (4, 4 * len(large_key(slot, 1)))
    p.release_frames(frames)
    assert p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    assert [f.frame.frame_index for f in read(p, slot, cut)] == [5]


def test_pressure_deadline_fences_exact_original_without_dropping_head():
    p, r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    for index in range(1, 17):
        invoke(cb, key(slot, index))
        p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    held = read(p, slot, cut)
    now = [time.monotonic()]
    p.clock = r.clock = lambda: now[0]
    invoke(cb, key(slot, 17))
    assert not p.pump(owner, deadline_monotonic=now[0] + 10)
    assert p._pressure == now[0] + 5
    now[0] += 5.01
    with pytest.raises(api().MuxIpcError):
        p.pump(owner, deadline_monotonic=now[0] + 1)
    assert owner.stopped and p.credit_usage(slot)[0] == 16
    p.release_frames(held)


def test_scratch_is_reserved_before_move_and_refusal_defers_original_bytes(monkeypatch):
    p, _r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    first, second = fragments(key(slot))
    baseline = api()._HOST_BYTES
    monkeypatch.setattr(api(), "MAX_HOST_BYTES", baseline)
    invoke(cb, first)
    assert not p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    assert p.codec.pending_bytes == len(first)
    assert p.credit_usage(slot) == (0, 0) and p.scratch_bytes == 0
    monkeypatch.setattr(api(), "MAX_HOST_BYTES", baseline + (2 << 20))
    assert p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    invoke(cb, second)
    assert p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    assert len(read(p, slot, cut)) == 1
    assert p.scratch_bytes == 0


def test_raw_host_charge_waits_original_retirement_and_returned_credit_stays():
    baseline = api()._HOST_BYTES
    p, _r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    invoke(cb, key(slot))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    held = read(p, slot, cut)
    assert api()._HOST_BYTES == baseline + api().RAW_STAGING_BYTES + len(key(slot))
    assert p.close() and not p.confirmed_closed()
    assert api()._HOST_BYTES == baseline + api().RAW_STAGING_BYTES + len(key(slot))
    owner.confirmed = True
    assert p.confirmed_closed()
    assert api()._HOST_BYTES == baseline + len(key(slot))
    p.release_frames(held)
    assert api()._HOST_BYTES == baseline


def test_constructor_failure_fences_and_retains_raw_reservation_until_confirmation():
    m = api()
    baseline = m._HOST_BYTES
    epoch = MuxEpochIdentity(7, b"s" * 16)
    parent = m.MuxParentAuthority(
        epoch=epoch, authorize=lambda *_: True, clock=time.monotonic
    )
    PARENTS.append(parent)
    owner = Owner()
    with pytest.raises(m.MuxIpcError):
        parent.bind_original(
            owner,
            connection=Pipe(None),
            peer_capability=0,
            deadline_monotonic=time.monotonic() + 1,
            cancel=Event(),
        )
    assert owner.stopped
    assert m._HOST_BYTES == baseline + m.RAW_STAGING_BYTES
    owner.confirmed = True
    assert parent.confirmed_closed()
    assert m._HOST_BYTES == baseline


def test_pipe_send_failure_keeps_original_host_charge():
    baseline = api()._HOST_BYTES
    p, _r, _cb, owner, (slot,) = rig()

    def fail_send(raw):
        raise OSError("inert")

    p.connection.send_bytes = fail_send
    with pytest.raises(api().MuxIpcError):
        admit(p, slot)
    assert owner.stopped and api()._HOST_BYTES == baseline + api().RAW_STAGING_BYTES


@pytest.mark.parametrize("failure", ["deny", "cancel", "expiry", "exception"])
def test_failed_read_handoff_refunds_only_unreturned_frames(failure):
    baseline = api()._HOST_BYTES
    p, _r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    invoke(cb, key(slot))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    returned = read(p, slot, cut)
    invoke(cb, key(slot, 2))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    now = [time.monotonic()]
    p.clock = lambda: now[0]
    deadline = now[0] + 1
    calls = 0

    def authorize(purpose, _slot, _registration):
        nonlocal calls
        if purpose is MuxPurpose.VIEWER:
            calls += 1
            if calls == 2:
                if failure == "deny":
                    return False
                if failure == "cancel":
                    p.cancel.set()
                if failure == "expiry":
                    now[0] = deadline + 0.1
                if failure == "exception":
                    raise ValueError("inert")
        return True

    p.authorize = authorize
    with pytest.raises(api().MuxIpcError):
        p.read_frames(
            slot, cut=cut, max_frames=16, max_bytes=4 << 20, deadline_monotonic=deadline
        )
    assert p.credit_usage(slot) == (1, len(key(slot)))
    assert len(p._held) == 1 and id(returned[0]) in p._held
    owner.confirmed = True
    assert p.confirmed_closed()
    assert api()._HOST_BYTES == baseline + len(key(slot))
    p.release_frames(returned)
    assert api()._HOST_BYTES == baseline


@pytest.mark.parametrize("stage", ["feed", "drain"])
def test_whole_pump_deadline_stops_original_during_codec_supplier(stage):
    p, _r, cb, owner, (slot,) = rig()
    admit(p, slot)
    if stage == "drain":
        invoke(cb, key(slot) + key(slot, 2))
        p.pump(owner, deadline_monotonic=time.monotonic() + 1)
        assert p.codec.pending_bytes > 0
    else:
        invoke(cb, key(slot))
    entered, release = Event(), Event()
    failures = []

    def authorize(purpose, _slot, _registration):
        if purpose is MuxPurpose.SLOT_RETENTION:
            entered.set()
            release.wait(1)
        return True

    p.authorize = authorize
    deadline = time.monotonic() + 0.03

    def pump():
        try:
            p.pump(owner, deadline_monotonic=deadline)
        except api().MuxIpcError:
            failures.append(True)

    thread = threading.Thread(target=pump)
    thread.start()
    try:
        assert entered.wait(1)
        until = time.monotonic() + 0.2
        while not owner.stopped and time.monotonic() < until:
            time.sleep(0.005)
        assert owner.stopped, "original must stop before blocked supplier is released"
        assert p._operation_deadline == deadline
    finally:
        release.set()
        thread.join(1)
    assert failures == [True]
    assert p._operation_deadline is None and p.credit_usage(slot) == (0, 0)


def test_first_key_cannot_cross_cut_expiry_in_final_viewer_supplier():
    p, _r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    invoke(cb, key(slot))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    now = [cut.expires_monotonic - 0.1]
    p.clock = lambda: now[0]
    calls = 0

    def authorize(purpose, _slot, _registration):
        nonlocal calls
        if purpose is MuxPurpose.VIEWER:
            calls += 1
            if calls == 2:
                now[0] = cut.expires_monotonic + 0.1
        return True

    p.authorize = authorize
    with pytest.raises(api().MuxIpcError):
        p.read_frames(
            slot,
            cut=cut,
            max_frames=16,
            max_bytes=4 << 20,
            deadline_monotonic=cut.expires_monotonic + 2,
        )
    assert owner.stopped and slot not in p._activated
    assert p.credit_usage(slot) == (0, 0) and not p._held


def test_consumed_cut_does_not_expire_ongoing_authorized_viewer():
    p, r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    invoke(cb, key(slot))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    p.release_frames(read(p, slot, cut))
    now = cut.expires_monotonic + 0.1
    p.clock = r.clock = lambda: now
    invoke(cb, key(slot, 2))
    p.pump(owner, deadline_monotonic=now + 2)
    frames = p.read_frames(
        slot, cut=cut, max_frames=16, max_bytes=4 << 20, deadline_monotonic=now + 2
    )
    assert [frame.frame.frame_index for frame in frames] == [2]
    p.release_frames(frames)


def test_initial_cut_watchdog_stops_blocked_final_viewer_check():
    p, _r, cb, owner, (slot,) = rig()
    cut = p.admission_cut(
        slot,
        registration=UUID(int=1),
        cancel=Event(),
        deadline_monotonic=time.monotonic() + 0.08,
    )
    invoke(cb, key(slot))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    entered, release = Event(), Event()
    failures = []
    calls = 0

    def authorize(purpose, _slot, _registration):
        nonlocal calls
        if purpose is MuxPurpose.VIEWER:
            calls += 1
            if calls == 2:
                entered.set()
                release.wait(1)
        return True

    p.authorize = authorize

    def first_read():
        try:
            read(p, slot, cut)
        except api().MuxIpcError:
            failures.append(True)

    thread = threading.Thread(target=first_read)
    thread.start()
    try:
        assert entered.wait(1)
        until = time.monotonic() + 0.3
        while not owner.stopped and time.monotonic() < until:
            time.sleep(0.005)
        assert owner.stopped
        assert p._operation_deadline == cut.expires_monotonic
    finally:
        release.set()
        thread.join(1)
    assert failures == [True] and slot not in p._activated
    assert p.credit_usage(slot) == (0, 0) and not p._held


@pytest.mark.parametrize("stage", ["read", "reserve", "scratch"])
def test_close_retains_live_operation_credit_until_supplier_unwinds(stage):
    baseline = api()._HOST_BYTES
    p, _r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    returned = ()
    if stage != "scratch":
        invoke(cb, key(slot))
        p.pump(owner, deadline_monotonic=time.monotonic() + 1)
        returned = read(p, slot, cut)
        invoke(cb, key(slot, 2))
        if stage == "read":
            p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    else:
        invoke(cb, fragments(key(slot))[0])
    entered, release = Event(), Event()
    failures = []
    viewer_calls = 0

    def authorize(purpose, _slot, _registration):
        nonlocal viewer_calls
        if purpose is MuxPurpose.VIEWER:
            viewer_calls += 1
        blocked = (
            stage == "read"
            and purpose is MuxPurpose.VIEWER
            and viewer_calls == 2
            or stage == "reserve"
            and purpose is MuxPurpose.SLOT_RETENTION
            and p._pending_credit is not None
            or stage == "scratch"
            and purpose is MuxPurpose.TRANSPORT
            and p.scratch_bytes > 0
        )
        if blocked:
            entered.set()
            release.wait(2)
        return True

    p.authorize = authorize

    def operation():
        try:
            deadline = time.monotonic() + 0.05
            if stage == "read":
                p.read_frames(
                    slot,
                    cut=cut,
                    max_frames=16,
                    max_bytes=4 << 20,
                    deadline_monotonic=deadline,
                )
            else:
                p.pump(owner, deadline_monotonic=deadline)
        except api().MuxIpcError:
            failures.append(True)

    thread = threading.Thread(target=operation)
    thread.start()
    try:
        assert entered.wait(1)
        retained = api()._HOST_BYTES
        assert retained > baseline + api().RAW_STAGING_BYTES
        until = time.monotonic() + 0.3
        while not owner.stopped and time.monotonic() < until:
            time.sleep(0.005)
        assert owner.stopped
        owner.confirmed = True  # proves only the inert original, not this operation
        assert p.close(timeout=0.01) is False
        assert p.confirmed_closed() is False
        assert thread.is_alive() and p._operation_deadline is not None
        assert p._active_invocations
        assert api()._HOST_BYTES == retained
        assert not p.connection.closed
        if stage == "reserve":
            assert p._pending_credit is not None
        if stage == "scratch":
            assert p.scratch_bytes > 0
    finally:
        release.set()
        thread.join(1)
    assert not thread.is_alive() and failures == [True]
    assert not p._active_invocations
    assert p.confirmed_closed()
    assert api()._HOST_BYTES == baseline + sum(len(key(slot)) for _ in returned)
    assert p.credit_usage(slot)[0] == len(returned)
    p.release_frames(returned)
    assert api()._HOST_BYTES == baseline


def test_reentrant_close_cannot_confirm_or_refund_its_own_active_reader():
    baseline = api()._HOST_BYTES
    p, _r, cb, owner, (slot,) = rig()
    cut = admit(p, slot)
    invoke(cb, key(slot))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    calls = 0
    observed = []

    def authorize(purpose, _slot, _registration):
        nonlocal calls
        if purpose is MuxPurpose.VIEWER:
            calls += 1
            if calls == 2:
                retained = api()._HOST_BYTES
                owner.confirmed = True
                observed.append(
                    (
                        p.close(),
                        p.confirmed_closed(),
                        api()._HOST_BYTES == retained,
                        p.connection.closed,
                    )
                )
        return True

    p.authorize = authorize
    with pytest.raises(api().MuxIpcError):
        read(p, slot, cut)
    assert observed == [(False, False, True, False)]
    assert p.confirmed_closed() and api()._HOST_BYTES == baseline
    assert p.credit_usage(slot) == (0, 0)


def test_wire_projection_uses_actual_accepts_and_retained_parked_media():
    p, _remote, callback, owner, slots = rig(2)
    assert callable(getattr(p, "wire_observation", None)), (
        "original wire projection missing"
    )
    first, second = slots
    assert p.wire_observation(first) == ((2, 1, 0x10000501, 1, False), None)
    assert p.wire_observation(second) == ((2, 1, 0x10000501, 2, False), None)
    before = api().media_credit_usage()
    invoke(callback, key(second))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    assert p.wire_observation(second) == (
        (2, 1, 0x10000501, 2, False),
        (0, 1, 65537, 0),
    )
    assert p.wire_observation(first)[1] is None
    assert p.credit_usage(second) == (0, 0)  # No viewer cut; parsed then discarded.
    assert api().media_credit_usage() == before
    marker = admit(p, first)
    assert p.wire_observation(first)[0][3] == 1
    assert marker.control_sequence != 1  # Cut sequence is not wire ACK sequence.


@pytest.mark.parametrize(
    "change",
    ["slot", "owner", "child", "connection", "codec", "epoch", "denied", "stopped"],
)
def test_wire_projection_rechecks_captured_original_after_current(change):
    from types import SimpleNamespace

    p, _remote, _callback, owner, (slot,) = rig()
    assert callable(getattr(p, "wire_observation", None)), (
        "original wire projection missing"
    )
    original = (p._owner, p.connection, p.codec, p.epoch)

    def current(purpose, given, registration):
        assert (
            purpose is MuxPurpose.SLOT_RETENTION
            and given is slot
            and registration is None
        )
        assert p._wire_lock.acquire(blocking=False), (
            "supplier ran under diagnostic lock"
        )
        p._wire_lock.release()
        if change == "slot":
            p._slots[slot.channel] = replace(slot)
        if change == "owner":
            p._owner = Owner()
        if change == "child":
            owner.child = SimpleNamespace(poll=lambda: None)
        if change == "connection":
            p.connection = object()
        if change == "codec":
            p.codec = object()
        if change == "epoch":
            p.epoch = MuxEpochIdentity(8, b"x" * 16)
        if change == "stopped":
            p.close(0)
        return change != "denied"

    p.authorize = current
    try:
        assert p.wire_observation(slot) == (None, None)
        if change != "stopped":
            assert not p.failed and not owner.stopped
    finally:
        p._owner, p.connection, p.codec, p.epoch = original
        p._slots[slot.channel] = slot
        if hasattr(owner, "child"):
            del owner.child
        p.authorize = lambda *args: True


def test_wire_projection_absence_does_not_mint_ack_or_fence_unknown_slot():
    p, _remote, callback, owner, _slots = rig(0)
    assert callable(getattr(p, "wire_observation", None)), (
        "original wire projection missing"
    )
    slot = MuxSlotIdentity(p.epoch, b"c" * 16, b"t" * 16, 2)
    assert p.wire_observation(slot) == (None, None)
    p.register_slot(slot, channel_number=0)
    assert p.wire_observation(slot) == (None, None)
    p.prepare_open(slot, request_guid=b"r" * 16, sequence=7)
    assert p.wire_observation(slot) == (None, None)
    invoke(callback, packet(0x10000501, sequence=7))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    assert p.wire_observation(replace(slot)) == (None, None)
    assert p.wire_observation(slot) == ((2, 1, 0x10000501, 7, False), None)
    assert not p.failed


def test_wire_projection_rejects_child_substituted_before_observation():
    from types import SimpleNamespace

    p, _remote, _callback, owner, (slot,) = rig()
    owner.child = SimpleNamespace(poll=lambda: None)
    try:
        assert p.wire_observation(slot) == (None, None)
        assert not p.failed
    finally:
        del owner.child


def test_wire_projection_keeps_current_supplier_outside_cleanup_barrier():
    from threading import Event, Thread

    p, _remote, _callback, owner, (slot,) = rig()
    entered, release = Event(), Event()
    results = []

    def current(*args):
        entered.set()
        assert release.wait(2)
        return True

    p.authorize = current
    reader = Thread(target=lambda: results.append(p.wire_observation(slot)))
    reader.start()
    try:
        assert entered.wait(1)
        owner.confirmed = True
        assert not p.close(0)
        assert p._active_invocations
        release.set()
        reader.join(1)
        assert not reader.is_alive()
        assert results == [(None, None)]
        assert p.confirmed_closed()
    finally:
        release.set()
        reader.join(1)


def test_wire_projection_read_does_not_consume_sequence_or_credit():
    p, _remote, callback, owner, (slot,) = rig()
    cut = admit(p, slot)
    invoke(callback, key(slot))
    p.pump(owner, deadline_monotonic=time.monotonic() + 1)
    before = (
        p._sequence,
        p.credit_usage(slot),
        api().media_credit_usage(),
        len(p._held),
    )
    for _ in range(4):
        assert p.wire_observation(slot) == (
            (2, 1, 0x10000501, 1, False),
            (0, 1, 65537, 0),
        )
    assert (
        p._sequence,
        p.credit_usage(slot),
        api().media_credit_usage(),
        len(p._held),
    ) == before
    assert len(read(p, slot, cut)) == 1
