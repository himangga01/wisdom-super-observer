import asyncio
import math
import queue
import threading
import time
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiortc.mediastreams import MediaStreamError
from aiortc.rtcdtlstransport import RTCDtlsTransport
from wso_core.tvt.frames import FrameTimestamp
from wso_core.tvt.local_live import LiveIdentity, LiveSummary, PrivateLiveFrame
from wso_core.tvt.local_media_service import LocalLiveProof
from wso_core.tvt.local_service import LocalDeviceFailure
from wso_core.tvt.windows_decode import PrivateRGBFrame
from wso_tvt_media.codec import MediaDenied
from wso_tvt_media.live import LocalWebRtcSession
from wso_tvt_media.native_source import NativeDecodedSource, NativeFrameAdapter

PROOF = LocalLiveProof(True, True, True, True, True)


def frame(*, timestamp=1000000, index=1, channel=b"c" * 16, key=True, payload=None):
    item = object.__new__(PrivateLiveFrame)
    values = {
        "_data": payload
        or b"\0\0\0\1\x40\x01\x80\0\0\0\1\x42\x01\x80\0\0\0\1\x44\x01\x80\0\0\0\1\x26\x01\x80",
        "identity": LiveIdentity(
            generation=4, session=b"s" * 16, channel=channel, task=b"t" * 16
        ),
        "device_timestamp": FrameTimestamp(1, timestamp),
        "frame_index": index,
        "key_frame": key,
        "source_context": (3, 1, 0, 0, 0),
        "_summary": LiveSummary(1, 1, "h265", 64, 48),
    }
    for k, v in values.items():
        object.__setattr__(item, k, v)
    return item


def open_source(core):
    # The worker fetches the proof off the media loop and supplies it here.
    return NativeDecodedSource(core, uuid4(), Path(__file__), proof=PROOF)


def wire(source, binding, permitted):
    # Exactly the worker wiring: lock-only liveness and the emission permit.
    return LocalWebRtcSession(
        binding=binding,
        source=source,
        current=source.alive,
        permitted=permitted,
        expires_at=time.monotonic() + 29,
    )


def rgb_for(binding, packet):
    return PrivateRGBFrame(
        binding, 64, 48, packet.timestamp_us, packet.ordinal, bytes(64 * 48 * 3)
    )


def test_native_adapter_binds_exact_private_frame_and_preserves_source_pts():
    source = NativeFrameAdapter(LocalLiveProof(True, True, True, True, True))
    packet = source.packet(frame())
    assert packet.timestamp_us == 1000000 and packet.binding.owner == b"s" * 16
    assert packet.binding.channel == b"c" * 16 and packet.codec == "hevc"
    assert source.proof.framing_verified and source.proof.timing_verified
    with pytest.raises(ValueError):
        source.packet(frame(timestamp=1100000, index=2, channel=b"x" * 16))


@pytest.mark.parametrize(
    "change",
    [
        {"key": False},
        {"payload": b"not-an-access-unit"},
        {"payload": b"\0\0\0\1\x26\x01\x80"},
        {"timestamp": None},
    ],
)
def test_native_adapter_refuses_unproved_first_picture(change):
    with pytest.raises(ValueError):
        NativeFrameAdapter(LocalLiveProof(True, True, True, True, True)).packet(
            frame(**change)
        )


def test_native_adapter_no_timestamp_revival_or_permission_invention():
    source = NativeFrameAdapter(LocalLiveProof(True, True, True, True, True))
    source.packet(frame())
    with pytest.raises(ValueError):
        source.packet(frame(index=2))
    with pytest.raises(ValueError):
        NativeFrameAdapter(replace(source.proof, live_permission=False))


def test_nal_marker_limit_stops_iteration_before_large_allocation(monkeypatch):
    from wso_tvt_media import native_source

    original = native_source.re.finditer
    seen = []

    def limited(*args, **kwargs):
        for match in original(*args, **kwargs):
            seen.append(1)
            yield match

    monkeypatch.setattr(native_source.re, "finditer", limited)
    with pytest.raises(ValueError):
        NativeFrameAdapter(LocalLiveProof(True, True, True, True, True)).packet(
            frame(payload=b"\0\0\0\1\x40\x01\x80" * 1000)
        )
    assert len(seen) == 129


async def test_supplied_proof_is_validated_without_executor_calls():
    class Untouched:
        def __getattr__(self, name):
            raise AssertionError(name)

    with pytest.raises(MediaDenied):
        NativeDecodedSource(
            Untouched(),
            uuid4(),
            Path(__file__),
            proof=replace(PROOF, live_permission=False),
        )
    source = NativeDecodedSource(Untouched(), uuid4(), Path(__file__), proof=PROOF)
    assert source.adapter.proof is PROOF
    await source.close()


async def test_native_ingress_drains_burst_while_decoder_is_slow_without_losing_order(
    monkeypatch,
):
    from wso_tvt_media import native_source

    gate = threading.Event()
    decoding = threading.Event()
    drained = threading.Event()
    decoded = []
    selected = [frame(timestamp=1_000_000 + i * 40_000, index=i + 1) for i in range(10)]

    class Core:
        def current(self, lease_id):
            return True

        def lease(self, lease_id):
            return SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=5))

        def read_frames(self, lease_id, *, max_frames, max_bytes, deadline_ms):
            assert max_frames <= 16 and max_bytes <= 4 * 1024 * 1024
            assert deadline_ms == 2000
            if selected:
                result = (selected.pop(0),)
                if not selected:
                    drained.set()
                return result
            time.sleep(0.005)
            return ()

    class SlowDecoder:
        def __init__(self, *, binding, **kwargs):
            self.binding = binding

        def decode(self, packet):
            if not decoded:
                decoding.set()
                assert gate.wait(2)
            decoded.append((packet.ordinal, packet.timestamp_us))
            return (
                PrivateRGBFrame(
                    self.binding,
                    64,
                    48,
                    packet.timestamp_us,
                    packet.ordinal,
                    bytes([210, 40, 20]) * 64 * 48,
                ),
            )

        def close(self):
            pass

        def wait_closed(self):
            return True

    monkeypatch.setattr(native_source, "WindowsDecoder", SlowDecoder)
    source = open_source(Core())
    source.start()
    try:
        assert await asyncio.to_thread(decoding.wait, 0.5)
        # The real source must drain all native inputs while first decode is
        # stalled; a shared producer cannot do this and overfills callbacks.
        assert await asyncio.to_thread(drained.wait, 0.5)
        gate.set()
        deadline = time.monotonic() + 1
        while source.produced_frames < 10:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.005)
        assert decoded == [(i + 1, 1_000_000 + i * 40_000) for i in range(10)]
        latest = await source.recv()
        assert latest.ordinal == 10
    finally:
        gate.set()
        await source.close()


async def test_partial_decoder_thread_start_failure_retains_started_ingress(
    monkeypatch,
):
    from wso_tvt_media import native_source

    class Core:
        def current(self, lease_id):
            return True

        def read_frames(self, *args, **kwargs):
            time.sleep(0.01)
            return ()

    actual_start = threading.Thread.start
    originals = []

    def partial_start(thread):
        originals.append(thread)
        if len(originals) == 2:
            raise RuntimeError("inert second-thread start failure")
        return actual_start(thread)

    source = open_source(Core())
    monkeypatch.setattr(native_source.threading.Thread, "start", partial_start)
    try:
        with pytest.raises(RuntimeError):
            source.start()
        await asyncio.wait_for(source.close(), 1)
        assert len(originals) == 2 and originals[0].ident is not None
        assert all(not thread.is_alive() for thread in originals)
    finally:
        await source.close()


async def test_authority_owner_registered_before_start_and_retained_on_partial_start(
    monkeypatch,
):
    from wso_tvt_media import native_source

    class Core:
        def current(self, lease_id):
            return True

        def lease(self, lease_id):
            return SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=5))

        def read_frames(self, *args, **kwargs):
            time.sleep(0.01)
            return ()

    actual_start = threading.Thread.start
    originals = []

    def partial_start(thread):
        originals.append(thread)
        if thread.name == "local-live-authority-owner":
            raise RuntimeError("inert third-thread start failure")
        return actual_start(thread)

    source = open_source(Core())
    # Every original owner and completion event exists before any start.
    names = [thread.name for thread in source._threads]
    assert names == [
        "local-live-ingress-owner",
        "local-live-decoder-owner",
        "local-live-authority-owner",
    ]
    assert len(source._thread_done) == 3
    assert all(thread.ident is None for thread in source._threads)
    monkeypatch.setattr(native_source.threading.Thread, "start", partial_start)
    try:
        with pytest.raises(RuntimeError):
            source.start()
        assert [thread.name for thread in originals] == names
        assert all(thread.ident is not None for thread in originals[:2])
        await asyncio.wait_for(source.close(), 1)
        assert all(not thread.is_alive() for thread in originals)
        assert source.alive() is False and source.transport_current() is False
    finally:
        await source.close()


async def test_close_joins_authority_owner_and_requires_decoder_wait_closed(
    monkeypatch,
):
    from wso_tvt_media import native_source

    released = threading.Event()
    heartbeat = []

    class Core:
        sent = False

        def current(self, lease_id):
            return True

        def lease(self, lease_id):
            heartbeat.append(threading.current_thread().name)
            return SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=5))

        def read_frames(self, *args, **kwargs):
            if not self.sent:
                self.sent = True
                return (frame(),)
            time.sleep(0.01)
            return ()

    class Decoder:
        closes = 0

        def __init__(self, *, binding, **kwargs):
            self.binding = binding

        def decode(self, packet):
            return (rgb_for(self.binding, packet),)

        def close(self):
            Decoder.closes += 1

        def wait_closed(self):
            return released.is_set()

    monkeypatch.setattr(native_source, "WindowsDecoder", Decoder)
    source = open_source(Core())
    source.start()
    closing = None
    try:
        await asyncio.wait_for(source.binding(), 1)
        deadline = time.monotonic() + 1
        while "local-live-authority-owner" not in heartbeat:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
        closing = asyncio.create_task(source.close())
        await asyncio.sleep(0.3)
        # The decoder stage retains its original owner until wait_closed is True.
        assert not closing.done() and Decoder.closes >= 2
        assert source._thread.is_alive() and not source._authority.is_alive()
        released.set()
        await asyncio.wait_for(closing, 1)
        assert all(not thread.is_alive() for thread in source._threads)
        assert all(done.is_set() for done in source._thread_done)
    finally:
        released.set()
        if closing is not None:
            await asyncio.wait_for(closing, 2)
        await source.close()


async def test_closed_loop_post_still_retires_decoder_and_settles_stages(
    monkeypatch,
):
    from wso_tvt_media import native_source

    class Core:
        sent = False

        def current(self, lease_id):
            return True

        def lease(self, lease_id):
            return SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=5))

        def read_frames(self, *args, **kwargs):
            if not self.sent:
                self.sent = True
                return (frame(),)
            time.sleep(0.01)
            return ()

    class Decoder:
        retired = False

        def __init__(self, *, binding, **kwargs):
            self.binding = binding

        def decode(self, packet):
            return (rgb_for(self.binding, packet),)

        def close(self):
            Decoder.retired = True

        def wait_closed(self):
            return True

    class ClosedLoop:
        def call_soon_threadsafe(self, *args):
            raise RuntimeError("Event loop is closed")

    monkeypatch.setattr(native_source, "WindowsDecoder", Decoder)
    source = open_source(Core())
    source.start()
    await asyncio.wait_for(source.binding(), 1)
    source._loop = ClosedLoop()
    source._signal_stop()
    for thread in source._threads:
        await asyncio.to_thread(thread.join, 2)
        assert not thread.is_alive()
    assert Decoder.retired and source._ended
    assert all(done.is_set() for done in source._thread_done)


@pytest.mark.parametrize("case", ["blocked", "expired", "revoked"])
async def test_delivery_permit_is_fast_bounded_and_never_revives(monkeypatch, case):
    from wso_tvt_media import native_source

    main_thread = threading.get_ident()
    sql_threads = []
    proceed = threading.Event()
    proceed.set()
    ttl = 0.5 if case == "expired" else 30

    class Core:
        sent = False
        active = True
        renewed = 0.0
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)

        def current(self, lease_id):
            sql_threads.append(threading.get_ident())
            return self.active

        def lease(self, lease_id):
            sql_threads.append(threading.get_ident())
            entered = time.monotonic()
            assert proceed.wait(5)
            if not self.active:
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            # Upper bound of this renewal's pre-SQL observation.
            self.renewed = max(self.renewed, entered)
            return SimpleNamespace(expires_at=self.expires_at)

        def read_frames(self, *args, **kwargs):
            if not self.sent:
                self.sent = True
                return (frame(),)
            time.sleep(0.01)
            return ()

    class Decoder:
        def __init__(self, *, binding, **kwargs):
            self.binding = binding

        def decode(self, packet):
            return (rgb_for(self.binding, packet),)

        def close(self):
            pass

        def wait_closed(self):
            return True

    monkeypatch.setattr(native_source, "WindowsDecoder", Decoder)
    core = Core()
    expiry = time.monotonic() + (core.expires_at - datetime.now(UTC)).total_seconds()
    source = open_source(core)
    source.start()
    try:
        await asyncio.wait_for(source.binding(), 1)
        assert source.transport_current() is True
        assert (await source.recv()).ordinal == 1
        if case == "blocked":
            # No fresh SQL observation: the permit lapses within 200 ms of the
            # last pre-SQL observation; staleness alone does not stop the source.
            proceed.clear()
            await asyncio.sleep(0.05)
            await asyncio.sleep(max(0.0, core.renewed + 0.3 - time.monotonic()))
            assert source.transport_current() is False and source.alive() is True
            pending = asyncio.create_task(source.recv())
            await asyncio.sleep(0.05)
            assert not pending.done()
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
            proceed.set()
            deadline = time.monotonic() + 1
            while not source.transport_current():
                assert time.monotonic() < deadline
                await asyncio.sleep(0.01)
        elif case == "expired":
            # Successful SQL never extends the permit past the SQL lease expiry.
            await asyncio.sleep(max(0.0, expiry + 0.1 - time.monotonic()))
            assert source.transport_current() is False and source.alive() is True
            await asyncio.sleep(0.15)
            assert source.transport_current() is False
        else:
            core.active = False
            deadline = time.monotonic() + 1
            while source.alive():
                assert time.monotonic() < deadline
                await asyncio.sleep(0.01)
            assert source.transport_current() is False
            with pytest.raises(MediaDenied):
                await source.recv()
            core.active = True
            await asyncio.sleep(0.15)
            assert source.transport_current() is False and source.alive() is False
        assert sql_threads and main_thread not in sql_threads
    finally:
        proceed.set()
        await source.close()
    assert source.transport_current() is False and source.alive() is False


async def test_slow_successful_renewal_skips_without_fencing_and_drops_frame(
    monkeypatch,
):
    from wso_tvt_media import native_source

    feed: queue.Queue = queue.Queue()
    slow_publish = threading.Event()

    class Core:
        stall = 0.0

        def current(self, lease_id):
            return True

        def lease(self, lease_id):
            stall = self.stall
            if stall and threading.current_thread().name == "local-live-decoder-owner":
                slow_publish.set()
            time.sleep(stall)
            return SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=30))

        def read_frames(self, *args, **kwargs):
            try:
                return (feed.get(timeout=0.02),)
            except queue.Empty:
                return ()

    class Decoder:
        def __init__(self, *, binding, **kwargs):
            self.binding = binding

        def decode(self, packet):
            return (rgb_for(self.binding, packet),)

        def close(self):
            pass

        def wait_closed(self):
            return True

    monkeypatch.setattr(native_source, "WindowsDecoder", Decoder)
    core = Core()
    source = open_source(core)
    source.start()
    try:
        feed.put(frame(timestamp=1_000_000, index=1))
        await asyncio.wait_for(source.binding(), 1)
        assert (await source.recv()).ordinal == 1
        # Successful SQL that returns after the 200 ms window renews nothing.
        core.stall = 0.3
        feed.put(frame(timestamp=1_100_000, index=2))
        assert await asyncio.to_thread(slow_publish.wait, 2)
        deadline = time.monotonic() + 1
        while source.transport_current():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
        assert source.alive() is True
        core.stall = 0.0
        feed.put(frame(timestamp=1_200_000, index=3))
        deadline = time.monotonic() + 2
        while source.produced_frames < 2:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
        # Frame 2 was dropped: never installed, never counted.
        assert (await source.recv()).ordinal == 3
        assert source.produced_frames == 2
        assert source.alive() is True and source.transport_current() is True
    finally:
        await source.close()


async def test_compressed_fifo_overflow_fences_without_dropping_or_reordering(
    monkeypatch,
):
    from wso_tvt_media import native_source

    entered = threading.Event()
    release = threading.Event()

    class Core:
        index = 0

        def current(self, lease_id):
            return True

        def lease(self, lease_id):
            return SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=5))

        def read_frames(self, *args, **kwargs):
            if self.index:
                assert entered.wait(1)
            self.index += 1
            return (frame(timestamp=1_000_000 + self.index * 40_000, index=self.index),)

    class Decoder:
        def __init__(self, **kwargs):
            pass

        def decode(self, packet):
            entered.set()
            assert release.wait(2)
            return ()

        def close(self):
            pass

        def wait_closed(self):
            return True

    monkeypatch.setattr(native_source, "WindowsDecoder", Decoder)
    core = Core()
    source = open_source(core)
    source.start()
    try:
        with pytest.raises(MediaDenied):
            await asyncio.wait_for(source.binding(), 1)
        assert core.index == 18  # One decoding, sixteen queued, next refused.
        assert source.transport_current() is False
        release.set()
        await asyncio.wait_for(source.close(), 1)
    finally:
        release.set()
        await source.close()


# Continuous-playback liveness: the real source composed with the real session.


class Paced:
    """Inert executor: injected SQL latency per transaction, paced frames.

    lease() is a fresh current plus a view (two transactions) and raises on
    denial, as LocalMediaExecutor does. stall delays a successful lease.
    """

    def __init__(self, schedule, *, sql=0.0):
        self.schedule, self.sql = list(schedule), sql
        self.active, self.stall, self.denied_at = True, 0.0, None
        self.started = None
        self.index = 0
        self.expires_at = datetime.now(UTC) + timedelta(seconds=30)

    def _transaction(self):
        if self.sql:
            time.sleep(self.sql)
        if not self.active and self.denied_at is None:
            self.denied_at = time.monotonic()
        return self.active

    def current(self, lease_id):
        return self._transaction()

    def lease(self, lease_id):
        stall = self.stall
        if not self._transaction():
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        if stall:
            time.sleep(stall)
        self._transaction()
        return SimpleNamespace(expires_at=self.expires_at)

    def read_frames(self, lease_id, *, max_frames, max_bytes, deadline_ms):
        if self.started is None:
            self.started = time.monotonic()
        if self.index >= len(self.schedule):
            time.sleep(0.02)
            return ()
        delay = self.started + self.schedule[self.index] - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self.index += 1
        return (frame(timestamp=1_000_000 + self.index * 100_000, index=self.index),)


class Contracted(Paced):
    """Paced plus the LocalMediaExecutor.read_frames deadline contract.

    A read with no compressed frame before deadline_ms is a denial: the real
    provider closes the native session and the executor closes the lease.
    """

    def __init__(self, schedule, *, sql=0.0):
        super().__init__(schedule, sql=sql)
        self.deadlines = []
        self.lease_closes = 0

    def read_frames(self, lease_id, *, max_frames, max_bytes, deadline_ms):
        self.deadlines.append(deadline_ms)
        if self.started is None:
            self.started = time.monotonic()
        deadline = time.monotonic() + deadline_ms / 1000
        due = math.inf
        if self.index < len(self.schedule):
            due = self.started + self.schedule[self.index]
        if due > deadline:
            time.sleep(max(0.0, deadline - time.monotonic()))
            self.active = False
            self.lease_closes += 1
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return super().read_frames(
            lease_id,
            max_frames=max_frames,
            max_bytes=max_bytes,
            deadline_ms=deadline_ms,
        )


def authorizing_decoder(seconds):
    class Decoder:
        def __init__(self, *, binding, authorize, **kwargs):
            self.binding, self.authorize = binding, authorize

        def decode(self, packet):
            # WindowsDecoder checks authority in _admit and after the exchange.
            if self.authorize(self.binding) is not True:
                raise ValueError("denied")
            time.sleep(seconds)
            if self.authorize(self.binding) is not True:
                raise ValueError("denied")
            return (rgb_for(self.binding, packet),)

        def close(self):
            pass

        def wait_closed(self):
            return True

    return Decoder


class Wire:
    """Worker-wired session; an inert sink replaces only DTLS encryption.

    The session's RTP/RTCP/retransmit hook wraps the sink, so every datagram
    that passes the hook is recorded with the permit value the hook observed.
    """

    def __init__(self, monkeypatch, source, binding):
        self.source = source
        self.last = None
        self.sent = []
        self.withheld = self.frames = self.lapses = self.fifo = 0
        self.refused = False

        async def sink(transport, data):
            self.sent.append((time.monotonic(), self.last))

        monkeypatch.setattr(RTCDtlsTransport, "_send_rtp", sink)
        self.session = wire(source, binding, self.permitted)
        sender = self.session.peer.getTransceivers()[0].sender
        self.hook = sender.transport._send_rtp
        self.reader = asyncio.create_task(self._read())
        self.tasks = [
            asyncio.create_task(self._send()),
            asyncio.create_task(self._sample()),
        ]

    def permitted(self):
        # Pass-through of source.transport_current recording what was seen.
        self.last = self.source.transport_current()
        return self.last

    async def _send(self):
        while True:
            count = len(self.sent)
            try:
                await self.hook(b"\x80" + bytes(11))
            except ConnectionError:
                self.refused = True
                return
            if len(self.sent) == count:
                self.withheld += 1
            await asyncio.sleep(0.01)

    async def _read(self):
        with suppress(MediaStreamError):
            while True:
                await self.session.track.recv()
                self.frames += 1

    async def _sample(self):
        while True:
            if not self.source.transport_current():
                self.lapses += 1
            self.fifo = max(self.fifo, len(self.source._encoded))
            await asyncio.sleep(0.005)

    def sent_since(self, moment):
        return [sent for sent, _ in self.sent if sent >= moment]

    async def until(self, condition, seconds):
        deadline = time.monotonic() + seconds
        while not condition():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        with suppress(MediaDenied):
            await self.session.close()
        await asyncio.wait_for(self.reader, 2)
        await asyncio.wait_for(self.session.wait_closed(), 3)


async def start_wired(monkeypatch, core, decode=0.005):
    from wso_tvt_media import native_source

    monkeypatch.setattr(native_source, "WindowsDecoder", authorizing_decoder(decode))
    source = open_source(core)
    source.start()
    try:
        binding = await asyncio.wait_for(source.binding(), 2)
        return source, Wire(monkeypatch, source, binding)
    except BaseException:
        await source.close()
        raise


@pytest.mark.parametrize(
    "fps, late, sql, strict",
    [(10, 0.0, 0.003, True), (10, 0.25, 0.003, False), (5, 0.0, 0.003, True)]
    + [(10, 0.0, 0.025, False)],
    ids=["10fps-3ms-sql", "one-250ms-late-frame", "5fps", "10fps-25ms-sql"],
)
async def test_composed_pipeline_stays_live(monkeypatch, fps, late, sql, strict):
    schedule = [i / fps for i in range(int(4.5 * fps))]
    if late:
        # One frame arrives 250 ms late; the next ones then arrive in a burst.
        schedule[15] += late
    source, harness = await start_wired(monkeypatch, Paced(schedule, sql=sql))
    try:
        await asyncio.sleep(3.0)
        session = harness.session
        assert not session._fenced and not harness.refused
        assert session.peer.connectionState != "closed"
        assert source.alive() is True and harness.fifo < 16
        assert harness.frames >= 3 * fps // 2
        # No datagram ever crossed the hook without a current permit.
        assert harness.sent and all(permit is True for _, permit in harness.sent)
        if strict:
            assert harness.lapses == 0 and harness.withheld == 0
    finally:
        await harness.close()
        await source.close()
    assert all(not thread.is_alive() for thread in source._threads)


async def test_revocation_while_stale_fences_and_nothing_leaves_after(monkeypatch):
    core = Paced([i / 10 for i in range(8)])
    source, harness = await start_wired(monkeypatch, core)
    session = harness.session
    try:
        await harness.until(lambda: source.produced_frames >= 8, 3)
        core.stall = 0.3  # Successful SQL that is always too late to renew.
        await harness.until(lambda: not source.transport_current(), 1)
        stale = time.monotonic()
        await asyncio.sleep(0.5)
        assert not session._fenced and source.alive() is True
        assert harness.withheld > 0 and not harness.sent_since(stale)
        session.renew(time.monotonic() + 10)  # Stale does not block renewal.
        revoked = time.monotonic()
        core.active = False
        await harness.until(lambda: session._fenced, 2)
        await harness.until(lambda: session.peer.connectionState == "closed", 3)
        assert core.denied_at is not None and not harness.sent_since(revoked)
        core.active, core.stall = True, 0.0
        await asyncio.sleep(0.2)
        assert source.alive() is False and source.transport_current() is False
        with pytest.raises(MediaDenied):
            session.renew(time.monotonic() + 10)
        assert not harness.sent_since(stale)
    finally:
        await harness.close()
        await source.close()


async def test_stale_beyond_grace_fences_permanently(monkeypatch):
    core = Paced([i / 10 for i in range(5)])
    source, harness = await start_wired(monkeypatch, core)
    session = harness.session
    try:
        await harness.until(lambda: source.produced_frames >= 5, 3)
        core.stall = 0.3
        stalled = time.monotonic()
        await asyncio.sleep(1.5)
        assert not session._fenced and source.alive() is True
        await harness.until(lambda: session._fenced, 3)
        fenced = time.monotonic()
        assert fenced - stalled > 1.5
        await harness.until(lambda: not source.alive(), 3)
        assert not harness.sent_since(stalled + 0.25)
        core.stall = 0.0
        with pytest.raises(MediaDenied):
            session.renew(time.monotonic() + 10)
    finally:
        await harness.close()
        await source.close()


async def test_ingress_read_deadline_tolerates_one_second_arrival_gap(monkeypatch):
    # 10 fps with a single 1.0 s compressed-frame arrival gap after frame 15.
    schedule = [i / 10 for i in range(15)] + [2.4 + i / 10 for i in range(30)]
    core = Contracted(schedule, sql=0.003)
    source, harness = await start_wired(monkeypatch, core)
    session = harness.session
    try:
        await harness.until(
            lambda: source.produced_frames >= 20 or not source.alive(), 5
        )
        # The idle read spanning the gap must not reach its terminal deadline.
        assert core.lease_closes == 0 and core.active
        assert source.alive() is True and source.produced_frames >= 20
        assert not session._fenced and not harness.refused
        assert core.deadlines and set(core.deadlines) == {2000}
    finally:
        await harness.close()
        await source.close()


async def test_older_renewal_never_shortens_newer_permit_or_renews_after_stop(
    monkeypatch,
):
    from wso_tvt_media import native_source

    # Module-local clock: only native_source sees it, never the event loop.
    clock = [100.0]
    monkeypatch.setattr(
        native_source,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0], sleep=time.sleep),
    )
    entered = threading.Event()
    gate = threading.Event()
    calls = []

    class Core:
        def lease(self, lease_id):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                assert gate.wait(2)
            return SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(seconds=30))

    source = open_source(Core())
    older = []
    owner = threading.Thread(target=lambda: older.append(source._renew()))
    owner.start()
    try:
        # The older round observed at 100.00; its SQL is still pending.
        assert await asyncio.to_thread(entered.wait, 2)
        clock[0] = 100.05
        assert await asyncio.to_thread(source._renew) is True
        newer = source._permit_deadline
        assert newer > 100.2
        # The older round finishes later but in time: valid, yet never shorter.
        clock[0] = 100.1
        gate.set()
        await asyncio.to_thread(owner.join, 2)
        assert older == [True] and source._permit_deadline == newer
        assert source.transport_current() is True
        source._signal_stop()
        assert await asyncio.to_thread(source._renew) is False
        assert source._permit_deadline == 0 and source.transport_current() is False
    finally:
        gate.set()
        owner.join(2)
        await source.close()
