"""Private Windows elementary-stream decoder; no TVT DLL or authority source.

An owner serializes this object with authority changes and later delivery. Native
work runs only in the originally owned worker, never a TVT callback process.
"""

from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, NoReturn, Self, SupportsIndex

_REQUEST = struct.Struct("!4sBBQ56sIIqII")
_RESPONSE = struct.Struct("!4sBQ56sI")
_FRAME = struct.Struct("!IIqII")
_CONFIG = struct.Struct("!4s9Id")


class DecodeError(ValueError):
    def __init__(self) -> None:
        super().__init__("private video decode failed")


class DecodeDenied(DecodeError):
    def __init__(self) -> None:
        ValueError.__init__(self, "private video decode authority denied")


class _Private:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: private>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("private decode value cannot be serialized")


class _Immutable(_Private):
    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("private decode value is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("private decode value is immutable")


def _int(value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise DecodeError()


class DecodeBinding(_Immutable):
    __slots__ = ("channel", "generation", "owner", "task")
    generation: int
    owner: bytes
    channel: bytes
    task: bytes

    def __init__(
        self, *, generation: int, owner: bytes, channel: bytes, task: bytes
    ) -> None:
        _int(generation, 1, 2**63 - 1)
        object.__setattr__(self, "generation", generation)
        for name, value in (("owner", owner), ("channel", channel), ("task", task)):
            if type(value) is not bytes or len(value) != 16 or value == bytes(16):
                raise DecodeError()
            object.__setattr__(self, name, value)

    def _wire(self) -> bytes:
        return struct.pack(
            "!Q16s16s16s", self.generation, self.owner, self.channel, self.task
        )


class ElementaryPacket(_Immutable):
    """One already delimited Annex B access unit, with proved PTS binding.

    Construct only after source routing/unencrypted status/framing validation.
    This class does not establish framing, identity, or access authority.
    """

    __slots__ = (
        "_data",
        "binding",
        "codec",
        "encrypted",
        "format",
        "generation",
        "height",
        "ordinal",
        "timestamp_us",
        "width",
    )
    _data: bytes
    binding: DecodeBinding
    codec: str
    format: str
    generation: int
    width: int
    height: int
    timestamp_us: int
    ordinal: int
    encrypted: bool

    def __init__(
        self,
        data: bytes,
        *,
        binding: DecodeBinding,
        codec: str,
        format: str,
        generation: int,
        width: int,
        height: int,
        timestamp_us: int,
        ordinal: int,
        encrypted: bool = False,
    ) -> None:
        values = locals()
        for name in self.__slots__:
            object.__setattr__(self, name, data if name == "_data" else values[name])


class PrivateRGBFrame(_Immutable):
    __slots__ = ("_rgb", "binding", "height", "ordinal", "timestamp_us", "width")
    binding: DecodeBinding
    width: int
    height: int
    timestamp_us: int
    ordinal: int
    _rgb: bytes

    def __init__(
        self,
        binding: DecodeBinding,
        width: int,
        height: int,
        timestamp_us: int,
        ordinal: int,
        rgb: bytes,
    ) -> None:
        for name, value in (
            ("binding", binding),
            ("width", width),
            ("height", height),
            ("timestamp_us", timestamp_us),
            ("ordinal", ordinal),
            ("_rgb", rgb),
        ):
            object.__setattr__(self, name, value)

    def private_rgb(self) -> bytes:
        """Trusted media caller only. Later delivery needs fresh authority."""
        return self._rgb


@dataclass(frozen=True, slots=True)
class DecodeLimits:
    max_width: int = 1920
    max_height: int = 1080
    max_packet_bytes: int = 1024 * 1024
    max_frame_bytes: int = 1920 * 1080 * 3
    max_frames: int = 256
    max_packets: int = 256
    max_input_bytes: int = 16 * 1024 * 1024
    max_output_bytes: int = 64 * 1024 * 1024
    max_response_frames: int = 16
    deadline_seconds: float = 30.0
    process_memory_bytes: int = 512 * 1024 * 1024

    def validate(self) -> None:
        for value, high in (
            (self.max_width, 4096),
            (self.max_height, 2160),
            (self.max_packet_bytes, 4 * 1024 * 1024),
            (self.max_frame_bytes, 4096 * 2160 * 3),
            (self.max_frames, 1024),
            (self.max_packets, 1024),
            (self.max_input_bytes, 64 * 1024 * 1024),
            (self.max_output_bytes, 256 * 1024 * 1024),
            (self.max_response_frames, 32),
        ):
            _int(value, 1, high)
        _int(self.process_memory_bytes, 128 * 1024 * 1024, 1024 * 1024 * 1024)
        if (
            type(self.deadline_seconds) not in (int, float)
            or not 0.05 <= self.deadline_seconds <= 60
        ):
            raise DecodeError()

    def _wire(self) -> bytes:
        return _CONFIG.pack(
            b"WDC1",
            self.max_width,
            self.max_height,
            self.max_packet_bytes,
            self.max_frame_bytes,
            self.max_frames,
            self.max_packets,
            self.max_input_bytes,
            self.max_output_bytes,
            self.max_response_frames,
            self.deadline_seconds,
        )


def _read(stream: IO[bytes], size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        data = stream.read(size - len(result))
        if not data:
            raise DecodeError()
        result.extend(data)
    return bytes(result)


def _job(process: subprocess.Popen[bytes], memory: int, custody: WindowsDecoder) -> int:
    """Assign exact original process to a bounded Windows Job before input."""
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_ws", ctypes.c_size_t),
            ("max_ws", ctypes.c_size_t),
            ("active", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IO(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "read_ops",
                "write_ops",
                "other_ops",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", IO),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t),
            ("peak_job", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise DecodeError()
    # Publish new handle ownership before any fallible configuration/assignment.
    custody._job_handle = int(handle)
    config = Extended()
    config.basic.flags = 0x2000 | 0x100 | 0x200 | 0x8
    config.basic.active = 1
    config.process_memory = memory
    config.job_memory = memory
    if not kernel.SetInformationJobObject(
        handle, 9, ctypes.byref(config), ctypes.sizeof(config)
    ) or not kernel.AssignProcessToJobObject(handle, process._handle):  # type: ignore[attr-defined]
        raise DecodeError()
    return int(handle)


class WindowsDecoder(_Private):
    """One bounded continuous codec task. Errors permanently fence it.

    Call from one thread, serialized with read/live authority changes. The
    authorize callback must check BOTH rights for this exact binding and return
    literal True. Decoding, construction, or worker success grants no access.
    """

    def __init__(
        self,
        *,
        binding: DecodeBinding,
        authorize: Callable[[DecodeBinding], bool],
        executable: Path,
        limits: DecodeLimits | None = None,
    ) -> None:
        limits = limits or DecodeLimits()
        limits.validate()
        if type(binding) is not DecodeBinding or not callable(authorize):
            raise DecodeError()
        executable = Path(executable)
        if os.name != "nt" or not executable.is_absolute() or not executable.is_file():
            raise DecodeError()
        self._binding = binding
        self._authorize = authorize
        self._executable = executable
        self._site_packages: Path | None = None
        config = executable.parent.parent / "pyvenv.cfg"
        if config.is_file():
            if config.stat().st_size > 8192:
                raise DecodeError()
            values = dict(
                line.split(" = ", 1)
                for line in config.read_text(encoding="utf-8").splitlines()
                if " = " in line
            )
            original = Path(values.get("executable", ""))
            site = config.parent / "Lib/site-packages"
            if (
                not original.is_absolute()
                or not original.is_file()
                or not site.is_dir()
            ):
                raise DecodeError()
            # Direct interpreter ownership avoids a launcher child creation race.
            self._executable = original
            self._site_packages = site
        self._limits = limits
        self._process: subprocess.Popen[bytes] | None = None
        self._job_handle: int | None = None
        self._threads: list[threading.Thread] = []
        self._thread_done: tuple[threading.Event, ...] = ()
        self._stop_watchdog = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._cleanup_lock = threading.Lock()
        self._reaper: threading.Thread | None = None
        self._retire_lock = threading.Lock()
        self._retire_done = threading.Event()
        self._retirement_threads: tuple[threading.Thread, ...] | None = None
        self._retirement_events: tuple[threading.Event, ...] = ()
        self._closed = False
        self._busy = False
        self._owner_thread = threading.get_ident()
        self._sequence = 0
        self._codec: str | None = None
        self._dimensions: tuple[int, int] | None = None
        self._pending: dict[int, int] = {}
        self._last_ordinal = -1
        self._packets = self._input = self._frames = self._output = 0
        self._deadline = time.monotonic() + limits.deadline_seconds

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        """Original child custody, for lifecycle supervision only; do not log."""
        return self._process

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _admit(self) -> None:
        if (
            self._closed
            or self._busy
            or threading.get_ident() != self._owner_thread
            or time.monotonic() >= self._deadline
        ):
            raise DecodeError()
        self._busy = True
        self._authority()

    def _authority(self) -> None:
        try:
            allowed = self._authorize(self._binding) is True
        except BaseException:  # noqa: BLE001 - fixed denial; no private exception logs
            allowed = False
        if not allowed or self._closed:
            raise DecodeDenied()
        if time.monotonic() >= self._deadline:
            raise DecodeError()

    def _spawn(self) -> None:
        if self._process is not None:
            return
        worker = Path(__file__).with_name("windows_decode_worker.py")
        # Store original ownership immediately; no authority/admission work intervenes.
        self._process = subprocess.Popen(
            [
                str(self._executable),
                "-I",
                str(worker),
                *([str(self._site_packages)] if self._site_packages else []),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(worker.parent),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        _job(self._process, self._limits.process_memory_bytes, self)

        def expire() -> None:
            if not self._stop_watchdog.wait(max(0, self._deadline - time.monotonic())):
                self.close()

        self._watchdog = threading.Thread(target=expire, daemon=True)
        self._watchdog.start()

    def _receive(self) -> tuple[PrivateRGBFrame, ...]:
        assert self._process is not None and self._process.stdout is not None
        stream = self._process.stdout
        magic, status, sequence, binding, count = _RESPONSE.unpack(
            _read(stream, _RESPONSE.size)
        )
        if (
            magic != b"WDR1"
            or status != 0
            or sequence != self._sequence
            or binding != self._binding._wire()
            or count > self._limits.max_response_frames
            or self._frames + count > self._limits.max_frames
        ):
            raise DecodeError()
        frames = []
        seen = set()
        for _ in range(count):
            width, height, ts, ordinal, length = _FRAME.unpack(
                _read(stream, _FRAME.size)
            )
            if (
                self._dimensions != (width, height)
                or length != width * height * 3
                or length > self._limits.max_frame_bytes
                or self._output + length > self._limits.max_output_bytes
                or ts in seen
                or self._pending.get(ts) != ordinal
            ):
                raise DecodeError()
            seen.add(ts)
            rgb = _read(stream, length)
            self._output += length
            frames.append(
                PrivateRGBFrame(self._binding, width, height, ts, ordinal, rgb)
            )
        for ts in seen:
            del self._pending[ts]
        self._frames += count
        return tuple(frames)

    def _exchange(self, request: bytes, payload: bytes) -> tuple[PrivateRGBFrame, ...]:
        fresh = self._process is None
        self._spawn()
        assert self._process is not None and self._process.stdin is not None
        process = self._process
        outcome: list[tuple[PrivateRGBFrame, ...] | BaseException] = []
        written = threading.Event()
        read = threading.Event()
        failures: list[BaseException] = []

        def feed() -> None:
            try:
                assert process.stdin is not None
                if fresh:
                    process.stdin.write(self._limits._wire())
                process.stdin.write(request)
                process.stdin.write(payload)
                process.stdin.flush()
            except BaseException as exc:  # noqa: BLE001 - retain feed custody
                failures.append(exc)
            finally:
                written.set()

        def drain() -> None:
            try:
                outcome.append(self._receive())
            except BaseException as exc:  # noqa: BLE001 - retain drain custody
                outcome.append(exc)
            finally:
                read.set()

        # Retain feed/drain objects before start and all fallible exchange admission.
        with self._cleanup_lock:
            if self._closed:
                raise DecodeError()
            self._threads = [
                threading.Thread(target=feed, daemon=True),
                threading.Thread(target=drain, daemon=True),
            ]
            self._thread_done = (written, read)
            for thread in self._threads:
                thread.start()
        while not (written.is_set() and read.is_set()):
            if failures or (outcome and isinstance(outcome[0], BaseException)):
                raise DecodeError()
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise DecodeError()
            (written if read.is_set() else read).wait(min(remaining, 0.02))
        if failures or not outcome or isinstance(outcome[0], BaseException):
            raise DecodeError()
        for thread in self._threads:
            thread.join()
        self._threads.clear()
        self._thread_done = ()
        return outcome[0]

    def decode(self, packet: ElementaryPacket) -> tuple[PrivateRGBFrame, ...]:
        try:
            self._admit()
            self._busy = True
            if type(packet) is not ElementaryPacket:
                raise DecodeError()
            if (
                type(packet.binding) is not DecodeBinding
                or packet.binding._wire() != self._binding._wire()
            ):
                raise DecodeError()
            _int(packet.generation, 1, 2**63 - 1)
            _int(packet.width, 1, self._limits.max_width)
            _int(packet.height, 1, self._limits.max_height)
            _int(packet.timestamp_us, -(2**63), 2**63 - 1)
            _int(packet.ordinal, 0, 2**32 - 1)
            if (
                packet.generation != self._binding.generation
                or packet.codec not in ("h264", "hevc")
                or packet.format != "annexb"
                or packet.encrypted is not False
                or type(packet._data) is not bytes
                or not packet._data
                or len(packet._data) > self._limits.max_packet_bytes
                or not packet._data.startswith((b"\x00\x00\x01", b"\x00\x00\x00\x01"))
                or packet.width * packet.height * 3 > self._limits.max_frame_bytes
                or (self._codec is not None and packet.codec != self._codec)
                or (
                    self._dimensions is not None
                    and self._dimensions != (packet.width, packet.height)
                )
                or packet.ordinal <= self._last_ordinal
                or packet.timestamp_us in self._pending
                or self._packets >= self._limits.max_packets
                or self._input + len(packet._data) > self._limits.max_input_bytes
            ):
                raise DecodeError()
            self._codec = packet.codec
            self._dimensions = (packet.width, packet.height)
            self._pending[packet.timestamp_us] = packet.ordinal
            self._last_ordinal = packet.ordinal
            self._packets += 1
            self._input += len(packet._data)
            self._sequence += 1
            request = _REQUEST.pack(
                b"WDQ1",
                1,
                1 if packet.codec == "h264" else 2,
                self._sequence,
                self._binding._wire(),
                packet.width,
                packet.height,
                packet.timestamp_us,
                packet.ordinal,
                len(packet._data),
            )
            frames = self._exchange(request, packet._data)
            self._authority()
            return frames
        except BaseException as exc:
            self.close()
            if isinstance(exc, DecodeDenied):
                raise DecodeDenied() from None
            if not isinstance(exc, Exception):
                raise
            raise DecodeError() from None
        finally:
            self._busy = False

    def finish(self) -> tuple[PrivateRGBFrame, ...]:
        """Flush delayed pictures, reap original child, then check authority."""
        try:
            self._admit()
            self._busy = True
            if self._codec is None or self._dimensions is None:
                raise DecodeError()
            self._sequence += 1
            width, height = self._dimensions
            request = _REQUEST.pack(
                b"WDQ1",
                2,
                1 if self._codec == "h264" else 2,
                self._sequence,
                self._binding._wire(),
                width,
                height,
                0,
                0,
                0,
            )
            frames = self._exchange(request, b"")
            assert self._process is not None
            self._process.wait(timeout=max(0.001, self._deadline - time.monotonic()))
            assert self._process.stdout is not None
            if (
                self._process.returncode != 0
                or self._pending
                or self._process.stdout.read(1)
            ):
                raise DecodeError()
            self._authority()
            self.close()
            return frames
        except BaseException as exc:
            self.close()
            if isinstance(exc, DecodeDenied):
                raise DecodeDenied() from None
            if not isinstance(exc, Exception):
                raise
            raise DecodeError() from None
        finally:
            self._busy = False

    def _retire_original(self) -> None:
        """Running thread OR calling owner keeps custody until all retirement ends."""
        acquired = False
        while not acquired:
            try:
                acquired = self._retire_lock.acquire(timeout=0.02)
            except BaseException:  # noqa: BLE001, S112 - interruption never drops custody
                continue
        try:
            if self._retire_done.is_set():
                return
            if self._retirement_threads is None:
                self._retirement_threads = tuple(self._threads)
                self._retirement_events = self._thread_done
            # A running retirement owner now exists before the watchdog is stopped.
            self._stop_watchdog.set()
            process = self._process
            assert process is not None
            reaped = False
            while True:
                if self._job_handle is not None:
                    try:
                        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                        if kernel.CloseHandle(self._job_handle):
                            self._job_handle = None
                    except BaseException:  # noqa: BLE001, S110 - retain Job and retry
                        pass
                # Safe original-handle fallback runs even when Job release fails.
                if not reaped:
                    try:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=1)
                        reaped = True
                    except BaseException:  # noqa: BLE001, S110 - retain exact original Popen
                        pass
                if reaped:
                    try:
                        for event, thread in zip(
                            self._retirement_events,
                            self._retirement_threads,
                            strict=False,
                        ):
                            # Unstarted feeder/drainer cannot signal its finally.
                            if thread.ident is not None:
                                event.wait()
                        for thread in self._retirement_threads:
                            if (
                                thread.ident is not None
                                and thread is not threading.current_thread()
                            ):
                                thread.join()
                        for pipe in (process.stdin, process.stdout):
                            if pipe is not None:
                                pipe.close()
                        if self._job_handle is None:
                            self._pending.clear()
                            self._retire_done.set()
                            return
                    except BaseException:  # noqa: BLE001, S110 - joins/pipes stay owned
                        pass
                try:
                    time.sleep(0.02)
                except BaseException:  # noqa: BLE001, S112 - synchronous fallback remains owner
                    continue
        finally:
            self._retire_lock.release()

    def close(self) -> None:
        """Fence, establish running retirement, then release exact owned resources.

        Failed reaper creation/start falls back to synchronous original retirement;
        an unstarted thread is neither a supervisor nor a reusable join target.
        """
        self._closed = True
        process = self._process
        if process is None:
            self._stop_watchdog.set()
            self._retire_done.set()
            return
        reaper = None
        fallback = False
        try:
            with self._cleanup_lock:
                if self._retire_done.is_set():
                    return
                if self._retirement_threads is None:
                    self._retirement_threads = tuple(self._threads)
                    self._retirement_events = self._thread_done
                if self._reaper is None:
                    candidate = threading.Thread(
                        target=self._retire_original, daemon=True
                    )
                    self._reaper = candidate
                    try:
                        candidate.start()
                    except BaseException:  # noqa: BLE001 - calling owner takes over
                        if candidate.ident is None:
                            self._reaper = None
                        fallback = True
                reaper = self._reaper
        except BaseException:  # noqa: BLE001 - creation/admission cannot drop original
            fallback = True
        if fallback or reaper is None:
            self._retire_original()
            return
        try:
            reaper.join(timeout=3)
        except BaseException:  # noqa: BLE001 - interrupted join retains caller custody
            self._retire_original()
