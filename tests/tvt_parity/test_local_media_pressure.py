"""Source admission reserves bounded credit while exact decoder ownership waits."""

import asyncio
import time
from types import SimpleNamespace

import pytest
from wso_tvt_media import native_source

from tests.tvt_parity.test_local_media_format_transition import (
    Decoders,
    Native,
    picture,
    until,
)
from tests.tvt_parity.test_local_media_source import open_source


class ReservedNative(Native):
    def __init__(self):
        super().__init__()
        self.reads = 0

    def read_frames(self, _lease, *, max_frames, max_bytes, deadline_ms):
        self.reads += 1
        assert 1 <= max_frames <= 16 and 1 <= max_bytes <= 4 * 1024 * 1024
        with self.items.mutex:
            if (
                self.items.queue
                and len(self.items.queue[0].private_bytes()) > max_bytes
            ):
                return ()  # Exact provider behavior: retain a head that cannot fit.
        return super().read_frames(_lease)


@pytest.mark.parametrize("rotation", [False, True])
async def test_full_source_fifo_waits_without_pulling_unreserved_frames(
    monkeypatch, rotation
):
    native, decoders = ReservedNative(), Decoders(monkeypatch)
    source = open_source(native)
    source.start()
    try:
        if rotation:
            native.items.put(picture(1, 352, 240))
            await source.binding()
            await source.recv()
            decoders.decode_entered.clear()
        decoders.decode_release.clear()
        first = 2 if rotation else 1
        native.items.put(picture(first, 1280, 720))
        await until(decoders.decode_entered.is_set)
        # The decoder owns one admitted packet; exactly sixteen queued packets
        # fit. Further original inputs must remain upstream, not over-read/dropped.
        for ordinal in range(first + 1, first + 20):
            native.items.put(picture(ordinal, 1280, 720))
        await until(lambda: len(source._encoded) == 16 or not source.alive())
        await asyncio.sleep(0.05)
        assert source.alive(), (
            "a bounded decoder launch pause must apply producer pressure"
        )
        assert len(source._encoded) == 16
        assert native.items.qsize() == 3
        decoders.decode_release.set()
        await until(lambda: len(decoders.packets) == first + 19 or not source.alive())
        assert source.alive()
        assert [packet.ordinal for packet in decoders.packets] == list(
            range(1, first + 20)
        )
    finally:
        decoders.decode_release.set()
        await source.close()


@pytest.mark.parametrize("ending", ["stop", "revoke", "timeout"])
async def test_pressure_ends_with_exact_decoder_retirement(monkeypatch, ending):
    clock = [100.0]
    monkeypatch.setattr(
        native_source,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0], sleep=time.sleep),
    )
    native, decoders = ReservedNative(), Decoders(monkeypatch)
    decoders.decode_release.clear()
    source = open_source(native)
    events = []
    source._observe = lambda stage, reason: events.append((stage, reason))
    source.start()
    closing = None
    try:
        for index in range(1, 22):
            native.items.put(picture(index, 1280, 720))
        await until(lambda: source._pressure_deadline is not None)
        if ending == "timeout":
            clock[0] = 104.99
            await asyncio.sleep(0.06)
            assert source.alive()
            clock[0] = 105.0
        elif ending == "revoke":
            native.active = False
        else:
            closing = asyncio.create_task(source.close())
        await until(lambda: not source.alive())
        assert not source._decoder_done.is_set()
        assert len(decoders.owners) == 1 and not decoders.owners[0].closed
        assert source._encoded_bytes == 0 and not source._encoded
        if closing:
            assert not closing.done()
        if ending == "timeout":
            assert ("ingress_queue", "wait_timeout") in events
        decoders.decode_release.set()
        await source.close()
        assert decoders.owners[0].closed and source.produced_frames == 0
    finally:
        decoders.decode_release.set()
        await source.close()
        if closing:
            await closing


async def test_insufficient_byte_credit_retains_upstream_head_without_busy_loop(
    monkeypatch,
):
    native, decoders = ReservedNative(), Decoders(monkeypatch)
    decoders.decode_release.clear()
    source = open_source(native)
    source.start()
    try:
        native.items.put(picture(1, 1280, 720))
        await until(decoders.decode_entered.is_set)
        payload = b"\0\0\0\1\x02\x01\x80" + b"x" * (1024 * 1024)
        for index in range(2, 7):
            native.items.put(picture(index, 1280, 720, key=False, payload=payload))
        await until(
            lambda: source._pressure_deadline is not None and len(source._encoded) == 3
        )
        assert source._encoded_bytes < 4 * 1024 * 1024
        reads = native.reads
        await asyncio.sleep(0.16)
        assert native.reads - reads <= 4 and native.items.qsize() == 2
        assert source.alive()
        decoders.decode_release.set()
        await until(lambda: len(decoders.packets) == 6)
        assert [packet.ordinal for packet in decoders.packets] == [1, 2, 3, 4, 5, 6]
        assert source.alive() and source._pressure_deadline is None
    finally:
        decoders.decode_release.set()
        await source.close()


async def test_original_source_and_parent_resume_exact_ipc_after_1800ms_launch(
    monkeypatch,
):
    import struct
    import threading

    from wso_tvt_bridge.local_live_ipc import LiveRemoteAuthority
    from wso_tvt_bridge.local_live_provider import OwnedLocalLiveSession

    from tests.contract.test_local_live_provider import helpers, sub_parent_setup

    parent, setup = sub_parent_setup()
    parent.deadline = time.monotonic() + 20
    parent._authorized = True
    parent._setup(setup)
    fixture = helpers()
    remote = LiveRemoteAuthority(
        parent.worker_connection, parent.generation, parent.deadline
    )
    outcomes = []
    producer_stop = threading.Event()
    routing = b"O" * 16 + b"S" * 16 + b"C" * 16 + bytes(4) + b"T" * 16 + bytes(4)

    def producer():
        try:
            remote.envelope(
                fixture.live_packet(0x10000505, bytes(72) + struct.pack("<i", 0))
            )
            for index in range(1, 41):
                payload = b"\0\0\0\1\x67\x80\0\0\0\1\x68\x80\0\0\0\1\x65\x80"
                extension = struct.pack("<BBH4shhIB", 0, 0, 0, b"H264", 64, 48, 0, 0)
                body = struct.pack(
                    "<BBBBiQQ",
                    0,
                    17,
                    0,
                    0,
                    len(payload),
                    116444736000000000 + index * 1000000,
                    116444736000000000 + index * 1000000,
                )
                body += extension + payload + bytes((-len(payload)) % 4)
                media = struct.pack("<4sHBB", b"RAW!", 6, 2, 1) + b"C" * 16
                media += (
                    struct.pack(
                        "<iQii",
                        len(body),
                        116444736000000000 + index * 1000000,
                        index,
                        0,
                    )
                    + body
                )
                remote.envelope(fixture.live_packet(65537, routing + media))
                outcomes.append(index)
            producer_stop.wait(5)
        finally:
            remote.close()

    producer_thread = threading.Thread(target=producer)
    producer_thread.start()
    while not parent.ready:
        assert parent.pump(lambda: True)
        await asyncio.sleep(0.001)
    owner = SimpleNamespace(confirmed=False, child=SimpleNamespace(poll=lambda: None))
    session = OwnedLocalLiveSession(owner, parent)

    class Core(Native):
        def read_frames(self, _lease, *, max_frames, max_bytes, deadline_ms):
            # After all bounded inputs have been delivered, keep this inert
            # source alive; real native sessions continue supplying input.
            if len(decoders.packets) == 40:
                time.sleep(0.005)
                return ()
            return session.read_frames(
                max_frames=max_frames,
                max_bytes=max_bytes,
                deadline_monotonic=time.monotonic() + deadline_ms / 1000,
                current=lambda: self.active,
            )

    decoders = Decoders(monkeypatch)
    decoders.decode_release.clear()
    source = open_source(Core())
    source.start()
    try:
        await until(lambda: source._pressure_deadline is not None)
        await asyncio.sleep(1.8)
        assert source.alive() and len(source._encoded) == 16
        # Model the executor sweep while its source ingress has no credit.
        for _ in range(3):
            assert await asyncio.to_thread(
                session.current,
                deadline_monotonic=time.monotonic() + 30,
                current=lambda: True,
            )
        assert len(parent.frames) == 1 and not parent.failure
        sequence = parent._live_sequence
        assert parent.pump(lambda: True) and parent._live_sequence == sequence
        decoders.decode_release.set()
        await until(lambda: len(decoders.packets) == 40 or not source.alive(), 3)
        assert source.alive() and outcomes == list(range(1, 41))
        assert [packet.ordinal for packet in decoders.packets] == list(range(1, 41))
        assert len(decoders.owners) == 1
    finally:
        decoders.decode_release.set()
        await source.close()
        producer_stop.set()
        parent.close()
        await asyncio.to_thread(producer_thread.join, 3)
        assert not producer_thread.is_alive()
