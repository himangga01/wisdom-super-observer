"""Owned spawn-only helpers and bounded, non-pickle command transport."""

from __future__ import annotations

import json
import os
import select
import signal
import socket
import struct
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from billiard.context import SpawnProcess  # type: ignore[import-untyped]

from wso_core.storage import CHUNK_BYTES, IOBudget, StorageFailure

CONTROL_CAP = 65536
_slots = threading.BoundedSemaphore(2)
_registry_lock = threading.Lock()

if sys.platform == "win32":
    import msvcrt

    from billiard import context, reduction, spawn  # type: ignore[import-untyped]
    from billiard.compat import _winapi  # type: ignore[import-untyped]
    from billiard.popen_spawn_win32 import (  # type: ignore[import-untyped]
        Popen as WindowsPopen,
    )

    def _windows_spawn_main(parent_pid: int, pipe_handle: int) -> None:
        """Duplicate the exact owned bootstrap descriptor without stealing it."""
        quiet_child()
        parent_handle = _winapi.OpenProcess(
            _winapi.PROCESS_DUP_HANDLE, False, parent_pid
        )
        try:
            read_handle = _winapi.DuplicateHandle(
                parent_handle,
                pipe_handle,
                _winapi.GetCurrentProcess(),
                0,
                False,
                _winapi.DUPLICATE_SAME_ACCESS,
            )
        finally:
            _winapi.CloseHandle(parent_handle)
        descriptor = msvcrt.open_osfhandle(read_handle, os.O_RDONLY)
        sys.exit(spawn._main(descriptor))

    class _WindowsSpawnPopen(WindowsPopen):  # type: ignore[misc]
        """Billiard socket reduction with a direct Windows interpreter handle.

        CPython's Windows venv executable redirects to the base interpreter.
        Launch the base interpreter as multiprocessing does, retaining the
        actual helper handle and preserving venv resolution in its environment.
        """

        def __init__(self, process_obj: Any) -> None:
            prep_data = spawn.get_preparation_data(process_obj._name)
            rhandle, whandle = _winapi.CreatePipe(None, 0)
            wfd = msvcrt.open_osfhandle(whandle, 0)
            executable = spawn.get_executable()
            command = spawn.get_command_line(
                parent_pid=os.getpid(), pipe_handle=rhandle
            )
            # Keep the parent's read handle owned until native settlement,
            # even if cancellation kills the child before descriptor uptake.
            command[command.index("-c") + 1] = (
                "from wso_core.asset_process import _windows_spawn_main; "
                f"_windows_spawn_main(parent_pid={os.getpid()},pipe_handle={rhandle})"
            )
            environment = None
            base_executable = getattr(sys, "_base_executable", sys.executable)
            if sys.executable != base_executable and executable == sys.executable:
                executable = base_executable
                command[0] = executable
                environment = os.environ.copy()
                environment["__PYVENV_LAUNCHER__"] = sys.executable
            command_line = " ".join(f'"{part}"' for part in command)
            with open(wfd, "wb", closefd=True) as to_child:
                try:
                    hp, ht, pid, _tid = _winapi.CreateProcess(
                        executable,
                        command_line,
                        None,
                        None,
                        False,
                        0,
                        environment,
                        None,
                        None,
                    )
                    _winapi.CloseHandle(ht)
                except BaseException:
                    _winapi.CloseHandle(rhandle)
                    raise
                self.pid, self.returncode = pid, None
                self._handle, self.sentinel = hp, int(hp)
                self._read_handle = rhandle
                # Retain exact custody before serialization can be interrupted.
                process_obj._popen = self
                process_obj._sentinel = self.sentinel
                context.set_spawning_popen(self)
                try:
                    reduction.dump(prep_data, to_child)
                    reduction.dump(process_obj, to_child)
                finally:
                    context.set_spawning_popen(None)

        def close(self) -> None:
            try:
                if self._read_handle is not None:
                    _winapi.CloseHandle(self._read_handle)
                    self._read_handle = None
            finally:
                super().close()


class OwnedProcess(Protocol):
    @property
    def pid(self) -> int | None: ...
    @property
    def exitcode(self) -> int | None: ...
    def start(self) -> None: ...
    def is_alive(self) -> bool: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def join(self, timeout: float) -> None: ...
    def close(self) -> None: ...


class _OwnedSpawnProcess(SpawnProcess):  # type: ignore[misc]
    """Explicit Billiard spawn, including exact-child hard termination.

    Billiard admits daemon-parent children and owns socket reduction on both
    platforms. Its Process lacks stdlib's kill operation; do not silently
    weaken the existing terminate/join/kill/join settlement sequence.
    """

    def __getstate__(self) -> dict[str, Any]:
        # Native parent custody is retained during serialization, but never
        # transported to the child as a live parent handle or sentinel.
        state: dict[str, Any] = self.__dict__.copy()
        state["_popen"] = None
        state.pop("_sentinel", None)
        return state

    @staticmethod
    def _Popen(process_obj: Any) -> Any:
        if sys.platform == "win32":
            return _WindowsSpawnPopen(process_obj)
        from billiard.popen_spawn_posix import Popen  # type: ignore[import-untyped]

        return Popen(process_obj)

    def kill(self) -> None:
        assert self._parent_pid == os.getpid() and self._popen is not None
        if sys.platform == "win32":
            # Billiard terminate uses the retained native process handle.
            self._popen.terminate()
        elif self.exitcode is None:
            # This exact unreaped direct child is retained by the registry.
            pid = self.pid
            assert type(pid) is int and pid > 0
            os.kill(pid, signal.SIGKILL)


_unreaped: dict[int, OwnedProcess] = {}
_active: set[int] = set()
_owned: dict[int, OwnedProcess] = {}


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


def _reap(process: OwnedProcess, deadline: float) -> bool:
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


def _ownership_key(process: OwnedProcess) -> int:
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
    process: OwnedProcess | None = None
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
        process = _OwnedSpawnProcess(target=target, args=(child,), daemon=False)
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
