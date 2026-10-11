"""Source-level resolution changes with inert native and exact decoder owners."""

import asyncio
import queue
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from wso_core.tvt.local_live import LiveSummary
from wso_core.tvt.local_service import LocalDeviceFailure
from wso_core.tvt.windows_decode import PrivateRGBFrame
from wso_tvt_media import native_source
from wso_tvt_media.codec import MediaDenied

from tests.tvt_parity.test_local_media_source import frame, open_source, wire


def picture(
    index, width, height, *, key=True, codec="h265", raw_timestamp=None, **kwargs
):
    if codec == "h264" and "payload" not in kwargs:
        kwargs["payload"] = (
            b"\0\0\0\1\x67\x80\0\0\0\1\x68\x80\0\0\0\1\x65\x80"
            if key
            else b"\0\0\0\1\x41\x80"
        )
    if not key and "payload" not in kwargs:
        kwargs["payload"] = b"\0\0\0\1\x02\x01\x80"
    item = frame(
        timestamp=1_000_000 + index * 100_000
        if raw_timestamp is None
        else raw_timestamp,
        index=index,
        key=key,
        **kwargs,
    )
    object.__setattr__(item, "_summary", LiveSummary(1, 1, codec, width, height))
    return item


class Native:
    def __init__(self):
        self.items = queue.Queue()
        self.active = True

    def current(self, _lease):
        return self.active

    def lease(self, _lease):
        if not self.active:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=30))

    def read_frames(self, _lease, **kwargs):
        try:
            return (self.items.get(timeout=0.01),)
        except queue.Empty:
            return ()


class Decoders:
    """No subprocesses: model owned synchronous decode and pending close exactly."""

    def __init__(self, monkeypatch, *, delay_first=False):
        self.owners = []
        self.packets = []
        self.close_entered = threading.Event()
        self.close_release = threading.Event()
        self.close_release.set()
        self.decode_entered = threading.Event()
        self.decode_release = threading.Event()
        self.decode_release.set()
        self.delay_first = delay_first
        harness = self

        class Decoder:
            def __init__(self, *, binding, authorize, **kwargs):
                assert all(owner.closed for owner in harness.owners)
                assert authorize(binding)
                self.binding, self.authorize = binding, authorize
                self.closed = False
                self.dimensions = None
                harness.owners.append(self)

            def decode(self, packet):
                assert self.authorize(self.binding)
                dimensions = (packet.width, packet.height)
                assert self.dimensions in (None, dimensions)
                self.dimensions = dimensions
                harness.packets.append(packet)
                harness.decode_entered.set()
                assert harness.decode_release.wait(3)
                if harness.delay_first and len(harness.owners) == 1:
                    return ()
                return (
                    PrivateRGBFrame(
                        self.binding,
                        packet.width,
                        packet.height,
                        packet.timestamp_us,
                        packet.ordinal,
                        bytes(packet.width * packet.height * 3),
                    ),
                )

            def close(self):
                harness.close_entered.set()

            def wait_closed(self):
                harness.close_release.wait()
                self.closed = True
                return True

        monkeypatch.setattr(native_source, "WindowsDecoder", Decoder)


async def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "source condition did not arrive"
        await asyncio.sleep(0.005)


@pytest.mark.parametrize("before_first", [True, False])
@pytest.mark.parametrize("codec", ["h264", "h265"])
@pytest.mark.parametrize("equal_time", [False, True])
async def test_original_source_rotates_352_to_1280_and_back_without_new_peer(
    monkeypatch, before_first, codec, equal_time
):
    native = Native()
    decoders = Decoders(monkeypatch, delay_first=before_first)
    source = open_source(native)
    source.start()
    peer = None
    try:
        native.items.put(picture(1, 352, 240, codec=codec))
        await until(lambda: len(decoders.packets) == 1)
        original_binding = source.adapter.binding
        if not before_first:
            assert await source.binding() is original_binding
            peer = wire(source, original_binding, source.transport_current)
            first = await asyncio.wait_for(peer.track.recv(), 2)
            assert (first.width, first.height, first.pts) == (352, 240, 1_100_000)
        for index, shape in [(2, (1280, 720)), (3, (704, 480)), (4, (352, 240))]:
            native.items.put(
                picture(
                    index,
                    *shape,
                    codec=codec,
                    raw_timestamp=1_100_000 if equal_time else None,
                )
            )
            await until(
                lambda index=index: len(decoders.packets) == index or not source.alive()
            )
            assert source.alive(), (
                "validated size change must preserve the original source"
            )
            if peer is None:
                assert (await source.binding())._wire() == original_binding._wire()
                peer = wire(source, original_binding, source.transport_current)
            video = await asyncio.wait_for(peer.track.recv(), 2)
            assert (video.width, video.height) == shape
            assert video.pts == (
                1_100_000 + (index - 1) * 24
                if equal_time
                else 1_000_000 + index * 100_000
            )
        assert [p.ordinal for p in decoders.packets] == [1, 2, 3, 4]
        assert all(
            p.binding._wire() == original_binding._wire() for p in decoders.packets
        )
        assert len(decoders.owners) == 4 and not peer._fenced
    finally:
        if peer:
            await peer.close()
        await source.close()


async def test_transition_inter_pictures_wait_for_complete_keyframe(monkeypatch):
    native, decoders = Native(), Decoders(monkeypatch)
    source = open_source(native)
    source.start()
    try:
        native.items.put(picture(1, 352, 240))
        await source.binding()
        await source.recv()
        native.items.put(picture(2, 1280, 720, key=False))
        await until(lambda: decoders.close_entered.is_set() or not source.alive())
        assert source.alive() and len(decoders.owners) == 1
        native.items.put(picture(3, 1280, 720, key=False))
        native.items.put(picture(4, 1280, 720))
        rgb = await asyncio.wait_for(source.recv(), 2)
        assert (rgb.width, rgb.height, rgb.ordinal) == (1280, 720, 4)
        assert [p.ordinal for p in decoders.packets] == [1, 4]
    finally:
        await source.close()


@pytest.mark.parametrize("action", ["stop", "revoke", "resume"])
@pytest.mark.parametrize("equal_time", [False, True])
async def test_original_decoder_must_settle_before_successor_or_source_close(
    monkeypatch, action, equal_time
):
    native, decoders = Native(), Decoders(monkeypatch)
    source = open_source(native)
    source.start()
    closing = None
    try:
        native.items.put(picture(1, 352, 240))
        await source.binding()
        await source.recv()
        decoders.close_release.clear()
        native.items.put(
            picture(2, 1280, 720, raw_timestamp=1_100_000 if equal_time else None)
        )
        await until(decoders.close_entered.is_set)
        assert len(decoders.owners) == 1 and not decoders.owners[0].closed
        if action == "stop":
            closing = asyncio.create_task(source.close())
        elif action == "revoke":
            native.active = False
        if action != "resume":
            await until(lambda: not source.alive())
            assert not source._decoder_done.is_set()
            if closing:
                assert not closing.done()
        decoders.close_release.set()
        if action == "resume":
            rgb = await asyncio.wait_for(source.recv(), 2)
            assert (rgb.width, rgb.ordinal) == (1280, 2)
            assert len(decoders.owners) == 2
        else:
            await source.close()
            assert len(decoders.owners) == 1
    finally:
        decoders.close_release.set()
        await source.close()
        if closing:
            await closing


@pytest.mark.parametrize("equal_time", [False, True])
async def test_old_decode_result_cannot_publish_after_new_dimensions_observed(
    monkeypatch,
    equal_time,
):
    native, decoders = Native(), Decoders(monkeypatch)
    decoders.decode_release.clear()
    source = open_source(native)
    source.start()
    try:
        native.items.put(picture(1, 352, 240))
        await until(decoders.decode_entered.is_set)
        native.items.put(
            picture(2, 1280, 720, raw_timestamp=1_100_000 if equal_time else None)
        )
        await until(lambda: source.adapter._ordinal == 2 or not source.alive())
        decoders.decode_release.set()
        await until(lambda: source.produced_frames or not source.alive())
        assert source.alive()
        rgb = await asyncio.wait_for(source.recv(), 2)
        assert (rgb.width, rgb.ordinal) == (1280, 2)
        assert rgb.timestamp_us == (1_100_024 if equal_time else 1_200_000)
        assert source.produced_frames == 1
    finally:
        decoders.decode_release.set()
        await source.close()


@pytest.mark.parametrize("blocked_close", [False, True])
async def test_transition_deadline_fences_while_waiting_for_key_or_old_close(
    monkeypatch, blocked_close
):
    # Source-only clock advances; event-loop and native timeout clocks stay real.
    clock = [100.0]
    monkeypatch.setattr(
        native_source,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            sleep=time.sleep,
        ),
    )
    native, decoders = Native(), Decoders(monkeypatch)
    source = open_source(native)
    events = []
    source._observe = lambda stage, reason: events.append((stage, reason))
    source.start()
    try:
        native.items.put(picture(1, 352, 240))
        await source.binding()
        if blocked_close:
            decoders.close_release.clear()
        native.items.put(picture(2, 1280, 720, key=blocked_close))
        await until(decoders.close_entered.is_set)
        assert source.alive()
        clock[0] = 104.99
        await asyncio.sleep(0.06)
        assert source.alive()
        clock[0] = 105.0
        await until(lambda: not source.alive())
        assert ("format_transition", "transition_deadline") in events
        assert len(decoders.owners) == 1
        if blocked_close:
            assert not source._decoder_done.is_set()
    finally:
        decoders.close_release.set()
        await source.close()


@pytest.mark.parametrize("expiry", [False, True])
async def test_rotation_rate_is_rolling_and_does_not_reset_global_clock(
    monkeypatch, expiry
):
    clock = [100.0]
    monkeypatch.setattr(
        native_source,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            sleep=time.sleep,
        ),
    )
    native, decoders = Native(), Decoders(monkeypatch)
    source = open_source(native)
    events = []
    source._observe = lambda stage, reason: events.append((stage, reason))
    source.start()
    try:
        for index in range(1, 19):
            if index == 18 and expiry:
                clock[0] = 160.0
            native.items.put(picture(index, 64 if index % 2 else 128, 48))
            await until(
                lambda index=index: len(decoders.packets) == index or not source.alive()
            )
            if index < 18 or expiry:
                assert source.alive()
                rgb = await asyncio.wait_for(source.recv(), 2)
                assert (
                    rgb.ordinal == index
                    and rgb.timestamp_us == 1_000_000 + index * 100_000
                )
        assert len(decoders.owners) == (18 if expiry else 17)
        assert source.alive() is expiry
        if not expiry:
            assert ("format_transition", "rotation_limit") in events
    finally:
        await source.close()


@pytest.mark.parametrize(
    "bad",
    ["identity", "codec", "header", "configuration", "timestamp", "reserved_picture"],
)
async def test_transition_cannot_skip_invalid_or_foreign_picture(monkeypatch, bad):
    native, decoders = Native(), Decoders(monkeypatch)
    source = open_source(native)
    source.start()
    try:
        native.items.put(picture(1, 352, 240))
        await source.binding()
        change = {}
        if bad == "identity":
            change["channel"] = b"x" * 16
        elif bad == "header":
            change["payload"] = b"\0\0\0\1\x82\x01\x80"
        elif bad == "configuration":
            change["payload"] = b"\0\0\0\1\x26\x01\x80"
        elif bad == "reserved_picture":
            change["payload"] = b"\0\0\0\1\x2c\x01\x80"
        item = picture(
            2 if bad != "timestamp" else 0,
            1280,
            720,
            key=bad == "configuration",
            **change,
        )
        if bad == "codec":
            object.__setattr__(item, "_summary", LiveSummary(1, 1, "h264", 1280, 720))
        native.items.put(item)
        await until(lambda: not source.alive())
        assert len(decoders.owners) == 1
        with pytest.raises(MediaDenied):
            await source.recv()
    finally:
        await source.close()


@pytest.mark.parametrize("by_bytes", [False, True])
async def test_transition_queue_pressure_stop_preserves_retiring_owner(
    monkeypatch, by_bytes
):
    from tests.tvt_parity.test_local_media_pressure import ReservedNative

    native, decoders = ReservedNative(), Decoders(monkeypatch)
    source = open_source(native)
    events = []
    source._observe = lambda stage, reason: events.append((stage, reason))
    source.start()
    try:
        native.items.put(picture(1, 352, 240))
        await source.binding()
        decoders.close_release.clear()
        native.items.put(picture(2, 1280, 720))
        await until(decoders.close_entered.is_set)
        for index in range(3, 20):
            payload = (
                b"\0\0\0\1\x02\x01\x80" + b"x" * (1024 * 1024) if by_bytes else None
            )
            native.items.put(
                picture(
                    index,
                    1280,
                    720,
                    key=False,
                    **({"payload": payload} if payload else {}),
                )
            )
        await until(lambda: len(source._encoded) == (3 if by_bytes else 16))
        assert source.alive() and source._encoded_bytes <= 4 * 1024 * 1024
        assert ("ingress_queue", "overflow") not in events
        source._signal_stop()
        assert len(decoders.owners) == 1 and not source._decoder_done.is_set()
        assert not source._encoded and source._latest is None
    finally:
        decoders.close_release.set()
        await source.close()
