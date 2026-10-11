"""R187 constructor custody with fake threads/events/loops only."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from wso_core.tvt.local_service import LocalDeviceFailure
from wso_tvt_media import worker


class Flag:
    def __init__(self):
        self.value = False

    def set(self):
        self.value = True

    def is_set(self):
        return self.value

    def wait(self, timeout=None):
        return self.value


class Loop:
    def __init__(self):
        self.closed = False
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        self.closed = True

    def is_closed(self):
        return self.closed

    def create_task(self, coroutine):
        coroutine.close()
        return SimpleNamespace(done=lambda: False)

    def run_forever(self):
        raise RuntimeError("controlled loop failure")


class Executor:
    def __init__(self):
        self.settled = True
        self.calls = 0

    def shutdown(self):
        self.calls += 1
        return self.settled


@pytest.fixture
def construction(monkeypatch):
    trace = []
    created = []
    loop = Loop()
    behavior = ["delay"]

    class Thread:
        def __init__(self, *, target, **kwargs):
            self.target = target
            self.ident = None
            self.alive = False
            self.starts = self.joins = 0
            created.append(self)

        def start(self):
            trace.append("start")
            self.starts += 1
            if behavior[0] == "interrupted":
                raise InterruptedError("controlled start interruption")
            if behavior[0] == "crash":
                self.enter_original()
                return
            self.ident = 7
            self.alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            self.joins += 1

        def enter_original(self):
            self.ident, self.alive = 7, True
            self.target()
            self.alive = False

    monkeypatch.setattr(worker.asyncio, "new_event_loop", lambda: loop)
    monkeypatch.setattr(worker.asyncio, "set_event_loop", lambda loop: None)
    monkeypatch.setattr(worker.threading, "Thread", Thread)
    monkeypatch.setattr(worker.threading, "Event", Flag)
    return loop, created, trace, behavior


def test_ready_failure_retains_before_start_then_joins_late_original(construction):
    loop, threads, trace, _ = construction
    retained = []
    core = Executor()

    def retain(owner):
        trace.append("retained")
        retained.append(owner)

    with pytest.raises(LocalDeviceFailure):
        worker.LocalMediaWorker(
            core, decoder_executable=Path(__file__).resolve(), retain_owner=retain
        )
    assert trace == ["retained", "start"]
    owner = retained[0]
    assert owner.shutdown() is False and not loop.closed
    threads[0].enter_original()
    assert owner.shutdown() is True
    assert loop.closed and threads[0].joins >= 1 and core.calls == 1


def test_interrupted_start_without_ident_never_implies_not_created(construction):
    loop, threads, _, behavior = construction
    behavior[0] = "interrupted"
    retained = []
    with pytest.raises(InterruptedError):
        worker.LocalMediaWorker(
            Executor(),
            decoder_executable=Path(__file__).resolve(),
            retain_owner=retained.append,
        )
    assert threads[0].ident is None and not threads[0].is_alive()
    assert retained[0].shutdown() is False
    assert not loop.closed
    threads[0].enter_original()
    assert retained[0].shutdown() is True


def test_hook_failure_proves_no_thread_start_and_closes_original_loop(construction):
    loop, threads, _, _ = construction
    retained = []
    error = RuntimeError("controlled hook failure")

    def retain(owner):
        retained.append(owner)
        raise error

    with pytest.raises(RuntimeError) as caught:
        worker.LocalMediaWorker(
            Executor(), decoder_executable=Path(__file__).resolve(), retain_owner=retain
        )
    assert caught.value is error
    assert threads[0].starts == 0 and loop.closed
    assert retained[0].shutdown() is True


def test_constructor_inflight_and_executor_pending_cannot_certify_shutdown(
    construction,
):
    loop, threads, _, _ = construction
    core = Executor()
    core.settled = False
    retained = []
    during = []

    def retain(owner):
        retained.append(owner)
        during.append(owner.shutdown())

    with pytest.raises(LocalDeviceFailure):
        worker.LocalMediaWorker(
            core, decoder_executable=Path(__file__).resolve(), retain_owner=retain
        )
    assert during == [False]
    assert threads[0].starts == 0 and loop.closed
    assert retained[0].shutdown() is False
    core.settled = True
    assert retained[0].shutdown() is True


def test_thread_exit_without_original_async_shutdown_stays_uncertain(construction):
    loop, threads, _, behavior = construction
    behavior[0] = "crash"
    retained = []
    core = Executor()
    with pytest.raises(LocalDeviceFailure):
        worker.LocalMediaWorker(
            core,
            decoder_executable=Path(__file__).resolve(),
            retain_owner=retained.append,
        )
    assert loop.closed and not threads[0].is_alive()
    assert retained[0].shutdown() is False
    assert core.calls == 0
