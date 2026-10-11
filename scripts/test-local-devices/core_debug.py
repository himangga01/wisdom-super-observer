"""Opt-in structural exception locations; no message, locals or argument access."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

from wso_core.tvt.local_service import LOCAL_DEVICE_FAILURES, LocalDeviceFailure

SOURCES = {
    "mux_service": "packages/core/src/wso_core/tvt/local_media_mux_service.py",
    "mux_admission": "packages/core/src/wso_core/tvt/local_media_mux_admission.py",
    "local_admission": "packages/core/src/wso_core/tvt/local_admission.py",
    "media_admission": "packages/core/src/wso_core/tvt/local_media_admission.py",
    "mux_provider": "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py",
    "media_worker": "services/tvt-media/src/wso_tvt_media/worker.py",
}
FUNCTIONS = {
    "mux_service": frozenset(
        {
            "start",
            "attach_dedicated",
            "current",
            "lease",
            "close",
            "settle_focus",
            "_current_dedicated",
            "_dedicated_retained",
            "_close_dedicated",
            "_active",
            "_lease",
        }
    ),
    "mux_admission": frozenset(
        {
            "prepare_viewer",
            "register_dedicated",
            "prepare_dedicated",
            "current_focus",
            "settle_focus",
            "_selection",
            "_sql",
            "_dedicated_owner",
            "_lease",
            "_known_lease",
        }
    ),
    "local_admission": frozenset({"checked"}),
    "media_admission": frozenset(
        {"activate", "current", "redeem", "view", "_known_lease"}
    ),
    "mux_provider": frozenset({"prepare_dedicated", "start", "current"}),
    "media_worker": frozenset({"start", "_prepare"}),
}
FIELDS = frozenset(
    {
        "schema_version",
        "action",
        "code",
        "status",
        "exception",
        "elapsed_ms",
        "frames",
        "chain_count",
        "truncated",
    }
)


def checked_record(value: object) -> bytes:
    if type(value) is not dict or set(value) != FIELDS:
        raise ValueError("invalid structural diagnostic")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["action"]) is not str
        or value["action"] != "executor_start"
        or type(value["exception"]) is not str
        or value["exception"] not in {"LocalDeviceFailure", "unexpected"}
        or type(value["code"]) is not str
        or type(value["status"]) is not int
        or (value["code"], value["status"])
        not in ({("UNEXPECTED", 500)} | set(LOCAL_DEVICE_FAILURES.items()))
        or type(value["elapsed_ms"]) is not int
        or not 0 <= value["elapsed_ms"] <= 60000
        or type(value["chain_count"]) is not int
        or not 1 <= value["chain_count"] <= 4
        or type(value["truncated"]) is not bool
        or type(value["frames"]) is not list
        or len(value["frames"]) > 8
    ):
        raise ValueError("invalid structural diagnostic")
    for frame in value["frames"]:
        if (
            type(frame) is not dict
            or set(frame) != {"module", "function", "line", "chain"}
            or type(frame["module"]) is not str
            or frame["module"] not in FUNCTIONS
            or type(frame["function"]) is not str
            or frame["function"] not in FUNCTIONS[frame["module"]]
            or type(frame["line"]) is not int
            or not 1 <= frame["line"] <= 20000
            or type(frame["chain"]) is not int
            or not 0 <= frame["chain"] < value["chain_count"]
        ):
            raise ValueError("invalid structural diagnostic frame")
    raw = (json.dumps(value, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
        "ascii"
    )
    if len(raw) > 2048:
        raise ValueError("structural diagnostic too large")
    return raw


def project_failure(
    error: BaseException, *, root: Path, elapsed_ms: int
) -> dict[str, Any]:
    paths = {
        os.path.normcase(os.path.abspath(root / path)): label
        for label, path in SOURCES.items()
    }
    frames: list[dict[str, Any]] = []
    seen: set[int] = set()
    current: BaseException | None = error
    count = inspected = 0
    truncated = False
    while current is not None and count < 4:
        if id(current) in seen:
            truncated = True
            break
        seen.add(id(current))
        trace = current.__traceback__
        while trace is not None and inspected < 8:
            inspected += 1
            code = trace.tb_frame.f_code
            label = paths.get(os.path.normcase(os.path.abspath(code.co_filename)))
            if (
                label is not None
                and code.co_name in FUNCTIONS[label]
                and 1 <= trace.tb_lineno <= 20000
            ):
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
        current = (
            current.__cause__ if current.__cause__ is not None else current.__context__
        )
    truncated = truncated or current is not None
    public_code, public_status, exception = "UNEXPECTED", 500, "unexpected"
    if (
        type(error) is LocalDeviceFailure
        and LOCAL_DEVICE_FAILURES.get(error.code) == error.status
    ):
        public_code, public_status, exception = (
            error.code,
            error.status,
            "LocalDeviceFailure",
        )
    record: dict[str, Any] = {
        "schema_version": 1,
        "action": "executor_start",
        "code": public_code,
        "status": public_status,
        "exception": exception,
        "elapsed_ms": min(60000, max(0, elapsed_ms)),
        "frames": frames,
        "chain_count": count,
        "truncated": truncated,
    }
    checked_record(record)
    return record


def wrap_start(
    original: Callable[..., Any], sink: Callable[[dict[str, Any]], None], *, root: Path
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        started = None
        try:
            started = time.monotonic()
        except BaseException:  # noqa: BLE001, S110 - preserve original call
            pass
        try:
            return original(*args, **kwargs)
        except BaseException as error:
            try:
                sink(
                    project_failure(
                        error,
                        root=root,
                        elapsed_ms=0
                        if started is None
                        else int((time.monotonic() - started) * 1000),
                    )
                )
            except BaseException:  # noqa: BLE001, S110 - preserve original failure
                pass
            raise

    return wrapped


class BoundedCoreDiagnostics:
    def __init__(self, writer: Callable[[bytes], None]) -> None:
        self._writer = writer
        self._lock = Lock()
        self._count = self._bytes = 0

    def __call__(self, record: dict[str, Any]) -> None:
        try:
            raw = checked_record(record)
            with self._lock:
                if self._count >= 128 or self._bytes + len(raw) > 65536:
                    return
                self._count += 1
                self._bytes += len(raw)
                self._writer(raw)
        except BaseException:  # noqa: BLE001 - optional writer cannot change results
            return
