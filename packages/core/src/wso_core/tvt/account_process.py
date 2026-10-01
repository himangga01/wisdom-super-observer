"""Private account HTTPS in an owned, single-use child per request.

The wall-clock budget includes serialization, process startup, IPC and network
work, with a final reserve for kill/wait/channel settlement. This assumes a
functioning OS process-create/kill API and scheduler; it cannot bound a stalled
OS syscall. One inflight request per instance; unproven settlement permanently
closes admission. Caller authority is a prerequisite, never created here.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, cast

from .account_protocol import (
    KNOWN_PATHS,
    MAX_BODY_BYTES,
    AccountRequest,
    AccountResponse,
    parse_response,
    private_json,
)
from .account_transport import (
    AccountTransportError,
    HttpsAccountTransport,
    OriginPolicy,
)

_INVALID = "Invalid account process configuration."
_FAILED = "Account process transport failed."
_DEADLINE = "Account process deadline exceeded."
_IPC_OVERHEAD = 8192


class AccountProcessError(AccountTransportError):
    """Fixed public failure text; no child exception or payload retained."""


def _seconds(value: object) -> float:
    if type(value) not in (int, float):
        raise AccountProcessError(_INVALID)
    numeric = cast(int | float, value)
    if not 0 < numeric <= 60:
        raise AccountProcessError(_INVALID)
    number = float(numeric)
    if not math.isfinite(number):
        raise AccountProcessError(_INVALID)
    return number


def _wire_limit(body_limit: int) -> int:
    return 4 * ((body_limit + 2) // 3) + _IPC_OVERHEAD


def _encode(value: dict[str, object]) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("ascii")


def _worker_command() -> list[str]:
    # -I/-S remove Python env, site hooks and cwd/module-search inheritance.
    # Only this trusted package path appears in argv; all private bytes use IPC.
    source = str(Path(__file__).resolve().parents[2])
    code = (
        f"import sys;sys.path.insert(0,{source!r});"
        "from wso_core.tvt.account_process import _child_main;_child_main()"
    )
    # Windows venv executables are redirectors: their Popen PID is not the
    # interpreter. This worker needs stdlib only, so launch the base executable
    # directly and retain the actual worker's process handle for cancellation.
    executable = (
        getattr(sys, "_base_executable", None) if os.name == "nt" else sys.executable
    )
    if not isinstance(executable, str) or not executable:
        raise AccountProcessError(_INVALID)
    return [executable, "-I", "-S", "-c", code]


def _environment() -> dict[str, str]:
    # Windows requires SystemRoot for some OS facilities. No proxy, CA override,
    # Python hooks, application credentials or arbitrary parent env is inherited.
    if os.name == "nt":
        root = os.environ.get("SystemRoot")
        if root:
            return {"SystemRoot": root}
    return {}


@dataclass(repr=False)
class _Exchange:
    process: subprocess.Popen[bytes]
    payload: bytes
    reply_limit: int
    output: bytearray = field(default_factory=bytearray)
    wrote: threading.Event = field(default_factory=threading.Event)
    read: threading.Event = field(default_factory=threading.Event)
    failed: threading.Event = field(default_factory=threading.Event)

    def write_input(self) -> None:
        stream = cast(BinaryIO, self.process.stdin)
        try:
            remaining = memoryview(self.payload)
            while remaining:
                written = os.write(stream.fileno(), remaining)
                if written <= 0:
                    raise OSError
                remaining = remaining[written:]
        except (OSError, ValueError):
            self.failed.set()
        finally:
            stream.close()
            self.wrote.set()

    def read_output(self) -> None:
        stream = cast(BinaryIO, self.process.stdout)
        try:
            while True:
                chunk = os.read(
                    stream.fileno(), min(8192, self.reply_limit + 1 - len(self.output))
                )
                if not chunk:
                    break
                self.output.extend(chunk)
                if len(self.output) > self.reply_limit:
                    self.failed.set()
                    break
        except (OSError, ValueError):
            self.failed.set()
        finally:
            stream.close()
            self.read.set()


def _settle(
    process: subprocess.Popen[bytes], threads: list[threading.Thread], deadline: float
) -> bool:
    """Only this Popen handle is killed/waited; never a PID-name/global sweep."""
    try:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=max(0, deadline - time.monotonic()))
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            return False
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()
        return process.poll() is not None
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        return False


def _decode_reply(raw: bytes, body_limit: int) -> AccountResponse:
    failed = False
    try:
        value = private_json(raw)
        if set(value) != {"status", "body"} or type(value["body"]) is not str:
            raise ValueError
        body = base64.b64decode(value["body"], validate=True)
        if len(body) > body_limit:
            raise ValueError
        result = parse_response(
            cast(int, value["status"]), body, max_body_bytes=body_limit
        )
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        failed = True
    if failed:
        raise AccountProcessError(_FAILED) from None
    return result


class ProcessAccountTransport:
    """AccountTransport implementation; raw response remains private.

    `timeout_seconds` is the total budget, not a fresh per-stage timeout.
    `settlement_seconds` is reserved inside it, so network work gets less time.
    close() cancels active work through its supervisor and closes new admission.
    The active send() owns bounded resource settlement before it returns.
    """

    def __init__(
        self,
        policy: OriginPolicy,
        *,
        region: str,
        origin: str,
        timeout_seconds: float = 10,
        settlement_seconds: float = 0.5,
        max_body_bytes: int = 65_536,
    ) -> None:
        self._timeout = _seconds(timeout_seconds)
        self._reserve = _seconds(settlement_seconds)
        if (
            self._reserve >= self._timeout
            or self._reserve > 3
            or type(max_body_bytes) is not int
            or not 1 <= max_body_bytes <= MAX_BODY_BYTES
        ):
            raise AccountProcessError(_INVALID)
        invalid = False
        try:
            self._origin = policy.resolve(region, origin).url
        except (ValueError, TypeError, AttributeError):
            invalid = True
        if invalid:
            raise AccountProcessError(_INVALID) from None
        self._region = region
        self._max_body = max_body_bytes
        self._lock = threading.Lock()
        self._busy = False
        self._closed = False
        self._cancel = threading.Event()
        # Keep exact ownership if settlement fails; never reuse this instance.
        self._unsettled: (
            tuple[subprocess.Popen[bytes], list[threading.Thread]] | None
        ) = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._cancel.set()

    def send(self, request: AccountRequest) -> AccountResponse:
        deadline = time.monotonic() + self._timeout
        work_deadline = deadline - self._reserve
        if (
            type(request) is not AccountRequest
            or type(request.path) is not str
            or request.path not in KNOWN_PATHS
            or type(request.body) is not bytes
            or len(request.body) > MAX_BODY_BYTES
        ):
            raise AccountProcessError("Invalid account process request.")
        with self._lock:
            if self._closed or self._busy:
                raise AccountProcessError(
                    "Account process admission is closed or busy."
                )
            self._busy = True
        process: subprocess.Popen[bytes] | None = None
        threads: list[threading.Thread] = []
        raw = b""
        result: AccountResponse | None = None
        failure: str | None = None
        try:
            payload = _encode(
                {
                    "region": self._region,
                    "origin": self._origin,
                    "timeout": self._timeout - self._reserve,
                    "limit": self._max_body,
                    "path": request.path,
                    "body": base64.b64encode(request.body).decode("ascii"),
                }
            )
            if len(payload) > _wire_limit(MAX_BODY_BYTES):
                failure = _FAILED
            elif self._cancel.is_set():
                failure = "Account process request cancelled."
            elif time.monotonic() >= work_deadline:
                failure = _DEADLINE
            else:
                process = subprocess.Popen(
                    _worker_command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    env=_environment(),
                    cwd=str(Path(__file__).resolve().parent),
                    bufsize=0,
                    creationflags=(
                        getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        if os.name == "nt"
                        else 0
                    ),
                )
                exchange = _Exchange(process, payload, _wire_limit(self._max_body))
                for name, target in (
                    ("write", exchange.write_input),
                    ("read", exchange.read_output),
                ):
                    thread = threading.Thread(
                        target=target,
                        name=f"account-process-{process.pid}-{name}",
                        daemon=True,
                    )
                    thread.start()
                    threads.append(thread)
                while True:
                    if self._cancel.is_set():
                        failure = "Account process request cancelled."
                        break
                    if exchange.failed.is_set():
                        failure = _FAILED
                        break
                    remaining = work_deadline - time.monotonic()
                    if remaining <= 0:
                        failure = _DEADLINE
                        break
                    status = process.poll()
                    if (
                        status is not None
                        and exchange.wrote.is_set()
                        and exchange.read.is_set()
                    ):
                        if status == 0:
                            raw = bytes(exchange.output)
                        else:
                            failure = _FAILED
                        break
                    self._cancel.wait(min(0.01, remaining))
                if failure is None:
                    result = _decode_reply(raw, self._max_body)
        except (OSError, ValueError, RuntimeError, TypeError):
            failure = _FAILED
        finally:
            settled = process is None or _settle(process, threads, deadline)
            with self._lock:
                if not settled:
                    self._closed = True
                    self._cancel.set()
                    assert process is not None
                    self._unsettled = (process, threads)
                    failure = "Account process settlement could not be proved."
                elif self._cancel.is_set():
                    failure = "Account process request cancelled."
                elif time.monotonic() >= deadline:
                    failure = _DEADLINE
                # Outcome and completion linearize against close() under the
                # admission lock, after decoding and exact resource settlement.
                self._busy = False
        if failure is not None:
            raise AccountProcessError(failure) from None
        assert result is not None
        return result


def _child_main() -> None:
    """Private fixed worker entry point; no pickle, eval, plugin or callable input."""
    reply: dict[str, object] = {"error": "transport"}
    try:
        raw = sys.stdin.buffer.read(_wire_limit(MAX_BODY_BYTES) + 1)
        if len(raw) > _wire_limit(MAX_BODY_BYTES):
            raise ValueError
        value = private_json(raw)
        if set(value) != {"region", "origin", "timeout", "limit", "path", "body"}:
            raise ValueError
        region, origin, path, encoded = (
            value[key] for key in ("region", "origin", "path", "body")
        )
        if any(type(item) is not str for item in (region, origin, path, encoded)):
            raise ValueError
        body = base64.b64decode(cast(str, encoded), validate=True)
        if len(body) > MAX_BODY_BYTES or path not in KNOWN_PATHS:
            raise ValueError
        region, origin = cast(str, region), cast(str, origin)
        transport = HttpsAccountTransport(
            OriginPolicy({region: frozenset({origin})}),
            region=region,
            origin=origin,
            timeout_seconds=_seconds(value["timeout"]),
            max_body_bytes=cast(int, value["limit"]),
        )
        result = transport.send(AccountRequest(cast(str, path), body))
        reply = {
            "status": result.http_status,
            "body": base64.b64encode(result.private_body).decode("ascii"),
        }
    except Exception:  # noqa: BLE001 -- fixed sanitized output at process boundary
        # No traceback, exception value or context is sent across the boundary.
        reply = {"error": "transport"}
    output = _encode(reply)
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()
