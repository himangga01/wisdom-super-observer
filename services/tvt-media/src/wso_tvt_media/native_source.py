"""Private source-bound access units and an owned continuous decode producer."""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from uuid import UUID

from wso_core.tvt.local_live import PrivateLiveFrame
from wso_core.tvt.local_media_service import LocalLiveProof, LocalMediaExecutor
from wso_core.tvt.local_service import LocalDeviceFailure
from wso_core.tvt.windows_decode import (
    DecodeBinding,
    DecodeLimits,
    ElementaryPacket,
    PrivateRGBFrame,
    WindowsDecoder,
)

from .codec import MediaDenied

# Emission permit: at most this long after a pre-SQL authority observation.
PERMIT_SECONDS = 0.2
# Fresh SQL lease reads independent of decoded-frame cadence.
AUTHORITY_HEARTBEAT_SECONDS = 0.05
# An executor read with no frame by its deadline is terminal (it denies and
# closes the lease), so this is also the tolerated compressed-arrival gap.
INGRESS_READ_DEADLINE_MS = 2000


class NativeFrameAdapter:
    """Initial live profile: one primary Annex B picture, increasing source PTS."""

    def __init__(self, proof: LocalLiveProof) -> None:
        try:
            proof.validate()
        except LocalDeviceFailure:
            raise MediaDenied() from None
        self.proof = proof
        self.binding: DecodeBinding | None = None
        self._format: tuple[str, int, int] | None = None
        self._pts: int | None = None
        self._ordinal = 0
        self._failed = False

    def packet(self, frame: PrivateLiveFrame) -> ElementaryPacket:
        try:
            if self._failed or type(frame) is not PrivateLiveFrame:
                raise MediaDenied()
            summary = frame.summary()
            data = frame.private_bytes()
            timestamp = frame.device_timestamp.unix_microseconds
            if (
                type(timestamp) is not int
                or not -(2**63) <= timestamp < 2**63
                or (self._pts is not None and timestamp <= self._pts)
                or not 1 <= len(data) <= 4 * 1024 * 1024
                or summary.codec not in {"h264", "h265"}
                or not 1 <= summary.width <= 4096
                or not 1 <= summary.height <= 2160
                or summary.width * summary.height * 3 > 16 * 1024 * 1024
                or frame.source_context[3] != 0
            ):
                raise MediaDenied()
            identity = frame.identity
            binding = DecodeBinding(
                generation=identity.generation,
                owner=identity.session,
                channel=identity.channel,
                task=identity.task,
            )
            if self.binding is not None and binding._wire() != self.binding._wire():
                raise MediaDenied()
            format = (summary.codec, summary.width, summary.height)
            if self._format is not None and format != self._format:
                raise MediaDenied()
            markers = list(islice(re.finditer(b"\x00\x00(?:\x00)?\x01", data), 129))
            if not markers or markers[0].start() != 0 or len(markers) > 128:
                raise MediaDenied()
            units = [
                data[
                    m.end() : markers[i + 1].start()
                    if i + 1 < len(markers)
                    else len(data)
                ]
                for i, m in enumerate(markers)
            ]
            if summary.codec == "h265":
                if any(
                    len(n) < 3
                    or n[0] & 128
                    or (n[0] & 1)
                    or (n[1] >> 3)
                    or not (n[1] & 7)
                    for n in units
                ):
                    raise MediaDenied()
                kinds = [(n[0] >> 1) & 63 for n in units]
                pictures = [n for n, k in zip(units, kinds, strict=True) if k < 32]
                if (
                    any(k >= 32 and k not in {32, 33, 34, 35, 39, 40} for k in kinds)
                    or len(pictures) != 1
                    or not (pictures[0][2] & 128)
                ):
                    raise MediaDenied()
                if self.binding is None and (
                    not frame.key_frame
                    or not {32, 33, 34}.issubset(kinds)
                    or not 16 <= ((pictures[0][0] >> 1) & 63) <= 21
                ):
                    raise MediaDenied()
            else:
                if any(len(n) < 2 or n[0] & 128 for n in units):
                    raise MediaDenied()
                kinds = [n[0] & 31 for n in units]
                pictures = [n for n, k in zip(units, kinds, strict=True) if k in {1, 5}]
                if (
                    any(k not in {1, 5, 6, 7, 8, 9, 12} for k in kinds)
                    or len(pictures) != 1
                    or not (pictures[0][1] & 128)
                ):
                    raise MediaDenied()
                if self.binding is None and (
                    not frame.key_frame or not {5, 7, 8}.issubset(kinds)
                ):
                    raise MediaDenied()
            self.binding = binding
            self._format = format
            self._pts = timestamp
            self._ordinal += 1
            codec = "hevc" if summary.codec == "h265" else "h264"
            self.proof = replace(
                self.proof,
                codec_supported=True,
                framing_verified=True,
                timing_verified=True,
                codec=codec,
            )
            return ElementaryPacket(
                data,
                binding=binding,
                codec=codec,
                format="annexb",
                generation=binding.generation,
                width=summary.width,
                height=summary.height,
                timestamp_us=timestamp,
                ordinal=self._ordinal,
                encrypted=False,
            )
        except Exception:  # noqa: BLE001 -- permanently fence malformed private media.
            self._failed = True
            raise MediaDenied() from None


class NativeDecodedSource:
    """Owned ingress, decoder and authority stages; bounded compressed FIFO order.

    All compressed pictures are decoded in source order. Only already-decoded
    RGB pictures may be replaced when a browser is not yet ready or is slow.
    One pending notification and one RGB frame bound event-loop backpressure.
    The authority stage renews the emission permit independent of cadence.
    """

    def __init__(
        self,
        executor: LocalMediaExecutor,
        lease_id: UUID,
        executable: Path,
        *,
        proof: LocalLiveProof,
    ) -> None:
        self.executor, self.lease_id, self.executable = executor, lease_id, executable
        # The caller fetches the proof off the event loop; validation is unchanged.
        self.adapter = NativeFrameAdapter(proof)
        self._loop = asyncio.get_running_loop()
        self._ready = asyncio.Event()
        self._settled = asyncio.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._encoded: deque[ElementaryPacket] = deque()
        self._encoded_bytes = 0
        self._latest: PrivateRGBFrame | None = None
        self._permit_deadline = 0.0
        self._ended = False
        self._failure = False
        self.produced_frames = 0
        self._ingress_done = threading.Event()
        self._decoder_done = threading.Event()
        self._authority_done = threading.Event()
        self._started = False
        self._ingress = threading.Thread(
            target=self._run_ingress, name="local-live-ingress-owner", daemon=False
        )
        self._thread = threading.Thread(
            target=self._run_decoder, name="local-live-decoder-owner", daemon=False
        )
        self._authority = threading.Thread(
            target=self._run_authority, name="local-live-authority-owner", daemon=False
        )
        # Retain every original thread/completion owner before any start.
        self._threads = (self._ingress, self._thread, self._authority)
        self._thread_done = (
            self._ingress_done,
            self._decoder_done,
            self._authority_done,
        )

    def start(self) -> None:
        if self._stop.is_set() or self._started:
            raise MediaDenied()
        self._started = True
        try:
            for thread in self._threads:
                thread.start()
        except BaseException:
            self._failure = True
            self._signal_stop()
            for thread, done in zip(self._threads, self._thread_done, strict=True):
                if thread.ident is None:
                    self._stage_done(done)
            raise

    def current(self) -> bool:
        return (
            not self._stop.is_set()
            and not self._ended
            and self.executor.current(self.lease_id)
        )

    def alive(self) -> bool:
        """No SQL/native work: stop, revocation and end are permanent."""
        with self._lock:
            return not self._stop.is_set() and not self._ended

    def transport_current(self) -> bool:
        """No SQL/native work: emission permit of a fresh SQL observation."""
        with self._lock:
            return (
                not self._stop.is_set()
                and not self._ended
                and time.monotonic() < self._permit_deadline
            )

    def _renew(self, frame: PrivateRGBFrame | None = None) -> bool:
        """One fresh SQL lease read renews the permit; frame publishes with it.

        SQL latency consumes, rather than extends, the bounded window, which is
        clipped to the actual lease expiry. A slow but successful read renews
        nothing and drops frame: staleness is not revocation. Denial raises.
        """
        observed = time.monotonic()
        lease = self.executor.lease(self.lease_id)
        now = time.monotonic()
        left = (lease.expires_at - datetime.now(UTC)).total_seconds()
        deadline = min(observed + PERMIT_SECONDS, now + left)
        if now >= deadline:
            return False
        with self._lock:
            if self._stop.is_set():
                return False
            # Each candidate is bounded by its own observation and lease
            # expiry; an older round finishing later never shortens a newer.
            self._permit_deadline = max(self._permit_deadline, deadline)
            notify = frame is not None and self._latest is None
            if frame is not None:
                self._latest = frame
                self.produced_frames += 1
        if notify:
            self._post(self._ready.set)
        return True

    def _publish(self, frame: PrivateRGBFrame) -> None:
        # lease() is the fresh exact authority check; a late one drops frame.
        self._renew(frame)

    def _post(self, callback: Callable[[], object]) -> None:
        # A closed loop must not skip decoder retirement or stage settlement.
        with suppress(RuntimeError):
            self._loop.call_soon_threadsafe(callback)

    def _signal_stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._latest = None
            self._permit_deadline = 0
            self._encoded.clear()
            self._encoded_bytes = 0
            self._condition.notify_all()
        self._post(self._ready.set)

    def _stage_done(self, done: threading.Event) -> None:
        done.set()
        if all(event.is_set() for event in self._thread_done):
            self._ended = True
            self._post(self._ready.set)
            self._post(self._settled.set)

    def _run_authority(self) -> None:
        try:
            while not self._stop.wait(AUTHORITY_HEARTBEAT_SECONDS):
                self._renew()
        except BaseException:  # noqa: BLE001 -- denial or authority failure fences.
            self._failure = True
        finally:
            self._signal_stop()
            self._stage_done(self._authority_done)

    def _run_ingress(self) -> None:
        try:
            while not self._stop.is_set():
                if not self.current():
                    raise MediaDenied()
                frames = self.executor.read_frames(
                    self.lease_id,
                    max_frames=16,
                    max_bytes=4 * 1024 * 1024,
                    deadline_ms=INGRESS_READ_DEADLINE_MS,
                )
                for raw in frames:
                    if type(raw) is not PrivateLiveFrame:
                        raise MediaDenied()
                    packet = self.adapter.packet(raw)
                    if not self.current():
                        raise MediaDenied()
                    with self._condition:
                        if (
                            self._stop.is_set()
                            or len(self._encoded) >= 16
                            or self._encoded_bytes + len(packet._data) > 4 * 1024 * 1024
                        ):
                            raise MediaDenied()
                        self._encoded.append(packet)
                        self._encoded_bytes += len(packet._data)
                        self._condition.notify()
        except BaseException:  # noqa: BLE001 -- private ingress always fences on failure.
            self._failure = True
        finally:
            self._signal_stop()
            self._stage_done(self._ingress_done)

    def _take_packet(self) -> ElementaryPacket | None:
        # Lock-only: decoder authorize and the authority stage hold fresh SQL.
        with self._condition:
            while not self._stop.is_set():
                if self._encoded:
                    packet = self._encoded.popleft()
                    self._encoded_bytes -= len(packet._data)
                    return packet
                self._condition.wait(0.05)
        return None

    def _run_decoder(self) -> None:
        decoder: WindowsDecoder | None = None
        try:
            while (packet := self._take_packet()) is not None:
                if decoder is None:
                    decoder = WindowsDecoder(
                        binding=packet.binding,
                        authorize=lambda _binding: self.current(),
                        executable=self.executable,
                        limits=DecodeLimits(
                            max_width=4096,
                            max_height=2160,
                            max_frame_bytes=16 * 1024 * 1024,
                            max_output_bytes=32 * 1024 * 1024,
                            max_response_frames=2,
                            continuous=True,
                            inactivity_seconds=5,
                        ),
                    )
                for frame in decoder.decode(packet):
                    self._publish(frame)
        except BaseException:  # noqa: BLE001 -- decoder failures stay private and fenced.
            self._failure = True
        finally:
            self._signal_stop()
            if decoder is not None:
                while True:
                    try:
                        decoder.close()
                        if decoder.wait_closed() is True:
                            break
                    except BaseException:  # noqa: BLE001 -- retain exact cleanup owner on interruption.
                        self._failure = True
                    time.sleep(0.01)
            self._stage_done(self._decoder_done)

    async def recv(self) -> PrivateRGBFrame:
        """Raises only when stopped/ended; the session enforces the permit."""
        while True:
            with self._lock:
                if self._stop.is_set() or self._ended:
                    raise MediaDenied()
                frame, self._latest = self._latest, None
                self._ready.clear()
            if frame is not None:
                return frame
            await self._ready.wait()

    async def binding(self) -> DecodeBinding:
        while self.adapter.binding is None or self.produced_frames == 0:
            if not self.alive():
                raise MediaDenied()
            await self._ready.wait()
        if not self.alive():
            raise MediaDenied()
        return self.adapter.binding

    async def close(self) -> None:
        self._signal_stop()
        for thread, done in zip(self._threads, self._thread_done, strict=True):
            if thread.ident is None:
                self._stage_done(done)
        await asyncio.shield(self._settled.wait())
        for thread in self._threads:
            if thread.ident is not None:
                thread.join()
        if not self._ended:
            raise MediaDenied()
