"""Opt-in private fixture observations. No SDK hooks or resource ownership."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from ctypes import wintypes
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import UUID

ROLES = frozenset({"coordinator", "runtime", "next", "api", "worker"})
# Dedicated snapshot budget; ordinary private context files keep their 64 KiB cap.
# Compact full-cardinality projection (256 sources, 16 formats, 6 milestones,
# 256 native attempts/peers, 64-bit counter envelope) fits below this finite cap.
SNAPSHOT_MAX_BYTES = 1024 * 1024
FAILURE_STAGES = frozenset(
    {
        "executor_start",
        "worker_prepare",
        "retirement_attach",
        "proof_read",
        "source_create",
        "source_start",
        "binding",
        "prepare_lease",
        "peer_create",
        "adapter",
        "source_current",
        "authority_renew",
        "ingress_read",
        "ingress_queue",
        "decoder_create",
        "decoder_decode",
        "decoder_retire",
        "format_transition",
        "publish_authority",
        "source",
        "peer_check",
        "peer_deadline",
        "peer_watch",
        "peer_connection",
        "peer",
        "worker_watch",
        "worker_lease",
        "worker_renew",
        "worker_start",
    }
)
FAILURE_REASONS = frozenset(
    {
        "failure",
        "denied",
        "deadline",
        "no_signal",
        "protocol_invalid",
        "cancelled",
        "busy",
        "generation_conflict",
        "upstream_rejected",
        "proof_invalid",
        "validation_failure",
        "frame_invalid",
        "timestamp_invalid",
        "metadata_invalid",
        "scope_invalid",
        "identity_changed",
        "format_changed",
        "framing_invalid",
        "header_invalid",
        "picture_unsupported",
        "initial_picture_unsupported",
        "parameter_sets_missing",
        "parameter_sets_or_idr_missing",
        "source_ended",
        "overflow",
        "first_frame_deadline",
        "explicit_close",
        "closed",
        "fenced",
        "current_false",
        "current_error",
        "stale_permit",
        "connection_failed",
        "connection_closed",
        "invalid_deadline",
        "close_scheduled",
        "transition_deadline",
        "rotation_limit",
        "wait_timeout",
    }
)
MILESTONES = frozenset(
    {
        "native_return",
        "first_adapter_packet",
        "first_decoded_frame",
        "binding_ready",
        "peer_created",
        "peer_connected",
    }
)
TRANSITION_EVENTS = frozenset(
    {
        "started",
        "decoder_rotated",
        "inter_picture_omitted",
        "output_verified",
        "late_output_omitted",
    }
)


def timestamp_failure(reason: str) -> dict[str, Any]:
    """Closed relative-only projection; never accept absolute timestamps/text."""
    if type(reason) is not str or len(reason) > 48:
        raise ValueError("observation timestamp refused")
    fields = reason.split(",")
    if len(fields) != 3:
        raise ValueError("observation timestamp refused")
    kind, raw_delta, saturated = fields
    if kind in {"missing", "invalid"} and raw_delta == "" and saturated == "0":
        return {"kind": kind, "delta_us": None, "delta_saturated": False}
    if kind == "duplicate" and raw_delta == "0" and saturated == "0":
        return {"kind": kind, "delta_us": 0, "delta_saturated": False}
    if kind == "regression" and saturated in {"0", "1"}:
        delta = int(raw_delta)
        if (
            str(delta) == raw_delta
            and -(2**31 - 1) <= delta < 0
            and (saturated == "0" or delta == -(2**31 - 1))
        ):
            return {
                "kind": kind,
                "delta_us": delta,
                "delta_saturated": saturated == "1",
            }
    raise ValueError("observation timestamp refused")


def transition_format(reason: str) -> dict[str, Any]:
    """Only codec and capped dimensions may enter optional transition evidence."""
    if type(reason) is not str or len(reason) > 64:
        raise ValueError("observation format refused")
    fields = reason.split(",")
    if len(fields) != 6 or fields[0] not in ("h264", "hevc") or fields[3] != fields[0]:
        raise ValueError("observation format refused")
    result = {}
    for name, offset in (("old", 0), ("new", 3)):
        width, height = fields[offset + 1 : offset + 3]
        if not all(value.isascii() and value.isdecimal() for value in (width, height)):
            raise ValueError("observation format refused")
        w, h = int(width), int(height)
        if not (1 <= w <= 4096 and 1 <= h <= 2160 and w * h * 3 <= 16 * 1024 * 1024):
            raise ValueError("observation format refused")
        result[name] = {"codec": fields[offset], "width": w, "height": h}
    return result


def snapshot_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def write_snapshot(path: Path, value: dict[str, Any]) -> None:
    """Observation-only writer; retain the private writer's path/atomic rules."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > SNAPSHOT_MAX_BYTES:
        raise ValueError("observation snapshot must be bounded")
    if (
        path.is_symlink()
        or path.is_junction()
        or path.parent.is_symlink()
        or path.parent.is_junction()
    ):
        raise ValueError("private path ownership")
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def valid_terminal(value: Any) -> bool:
    return (
        type(value) is dict
        and set(value)
        == {
            "schema_version",
            "status",
            "writer_settled",
            "observation_failures",
            "omitted_attempts",
            "omitted_peers",
            "snapshot_sha256",
        }
        and type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["status"] in ("COMPLETE", "FAILED")
        and type(value["writer_settled"]) is bool
        and all(
            type(value[key]) is int and value[key] >= 0
            for key in ("observation_failures", "omitted_attempts", "omitted_peers")
        )
        and (
            value["snapshot_sha256"] is None
            or (
                type(value["snapshot_sha256"]) is str
                and len(value["snapshot_sha256"]) == 64
                and all(char in "0123456789abcdef" for char in value["snapshot_sha256"])
            )
        )
    )


def read_terminal(path: Path) -> dict[str, Any]:
    """Original runtime reads only after its original worker has settled."""
    try:
        with path.open("rb") as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            raise ValueError("observation terminal refused")
        value = json.loads(data)["mediaObservation"]
        if not valid_terminal(value):
            raise ValueError("observation terminal refused")
        result: dict[str, Any] = value
        return result
    except Exception:  # noqa: BLE001 -- absence/private parser errors never certify.
        return {"schema_version": 1, "status": "UNAVAILABLE"}


def complete_observation(summary: Any, terminal: Any) -> bool:
    """Controller gate: require original-custodian terminal AND exact snapshot."""
    return (
        valid_terminal(terminal)
        and terminal["status"] == "COMPLETE"
        and terminal["writer_settled"] is True
        and all(
            terminal[key] == 0
            for key in ("observation_failures", "omitted_attempts", "omitted_peers")
        )
        and type(summary) is dict
        and type(summary.get("schema_version")) is int
        and summary.get("schema_version") in (2, 3)
        and (
            summary["schema_version"] == 2
            or (type(summary.get("mux")) is dict and summary["mux"].get("omitted") == 0)
        )
        and summary.get("stop_requested") is True
        and terminal["snapshot_sha256"] == snapshot_digest(summary)
    )


def owner_identity(role: str, pid: int, creation: int) -> dict[str, Any]:
    if (
        role not in ROLES
        or type(pid) is not int
        or pid <= 0
        or type(creation) is not int
        or not 0 < creation < 2**63
    ):
        raise ValueError("observation identity refused")
    # JSON numbers would lose the low FILETIME bits in Node.
    return {"role": role, "pid": pid, "creation_filetime": str(creation)}


def windows_identity(role: str, caller: int | None = None) -> dict[str, Any]:
    """Current self, or synchronously waiting original Node parent only."""
    if os.name != "nt" or (caller is not None and caller != os.getppid()):
        raise ValueError("observation identity refused")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
        ctypes.POINTER(wintypes.FILETIME)
    ] * 4
    kernel.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = (
        kernel.GetCurrentProcess()
        if caller is None
        else kernel.OpenProcess(0x1000, False, caller)
    )
    try:
        if not handle or kernel.GetProcessId(handle) != (
            os.getpid() if caller is None else caller
        ):
            raise ValueError("observation identity refused")
        times = [wintypes.FILETIME() for _ in range(4)]
        code = wintypes.DWORD()
        if (
            not kernel.GetProcessTimes(
                handle, *(ctypes.byref(value) for value in times)
            )
            or not kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            or code.value != 259
        ):
            raise ValueError("observation identity refused")
        creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return owner_identity(role, os.getpid() if caller is None else caller, creation)
    finally:
        if caller is not None and handle:
            kernel.CloseHandle(handle)


def identity_fields(*, enabled: bool, role: str) -> dict[str, Any]:
    if not enabled:
        return {}
    try:
        return {"measurement_owner": windows_identity(role)}
    except Exception:  # noqa: BLE001 -- optional observation cannot obstruct cleanup.
        return {"measurement_owner_error": "IDENTITY_UNAVAILABLE"}


def first_media(frame: Any, requested: str, warning: bool) -> dict[str, Any]:
    from wso_core.tvt.local_live import PrivateLiveFrame

    if (
        type(frame) is not PrivateLiveFrame
        or requested not in {"main", "sub"}
        or type(warning) is not bool
    ):
        raise ValueError("observation metadata refused")
    summary = frame.summary()
    kind = frame.source_context[1]
    if (
        type(kind) is not int
        or kind not in {1, 2}
        or summary.codec not in {"h264", "h265"}
        or not 1 <= summary.width <= 4096
        or not 1 <= summary.height <= 2160
    ):
        raise ValueError("observation metadata refused")
    return {
        "requested_stream": requested,
        "media_kind": kind,
        "codec": summary.codec,
        "width": summary.width,
        "height": summary.height,
        "sub_stream_adaptation_off": warning,
    }


class MediaObservation:
    """Bounded safe projections only; originals remain in their existing owners."""

    def __init__(
        self,
        write: Callable[[dict[str, Any]], None],
        *,
        limit: int = 256,
        clock: Callable[[], float] = time.monotonic,
        shared: bool = False,
    ) -> None:
        if type(limit) is not int or not 1 <= limit <= 256 or type(shared) is not bool:
            raise ValueError("observation bound refused")
        self.write, self.limit = write, limit
        self._clock = clock
        self._lock = threading.RLock()
        self._publish_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._attempts: list[dict[str, Any]] = []
        self._peers: list[dict[str, Any]] = []
        self._sources: list[dict[str, Any]] = []
        self._source_count = 0
        self._source_context = threading.local()
        self._recorders: dict[bytes, int] = {}
        self._bindings: dict[tuple[Any, ...], int] = {}
        self._count = self._failures = self._omitted_peers = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._terminal: dict[str, Any] | None = None
        self._last_digest: str | None = None
        self._final_published = False
        self.shared = shared
        self._mux_started = self._clock()
        self._mux_rows: dict[str, list[dict[str, Any]]] = {
            name: [] for name in ("masters", "slots", "viewers", "dedicated", "focus")
        }
        self._mux_maps: dict[str, dict[Any, int]] = {
            name: {} for name in self._mux_rows
        }
        self._mux_omitted = 0
        self._mux_probe: dict[str, Any] | None = None
        self._mux_master_owners: dict[int, tuple[Any, Any]] = {}
        self._mux_viewer_owners: dict[UUID, dict[str, Any]] = {}
        self._mux_credits: dict[str, Any] = {
            "basis": "SAMPLED_CURRENT_NOT_ACTUAL_PEAK",
            "samples": 0,
            "host_bytes_last": 0,
            "encoded_bytes_last": 0,
            "host_bytes_sampled_max": 0,
            "encoded_bytes_sampled_max": 0,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            value: dict[str, Any] = {
                "schema_version": 3 if self.shared else 2,
                "stop_requested": self._stop.is_set(),
                "attempt_count": self._count,
                "omitted_attempts": self._count - len(self._attempts),
                "observation_failures": self._failures,
                "attempts": [dict(row) for row in self._attempts],
                "source_attempt_count": self._source_count,
                "omitted_source_attempts": self._source_count - len(self._sources),
                "source_attempts": [
                    {
                        "source_attempt": row["source_attempt"],
                        "first_failure": deepcopy(row["first_failure"]),
                        "milestones": [dict(item) for item in row["milestones"]],
                        "transition_counts": dict(row["transition_counts"]),
                        "format_transitions": [
                            {
                                "old": dict(item["old"]),
                                "new": dict(item["new"]),
                                "elapsed_ms": item["elapsed_ms"],
                            }
                            for item in row["format_transitions"]
                        ],
                        "omitted_format_transitions": row["omitted_format_transitions"],
                    }
                    for row in self._sources
                ],
                "peers": [
                    {
                        "peer_ordinal": row["peer_ordinal"],
                        "attempt": row["attempt"],
                        **row["counts"],
                    }
                    for row in self._peers
                ],
                "omitted_peers": self._omitted_peers,
            }
            if self.shared:
                value["mux"] = {
                    **deepcopy(self._mux_rows),
                    "omitted": self._mux_omitted,
                    "credits": dict(self._mux_credits),
                }
            return value

    def _mux_safe(self, callback: Callable[[], Any]) -> Any:
        """Observation failures never change a resource owner's return/exception."""
        try:
            if not self.shared:
                raise ValueError("shared observation required")
            with self._lock:
                if self._terminal is not None:
                    return None
            return callback()
        except BaseException:  # noqa: BLE001 -- failure is a closed counter, never private text.
            with self._lock:
                if self._terminal is None:
                    self._failures += 1
            return None

    def _mux_row(
        self, category: str, identity: Any, **fields: Any
    ) -> dict[str, Any] | None:
        with self._lock:
            if self._terminal is not None:
                return None
            mapping, rows = self._mux_maps[category], self._mux_rows[category]
            if identity in mapping:
                return rows[mapping[identity] - 1]
            if len(rows) >= min(self.limit, 64):
                self._mux_omitted = min(2**31 - 1, self._mux_omitted + 1)
                return None
            ordinal = len(rows) + 1
            row = {"ordinal": ordinal, **fields}
            mapping[identity] = ordinal
            rows.append(row)
            return row

    def _mux_elapsed(self) -> int:
        return max(0, min(2**31 - 1, int((self._clock() - self._mux_started) * 1000)))

    def _mux_active(self, interval: dict[str, Any]) -> bool:
        return (
            self.shared
            and self._mux_probe is interval
            and self._terminal is None
            and not self._stop.is_set()
            and self._thread is interval["writer"]
            and self._thread is not None
            and self._thread.is_alive()
            and self._failures == 0
            and self._mux_omitted == 0
            and self._omitted_peers == 0
            and self._count == len(self._attempts)
            and self._source_count == len(self._sources)
        )

    def begin_mux_probe(self, channels: tuple[int, ...]) -> object:
        with self._lock:
            if (
                self._mux_probe is not None
                or type(channels) is not tuple
                or len(channels) not in (2, 4)
                or len(set(channels)) != len(channels)
            ):
                raise ValueError("current probe interval refused")
            interval = {
                "token": object(),
                "channels": channels,
                "writer": self._thread,
                "bindings": {},
                "prior_counts": {
                    name: len(rows) for name, rows in self._mux_rows.items()
                },
            }
            self._mux_probe = interval
            if not self._mux_active(interval):
                self._mux_probe = None
                raise ValueError("active current observer required")
            return interval["token"]

    def bind_mux_probe(self, token: object, viewer: Any, slot: Any, cut: Any) -> None:
        registration = viewer.registration
        actual_cut = viewer.cut
        with self._lock:
            interval = self._mux_probe
            context = self._mux_viewer_owners.get(registration)
            if (
                interval is None
                or interval["token"] is not token
                or not self._mux_active(interval)
                or context is None
                or context["interval"] is not interval
                or context["viewer"] is not viewer
                or context["slot"] != slot
                or context["cut"] is not cut
                or actual_cut is not cut
                or context["viewer_ordinal"] <= interval["prior_counts"]["viewers"]
                or context["slot_ordinal"] <= interval["prior_counts"]["slots"]
                or context["master_ordinal"] <= interval["prior_counts"]["masters"]
                or len(interval["bindings"]) >= len(interval["channels"])
                or registration in interval["bindings"]
            ):
                raise ValueError("current original probe binding required")
            master = self._mux_master_owners.get(context["master_ordinal"])
            if (
                master is None
                or master[0] is not context["master"]
                or master[1] is not interval
            ):
                raise ValueError("current original master required")
            interval["bindings"][registration] = context

    def mux_probe_current(self, token: object) -> bool:
        try:
            with self._lock:
                interval = self._mux_probe
                if (
                    interval is None
                    or interval["token"] is not token
                    or not self._mux_active(interval)
                ):
                    return False
                bindings: tuple[tuple[UUID, dict[str, Any]], ...] = tuple(
                    interval["bindings"].items()
                )
            # Original properties stay outside the observation registry lock.
            for registration, context in bindings:
                if (
                    context["viewer"].registration != registration
                    or context["viewer"].cut is not context["cut"]
                    or context["viewer"].master is not context["master"]
                ):
                    return False
            with self._lock:
                return self._mux_active(interval) and all(
                    self._mux_viewer_owners.get(registration) is context
                    and context["interval"] is interval
                    and self._mux_master_owners.get(
                        context["master_ordinal"], (None, None)
                    )[0]
                    is context["master"]
                    and self._mux_master_owners[context["master_ordinal"]][1]
                    is interval
                    and self._mux_maps["slots"].get(context["slot"])
                    == context["slot_ordinal"]
                    for registration, context in bindings
                )
        except Exception:  # noqa: BLE001 -- unreadable original evidence never qualifies a run.
            return False

    def mux_probe_snapshot(self, token: object) -> dict[str, Any]:
        if not self.mux_probe_current(token):
            raise ValueError("current probe observation required")
        snapshot = self.snapshot()
        if not self.mux_probe_current(token):
            raise ValueError("probe observation changed")
        with self._lock:
            interval = self._mux_probe
            assert interval is not None
            bindings = tuple(interval["bindings"].values())
            if len(bindings) != len(interval["channels"]):
                raise ValueError("incomplete probe observation")
            indices = {
                "masters": {context["master_ordinal"] for context in bindings},
                "slots": {context["slot_ordinal"] for context in bindings},
                "viewers": {context["viewer_ordinal"] for context in bindings},
            }
            selected = {}
            for category, ordinals in indices.items():
                rows = []
                for ordinal in sorted(ordinals):
                    actual = self._mux_rows[category][ordinal - 1]
                    recorded = snapshot["mux"][category][ordinal - 1]
                    if actual != recorded:
                        raise ValueError("stale probe snapshot")
                    rows.append(deepcopy(actual))
                selected[category] = rows
            if any(
                "first" not in row or row["frames"] < 2 for row in selected["viewers"]
            ):
                raise ValueError("current probe frames unobserved")
            snapshot["mux"].update(selected)
            return snapshot

    def end_mux_probe(self, token: object) -> None:
        with self._lock:
            if self._mux_probe is None or self._mux_probe["token"] is not token:
                raise ValueError("original probe interval required")
            self._mux_probe = None

    def record_mux_focus(self, reference: UUID, event: str) -> None:
        def record() -> None:
            if (
                type(reference) is not UUID
                or not reference.int
                or event not in {"RESERVE_RETURNED", "SETTLE_RETURNED"}
            ):
                raise ValueError("focus observation refused")
            row = self._mux_row("focus", reference, reserve_returns=0, settle_returns=0)
            if row is not None:
                with self._lock:
                    if self._terminal is not None:
                        return
                    key = (
                        "reserve_returns"
                        if event == "RESERVE_RETURNED"
                        else "settle_returns"
                    )
                    row[key] = min(2**31 - 1, row[key] + 1)
                    row["last_elapsed_ms"] = self._mux_elapsed()

        self._mux_safe(record)

    def sample_mux_credits(self) -> None:
        def sample() -> None:
            from wso_tvt_bridge.local_live_mux_ipc import media_credit_usage

            host, encoded = media_credit_usage()
            if (
                type(host) is not int
                or type(encoded) is not int
                or not 0 <= encoded <= host <= 1 << 30
            ):
                raise ValueError("credit observation refused")
            with self._lock:
                if self._terminal is not None:
                    return
                row = self._mux_credits
                row["samples"] = min(2**31 - 1, int(row["samples"]) + 1)
                row["host_bytes_last"], row["encoded_bytes_last"] = host, encoded
                row["host_bytes_sampled_max"] = max(
                    int(row["host_bytes_sampled_max"]), host
                )
                row["encoded_bytes_sampled_max"] = max(
                    int(row["encoded_bytes_sampled_max"]), encoded
                )

        self._mux_safe(sample)

    def wrap_mux_controls(self, adapter: Any) -> Any:
        observer = self

        class Controls:
            def __getattr__(self, name: str) -> Any:
                return getattr(adapter, name)

            def focus_reserve(self, *args: Any, **kwargs: Any) -> Any:
                result = adapter.focus_reserve(*args, **kwargs)
                observer._mux_safe(
                    lambda: observer.record_mux_focus(result.id, "RESERVE_RETURNED")
                )
                return result

            def focus_settle(self, *args: Any, **kwargs: Any) -> Any:
                result = adapter.focus_settle(*args, **kwargs)
                observer._mux_safe(
                    lambda: observer.record_mux_focus(result.id, "SETTLE_RETURNED")
                )
                return result

        return Controls()

    @staticmethod
    def _mux_wire(parent: Any, slot: Any) -> dict[str, Any]:
        project = getattr(parent, "wire_observation", None)
        if not callable(project):
            return {"ack": None, "media": None, "status": "UNAVAILABLE"}
        value = project(slot)
        if type(value) is not tuple or len(value) != 2:
            raise ValueError("wire observation refused")
        result: dict[str, Any] = {"status": "OBSERVED"}
        for name, item, length in (("ack", value[0], 5), ("media", value[1], 4)):
            if item is None:
                result[name] = None
                continue
            if (
                type(item) is not tuple
                or len(item) != length
                or any(
                    type(number) is not int or not 0 <= number <= 0xFFFFFFFF
                    for number in item[:4]
                )
                or item[0] not in (0, 2)
                or not 0 <= item[1] <= 255
            ):
                raise ValueError("wire observation refused")
            if name == "ack" and (
                item[2] not in (0x10000501, 0x10000505) or type(item[4]) is not bool
            ):
                raise ValueError("ack observation refused")
            if name == "media" and item[2] != 65537:
                raise ValueError("media observation refused")
            result[name] = dict(
                zip(
                    ("route", "wire_kind", "command", "sequence"), item[:4], strict=True
                )
            )
            if name == "ack":
                result[name]["warning"] = item[4]
        if result["ack"] is None:
            result["status"] = "UNAVAILABLE"
        return result

    def _mux_hook(self, original: Any, name: str, after: Callable[..., None]) -> None:
        method = getattr(original, name)

        @wraps(method)
        def observed(*args: Any, **kwargs: Any) -> Any:
            result = method(*args, **kwargs)
            self._mux_safe(lambda: after(result, *args, **kwargs))
            return result

        setattr(original, name, observed)

    def _mux_once(self, original: Any) -> bool:
        previous = getattr(original, "_fixture_mux_observer", None)
        if previous is self:
            return False
        if previous is not None:
            raise ValueError("observer already installed")
        original._fixture_mux_observer = self
        return True

    def _mux_attempt(
        self, registration: UUID, stream: str, **fields: Any
    ) -> dict[str, Any] | None:
        if type(registration) is not UUID or not registration.int:
            raise ValueError("registration observation refused")
        with self._lock:
            if self._terminal is not None:
                return None
            self._count += 1
            attempt = self._count
            row = self._mux_row(
                "viewers",
                registration,
                attempt=attempt,
                stream=stream,
                frames=0,
                cleanup="RETAINED",
                **fields,
            )
            if attempt <= self.limit:
                self._attempts.append(
                    {
                        "attempt": attempt,
                        "requested_stream": stream,
                        "source_attempt": getattr(
                            self._source_context, "ordinal", None
                        ),
                        "outcome": "PREPARED",
                    }
                )
            return row

    def _mux_frame(self, row: dict[str, Any], frame: Any, *, cut: Any = None) -> None:
        from wso_core.tvt.local_media_mux_types import MuxValidatedFrame

        if cut is not None:
            if (
                type(frame) is not MuxValidatedFrame
                or frame.slot != cut.slot
                or frame.ingress.first <= cut.after_ordinal
            ):
                raise ValueError("cut observation refused")
            raw = frame.frame
        else:
            raw = frame
        metadata = first_media(raw, row["stream"], False)
        # Warning is a wire ACK property; do not invent it for this frame.
        metadata.pop("sub_stream_adaptation_off")
        metadata["selected_stream_kind"] = metadata.pop("media_kind")
        metadata["elapsed_ms"] = self._mux_elapsed()
        metadata["key_frame"] = raw.key_frame
        if cut is not None:
            metadata.update(
                ingress_first=frame.ingress.first,
                ingress_last=frame.ingress.last,
                slot_ordinal=frame.slot_ordinal,
                cut_decision="POST_CUT_RETURNED",
            )
        identity = raw.identity
        with self._lock:
            if self._terminal is not None:
                return
            row["frames"] = min(2**31 - 1, row["frames"] + 1)
            row.setdefault("first", dict(metadata))
            row["last"] = metadata
            binding = (
                identity.generation,
                identity.session,
                identity.channel,
                identity.task,
            )
            if binding not in self._bindings and len(self._bindings) >= self.limit:
                self._mux_omitted += 1
            else:
                self._bindings[binding] = row["attempt"]

    def _mux_cleanup(
        self, row: dict[str, Any] | None, receipt: Any, scope: str
    ) -> None:
        from wso_core.tvt.local_media_mux_types import (
            EpochCleanupReceipt,
            ViewerCleanupReceipt,
        )

        if row is None:
            return
        expected = ViewerCleanupReceipt if scope == "VIEWER" else EpochCleanupReceipt
        if receipt is not None and type(receipt) is not expected:
            raise ValueError("cleanup observation refused")
        with self._lock:
            if self._terminal is not None:
                return
            row["cleanup"] = "RETAINED" if receipt is None else "RECEIPT_RETURNED"
            row["cleanup_scope"] = scope
            row["cleanup_elapsed_ms"] = self._mux_elapsed()
            if type(receipt) is EpochCleanupReceipt:
                row["original_state"] = receipt.original_state

    def _mux_viewer(
        self, original: Any, master: Any, grant: Any, master_ordinal: int
    ) -> None:
        if not self._mux_once(original):
            return
        slot_ordinal = self._mux_maps["slots"].get(grant.slot)
        if slot_ordinal is None:
            raise ValueError("slot correlation unavailable")
        row = self._mux_attempt(
            grant.registration,
            "sub",
            master_ordinal=master_ordinal,
            slot_ordinal=slot_ordinal,
        )
        context = None
        if row is not None:
            with self._lock:
                context = {
                    "viewer": original,
                    "master": master,
                    "slot": grant.slot,
                    "cut": None,
                    "interval": self._mux_probe,
                    "master_ordinal": master_ordinal,
                    "slot_ordinal": slot_ordinal,
                    "viewer_ordinal": row["ordinal"],
                }
                self._mux_viewer_owners[grant.registration] = context

        def started(_result: Any, **kwargs: Any) -> None:
            cut = original.cut
            if cut.registration != grant.registration or cut.slot != grant.slot:
                raise ValueError("cut correlation refused")
            if row is not None:
                with self._lock:
                    if self._terminal is not None:
                        return
                    row["cut"] = {
                        "control_sequence": cut.control_sequence,
                        "after_ordinal": cut.after_ordinal,
                    }
                    if context is not None:
                        context["cut"] = cut

        def read(result: Any, **kwargs: Any) -> None:
            if type(result) is not tuple:
                raise ValueError("frame collection refused")
            if row is not None:
                for frame in result:
                    self._mux_frame(row, frame, cut=original.cut)
            slot_row = self._mux_rows["slots"][slot_ordinal - 1]
            wire = self._mux_wire(master.parent, grant.slot)
            with self._lock:
                if self._terminal is not None:
                    return
                slot_row["wire"] = wire
            self.sample_mux_credits()

        self._mux_hook(original, "start", started)
        self._mux_hook(original, "read_frames", read)
        self._mux_hook(
            original, "close", lambda result: self._mux_cleanup(row, result, "VIEWER")
        )

    def _mux_master(self, original: Any, reservation: Any) -> None:
        from wso_core.tvt.local_media_mux_types import MasterLoginProof

        if not self._mux_once(original):
            return
        row = self._mux_row(
            "masters",
            reservation.master_id,
            login_proof="UNAVAILABLE",
            cleanup="RETAINED",
        )
        if row is None:
            return
        ordinal = row["ordinal"]
        with self._lock:
            self._mux_master_owners[ordinal] = (original, self._mux_probe)

        def started(result: Any, *args: Any, **kwargs: Any) -> None:
            if type(result) is not MasterLoginProof or not all(
                (
                    result.login_accepted,
                    result.same_original_session,
                    result.serial_matched,
                    result.device_matched,
                    result.inventory_session_matched,
                )
            ):
                raise ValueError("login observation refused")
            with self._lock:
                if self._terminal is not None:
                    return
                row["login_proof"] = "VERIFIED_RETURN"
                row["login_elapsed_ms"] = self._mux_elapsed()

        def opened(result: Any, selection: Any, grant: Any, **kwargs: Any) -> None:
            if (
                result != grant.slot
                or type(selection.ordinal) is not int
                or not 0 <= selection.ordinal <= 4096
            ):
                raise ValueError("slot observation refused")
            slot_row = self._mux_row(
                "slots",
                grant.slot,
                master_ordinal=ordinal,
                channel_ordinal=selection.ordinal,
                wire={"ack": None, "media": None, "status": "UNAVAILABLE"},
            )
            if slot_row is not None:
                wire = self._mux_wire(original.parent, grant.slot)
                with self._lock:
                    if self._terminal is not None:
                        return
                    slot_row["wire"] = wire

        self._mux_hook(original, "start", started)
        self._mux_hook(original, "open_slot", opened)
        self._mux_hook(
            original,
            "prepare_viewer",
            lambda result, grant: self._mux_viewer(result, original, grant, ordinal),
        )
        self._mux_hook(
            original,
            "close",
            lambda result: self._mux_cleanup(
                row, result, "LAST_VIEWER_AND_DEVICE_EPOCH"
            ),
        )

    def _mux_dedicated(self, original: Any, registration: UUID) -> None:
        if not self._mux_once(original):
            return
        row = self._mux_row("dedicated", registration, cleanup="RETAINED")
        viewer = self._mux_attempt(
            registration,
            "main",
            dedicated_ordinal=None if row is None else row["ordinal"],
        )

        def started(result: Any, *args: Any, **kwargs: Any) -> None:
            # The returned original session has not yet been received/captured
            # by Core. Only its read method is instrumented, before that return.
            if not self._mux_once(result):
                return

            def read(frames: Any, **limits: Any) -> None:
                if type(frames) is not tuple:
                    raise ValueError("frame collection refused")
                if viewer is not None:
                    for frame in frames:
                        self._mux_frame(viewer, frame)
                self.sample_mux_credits()

            self._mux_hook(result, "read_frames", read)

        self._mux_hook(original, "start", started)
        self._mux_hook(
            original,
            "close_native",
            lambda result: self._mux_cleanup(row, result, "DEDICATED_NATIVE"),
        )
        self._mux_hook(
            original,
            "close_viewer",
            lambda result: self._mux_cleanup(viewer, result, "VIEWER"),
        )

    def wrap_mux_provider(self, provider: Any) -> Any:
        """Prepare facade only: return exact originals before Core captures them.

        binding_for, issued_receipt, all issuer objects and native child methods
        are never replaced. Repeated preparation never reinstalls a hook.
        """
        observer = self

        class Provider:
            def __getattr__(self, name: str) -> Any:
                return getattr(provider, name)

            def prepare_master(self, reservation: Any, original: Any) -> Any:
                result = provider.prepare_master(reservation, original)
                observer._mux_safe(lambda: observer._mux_master(result, reservation))
                return result

            def prepare_dedicated(
                self, lease: Any, scope: Any, original_budget: Any, registration: UUID
            ) -> Any:
                result = provider.prepare_dedicated(
                    lease, scope, original_budget, registration
                )
                observer._mux_safe(
                    lambda: observer._mux_dedicated(result, registration)
                )
                return result

        return Provider()

    def begin_source(self) -> Callable[[str, str], None]:
        """Called on the original synchronous start thread before native open.

        Its private thread context links provider and worker attempts without
        retaining leases, credentials or source objects in exported records.
        The callback does only bounded in-memory updates, never writer I/O.
        """
        started = self._clock()
        with self._lock:
            self._source_count += 1
            ordinal = self._source_count
            row: dict[str, Any] | None = None
            if ordinal <= self.limit and self._terminal is None:
                row = {
                    "source_attempt": ordinal,
                    "first_failure": None,
                    "milestones": [],
                    "transition_counts": dict.fromkeys(sorted(TRANSITION_EVENTS), 0),
                    "format_transitions": [],
                    "omitted_format_transitions": 0,
                }
                self._sources.append(row)
        self._source_context.ordinal = ordinal

        def record(stage: str, reason: str) -> None:
            if row is None:
                return
            try:
                with self._lock:
                    if self._terminal is not None:
                        return
                    if stage == "timestamp_failure":
                        metadata = timestamp_failure(reason)
                        if row["first_failure"] is None:
                            row["first_failure"] = {
                                "stage": "adapter",
                                "reason": "timestamp_invalid",
                                "elapsed_ms": max(
                                    0,
                                    min(
                                        2**31 - 1, int((self._clock() - started) * 1000)
                                    ),
                                ),
                                "timestamp": metadata,
                            }
                    elif stage == "transition":
                        if reason not in TRANSITION_EVENTS:
                            raise ValueError("observation enum refused")
                        row["transition_counts"][reason] = min(
                            2**31 - 1, row["transition_counts"][reason] + 1
                        )
                    elif stage == "transition_format":
                        change = transition_format(reason)
                        if len(row["format_transitions"]) < 16:
                            change["elapsed_ms"] = max(
                                0, min(2**31 - 1, int((self._clock() - started) * 1000))
                            )
                            row["format_transitions"].append(change)
                        else:
                            row["omitted_format_transitions"] = min(
                                2**31 - 1, row["omitted_format_transitions"] + 1
                            )
                    elif stage == "milestone":
                        if reason not in MILESTONES:
                            raise ValueError("observation enum refused")
                        if any(item["stage"] == reason for item in row["milestones"]):
                            return
                        elapsed = max(
                            0, min(2**31 - 1, int((self._clock() - started) * 1000))
                        )
                        row["milestones"].append(
                            {"stage": reason, "elapsed_ms": elapsed}
                        )
                    else:
                        if stage not in FAILURE_STAGES or reason not in FAILURE_REASONS:
                            raise ValueError("observation enum refused")
                        if row["first_failure"] is None:
                            elapsed = max(
                                0, min(2**31 - 1, int((self._clock() - started) * 1000))
                            )
                            row["first_failure"] = {
                                "stage": stage,
                                "reason": reason,
                                "elapsed_ms": elapsed,
                            }
            except BaseException:  # noqa: BLE001 -- observer cannot alter service.
                with self._lock:
                    self._failures += 1

        self._source_context.record = record
        return record

    def publish(self) -> None:
        try:
            if self.shared:
                self.sample_mux_credits()
            with self._publish_lock:
                with self._lock:
                    if self._terminal is not None:
                        return
                    value = self.snapshot()
                digest = snapshot_digest(value)
                self.write(value)
                with self._lock:
                    self._last_digest = digest
                    if value["stop_requested"] is True:
                        self._final_published = True
        except Exception:  # noqa: BLE001 -- no private error or observer failure escapes.
            with self._lock:
                self._failures += 1

    def start(self) -> None:
        def watch() -> None:
            while not self._stop.wait(1):
                self.publish()
            self.publish()

        self._thread = threading.Thread(
            target=watch, name="fixture-observation", daemon=True
        )
        try:
            self._thread.start()
        except Exception:  # noqa: BLE001 -- no resource owner depends on observation.
            self._thread = None
            with self._lock:
                self._failures += 1

    def close(self) -> dict[str, Any]:
        # The writer never publishes this decision. A late snapshot cannot
        # replace the original custodian's sticky result after the join bound.
        with self._close_lock:
            if self._terminal is not None:
                return dict(self._terminal)
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=0.2)
            with self._lock:
                settled = self._thread is not None and not self._thread.is_alive()
                if not settled and self._thread is not None:
                    self._failures += 1
                omitted = (
                    self._count
                    - len(self._attempts)
                    + self._source_count
                    - len(self._sources)
                    + self._mux_omitted
                )
                complete = (
                    settled
                    and self._final_published
                    and self._failures == 0
                    and omitted == 0
                    and self._omitted_peers == 0
                )
                self._terminal = {
                    "schema_version": 1,
                    "status": "COMPLETE" if complete else "FAILED",
                    "writer_settled": settled,
                    "observation_failures": self._failures,
                    "omitted_attempts": omitted,
                    "omitted_peers": self._omitted_peers,
                    "snapshot_sha256": self._last_digest,
                }
                return dict(self._terminal)

    def wrap_provider(self, provider: Any) -> Any:
        observer = self

        class ObservedProvider:
            def open_session(
                self, credentials: Any, selection: Any, **kwargs: Any
            ) -> Any:
                with observer._lock:
                    observer._count += 1
                    attempt = observer._count
                row = None
                if attempt <= observer.limit:
                    try:
                        digest = hashlib.sha256(credentials.to_encrypt_bytes()).digest()
                        with observer._lock:
                            if digest not in observer._recorders:
                                if len(observer._recorders) >= 2:
                                    raise ValueError("observation recorder bound")
                                observer._recorders[digest] = (
                                    len(observer._recorders) + 1
                                )
                            if (
                                type(selection.ordinal) is not int
                                or not 0 <= selection.ordinal <= 4096
                                or selection.stream not in {"main", "sub"}
                            ):
                                raise ValueError("observation selection refused")
                            row = {
                                "attempt": attempt,
                                "recorder_ordinal": observer._recorders[digest],
                                "channel_ordinal": selection.ordinal,
                                "requested_stream": selection.stream,
                                "outcome": "OPEN_PENDING",
                            }
                            source_attempt = getattr(
                                observer._source_context, "ordinal", None
                            )
                            if source_attempt is not None:
                                row["source_attempt"] = source_attempt
                            observer._attempts.append(row)
                    except Exception:  # noqa: BLE001 -- optional projection never changes open.
                        with observer._lock:
                            observer._failures += 1
                # The original provider owns all failure/cleanup paths.
                try:
                    session = provider.open_session(credentials, selection, **kwargs)
                except BaseException:
                    if row is not None:
                        with observer._lock:
                            row["outcome"] = "OPEN_FAILED"
                    raise
                if row is not None:
                    try:
                        authority = session._authority
                        frame = authority.frames[0]
                        metadata = first_media(
                            frame, selection.stream, authority.sub_stream_adaptation_off
                        )
                        identity = frame.identity
                        with observer._lock:
                            row.update(metadata, outcome="OPEN_RETURNED")
                            observer._bindings[
                                (
                                    identity.generation,
                                    identity.session,
                                    identity.channel,
                                    identity.task,
                                )
                            ] = attempt
                    except Exception:  # noqa: BLE001 -- return the exact original session.
                        with observer._lock:
                            row["outcome"] = "METADATA_UNAVAILABLE"
                            observer._failures += 1
                record = getattr(observer._source_context, "record", None)
                if record is not None:
                    record("milestone", "native_return")
                return session

        return ObservedProvider()

    def install_peer_observer(self, module: Any) -> None:
        observer = self
        original = module.LocalWebRtcSession

        class ObservedPeer(original):  # type: ignore[misc, valid-type]
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                try:
                    with observer._lock:
                        if len(observer._peers) < observer.limit:
                            binding = kwargs["binding"]
                            attempt = observer._bindings.pop(
                                (
                                    binding.generation,
                                    binding.owner,
                                    binding.channel,
                                    binding.task,
                                ),
                                None,
                            )
                            if attempt is None:
                                raise ValueError("observation correlation unavailable")
                            observer._peers.append(
                                {
                                    "peer_ordinal": len(observer._peers) + 1,
                                    "attempt": attempt,
                                    "counts": self.enable_observation(),
                                }
                            )
                        else:
                            observer._omitted_peers += 1
                except Exception:  # noqa: BLE001 -- construction already owns resources.
                    with observer._lock:
                        observer._failures += 1

        module.LocalWebRtcSession = ObservedPeer


if __name__ == "__main__":
    try:
        if len(sys.argv) != 4 or sys.argv[1] != "--caller":
            raise ValueError("observation invocation refused")
        print(json.dumps(windows_identity(sys.argv[3], int(sys.argv[2]))))
    except Exception:  # noqa: BLE001 -- caller sees fixed failure, never private state.
        sys.stderr.write("Observation identity unavailable.\n")
        sys.exit(1)
