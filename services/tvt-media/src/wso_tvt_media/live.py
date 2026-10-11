"""Original-peer lifetime fenced by the continuously checked local lease."""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCRtpSender,
    RTCSessionDescription,
    VideoStreamTrack,
)
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame
from wso_core.tvt.windows_decode import DecodeBinding, PrivateRGBFrame

from .codec import FrameLimits, MediaDenied, frame_to_video, validate_frame
from .native_source import FailureObserver, NativeDecodedSource, observe_failure
from .signaling import SessionAnswer, SignalingDenied, validate_offer

if TYPE_CHECKING:
    from aiortc.rtcrtpparameters import RTCRtpCodecParameters
    from aiortc.rtcrtpsender import RTCEncodedFrame

    from .mux_budget import MediaCredit, MediaCreditLedger

# A stale (not revoked) emission permit withholds media at most this long.
STALE_GRACE_SECONDS = 2.0


class AuthorizedDecodedSource(Protocol):
    async def recv(self) -> PrivateRGBFrame: ...
    async def close(self) -> None: ...


class BoundedDecodedSource:
    """Single-loop queue; overflow permanently fences and discards queued RGB.

    Native callbacks must enqueue on their separate bounded private transport;
    this queue is fed by an admitted decoder adapter on the media event loop.
    """

    def __init__(
        self,
        *,
        binding: DecodeBinding,
        current: Callable[[], bool],
        max_frames: int = 3,
        max_bytes: int = 16 * 1024 * 1024,
        limits: FrameLimits | None = None,
    ) -> None:
        if (
            type(binding) is not DecodeBinding
            or not callable(current)
            or type(max_frames) is not int
            or not 1 <= max_frames <= 16
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 64 * 1024 * 1024
        ):
            raise MediaDenied()
        self.binding = binding
        self.current = current
        self.limits = limits or FrameLimits()
        self.limits.validate()
        self.max_frames, self.max_bytes = max_frames, max_bytes
        self._frames: deque[PrivateRGBFrame] = deque()
        self._bytes = 0
        self._ready = asyncio.Event()
        self.closed = False

    @property
    def buffered_bytes(self) -> int:
        return self._bytes

    def _fence(self) -> None:
        self.closed = True
        self._frames.clear()
        self._bytes = 0
        self._ready.set()

    def _check(self) -> None:
        try:
            allowed = not self.closed and self.current() is True
        except Exception:  # noqa: BLE001 -- authority errors deny every frame.
            allowed = False
        if not allowed:
            self._fence()
            raise MediaDenied()

    def put_nowait(self, frame: PrivateRGBFrame) -> None:
        try:
            self._check()
            data = validate_frame(frame, self.binding, self.limits)
            if (
                len(self._frames) >= self.max_frames
                or self._bytes + len(data) > self.max_bytes
            ):
                raise MediaDenied()
            self._check()
            self._frames.append(frame)
            self._bytes += len(data)
            self._ready.set()
        except Exception:  # noqa: BLE001 -- no private exception leaves this boundary.
            self._fence()
            raise MediaDenied() from None

    async def recv(self) -> PrivateRGBFrame:
        while True:
            self._check()
            if self._frames:
                frame = self._frames.popleft()
                self._bytes -= len(frame.private_rgb())
                self._check()
                return frame
            self._ready.clear()
            await self._ready.wait()

    async def close(self) -> None:
        self._fence()


class _AuthorizedTrack(VideoStreamTrack):
    def __init__(self, owner: LocalWebRtcSession) -> None:
        super().__init__()
        self.owner = owner
        self._ordinal = 0
        self._source_timestamp: int | None = None

    async def recv(self) -> VideoFrame:
        frame = None
        try:
            while True:
                self.owner._check()
                frame = await self.owner.source.recv()
                self.owner._check()
                if self.owner._permitted():
                    break
                if self.owner.observation_counts is not None:
                    self.owner.observation_counts["withheld_decoded_frames"] += 1
                self.owner._release_rgb(frame)
                frame = None
                # Stale, not revoked: withhold this frame and wait for a fresh
                # one; the watcher bounds how long staleness may last.
            self.owner._reserve_conversion(frame)
            video = frame_to_video(frame, self.owner.binding, self.owner.limits)
            if frame.ordinal <= self._ordinal or (
                self._source_timestamp is not None
                and frame.timestamp_us <= self._source_timestamp
            ):
                raise MediaDenied()
            self.owner._check()
            if self.owner.on_delivery is not None:
                self.owner.on_delivery(frame)
            self.owner._check()
            self._ordinal, self._source_timestamp = frame.ordinal, frame.timestamp_us
            return video
        except asyncio.CancelledError:
            self.owner._schedule_close()
            raise
        except Exception:  # noqa: BLE001 -- decoder/callback failures stop RTP.
            self.owner._schedule_close()
            raise MediaStreamError() from None
        finally:
            if frame is not None:
                self.owner._release_rgb(frame)


class LocalWebRtcSession:
    """Single offer / original source and peer. renew never revives a fence.

    current is supplied by trusted worker authority, not a browser callback;
    False fences permanently. permitted, when supplied, is the emission
    permit: False while current is True is staleness, which withholds media
    and fences only after STALE_GRACE_SECONDS. Omitted, it reuses current.
    on_delivery observes admission to the RTP encoder, not browser rendering.
    Actual PLAYING acceptance needs the browser's received-frame observation.
    """

    def __init__(
        self,
        *,
        binding: DecodeBinding,
        source: AuthorizedDecodedSource,
        current: Callable[[], bool],
        expires_at: float,
        permitted: Callable[[], bool] | None = None,
        limits: FrameLimits | None = None,
        on_delivery: Callable[[PrivateRGBFrame], None] | None = None,
        observe: FailureObserver | None = None,
        media_credit: MediaCreditLedger | None = None,
        registration: UUID | None = None,
    ) -> None:
        if media_credit is not None and type(registration) is not UUID:
            raise MediaDenied()
        self._media_credit, self._registration = media_credit, registration
        self._conversion: list[MediaCredit] = []
        self._conversion_bytes = 0
        self._encode_tasks: set[asyncio.Task[RTCEncodedFrame | None]] = set()
        if (
            type(binding) is not DecodeBinding
            or not callable(current)
            or (permitted is not None and not callable(permitted))
        ):
            raise MediaDenied()
        self._observe = observe
        self.binding, self.source, self.current = binding, source, current
        self.permitted = permitted
        self.limits, self.on_delivery = limits or FrameLimits(), on_delivery
        self.limits.validate()
        self._closed = False
        self._fenced = False
        self._stale_since: float | None = None
        self.observation_counts: dict[str, int] | None = None
        self._cleanup_failed = False
        self._original_close_failed = False
        self._closed_event = asyncio.Event()
        self._close_task: asyncio.Task[None] | None = None
        self._source_close_task: asyncio.Task[None] | None = None
        self._peer_close_task: asyncio.Task[None] | None = None
        self._settlement_task: asyncio.Task[None] | None = None
        self._offered = False
        self.expires_at = self._deadline(expires_at)
        self._check()
        self.peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.track = _AuthorizedTrack(self)
        transceiver = self.peer.addTransceiver(self.track, direction="sendonly")
        if self._media_credit is not None:
            # aiortc cancels _run_rtp on stop, but an encoder callable submitted
            # to run_in_executor continues owning its AV input. Shield the exact
            # original encode coroutine, retaining its executor await until the
            # callable really returns. Do not replace/reimplement its encoder.
            original_next = transceiver.sender._next_encoded_frame

            async def retained_next(
                codec: RTCRtpCodecParameters,
            ) -> RTCEncodedFrame | None:
                task = asyncio.create_task(original_next(codec))
                self._encode_tasks.add(task)
                task.add_done_callback(self._encode_finished)
                return await asyncio.shield(task)

            transceiver.sender._next_encoded_frame = retained_next  # type: ignore[method-assign]
        # VP8 is baseline browser WebRTC support; opaque HEVC never enters RTP.
        transceiver.setCodecPreferences(
            [
                codec
                for codec in RTCRtpSender.getCapabilities("video").codecs
                if codec.mimeType.lower() == "video/vp8"
            ]
        )
        # aiortc 1.15 encodes in an executor after track.recv(). Fence the
        # original transport too, including RTP retransmits, after that await.
        # The pinned dependency and transport regression test protect this hook.
        transport = transceiver.sender.transport
        original_send = transport._send_rtp

        async def fenced_send(data: bytes) -> None:
            try:
                self._check()
            except MediaDenied:
                self._schedule_close()
                raise ConnectionError("local media unavailable") from None
            # A stale permit drops this datagram and returns normally:
            # ConnectionError would end aiortc's original _run_rtp.
            if self._permitted():
                await original_send(data)
            elif self.observation_counts is not None:
                self.observation_counts["withheld_datagrams"] += 1

        transport._send_rtp = fenced_send  # type: ignore[method-assign]

        @self.peer.on("connectionstatechange")
        async def state_change() -> None:
            state = self.peer.connectionState
            if state in ("failed", "closed"):
                observe_failure(
                    self._observe,
                    "peer_connection",
                    "connection_failed" if state == "failed" else "connection_closed",
                )
                self._schedule_close()
            elif state == "connected":
                observe_failure(self._observe, "milestone", "peer_connected")

        self._monitor = asyncio.create_task(self._watch())

    def enable_observation(self) -> dict[str, int]:
        """Fixture opt-in counters; no callbacks, I/O or authority decisions."""
        if self.observation_counts is None:
            self.observation_counts = {
                "permit_lapse_episodes": 0,
                "withheld_datagrams": 0,
                "withheld_decoded_frames": 0,
            }
        return self.observation_counts

    def _release_rgb(self, frame: PrivateRGBFrame) -> None:
        if self._media_credit is not None:
            if not isinstance(self.source, NativeDecodedSource):
                raise MediaDenied()
            self.source.release_rgb(frame)

    def _reserve_conversion(self, frame: PrivateRGBFrame) -> None:
        if self._media_credit is None:
            return
        assert self._registration is not None
        # One sender serially awaits each encode. Retain a conservative aligned
        # high-water charge for its current/previous video, padded conversion
        # buffers and encoder input until the original sender/peer has settled.
        # A returned AV VideoFrame cannot carry a Python weakref finalizer.
        aligned = ((frame.width * 3 + 63) // 64) * 64 * frame.height
        needed = 6 * aligned
        if needed > self._conversion_bytes:
            credit = self._media_credit.reserve_conversion(
                self._registration, needed - self._conversion_bytes
            )
            if credit is None:
                raise MediaDenied()
            self._conversion.append(credit)
            self._conversion_bytes = needed

    def _encode_finished(self, task: asyncio.Task[RTCEncodedFrame | None]) -> None:
        if task.cancelled():
            # Our cancellation boundary never cancels this original. An
            # unexpected external cancellation cannot certify executor custody.
            self._original_close_failed = True
            self._cleanup_failed = True
        else:
            task.exception()  # Retrieve errors even after the RTP waiter stopped.
        self._encode_tasks.discard(task)

    @staticmethod
    def _deadline(value: float) -> float:
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 < value - time.monotonic() <= 30
        ):
            raise MediaDenied()
        return float(value)

    def _check(self) -> None:
        reason = "current_false"
        try:
            # Preserve the original short-circuit order and call current once.
            if self._closed:
                allowed, reason = False, "closed"
            elif self._fenced:
                allowed, reason = False, "fenced"
            elif not time.monotonic() < self.expires_at:
                allowed, reason = False, "deadline"
            else:
                allowed = self.current() is True
        except Exception:  # noqa: BLE001 -- authority infrastructure fails closed.
            allowed, reason = False, "current_error"
        if not allowed:
            observe_failure(self._observe, "peer_check", reason)
            self._fenced = True
            raise MediaDenied()

    def _permitted(self) -> bool:
        """Non-raising emission predicate; call after _check().

        False is staleness: nothing leaves, nothing fences here. Any permitted
        observation resets the stale timer that the watcher bounds.
        """
        if self.permitted is None:
            return True  # Reuses current, which _check() just enforced.
        try:
            allowed = self.permitted() is True
        except Exception:  # noqa: BLE001 -- an unreadable permit withholds media.
            allowed = False
        if allowed:
            self._stale_since = None
        elif self._stale_since is None:
            self._stale_since = time.monotonic()
            if self.observation_counts is not None:
                self.observation_counts["permit_lapse_episodes"] += 1
        return allowed

    def renew(self, expires_at: float) -> None:
        self._check()
        try:
            next_deadline = self._deadline(expires_at)
        except MediaDenied:
            observe_failure(self._observe, "peer_deadline", "invalid_deadline")
            raise
        self._check()
        self.expires_at = next_deadline

    async def _watch(self) -> None:
        try:
            while True:
                await asyncio.sleep(
                    min(0.05, max(0.001, self.expires_at - time.monotonic()))
                )
                self._check()
                if getattr(self.source, "closed", False):
                    observe_failure(self._observe, "peer_watch", "source_ended")
                    raise MediaDenied()
                if not self._permitted():
                    since = self._stale_since
                    if (
                        since is not None
                        and time.monotonic() - since > STALE_GRACE_SECONDS
                    ):
                        observe_failure(self._observe, "peer_watch", "stale_permit")
                        raise MediaDenied()
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001 -- watcher errors fence the original owner.
            self._schedule_close()

    def _schedule_close(self) -> None:
        observe_failure(self._observe, "peer", "close_scheduled")
        self._fenced = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._dispose())

    async def answer(self, offer_sdp: str, offer_id: str) -> SessionAnswer:
        try:
            self._check()
            if (
                self._offered
                or type(offer_id) is not str
                or not 1 <= len(offer_id) <= 128
            ):
                raise SignalingDenied()
            self._offered = True
            validate_offer(offer_sdp)
            remaining = self.expires_at - time.monotonic()
            async with asyncio.timeout(min(10, remaining)):
                await self.peer.setRemoteDescription(
                    RTCSessionDescription(offer_sdp, "offer")
                )
                self._check()
                await self.peer.setLocalDescription(await self.peer.createAnswer())
            self._check()
            description = self.peer.localDescription
            if description is None or len(description.sdp.encode("utf-8")) > 65536:
                raise SignalingDenied()
            return SessionAnswer(description.sdp)
        except asyncio.CancelledError:
            # Disposal keeps its uncertainty flag; preserve caller cancellation.
            with suppress(MediaDenied):
                await asyncio.shield(self.close())
            raise
        except Exception:  # noqa: BLE001 -- fixed signaling error, never private SDP detail.
            # wait_closed/close still expose uncertain original-source disposal.
            with suppress(MediaDenied):
                await self.close()
            raise SignalingDenied() from None

    async def close(self, reason: str = "closed") -> None:
        del reason  # Caller text is never returned in public error messages.
        observe_failure(self._observe, "peer", "explicit_close")
        self._fenced = True
        self._schedule_close()
        assert self._close_task is not None
        # A cancelled request must not cancel ownership disposal.
        await asyncio.shield(self._close_task)
        if self._cleanup_failed:
            raise MediaDenied()

    async def _dispose(self) -> None:
        self._closed = True
        self._fenced = True
        self.track.stop()
        self._monitor.cancel()
        # Retain original resource owners separately from bounded caller waits.
        # Cancelling aiortc.close after its internal future is created strands
        # later close callers, so timeouts can cancel only these shielded waits.
        self._source_close_task = asyncio.create_task(self.source.close())
        try:
            try:
                async with asyncio.timeout(3):
                    await asyncio.shield(self._source_close_task)
            except Exception:  # noqa: BLE001 -- bounded wait uncertainty is fixed/public.
                self._cleanup_failed = True
        finally:
            self._peer_close_task = asyncio.create_task(self.peer.close())
            self._settlement_task = asyncio.create_task(self._settle_resources())
        try:
            async with asyncio.timeout(3):
                await asyncio.shield(self._peer_close_task)
        except Exception:  # noqa: BLE001 -- bounded wait uncertainty is fixed/public.
            self._cleanup_failed = True

    async def _settle_resources(self) -> None:
        settled = False
        try:
            for task in (self._source_close_task, self._peer_close_task):
                assert task is not None
                try:
                    await asyncio.shield(task)
                except Exception:  # noqa: BLE001 -- original close failure remains observable.
                    self._cleanup_failed = True
                    self._original_close_failed = True
            # Peer closure stops further sender calls, so only retained original
            # operations remain. Never cancel them to meet a controller timeout.
            while self._encode_tasks:
                await asyncio.gather(
                    *(asyncio.shield(task) for task in tuple(self._encode_tasks)),
                    return_exceptions=True,
                )
            settled = True
        finally:
            if (
                settled
                and not self._original_close_failed
                and self._media_credit is not None
            ):
                for credit in self._conversion:
                    self._media_credit.release(credit)
                self._conversion.clear()
                self._conversion_bytes = 0
            # Includes the actual encoder callable; RTP/peer coroutine exit or
            # cancellation of this settlement waiter is not that barrier.
            if settled:
                self._closed_event.set()

    @property
    def original_close_failed(self) -> bool:
        """True only when an original source/peer close task itself raised.

        A bounded caller wait that timed out while the original later settled
        cleanly is uncertainty (wait_closed raises), not an original failure.
        """
        return self._original_close_failed

    async def wait_closed(self) -> None:
        await self._closed_event.wait()
        if self._cleanup_failed:
            raise MediaDenied()
