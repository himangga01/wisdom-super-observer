"""Private source-bound access units and an owned continuous decode producer."""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from wso_core.tvt.frames import FrameTimestamp
from wso_core.tvt.local_live import LiveIdentity, PrivateLiveFrame
from wso_core.tvt.local_media_admission import AUTHORITY_FRESHNESS_SECONDS
from wso_core.tvt.local_media_mux_service import MuxMediaExecutor
from wso_core.tvt.local_media_mux_types import IngressCut, MuxValidatedFrame
from wso_core.tvt.local_media_service import LocalLiveProof, LocalMediaExecutor
from wso_core.tvt.local_service import FIRST_FRAME_SECONDS, LocalDeviceFailure
from wso_core.tvt.windows_decode import (
    DecodeBinding,
    DecodeLimits,
    ElementaryPacket,
    PrivateRGBFrame,
    WindowsDecoder,
)

from .codec import FrameLimits, MediaDenied, validate_frame

if TYPE_CHECKING:
    from .mux_budget import MediaCredit, MediaCreditLedger
    from .mux_source import MuxFrameSource

# Emission permit: at most this long after a pre-SQL authority observation.
PERMIT_SECONDS = 0.2
# Gate-answered lease reads independent of decoded-frame cadence.
AUTHORITY_HEARTBEAT_SECONDS = 0.05
# An executor read with no frame by its deadline is terminal (it denies and
# closes the lease), so this is also the tolerated compressed-arrival gap.
INGRESS_READ_DEADLINE_MS = 2000
FORMAT_WAIT_SECONDS = 5.0
FORMAT_ROTATIONS = 16
FORMAT_WINDOW_SECONDS = 60.0
QUEUE_WAIT_SECONDS = 5.0
TIMESTAMP_DELTA_LIMIT_US = 2**31 - 1
# More than two 90 kHz ticks, including int(Fraction) truncation across zero.
PRESENTATION_STEP_US = 24


FailureObserver = Callable[[str, str], None]


def observe_failure(observe: FailureObserver | None, stage: str, reason: str) -> None:
    """Optional in-memory fixture sink; never owns resources or authority."""
    if observe is not None:
        try:
            observe(stage, reason)
        except BaseException:  # noqa: BLE001, S110 -- diagnostics must not log or alter custody.
            pass


def failure_reason(error: BaseException) -> str:
    if isinstance(error, LocalDeviceFailure):
        return {
            "LOCAL_DEVICE_DENIED": "denied",
            "LOCAL_DEVICE_DEADLINE_EXCEEDED": "deadline",
            "LOCAL_DEVICE_NO_SIGNAL": "no_signal",
            "LOCAL_DEVICE_PROTOCOL_INVALID": "protocol_invalid",
            "LOCAL_DEVICE_CANCELLED": "cancelled",
            "LOCAL_DEVICE_BUSY": "busy",
            "LOCAL_DEVICE_GENERATION_CONFLICT": "generation_conflict",
            "LOCAL_DEVICE_UPSTREAM_REJECTED": "upstream_rejected",
        }.get(error.code, "failure")
    if isinstance(error, TimeoutError):
        return "deadline"
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    return "failure"


class MediaNoSignal(MediaDenied):
    """An authorized source supplied no first decoded frame within its bound."""


class NativeFrameAdapter:
    """One primary Annex B picture, nondecreasing raw and strict presentation PTS."""

    def __init__(
        self,
        proof: LocalLiveProof,
        *,
        observe: FailureObserver | None = None,
        allow_dimension_changes: bool = False,
    ) -> None:
        self._observe = observe
        try:
            proof.validate()
        except LocalDeviceFailure:
            observe_failure(self._observe, "adapter", "proof_invalid")
            raise MediaDenied() from None
        self.proof = proof
        self.binding: DecodeBinding | None = None
        self._format: tuple[str, int, int] | None = None
        self._pts: int | None = None  # Original derived device time, never mapped.
        self._mapped_pts: int | None = None
        self._ordinal = 0
        self._failed = False
        self._allow_dimension_changes = allow_dimension_changes
        self._waiting_configuration = False
        self.random_access = False
        self._observation_context: tuple[int, int, int, int, int] | None = None
        self._mux_cut: IngressCut | None = None

    def _observe_timestamp_failure(
        self, frame: PrivateLiveFrame, timestamp: object
    ) -> None:
        # Timestamp rejection precedes scope validation. Only an already accepted
        # original binding/context may supply optional failure metadata; this does
        # not admit the rejected frame or change the existing guard order.
        if self._observe is None:
            return
        try:
            identity, context = frame.identity, frame.source_context
            if (
                self.binding is None
                or self._pts is None
                or type(identity) is not LiveIdentity
                or type(frame.device_timestamp) is not FrameTimestamp
                or type(context) is not tuple
                or len(context) != 5
                or any(type(value) is not int for value in context)
                or context != self._observation_context
                or context[3] != 0
                or type(identity.generation) is not int
                or identity.generation != self.binding.generation
                or any(
                    type(value) is not bytes
                    for value in (identity.session, identity.channel, identity.task)
                )
                or (identity.session, identity.channel, identity.task)
                != (self.binding.owner, self.binding.channel, self.binding.task)
            ):
                return
            if timestamp is None:
                detail = "missing,,0"
            elif type(timestamp) is not int or not -(2**63) <= timestamp < 2**63:
                detail = "invalid,,0"
            elif timestamp == self._pts:
                detail = "duplicate,0,0"
            elif timestamp < self._pts:
                delta = timestamp - self._pts
                saturated = delta < -TIMESTAMP_DELTA_LIMIT_US
                detail = f"regression,{max(-TIMESTAMP_DELTA_LIMIT_US, delta)},{int(saturated)}"
            else:
                return
            observe_failure(self._observe, "timestamp_failure", detail)
        except BaseException:  # noqa: BLE001, S110 -- optional metadata cannot change fencing.
            pass

    def packet(self, frame: PrivateLiveFrame) -> ElementaryPacket:
        if self._mux_cut is not None:
            self._failed = True
            raise MediaDenied()
        return self._packet(frame)

    def packet_mux(
        self, frame: MuxValidatedFrame, *, registration: UUID, cut: IngressCut
    ) -> ElementaryPacket:
        """Consume the original post-cut wrapper and its persistent slot clock."""
        try:
            if (
                self._failed
                or type(frame) is not MuxValidatedFrame
                or type(cut) is not IngressCut
                or type(registration) is not UUID
                or cut.registration != registration
                or frame.slot != cut.slot
                or frame.slot.epoch != cut.epoch
                or frame.ingress.first <= cut.after_ordinal
                or (self._mux_cut is not None and self._mux_cut is not cut)
                or (self._mux_cut is None and self.binding is not None)
                or (
                    self._mux_cut is None
                    and (
                        time.monotonic() >= cut.expires_monotonic
                        or not frame.frame.key_frame
                    )
                )
                or frame.slot_ordinal <= self._ordinal
                or (
                    self._mapped_pts is not None
                    and frame.mapped_timestamp_us <= self._mapped_pts
                )
            ):
                raise MediaDenied()
            identity = frame.frame.identity
            if (
                type(frame.frame) is not PrivateLiveFrame
                or type(identity) is not LiveIdentity
                or (
                    identity.generation,
                    identity.session,
                    identity.channel,
                    identity.task,
                )
                != (
                    cut.epoch.generation,
                    cut.epoch.session,
                    cut.slot.channel,
                    cut.slot.task,
                )
                or frame.frame.source_context[1] != 2
            ):
                raise MediaDenied()
            packet = self._packet(
                frame.frame, mapped=(frame.mapped_timestamp_us, frame.slot_ordinal)
            )
            if self._mux_cut is None and not self.random_access:
                raise MediaDenied()
            self._mux_cut = cut
            return packet
        except Exception:  # noqa: BLE001 -- malformed wrappers permanently fence this adapter.
            self._failed = True
            raise MediaDenied() from None

    def _packet(
        self, frame: PrivateLiveFrame, *, mapped: tuple[int, int] | None = None
    ) -> ElementaryPacket:
        reason = "validation_failure"
        try:
            if self._failed or type(frame) is not PrivateLiveFrame:
                reason = "frame_invalid"
                raise MediaDenied()
            summary = frame.summary()
            data = frame.private_bytes()
            timestamp = frame.device_timestamp.unix_microseconds
            if (
                type(timestamp) is not int
                or not -(2**63) <= timestamp < 2**63
                or (self._pts is not None and timestamp < self._pts)
            ):
                reason = "timestamp_invalid"
                self._observe_timestamp_failure(frame, timestamp)
                raise MediaDenied()
            if (
                not 1 <= len(data) <= 4 * 1024 * 1024
                or summary.codec not in {"h264", "h265"}
                or not 1 <= summary.width <= 4096
                or not 1 <= summary.height <= 2160
                or summary.width * summary.height * 3 > 16 * 1024 * 1024
            ):
                reason = "metadata_invalid"
                raise MediaDenied()
            if frame.source_context[3] != 0:
                reason = "scope_invalid"
                raise MediaDenied()
            identity = frame.identity
            binding = DecodeBinding(
                generation=identity.generation,
                owner=identity.session,
                channel=identity.channel,
                task=identity.task,
            )
            if self.binding is not None and binding._wire() != self.binding._wire():
                reason = "identity_changed"
                raise MediaDenied()
            format = (summary.codec, summary.width, summary.height)
            changed = self._format is not None and format != self._format
            if (
                self._format is not None
                and changed
                and (not self._allow_dimension_changes or format[0] != self._format[0])
            ):
                reason = "format_changed"
                raise MediaDenied()
            needs_configuration = (
                self.binding is None or changed or self._waiting_configuration
            )
            markers = list(islice(re.finditer(b"\x00\x00(?:\x00)?\x01", data), 129))
            if not markers or markers[0].start() != 0 or len(markers) > 128:
                reason = "framing_invalid"
                raise MediaDenied()
            # Inspect bounded NAL headers through views of the already charged
            # original payload; bytes slices would allocate an uncharged copy.
            view = memoryview(data)
            units = [
                view[
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
                    reason = "header_invalid"
                    raise MediaDenied()
                kinds = [(n[0] >> 1) & 63 for n in units]
                pictures = [n for n, k in zip(units, kinds, strict=True) if k < 32]
                if (
                    any(k >= 32 and k not in {32, 33, 34, 35, 39, 40} for k in kinds)
                    or len(pictures) != 1
                    or not (pictures[0][2] & 128)
                ):
                    reason = "picture_unsupported"
                    raise MediaDenied()
                picture_kind = (pictures[0][0] >> 1) & 63
                random_picture = 16 <= picture_kind <= 21
                configured = {32, 33, 34}.issubset(kinds) and random_picture
                if needs_configuration and not random_picture and picture_kind > 9:
                    reason = "picture_unsupported"
                    raise MediaDenied()
                if needs_configuration and (
                    self.binding is None or frame.key_frame or random_picture
                ):
                    if not frame.key_frame:
                        reason = "initial_picture_unsupported"
                        raise MediaDenied()
                    if not {32, 33, 34}.issubset(kinds):
                        reason = "parameter_sets_missing"
                        raise MediaDenied()
                    if not random_picture:
                        reason = "initial_picture_unsupported"
                        raise MediaDenied()
            else:
                if any(len(n) < 2 or n[0] & 128 for n in units):
                    reason = "header_invalid"
                    raise MediaDenied()
                kinds = [n[0] & 31 for n in units]
                pictures = [n for n, k in zip(units, kinds, strict=True) if k in {1, 5}]
                if (
                    any(k not in {1, 5, 6, 7, 8, 9, 12} for k in kinds)
                    or len(pictures) != 1
                    or not (pictures[0][1] & 128)
                ):
                    reason = "picture_unsupported"
                    raise MediaDenied()
                random_picture = 5 in kinds
                configured = {5, 7, 8}.issubset(kinds)
                if needs_configuration and (
                    self.binding is None or frame.key_frame or random_picture
                ):
                    if not frame.key_frame:
                        reason = "initial_picture_unsupported"
                        raise MediaDenied()
                    if not {5, 7, 8}.issubset(kinds):
                        reason = "parameter_sets_or_idr_missing"
                        raise MediaDenied()
            mapped_pts = (
                timestamp
                if self._mapped_pts is None
                else max(timestamp, self._mapped_pts + PRESENTATION_STEP_US)
            )
            if mapped is not None:
                mapped_pts = mapped[0]
            if mapped_pts >= 2**63:
                reason = "timestamp_invalid"
                raise MediaDenied()
            ordinal = self._ordinal + 1 if mapped is None else mapped[1]
            codec = "hevc" if summary.codec == "h265" else "h264"
            proof = replace(
                self.proof,
                codec_supported=True,
                framing_verified=True,
                timing_verified=True,
                codec=codec,
            )
            packet = ElementaryPacket(
                data,
                binding=binding,
                codec=codec,
                format="annexb",
                generation=binding.generation,
                width=summary.width,
                height=summary.height,
                timestamp_us=mapped_pts,
                ordinal=ordinal,
                encrypted=False,
            )
            self.binding = binding
            self.random_access = bool(frame.key_frame and configured)
            self._waiting_configuration = needs_configuration and not self.random_access
            self._format = format
            self._pts, self._mapped_pts, self._ordinal = timestamp, mapped_pts, ordinal
            self.proof = proof
            if self._observe is not None and self._observation_context is None:
                self._observation_context = frame.source_context
            if self._ordinal == 1:
                observe_failure(self._observe, "milestone", "first_adapter_packet")
            return packet
        except Exception:  # noqa: BLE001 -- permanently fence malformed private media.
            observe_failure(self._observe, "adapter", reason)
            self._failed = True
            raise MediaDenied() from None


@dataclass(frozen=True, slots=True)
class _QueuedPicture:
    packet: ElementaryPacket
    random_access: bool
    epoch: int
    release: Callable[[], None] | None = None


class NativeDecodedSource:
    """Owned ingress, decoder and authority stages; bounded compressed FIFO order.

    Compressed pictures stay in source order. Validated inter pictures awaiting
    a new format's configuration may be omitted within the transition bound.
    RGB pictures may be replaced when a browser is not yet ready or is slow.
    One pending notification and one RGB frame bound event-loop backpressure.
    The authority stage renews the emission permit independent of cadence.
    """

    def __init__(
        self,
        executor: LocalMediaExecutor | MuxMediaExecutor,
        lease_id: UUID,
        executable: Path,
        *,
        proof: LocalLiveProof,
        observe: FailureObserver | None = None,
        frame_source: MuxFrameSource | None = None,
        media_credit: MediaCreditLedger | None = None,
        registration: UUID | None = None,
        dedicated: bool = False,
    ) -> None:
        self.executor, self.lease_id, self.executable = executor, lease_id, executable
        self.frame_source, self.media_credit = frame_source, media_credit
        self.registration, self._dedicated = registration, dedicated
        if (frame_source is not None or dedicated or media_credit is not None) and (
            media_credit is None or type(registration) is not UUID
        ):
            raise MediaDenied()
        self._latest_credit: MediaCredit | None = None
        self._received_credit: dict[int, tuple[PrivateRGBFrame, MediaCredit]] = {}
        # The caller fetches the proof off the event loop; validation is unchanged.
        self._observe = observe
        self.adapter = NativeFrameAdapter(
            proof, observe=observe, allow_dimension_changes=True
        )
        self._loop = asyncio.get_running_loop()
        self._ready = asyncio.Event()
        self._settled = asyncio.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._encoded: deque[_QueuedPicture] = deque()
        self._encoded_bytes = 0
        self._observed_format: tuple[str, int, int] | None = None
        self._format_epoch = 0
        self._transition_deadline: float | None = None
        self._pressure_deadline: float | None = None
        self._published_pts: int | None = None
        self._published_ordinal = 0
        self._latest: PrivateRGBFrame | None = None
        self._permit_deadline = 0.0
        self._ended = False
        self._failure = False
        self.produced_frames = 0
        self._ingress_done = threading.Event()
        self._decoder_done = threading.Event()
        self._authority_done = threading.Event()
        self._started = False
        self._started_at: float | None = None
        self._first_frame_at: float | None = None
        self._thread_attempted = [False, False, False]
        self._thread_entered = tuple(threading.Event() for _ in range(3))
        self._thread_exited = tuple(threading.Event() for _ in range(3))
        self._thread_joined = [False, False, False]
        self._start_done = threading.Event()
        self._start_done.set()
        self._ingress = threading.Thread(
            target=lambda: self._run_owned(0, self._run_ingress),
            name="local-live-ingress-owner",
            daemon=False,
        )
        self._thread = threading.Thread(
            target=lambda: self._run_owned(1, self._run_decoder),
            name="local-live-decoder-owner",
            daemon=False,
        )
        self._authority = threading.Thread(
            target=lambda: self._run_owned(2, self._run_authority),
            name="local-live-authority-owner",
            daemon=False,
        )
        # Retain every original thread/completion owner before any start.
        self._threads = (self._ingress, self._thread, self._authority)
        self._thread_done = (
            self._ingress_done,
            self._decoder_done,
            self._authority_done,
        )

    def start(self) -> None:
        with self._lock:
            if self._stop.is_set() or self._started:
                raise MediaDenied()
            self._started = True
            self._start_done.clear()
            self._started_at = time.monotonic()
        try:
            for index, thread in enumerate(self._threads):
                start = thread.start
                with self._lock:
                    stopped = self._stop.is_set()
                    if not stopped:
                        self._thread_attempted[index] = True
                if stopped:
                    for remaining in self._thread_done[index:]:
                        self._stage_done(remaining)
                    break
                start()
        except BaseException as error:
            observe_failure(self._observe, "source_start", failure_reason(error))
            self._failure = True
            self._signal_stop()
            for attempted, done in zip(
                self._thread_attempted, self._thread_done, strict=True
            ):
                if not attempted:
                    self._stage_done(done)
            raise
        finally:
            self._start_done.set()
            self._settle_stages()

    def _run_owned(self, index: int, target: Callable[[], None]) -> None:
        self._thread_entered[index].set()
        try:
            target()
        finally:
            self._thread_exited[index].set()
            self._settle_stages()

    def current(self) -> bool:
        try:
            self._check_transition()
            if self._stop.is_set() or self._ended:
                observe_failure(self._observe, "source_current", "source_ended")
                return False
            allowed = self.executor.current(self.lease_id) and (
                self._registration_current()
            )
            if not allowed:
                observe_failure(self._observe, "source_current", "denied")
            return allowed
        except BaseException as error:
            observe_failure(self._observe, "source_current", failure_reason(error))
            raise

    def _registration_current(self) -> bool:
        if self.frame_source is not None:
            return self.frame_source.current()
        if self._dedicated:
            return (
                isinstance(self.executor, MuxMediaExecutor)
                and self.executor.registration(self.lease_id) == self.registration
            )
        return True

    def alive(self) -> bool:
        """No SQL/native work: stop, revocation and end are permanent."""
        with self._lock:
            return not self._stop.is_set() and not self._ended

    def transport_current(self) -> bool:
        """No SQL/native work: emission permit of a bounded SQL observation."""
        with self._lock:
            return (
                not self._stop.is_set()
                and not self._ended
                and time.monotonic() < self._permit_deadline
            )

    def _check_transition(self) -> None:
        with self._lock:
            deadlines = [
                (value, stage, reason)
                for value, stage, reason in (
                    (
                        self._transition_deadline,
                        "format_transition",
                        "transition_deadline",
                    ),
                    (self._pressure_deadline, "ingress_queue", "wait_timeout"),
                )
                if value is not None
            ]
            expired = min(deadlines) if deadlines else None
        if expired is not None and time.monotonic() >= expired[0]:
            observe_failure(self._observe, expired[1], expired[2])
            self._signal_stop()
            raise MediaDenied()

    def _renew(
        self, frame: PrivateRGBFrame | None = None, *, epoch: int | None = None
    ) -> bool:
        """One authority-gate lease read renews the permit; frame publishes with it.

        The gate (R120) may answer from a SQL check that began up to
        AUTHORITY_FRESHNESS_SECONDS before this call, so the observation is
        anchored that much earlier: the permit never outlives the backing
        check's start plus PERMIT_SECONDS. Latency consumes, rather than
        extends, the window, which is clipped to the actual lease expiry. A
        slow but successful read renews nothing and drops frame: staleness is
        not revocation. Denial raises.
        """
        self._check_transition()
        observed = time.monotonic() - AUTHORITY_FRESHNESS_SECONDS
        lease = self.executor.lease(self.lease_id)
        if not self._registration_current():
            raise MediaDenied()
        self._check_transition()
        now = time.monotonic()
        left = (lease.expires_at - datetime.now(UTC)).total_seconds()
        deadline = min(observed + PERMIT_SECONDS, now + left)
        if now >= deadline:
            return False
        with self._lock:
            if self._stop.is_set():
                return False
            if frame is not None and epoch is not None and epoch != self._format_epoch:
                observe_failure(self._observe, "transition", "late_output_omitted")
                return False
            if (
                self._transition_deadline is not None
                and now >= self._transition_deadline
            ):
                raise MediaDenied()
            # Each candidate is bounded by its own observation and lease
            # expiry; an older round finishing later never shortens a newer.
            self._permit_deadline = max(self._permit_deadline, deadline)
            notify = frame is not None and self._latest is None
            if frame is not None:
                if frame.ordinal <= self._published_ordinal or (
                    self._published_pts is not None
                    and frame.timestamp_us <= self._published_pts
                ):
                    raise MediaDenied()
                self._published_pts, self._published_ordinal = (
                    frame.timestamp_us,
                    frame.ordinal,
                )
                self._clear_latest()
                if self.media_credit is not None:
                    assert self.registration is not None
                    self._latest_credit = self.media_credit.reserve_rgb(
                        self.registration, len(frame.private_rgb())
                    )
                    if self._latest_credit is None:
                        raise MediaDenied()
                if epoch is not None and self._transition_deadline is not None:
                    self._transition_deadline = None
                    observe_failure(self._observe, "transition", "output_verified")
                self._latest = frame
                if self._first_frame_at is None:
                    self._first_frame_at = now
                self.produced_frames += 1
        if notify:
            self._post(self._ready.set)
        return True

    def _publish(self, frame: PrivateRGBFrame, *, epoch: int | None = None) -> None:
        # lease() is the gate-bounded exact authority check; a late one drops it.
        self._renew(frame, epoch=epoch)

    def _post(self, callback: Callable[[], object]) -> None:
        # A closed loop must not skip decoder retirement or stage settlement.
        with suppress(RuntimeError):
            self._loop.call_soon_threadsafe(callback)

    def _clear_latest(self) -> None:
        self._latest = None
        if self._latest_credit is not None:
            assert self.media_credit is not None
            self.media_credit.release(self._latest_credit)
            self._latest_credit = None

    def release_rgb(self, frame: PrivateRGBFrame) -> None:
        """The sender calls this after dropping its exact received RGB owner."""
        if self.media_credit is None:
            return
        with self._lock:
            record = self._received_credit.get(id(frame))
            if record is None or record[0] is not frame:
                raise MediaDenied()
            self.media_credit.release(record[1])
            del self._received_credit[id(frame)]

    def _signal_stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._clear_latest()
            self._permit_deadline = 0
            discarded = tuple(self._encoded)
            self._encoded.clear()
            self._encoded_bytes = 0
            self._condition.notify_all()
        if self.media_credit is not None:
            for picture in discarded:
                if picture.release is not None:
                    picture.release()
        self._post(self._ready.set)

    def _stage_done(self, done: threading.Event) -> None:
        done.set()
        self._settle_stages()

    def _settle_stages(self) -> None:
        if self._stages_settled():
            self._post(self._ready.set)
            self._post(self._settled.set)

    def _stages_settled(self) -> bool:
        return (
            self._start_done.is_set()
            and all(event.is_set() for event in self._thread_done)
            and all(
                not attempted or (entered.is_set() and exited.is_set())
                for attempted, entered, exited in zip(
                    self._thread_attempted,
                    self._thread_entered,
                    self._thread_exited,
                    strict=True,
                )
            )
        )

    def _run_authority(self) -> None:
        try:
            while not self._stop.wait(AUTHORITY_HEARTBEAT_SECONDS):
                self._renew()
        except BaseException as error:  # noqa: BLE001 -- denial or authority failure fences.
            observe_failure(self._observe, "authority_renew", failure_reason(error))
            self._failure = True
        finally:
            self._signal_stop()
            self._stage_done(self._authority_done)

    def _run_ingress(self) -> None:
        stage = "ingress_read"
        frames: tuple[PrivateLiveFrame | MuxValidatedFrame, ...]
        raw: PrivateLiveFrame | MuxValidatedFrame | None
        packet: ElementaryPacket | None
        unqueued: list[PrivateLiveFrame | MuxValidatedFrame]
        release: Callable[[], None] | None
        try:
            while not self._stop.is_set():
                max_frames, max_bytes = self._read_capacity()
                stage = "ingress_read"
                reservation = None
                dedicated_release = None
                if self._dedicated:
                    assert (
                        self.media_credit is not None and self.registration is not None
                    )
                    reservation = self.media_credit.reserve_dedicated(
                        self.registration, frames=max_frames, bytes=max_bytes
                    )
                    if reservation is None:
                        self._wait_for_capacity()
                        continue
                if self.frame_source is not None:
                    frames = self.frame_source.read_frames(
                        max_frames=max_frames,
                        max_bytes=max_bytes,
                        deadline_monotonic=time.monotonic()
                        + INGRESS_READ_DEADLINE_MS / 1000,
                    )
                else:
                    if self._dedicated:
                        if not isinstance(self.executor, MuxMediaExecutor):
                            raise MediaDenied()
                        reader = self.executor.read_dedicated_frames
                    else:
                        reader = self.executor.read_frames
                    try:
                        frames = reader(
                            self.lease_id,
                            max_frames=max_frames,
                            max_bytes=max_bytes,
                            deadline_ms=INGRESS_READ_DEADLINE_MS,
                        )
                    except BaseException:
                        if reservation is not None:
                            assert self.media_credit is not None
                            self.media_credit.release(reservation)
                        raise
                    if reservation is not None:
                        assert self.media_credit is not None
                        if not frames:
                            self.media_credit.release(reservation)
                        else:
                            dedicated_release = self._batch_release(
                                reservation, len(frames)
                            )
                if not frames and max_bytes < 4 * 1024 * 1024:
                    # The parent's next complete frame may exceed remaining
                    # byte credit. Wait for consumer progress instead of polling
                    # its still-retained head repeatedly or draining it early.
                    self._wait_for_capacity(unchanged_bytes=max_bytes)
                unqueued = list(frames)
                try:
                    for raw in frames:
                        stage = "adapter"
                        release = None
                        if self.frame_source is not None:
                            if type(raw) is not MuxValidatedFrame:
                                raise MediaDenied()
                            packet = self.adapter.packet_mux(
                                raw,
                                registration=self.frame_source.registration,
                                cut=self.frame_source.cut,
                            )
                            release = partial(self.frame_source.release_frame, raw)
                        else:
                            if type(raw) is not PrivateLiveFrame:
                                observe_failure(self._observe, stage, "frame_invalid")
                                raise MediaDenied()
                            packet = self.adapter.packet(raw)
                            release = dedicated_release
                        if not self.current():
                            raise MediaDenied()
                        self._queue_packet(
                            packet, self.adapter.random_access, release=release
                        )
                        unqueued.pop(0)
                finally:
                    if self.frame_source is not None:
                        for raw in unqueued:
                            if type(raw) is not MuxValidatedFrame:
                                raise MediaDenied()
                            self.frame_source.release_frame(raw)
                    elif dedicated_release is not None:
                        for _ in unqueued:
                            dedicated_release()
                if frames:
                    with self._condition:
                        self._pressure_deadline = None
                frames, unqueued, raw, packet, release = (), [], None, None, None
        except BaseException as error:  # noqa: BLE001 -- private ingress always fences on failure.
            observe_failure(self._observe, stage, failure_reason(error))
            self._failure = True
        finally:
            self._signal_stop()
            self._stage_done(self._ingress_done)

    def _batch_release(self, credit: MediaCredit, remaining: int) -> Callable[[], None]:
        gate = threading.Lock()

        def release() -> None:
            nonlocal remaining
            with gate:
                if remaining <= 0:
                    raise MediaDenied()
                if remaining == 1:
                    assert self.media_credit is not None
                    self.media_credit.release(credit)
                remaining -= 1

        return release

    def _wait_for_capacity(self, *, unchanged_bytes: int | None = None) -> None:
        if not self.current():
            raise MediaDenied()
        with self._condition:
            if self._stop.is_set():
                raise MediaDenied()
            if (
                unchanged_bytes is not None
                and 4 * 1024 * 1024 - self._encoded_bytes > unchanged_bytes
            ):
                return  # The consumer already released credit during the read.
            if self._pressure_deadline is None:
                self._pressure_deadline = time.monotonic() + QUEUE_WAIT_SECONDS
            self._condition.wait(
                min(0.05, max(0, self._pressure_deadline - time.monotonic()))
            )

    def _read_capacity(self) -> tuple[int, int]:
        # Exactly one ingress producer. A bounded read reserves only currently
        # free credit; the sole consumer can only increase that credit while the
        # read runs. Queued + returned-but-not-yet-queued packets therefore fit
        # the same sixteen-picture/four-MiB limit, without an extra drained batch.
        while True:
            if not self.current():
                raise MediaDenied()
            with self._condition:
                if self._stop.is_set():
                    raise MediaDenied()
                count = 16 - len(self._encoded)
                size = 4 * 1024 * 1024 - self._encoded_bytes
                if not self._encoded:
                    self._pressure_deadline = None
                if count > 0 and size > 0:
                    return count, size
            self._wait_for_capacity()

    def _queue_packet(
        self,
        packet: ElementaryPacket,
        random_access: bool,
        *,
        release: Callable[[], None] | None = None,
    ) -> None:
        with self._condition:
            if self._stop.is_set():
                observe_failure(self._observe, "ingress_queue", "source_ended")
                raise MediaDenied()
            if (
                len(self._encoded) >= 16
                or self._encoded_bytes + len(packet._data) > 4 * 1024 * 1024
            ):
                observe_failure(self._observe, "ingress_queue", "overflow")
                raise MediaDenied()
            shape = (packet.codec, packet.width, packet.height)
            if self._observed_format is not None and shape != self._observed_format:
                self._format_epoch += 1
                if self._transition_deadline is None:
                    self._transition_deadline = time.monotonic() + FORMAT_WAIT_SECONDS
                # A result still returning from the old decoder cannot publish
                # after this boundary. Already queued RGB is obsolete too.
                self._clear_latest()
                observe_failure(
                    self._observe,
                    "transition_format",
                    ",".join(str(value) for value in (*self._observed_format, *shape)),
                )
                observe_failure(self._observe, "transition", "started")
            self._observed_format = shape
            self._encoded.append(
                _QueuedPicture(packet, random_access, self._format_epoch, release)
            )
            self._encoded_bytes += len(packet._data)
            self._condition.notify()

    def _take_packet(self) -> _QueuedPicture | None:
        # Lock-only: decoder authorize and the authority stage hold the SQL gate.
        with self._condition:
            while not self._stop.is_set():
                if self._encoded:
                    packet = self._encoded.popleft()
                    self._encoded_bytes -= len(packet.packet._data)
                    self._condition.notify_all()
                    return packet
                self._condition.wait(0.05)
        return None

    def _run_decoder(self) -> None:
        packet: ElementaryPacket | None
        frame: PrivateRGBFrame | None
        decoder: WindowsDecoder | None = None
        decoder_epoch = 0
        rotations: deque[float] = deque()
        allocated = False
        decoded_seen = False
        stage = "decoder_create"
        try:
            while (picture := self._take_packet()) is not None:
                decode_credit = None
                try:
                    packet = picture.packet
                    if not self.current():
                        raise MediaDenied()
                    if decoder is not None and picture.epoch != decoder_epoch:
                        stage = "decoder_retire"
                        self._retire_decoder(decoder)
                        # Retain the exact owner through actual settlement; stop or
                        # revocation can fence meanwhile, but never replace custody.
                        decoder = None
                        if not self.current():
                            raise MediaDenied()
                    if decoder is None and not picture.random_access:
                        observe_failure(
                            self._observe, "transition", "inter_picture_omitted"
                        )
                        continue
                    if decoder is None:
                        if allocated:
                            now = time.monotonic()
                            while (
                                rotations
                                and now - rotations[0] >= FORMAT_WINDOW_SECONDS
                            ):
                                rotations.popleft()
                            if len(rotations) >= FORMAT_ROTATIONS:
                                observe_failure(
                                    self._observe, "format_transition", "rotation_limit"
                                )
                                raise MediaDenied()
                            rotations.append(now)
                        if not self.current():
                            raise MediaDenied()
                        stage = "decoder_create"
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
                        decoder_epoch = picture.epoch
                        if allocated:
                            observe_failure(
                                self._observe, "transition", "decoder_rotated"
                            )
                        allocated = True
                    stage = "decoder_decode"
                    if not self.current():
                        raise MediaDenied()
                    decode_credit = None
                    if self.media_credit is not None:
                        assert self.registration is not None
                        decode_credit = self.media_credit.reserve_conversion(
                            # Two responses plus _read bytearray/read/result
                            # overlap (including growth slack), before allocation.
                            self.registration,
                            5 * packet.width * packet.height * 3,
                        )
                        if decode_credit is None:
                            raise MediaDenied()
                    for frame in decoder.decode(packet):
                        validate_frame(frame, packet.binding, FrameLimits())
                        if (frame.width, frame.height) != (packet.width, packet.height):
                            raise MediaDenied()
                        if not decoded_seen:
                            decoded_seen = True
                            observe_failure(
                                self._observe, "milestone", "first_decoded_frame"
                            )
                        stage = "publish_authority"
                        self._publish(frame, epoch=decoder_epoch)
                        stage = "decoder_decode"
                except BaseException:
                    # A decode exception can leave the original feed/drain
                    # threads alive. Keep both input and scratch charged until
                    # that exact decoder's cleanup barrier actually settles.
                    self._signal_stop()
                    if decoder is not None:
                        self._retire_decoder(decoder)
                        decoder = None
                    raise
                finally:
                    frame, packet = None, None
                    if decode_credit is not None:
                        assert self.media_credit is not None
                        self.media_credit.release(decode_credit)
                    completion, picture = picture.release, None
                    if completion is not None:
                        completion()
                    completion = None
        except BaseException as error:  # noqa: BLE001 -- decoder failures stay private and fenced.
            observe_failure(self._observe, stage, failure_reason(error))
            self._failure = True
        finally:
            self._signal_stop()
            if decoder is not None:
                self._retire_decoder(decoder)
            self._stage_done(self._decoder_done)

    def _retire_decoder(self, decoder: WindowsDecoder) -> None:
        while True:
            try:
                decoder.close()
                if decoder.wait_closed() is True:
                    return
            except BaseException:  # noqa: BLE001 -- retain exact cleanup owner on interruption.
                self._failure = True
            time.sleep(0.01)

    async def recv(self) -> PrivateRGBFrame:
        """Raises only when stopped/ended; the session enforces the permit."""
        while True:
            with self._lock:
                if self._stop.is_set() or self._ended:
                    raise MediaDenied()
                frame = self._latest
                if frame is not None and self.media_credit is not None:
                    assert self.registration is not None
                    owned = self.media_credit.reserve_conversion(
                        self.registration, len(frame.private_rgb())
                    )
                    if owned is None:
                        raise MediaDenied()
                    self._received_credit[id(frame)] = frame, owned
                self._clear_latest()
                self._ready.clear()
            if frame is not None:
                return frame
            await self._ready.wait()

    async def binding(self) -> DecodeBinding:
        if self._started_at is None:
            raise MediaDenied()
        while self.adapter.binding is None or self.produced_frames == 0:
            if not self.alive():
                raise MediaDenied()
            remaining = self._started_at + FIRST_FRAME_SECONDS - time.monotonic()
            if remaining <= 0:
                observe_failure(self._observe, "binding", "first_frame_deadline")
                self._signal_stop()
                raise MediaNoSignal()
            try:
                await asyncio.wait_for(self._ready.wait(), timeout=remaining)
            except TimeoutError:
                # A concurrent stop/denial keeps its original failure meaning.
                if not self.alive():
                    raise MediaDenied() from None
                if (
                    self._first_frame_at is not None
                    and self._first_frame_at < self._started_at + FIRST_FRAME_SECONDS
                ):
                    break
                observe_failure(self._observe, "binding", "first_frame_deadline")
                self._signal_stop()
                raise MediaNoSignal() from None
            self._ready.clear()
        if not self.alive():
            raise MediaDenied()
        if (
            self._first_frame_at is not None
            and self._first_frame_at >= self._started_at + FIRST_FRAME_SECONDS
        ):
            observe_failure(self._observe, "binding", "first_frame_deadline")
            self._signal_stop()
            raise MediaNoSignal()
        binding = self.adapter.binding
        if binding is None:
            raise MediaDenied()
        observe_failure(self._observe, "milestone", "binding_ready")
        return binding

    async def close(self) -> None:
        observe_failure(self._observe, "source", "explicit_close")
        self._signal_stop()
        for attempted, done in zip(
            self._thread_attempted, self._thread_done, strict=True
        ):
            if not attempted:
                self._stage_done(done)
        if not self._stages_settled():
            await asyncio.shield(self._settled.wait())
        for index, thread in enumerate(self._threads):
            if self._thread_attempted[index] and not self._thread_joined[index]:
                thread.join()
                if thread.is_alive() or not self._thread_exited[index].is_set():
                    raise MediaDenied()
                self._thread_joined[index] = True
        self._ended = all(
            not attempted or joined
            for attempted, joined in zip(
                self._thread_attempted, self._thread_joined, strict=True
            )
        )
        if not self._ended:
            raise MediaDenied()
