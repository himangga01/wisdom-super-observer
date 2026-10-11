"""Inert originals only: never invokes Popen, WinDLL, SDK, DB or a listener."""

import importlib.util
import io
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


class FakeThread:
    def __init__(self, *, target, **kwargs):
        self.target = target
        self.ident = None
        self.alive = False

    def start(self):
        self.ident = 1
        self.alive = True
        self.complete()

    def complete(self):
        try:
            self.target()
        finally:
            self.alive = False

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        pass


@pytest.fixture
def module(monkeypatch):
    path = ROOT / "scripts/test-local-devices/worker_job.py"
    assert path.is_file(), "separate worker Job supervisor missing"
    spec = importlib.util.spec_from_file_location("inert_worker_job", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    # Replace the module binding, never mutate global threading.Thread.
    monkeypatch.setattr(
        result,
        "threading",
        SimpleNamespace(
            Thread=FakeThread,
            Event=threading.Event,
            Lock=threading.Lock,
        ),
    )
    return result


class FakeJob:
    def __init__(self, events, *, deny=False):
        self.events, self.deny = events, deny
        self.closed, self.active = False, 0

    def create(self):
        self.events.append("job-created")

    def admit(self, child, *, original_handle, raw_handle):
        self.events.append("admitted")
        assert child._handle is original_handle and int(original_handle) == raw_handle
        assert child.stdin.getvalue() == b""
        if self.deny:
            raise ValueError("inert admission denial")
        self.active = 1

    def empty(self):
        return self.active == 0

    def terminate(self):
        self.events.append("job-terminate")
        self.active = 0

    def terminate_original(self, handle):
        assert handle == self.child._handle
        self.events.append("original-terminate")
        self.child.returncode = 1

    def identity_current(self):
        return True

    def close(self):
        assert self.active == 0
        self.events.append("job-closed")
        self.closed = True


class FakeChild:
    def __init__(self, events):
        self.events = events
        self.stdin = io.BytesIO()
        self.returncode = None
        self.pid = 123
        self._handle = 71

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        assert self.returncode is not None
        self.events.append("reaped")
        return self.returncode

    def terminate(self):
        pytest.fail("mutable Popen wrapper must not be signalled")


def make_owner(module, *, deny=False, spawn_error=False):
    events = []
    job, child = FakeJob(events, deny=deny), FakeChild(events)
    job.child = child

    def spawn(*args, **kwargs):
        events.append("spawn")
        assert owner.job is job
        if spawn_error:
            raise OSError("inert uncertain constructor")
        return child

    owner = module.WorkerSupervisor(job=job, spawn=spawn)
    return owner, job, child, events


def test_worker_release_follows_original_job_admission(module):
    owner, job, child, events = make_owner(module)
    assert owner.launch(["inert"], env={}, cwd=ROOT) is child
    assert events[:3] == ["job-created", "spawn", "admitted"]
    assert child.stdin.getvalue() == b"J\n"
    assert owner.child is child and not owner.confirmed
    assert not owner.close_step()
    assert child.stdin.getvalue() == b"J\nclose\n"
    child.returncode, job.active = 0, 0
    assert owner.close_step()
    assert owner.confirmed and child.stdin.closed and job.closed
    assert events.index("reaped") < events.index("job-closed")
    assert owner.receipt()["exit"] == 0


def test_worker_exit_does_not_certify_surviving_descendants(module):
    owner, job, child, _events = make_owner(module)
    owner.launch(["inert"], env={}, cwd=ROOT)
    child.returncode = 0
    assert not owner.close_step()
    assert not job.closed and not owner.confirmed
    assert owner.receipt()["custody_retained"] is True
    job.active = 0
    assert owner.close_step()


def test_worker_admission_failure_never_releases_input(module):
    owner, _job, child, events = make_owner(module, deny=True)
    with pytest.raises(ValueError):
        owner.launch(["inert"], env={}, cwd=ROOT)
    assert child.stdin.getvalue() == b""
    assert owner.child is child
    assert owner.close_step()
    assert "original-terminate" in events
    assert owner.receipt()["failed"] is True


def test_uncertain_popen_failure_retains_job_and_fails_closed(module):
    owner, job, _child, _events = make_owner(module, spawn_error=True)
    with pytest.raises(OSError):
        owner.launch(["inert"], env={}, cwd=ROOT)
    assert owner.child is None
    assert not owner.close_step()
    assert owner.receipt()["constructor_uncertain"] is True
    assert owner.receipt()["custody_retained"] is True
    assert not job.closed


def test_worker_bootstrap_checks_job_before_application_import(module):
    text = module.WORKER_BOOTSTRAP
    assert text.index("sys.stdin.buffer.read(2)") < text.index("IsProcessInJob")
    assert text.index("IsProcessInJob") < text.index("import site")
    assert "WSO_TEST_LOCAL_MEDIA_SHARED" not in text
    assert module.WORKER_PROCESS_BYTES == 2 << 30
    assert module.WORKER_JOB_FLAGS == 0x2100


def test_unknown_job_accounting_or_release_retains_original(module):
    owner, job, child, _events = make_owner(module)
    owner.launch(["inert"], env={}, cwd=ROOT)
    child.returncode = 0

    def unknown():
        raise OSError("inert unknown kernel result")

    job.empty = unknown
    assert not owner.close_step()
    assert not owner.confirmed and not job.closed
    assert owner.receipt()["custody_retained"] is True
    job.empty = lambda: True
    job.active = 0
    job.close = unknown
    assert not owner.close_step()
    assert not owner.confirmed


def test_partial_marker_failure_reaps_only_original_and_stays_failed(module):
    owner, _job, child, events = make_owner(module)

    class FailedPipe(io.BytesIO):
        def write(self, value):
            super().write(value[:1])
            raise OSError("inert partial marker")

    child.stdin = FailedPipe()
    with pytest.raises(ValueError, match="bootstrap"):
        owner.launch(["inert"], env={}, cwd=ROOT)
    assert child.stdin.getvalue() == b"J"
    assert not owner.close_step()
    assert "job-terminate" in events and "original-terminate" not in events
    child.returncode = 1
    assert owner.close_step()
    assert owner.receipt()["failed"] is True


def test_live_original_and_writer_block_clean_receipt(module):
    owner, job, child, _events = make_owner(module)

    class HeldThread(FakeThread):
        def start(self):
            self.ident, self.alive = 1, True

    module.threading.Thread = HeldThread
    with pytest.raises(ValueError, match="bootstrap"):
        owner.launch(["inert"], env={}, cwd=ROOT)
    child.returncode, job.active = 1, 0
    assert not owner.close_step()
    assert owner.receipt()["writer_settled"] is False
    assert not job.closed
    owner._writer.complete()
    assert owner.close_step()


@pytest.mark.parametrize("phase", ["marker", "close"])
def test_r1_interrupted_writer_start_without_identity_stays_pending(module, phase):
    owner, job, child, _events = make_owner(module)
    if phase == "close":
        owner.launch(["inert"], env={}, cwd=ROOT)

    class InterruptedThread(FakeThread):
        def start(self):
            raise KeyboardInterrupt()

    module.threading.Thread = InterruptedThread
    if phase == "marker":
        with pytest.raises(KeyboardInterrupt):
            owner.launch(["inert"], env={}, cwd=ROOT)
    else:
        try:
            settled = owner.close_step()
        except KeyboardInterrupt:
            pytest.fail("uncertain close writer escaped original cleanup owner")
        assert not settled
    child.returncode, job.active = 1, 0
    assert not owner.close_step()
    value = owner.receipt()
    assert value["writer_settled"] is False
    assert value["custody_retained"] is True
    assert not child.stdin.closed and not job.closed
    # The exact late original starts/finishes; only then can it be joined.
    owner._writer.ident = 99
    owner._writer.complete()
    assert owner.close_step()


def test_r1_poll_handle_substitution_never_uses_foreign_terminate(module):
    owner, _job, child, events = make_owner(module, deny=True)
    with pytest.raises(ValueError):
        owner.launch(["inert"], env={}, cwd=ROOT)

    def substitute():
        child._handle = 999

    child.poll = substitute
    assert not owner.close_step()
    assert "original-terminate" not in events and "job-terminate" not in events
    assert owner.receipt()["custody_retained"] is True


@pytest.mark.parametrize(
    "phase",
    [
        "launch_poll",
        "write",
        "wait",
        "accounting",
        "job_close",
        "stdin_close",
        "receipt",
        "writer_join",
        "receipt_supplier",
    ],
)
def test_r1_substitution_inside_fallible_phase_never_confirms(module, phase):
    owner, job, child, _events = make_owner(module)

    def substitute():
        child._handle = 999

    if phase == "launch_poll":
        child.poll = lambda: substitute()
        with pytest.raises(ValueError, match="original"):
            owner.launch(["inert"], env={}, cwd=ROOT)
        assert not owner.confirmed
        return
    if phase == "write":

        class SubstitutingPipe(io.BytesIO):
            def write(self, value):
                result = super().write(value)
                substitute()
                return result

        child.stdin = SubstitutingPipe()
        with pytest.raises(ValueError, match="original"):
            owner.launch(["inert"], env={}, cwd=ROOT)
        assert not owner.confirmed
        return
    owner.launch(["inert"], env={}, cwd=ROOT)
    child.returncode, job.active = 0, 0
    if phase == "wait":
        child.wait = lambda **kwargs: substitute() or 0
    elif phase == "accounting":
        job.empty = lambda: substitute() or True
    elif phase == "job_close":
        original_close = job.close

        def close():
            original_close()
            substitute()

        job.close = close
    elif phase == "stdin_close":
        # Change the retained exact pipe's implementation; not its identity.
        child.stdin.close = lambda: substitute()
    elif phase == "writer_join":
        owner._writer.join = lambda timeout=None: setattr(owner, "_writer", object())
    elif phase == "receipt_supplier":
        assert owner.close_step()

        class ReceiptJob(FakeJob):
            @property
            def qualified(self):
                substitute()
                return True

        job.__class__ = ReceiptJob
        assert owner.receipt()["custody_retained"] is True
        assert not owner.confirmed
        return
    elif phase == "receipt":
        assert owner.close_step()
        substitute()
        assert owner.receipt()["custody_retained"] is True
        assert not owner.confirmed
        return
    assert not owner.close_step()
    assert not owner.confirmed
    assert owner.receipt()["custody_retained"] is True


def test_no_second_launch_or_public_original_replacement(module):
    owner, job, child, _events = make_owner(module)
    owner.launch(["inert"], env={}, cwd=ROOT)
    with pytest.raises(ValueError, match="already attempted"):
        owner.launch(["foreign"], env={}, cwd=ROOT)
    with pytest.raises(AttributeError):
        owner.child = object()
    with pytest.raises(AttributeError):
        owner.job = object()
    child.returncode, job.active = 0, 0
    assert owner.close_step()


def test_process_handle_substitution_during_admission_releases_no_marker(module):
    owner, job, child, _events = make_owner(module)
    original = child._handle

    def replace(process, **kwargs):
        process._handle = object()

    job.admit = replace
    try:
        with pytest.raises(ValueError, match="original"):
            owner.launch(["inert"], env={}, cwd=ROOT)
        assert child.stdin.getvalue() == b""
        assert not owner.close_step()
        assert owner.receipt()["custody_retained"] is True
    finally:
        child._handle = original
        child.returncode, job.active = 1, 0
        assert owner.close_step()


def test_original_stdin_substitution_never_signals_foreign_pipe(module):
    owner, job, child, _events = make_owner(module)
    owner.launch(["inert"], env={}, cwd=ROOT)
    original, foreign = child.stdin, io.BytesIO()
    child.stdin = foreign
    try:
        assert not owner.close_step()
        assert foreign.getvalue() == b"" and not foreign.closed
        assert owner.receipt()["custody_retained"] is True
    finally:
        child.stdin = original
        child.returncode, job.active = 0, 0
        assert owner.close_step()


def make_kernel():
    calls = []

    class Function:
        def __init__(self, fn):
            self.fn = fn

        def __call__(self, *args):
            return self.fn(*args)

    class Kernel:
        pass

    kernel = Kernel()
    kernel.CreateJobObjectW = Function(lambda *_: 42)

    def set_information(handle, kind, data, size):
        limits = data._obj
        calls.append(
            (
                limits.basic.flags,
                limits.basic.active_processes,
                limits.process_memory,
                limits.job_memory,
            )
        )
        return 1

    kernel.SetInformationJobObject = Function(set_information)

    def query(handle, kind, data, size, returned):
        if kind == 9:
            data._obj.basic.flags = 0x2100
            data._obj.process_memory = 2 << 30
        else:
            data._obj.active_processes = 0
        return 1

    kernel.QueryInformationJobObject = Function(query)
    kernel.AssignProcessToJobObject = Function(
        lambda job, process: calls.append((job, process)) or 1
    )

    def member(process, job, result):
        result._obj.value = 1
        return 1

    kernel.IsProcessInJob = Function(member)
    kernel.TerminateJobObject = Function(lambda *_: 1)
    kernel.TerminateProcess = Function(lambda *_: 1)
    kernel.CloseHandle = Function(lambda handle: calls.append(("closed", handle)) or 1)
    return kernel, calls


def test_job_exact_profile_and_original_handle_without_native_kernel(module):
    kernel, calls = make_kernel()
    job = module.WorkerJob(kernel=kernel)
    job.create()

    class Original:
        _handle = 73

    job.admit(Original(), original_handle=73, raw_handle=73)
    assert calls[:2] == [(0x2100, 0, 2 << 30, 0), (42, 73)]
    assert job.empty()
    job.close()
    assert job.closed and calls[-1] == ("closed", 42)


@pytest.mark.parametrize(
    "phase",
    [
        "limits",
        "limits_query",
        "admit",
        "accounting",
        "close_accounting",
        "close_handle",
        "kernel",
    ],
)
def test_r1_job_retains_raw_original_through_kernel_boundaries(module, phase):
    kernel, calls = make_kernel()
    job = module.WorkerJob(kernel=kernel)
    names = {
        "limits": "SetInformationJobObject",
        "limits_query": "QueryInformationJobObject",
        "admit": "AssignProcessToJobObject",
        "accounting": "QueryInformationJobObject",
        "close_accounting": "QueryInformationJobObject",
        "close_handle": "CloseHandle",
        "kernel": "QueryInformationJobObject",
    }
    if phase not in ("limits", "limits_query"):
        job.create()
    function = getattr(kernel, names[phase])
    original = function.fn

    def changed(*args):
        result = original(*args)
        if phase == "kernel":
            job._kernel = object()
        else:
            job._handle = 999
        return result

    function.fn = changed
    with pytest.raises(ValueError, match="original"):
        if phase in ("limits", "limits_query"):
            job.create()
        elif phase == "admit":
            job.admit(SimpleNamespace(_handle=73), original_handle=73, raw_handle=73)
        elif phase in ("accounting", "kernel"):
            job.empty()
        else:
            job.close()
    assert not job.identity_current() and not job.closed
    assert ("closed", 999) not in calls
    if phase == "close_handle":
        assert calls.count(("closed", 42)) == 1
        with pytest.raises(ValueError):
            job.close()
        assert calls.count(("closed", 42)) == 1
    else:
        assert not any(row[0] == "closed" for row in calls)


def test_r1_unadmitted_signal_targets_captured_raw_handle(module):
    kernel, calls = make_kernel()
    job = module.WorkerJob(kernel=kernel)
    job.create()
    kernel.TerminateProcess.fn = lambda raw, code: (
        calls.append(("signal", raw, code)) or 1
    )
    job.terminate_original(73)
    assert calls[-1] == ("signal", 73, 1)


def test_r1_unknown_identity_supplier_remains_owned(module):
    owner, job, _child, _events = make_owner(module)
    owner.launch(["inert"], env={}, cwd=ROOT)

    def unknown():
        raise OSError("inert identity unavailable")

    job.identity_current = unknown
    assert not owner.close_step()
    assert owner.receipt()["custody_retained"] is True


@pytest.mark.parametrize(
    "change", [None, "admission_read", "after_assignment", "child_at_method_lookup"]
)
def test_r2_admission_only_targets_supervisor_captured_raw_handle(module, change):
    kernel, calls = make_kernel()
    memberships = []

    class Child:
        def __init__(self, value=73):
            self.value, self.reads = value, 0
            self.stdin = io.BytesIO()
            self.returncode = None

        @property
        def _handle(self):
            self.reads += 1
            # Capture/check see73; the next accessor models the admission seam.
            if change == "admission_read" and self.reads >= 3:
                self.value = 999
            return self.value

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    child, foreign = Child(), Child(999)
    original_assign = kernel.AssignProcessToJobObject.fn

    def assign(job_handle, process_handle):
        result = original_assign(job_handle, process_handle)
        if change == "after_assignment":
            child.value = 999
        return result

    kernel.AssignProcessToJobObject.fn = assign
    original_member = kernel.IsProcessInJob.fn

    def member(process_handle, job_handle, result):
        memberships.append(process_handle)
        return original_member(process_handle, job_handle, result)

    kernel.IsProcessInJob.fn = member

    class Job(module.WorkerJob):
        def __getattribute__(self, name):
            if name == "admit" and change == "child_at_method_lookup":
                owner._child = foreign
            return super().__getattribute__(name)

    job = Job(kernel=kernel)
    owner = module.WorkerSupervisor(job=job, spawn=lambda *args, **kwargs: child)
    if change is None:
        assert owner.launch(["inert"], env={}, cwd=ROOT) is child
    else:
        with pytest.raises(ValueError, match="original"):
            owner.launch(["inert"], env={}, cwd=ROOT)
    assert owner._original[0] is child and owner._original[3] == 73
    assignments = [row[1] for row in calls if len(row) == 2 and row[0] == 42]
    assert all(value == 73 for value in assignments), assignments
    assert all(value == 73 for value in memberships), memberships
    if change is None:
        assert assignments == memberships == [73]
        assert child.stdin.getvalue() == b"J\n"
        child.returncode = 0
        assert owner.close_step()
    else:
        assert child.stdin.getvalue() == foreign.stdin.getvalue() == b""
        assert not owner.close_step() and not owner.confirmed
        assert owner.receipt()["custody_retained"] is True
        assert not job.closed
