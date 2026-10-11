"""Inert borrowed-memory provenance tests; no DLL, recorder or authority proof."""

import ctypes as ct
import struct
import threading
import time
from uuid import UUID

import pytest
from wso_core.tvt.local_live import LiveError
from wso_core.tvt.local_live_mux import MultiplexLiveCodec
from wso_core.tvt.local_media_mux_types import (
    MAX_ORDINAL,
    IngressSpan,
    MuxEpochIdentity,
    MuxSlotIdentity,
)
from wso_tvt_bridge import windows_socket_worker as w


def owner():
    result = w.CallbackOwner(7, 7)
    assert hasattr(result, "bind_mux_epoch"), "original mux epoch binding is missing"
    epoch = MuxEpochIdentity(7, b"s" * 16)
    result.bind_mux_epoch(epoch)
    return result, MuxSlotIdentity(epoch, b"c" * 16, b"t" * 16, 2)


def invoke(callback, raw, **changes):
    buffer = ct.create_string_buffer(raw)
    args = {
        "this": callback.this_address,
        "handle": callback.handle,
        "data": ct.addressof(buffer),
        "length": len(raw),
        "opaque": 0,
        "context": callback.context_address,
    }
    return callback._data(**(args | changes))


def cut(callback, default_slot, **changes):
    args = {
        "registration": UUID(int=1),
        "slot": default_slot,
        "control_sequence": 1,
        "expires_monotonic": time.monotonic() + 10,
    }
    return callback.cut_mux_ingress(**(args | changes))


def packet(command, body=b"", *, flags=2, sequence=1, declared=0):
    inner = struct.pack("<HBBIII", 5, flags, 1, command, sequence, declared) + body
    return struct.pack("<II", 825307441, len(inner)) + inner


def key(slot, index=1):
    payload = b"\0\0\0\1\x67sps\0\0\0\1\x68pps\0\0\0\1\x65inert"
    extension = struct.pack("<BBH4shhIB", 0, 0, 0, b"H264", 640, 480, 0, 0)
    body = struct.pack(
        "<BBBBiQQ",
        0,
        len(extension),
        0x80,
        0,
        len(payload),
        116444736000010000,
        116444736000020000,
    )
    body += extension + payload + bytes((-len(payload)) % 4)
    media = (
        struct.pack("<4sHBB", b"SHFL", 1, 2, 0)
        + slot.channel
        + struct.pack("<iQii", len(body), 116444736000000000, index, 0)
        + body
    )
    return packet(65537, media, flags=0, sequence=0, declared=len(media))


def test_callback_before_cut_cannot_gain_post_cut_origin():
    callback, slot = owner()
    assert invoke(callback, b"before") == 6
    held = callback.take_mux_batch()
    expiry = time.monotonic() + 10
    marker = cut(callback, slot, expires_monotonic=expiry)
    assert (
        marker.epoch,
        marker.slot,
        marker.registration,
        marker.control_sequence,
        marker.after_ordinal,
        marker.expires_monotonic,
    ) == (slot.epoch, slot, UUID(int=1), 1, 1, expiry)
    assert invoke(callback, b"after") == 5
    (fresh,) = callback.take_mux_batch()
    assert held[0].data == b"before" and held[0].span == IngressSpan(1, 1)
    assert fresh.data == b"after" and fresh.span == IngressSpan(2, 2)
    assert held[0].span.first <= marker.after_ordinal < fresh.span.first
    assert callback.take_mux_batch() == ()


@pytest.mark.parametrize("held_at", ["fifo", "returned", "assembled", "partial"])
def test_complete_and_partial_key_held_before_cut_ineligible(held_at):
    callback, slot = owner()
    codec = MultiplexLiveCodec(
        epoch=slot.epoch, peer_capability=4, authorize=lambda _: True
    )
    codec.register_slot(slot, channel_number=0)
    codec.open_slot(slot, request_guid=b"r" * 16, sequence=1)
    invoke(callback, packet(0x10000501))
    for chunk in callback.take_mux_batch():
        codec.feed(chunk, generation=7)
    raw = key(slot)
    # Split within the parameter-set payload; even its tail must retain origin.
    split = len(raw) - 18
    invoke(callback, raw[:split] if held_at == "partial" else raw)
    held = () if held_at == "fifo" else callback.take_mux_batch()
    frames = ()
    if held_at in ("assembled", "partial"):
        for chunk in held:
            frames += codec.feed(chunk, generation=7)
    marker = cut(callback, slot)
    if held_at == "partial":
        assert frames == ()
        invoke(callback, raw[split:])
    if held_at in ("fifo", "partial"):
        held = callback.take_mux_batch()
    if held_at != "assembled":
        for chunk in held:
            frames += codec.feed(chunk, generation=7)
    (frame,) = frames
    assert frame.ingress.first == 2 <= marker.after_ordinal
    assert frame.ingress.last == (3 if held_at == "partial" else 2)
    invoke(callback, key(slot, index=2))
    (fresh,) = codec.feed(callback.take_mux_batch()[0], generation=7)
    assert fresh.ingress.first > marker.after_ordinal


def test_cut_races_nonblocking_copy(monkeypatch):
    callback, slot = owner()
    copying, release, cutting, finished = (threading.Event() for _ in range(4))
    original = ct.string_at
    results, cuts = [], []

    def held_copy(pointer, length):
        copying.set()
        assert release.wait(2)
        return original(pointer, length)

    def request_cut():
        cutting.set()
        cuts.append(cut(callback, slot))
        finished.set()

    monkeypatch.setattr(w.ct, "string_at", held_copy)
    producer = threading.Thread(target=lambda: results.append(invoke(callback, b"key")))
    consumer = threading.Thread(target=request_cut)
    producer.start()
    try:
        assert copying.wait(2)
        assert callback._mux_ordinal == 1  # Assigned before application-visible copy.
        consumer.start()
        assert cutting.wait(2)
        assert not finished.wait(0.02)
    finally:
        release.set()
        producer.join(2)
        if consumer.ident is not None:
            consumer.join(2)
    assert not producer.is_alive() and not consumer.is_alive()
    assert results == [3] and cuts[0].after_ordinal == 1
    assert callback.take_mux_batch()[0].span.first <= cuts[0].after_ordinal


@pytest.mark.parametrize("limit", ["chunks", "bytes", "counter"])
def test_ingress_overflow_and_counter_wrap_sticky(limit):
    callback, slot = owner()
    if limit == "chunks":
        for _ in range(256):
            assert invoke(callback, b"x") == 1
    elif limit == "bytes":
        assert invoke(callback, b"x" * (1 << 20)) == 1 << 20
    else:
        callback._mux_ordinal = MAX_ORDINAL
    assert invoke(callback, b"x") == 0
    assert callback.failed and callback.take_mux_batch() == ()
    with pytest.raises(LiveError):
        cut(callback, slot)
    assert invoke(callback, b"x") == 0


@pytest.mark.parametrize(
    "foreign", ["this", "handle", "context", "opaque", "generation"]
)
def test_mux_foreign_context_sticky(foreign):
    callback, slot = owner()
    changes = {foreign: 999}
    if foreign == "generation":
        callback.context.value += 1
        changes = {}
    assert invoke(callback, b"x", **changes) == 0
    assert callback.failed and callback.take_mux_batch() == ()
    with pytest.raises(LiveError):
        cut(callback, slot)


def test_mux_callback_cannot_wait_on_control_lock():
    callback, _ = owner()
    callback.lock.acquire()
    try:
        assert invoke(callback, b"x") == 0
    finally:
        callback.lock.release()
    assert callback.failed


def test_mux_copies_borrowed_memory_before_return_and_releases_queue_credit():
    callback, slot = owner()
    raw = ct.create_string_buffer(b"key")
    assert (
        callback.data_callback(
            callback.this_address,
            callback.handle,
            ct.addressof(raw),
            3,
            0,
            callback.context_address,
        )
        == 3
    )
    raw[0] = b"z"
    (held,) = callback.take_mux_batch()
    assert held.data == b"key" and callback.used == 0
    assert callback in w.RETAINED
    assert invoke(callback, b"x" * (1 << 20)) == 1 << 20
    marker = cut(callback, slot)
    assert marker.after_ordinal == 2 and held.span.last == 1


@pytest.mark.parametrize("denial", ["failed", "context", "generation"])
def test_denial_during_copy_cannot_return_admitted_bytes(monkeypatch, denial):
    callback, slot = owner()
    original = ct.string_at

    def denied_copy(pointer, length):
        if denial == "failed":
            callback.mark_failed()
        elif denial == "context":
            callback.context.value += 1
        else:
            callback.generation += 1
            callback.context.value += 1
        return original(pointer, length)

    monkeypatch.setattr(w.ct, "string_at", denied_copy)
    assert invoke(callback, b"key") == 0
    assert callback.failed and callback.take_mux_batch() == ()
    with pytest.raises(LiveError):
        cut(callback, slot)


@pytest.mark.parametrize("bad", ["replayed", "context", "generation"])
def test_cut_rechecks_original_and_never_reuses_control_sequence(bad):
    callback, slot = owner()
    assert cut(callback, slot).after_ordinal == 0
    if bad == "context":
        callback.context.value += 1
    elif bad == "generation":
        callback.generation += 1
        callback.context.value += 1
    with pytest.raises(LiveError):
        cut(callback, slot, control_sequence=1 if bad == "replayed" else 2)
    assert callback.failed


@pytest.mark.parametrize(
    "bad", ["epoch", "registration", "sequence", "overflow", "expiry", "nan"]
)
def test_cut_bad_binding_is_sticky(bad):
    callback, slot = owner()
    changes = {}
    if bad == "epoch":
        changes["slot"] = MuxSlotIdentity(
            MuxEpochIdentity(7, b"f" * 16), slot.channel, slot.task, 2
        )
    elif bad == "registration":
        changes["registration"] = UUID(int=0)
    elif bad == "sequence":
        changes["control_sequence"] = 0
    elif bad == "overflow":
        changes["control_sequence"] = MAX_ORDINAL + 1
    else:
        changes["expires_monotonic"] = 1.0 if bad == "expiry" else float("nan")
    with pytest.raises(LiveError):
        cut(callback, slot, **changes)
    assert callback.failed


@pytest.mark.parametrize(
    "mode", ["rebind", "legacy", "wrong_generation", "pending", "closed"]
)
def test_mux_binding_is_one_shot_and_separate(mode):
    callback = w.CallbackOwner(7, 7)
    assert hasattr(callback, "bind_mux_epoch"), "original mux epoch binding is missing"
    epoch = MuxEpochIdentity(7, b"s" * 16)
    if mode == "rebind":
        callback.bind_mux_epoch(epoch)
    elif mode == "legacy":
        assert callback.claim_first_live()
    elif mode == "wrong_generation":
        epoch = MuxEpochIdentity(8, b"s" * 16)
    elif mode == "pending":
        invoke(callback, b"old")
    else:
        callback.closed = True
    with pytest.raises(LiveError):
        callback.bind_mux_epoch(epoch)


def test_mux_cannot_drain_through_legacy_or_claim_first():
    callback, _ = owner()
    assert not callback.claim_first_live()
    invoke(callback, b"safe")
    assert callback.take_live_batch() is None and callback.take() is None
    assert callback.take_mux_batch()[0].data == b"safe"


def test_legacy_first_claim_and_batches_unchanged():
    callback = w.CallbackOwner(7, 1)
    assert callback.claim_first_live() and not callback.claim_first_live()
    invoke(callback, b"a")
    invoke(callback, b"bc")
    assert callback.take_live_batch() == b"abc"
    assert callback.take_live_batch() is None and callback.used == 0
