"""Original shared media worker custody. Import is inert; native Jobs are opt-in.

This parent profile allows descendants with their own stricter Jobs. It never
changes the recorder's active-process-one/512MiB profile or looks up a PID.
"""

from __future__ import annotations

import ctypes as ct
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

WORKER_PROCESS_BYTES = 2 << 30
WORKER_JOB_FLAGS = 0x2100  # KILL_ON_JOB_CLOSE | PROCESS_MEMORY; descendants allowed

# The parent queries its exact Job and admits the original Popen before J.
# -I -S prevents site hooks/application imports before the admission barrier.
WORKER_BOOTSTRAP = """import sys, ctypes as c
if sys.stdin.buffer.read(2) != b'J\\n':
    raise SystemExit(91)
k = c.WinDLL('kernel32', use_last_error=True)
k.GetCurrentProcess.restype = c.c_void_p
k.IsProcessInJob.argtypes = [c.c_void_p, c.c_void_p, c.POINTER(c.c_int)]
k.IsProcessInJob.restype = c.c_int
inside = c.c_int()
if not k.IsProcessInJob(k.GetCurrentProcess(), None, c.byref(inside)) or not inside.value:
    raise SystemExit(92)
if len(sys.argv) != 6:
    raise SystemExit(93)
import site, runpy
root, prefix, purelib, entry, folder = sys.argv[1:]
sys.prefix = prefix
site.addsitedir(purelib)
sys.path.insert(0, root)
sys.argv = [entry, '--worker', folder]
runpy.run_path(entry, run_name='__main__')
"""


class BasicLimits(ct.Structure):
    _fields_ = [
        ("process_time", ct.c_int64),
        ("job_time", ct.c_int64),
        ("flags", ct.c_uint32),
        ("min_working", ct.c_size_t),
        ("max_working", ct.c_size_t),
        ("active_processes", ct.c_uint32),
        ("affinity", ct.c_size_t),
        ("priority", ct.c_uint32),
        ("scheduling", ct.c_uint32),
    ]


class ExtendedLimits(ct.Structure):
    _fields_ = [
        ("basic", BasicLimits),
        ("io", ct.c_uint64 * 6),
        ("process_memory", ct.c_size_t),
        ("job_memory", ct.c_size_t),
        ("peak_process_memory", ct.c_size_t),
        ("peak_job_memory", ct.c_size_t),
    ]


class Accounting(ct.Structure):
    _fields_ = [
        ("user_time", ct.c_int64),
        ("kernel_time", ct.c_int64),
        ("period_user_time", ct.c_int64),
        ("period_kernel_time", ct.c_int64),
        ("page_faults", ct.c_uint32),
        ("total_processes", ct.c_uint32),
        ("active_processes", ct.c_uint32),
        ("terminated_processes", ct.c_uint32),
    ]


class WorkerJob:
    """One retained Job handle; no alternate handle, process discovery or breakaway."""

    def __init__(self, *, kernel: Any = None) -> None:
        self._kernel = kernel
        self._original_kernel: Any = None
        self._handle: Any = None
        self._original_handle: Any = None
        self._released = False
        self.qualified = False

    @property
    def closed(self) -> bool:
        return self._handle is None and (
            self._original_handle is None or self._released
        )

    def identity_current(self) -> bool:
        return (
            self._original_kernel is None or self._kernel is self._original_kernel
        ) and (
            self._handle is None
            if self._released
            else self._handle is self._original_handle
        )

    def _check(self) -> None:
        if not self.identity_current():
            raise ValueError("original worker Job identity changed")

    def create(self) -> None:
        if not self.closed or self._original_handle is not None:
            raise ValueError("worker Job already created")
        if self._kernel is None:
            self._kernel = ct.WinDLL("kernel32", use_last_error=True)
        k = self._kernel
        self._original_kernel = k
        for name, args, result in (
            ("CreateJobObjectW", [ct.c_void_p, ct.c_wchar_p], ct.c_void_p),
            (
                "SetInformationJobObject",
                [ct.c_void_p, ct.c_int, ct.c_void_p, ct.c_uint32],
                ct.c_int,
            ),
            (
                "QueryInformationJobObject",
                [ct.c_void_p, ct.c_int, ct.c_void_p, ct.c_uint32, ct.c_void_p],
                ct.c_int,
            ),
            ("AssignProcessToJobObject", [ct.c_void_p, ct.c_void_p], ct.c_int),
            (
                "IsProcessInJob",
                [ct.c_void_p, ct.c_void_p, ct.POINTER(ct.c_int)],
                ct.c_int,
            ),
            ("TerminateJobObject", [ct.c_void_p, ct.c_uint32], ct.c_int),
            ("TerminateProcess", [ct.c_void_p, ct.c_uint32], ct.c_int),
            ("CloseHandle", [ct.c_void_p], ct.c_int),
        ):
            function = getattr(k, name)
            function.argtypes, function.restype = args, result
        self._handle = k.CreateJobObjectW(None, None)
        self._original_handle = self._handle
        if not self._handle:
            self._handle = None
            self._original_handle = None
            raise ValueError("worker Job creation refused")
        self._check()
        limits = ExtendedLimits()
        limits.basic.flags = WORKER_JOB_FLAGS
        limits.process_memory = WORKER_PROCESS_BYTES
        if not k.SetInformationJobObject(
            self._original_handle, 9, ct.byref(limits), ct.sizeof(limits)
        ):
            raise ValueError("worker Job limits refused")
        self._check()
        actual = ExtendedLimits()
        if not k.QueryInformationJobObject(
            self._original_handle, 9, ct.byref(actual), ct.sizeof(actual), None
        ) or (
            actual.basic.flags != WORKER_JOB_FLAGS
            or actual.basic.active_processes != 0
            or actual.process_memory != WORKER_PROCESS_BYTES
            or actual.job_memory != 0
        ):
            raise ValueError("worker Job limits unconfirmed")
        self._check()
        self.qualified = True

    def admit(self, child: Any, *, original_handle: Any, raw_handle: int) -> None:
        """Admit the supervisor's captured capability, never a fresh handle."""
        self._check()
        inside = ct.c_int()
        if (
            self.closed
            or not self.qualified
            or original_handle is None
            or type(raw_handle) is not int
            or raw_handle <= 0
            or int(original_handle) != raw_handle
            or getattr(child, "_handle", None) is not original_handle
        ):
            raise ValueError("original worker Job admission refused")
        # Wrapper reads above/below are comparison only. Both native calls use
        # the exact raw HANDLE captured before this boundary.
        if not self._original_kernel.AssignProcessToJobObject(
            self._original_handle, raw_handle
        ):
            raise ValueError("original worker Job admission refused")
        self._check()
        if child._handle is not original_handle:
            raise ValueError("original worker handle changed")
        if (
            not self._original_kernel.IsProcessInJob(
                raw_handle, self._original_handle, ct.byref(inside)
            )
            or not inside.value
        ):
            raise ValueError("original worker Job admission refused")
        self._check()
        if child._handle is not original_handle:
            raise ValueError("original worker handle changed")

    def empty(self) -> bool:
        self._check()
        if self.closed:
            return True
        value = Accounting()
        if not self._original_kernel.QueryInformationJobObject(
            self._original_handle, 1, ct.byref(value), ct.sizeof(value), None
        ):
            raise ValueError("worker Job accounting unavailable")
        self._check()
        return bool(value.active_processes == 0)

    def terminate(self) -> None:
        self._check()
        if not self.closed and not self._original_kernel.TerminateJobObject(
            self._original_handle, 1
        ):
            raise ValueError("original worker Job termination pending")
        self._check()

    def terminate_original(self, raw_process_handle: int) -> None:
        """Signal the retained raw HANDLE, never mutable Popen.terminate()."""
        self._check()
        if not self._original_kernel.TerminateProcess(raw_process_handle, 1):
            raise ValueError("original worker termination pending")
        self._check()

    def close(self) -> None:
        self._check()
        if not self.closed:
            if not self.empty():
                raise ValueError("worker Job release pending")
            self._check()
            original = self._original_handle
            if not self._original_kernel.CloseHandle(original):
                raise ValueError("worker Job release pending")
            self._released = True
            if self._handle is original:
                self._handle = None
            self._check()


class _WriterState:
    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.start_attempted = False
        self.start_returned = False
        self.finished = False
        self.joined = False


class WorkerSupervisor:
    """Retain original constructor, child, Job, stdin and writers until settled.

    Normal close never kills a worker or its descendants. Launch failure may
    terminate only its original child/Job and remains FAILED even after reap.
    A constructor with no returned Popen is uncertain and never certifies absence.
    """

    def __init__(
        self, *, job: Any = None, spawn: Callable[..., Any] | None = None
    ) -> None:
        self._job = WorkerJob() if job is None else job
        self._original_job = self._job
        self._spawn = subprocess.Popen if spawn is None else spawn
        self._child: Any = None
        self._process_handle: Any = None
        self._raw_process_handle: int | None = None
        self._original: tuple[Any, Any, Any, int] | None = None
        self._stdin: Any = None
        self._writer: threading.Thread | None = None
        self._writers: list[tuple[_WriterState, threading.Thread]] = []
        self._write_failed = threading.Event()
        self._started = self._launching = self._attempted = self._uncertain = False
        self._failed = self._admitted = self._stop_sent = self._confirmed = False
        self._reaped = self._empty = False
        self._exit: int | None = None
        self._close_lock = threading.Lock()

    @property
    def child(self) -> Any:
        return self._child

    @property
    def job(self) -> Any:
        return self._job

    @property
    def confirmed(self) -> bool:
        try:
            current = self._matches()
        except Exception:  # noqa: BLE001 - unknown identity cannot confirm custody
            current = False
        if not current:
            self._failed = True
        return self._confirmed and current

    def _write(self, data: bytes) -> None:
        self._check()
        original = self._stdin
        state = _WriterState()

        def write() -> None:
            try:
                self._check()
                if self._failed or original is None:
                    raise ValueError("worker input fenced")
                size = original.write(data)
                self._check()
                if size != len(data):
                    raise ValueError("worker input incomplete")
                original.flush()
                self._check()
            except BaseException:  # noqa: BLE001 - retained writer reports no private details
                self._write_failed.set()
            finally:
                state.finished = True

        thread = threading.Thread(target=write, name="owned-worker-input", daemon=False)
        self._check()
        state.thread = thread
        self._writer = thread
        self._writers.append((state, thread))
        # A start can acquire an OS thread then be interrupted before ident is
        # published. Retain the attempt BEFORE invoking the original start.
        state.start_attempted = True
        try:
            thread.start()
            state.start_returned = True
            self._check()
            if thread.ident is not None:
                thread.join(0.2)
                self._check()
        except BaseException:
            self._failed = True
            raise

    def _matches(self) -> bool:
        if (
            self._job is not self._original_job
            or not self._original_job.identity_current()
        ):
            return False
        original = self._original
        if original is None:
            child_matches = self._child is None
        else:
            child, handle, pipe, raw = original
            child_matches = (
                self._child is child
                and self._process_handle is handle
                and self._stdin is pipe
                and self._raw_process_handle == raw
                and getattr(child, "_handle", None) is handle
                and child.stdin is pipe
            )
        return (
            child_matches
            and all(state.thread is thread for state, thread in self._writers)
            and self._writer is (self._writers[-1][1] if self._writers else None)
        )

    def _check(self) -> None:
        if not self._matches():
            self._failed = True
            raise ValueError("original worker custody changed")

    def _writers_settled(self) -> bool:
        self._check()
        for state, thread in tuple(self._writers):
            if not state.start_attempted:
                continue
            identity = thread.ident
            self._check()
            if identity is None:
                return False
            thread.join(0.05)
            self._check()
            alive = thread.is_alive()
            self._check()
            if alive or not state.finished:
                return False
            state.joined = True
        return True

    def _writer_proof(self) -> bool:
        return all(
            not state.start_attempted or (state.finished and state.joined)
            for state, _ in self._writers
        )

    def launch(
        self, command: Sequence[str], *, env: Mapping[str, str], cwd: Path
    ) -> Any:
        if self._started:
            raise ValueError("original worker already attempted")
        self._started = self._launching = True
        try:
            self._job.create()
            self._check()
            self._attempted = True
            self._child = self._spawn(
                list(command),
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            child = self._child
            self._process_handle = getattr(child, "_handle", None)
            if self._process_handle is None:
                raise ValueError("original worker handle unavailable")
            self._raw_process_handle = int(self._process_handle)
            self._stdin = child.stdin
            original = (
                child,
                self._process_handle,
                self._stdin,
                self._raw_process_handle,
            )
            self._original = original
            if not self._matches():
                raise ValueError("original worker handle unavailable")
            self._original_job.admit(
                original[0], original_handle=original[1], raw_handle=original[3]
            )
            self._admitted = True
            if not self._matches():
                raise ValueError("original worker custody changed")
            self._write(b"J\n")
            if not self._writers_settled() or self._write_failed.is_set():
                raise ValueError("original worker bootstrap release failed")
            status = self._child.poll()
            self._check()
            if status is not None:
                raise ValueError("original worker bootstrap release failed")
            return self._child
        except BaseException:
            self._failed = True
            self._uncertain = self._attempted and self._child is None
            raise
        finally:
            self._launching = False

    def close_step(self) -> bool:
        with self._close_lock:
            if self.confirmed:
                return True
            if self._launching or self._uncertain:
                return False
            try:
                self._check()
                child, job, pipe = self._child, self._original_job, self._stdin
                if self._write_failed.is_set():
                    self._failed = True
                status = child.poll() if child is not None else None
                self._check()
                if self._failed and child is not None and status is None:
                    self._check()
                    if self._admitted:
                        job.terminate()
                    else:
                        # No Popen method may reread a substituted _handle at
                        # signal time. The retained raw HANDLE is the target.
                        raw = self._raw_process_handle
                        if raw is None:
                            raise ValueError("original worker handle unavailable")
                        job.terminate_original(raw)
                    self._check()
                    status = child.poll()
                    self._check()
                if child is not None and status is None:
                    if not self._failed and not self._stop_sent:
                        if not self._writers_settled():
                            return False
                        self._stop_sent = True
                        self._write(b"close\n")
                        self._check()
                    return False
                if not self._writers_settled():
                    return False
                if child is not None and not self._reaped:
                    self._check()
                    code = child.wait(timeout=0)
                    self._check()
                    self._exit = code
                    self._reaped = True
                    self._failed |= self._exit != 0
                closed = pipe is None or pipe.closed
                self._check()
                if not closed:
                    pipe.close()
                    self._check()
                    closed = pipe.closed
                    self._check()
                    if not closed:
                        return False
                empty = job.empty()
                self._check()
                if not empty:
                    return False
                self._empty = True
                self._check()
                job.close()
                self._check()
                closed = job.closed
                self._check()
                self._confirmed = closed and self._writer_proof()
                return self.confirmed
            except BaseException:  # noqa: BLE001 - interrupted cleanup retains originals
                self._failed = True
                return False

    def receipt(self) -> dict[str, object]:
        # Only stored join/finish evidence can certify a writer. ident/alive
        # heuristics cannot settle an interrupted start.
        try:
            self._check()
            qualified = getattr(self._original_job, "qualified", False) is True
            self._check()
            job_closed = self._original_job.closed
            self._check()
            stdin_closed = self._stdin is None or self._stdin.closed
            self._check()
            current = True
        except Exception:  # noqa: BLE001 - unknown original metadata stays pending
            qualified = job_closed = stdin_closed = current = False
            self._failed = True
        confirmed = self._confirmed and current and self._writer_proof()
        return {
            "exit": self._exit,
            "custody_retained": not confirmed,
            "incomplete": not confirmed,
            "failed": self._failed,
            "constructor_uncertain": self._uncertain,
            "worker_process_bytes": WORKER_PROCESS_BYTES,
            "job_flags": WORKER_JOB_FLAGS,
            "job_limits_confirmed": qualified,
            "job_assignment_confirmed": self._admitted,
            "job_empty": self._empty,
            "job_closed": job_closed,
            "writer_settled": current and self._writer_proof(),
            "writer_start_uncertain": any(
                state.start_attempted and not state.joined for state, _ in self._writers
            ),
            "stdin_closed": stdin_closed,
            "original_reaped": self._reaped,
        }
