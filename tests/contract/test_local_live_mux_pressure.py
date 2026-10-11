"""Common host/encoded pressure; entirely inert ports and callback memory."""

from uuid import uuid4

import pytest
from wso_core.tvt.local_media_mux_types import MuxEpochIdentity, MuxSlotIdentity
from wso_tvt_bridge import local_live_mux_ipc as ipc


def test_media_and_original_encoded_frames_share_slot_credit():
    assert hasattr(ipc, "reserve_media_credit"), "common media credits missing"
    slot = MuxSlotIdentity(MuxEpochIdentity(7, b"s" * 16), b"c" * 16, b"t" * 16, 2)
    before = ipc.media_credit_usage()
    token = ipc.reserve_media_credit(
        slot=slot, registration=uuid4(), frames=16, bytes=16, stage="decode"
    )
    assert token is not None
    assert (
        ipc.reserve_media_credit(
            slot=slot, registration=uuid4(), frames=1, bytes=1, stage="source"
        )
        is None
    )
    ipc.release_media_credit(token)
    assert ipc.media_credit_usage() == before
    with pytest.raises(ipc.MuxIpcError):
        ipc.release_media_credit(token)


def test_rgb_and_encoded_reservations_share_one_host_limit():
    assert hasattr(ipc, "reserve_media_credit"), "common media credits missing"
    before = ipc.media_credit_usage()
    token = ipc.reserve_media_credit(
        slot=None,
        registration=uuid4(),
        frames=0,
        bytes=ipc.MAX_HOST_BYTES - before[0],
        stage="raw",
    )
    try:
        assert token is not None
        assert (
            ipc.reserve_media_credit(
                slot=None, registration=uuid4(), frames=1, bytes=1, stage="source"
            )
            is None
        )
        assert (
            ipc.reserve_media_credit(
                slot=None, registration=uuid4(), frames=0, bytes=1, stage="rgb"
            )
            is None
        )
    finally:
        ipc.release_media_credit(token)
    assert ipc.media_credit_usage() == before


def test_original_open_send_uses_codec_bytes_once_outside_remote_lock():
    import threading
    import time

    from test_local_live_mux_ipc import PARENTS, Owner, Pipe
    from wso_tvt_bridge.windows_socket_worker import CallbackOwner

    epoch = MuxEpochIdentity(7, b"s" * 16)
    callback = CallbackOwner(7, 7)
    callback.bind_mux_epoch(epoch)
    sent = []
    remote = None

    def send(raw):
        assert remote._lock.acquire(blocking=False), "native send under control lock"
        remote._lock.release()
        sent.append(raw)
        return len(raw)

    assert hasattr(ipc.MuxParentAuthority, "send_open"), "native open port missing"
    remote = ipc.MuxRemoteAuthority(
        epoch=epoch,
        callback=callback,
        deadline_monotonic=time.monotonic() + 20,
        peer_capability=4,
        native_send=send,
    )
    parent = ipc.MuxParentAuthority(
        epoch=epoch, authorize=lambda *args: True, clock=time.monotonic
    )
    PARENTS.append(parent)
    owner = Owner()
    try:
        parent.bind_original(
            owner,
            connection=Pipe(remote),
            peer_capability=4,
            deadline_monotonic=time.monotonic() + 20,
            cancel=threading.Event(),
        )
        slot = MuxSlotIdentity(epoch, b"c" * 16, b"t" * 16, 2)
        parent.register_slot(slot, channel_number=3)
        raw = parent.prepare_open(slot, request_guid=b"r" * 16, sequence=6)
        parent.send_open(
            slot, deadline_monotonic=time.monotonic() + 1, cancel=threading.Event()
        )
        assert sent == [raw]
        with pytest.raises(ipc.MuxIpcError):
            parent.send_open(
                slot, deadline_monotonic=time.monotonic() + 1, cancel=threading.Event()
            )
        assert len(sent) == 1
    finally:
        owner.confirmed = True
        parent.close()
        PARENTS.remove(parent)


def test_park_discard_and_retention_heartbeat_no_blanket_allow():
    import time

    from test_local_live_mux_ipc import PARENTS, admit, rig
    from test_local_mux_callback import invoke, key
    from wso_core.tvt.local_media_mux_types import MuxPurpose

    allowed = [True]

    def authorize(purpose, slot, registration):
        return purpose is MuxPurpose.TRANSPORT or allowed[0]

    parent, remote, callback, owner, (slot,) = rig(authorize=authorize)
    sent = []
    try:
        admit(parent, slot)
        parent.park(slot)
        invoke(callback, key(slot))
        parent.pump(owner, deadline_monotonic=time.monotonic() + 1)
        assert parent.credit_usage(slot) == (0, 0)
        remote._native_heartbeat = lambda: sent.append(True)
        assert hasattr(parent, "heartbeat"), "retention-bound heartbeat missing"
        parent.heartbeat(deadline_monotonic=time.monotonic() + 1)
        assert sent == [True]
        allowed[0] = False
        with pytest.raises(ipc.MuxIpcError):
            parent.heartbeat(deadline_monotonic=time.monotonic() + 1)
        assert sent == [True]
    finally:
        owner.confirmed = True
        parent.close()
        PARENTS.remove(parent)


def test_sibling_stall_epoch_pressure_fences_at_five_seconds():
    import time

    from test_local_live_mux_ipc import PARENTS, admit, read, rig
    from test_local_mux_callback import invoke, key

    parent, remote, callback, owner, (blocked, sibling) = rig(2)
    held = ()
    try:
        cut = admit(parent, blocked)
        admit(parent, sibling, uuid4())
        for index in range(1, 17):
            invoke(callback, key(blocked, index))
            parent.pump(owner, deadline_monotonic=time.monotonic() + 1)
        held = read(parent, blocked, cut)
        now = [time.monotonic()]
        parent.clock = remote.clock = lambda: now[0]
        invoke(callback, key(blocked, 17) + key(sibling, 1))
        assert not parent.pump(owner, deadline_monotonic=now[0] + 10)
        assert parent._pressure == now[0] + 5
        assert parent.credit_usage(sibling) == (0, 0)
        assert parent.pending_raw_bytes <= 1 << 20
        now[0] += 5
        with pytest.raises(ipc.MuxIpcError):
            parent.pump(owner, deadline_monotonic=now[0] + 1)
        assert owner.stopped and parent.credit_usage(blocked)[0] == 16
        parent.release_frames(held)
        held = ()
        assert parent.credit_usage(blocked) == (0, 0)
    finally:
        if held:
            parent.release_frames(held)
        owner.confirmed = True
        parent.close()
        PARENTS.remove(parent)


def test_media_credit_blocks_original_codec_using_same_slot_counter():
    import time

    from test_local_live_mux_ipc import PARENTS, admit, rig
    from test_local_mux_callback import invoke, key

    parent, _remote, callback, owner, (slot,) = rig()
    token = None
    try:
        admit(parent, slot)
        token = ipc.reserve_media_credit(
            slot=slot, registration=uuid4(), frames=16, bytes=16, stage="decode"
        )
        invoke(callback, key(slot))
        assert not parent.pump(owner, deadline_monotonic=time.monotonic() + 1)
        assert parent.credit_usage(slot) == (0, 0)
        ipc.release_media_credit(token)
        token = None
        assert parent.pump(owner, deadline_monotonic=time.monotonic() + 1)
        assert parent.credit_usage(slot)[0] == 1
    finally:
        if token is not None:
            ipc.release_media_credit(token)
        owner.confirmed = True
        parent.close()
        PARENTS.remove(parent)
