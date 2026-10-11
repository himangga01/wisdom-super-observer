"""Bounded private live IPC. SQL authority runs only on the caller thread.

One message in flight is acknowledged before the worker dequeues another native
chunk. Neither a background thread nor the native callback invokes SQL.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from wso_core.tvt.local_live import (
    LiveAcknowledgement,
    LiveCodec,
    LiveIdentity,
    LiveRefused,
    PrivateLiveFrame,
)

from .local_inventory_ipc import (
    AuthorityError,
    ParentAuthority,
    RemoteAuthority,
    decode,
    encode,
)
from .local_live_diagnostics import NativeFirstKeyRecord, _FirstKeyDiagnostics

MAX_ENVELOPE = 1 << 20
MAX_QUEUE_BYTES = 4 << 20
MAX_QUEUE_FRAMES = 16
MAX_MEDIA_TTL = 30.0
# Keep this IPC module importable by the isolated stdlib-only native child.
# The media facade uses the same bound from core local_service.
FIRST_FRAME_SECONDS = 10.0
LIVE_PURPOSES = frozenset(("prepare", "connect", "metadata", "send", "frame", "idle"))


def frame_storage(frame: PrivateLiveFrame) -> int:
    # Account for every retained source byte value as well as the payload.
    # This deliberately overcounts shared bytes; object overhead is separately
    # bounded by the 16-frame quota.
    return len(frame.private_bytes()) + sum(
        len(value.private_bytes())
        for value in (
            frame.source_extension,
            frame.source_envelope,
            frame.source_header,
            frame.source_outer_headers,
            frame.source_padding,
        )
    )


class LiveRemoteAuthority(RemoteAuthority):
    def exchange(self, message: dict[str, Any] | bytes, purpose: str) -> None:
        try:
            self._time()
            if purpose not in LIVE_PURPOSES:
                raise AuthorityError()
            self.sequence += 1
            if isinstance(message, dict):
                message.update(generation=self.generation, sequence=self.sequence)
                raw = b"J" + encode(message)
            else:
                if not 8 <= len(message) <= MAX_ENVELOPE:
                    raise AuthorityError()
                raw = b"E" + message
            self.connection.send_bytes(raw)
            if not self.connection.poll(max(0, self.deadline - time.monotonic())):
                raise AuthorityError()
            answer = decode(self.connection.recv_bytes(65536))
            if (
                set(answer) != {"type", "generation", "sequence", "allow", "deadline"}
                or answer["type"] != "decision"
                or answer["generation"] != self.generation
                or type(answer["sequence"]) is not int
                or answer["sequence"] != self.sequence
                or answer["allow"] is not True
                or type(answer["deadline"]) not in (int, float)
                or not math.isfinite(answer["deadline"])
                or not 0 < answer["deadline"] - time.monotonic() <= MAX_MEDIA_TTL
            ):
                raise AuthorityError()
            self.deadline = answer["deadline"]
            self._time()
        except Exception:  # noqa: BLE001 -- fixed private IPC boundary
            self.close()
            raise AuthorityError() from None

    def require(self, purpose: str) -> None:
        self.exchange({"type": "current", "purpose": purpose}, purpose)

    def setup(self, data: dict[str, Any]) -> None:
        self.exchange({"type": "setup", "data": data}, "send")

    def envelope(self, raw: bytes) -> None:
        self.exchange(raw, "frame")


class LiveParentAuthority(ParentAuthority):
    def __init__(
        self,
        deadline: float,
        cancel: Any,
        selection: Any = None,
        *,
        diagnostics: bool = False,
    ) -> None:
        super().__init__(deadline, cancel)
        self.selection = selection
        self.codec: LiveCodec | None = None
        self.identity: LiveIdentity | None = None
        self.frames: deque[PrivateLiveFrame] = deque()
        self.queued_bytes = 0
        self.open_ack = False
        self._first_frame_deadline: float | None = None
        self._sub_stream_adaptation_off = False
        self.setup_data: dict[str, Any] | None = None
        self.ready = False
        self.handed_off = False
        self._authorized = False
        self._live_sequence = 1
        self._retirement: threading.Thread | None = None
        self._transition_lock = threading.RLock()
        self._diagnostics: _FirstKeyDiagnostics | None = None
        if diagnostics is True:
            try:
                self._diagnostics = _FirstKeyDiagnostics(time.monotonic())
            except BaseException:  # noqa: BLE001,S110 -- diagnostics cannot alter authority
                pass

    def _diagnostic_note(self, method: str, *values: Any) -> None:
        if self._diagnostics is not None:
            try:
                getattr(self._diagnostics, method)(*values)
            except BaseException:  # noqa: BLE001,S110 -- fixed observation only
                pass

    def first_key_snapshot(self) -> NativeFirstKeyRecord | None:
        if self._diagnostics is not None:
            try:
                with self._transition_lock:
                    return self._diagnostics.snapshot(
                        self, self.failure or ("ready" if self.ready else "waiting")
                    )
            except BaseException:  # noqa: BLE001,S110 -- no private exception retained
                pass
        return None

    def check(self, current: Callable[[], bool]) -> bool:
        if self._diagnostics is None:
            return super().check(current)
        start = end = None
        try:
            start = time.monotonic()
        except BaseException:  # noqa: BLE001,S110 -- original check still runs once
            pass
        try:
            return super().check(current)
        finally:
            try:
                end = time.monotonic()
            except BaseException:  # noqa: BLE001,S110 -- preserve original result/exception
                pass
            self._diagnostic_note("checked", start, end)

    @property
    def sub_stream_adaptation_off(self) -> bool:
        return self._sub_stream_adaptation_off

    def start_watchdog(self, stop_original: Callable[[], None]) -> None:
        super().start_watchdog(stop_original)
        # Preserve the original owner in a reaper with no SQL/credential
        # closure. It waits for the watchdog to exit before joining/closing it.
        owner = getattr(stop_original, "__self__", None)
        if owner is None:
            raise AuthorityError()

        def retire() -> None:
            self._stop.wait()
            watchdog = self._watchdog
            if watchdog is not None:
                watchdog.join()
            if owner.finish():
                from .windows_socket import remove_confirmed_owner

                remove_confirmed_owner(owner)

        self._retirement = threading.Thread(
            target=retire, daemon=False, name="local-live-original-retirement"
        )
        self._retirement.start()

    def wait_retirement(self, timeout: float = 1) -> bool:
        if self._retirement is not None:
            self._retirement.join(timeout)
            if self._retirement.is_alive():
                return False
            self._retirement = None
        return True

    def renew(self, deadline: float, current: Callable[[], bool]) -> bool:
        # Check the old expiry first; an expired or denied generation is terminal.
        with self._transition_lock:
            old_deadline = self.deadline
        if not self.check(current):
            return False
        if (
            type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or not 0 < deadline - time.monotonic() <= MAX_MEDIA_TTL
        ):
            return self.deny("protocol")
        if not self._replace_deadline(deadline, old_deadline):
            return False
        if not self.check(current):
            return False
        with self._transition_lock:
            return not self.failure and not self._stop.is_set()

    def _replace_deadline(self, deadline: float, old_deadline: float) -> bool:
        # No SQL callback runs under this lock: watchdog cancellation/expiry
        # remains independent of a blocked supplier. The final old-expiry test
        # and assignment serialize with its permanent deny latch.
        with self._transition_lock:
            if self.failure or self._stop.is_set():
                return False
            if self.cancel.is_set():
                return self.deny("cancelled")
            if time.monotonic() >= min(old_deadline, self.deadline):
                return self.deny("deadline")
            self.deadline = deadline
            return True

    def deny(self, reason: str) -> bool:
        with self._transition_lock:
            if self._diagnostics is not None:
                try:
                    self._diagnostics.snapshot(self, self.failure or reason)
                except BaseException:  # noqa: BLE001,S110 -- snapshot precedes state clear
                    pass
            self.ready = self._authorized = False
            self.frames.clear()
            self.queued_bytes = 0
            if self.codec is not None:
                self.codec.close()
            return super().deny(reason)

    def _setup(self, data: Any) -> None:
        if (
            self.setup_data is not None
            or type(data) is not dict
            or self.selection is None
        ):
            raise AuthorityError()
        if set(data) != {
            "session",
            "channel",
            "task",
            "open_request",
            "peer_version",
            "callback_generation",
            "raw_index",
            "window_index",
            "ordinal",
            "stream",
            "live_basis",
            "login_accepted",
            "serial_matched",
        }:
            raise AuthorityError()
        selection = self.selection
        if (
            selection.stream not in ("main", "sub")
            or type(data["stream"]) is not int
            or data["stream"] != (2 if selection.stream == "sub" else 1)
            or data["channel"] != selection.channel_guid.hex()
            or data["raw_index"] != selection.raw_index
            or type(data["raw_index"]) is not int
            or data["window_index"] != selection.window_index
            or type(data["window_index"]) is not int
            or data["ordinal"] != selection.ordinal
            or type(data["ordinal"]) is not int
            or data["login_accepted"] is not True
            or data["serial_matched"] is not True
            or data["live_basis"] not in ("legacy_no_group", "explicit_lp")
        ):
            raise AuthorityError()
        guids = []
        for key in ("session", "channel", "task", "open_request"):
            value = data[key]
            if type(value) is not str or len(value) != 32:
                raise AuthorityError()
            guid = bytes.fromhex(value)
            if guid.hex() != value or guid == bytes(16):
                raise AuthorityError()
            guids.append(guid)
        expected_generation = int(self.generation[:15], 16) + 1
        if (
            type(data["callback_generation"]) is not int
            or data["callback_generation"] != expected_generation
        ):
            raise AuthorityError()
        self.identity = LiveIdentity(
            generation=expected_generation,
            session=guids[0],
            channel=guids[1],
            task=guids[2],
        )
        identity = self.identity
        self.codec = LiveCodec(
            identity=identity,
            peer_capability=data["peer_version"],
            channel_number=selection.raw_index & 255,
            stream=data["stream"],
            exclusive_first_task=True,
            authorize=lambda given: (
                self._authorized and given is identity and not self.failure
            ),
            max_packet=MAX_ENVELOPE,
            max_session_bytes=1 << 40,
            max_packets=1 << 20,
            max_fragments=64,
        )
        self.codec.open(request_guid=guids[3], sequence=6)
        self.setup_data = data

    def pump(self, current: Callable[[], bool]) -> bool:
        if self.failure:
            return False
        try:
            if self._stop.is_set():
                return self.deny("closed")
            if not self.check(current):
                return False
            # One outstanding IPC envelope is ACKed only after validation. A
            # retained frame consumes receive credit; leave the next original
            # message/sequence untouched until the consumer drains the FIFO.
            # Conservative empty-FIFO credit also covers an unknown next size
            # or multiple parsed pictures without increasing any byte bound.
            with self._transition_lock:
                if self.failure or self._stop.is_set():
                    return False
                if self.frames:
                    return True
            if self.connection is None or not self.connection.poll(0):
                return True
            raw = self.connection.recv_bytes(MAX_ENVELOPE + 1)
            self._diagnostic_note("received", len(raw), raw[:1] == b"E")
            if not self.check(current):
                return False
            self._authorized = True
            if raw[:1] == b"J":
                message = decode(raw[1:])
                if (
                    message.get("generation") != self.generation
                    or type(message.get("sequence")) is not int
                    or message["sequence"] != self._live_sequence
                ):
                    raise AuthorityError()
                if message.get("type") == "current":
                    if (
                        set(message) != {"type", "purpose", "generation", "sequence"}
                        or message["purpose"] not in LIVE_PURPOSES
                    ):
                        raise AuthorityError()
                    diagnostic_purpose = message["purpose"]
                elif message.get("type") == "setup":
                    if set(message) != {"type", "data", "generation", "sequence"}:
                        raise AuthorityError()
                    self._setup(message["data"])
                    diagnostic_purpose = "setup"
                else:
                    raise AuthorityError()
            elif raw[:1] == b"E":
                diagnostic_purpose = "envelope"
                if self.codec is None or self.identity is None:
                    raise AuthorityError()
                was_ready = self.ready
                for item in self.codec.feed(
                    raw[1:], generation=self.identity.generation
                ):
                    if type(item) is LiveAcknowledgement:
                        self.open_ack = item.command in (1281, 1285)
                        if self.open_ack and self._first_frame_deadline is None:
                            self._first_frame_deadline = (
                                time.monotonic() + FIRST_FRAME_SECONDS
                            )
                        if self.open_ack and self._first_frame_deadline is not None:
                            self._diagnostic_note(
                                "acknowledged",
                                item.command,
                                self._first_frame_deadline - FIRST_FRAME_SECONDS,
                            )
                        if item.warning == "SUB_STREAM_ADAPTATION_OFF":
                            self._sub_stream_adaptation_off = True
                    elif type(item) is PrivateLiveFrame:
                        if self._diagnostics is not None:
                            try:
                                observed = time.monotonic()
                                self._diagnostic_note(
                                    "frame",
                                    item.key_frame,
                                    observed,
                                    self._first_frame_deadline is not None
                                    and observed >= self._first_frame_deadline,
                                )
                            except BaseException:  # noqa: BLE001,S110 -- original frame path
                                pass
                        if not self.open_ack:
                            raise AuthorityError()
                        if not self._first_frame_current(current):
                            return False
                        if not self.ready and not item.key_frame:
                            continue
                        summary = item.summary()
                        payload = item.private_bytes()
                        storage = frame_storage(item)
                        if (
                            summary.codec not in ("h264", "h265")
                            or item.device_timestamp.unix_microseconds is None
                            or not payload.startswith((b"\0\0\0\1", b"\0\0\1"))
                        ):
                            raise AuthorityError()
                        if (
                            len(self.frames) >= MAX_QUEUE_FRAMES
                            or self.queued_bytes + storage > MAX_QUEUE_BYTES
                        ):
                            return self.deny("overflow")
                        self.frames.append(item)
                        self.queued_bytes += storage
                        self.ready = True
                    else:
                        raise AuthorityError()
            else:
                raise AuthorityError()
            if not self.check(current):
                return False
            if raw[:1] == b"E" and not was_ready and self.ready:
                # Credentials were dropped before setup. The short startup
                # SQL callback is still checked above, but the child now gets
                # an independent 30s orphan bound in its exact frame ACK.
                old_deadline = self.deadline
                if not self._replace_deadline(
                    time.monotonic() + MAX_MEDIA_TTL, old_deadline
                ):
                    return False
            self.connection.send_bytes(
                encode(
                    {
                        "type": "decision",
                        "generation": self.generation,
                        "sequence": self._live_sequence,
                        "allow": True,
                        "deadline": self.deadline,
                    }
                )
            )
            self._live_sequence += 1
            self._diagnostic_note("completed", diagnostic_purpose)
            return True
        except LiveRefused as refusal:
            return self.deny("device_" + refusal.reason)
        except Exception:  # noqa: BLE001 -- fixed private IPC boundary
            return self.deny("protocol")
        finally:
            self._authorized = False

    def _first_frame_current(self, current: Callable[[], bool]) -> bool:
        if (
            not self.ready
            and self._first_frame_deadline is not None
            and time.monotonic() >= self._first_frame_deadline
        ):
            # Preserve caller cancellation/deadline and fresh authority denial.
            if not self.check(current):
                return False
            return self.deny("no_signal")
        return not self.failure

    def tick(self, current: Callable[[], bool]) -> bool:
        # Process an independently parsed refusal before the no-media outcome.
        return super().tick(current) and self._first_frame_current(current)

    def close(self, timeout: float = 1) -> bool:
        self.deny("closed")
        return super().close(timeout)
