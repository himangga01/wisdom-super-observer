"""Private bounded byte IPC; current() is evaluated only by the parent caller."""

from __future__ import annotations

import ctypes as ct
import json
import multiprocessing
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

MAX_MESSAGE = 65536
PURPOSES = frozenset(("prepare", "connect", "metadata", "send", "publish"))


class AuthorityError(ValueError):
    def __init__(self) -> None:
        super().__init__("Private inventory authority channel failed.")


def encode(value: dict[str, Any]) -> bytes:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    if not 0 < len(raw) <= MAX_MESSAGE:
        raise AuthorityError()
    return raw


def decode(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise AuthorityError()
            out[key] = value
        return out

    if type(raw) is not bytes or not 0 < len(raw) <= MAX_MESSAGE:
        raise AuthorityError()
    result: Any = None
    try:
        result = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        pass
    if type(result) is not dict:
        raise AuthorityError()
    return result


class RemoteAuthority:
    def __init__(self, connection: Any, generation: str, deadline: float) -> None:
        self.connection = connection
        self.generation, self.deadline = generation, deadline
        self.sequence = 0
        self._last = ""
        self.closed = False

    @classmethod
    def from_handle(
        cls, handle: int, generation: str, deadline: float
    ) -> RemoteAuthority:
        if os.name != "nt" or type(handle) is not int or handle <= 0:
            raise AuthorityError()
        from multiprocessing.connection import PipeConnection

        return cls(PipeConnection(handle), generation, deadline)

    def _time(self) -> None:
        if self.closed or time.monotonic() >= self.deadline:
            raise AuthorityError()

    def require(self, purpose: str) -> None:
        failed = False
        try:
            self._time()
            if (
                purpose not in PURPOSES
                or self.sequence >= 128
                or self._last == "publish"
            ):
                raise AuthorityError()
            self.sequence += 1
            self.connection.send_bytes(
                encode(
                    {
                        "type": "current",
                        "generation": self.generation,
                        "sequence": self.sequence,
                        "purpose": purpose,
                    }
                )
            )
            if not self.connection.poll(max(0, self.deadline - time.monotonic())):
                raise AuthorityError()
            answer = decode(self.connection.recv_bytes(MAX_MESSAGE))
            self._time()
            if (
                set(answer) != {"type", "generation", "sequence", "purpose", "allow"}
                or answer["type"] != "decision"
                or answer["generation"] != self.generation
                or type(answer["sequence"]) is not int
                or answer["sequence"] != self.sequence
                or answer["purpose"] != purpose
                or answer["allow"] is not True
            ):
                raise AuthorityError()
            self._last = purpose
        except Exception:  # noqa: BLE001 -- never retain supplier/pipe exception text
            failed = True
        if failed:
            self.close()
            raise AuthorityError()

    def publish(self, observation: bytes) -> None:
        self._time()
        if self._last != "publish":
            raise AuthorityError()
        self.connection.send_bytes(
            encode(
                {
                    "type": "observation",
                    "generation": self.generation,
                    "sequence": self.sequence,
                    "data": decode(observation),
                }
            )
        )
        self._last = "published"
        self._time()

    def close(self) -> None:
        self.closed = True
        self.connection.close()


class ParentAuthority:
    """No credentials or SQL callback are stored here or in the watchdog."""

    def __init__(self, deadline: float, cancel: threading.Event) -> None:
        self.deadline, self.cancel = deadline, cancel
        self.generation = ""
        self.connection: Any = None
        self.worker_connection: Any = None
        self.observation: bytes | None = None
        self.failure = ""
        self._expected = 1
        self._publish_sequence: int | None = None
        self._done = False
        self._peer_closed = False
        self._stop = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._watchdog_start_attempted = False
        self._next_poll = 0.0

    def deny(self, reason: str) -> bool:
        if not self.failure:
            self.failure = reason
        self._stop.set()
        return False

    def check(self, current: Callable[[], bool]) -> bool:
        if self.failure:
            return False
        if self.cancel.is_set():
            return self.deny("cancelled")
        if time.monotonic() >= self.deadline:
            return self.deny("deadline")
        permitted = False
        try:
            permitted = current() is True
        except BaseException:  # noqa: BLE001 -- fixed denial and original retirement
            permitted = False
        if self.cancel.is_set():
            return self.deny("cancelled")
        if time.monotonic() >= self.deadline:
            return self.deny("deadline")
        return True if permitted else self.deny("denied")

    def bind(self, generation: str) -> None:
        if self.generation or re.fullmatch(r"[a-f0-9]{32}", generation) is None:
            raise AuthorityError()
        self.generation = generation
        self.connection, self.worker_connection = multiprocessing.Pipe(duplex=True)

    def duplicate_to(self, child: Any) -> int:
        if os.name != "nt" or self.worker_connection is None:
            raise AuthorityError()
        kernel = ct.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ct.c_void_p
        kernel.DuplicateHandle.argtypes = [
            ct.c_void_p,
            ct.c_void_p,
            ct.c_void_p,
            ct.c_void_p,
            ct.c_uint32,
            ct.c_int,
            ct.c_uint32,
        ]
        kernel.DuplicateHandle.restype = ct.c_int
        duplicate = ct.c_void_p()
        if not kernel.DuplicateHandle(
            kernel.GetCurrentProcess(),
            self.worker_connection.fileno(),
            int(child._handle),
            ct.byref(duplicate),
            0,
            False,
            2,
        ):
            raise AuthorityError()
        self.worker_connection.close()
        self.worker_connection = None
        assert duplicate.value is not None
        return duplicate.value

    def start_watchdog(self, stop_original: Callable[[], None]) -> None:
        def watch() -> None:
            while not self._stop.wait(0.01):
                if self.cancel.is_set():
                    self.deny("cancelled")
                elif time.monotonic() >= self.deadline:
                    self.deny("deadline")
            try:
                stop_original()
            except BaseException:  # noqa: BLE001 -- caller retains same original owner
                return

        self._watchdog = threading.Thread(target=watch, daemon=False)
        self._watchdog_start_attempted = True
        self._watchdog.start()

    def tick(self, current: Callable[[], bool]) -> bool:
        if self.cancel.is_set() or time.monotonic() >= self.deadline:
            return self.check(current)
        if time.monotonic() >= self._next_poll:
            self._next_poll = time.monotonic() + 0.1
            if not self.check(current):
                return False
        return self.pump(current)

    def pump(self, current: Callable[[], bool]) -> bool:
        if self.failure:
            return False
        try:
            if self._peer_closed:
                return True
            if self.connection is None:
                return True
            try:
                readable = self.connection.poll(0)
            except BrokenPipeError as error:
                # Windows PeekNamedPipe reports the peer's clean close here,
                # before recv_bytes can translate it to EOFError. Only an
                # already accepted publication may finish this authority pipe.
                if (
                    os.name == "nt"
                    and error.winerror == 109
                    and self._done
                    and self.observation is not None
                ):
                    self._peer_closed = True
                    return True
                raise
            if not readable:
                return True
            try:
                raw = self.connection.recv_bytes(MAX_MESSAGE)
            except EOFError:
                if self._done:
                    self._peer_closed = True
                    return True
                raise
            message = decode(raw)
            if self._done or message.get("generation") != self.generation:
                raise AuthorityError()
            if message.get("type") == "current":
                if (
                    set(message) != {"type", "generation", "sequence", "purpose"}
                    or type(message["sequence"]) is not int
                    or message["sequence"] != self._expected
                    or self._expected > 128
                    or message["purpose"] not in PURPOSES
                    or self._publish_sequence is not None
                ):
                    raise AuthorityError()
                self._expected += 1
                allowed = self.check(current)
                self.connection.send_bytes(
                    encode(
                        {
                            "type": "decision",
                            "generation": self.generation,
                            "sequence": message["sequence"],
                            "purpose": message["purpose"],
                            "allow": allowed,
                        }
                    )
                )
                if allowed and message["purpose"] == "publish":
                    self._publish_sequence = message["sequence"]
                return allowed
            if (
                set(message) != {"type", "generation", "sequence", "data"}
                or message["type"] != "observation"
                or type(message["sequence"]) is not int
                or message["sequence"] != self._publish_sequence
                or self._publish_sequence is None
                or type(message["data"]) is not dict
            ):
                raise AuthorityError()
            if not self.check(current):
                return False
            self.observation = encode(message["data"])
            self._done = True
            return True
        except Exception:  # noqa: BLE001 -- fixed protocol boundary
            return self.deny("protocol")

    def close(self, timeout: float = 1) -> bool:
        self._stop.set()
        try:
            if self._watchdog is not None:
                if self._watchdog.ident is not None:
                    self._watchdog.join(timeout)
                    if self._watchdog.is_alive():
                        return False
                elif self._watchdog_start_attempted:
                    return False
                self._watchdog = None
            for name in ("connection", "worker_connection"):
                connection = getattr(self, name)
                if connection is not None:
                    connection.close()
                    setattr(self, name, None)
            return True
        except BaseException:  # noqa: BLE001 -- preserve original IPC/thread custody
            return False
