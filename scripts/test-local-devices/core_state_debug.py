"""Optional retained-instance close-origin records; authority is never queried."""

from __future__ import annotations

import json
import os
import sys
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock, Thread
from types import FrameType, MethodType
from typing import Any, cast
from uuid import UUID

from wso_core.tvt.local_live_mux import UnsupportedMuxPacket
from wso_core.tvt.local_media_admission import LocalMediaLease
from wso_core.tvt.local_media_mux_admission import SqlMuxAdmission, _Record
from wso_core.tvt.local_media_mux_service import (
    DedicatedRecord,
    DeviceEpochCoordinator,
    EpochState,
    MuxMediaExecutor,
    OriginalConstructorRecord,
    SlotRecord,
    ViewerRecord,
)
from wso_core.tvt.local_media_mux_types import (
    SlotRetentionGrant,
    TransportGrant,
    ViewerGrant,
)
from wso_core.tvt.local_service import LOCAL_DEVICE_FAILURES, LocalDeviceFailure
from wso_tvt_bridge.local_live_diagnostics import NativeFirstKeySink

SOURCES = {
    "mux_service": "packages/core/src/wso_core/tvt/local_media_mux_service.py",
    "mux_admission": "packages/core/src/wso_core/tvt/local_media_mux_admission.py",
    "mux_provider": "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py",
    "media_worker": "services/tvt-media/src/wso_tvt_media/worker.py",
    "mux_source": "services/tvt-media/src/wso_tvt_media/mux_source.py",
    "native_source": "services/tvt-media/src/wso_tvt_media/native_source.py",
    "mux_ipc": "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ipc.py",
    "local_admission": "packages/core/src/wso_core/tvt/local_admission.py",
    "mux_codec": "packages/core/src/wso_core/tvt/local_live_mux.py",
    "live_codec": "packages/core/src/wso_core/tvt/local_live.py",
}
HEARTBEAT_FUNCTIONS = {
    "mux_service": frozenset({"heartbeat", "_check_replacement"}),
    "mux_admission": frozenset(
        {"refresh_grant", "_refresh_current_grant", "_record", "_observe", "_sql"}
    ),
    "mux_provider": frozenset(
        {"refresh_grants", "authority_operation", "replace_grant", "heartbeat"}
    ),
    "mux_ipc": frozenset({"renew", "_rpc", "_check", "heartbeat"}),
    "local_admission": frozenset({"checked"}),
}
READ_FUNCTIONS = {
    "mux_service": frozenset({"read_mux_frames", "_read_limits", "current", "_lease"}),
    "mux_provider": frozenset(
        {
            "read_frames",
            "current",
            "_current_once",
            "_matches",
            "_serialized_io",
            "authority_operation",
            "heartbeat",
            "fail",
        }
    ),
    "mux_ipc": frozenset(
        {"pump", "read_frames", "_check", "_rpc", "_fail", "_accept", "_operation"}
    ),
    "mux_codec": frozenset(
        {
            "feed",
            "drain",
            "_feed",
            "_check",
            "_slot",
            "_authority",
            "_deliver",
            "_preflight",
            "_parse",
            "_media",
            "_move_fragment",
            "_peek_span",
            "_consume_span",
            "_count",
            "accept",
        }
    ),
    "live_codec": frozenset({"_integer", "_guid", "_raw_timestamp"}),
}
FUNCTIONS = {
    "mux_service": frozenset(
        {
            "current",
            "_current_once",
            "_current_dedicated",
            "_current_dedicated_once",
            "_close_dedicated",
            "_original_current",
            "_pending_current",
            "_fence",
            "_close_viewer",
            "_retire_master",
            "_retire_if_unused",
            "attach",
            "attach_dedicated",
            "detach",
            "sweep",
            "heartbeat",
            "shutdown",
            "stop_wall",
            "start",
            "close",
            "_lease",
            "mux_binding",
            "_mux_binding_once",
            "monitor",
            "retain_focus",
            "settle_focus",
            "lease",
            "renew_stream",
        }
    ),
    "mux_admission": frozenset(
        {"current_transport", "current_slot", "current_viewer", "_current"}
    ),
    "mux_provider": frozenset(
        {
            "current",
            "_original_current",
            "read_frames",
            "_next",
            "_read",
            "start",
            "close",
            "renew_stream",
        }
    ),
    "media_worker": frozenset(
        {
            "start",
            "_start",
            "_prepare",
            "_watch",
            "_close_entry",
            "_stop",
            "stop",
            "shutdown",
            "offer",
            "_offer",
        }
    ),
    "mux_source": frozenset({"current", "_current", "read", "_read", "binding"}),
    "native_source": frozenset({"current", "_current", "_produce", "_renew"}),
}
FUNCTIONS["mux_admission"] = FUNCTIONS.get("mux_admission", frozenset()) | {
    "current_main_retention"
}
EVENTS = frozenset(
    {
        "COORDINATOR_CURRENT",
        "MASTER_FENCE",
        "VIEWER_CLOSE",
        "GRANT_CURRENT",
        "HEARTBEAT_EXCEPTION",
        "VIEWER_READ_EXCEPTION",
        "GRANT_REFRESH_EXCEPTION",
        "DEDICATED_CURRENT",
        "MAIN_RETENTION_CURRENT",
        "DEDICATED_CLOSE",
        "SUMMARY",
    }
)
BOOLS = frozenset(
    {
        "snapshot_atomic",
        "starting",
        "stopping",
        "closing",
        "refreshing",
        "registered",
        "denied",
        "closed",
        "holder_replaced",
        "expired",
        "refreshing_at_entry",
        "refresh_changed",
    }
)
FIELDS = frozenset(
    {
        "schema_version",
        "event",
        "purpose",
        "result",
        "exception",
        "sequence",
        "hook_sequence",
        "elapsed_ms",
        "frames",
        "truncated",
        "state",
        "accepted",
        "written",
        "omitted",
        "diagnostic_failures",
        "suppressed",
    }
)
COUNTERS = ("accepted", "written", "omitted", "diagnostic_failures", "suppressed")
LIMIT = (1 << 31) - 1
FAILURE_FIELDS = frozenset({"code", "status", "chain_count"})
WIRE_FIELDS = frozenset({"wire_command", "wire_route"})


def checked_record(value: object) -> bytes:
    if type(value) is not dict:
        raise ValueError("invalid core state diagnostic")
    failure_event = value.get("event") in {
        "HEARTBEAT_EXCEPTION",
        "VIEWER_READ_EXCEPTION",
        "GRANT_REFRESH_EXCEPTION",
    }
    wire_fields = set(value) & WIRE_FIELDS
    if wire_fields and (
        wire_fields != WIRE_FIELDS
        or value.get("event") != "VIEWER_READ_EXCEPTION"
        or type(value["wire_command"]) is not int
        or not 0 <= value["wire_command"] <= 0xFFFFFFFF
        or type(value["wire_route"]) is not int
        or not 0 <= value["wire_route"] <= 255
    ):
        raise ValueError("invalid typed mux packet facts")
    if set(value) != (
        (FIELDS | FAILURE_FIELDS if failure_event else FIELDS) | wire_fields
    ):
        raise ValueError("invalid core state diagnostic")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["event"]) is not str
        or value["event"] not in EVENTS
        or type(value["purpose"]) is not str
        or value["purpose"] not in {"NONE", "TRANSPORT", "SLOT_RETENTION", "VIEWER"}
        or type(value["result"]) is not str
        or value["result"] not in {"FALSE", "EXCEPTION", "ENTRY", "FINAL"}
        or type(value["exception"]) is not str
        or value["exception"] not in {"none", "LocalDeviceFailure", "unexpected"}
        or type(value["sequence"]) is not int
        or not 1 <= value["sequence"] <= 128
        or type(value["hook_sequence"]) is not int
        or not 1 <= value["hook_sequence"] <= 128
        or type(value["elapsed_ms"]) is not int
        or not 0 <= value["elapsed_ms"] <= 7200000
        or type(value["truncated"]) is not bool
        or type(value["frames"]) is not list
        or len(value["frames"]) > 8
        or type(value["state"]) is not dict
        or set(value["state"]) - (BOOLS | {"master_state"})
        or any(
            type(value[key]) is not int or not 0 <= value[key] <= LIMIT
            for key in COUNTERS
        )
    ):
        raise ValueError("invalid core state diagnostic")
    if (value["event"] in {"GRANT_CURRENT", "GRANT_REFRESH_EXCEPTION"}) != (
        value["purpose"] != "NONE"
    ):
        raise ValueError("invalid core state purpose")
    allowed_result = (
        {"FINAL"}
        if value["event"] == "SUMMARY"
        else {"EXCEPTION"}
        if failure_event
        else {"ENTRY"}
        if value["event"] in {"MASTER_FENCE", "VIEWER_CLOSE", "DEDICATED_CLOSE"}
        else {"FALSE", "EXCEPTION"}
    )
    if value["result"] not in allowed_result or (
        (value["exception"] != "none") != (value["result"] == "EXCEPTION")
    ):
        raise ValueError("invalid core state result")
    if failure_event and (
        type(value["code"]) is not str
        or type(value["status"]) is not int
        or type(value["chain_count"]) is not int
        or not 1 <= value["chain_count"] <= 4
        or (
            (value["code"], value["status"]) not in LOCAL_DEVICE_FAILURES.items()
            if value["exception"] == "LocalDeviceFailure"
            else (value["code"], value["status"]) != ("UNEXPECTED", 500)
        )
    ):
        raise ValueError("invalid inner failure")
    for key, item in value["state"].items():
        if key in BOOLS and type(item) is not bool:
            raise ValueError("invalid primitive state")
        if key == "master_state" and (
            type(item) is not str
            or item not in {"STARTING", "ACTIVE", "STOPPING", "QUARANTINED", "CLOSED"}
        ):
            raise ValueError("invalid master state")
    for frame in value["frames"]:
        functions = (
            HEARTBEAT_FUNCTIONS
            if value["event"] in {"HEARTBEAT_EXCEPTION", "GRANT_REFRESH_EXCEPTION"}
            else READ_FUNCTIONS
            if value["event"] == "VIEWER_READ_EXCEPTION"
            else FUNCTIONS
        )
        if (
            type(frame) is not dict
            or set(frame)
            != (
                {"module", "function", "line", "chain"}
                if failure_event
                else {"module", "function", "line"}
            )
            or type(frame["module"]) is not str
            or frame["module"] not in functions
            or type(frame["function"]) is not str
            or frame["function"] not in functions[frame["module"]]
            or type(frame["line"]) is not int
            or not 1 <= frame["line"] <= 20000
            or failure_event
            and (
                type(frame["chain"]) is not int
                or not 0 <= frame["chain"] < value["chain_count"]
            )
        ):
            raise ValueError("invalid closed callsite")
    raw = (json.dumps(value, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
        "ascii"
    )
    if len(raw) > 2048:
        raise ValueError("core state diagnostic too large")
    return raw


def project_heartbeat_failure(error: BaseException, *, root: Path) -> dict[str, Any]:
    return _project_failure(error, root=root, functions=HEARTBEAT_FUNCTIONS)[0]


def project_read_failure(
    error: BaseException, *, root: Path, reader: FrameType | None = None
) -> tuple[dict[str, Any], bool]:
    return _project_failure(
        error,
        root=root,
        functions=READ_FUNCTIONS,
        reader=reader,
        inspection_limit=32,
        deepest=True,
        wire_facts=True,
    )


def _project_failure(
    error: BaseException,
    *,
    root: Path,
    functions: dict[str, frozenset[str]],
    reader: FrameType | None = None,
    inspection_limit: int = 8,
    deepest: bool = False,
    wire_facts: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Finite primitive projection; no exceptions or frames escape this function."""
    paths = {
        os.path.normcase(os.path.abspath(root / SOURCES[label])): label
        for label in functions
    }
    frames: list[dict[str, Any]] = []
    seen: set[int] = set()
    current: BaseException | None = error
    count = inspected = 0
    truncated = False
    initiating = False
    wire: dict[str, int] = {}
    trace = None
    try:
        while current is not None and count < 4:
            if id(current) in seen:
                truncated = True
                break
            seen.add(id(current))
            if wire_facts and not wire and type(current) is UnsupportedMuxPacket:
                command, route = (
                    getattr(current, "command", None),
                    getattr(current, "route", None),
                )
                if (
                    type(command) is int
                    and 0 <= command <= 0xFFFFFFFF
                    and type(route) is int
                    and 0 <= route <= 255
                ):
                    wire = {"wire_command": command, "wire_route": route}
            # Typeshed describes instance attributes; class lookup returns the
            # original native descriptor, bypassing subclass attribute hooks.
            trace = cast(Any, BaseException.__traceback__).__get__(current)
            while trace is not None and inspected < inspection_limit:
                inspected += 1  # Unknown frames consume the same total budget.
                code = trace.tb_frame.f_code
                if (
                    count == 0
                    and reader is not None
                    and trace.tb_frame is reader
                    and code is MuxMediaExecutor.read_mux_frames.__code__
                ):
                    initiating = True
                label = paths.get(os.path.normcase(os.path.abspath(code.co_filename)))
                if (
                    label is not None
                    and code.co_name in functions[label]
                    and 1 <= trace.tb_lineno <= 20000
                ):
                    if deepest and len(frames) == 8:
                        # Keep the deepest tail of this finite traversal across
                        # chains; reduction remains explicitly observable.
                        frames.pop(0)
                        truncated = True
                    frames.append(
                        {
                            "module": label,
                            "function": code.co_name,
                            "line": trace.tb_lineno,
                            "chain": count,
                        }
                    )
                trace = trace.tb_next
            truncated = truncated or trace is not None
            count += 1
            cause = cast(Any, BaseException.__cause__).__get__(current)
            current = (
                cause
                if cause is not None
                else cast(Any, BaseException.__context__).__get__(current)
            )
        truncated = truncated or current is not None
        public_code, status, exception = "UNEXPECTED", 500, "unexpected"
        if type(error) is LocalDeviceFailure:
            candidate, candidate_status = error.code, error.status
            if (
                type(candidate) is str
                and type(candidate_status) is int
                and LOCAL_DEVICE_FAILURES.get(candidate) == candidate_status
            ):
                public_code, status, exception = (
                    candidate,
                    candidate_status,
                    "LocalDeviceFailure",
                )
        return {
            "code": public_code,
            "status": status,
            "exception": exception,
            "chain_count": count,
            "frames": frames,
            "truncated": truncated,
            **wire,
        }, initiating
    finally:
        del current, trace


def project_callchain(root: Path) -> tuple[list[dict[str, Any]], bool]:
    paths = {
        os.path.normcase(os.path.abspath(root / SOURCES[label])): label
        for label in FUNCTIONS
    }
    frames: list[dict[str, Any]] = []
    frame: FrameType | None = sys._getframe(1)
    try:
        # Unknown and helper frames consume the same finite inspection budget.
        for _ in range(8):
            if frame is None:
                break
            code = frame.f_code
            label = paths.get(os.path.normcase(os.path.abspath(code.co_filename)))
            if (
                label is not None
                and code.co_name in FUNCTIONS[label]
                and 1 <= frame.f_lineno <= 20000
            ):
                frames.append(
                    {"module": label, "function": code.co_name, "line": frame.f_lineno}
                )
            frame = frame.f_back
        return frames, frame is not None
    finally:
        del frame


def snapshot_state(
    admission: object, coordinator: object, value: object, event: str
) -> dict[str, Any]:
    """Read exact retained dataclass fields only; snapshot is deliberately non-atomic."""
    state: dict[str, Any] = {"snapshot_atomic": False}
    master: OriginalConstructorRecord | None = None
    owned: ViewerRecord | DedicatedRecord | None = None
    if type(coordinator) is DeviceEpochCoordinator:
        if event == "COORDINATOR_CURRENT" and type(value) is UUID:
            owned = coordinator._viewers.get(value) or coordinator._dedicated.get(value)
        elif (
            event == "MAIN_RETENTION_CURRENT"
            and type(value) is LocalMediaLease
            and type(value.id) is UUID
        ):
            candidate = coordinator._dedicated.get(value.id)
            if type(candidate) is DedicatedRecord and candidate.lease is value:
                owned = candidate
        elif type(value) in (ViewerRecord, DedicatedRecord):
            owned = cast(ViewerRecord | DedicatedRecord, value)
        elif type(value) is OriginalConstructorRecord:
            master = value
        if owned is not None and type(owned) in (ViewerRecord, DedicatedRecord):
            master = owned.master
            for key in ("starting", "stopping", "closing"):
                item = getattr(owned, key)
                if type(item) is bool:
                    state[key] = item
    if type(admission) is SqlMuxAdmission and type(value) in (
        TransportGrant,
        SlotRetentionGrant,
        ViewerGrant,
    ):
        grant = cast(TransportGrant | SlotRetentionGrant | ViewerGrant, value)
        grant_record = admission._records.get(id(grant))
        registered = type(grant_record) is _Record and grant_record.grant is grant
        state["registered"] = registered
        if type(grant_record) is _Record and grant_record.grant is grant:
            state["denied"], state["closed"] = grant_record.denied, grant_record.closed
            if type(coordinator) is DeviceEpochCoordinator:
                master = coordinator._records.get(grant_record.master_id)
                holder: TransportGrant | SlotRetentionGrant | ViewerGrant | None = None
                if (
                    type(value) is TransportGrant
                    and type(master) is OriginalConstructorRecord
                ):
                    holder = master.transport
                elif type(value) is ViewerGrant:
                    retained = coordinator._viewers.get(value.lease_id)
                    if type(retained) is ViewerRecord:
                        holder = retained.grant
                elif type(master) is OriginalConstructorRecord:
                    slot = master.slots.get(
                        cast(SlotRetentionGrant, value).slot.channel
                    )
                    if type(slot) is SlotRecord:
                        holder = slot.grant
                if type(holder) is type(value):
                    state["holder_replaced"] = holder is not value
        # Never call the owner's clock or authority/supplier methods for logging.
        if (
            admission._clock is time.monotonic
            and type(grant.expires_monotonic) is float
        ):
            state["expired"] = time.monotonic() >= grant.expires_monotonic
    if type(master) is OriginalConstructorRecord:
        if type(master.state) is EpochState:
            state["master_state"] = master.state.value
        if type(master.refreshing) is bool:
            state["refreshing"] = master.refreshing
    return state


class BoundedCoreStateDiagnostics:
    """Bounded canonical-byte queue and explicitly retained runtime publisher."""

    def __init__(self, writer: Callable[[bytes], None]) -> None:
        self._writer = writer
        self._lock, self._publish_lock, self._close_lock = Lock(), Lock(), Lock()
        self._queue: deque[bytes] = deque()
        self._counts = dict.fromkeys(COUNTERS, 0)
        self._hooks: dict[str, int] = {}
        self._seen: set[tuple[str, int]] = set()
        self._bytes = 0
        self._final = False
        self._stop = Event()
        self._thread: Thread | None = None
        self._start_attempted = False
        self._start_outcome = "NOT_ATTEMPTED"
        self._native_sink: NativeFirstKeySink | None = None
        self._native_writer: Callable[[bytes], None] | None = None
        self._native_counts = dict.fromkeys(
            ("accepted", "written", "omitted", "diagnostic_failures"), 0
        )
        self._native_bytes = 0
        self._started: float | None
        try:
            self._started = time.monotonic()
        except BaseException:  # noqa: BLE001 - optional clock
            self._started = None
            self._counts["diagnostic_failures"] = 1

    def failed(self) -> None:
        with self._lock:
            self._counts["diagnostic_failures"] = min(
                LIMIT, self._counts["diagnostic_failures"] + 1
            )

    def first(self, event: str, value: object) -> bool:
        with self._lock:
            identity = (event, id(value))
            if identity in self._seen:
                self._counts["suppressed"] = min(LIMIT, self._counts["suppressed"] + 1)
                return False
            if len(self._seen) >= 127:
                self._counts["omitted"] = min(LIMIT, self._counts["omitted"] + 1)
                return False
            self._seen.add(identity)
            return True

    def _elapsed(self) -> int:
        if self._started is None:
            return 0
        return min(7200000, max(0, int((time.monotonic() - self._started) * 1000)))

    def capture(
        self,
        event: str,
        purpose: str,
        result: str,
        state: dict[str, Any],
        frames: list[dict[str, Any]],
        truncated: bool,
        *,
        exception: str = "none",
        failure: dict[str, Any] | None = None,
    ) -> None:
        try:
            elapsed = self._elapsed()
            with self._lock:
                if self._final or self._counts["accepted"] >= 127:
                    self._counts["omitted"] = min(LIMIT, self._counts["omitted"] + 1)
                    return
                hook = event + ":" + purpose
                raw = checked_record(
                    {
                        "schema_version": 1,
                        "event": event,
                        "purpose": purpose,
                        "result": result,
                        "exception": exception,
                        "sequence": self._counts["accepted"] + 1,
                        "hook_sequence": self._hooks.get(hook, 0) + 1,
                        "elapsed_ms": elapsed,
                        "state": state,
                        "frames": frames,
                        "truncated": truncated,
                        **(self._counts | {"accepted": self._counts["accepted"] + 1}),
                        **({} if failure is None else failure),
                    }
                )
                if self._bytes + len(raw) > 65536 - 2048:
                    self._counts["omitted"] = min(LIMIT, self._counts["omitted"] + 1)
                    return
                self._hooks[hook] = self._hooks.get(hook, 0) + 1
                self._counts["accepted"] += 1
                self._bytes += len(raw)
                self._queue.append(raw)
        except BaseException:  # noqa: BLE001 - no optional failure changes authority
            self.failed()

    def _write(self, raw: bytes) -> None:
        try:
            self._writer(raw)
            with self._lock:
                self._counts["written"] += 1
        except BaseException:  # noqa: BLE001 - attempted record is never retried
            self.failed()

    def publish(self) -> None:
        with self._publish_lock:
            while True:
                with self._lock:
                    if not self._queue:
                        break
                    raw = self._queue.popleft()
                self._write(raw)
            self._publish_native()

    def add_native_sink(
        self, sink: NativeFirstKeySink, writer: Callable[[bytes], None]
    ) -> None:
        if self._thread is not None or self._native_sink is not None:
            raise ValueError("original native diagnostic channel changed")
        if type(sink) is not NativeFirstKeySink:
            raise ValueError("exact native diagnostic sink required")
        self._native_sink, self._native_writer = sink, writer

    def _publish_native(self) -> None:
        if self._native_sink is None or self._native_writer is None:
            return
        try:
            rows = self._native_sink.drain()
        except BaseException:  # noqa: BLE001 - drain is optional, outside owner locks
            with self._lock:
                self._native_counts["diagnostic_failures"] = min(
                    LIMIT, self._native_counts["diagnostic_failures"] + 1
                )
            return
        for raw in rows:
            with self._lock:
                if (
                    type(raw) is not bytes
                    or not 0 < len(raw) <= 2048
                    or not raw.endswith(b"\n")
                    or self._native_counts["accepted"] >= 128
                    or self._native_bytes + len(raw) > 65536
                ):
                    self._native_counts["omitted"] = min(
                        LIMIT, self._native_counts["omitted"] + 1
                    )
                    continue
                self._native_counts["accepted"] += 1
                self._native_bytes += len(raw)
            try:
                self._native_writer(raw)
                with self._lock:
                    self._native_counts["written"] += 1
            except BaseException:  # noqa: BLE001 - never retry attempted bytes
                with self._lock:
                    self._native_counts["diagnostic_failures"] = min(
                        LIMIT, self._native_counts["diagnostic_failures"] + 1
                    )

    def start(self) -> None:
        def watch() -> None:
            while not self._stop.wait(0.25):
                self.publish()

        if self._thread is not None:
            return
        try:
            # Retain the exact original before start; never discard it on failure.
            self._thread = Thread(
                target=watch, name="fixture-core-state-debug", daemon=False
            )
            self._start_attempted = True
            self._start_outcome = "UNKNOWN"
            self._thread.start()
            self._start_outcome = "RETURNED"
        except BaseException:  # noqa: BLE001 - runtime retains uncertain thread
            if self._start_attempted:
                self._start_outcome = "UNKNOWN"
            self.failed()

    def close(self) -> bool:
        with self._close_lock:
            self._stop.set()
            try:
                if self._thread is not None and self._start_attempted:
                    # start() can acquire a platform thread, then be interrupted
                    # before bootstrap publishes ident/_started. False is_alive
                    # in that window is not evidence of non-acquisition.
                    if self._thread.ident is None:
                        return False
                    # The original join also requires its positive bootstrap
                    # event; only a successful join plus non-alive settles it.
                    self._thread.join(timeout=0.2)
                    if self._thread.is_alive():
                        return False
                    self._start_outcome = "RETIRED"
                self.publish()
                with self._lock:
                    if self._final:
                        return True
                    self._final = True
                    raw = checked_record(
                        {
                            "schema_version": 1,
                            "event": "SUMMARY",
                            "purpose": "NONE",
                            "result": "FINAL",
                            "exception": "none",
                            "sequence": self._counts["accepted"] + 1,
                            "hook_sequence": 1,
                            "elapsed_ms": 0,
                            "state": {},
                            "frames": [],
                            "truncated": False,
                            **self._counts,
                        }
                    )
                self._write(raw)
                return True
            except BaseException:  # noqa: BLE001 - preserve retained publisher custody
                self.failed()
                return False

    def status(self) -> dict[str, Any]:
        dropped = 0
        if self._native_sink is not None:
            try:
                dropped = self._native_sink.dropped
            except BaseException:  # noqa: BLE001 - optional reporting only
                self.failed()
        with self._lock:
            return (
                self._counts
                | {
                    "publisher_settled": self._final,
                    "publisher_start_attempted": self._start_attempted,
                    "publisher_start_outcome": self._start_outcome,
                }
                | (
                    {"native": self._native_counts | {"queue_dropped": dropped}}
                    if self._native_sink is not None
                    else {}
                )
            )


def install_hooks(
    admission: object,
    coordinator: object,
    sink: BoundedCoreStateDiagnostics,
    *,
    root: Path,
) -> None:
    def wrapper(
        original: Callable[..., Any], event: str, purpose: str
    ) -> Callable[..., Any]:
        def emit(
            value: object,
            result: str,
            error: BaseException | None = None,
            refresh: tuple[bool, bool] | None = None,
        ) -> None:
            try:
                frames, truncated = project_callchain(root)
                state = snapshot_state(admission, coordinator, value, event)
                if refresh is not None:
                    state["refreshing_at_entry"], state["refresh_changed"] = refresh
                sink.capture(
                    event,
                    purpose,
                    result,
                    state,
                    frames,
                    truncated,
                    exception="none"
                    if error is None
                    else "LocalDeviceFailure"
                    if type(error) is LocalDeviceFailure
                    else "unexpected",
                )
            except BaseException:  # noqa: BLE001 - preserve original even with broken sink
                try:
                    sink.failed()
                except BaseException:  # noqa: BLE001, S110
                    pass

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            value = (
                args[0]
                if args
                else kwargs.get(
                    "lease_id",
                    kwargs.get("grant", kwargs.get("record", kwargs.get("owned"))),
                )
            )
            refresh = None
            try:
                if (
                    event == "DEDICATED_CURRENT"
                    and type(value) is DedicatedRecord
                    and type(value.master) is OriginalConstructorRecord
                    and type(value.master.refreshing) is bool
                    and type(value.master.refresh_version) is int
                ):
                    refresh = (
                        value.master,
                        value.master.refreshing,
                        value.master.refresh_version,
                    )
            except BaseException:  # noqa: BLE001,S110 - optional snapshot only
                pass

            def refresh_result() -> tuple[bool, bool] | None:
                try:
                    if refresh is not None:
                        return refresh[1], refresh[0].refresh_version != refresh[2]
                except BaseException:  # noqa: BLE001,S110 - preserve original result
                    pass
                return None

            if event in {"MASTER_FENCE", "VIEWER_CLOSE", "DEDICATED_CLOSE"}:
                if event == "VIEWER_CLOSE":
                    caller = None
                    error = None
                    try:
                        caller = sys._getframe(1)
                        # Unknown/helper callers consume this finite stack scan.
                        for _ in range(8):
                            if caller is None:
                                break
                            if (
                                caller.f_code
                                is MuxMediaExecutor.read_mux_frames.__code__
                                and os.path.normcase(
                                    os.path.abspath(caller.f_code.co_filename)
                                )
                                == os.path.normcase(
                                    os.path.abspath(root / SOURCES["mux_service"])
                                )
                            ):
                                error = sys.exception()
                                if error is not None:
                                    failure, initiating = project_read_failure(
                                        error, root=root, reader=caller
                                    )
                                    # Same active reader must be in the handled
                                    # exception's own traceback. An unrelated
                                    # held error on a normal Stop is not enough.
                                    if initiating:
                                        sink.capture(
                                            "VIEWER_READ_EXCEPTION",
                                            "NONE",
                                            "EXCEPTION",
                                            snapshot_state(
                                                admission, coordinator, value, event
                                            ),
                                            failure["frames"],
                                            failure["truncated"],
                                            exception=failure["exception"],
                                            failure={
                                                key: failure[key]
                                                for key in FAILURE_FIELDS | WIRE_FIELDS
                                                if key in failure
                                            },
                                        )
                                break
                            caller = caller.f_back
                    except BaseException:  # noqa: BLE001 - optional diagnosis
                        try:
                            sink.failed()
                        except BaseException:  # noqa: BLE001, S110
                            pass
                    finally:
                        del caller, error
                if event == "MASTER_FENCE":
                    caller = None
                    error = None
                    try:
                        caller = sys._getframe(1)
                        # Only the actual Core heartbeat catch may expose its
                        # handled exception; names/unknown stack frames cannot.
                        if (
                            caller.f_code is DeviceEpochCoordinator.heartbeat.__code__
                            and os.path.normcase(
                                os.path.abspath(caller.f_code.co_filename)
                            )
                            == os.path.normcase(
                                os.path.abspath(root / SOURCES["mux_service"])
                            )
                        ):
                            error = sys.exception()
                            if error is not None:
                                failure = project_heartbeat_failure(error, root=root)
                                sink.capture(
                                    "HEARTBEAT_EXCEPTION",
                                    "NONE",
                                    "EXCEPTION",
                                    snapshot_state(
                                        admission, coordinator, value, event
                                    ),
                                    failure["frames"],
                                    failure["truncated"],
                                    exception=failure["exception"],
                                    failure={
                                        key: failure[key] for key in FAILURE_FIELDS
                                    },
                                )
                    except BaseException:  # noqa: BLE001 - optional diagnosis
                        try:
                            sink.failed()
                        except BaseException:  # noqa: BLE001, S110
                            pass
                    finally:
                        del caller, error
                try:
                    if sink.first(event, value):
                        emit(value, "ENTRY")
                except BaseException:  # noqa: BLE001, S110 - original always invoked
                    pass
                return original(*args, **kwargs)
            try:
                result = original(*args, **kwargs)
            except BaseException as error:
                refresh_facts = refresh_result()
                if event == "GRANT_REFRESH_EXCEPTION":
                    try:
                        grant_purpose = {
                            TransportGrant: "TRANSPORT",
                            SlotRetentionGrant: "SLOT_RETENTION",
                            ViewerGrant: "VIEWER",
                        }.get(type(value))
                        if grant_purpose is not None and sink.first(event, value):
                            failure = project_heartbeat_failure(error, root=root)
                            sink.capture(
                                event,
                                grant_purpose,
                                "EXCEPTION",
                                {},
                                failure["frames"],
                                failure["truncated"],
                                exception=failure["exception"],
                                failure={key: failure[key] for key in FAILURE_FIELDS},
                            )
                    except BaseException:  # noqa: BLE001 -- preserve original failure
                        try:
                            sink.failed()
                        except BaseException:  # noqa: BLE001,S110
                            pass
                else:
                    if event not in {"DEDICATED_CURRENT", "MAIN_RETENTION_CURRENT"}:
                        emit(value, "EXCEPTION", error)
                    else:
                        try:
                            if sink.first(event, value):
                                emit(value, "EXCEPTION", error, refresh_facts)
                        except BaseException:  # noqa: BLE001,S110 - preserve original
                            pass
                raise
            if result is False:
                refresh_facts = refresh_result()
                if event not in {"DEDICATED_CURRENT", "MAIN_RETENTION_CURRENT"}:
                    emit(value, "FALSE")
                else:
                    try:
                        if sink.first(event, value):
                            emit(value, "FALSE", refresh=refresh_facts)
                    except BaseException:  # noqa: BLE001,S110 - preserve original
                        pass
            return result

        return wrapped

    hooks = [
        (coordinator, "current", "COORDINATOR_CURRENT", "NONE"),
        (coordinator, "_fence", "MASTER_FENCE", "NONE"),
        (coordinator, "_close_viewer", "VIEWER_CLOSE", "NONE"),
        (admission, "current_transport", "GRANT_CURRENT", "TRANSPORT"),
        (admission, "current_slot", "GRANT_CURRENT", "SLOT_RETENTION"),
        (admission, "current_viewer", "GRANT_CURRENT", "VIEWER"),
    ]
    for owner, cls, name, event in (
        (
            coordinator,
            DeviceEpochCoordinator,
            "_current_dedicated",
            "DEDICATED_CURRENT",
        ),
        (coordinator, DeviceEpochCoordinator, "_close_dedicated", "DEDICATED_CLOSE"),
        (
            admission,
            SqlMuxAdmission,
            "current_main_retention",
            "MAIN_RETENTION_CURRENT",
        ),
    ):
        if type(owner) is cls:
            original = getattr(owner, name)
            if type(original) is MethodType and original.__func__ is getattr(cls, name):
                hooks.append((owner, name, event, "NONE"))
    if type(admission) is SqlMuxAdmission:
        refresh = admission._refresh_current_grant
        if (
            type(refresh) is MethodType
            and refresh.__func__ is SqlMuxAdmission._refresh_current_grant
        ):
            hooks.append(
                (admission, "_refresh_current_grant", "GRANT_REFRESH_EXCEPTION", "NONE")
            )
    retained = [
        (owner, name, getattr(owner, name), event, purpose)
        for owner, name, event, purpose in hooks
    ]
    assigned = []
    try:
        for owner, name, original, event, purpose in retained:
            setattr(owner, name, wrapper(original, event, purpose))
            assigned.append((owner, name, original))
    except BaseException:
        for owner, name, original in reversed(assigned):
            setattr(owner, name, original)
        raise
