"""Closed parent-only first-key records; no native bytes or identities retained."""

from __future__ import annotations

import json
import math
import threading
from collections import deque
from dataclasses import dataclass, fields, replace
from typing import Any, cast

from wso_core.tvt.local_live_mux import UnsupportedMuxPacket

MAX_DIAGNOSTIC_VALUE = (1 << 31) - 1
MAX_DIAGNOSTIC_RECORDS = 128
MAX_DIAGNOSTIC_BYTES = 64 << 10
OUTCOMES = frozenset(
    (
        "waiting",
        "ready",
        "no_signal",
        "denied",
        "cancelled",
        "deadline",
        "closed",
        "protocol",
        "overflow",
        "device_refusal",
        "other",
    )
)
PROGRESS = frozenset(
    (
        "none",
        "prepare",
        "connect",
        "metadata",
        "send",
        "frame",
        "idle",
        "setup",
        "envelope",
    )
)


@dataclass(frozen=True, slots=True)
class NativeMuxIngressFailureRecord:
    cause: str
    wire_command: int | None
    wire_route: int | None


def project_mux_ingress_failure(error: BaseException) -> NativeMuxIngressFailureRecord:
    """Inspect at most four original cause/context nodes without wrapper hooks."""
    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if type(current) is UnsupportedMuxPacket:
            values = cast(Any, BaseException.__dict__["__dict__"]).__get__(current)
            if type(values) is dict:
                command, route = values.get("command"), values.get("route")
                if (
                    type(command) is int
                    and 0 <= command <= 0xFFFFFFFF
                    and type(route) is int
                    and 0 <= route <= 255
                ):
                    return NativeMuxIngressFailureRecord(
                        "unsupported_packet", command, route
                    )
        cause = cast(Any, BaseException.__cause__).__get__(current)
        current = (
            cause
            if cause is not None
            else cast(Any, BaseException.__context__).__get__(current)
        )
    return NativeMuxIngressFailureRecord("unknown", None, None)


def encode_mux_ingress_failure_record(record: NativeMuxIngressFailureRecord) -> bytes:
    if (
        type(record) is not NativeMuxIngressFailureRecord
        or type(record.cause) is not str
    ):
        raise ValueError("Invalid mux ingress failure record.")
    if record.cause == "unsupported_packet":
        valid = (
            type(record.cause) is str
            and type(record.wire_command) is int
            and 0 <= record.wire_command <= 0xFFFFFFFF
            and type(record.wire_route) is int
            and 0 <= record.wire_route <= 255
        )
    else:
        valid = (
            type(record.cause) is str
            and record.cause == "unknown"
            and record.wire_command is None
            and record.wire_route is None
        )
    if not valid:
        raise ValueError("Invalid mux ingress failure record.")
    raw = (
        json.dumps(
            {
                "event": "native_mux_ingress_failure",
                "version": 1,
                "cause": record.cause,
                "wire_command": record.wire_command,
                "wire_route": record.wire_route,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )
    if len(raw) > 1024:
        raise ValueError("Invalid mux ingress failure record.")
    return raw


@dataclass(frozen=True, slots=True)
class NativeMuxTerminalRecord:
    """One private original result's terminal sample, not an atomic FIFO audit."""

    epoch_bound: bool
    failed: bool
    closed: bool
    queued_chunks: int
    queued_bytes: int
    ingress_ordinal: int
    capacity_bytes: int


def validate_mux_terminal_record(record: NativeMuxTerminalRecord) -> None:
    if type(record) is not NativeMuxTerminalRecord or any(
        type(getattr(record, name)) is not bool
        for name in ("epoch_bound", "failed", "closed")
    ):
        raise ValueError("Invalid mux terminal record.")
    for name, maximum in (
        ("queued_chunks", 256),
        ("queued_bytes", 1 << 20),
        ("ingress_ordinal", (1 << 63) - 1),
        ("capacity_bytes", 1 << 20),
    ):
        value = getattr(record, name)
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError("Invalid mux terminal record.")


def encode_mux_terminal_record(record: NativeMuxTerminalRecord) -> bytes:
    validate_mux_terminal_record(record)
    values = {field.name: getattr(record, field.name) for field in fields(record)}
    raw = (
        json.dumps(
            {"event": "native_mux_terminal", "version": 1, **values},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )
    if len(raw) > 1024:
        raise ValueError("Invalid mux terminal record.")
    return raw


@dataclass(frozen=True, slots=True)
class NativeFirstKeyRecord:
    outcome: str
    open_ack: bool
    ack_command: int
    ready: bool
    ack_ms: int | None
    first_frame_ms: int | None
    first_key_ms: int | None
    first_key_late: bool
    parsed_frames: int
    nonkey_frames: int
    key_frames: int
    ipc_messages: int
    ipc_envelopes: int
    ipc_received_bytes: int
    ipc_decisions: int
    ipc_sequence: int
    last_completed: str
    received_bytes: int
    parsed_packets: int
    partial_bytes: int
    assembly_bytes: int
    fragment_pending: bool
    fragment_count: int
    fragment_next: int
    fragment_total_bytes: int
    queued_frames: int
    queued_bytes: int
    authority_check_calls: int
    authority_check_elapsed_max_ms: int
    worker_observed: bool = False


def encode_first_key_record(record: NativeFirstKeyRecord) -> bytes:
    """Accept only the exact closed primitive record, never arbitrary mappings."""
    if type(record) is not NativeFirstKeyRecord:
        raise ValueError("Invalid first-key diagnostic record.")
    values = {field.name: getattr(record, field.name) for field in fields(record)}
    for name, value in values.items():
        if name == "outcome":
            valid = type(value) is str and value in OUTCOMES
        elif name == "last_completed":
            valid = type(value) is str and value in PROGRESS
        elif name in (
            "open_ack",
            "ready",
            "first_key_late",
            "fragment_pending",
            "worker_observed",
        ):
            valid = type(value) is bool and (
                name != "worker_observed" or value is False
            )
        elif name in ("ack_ms", "first_frame_ms", "first_key_ms") and value is None:
            valid = True
        else:
            valid = type(value) is int and 0 <= value <= MAX_DIAGNOSTIC_VALUE
        if not valid or (name == "ack_command" and value not in (0, 1281, 1285)):
            raise ValueError("Invalid first-key diagnostic record.")
    raw = (
        json.dumps(
            {"event": "native_first_key", "version": 1, **values},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )
    if len(raw) > 2048:
        raise ValueError("Invalid first-key diagnostic record.")
    return raw


class NativeFirstKeySink:
    """Bounded byte queue with short locks; runtime owns file I/O after drain."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: deque[bytes] = deque()
        self._bytes = self._dropped = 0

    def __call__(
        self,
        record: NativeFirstKeyRecord
        | NativeMuxTerminalRecord
        | NativeMuxIngressFailureRecord,
    ) -> None:
        if type(record) is NativeMuxIngressFailureRecord:
            raw = encode_mux_ingress_failure_record(record)
        elif type(record) is NativeMuxTerminalRecord:
            raw = encode_mux_terminal_record(record)
        elif type(record) is NativeFirstKeyRecord:
            raw = encode_first_key_record(record)
        else:
            raise ValueError("Invalid diagnostic record.")
        with self._lock:
            if (
                len(self._records) >= MAX_DIAGNOSTIC_RECORDS
                or self._bytes + len(raw) > MAX_DIAGNOSTIC_BYTES
            ):
                self._dropped = min(MAX_DIAGNOSTIC_VALUE, self._dropped + 1)
                return
            self._records.append(raw)
            self._bytes += len(raw)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def drain(self) -> tuple[bytes, ...]:
        with self._lock:
            result = tuple(self._records)
            self._records.clear()
            self._bytes = 0
            return result


def _bounded(value: int) -> int:
    return min(MAX_DIAGNOSTIC_VALUE, max(0, value))


class _FirstKeyDiagnostics:
    """One original's numeric state. Never stores an authority, codec or callback."""

    def __init__(self, started: float) -> None:
        self._lock = threading.RLock()
        self._started = started
        self._record: NativeFirstKeyRecord | None = None
        self.ack_command = 0
        self.ack_ms: int | None = None
        self.first_frame_ms: int | None = None
        self.first_key_ms: int | None = None
        self.first_key_late = False
        self.parsed_frames = self.nonkey_frames = self.key_frames = 0
        self.ipc_messages = self.ipc_envelopes = self.ipc_received_bytes = 0
        self.ipc_decisions = self.authority_check_calls = 0
        self.authority_check_elapsed_max_ms = 0
        self.last_completed = "none"

    def _ms(self, now: float) -> int:
        if not math.isfinite(now) or not math.isfinite(self._started):
            raise ValueError("Invalid diagnostic clock.")
        return _bounded(round((now - self._started) * 1000))

    def received(self, size: int, envelope: bool) -> None:
        with self._lock:
            self.ipc_messages = _bounded(self.ipc_messages + 1)
            self.ipc_envelopes = _bounded(self.ipc_envelopes + int(envelope))
            self.ipc_received_bytes = _bounded(self.ipc_received_bytes + size)

    def completed(self, purpose: str) -> None:
        with self._lock:
            self.ipc_decisions = _bounded(self.ipc_decisions + 1)
            self.last_completed = purpose if purpose in PROGRESS else "none"

    def acknowledged(self, command: int, now: float) -> None:
        with self._lock:
            if command in (1281, 1285) and self.ack_ms is None:
                self.ack_ms, self.ack_command = self._ms(now), command

    def frame(self, key: bool, now: float, late: bool) -> None:
        with self._lock:
            self.parsed_frames = _bounded(self.parsed_frames + 1)
            if self.first_frame_ms is None:
                self.first_frame_ms = self._ms(now)
            if key:
                self.key_frames = _bounded(self.key_frames + 1)
                if self.first_key_ms is None:
                    self.first_key_ms, self.first_key_late = self._ms(now), late
            else:
                self.nonkey_frames = _bounded(self.nonkey_frames + 1)

    def checked(self, start: float | None, end: float | None) -> None:
        with self._lock:
            self.authority_check_calls = _bounded(self.authority_check_calls + 1)
            if (
                start is not None
                and end is not None
                and math.isfinite(start)
                and math.isfinite(end)
            ):
                self.authority_check_elapsed_max_ms = max(
                    self.authority_check_elapsed_max_ms,
                    _bounded(round((end - start) * 1000)),
                )
            if self._record is not None:
                # Completion of the existing check can follow its terminal deny.
                # Amend only numeric timing; never inspect cleared codec state.
                self._record = replace(
                    self._record,
                    authority_check_calls=self.authority_check_calls,
                    authority_check_elapsed_max_ms=self.authority_check_elapsed_max_ms,
                )

    def snapshot(self, authority: Any, outcome: str) -> NativeFirstKeyRecord:
        with self._lock:
            if self._record is not None:
                return self._record
            codec = authority.codec
            fragment = None if codec is None else codec._fragment
            self._record = NativeFirstKeyRecord(
                outcome=outcome
                if outcome in OUTCOMES
                else "device_refusal"
                if outcome.startswith("device_")
                else "other",
                open_ack=authority.open_ack,
                ack_command=self.ack_command,
                ready=authority.ready,
                ack_ms=self.ack_ms,
                first_frame_ms=self.first_frame_ms,
                first_key_ms=self.first_key_ms,
                first_key_late=self.first_key_late,
                parsed_frames=self.parsed_frames,
                nonkey_frames=self.nonkey_frames,
                key_frames=self.key_frames,
                ipc_messages=self.ipc_messages,
                ipc_envelopes=self.ipc_envelopes,
                ipc_received_bytes=self.ipc_received_bytes,
                ipc_decisions=self.ipc_decisions,
                ipc_sequence=_bounded(authority._live_sequence),
                last_completed=self.last_completed,
                received_bytes=0 if codec is None else _bounded(codec._received),
                parsed_packets=0 if codec is None else _bounded(codec._packets),
                partial_bytes=0 if codec is None else _bounded(len(codec._buffer)),
                assembly_bytes=0 if codec is None else _bounded(len(codec._assembly)),
                fragment_pending=fragment is not None,
                fragment_count=0 if fragment is None else _bounded(fragment[1]),
                fragment_next=0 if fragment is None else _bounded(fragment[3]),
                fragment_total_bytes=0 if fragment is None else _bounded(fragment[2]),
                queued_frames=_bounded(len(authority.frames)),
                queued_bytes=_bounded(authority.queued_bytes),
                authority_check_calls=self.authority_check_calls,
                authority_check_elapsed_max_ms=self.authority_check_elapsed_max_ms,
            )
            return self._record
