"""Mux media boundaries with synthetic original codec pictures only."""

import asyncio
import importlib
import importlib.util
import struct
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from test_local_live_mux import feed, opened, setup, types, wire
from wso_tvt_media.codec import MediaDenied
from wso_tvt_media.native_source import NativeFrameAdapter

from tests.tvt_parity.test_local_media_source import PROOF

KEY = b"\0\0\0\1\x67\x80\0\0\0\1\x68\x80\0\0\0\1\x65\x80"


def frames(count=3, shapes=None):
    codec, (slot,) = setup()
    opened(codec, slot)
    result = []
    for i in range(1, count + 1):
        if shapes is None:
            encoded = wire(slot, i, payload=KEY)
        else:
            from test_local_live import media, packet

            width, height = shapes[i - 1]
            body = media(
                index=i,
                payload=KEY,
                channel=slot.channel,
                extension=struct.pack(
                    "<BBH4shhIB", 0, 0, 0, b"H264", width, height, 0, 0
                ),
            )
            encoded = packet(65537, body, flags=0, sequence=0, declared=len(body))
        result.append(feed(codec, encoded, i + 1)[0])
    return slot, result


def cut_for(slot, *, after=1, expiry=None):
    return types().IngressCut(
        slot.epoch, slot, uuid4(), 1, after, expiry or time.monotonic() + 10
    )


def mux_packet(adapter, item, cut):
    assert callable(getattr(adapter, "packet_mux", None)), (
        "explicit mux packet gate missing"
    )
    return adapter.packet_mux(item, registration=cut.registration, cut=cut)


def test_mapped_slot_clock_never_resets_on_park():
    slot, items = frames(5)
    first = cut_for(slot)
    packet = mux_packet(NativeFrameAdapter(PROOF), items[0], first)
    assert (packet.timestamp_us, packet.ordinal) == (1000, 1)
    returned = cut_for(slot, after=4)
    packet = mux_packet(NativeFrameAdapter(PROOF), items[4], returned)
    assert (packet.timestamp_us, packet.ordinal) == (1096, 5)
    assert items[4].frame.device_timestamp.unix_microseconds == 1000


@pytest.mark.parametrize("held", [0, 1])
def test_held_complete_pre_cut_pictures_cannot_seed_new_viewer(held):
    slot, items = frames()
    cut = cut_for(slot, after=3)
    with pytest.raises(MediaDenied):
        mux_packet(NativeFrameAdapter(PROOF), items[held], cut)


def test_late_first_key_is_denied_but_consumed_cut_keeps_watermark(monkeypatch):
    slot, items = frames()
    cut = cut_for(slot, expiry=10)
    monkeypatch.setattr("wso_tvt_media.native_source.time.monotonic", lambda: 9)
    adapter = NativeFrameAdapter(PROOF)
    mux_packet(adapter, items[0], cut)
    monkeypatch.setattr("wso_tvt_media.native_source.time.monotonic", lambda: 11)
    assert mux_packet(adapter, items[1], cut).ordinal == 2
    with pytest.raises(MediaDenied):
        mux_packet(NativeFrameAdapter(PROOF), items[2], cut)


def test_legacy_exact_private_frame_gate_unchanged():
    slot, items = frames()
    with pytest.raises(MediaDenied):
        NativeFrameAdapter(PROOF).packet(items[0])
    assert mux_packet(NativeFrameAdapter(PROOF), items[0], cut_for(slot)).ordinal == 1


def test_registration_or_cut_replacement_blocks_later_packets():
    slot, items = frames()
    cut = cut_for(slot)
    adapter = NativeFrameAdapter(PROOF)
    mux_packet(adapter, items[0], cut)
    with pytest.raises(MediaDenied):
        mux_packet(adapter, items[1], cut_for(slot))


class Viewer:
    def __init__(self, items, cut):
        from test_local_media_mux_service import Admission
        from wso_core.tvt.local_media_mux_types import _GRANT_SEAL, ViewerGrant

        self.registration, self.cut = cut.registration, cut
        self.grant = ViewerGrant(
            scope=Admission().scope,
            slot=cut.slot,
            lease_id=uuid4(),
            registration=cut.registration,
            expires_monotonic=time.monotonic() + 30,
            _authority=object(),
            _seal=_GRANT_SEAL,
        )
        self.items = items
        self.released = []
        self.active = True
        self.closed = 0

    def current_grant(self):
        return self.grant

    def current(self):
        return self.active

    def read_frames(self, **_limits):
        result, self.items = self.items, ()
        if not result:
            time.sleep(0.005)
        return result

    def release_frames(self, batch):
        self.released.append(batch)

    def close(self):
        self.closed += 1


def source_api():
    name = "wso_tvt_media.mux_source"
    assert importlib.util.find_spec(name), "shared source port missing"
    return importlib.import_module(name)


def read(source):
    return source.read_frames(
        max_frames=16, max_bytes=4 << 20, deadline_monotonic=time.monotonic() + 1
    )


def test_exact_batch_credit_survives_until_every_downstream_picture_settles():
    slot, items = frames()
    batch = tuple(items)
    viewer = Viewer(batch, cut_for(slot))
    source = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, None
    )
    assert read(source) is batch
    source.release_frame(batch[0])
    source.release_frame(batch[1])
    assert viewer.released == []
    assert source.close() is None and viewer.closed == 0
    source.release_frame(batch[2])
    assert viewer.released[0] is batch
    source.close()
    assert viewer.closed == 1


def test_new_post_cut_key_and_sibling_progress():
    slot, items = frames()
    viewer = Viewer(tuple(items), cut_for(slot))
    source = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, None
    )
    from wso_core.tvt.local_media_mux_types import _GRANT_SEAL

    renewed = replace(
        viewer.grant, expires_monotonic=time.monotonic() + 40, _seal=_GRANT_SEAL
    )
    viewer.grant = renewed
    assert source.current()
    assert source.grant is renewed
    assert read(source) == tuple(items)
    for item in items:
        source.release_frame(item)
    source.close()


def test_denial_or_registration_change_blocks_late_decoder_output():
    slot, items = frames()
    viewer = Viewer(tuple(items), cut_for(slot))
    source = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, None
    )
    assert source.current()
    viewer.registration = uuid4()
    assert not source.current()
    with pytest.raises(MediaDenied):
        read(source)


def test_registration_change_inside_current_callback_is_rechecked():
    slot, items = frames()
    viewer = Viewer(tuple(items), cut_for(slot))
    source = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, None
    )

    def change():
        viewer.registration = uuid4()
        return True

    viewer.current = change
    assert not source.current()


async def test_mux_decoder_retains_batch_through_decode_and_original_retirement(
    monkeypatch,
):
    from wso_tvt_media.mux_budget import MediaCreditLedger
    from wso_tvt_media.native_source import NativeDecodedSource

    from tests.tvt_parity.test_local_media_format_transition import (
        Decoders,
        Native,
        until,
    )

    slot, items = frames(1)
    batch = tuple(items)
    viewer = Viewer(batch, cut_for(slot))
    credit = MediaCreditLedger()
    ingress = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, credit
    )
    decoders = Decoders(monkeypatch)
    decoders.decode_release.clear()
    source = NativeDecodedSource(
        Native(),
        viewer.grant.lease_id,
        Path(__file__),
        proof=PROOF,
        frame_source=ingress,
        media_credit=credit,
        registration=viewer.registration,
    )
    source.start()
    try:
        await until(decoders.decode_entered.is_set)
        assert viewer.released == []
        from wso_tvt_bridge.local_live_mux_ipc import media_credit_usage

        # _receive can retain the first RGB while _read owns a growing bytearray,
        # its last read bytes and the immutable result for the second response.
        assert media_credit_usage()[0] >= 5 * 640 * 480 * 3
        decoders.decode_release.set()
        await source.binding()
        await until(lambda: len(viewer.released) == 1)
        assert viewer.released[0] is batch
    finally:
        decoders.decode_release.set()
        await source.close()
    assert all(owner.closed for owner in decoders.owners)


async def test_mux_late_decode_after_registration_change_never_publishes(monkeypatch):
    from wso_tvt_media.mux_budget import MediaCreditLedger
    from wso_tvt_media.native_source import NativeDecodedSource

    from tests.tvt_parity.test_local_media_format_transition import (
        Decoders,
        Native,
        until,
    )

    slot, items = frames(1)
    viewer = Viewer(tuple(items), cut_for(slot))
    credit = MediaCreditLedger()
    ingress = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, credit
    )
    decoders = Decoders(monkeypatch)
    decoders.decode_release.clear()
    source = NativeDecodedSource(
        Native(),
        viewer.grant.lease_id,
        Path(__file__),
        proof=PROOF,
        frame_source=ingress,
        media_credit=credit,
        registration=viewer.registration,
    )
    source.start()
    try:
        await until(decoders.decode_entered.is_set)
        viewer.registration = uuid4()
        decoders.decode_release.set()
        await until(lambda: not source.alive())
        assert source.produced_frames == 0
    finally:
        decoders.decode_release.set()
        await source.close()


def test_worker_explicit_mux_factory_issues_exact_receipt_after_original_owners(
    monkeypatch,
):
    from wso_core.tvt.local_media_mux_types import ViewerCleanupReceipt
    from wso_tvt_media import worker
    from wso_tvt_media.mux_budget import MediaCreditLedger

    from tests.tvt_parity.test_local_media_worker import Core, Peer, Source, settle

    core = Core()
    registration = uuid4()
    core.registration = lambda _: registration
    core.binding_proof = core.proof

    class Factory:
        executor = core
        credit = MediaCreditLedger()

        async def __call__(self, *args, **kwargs):
            return Source(proof=kwargs["proof"])

    monkeypatch.setattr(worker, "LocalWebRtcSession", Peer)
    owner = worker.LocalMediaWorker(
        core, decoder_executable=Path(__file__).resolve(), source_factory=Factory()
    )
    try:
        owner.start("ticket", deadline_ms=1000, correlation_id="mux-test")
        assert core.barrier() is None
        deadline = time.monotonic() + 3
        while core.view.state != "CLOSED":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        receipt = core.barrier()
        assert type(receipt) is ViewerCleanupReceipt
        assert receipt.registration_id == registration
        assert receipt.lease_id == core.id
        assert core.barrier() is receipt
    finally:
        settle(owner)


async def test_same_mux_peer_decoded_delivery_rtp_fence_and_memory_retirement(
    monkeypatch,
):
    from aiortc.rtcdtlstransport import RTCDtlsTransport
    from wso_tvt_bridge.local_live_mux_ipc import media_credit_usage
    from wso_tvt_media.live import LocalWebRtcSession
    from wso_tvt_media.mux_budget import MediaCreditLedger
    from wso_tvt_media.native_source import NativeDecodedSource

    from tests.tvt_parity.test_local_media_format_transition import (
        Decoders,
        Native,
        until,
    )

    baseline = media_credit_usage()
    slot, items = frames(2)
    viewer = Viewer((items[0],), cut_for(slot))
    credit = MediaCreditLedger()
    ingress = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, credit
    )
    Decoders(monkeypatch)
    source = NativeDecodedSource(
        Native(),
        viewer.grant.lease_id,
        Path(__file__),
        proof=PROOF,
        frame_source=ingress,
        media_credit=credit,
        registration=viewer.registration,
    )
    sent = []

    async def sink(_self, packet):
        sent.append(packet)

    monkeypatch.setattr(RTCDtlsTransport, "_send_rtp", sink)
    source.start()
    peer = None
    try:
        binding = await source.binding()
        peer = LocalWebRtcSession(
            binding=binding,
            source=source,
            current=source.alive,
            permitted=source.transport_current,
            expires_at=time.monotonic() + 20,
            media_credit=credit,
            registration=viewer.registration,
        )
        first = await peer.track.recv()
        assert first.pts == 1000
        sender = peer.peer.getTransceivers()[0].sender
        await sender.transport._send_rtp(b"inert-one")
        viewer.items = (items[1],)
        second = await asyncio.wait_for(peer.track.recv(), 2)
        assert second.pts == 1024
        await sender.transport._send_rtp(b"inert-two")
        assert sent == [b"inert-one", b"inert-two"]
        assert media_credit_usage()[0] > baseline[0]
        viewer.active = False
        await until(lambda: not source.alive())
        with pytest.raises(ConnectionError):
            await sender.transport._send_rtp(b"late")
        assert len(sent) == 2
        del first, second
    finally:
        if peer is not None:
            await peer.close()
            await peer.wait_closed()
        await source.close()
    assert media_credit_usage() == baseline


async def test_dimension_rotation_waits_original_decoder(monkeypatch):
    from wso_tvt_media.mux_budget import MediaCreditLedger
    from wso_tvt_media.native_source import NativeDecodedSource

    from tests.tvt_parity.test_local_media_format_transition import (
        Decoders,
        Native,
        until,
    )

    slot, items = frames(2, shapes=[(352, 240), (1280, 720)])
    viewer = Viewer((items[0],), cut_for(slot))
    credit = MediaCreditLedger()
    ingress = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, credit
    )
    decoders = Decoders(monkeypatch)
    source = NativeDecodedSource(
        Native(),
        viewer.grant.lease_id,
        Path(__file__),
        proof=PROOF,
        frame_source=ingress,
        media_credit=credit,
        registration=viewer.registration,
    )
    source.start()
    try:
        await source.binding()
        decoders.close_release.clear()
        viewer.items = (items[1],)
        await until(decoders.close_entered.is_set)
        assert len(decoders.owners) == 1
        assert len(viewer.released) == 1
        assert source._latest is None
        decoders.close_release.set()
        await until(lambda: len(decoders.owners) == 2)
        await until(lambda: source.produced_frames == 2)
        assert [p.timestamp_us for p in decoders.packets] == [1000, 1024]
        assert [p.ordinal for p in decoders.packets] == [1, 2]
        # Publication precedes the decoder finally releasing its input credit.
        await until(lambda: len(viewer.released) == 2)
        assert len(viewer.released) == 2
    finally:
        decoders.close_release.set()
        await source.close()


async def test_held_complete_partial_and_old_rgb_cannot_seed_new_viewer(monkeypatch):
    from wso_tvt_media.mux_budget import MediaCreditLedger
    from wso_tvt_media.native_source import NativeDecodedSource

    from tests.tvt_parity.test_local_media_format_transition import (
        Decoders,
        Native,
        until,
    )

    codec, (slot,) = setup()
    opened(codec, slot)
    raw = wire(slot, 1, payload=KEY)
    assert feed(codec, raw[:31], 2) == ()
    item = feed(codec, raw[31:], 6)[0]
    assert (item.ingress.first, item.ingress.last) == (2, 6)
    viewer = Viewer((item,), cut_for(slot, after=4))
    credit = MediaCreditLedger()
    ingress = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, credit
    )
    decoders = Decoders(monkeypatch)
    source = NativeDecodedSource(
        Native(),
        viewer.grant.lease_id,
        Path(__file__),
        proof=PROOF,
        frame_source=ingress,
        media_credit=credit,
        registration=viewer.registration,
    )
    source.start()
    try:
        await until(lambda: not source.alive())
        assert source.produced_frames == 0 and source._latest is None
        assert not decoders.owners
        assert viewer.released[0][0] is item
    finally:
        await source.close()


@pytest.mark.parametrize("mode", ["sub", "main"])
async def test_explicit_factory_uses_only_selected_reader_and_original_release(
    monkeypatch, mode
):
    from wso_core.tvt.local_media_mux_service import MuxMediaExecutor
    from wso_tvt_bridge.local_live_mux_ipc import media_credit_usage
    from wso_tvt_media.mux_budget import MediaCreditLedger

    from tests.tvt_parity.test_local_media_format_transition import Decoders, Native
    from tests.tvt_parity.test_local_media_source import frame

    slot, items = frames(1)
    viewer = Viewer(tuple(items), cut_for(slot))
    baseline = media_credit_usage()

    class Core(MuxMediaExecutor):
        def __init__(self):
            self.readers = []
            self.main = (frame(),)

        def registration(self, _lease):
            return viewer.registration

        def source_mode(self, _lease):
            return mode

        def mux_binding(self, _lease):
            assert mode == "sub"
            return viewer, viewer.grant

        def current(self, _lease):
            return viewer.active

        def lease(self, _lease):
            return Native().lease(_lease)

        def read_mux_frames(self, _lease, **limits):
            assert mode == "sub"
            self.readers.append("sub")
            return viewer.read_frames(**limits)

        def release_mux_frames(self, _lease, batch):
            viewer.release_frames(batch)

        def read_dedicated_frames(self, _lease, **limits):
            assert mode == "main"
            self.readers.append("main")
            result, self.main = self.main, ()
            if not result:
                time.sleep(0.005)
            return result

        def read_frames(self, *_args, **_kwargs):
            pytest.fail("legacy reader used by explicit mux factory")

    core = Core()
    factory = source_api().MuxSourceFactory(core, MediaCreditLedger())
    Decoders(monkeypatch)
    source = await factory(viewer.grant.lease_id, Path(__file__), proof=PROOF)
    source.start()
    try:
        await source.binding()
        assert core.readers and set(core.readers) == {mode}
    finally:
        await source.close()
    assert media_credit_usage() == baseline
    if mode == "sub":
        assert viewer.released[0][0] is items[0]


async def test_failed_decode_retains_encoded_and_scratch_until_original_settles(
    monkeypatch,
):
    from wso_tvt_bridge.local_live_mux_ipc import media_credit_usage
    from wso_tvt_media import native_source
    from wso_tvt_media.mux_budget import MediaCreditLedger

    from tests.tvt_parity.test_local_media_format_transition import (
        Decoders,
        Native,
        until,
    )

    slot, items = frames(1)
    viewer = Viewer(tuple(items), cut_for(slot))
    credit = MediaCreditLedger()
    ingress = source_api().MuxFrameSource(
        viewer, viewer.grant, viewer.registration, viewer.cut, credit
    )
    decoders = Decoders(monkeypatch)
    decoders.close_release.clear()

    def fail_decode(_self, _packet):
        raise MediaDenied()

    monkeypatch.setattr(native_source.WindowsDecoder, "decode", fail_decode)
    source = native_source.NativeDecodedSource(
        Native(),
        viewer.grant.lease_id,
        Path(__file__),
        proof=PROOF,
        frame_source=ingress,
        media_credit=credit,
        registration=viewer.registration,
    )
    source.start()
    try:
        await until(decoders.close_entered.is_set)
        assert viewer.released == []
        assert media_credit_usage()[0] >= 5 * 640 * 480 * 3
    finally:
        decoders.close_release.set()
        await source.close()
    assert len(viewer.released) == 1


@pytest.mark.parametrize("occupied,allowed", [(11, True), (12, False)])
def test_shared_worker_twelve_source_admission(monkeypatch, occupied, allowed):
    from wso_core.tvt.local_service import LocalDeviceFailure
    from wso_tvt_media import worker
    from wso_tvt_media.mux_budget import MediaCreditLedger

    from tests.tvt_parity.test_local_media_worker import (
        Core,
        Peer,
        Source,
        on_loop,
        settle,
    )

    core = Core()
    core.registration = lambda _: registration
    core.binding_proof = core.proof
    registration = uuid4()

    class Factory:
        executor = core
        credit = MediaCreditLedger()

        async def __call__(self, *args, **kwargs):
            return Source(proof=kwargs["proof"])

    monkeypatch.setattr(worker, "LocalWebRtcSession", Peer)
    owner = worker.LocalMediaWorker(
        core, decoder_executable=Path(__file__).resolve(), source_factory=Factory()
    )
    occupied_ids = [uuid4() for _ in range(occupied)]
    try:
        on_loop(
            owner,
            lambda: owner._sources.update({key: Source() for key in occupied_ids}),
        )
        if allowed:
            owner.start("ticket", deadline_ms=1000, correlation_id="cap")
            assert core.id in owner._sources
        else:
            with pytest.raises(LocalDeviceFailure):
                owner.start("ticket", deadline_ms=1000, correlation_id="cap")
            assert core.id not in owner._sources
    finally:
        on_loop(owner, lambda: [owner._sources.pop(key, None) for key in occupied_ids])
        settle(owner)


async def test_dedicated_registration_substitution_denies_current_and_publication():
    from wso_core.tvt.local_media_mux_service import MuxMediaExecutor
    from wso_tvt_media.mux_budget import MediaCreditLedger
    from wso_tvt_media.native_source import NativeDecodedSource

    from tests.tvt_parity.test_local_media_format_transition import Native

    registration = uuid4()

    class Core(MuxMediaExecutor):
        def __init__(self):
            self.identity = registration

        def current(self, _lease):
            return True

        def registration(self, _lease):
            return self.identity

        def lease(self, lease):
            return Native().lease(lease)

    core = Core()
    source = NativeDecodedSource(
        core,
        uuid4(),
        Path(__file__),
        proof=PROOF,
        media_credit=MediaCreditLedger(),
        registration=registration,
        dedicated=True,
    )
    try:
        assert source.current()
        core.identity = uuid4()
        assert not source.current()
        with pytest.raises(MediaDenied):
            source._renew()
    finally:
        await source.close()


def test_r1_actual_sender_encode_blocks_credit_refund_and_worker_receipt(monkeypatch):
    """Exercise aiortc's real run_in_executor path, including stop cancellation."""
    import concurrent.futures
    import threading

    from aiortc import rtcrtpsender
    from aiortc.rtcrtpparameters import RTCRtpCodecParameters, RTCRtpSendParameters
    from wso_core.tvt.windows_decode import DecodeBinding, PrivateRGBFrame
    from wso_tvt_bridge.local_live_mux_ipc import media_credit_usage
    from wso_tvt_media import worker
    from wso_tvt_media.mux_budget import MediaCreditLedger
    from wso_tvt_media.native_source import NativeDecodedSource

    from tests.tvt_parity.test_local_media_worker import Core, settle

    entered, release, completed = (threading.Event() for _ in range(3))

    class Encoder:
        def encode(self, frame, force_keyframe):
            assert frame.width == frame.height == 2
            entered.set()
            assert release.wait(10)
            completed.set()
            return [], 0

    monkeypatch.setattr(rtcrtpsender, "get_encoder", lambda _: Encoder())
    baseline = media_credit_usage()
    core = Core()
    registration = uuid4()
    core.registration = lambda _: registration
    core.binding_proof = core.proof
    core.live_proof = PROOF
    binding = DecodeBinding(
        generation=1, owner=b"s" * 16, channel=b"c" * 16, task=b"t" * 16
    )

    class Source(NativeDecodedSource):
        def start(self):
            # No native/decoder threads: publish one inert frame to the actual sender.
            self._started_at = time.monotonic()
            self.adapter.binding = binding
            self._publish(PrivateRGBFrame(binding, 2, 2, 1000, 1, bytes(12)))

    class Factory:
        executor = core
        credit = MediaCreditLedger()

        async def __call__(self, lease_id, executable, *, proof, observe):
            return Source(
                core,
                lease_id,
                executable,
                proof=proof,
                observe=observe,
                media_credit=self.credit,
                registration=registration,
            )

    owner = worker.LocalMediaWorker(
        core, decoder_executable=Path(__file__).resolve(), source_factory=Factory()
    )
    waiter = None
    try:
        owner.start("ticket", deadline_ms=1000, correlation_id="encode-custody")
        peer = owner._peers[core.id]
        sender = peer.peer.getTransceivers()[0].sender
        future = asyncio.run_coroutine_threadsafe(
            sender.send(
                RTCRtpSendParameters(
                    codecs=[
                        RTCRtpCodecParameters(
                            mimeType="video/VP8", clockRate=90000, payloadType=96
                        )
                    ]
                )
            ),
            owner._loop,
        )
        future.result(2)
        assert entered.wait(2)
        charged = media_credit_usage()[0]
        assert charged > baseline[0]
        assert core.barrier() is None

        async def peer_stopped():
            while peer._peer_close_task is None:
                await asyncio.sleep(0.001)
            await asyncio.shield(peer._peer_close_task)

        asyncio.run_coroutine_threadsafe(peer_stopped(), owner._loop).result(2)
        waiter = asyncio.run_coroutine_threadsafe(peer.wait_closed(), owner._loop)
        with pytest.raises(concurrent.futures.TimeoutError):
            waiter.result(0.1)
        assert not completed.is_set()
        assert media_credit_usage()[0] == charged
        assert core.barrier() is None
        assert core.id in owner._sources and core.id in owner._peers
        release.set()
        assert completed.wait(2)
        waiter.result(2)
        deadline = time.monotonic() + 2
        while core.view.state != "CLOSED":
            assert time.monotonic() < deadline
            time.sleep(0.005)
        receipt = core.barrier()
        assert receipt is not None and receipt.peer_settled and receipt.media_cleared
        assert core.barrier() is receipt
        assert media_credit_usage() == baseline
    finally:
        release.set()
        if entered.is_set():
            assert completed.wait(2)
        if waiter is not None:
            waiter.result(2)
        settle(owner)


@pytest.mark.parametrize("mode", ["sub", "main"])
def test_r1_adapter_full_host_budget_does_not_copy_encoded_nals(mode):
    import tracemalloc

    from test_local_live import media, packet
    from wso_tvt_bridge.local_live_mux_ipc import (
        media_credit_usage,
        release_media_credit,
        reserve_media_credit,
    )
    from wso_tvt_media.mux_budget import MediaCreditLedger

    from tests.tvt_parity.test_local_media_source import frame

    payload = KEY + bytes(512 << 10)
    codec, (slot,) = setup()
    opened(codec, slot)
    body = media(index=1, payload=payload, channel=slot.channel)
    wrapper = feed(
        codec, packet(65537, body, flags=0, sequence=0, declared=len(body)), 2
    )[0]
    cut = cut_for(slot)
    original = wrapper.frame.private_bytes()
    if mode == "main":
        raw = frame(
            payload=(
                b"\0\0\0\1\x40\x01\x80\0\0\0\1\x42\x01\x80"
                b"\0\0\0\1\x44\x01\x80\0\0\0\1\x26\x01\x80"
            )
            + bytes(512 << 10)
        )
        original = raw.private_bytes()
    ledger = MediaCreditLedger()
    encoded = (
        ledger.reserve_encoded(slot, frames=1, bytes=len(original))
        if mode == "sub"
        else ledger.reserve_dedicated(uuid4(), frames=1, bytes=len(original))
    )
    assert encoded is not None
    available = (1 << 30) - media_credit_usage()[0]
    padding = reserve_media_credit(
        slot=None, registration=uuid4(), frames=0, bytes=available, stage="raw"
    )
    assert padding is not None
    adapter = NativeFrameAdapter(PROOF)
    try:
        assert media_credit_usage()[0] == 1 << 30
        tracemalloc.start()
        before = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        result = (
            adapter.packet_mux(wrapper, registration=cut.registration, cut=cut)
            if mode == "sub"
            else adapter.packet(raw)
        )
        peak = tracemalloc.get_traced_memory()[1] - before
        assert result._data is original
        # Bounded marker/view metadata is permitted, another 512KiB payload is not.
        assert peak < 128 << 10, f"uncharged adapter peak: {peak}"
        assert media_credit_usage()[0] == 1 << 30
    finally:
        tracemalloc.stop()
        release_media_credit(padding)
        ledger.release(encoded)


@pytest.mark.parametrize("case", ["fresh", "first_frame_invalid", "stale_binding"])
def test_r185_actual_mux_worker_uses_binding_proof_before_first_read(monkeypatch, case):
    import threading
    from types import SimpleNamespace

    from wso_core.tvt.local_media_mux_service import EpochState, MuxMediaExecutor
    from wso_core.tvt.local_media_service import LocalLiveProof
    from wso_core.tvt.local_service import LocalDeviceFailure
    from wso_tvt_media.mux_budget import MediaCreditLedger
    from wso_tvt_media.mux_source import MuxSourceFactory
    from wso_tvt_media.worker import LocalMediaWorker

    from tests.tvt_parity.test_local_media_format_transition import Decoders
    from tests.tvt_parity.test_local_media_worker import Core, settle

    slot, items = frames(1)
    if case == "first_frame_invalid":
        object.__setattr__(items[0].frame, "_data", b"invalid-annex-b")
    record = None

    class InitialViewer(Viewer):
        proof_value = PROOF
        reads = 0
        callback = None

        @property
        def proof(self):
            if case == "stale_binding":
                record.stopping = True
            return self.proof_value

        def read_frames(self, **kwargs):
            self.reads += 1
            result = super().read_frames(**kwargs)
            if result:
                self.proof_value = LocalLiveProof(
                    True, True, True, True, True, True, True, True, "h264"
                )
            return result

        def attach_retirement(self, callback):
            self.callback = callback

    viewer = InitialViewer(tuple(items), cut_for(slot))
    lease = SimpleNamespace(id=viewer.grant.lease_id)
    view = Core().view.model_copy(update={"id": lease.id})
    record = SimpleNamespace(
        lease=lease,
        handle=viewer,
        grant=viewer.grant,
        cut=viewer.cut,
        master=SimpleNamespace(
            scope=viewer.grant.scope,
            refresh_version=0,
            refreshing=False,
            state=EpochState.ACTIVE,
        ),
        slot=SimpleNamespace(identity=slot),
        stopping=False,
        starting=False,
        view=view,
    )
    coordinator = SimpleNamespace(
        _lock=threading.RLock(),
        _closed=False,
        _viewers={lease.id: record},
        _dedicated={},
        current=lambda ident: ident in coordinator._viewers and not record.stopping,
        attach=lambda *a, **k: viewer,
    )

    def retire(original):
        original.stopping = True
        if viewer.callback is None or viewer.callback() is None:
            return False
        coordinator._viewers.pop(lease.id, None)
        return True

    coordinator._close_viewer = retire
    coordinator.shutdown = lambda: not coordinator._viewers
    admission = SimpleNamespace(
        redeem=lambda *a, **k: lease,
        prepare_viewer=lambda *a, **k: SimpleNamespace(stream="sub"),
        view=lambda _: view,
    )
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    # Delivery proof is intentionally unavailable until the real first read.
    if case != "stale_binding":
        with pytest.raises(LocalDeviceFailure):
            executor.proof(lease.id)
    decoders = Decoders(monkeypatch)
    owner = LocalMediaWorker(
        executor,
        decoder_executable=Path(__file__).resolve(),
        source_factory=MuxSourceFactory(executor, MediaCreditLedger()),
    )
    try:
        if case == "fresh":
            result = owner.start("a" * 64, deadline_ms=2000, correlation_id="fresh-mux")
            assert result.lease.id == lease.id and viewer.reads > 0
            assert owner._sources[lease.id].produced_frames == 1
            owner._sources[lease.id].adapter.proof.validate(delivery=True)
            executor.proof(lease.id).validate(delivery=True)
        else:
            with pytest.raises(LocalDeviceFailure):
                owner.start("a" * 64, deadline_ms=2000, correlation_id="invalid-mux")
            assert lease.id not in owner._peers
            assert not decoders.owners
            assert (viewer.reads == 0) is (case == "stale_binding")
    finally:
        settle(owner)
