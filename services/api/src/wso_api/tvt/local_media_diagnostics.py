"""Optional bounded structural diagnostics. Never serialize request data/errors."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from threading import Lock
from typing import Any, cast

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from wso_core.tvt.local_service import LOCAL_DEVICE_FAILURES, LocalDeviceFailure

from wso_api.auth import AuthFailure

PHASES = frozenset(
    {
        "route",
        "auth",
        "query",
        "body",
        "handler",
        "mode",
        "worker",
        "tenant",
        "ticket",
        "rpc",
        "response",
    }
)
ROUTES = frozenset(
    {
        "start",
        "offer",
        "stop",
        "playing",
        "heartbeat",
        "state",
        "wall",
        "wall_heartbeat",
        "wall_stop",
        "focus_settle",
        "focus",
        "other",
    }
)
EXCEPTIONS = frozenset(
    {
        "none",
        "LocalDeviceFailure",
        "AuthFailure",
        "RequestValidationError",
        "HTTPException",
        "unexpected",
    }
)
CODES = frozenset(LOCAL_DEVICE_FAILURES) | {
    "OK",
    "AUTH_REJECTED",
    "VALIDATION_REJECTED",
    "HTTP_REJECTED",
    "UNEXPECTED",
}
FIELDS = frozenset(
    {
        "schema_version",
        "route",
        "phase",
        "completed",
        "shared",
        "stream",
        "wall_present",
        "focus_present",
        "status",
        "code",
        "exception",
        "elapsed_ms",
    }
)


def checked_record(value: object) -> bytes:
    """Closed fields/enums and exact types block arbitrary strings and identifiers."""
    if type(value) is not dict or set(value) != FIELDS:
        raise ValueError("invalid diagnostic record")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["route"]) is not str
        or value["route"] not in ROUTES
        or type(value["phase"]) is not str
        or value["phase"] not in PHASES
        or type(value["completed"]) is not list
        or len(value["completed"]) > len(PHASES)
        or any(
            type(phase) is not str or phase not in PHASES
            for phase in value["completed"]
        )
        or any(
            type(value[key]) is not bool
            for key in ("shared", "wall_present", "focus_present")
        )
        or type(value["stream"]) is not str
        or value["stream"] not in {"main", "sub", "unknown"}
        or type(value["status"]) is not int
        or not 100 <= value["status"] <= 599
        or type(value["elapsed_ms"]) is not int
        or not 0 <= value["elapsed_ms"] <= 60000
        or type(value["code"]) is not str
        or value["code"] not in CODES
        or type(value["exception"]) is not str
        or value["exception"] not in EXCEPTIONS
    ):
        raise ValueError("invalid diagnostic record")
    raw = (json.dumps(value, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
        "ascii"
    )
    if len(raw) > 1024:
        raise ValueError("diagnostic record too large")
    return raw


class BoundedMediaDiagnostics:
    """Serialized writes; caps count and attempted bytes even when writer fails."""

    def __init__(self, writer: Callable[[bytes], None]) -> None:
        self._writer = writer
        self._lock = Lock()
        self._count = self._bytes = 0

    def __call__(self, value: dict[str, Any]) -> None:
        try:
            raw = checked_record(value)
            with self._lock:
                if self._count >= 128 or self._bytes + len(raw) > 65536:
                    return
                self._count += 1
                self._bytes += len(raw)
                self._writer(raw)
        except BaseException:  # noqa: BLE001 - optional writer cannot change results
            return


class MediaDiagnostic:
    def __init__(self, request: Any, template: str) -> None:
        self._sink = getattr(
            request.app.state, "tvt_local_media_diagnostics_sink", None
        )
        self._started = time.monotonic()
        actions = {
            "/api/v1/tvt/live-walls/{wall_id}/focus-reservations/{reference_id}/settle": "focus_settle",
            "/api/v1/tvt/live-walls/{wall_id}/heartbeat": "wall_heartbeat",
            "/api/v1/tvt/live-walls/{wall_id}/stop": "wall_stop",
        }
        route = actions.get(template, "other")
        if template in actions:
            pass
        elif template == "/api/v1/tvt/live-sessions":
            route = "start"
        elif "/live-walls" in template:
            route = "wall"
        elif "/focus-reservations" in template:
            route = "focus"
        elif template.endswith("/webrtc-offer"):
            route = "offer"
        else:
            for suffix in ("stop", "playing", "heartbeat"):
                if template.endswith("/" + suffix):
                    route = suffix
                    break
            else:
                if template.endswith("/{lease_id}"):
                    route = "state"
        self._record: dict[str, Any] = {
            "schema_version": 1,
            "route": route,
            "phase": "route",
            "completed": [],
            "shared": getattr(
                request.app.state, "tvt_local_media_shared_enabled", False
            )
            is True,
            "stream": "unknown",
            "wall_present": False,
            "focus_present": False,
            "status": 500,
            "code": "UNEXPECTED",
            "exception": "unexpected",
            "elapsed_ms": 0,
        }

    def phase(self, phase: str) -> None:
        if phase in PHASES:
            self._record["phase"] = phase

    def complete(self) -> None:
        phase = self._record["phase"]
        if phase not in self._record["completed"]:
            self._record["completed"].append(phase)

    def mode(self, body: Any) -> None:
        from wso_contracts.tvt.local_media import LocalLiveRequest

        self.phase("mode")
        if type(body) is LocalLiveRequest:
            self._record["stream"] = (
                body.stream if body.stream in {"main", "sub"} else "unknown"
            )
            self._record["wall_present"] = body.wall_id is not None
            self._record["focus_present"] = body.focus_ref_id is not None

    def finish(self, status: int = 200, error: BaseException | None = None) -> None:
        if self._sink is None:
            return
        try:
            code, exception = "OK", "none"
            if type(error) is LocalDeviceFailure:
                status, code, exception = error.status, error.code, "LocalDeviceFailure"
            elif type(error) is AuthFailure:
                status, code, exception = error.status, "AUTH_REJECTED", "AuthFailure"
            elif isinstance(error, RequestValidationError):
                status, code, exception = (
                    422,
                    "VALIDATION_REJECTED",
                    "RequestValidationError",
                )
            elif isinstance(error, HTTPException):
                status, code, exception = (
                    error.status_code,
                    "HTTP_REJECTED",
                    "HTTPException",
                )
            elif error is not None:
                status, code, exception = 500, "UNEXPECTED", "unexpected"
            self._record.update(
                status=status,
                code=code,
                exception=exception,
                elapsed_ms=min(
                    60000, max(0, int((time.monotonic() - self._started) * 1000))
                ),
            )
            checked_record(self._record)
            self._sink(self._record)
        except BaseException:  # noqa: BLE001 - preserve original request/owner failure
            return


def diagnostic(request: Any) -> MediaDiagnostic:
    return cast(MediaDiagnostic, request.state.local_media_diagnostic)
