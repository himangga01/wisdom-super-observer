"""Owned spawn-only helpers and bounded, non-pickle command transport."""

from __future__ import annotations

import json
import multiprocessing
import os
import select
import socket
import struct
import threading
import time
from collections.abc import Callable
from multiprocessing.process import BaseProcess
from typing import Any

from wso_core.storage import CHUNK_BYTES, IOBudget, StorageFailure

CONTROL_CAP = 65536
_slots = threading.BoundedSemaphore(2)
_registry_lock = threading.Lock()
_unreaped: dict[int, BaseProcess] = {}
_active: set[int] = set()
_owned: dict[int, BaseProcess] = {}


def owned_helper_pids() -> tuple[int, ...]:
    """Diagnostic ownership inventory, never enumerate unrelated processes."""
    with _registry_lock:
        return tuple(sorted(_active | {pid for pid in _unreaped if pid > 0}))


def local_cleanup_complete() -> bool:
    """Terminal local cleanup health across S3 and decoder helpers, not remote state."""
    with _registry_lock:
        return not _unreaped


def quiet_child() -> None:
    import logging

    logging.disable(logging.CRITICAL)
    descriptor = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(descriptor, 1)
        os.dup2(descriptor, 2)
    finally:
        os.close(descriptor)


def _wait(sock: socket.socket, deadline: float, *, writing: bool) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise StorageFailure("DEADLINE")
    ready = select.select(
        [] if writing else [sock], [sock] if writing else [], [sock], remaining
    )
    if ready[2]:
        raise StorageFailure("UNAVAILABLE")
    if not (ready[1] if writing else ready[0]):
        raise StorageFailure("DEADLINE")


def send_bytes(sock: socket.socket, value: bytes, deadline: float) -> None:
    view = memoryview(value)
    while view:
        _wait(sock, deadline, writing=True)
        try:
            count = sock.send(view[:CHUNK_BYTES])
        except BlockingIOError:
            continue
        if count <= 0:
            raise StorageFailure("UNAVAILABLE")
        view = view[count:]


def receive_bytes(sock: socket.socket, count: int, deadline: float) -> bytes:
    result = bytearray()
    while len(result) < count:
        _wait(sock, deadline, writing=False)
        try:
            part = sock.recv(min(CHUNK_BYTES, count - len(result)))
        except BlockingIOError:
            continue
        if not part:
            raise StorageFailure("UNAVAILABLE")
        result.extend(part)
    return bytes(result)


def send_frame(sock: socket.socket, value: bytes, cap: int, deadline: float) -> None:
    if len(value) > cap:
        raise StorageFailure("LIMIT")
    send_bytes(sock, struct.pack("!I", len(value)), deadline)
    send_bytes(sock, value, deadline)


def receive_frame(sock: socket.socket, cap: int, deadline: float) -> bytes:
    count = struct.unpack("!I", receive_bytes(sock, 4, deadline))[0]
    if count > cap:
        raise StorageFailure("LIMIT")
    return receive_bytes(sock, count, deadline)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate control field")
        result[key] = value
    return result


def encode_control(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("ascii")


def decode_control(value: bytes) -> dict[str, Any]:
    result = json.loads(
        value,
        object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )
    if type(result) is not dict:
        raise ValueError("invalid control frame")
    return result


def require_eof(sock: socket.socket, deadline: float) -> None:
    _wait(sock, deadline, writing=False)
    if sock.recv(1):
        raise StorageFailure("INTEGRITY")


def child_request(
    sock: socket.socket, body_cap: int, seconds: float = 10
) -> tuple[dict[str, Any], bytes, float]:
    sock.setblocking(False)
    deadline = time.monotonic() + seconds
    control = decode_control(receive_frame(sock, CONTROL_CAP, deadline))
    body = receive_frame(sock, body_cap, deadline)
    require_eof(sock, deadline)
    return control, body, deadline


def child_response(
    sock: socket.socket, control: dict[str, Any], body: bytes, cap: int, deadline: float
) -> None:
    send_frame(sock, encode_control(control), CONTROL_CAP, deadline)
    send_frame(sock, body, cap, deadline)
    sock.shutdown(socket.SHUT_WR)


def _reap(process: BaseProcess, deadline: float) -> bool:
    def alive() -> bool | None:
        try:
            return process.is_alive()
        except BaseException:  # noqa: BLE001 - cleanup cannot lose ownership
            return None

    def invoke(action: Callable[[], None]) -> bool:
        try:
            action()
            return True
        except BaseException:  # noqa: BLE001 - continue owned escalation, never expose raw errors
            return False

    if alive() is not False:
        invoke(process.terminate)
    joined = invoke(lambda: process.join(max(0, min(1, deadline - time.monotonic()))))
    if joined and alive() is False:
        return True
    invoke(process.kill)
    joined = invoke(lambda: process.join(max(0, deadline - time.monotonic())))
    return joined and alive() is False


def _ownership_key(process: BaseProcess) -> int:
    try:
        pid = process.pid
        return pid if pid is not None else -id(process)
    except BaseException:  # noqa: BLE001 - retain exact handle even without a readable PID
        return -id(process)


def exchange_owned(
    target: Callable[[socket.socket], None],
    control: dict[str, Any],
    body: bytes,
    *,
    request_cap: int,
    response_cap: int,
    budget: IOBudget,
    mutating: bool,
    wall_seconds: float = 10,
) -> tuple[dict[str, Any], bytes]:
    started_at = time.monotonic()
    duration = min(
        wall_seconds, budget.call_timeout_seconds, budget.remaining_seconds()
    )
    if duration <= 2:
        raise StorageFailure("DEADLINE")
    if len(body) > request_cap:
        raise StorageFailure("LIMIT")
    encoded = encode_control(control)
    if len(encoded) > CONTROL_CAP:
        raise StorageFailure("LIMIT")
    if not _slots.acquire(blocking=False):
        raise StorageFailure("UNAVAILABLE")
    parent: socket.socket | None = None
    child: socket.socket | None = None
    process: BaseProcess | None = None
    start_attempted = False
    dispatched = False
    complete = False
    overall_deadline = min(budget.deadline_monotonic, started_at + duration)
    work_deadline = overall_deadline - 2
    failure: StorageFailure | None = None
    result: tuple[dict[str, Any], bytes] | None = None
    interruption: BaseException | None = None
    try:
        with _registry_lock:
            if _unreaped:
                raise StorageFailure("UNAVAILABLE")
        parent, child = socket.socketpair()
        parent.setblocking(False)
        process = multiprocessing.get_context("spawn").Process(
            target=target, args=(child,), daemon=False
        )
        # Establish ownership before startup can create a native child. A
        # partially initialized Process remains owned even without a known PID.
        with _registry_lock:
            _owned[id(process)] = process
        start_attempted = True
        process.start()
        assert process.pid is not None
        with _registry_lock:
            _active.add(process.pid)
        if time.monotonic() >= work_deadline:
            raise StorageFailure("DEADLINE")
        child.close()
        child = None
        dispatched = True  # Partial/uncertain delivery is conservatively unknown.
        send_frame(parent, encoded, CONTROL_CAP, work_deadline)
        send_frame(parent, body, request_cap, work_deadline)
        parent.shutdown(socket.SHUT_WR)
        response = decode_control(receive_frame(parent, CONTROL_CAP, work_deadline))
        data = receive_frame(parent, response_cap, work_deadline)
        require_eof(parent, work_deadline)
        process.join(max(0, work_deadline - time.monotonic()))
        if process.is_alive():
            raise StorageFailure("DEADLINE")
        if process.exitcode != 0:
            raise StorageFailure("UNAVAILABLE")
        if time.monotonic() >= work_deadline:
            raise StorageFailure("DEADLINE")
        complete = True
        result = response, data
    except StorageFailure as error:
        failure = StorageFailure(error.code, outcome_unknown=mutating and dispatched)
    except Exception:  # noqa: BLE001 - runtime/transport errors cross only as sanitized codes
        failure = StorageFailure("UNAVAILABLE", outcome_unknown=mutating and dispatched)
    except BaseException as error:  # noqa: BLE001 - rethrow cancellation only after ownership settles
        interruption = error
    finally:
        resources_closed = True
        if parent is not None:
            try:
                parent.close()
            except BaseException:  # noqa: BLE001 - still reap the exact owned child
                resources_closed = False
        if child is not None:
            try:
                child.close()
            except BaseException:  # noqa: BLE001 - still reap the exact owned child
                resources_closed = False
        if process is not None:
            key = _ownership_key(process)
            reaped = not start_attempted or complete or _reap(process, overall_deadline)
            if reaped:
                try:
                    process.close()
                except BaseException:  # noqa: BLE001 - unsettled handles remain terminally owned
                    reaped = False
            reaped = reaped and resources_closed
            with _registry_lock:
                _owned.pop(id(process), None)
                _active.discard(key)
                if not reaped:
                    _unreaped[key] = process
            if reaped:
                _slots.release()
            else:
                # Retain slot and exact owned handle; fail further admission.
                failure = StorageFailure(
                    "UNAVAILABLE", outcome_unknown=mutating and dispatched
                )
        else:
            _slots.release()
    if interruption is not None:
        raise interruption
    if failure is None and time.monotonic() >= overall_deadline:
        failure = StorageFailure("DEADLINE", outcome_unknown=mutating and dispatched)
    if failure is not None:
        raise failure
    assert result is not None
    return result
