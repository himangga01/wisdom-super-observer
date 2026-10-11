"""Inert WebRTC acceptance; no native provider, credentials or user devices."""

import asyncio
import time
from fractions import Fraction

import pytest
from aiortc import RTCConfiguration, RTCPeerConnection
from aiortc.rtcdtlstransport import RTCDtlsTransport
from wso_core.tvt.windows_decode import DecodeBinding, PrivateRGBFrame
from wso_tvt_media.codec import FrameLimits, frame_to_video
from wso_tvt_media.live import BoundedDecodedSource, LocalWebRtcSession, MediaDenied
from wso_tvt_media.signaling import SignalingDenied, validate_offer


def binding(generation=1):
    return DecodeBinding(
        generation=generation, owner=b"o" * 16, channel=b"c" * 16, task=b"t" * 16
    )


def rgb(ordinal=1, timestamp=1_000_000, selected=None, width=64, height=48):
    return PrivateRGBFrame(
        selected or binding(),
        width,
        height,
        timestamp,
        ordinal,
        bytes([210, 40, 20]) * width * height,
    )


def test_codec_preserves_source_microseconds_and_rgb():
    frame = frame_to_video(rgb(timestamp=1_234_567), binding(), FrameLimits())
    assert frame.pts == 1_234_567
    assert frame.time_base == Fraction(1, 1_000_000)
    assert bytes(frame.planes[0])[:3] == bytes([210, 40, 20])


@pytest.mark.parametrize(
    "frame",
    [
        rgb(selected=binding(2)),
        rgb(width=4097),
        PrivateRGBFrame(binding(), 64, 48, 100, 1, b"short"),
    ],
)
def test_codec_rejects_wrong_binding_dimensions_and_payload(frame):
    with pytest.raises(MediaDenied):
        frame_to_video(frame, binding(), FrameLimits())


@pytest.mark.parametrize(
    "sdp",
    [
        "v=0\r\n" + "x" * 65536,
        "v=0\r\na=ice-server:https://untrusted.invalid\r\n",
        "v=0\r\n" + "a=candidate:x\r\n" * 65,
    ],
    ids=["oversize", "urls", "flood"],
)
def test_signaling_rejects_unbounded_or_url_configuration(sdp):
    with pytest.raises(SignalingDenied):
        validate_offer(sdp)


async def test_queue_overflow_and_revocation_discard_frames():
    current = [True]
    source = BoundedDecodedSource(
        binding=binding(),
        current=lambda: current[0],
        max_frames=1,
        max_bytes=64 * 48 * 3,
    )
    source.put_nowait(rgb())
    with pytest.raises(MediaDenied):
        source.put_nowait(rgb(2, 1_033_333))
    with pytest.raises(MediaDenied):
        await source.recv()
    assert source.buffered_bytes == 0
    source2 = BoundedDecodedSource(binding=binding(), current=lambda: current[0])
    source2.put_nowait(rgb())
    current[0] = False
    with pytest.raises(MediaDenied):
        await source2.recv()
    assert source2.buffered_bytes == 0


async def make_offer(peer):
    peer.addTransceiver("video", direction="recvonly")
    await peer.setLocalDescription(await peer.createOffer())
    return peer.localDescription.sdp


async def test_same_vp8_peer_presents_equal_raw_timestamps_as_distinct_rtp_frames():
    from aiortc import RTCSessionDescription
    from wso_tvt_media.native_source import NativeFrameAdapter

    from tests.tvt_parity.test_local_media_source import PROOF, frame

    adapter = NativeFrameAdapter(PROOF)
    packets = [
        adapter.packet(frame(timestamp=raw, index=index))
        for index, raw in enumerate([1000000] * 4 + [1100000, 1200000], 1)
    ]
    selected = packets[0].binding
    source = BoundedDecodedSource(binding=selected, current=lambda: True)
    delivered = []
    server = LocalWebRtcSession(
        binding=selected,
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 20,
        on_delivery=lambda item: delivered.append((item.timestamp_us, item.ordinal)),
    )
    original = server.peer
    client = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    track_ready = asyncio.Future()
    client.on("track", lambda track: track_ready.set_result(track))
    try:
        answer = await server.answer(await make_offer(client), "equal-raw-offer")
        await client.setRemoteDescription(
            RTCSessionDescription(answer.sdp, answer.type)
        )
        track = await asyncio.wait_for(track_ready, 5)
        for packet in packets:
            source.put_nowait(
                rgb(packet.ordinal, packet.timestamp_us, selected=selected)
            )
            await asyncio.sleep(0.06)
        received = [await asyncio.wait_for(track.recv(), 5) for _ in range(4)]
        assert [item.pts for item in received] == [0, 2, 4, 6]
        assert all(item.time_base == Fraction(1, 90000) for item in received)
        assert all((item.width, item.height) == (64, 48) for item in received)
        assert delivered == [
            (1000000, 1),
            (1000024, 2),
            (1000048, 3),
            (1000072, 4),
            (1100000, 5),
            (1200000, 6),
        ]
        assert server.peer is original and not server._fenced
    finally:
        await server.close()
        await client.close()
    assert server.peer.connectionState == "closed" and source.closed


async def test_real_loopback_encodes_vp8_and_closes_original_peer_on_revoke():
    current = [True]
    source = BoundedDecodedSource(binding=binding(), current=lambda: current[0])
    delivered = []
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: current[0],
        expires_at=time.monotonic() + 20,
        on_delivery=lambda value: delivered.append(value.timestamp_us),
    )
    client = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    track_ready = asyncio.Future()
    client.on("track", lambda track: track_ready.set_result(track))
    try:
        answer = await server.answer(await make_offer(client), "offer-1")
        assert answer.type == "answer"
        assert "a=sendonly" in answer.sdp
        assert "VP8/90000" in answer.sdp
        assert delivered == []
        from aiortc import RTCSessionDescription

        await client.setRemoteDescription(
            RTCSessionDescription(answer.sdp, answer.type)
        )
        track = await asyncio.wait_for(track_ready, 5)
        for ordinal in range(1, 5):
            source.put_nowait(rgb(ordinal, 1_000_000 + ordinal * 33_333))
            await asyncio.sleep(0.05)
        received = await asyncio.wait_for(track.recv(), 5)
        assert (received.width, received.height) == (64, 48)
        pixels = bytes(received.reformat(format="rgb24").planes[0])[:3]
        assert pixels[0] > 150 and pixels[1] < 80
        received_next = await asyncio.wait_for(track.recv(), 5)
        assert received.time_base == Fraction(1, 90_000)
        assert received_next.pts - received.pts in (2_999, 3_000)
        assert delivered[0] == 1_033_333
        current[0] = False
        await asyncio.wait_for(server.wait_closed(), 2)
        assert server.peer.connectionState == "closed"
        assert source.buffered_bytes == 0
        with pytest.raises(MediaDenied):
            server.renew(time.monotonic() + 10)
        with pytest.raises(SignalingDenied):
            await server.answer(answer.sdp, "offer-2")
    finally:
        await server.close()
        await client.close()


async def test_offer_replay_closes_session_and_no_frames_before_offer():
    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 15,
    )
    client = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    try:
        sdp = await make_offer(client)
        await server.answer(sdp, "one")
        with pytest.raises(SignalingDenied):
            await server.answer(sdp, "one")
        assert server.peer.connectionState == "closed"
    finally:
        await server.close()
        await client.close()


async def test_original_vp8_peer_receives_up_and_down_resolution_with_increasing_pts():
    from aiortc import RTCSessionDescription

    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 20,
    )
    client = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    track_ready = asyncio.Future()
    client.on("track", lambda track: track_ready.set_result(track))
    original = server.peer
    ordinal, last_pts = 0, -1
    try:
        answer = await server.answer(await make_offer(client), "resolution-offer")
        await client.setRemoteDescription(
            RTCSessionDescription(answer.sdp, answer.type)
        )
        track = await asyncio.wait_for(track_ready, 5)
        for width, height in [(352, 240), (1280, 720), (352, 240)]:
            for _ in range(3):
                ordinal += 1
                source.put_nowait(
                    rgb(
                        ordinal,
                        1_000_000 + ordinal * 100_000,
                        width=width,
                        height=height,
                    )
                )
                await asyncio.sleep(0.1)
            while True:
                received = await asyncio.wait_for(track.recv(), 5)
                assert received.pts > last_pts
                last_pts = received.pts
                if (received.width, received.height) == (width, height):
                    break
            assert server.peer is original and not server._fenced
    finally:
        await server.close()
        await client.close()


async def test_expiry_and_cancel_close_source_and_reject_late_offer():
    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 0.08,
    )
    await asyncio.wait_for(server.wait_closed(), 2)
    assert source.closed
    with pytest.raises(SignalingDenied):
        await server.answer("v=0\r\n", "late")


async def test_rtp_send_and_retransmit_fence_current_authority():
    current = [True]
    source = BoundedDecodedSource(binding=binding(), current=lambda: current[0])
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: current[0],
        expires_at=time.monotonic() + 15,
    )
    try:
        current[0] = False
        # This is the original sender's DTLS boundary used by encoded RTP,
        # RTCP and retransmits. Denial must happen before networking.
        with pytest.raises(ConnectionError):
            await server.peer.getTransceivers()[0].sender.transport._send_rtp(b"inert")
        current[0] = True
        with pytest.raises(MediaDenied):
            server.renew(time.monotonic() + 10)
        await asyncio.wait_for(server.wait_closed(), 2)
        assert server.peer.connectionState == "closed"
    finally:
        await server.close()


async def test_renew_is_bounded_and_no_revive_after_expiry():
    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 1,
    )
    try:
        server.renew(time.monotonic() + 2)
        assert server.peer.connectionState != "closed"
        with pytest.raises(MediaDenied):
            server.renew(time.monotonic() + 31)
    finally:
        await server.close()


async def test_cancelled_frame_read_closes_original_session():
    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 15,
    )
    pending = asyncio.create_task(server.track.recv())
    try:
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(server.wait_closed(), 0.3)
        assert source.closed
        assert server.peer.connectionState == "closed"
    finally:
        await server.close()


async def test_nonincreasing_source_pts_fences_peer():
    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 15,
    )
    try:
        source.put_nowait(rgb(1, 1_000_000))
        await server.track.recv()
        source.put_nowait(rgb(2, 999_999))
        from aiortc.mediastreams import MediaStreamError

        with pytest.raises(MediaStreamError):
            await server.track.recv()
        # A later good frame cannot escape before scheduled disposal runs.
        source.put_nowait(rgb(3, 1_000_001))
        with pytest.raises(MediaStreamError):
            await server.track.recv()
        await asyncio.wait_for(server.wait_closed(), 1)
        assert source.closed
    finally:
        await server.close()


async def test_cleanup_failure_still_closes_peer_and_cannot_report_clean_close():
    class FailingSource(BoundedDecodedSource):
        async def close(self):
            await super().close()
            raise ValueError("private upstream detail")

    source = FailingSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 15,
    )
    with pytest.raises(MediaDenied, match="local media unavailable"):
        await server.close()
    assert server.peer.connectionState == "closed"
    with pytest.raises(MediaDenied):
        await server.wait_closed()
    assert server.original_close_failed is True


@pytest.mark.parametrize("sdp", ["\ud800", "v=0\r\nm=invalid\r\n"])
def test_invalid_sdp_encoding_and_syntax_return_fixed_denial(sdp):
    with pytest.raises(SignalingDenied):
        validate_offer(sdp)


async def test_sendrecv_browser_offer_is_rejected_and_peer_closed():
    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 15,
    )
    client = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    try:
        offer = await make_offer(client)
        with pytest.raises(SignalingDenied):
            await server.answer(offer.replace("a=recvonly", "a=sendrecv"), "wrong")
        assert server.peer.connectionState == "closed"
        assert source.closed
    finally:
        await server.close()
        await client.close()


@pytest.mark.parametrize("attribute", ["a=candidate", "a=fmtp:97 x=1"])
def test_sdp_parser_edge_failures_return_fixed_signaling_denial(attribute):
    base = (
        "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=recvonly\r\na=rtcp-mux\r\na=rtpmap:96 VP8/90000\r\n"
    )
    with pytest.raises(SignalingDenied):
        validate_offer(base + attribute + "\r\n")


async def test_signaling_denial_survives_uncertain_source_cleanup():
    class FailingSource(BoundedDecodedSource):
        async def close(self):
            await super().close()
            raise ValueError("private upstream detail")

    source = FailingSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 15,
    )
    with pytest.raises(SignalingDenied):
        await server.answer("v=0\r\n", "invalid")
    assert server.peer.connectionState == "closed"
    with pytest.raises(MediaDenied):
        await server.wait_closed()


async def test_signaling_cancellation_survives_uncertain_source_cleanup():
    class FailingSource(BoundedDecodedSource):
        async def close(self):
            await super().close()
            raise ValueError("private upstream detail")

    answer_task = None
    answer_checks = 0

    def current():
        nonlocal answer_checks
        if asyncio.current_task() is answer_task:
            answer_checks += 1
            if answer_checks == 2:
                answer_task.cancel()
        return True

    source = FailingSource(binding=binding(), current=current)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=current,
        expires_at=time.monotonic() + 15,
    )
    client = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    try:
        offer = await make_offer(client)
        answer_task = asyncio.create_task(server.answer(offer, "cancel"))
        with pytest.raises(asyncio.CancelledError):
            await answer_task
        assert server.peer.connectionState == "closed"
        with pytest.raises(MediaDenied):
            await server.wait_closed()
    finally:
        with pytest.raises(MediaDenied):
            await server.close()
        await client.close()


async def test_slow_original_peer_close_survives_timeout_and_settles_same_peer(
    monkeypatch,
):
    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 15,
    )
    transceiver = server.peer.getTransceivers()[0]
    original_stop = transceiver.stop
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def slow_original_stop():
        entered.set()
        await gate.wait()
        await original_stop()

    monkeypatch.setattr(transceiver, "stop", slow_original_stop)
    try:
        with pytest.raises(MediaDenied):
            await server.close()
        assert entered.is_set()
        pending_confirmation = asyncio.create_task(server.wait_closed())
        await asyncio.sleep(0)
        assert not pending_confirmation.done()
        # A later close awaits aiortc's same original internal future. The
        # timeout must leave the original close owner able to complete it.
        same_peer_close = asyncio.create_task(server.peer.close())
        gate.set()
        await asyncio.wait_for(same_peer_close, 1)
        with pytest.raises(MediaDenied):
            await asyncio.wait_for(pending_confirmation, 1)
        assert server.peer.connectionState == "closed"
        # Only the caller's bounded wait timed out; the original settled cleanly.
        assert server.original_close_failed is False
    finally:
        gate.set()


async def test_slow_original_source_close_survives_timeout_and_waits_actual_owner():
    gate = asyncio.Event()

    class SlowSource(BoundedDecodedSource):
        async def close(self):
            await gate.wait()
            await super().close()

    source = SlowSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 15,
    )
    try:
        with pytest.raises(MediaDenied):
            await server.close()
        confirmed = asyncio.create_task(server.wait_closed())
        await asyncio.sleep(0)
        assert not confirmed.done() and not source.closed
        gate.set()
        with pytest.raises(MediaDenied):
            await asyncio.wait_for(confirmed, 1)
        assert source.closed and server.peer.connectionState == "closed"
        assert server.original_close_failed is False
    finally:
        gate.set()


def stale_session(monkeypatch, permit, *, current=lambda: True):
    sent = []

    async def sink(transport, data):
        sent.append(data)

    # Only DTLS encryption is replaced; the session's hook wraps this sink.
    monkeypatch.setattr(RTCDtlsTransport, "_send_rtp", sink)
    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=current,
        permitted=lambda: permit[0],
        expires_at=time.monotonic() + 15,
    )
    hook = server.peer.getTransceivers()[0].sender.transport._send_rtp
    return source, server, hook, sent


async def test_stale_permit_withholds_media_without_fencing(monkeypatch):
    permit = [False]
    source, server, hook, sent = stale_session(monkeypatch, permit)
    pending = None
    try:
        # Construction is not fenced by a momentarily stale permit.
        assert not server._fenced
        # A stale datagram is dropped and returns normally: ConnectionError
        # would end aiortc's original RTP/RTCP sender.
        assert await hook(b"stale") is None and sent == []
        server.renew(time.monotonic() + 10)
        source.put_nowait(rgb(1, 1_000_000))
        pending = asyncio.create_task(server.track.recv())
        await asyncio.sleep(0.2)
        assert not pending.done() and not server._fenced and sent == []
        permit[0] = True
        source.put_nowait(rgb(2, 1_100_000))
        video = await asyncio.wait_for(pending, 1)
        assert video.pts == 1_100_000  # The stale frame never left.
        await hook(b"fresh")
        assert sent == [b"fresh"] and not server._fenced
        assert server.peer.connectionState != "closed"
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
        await server.close()


async def test_stale_permit_does_not_fence_answer(monkeypatch):
    permit = [False]
    _, server, _, _ = stale_session(monkeypatch, permit)
    client = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    try:
        answer = await server.answer(await make_offer(client), "stale")
        assert answer.type == "answer" and not server._fenced
        assert server.peer.connectionState != "closed"
    finally:
        await server.close()
        await client.close()


async def test_stale_grace_fences_and_any_permitted_observation_resets(monkeypatch):
    from wso_tvt_media import live

    assert live.STALE_GRACE_SECONDS == 2.0
    monkeypatch.setattr(live, "STALE_GRACE_SECONDS", 0.5)
    permit = [False]
    source, server, hook, sent = stale_session(monkeypatch, permit)
    try:
        # Two 0.25 s stale periods separated by permitted watcher observations
        # never reach the 0.5 s continuous grace.
        await asyncio.sleep(0.25)
        permit[0] = True
        await asyncio.sleep(0.15)
        permit[0] = False
        await asyncio.sleep(0.25)
        assert not server._fenced
        await asyncio.wait_for(server.wait_closed(), 2)
        assert server._fenced and source.closed
        assert server.peer.connectionState == "closed"
        permit[0] = True
        with pytest.raises(MediaDenied):
            server.renew(time.monotonic() + 10)
        with pytest.raises(ConnectionError):
            await hook(b"late")
        assert sent == []
    finally:
        await server.close()


async def test_revocation_while_stale_is_terminal_and_never_revived(monkeypatch):
    permit, current = [False], [True]
    source, server, hook, sent = stale_session(
        monkeypatch, permit, current=lambda: current[0]
    )
    try:
        assert await hook(b"stale") is None
        current[0] = False
        with pytest.raises(ConnectionError):
            await hook(b"revoked")
        await asyncio.wait_for(server.wait_closed(), 2)
        current[0] = permit[0] = True
        with pytest.raises(MediaDenied):
            server.renew(time.monotonic() + 10)
        with pytest.raises(ConnectionError):
            await hook(b"revived")
        assert sent == [] and source.closed
    finally:
        await server.close()


async def test_original_peer_close_failure_is_reported_read_only_and_sticky(
    monkeypatch,
):
    source = BoundedDecodedSource(binding=binding(), current=lambda: True)
    server = LocalWebRtcSession(
        binding=binding(),
        source=source,
        current=lambda: True,
        expires_at=time.monotonic() + 15,
    )
    original_close = server.peer.close

    async def failing_original_close():
        await original_close()
        raise RuntimeError("inert original close failure")

    monkeypatch.setattr(server.peer, "close", failing_original_close)
    assert server.original_close_failed is False
    with pytest.raises(AttributeError):
        server.original_close_failed = True
    with pytest.raises(MediaDenied):
        await server.close()
    with pytest.raises(MediaDenied):
        await asyncio.wait_for(server.wait_closed(), 2)
    assert server.original_close_failed is True and source.closed
    assert server.peer.connectionState == "closed"


async def test_optional_observation_counts_lapses_and_actual_withholding(monkeypatch):
    permit = [False]
    source, server, hook, sent = stale_session(monkeypatch, permit)
    try:
        assert server.observation_counts is None
        counts = server.enable_observation()
        await hook(b"one")
        await hook(b"two")
        assert counts == {
            "permit_lapse_episodes": 1,
            "withheld_datagrams": 2,
            "withheld_decoded_frames": 0,
        }
        permit[0] = True
        await hook(b"fresh")
        permit[0] = False
        await hook(b"three")
        assert counts["permit_lapse_episodes"] == 2
        assert counts["withheld_datagrams"] == 3
        source.put_nowait(rgb(1, 1_000_000))
        pending = asyncio.create_task(server.track.recv())
        await asyncio.sleep(0)
        assert counts["withheld_decoded_frames"] == 1
        permit[0] = True
        source.put_nowait(rgb(2, 1_100_000))
        assert (await asyncio.wait_for(pending, 1)).pts == 1_100_000
        assert sent == [b"fresh"] and not server._fenced
    finally:
        await server.close()
