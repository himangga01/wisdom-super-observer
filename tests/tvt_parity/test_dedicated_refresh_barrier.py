"""Observe refreshed authority before dedicated native denial."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident

import pytest

from tests.tvt_parity.test_local_media_mux_service import main_setup


@pytest.mark.parametrize("boundary", ["direct", "sweep", "native_supplier"])
@pytest.mark.parametrize("entered", ["before", "during"])
def test_refreshed_state_keeps_dedicated_original(boundary, entered):
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    crossed, release = Event(), Event()
    original = admission.current_main_retention
    reads = []

    def begin_refresh():
        with coordinator._lock:
            owned.master.refreshing = True
            owned.master.refresh_version += 1
            owned.master.refresh_owner = -1
            owned.master.refresh_done.clear()
        crossed.set()

    def observe(*args):
        result = original(*args)
        reads.append(result)
        if entered == "before" and len(reads) == 1:
            begin_refresh()
        return result

    admission.current_main_retention = observe

    class NativeProbe:
        def current(self, *, deadline_monotonic, current):
            if not crossed.is_set():
                begin_refresh()
            result = current()
            assert result, "transient refresh must not reach native denial latch"
            return result

    if boundary == "native_supplier":
        owned.session = NativeProbe()
        admission.current_main_retention = original
    elif entered == "during":
        begin_refresh()

    def operation():
        if boundary == "direct":
            return coordinator._current_dedicated(owned)
        coordinator.sweep()
        return not owned.stopping

    def complete_refresh():
        assert crossed.wait(1) and release.wait(1)
        # Observer cannot hold the registry lock while awaiting this publication.
        with coordinator._lock:
            owned.master.refreshing = False
            owned.master.refresh_version += 1
            owned.master.refresh_owner = None
            owned.master.refresh_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        finisher = pool.submit(complete_refresh)
        observer = pool.submit(operation)
        if boundary == "sweep" and entered == "during":
            release.set()  # Existing sweep safely skips an already active refresh.
        else:
            assert crossed.wait(1)
            time.sleep(0.02)
            assert not observer.done()
            release.set()
        assert observer.result(timeout=1) is True
        finisher.result(timeout=1)
    assert not owned.stopping and coordinator._current_dedicated(owned) is True
    admission.current = lambda lease: False
    assert coordinator._current_dedicated(owned) is False


@pytest.mark.parametrize("stop", ["main", "shutdown", "revocation"])
def test_refresh_wait_denies_real_stop_or_revocation(stop):
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    owned.master.refreshing = True
    owned.master.refresh_version += 1
    owned.master.refresh_done.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        observer = pool.submit(coordinator._current_dedicated, owned)
        time.sleep(0.02)
        assert not observer.done()
        with coordinator._lock:
            if stop == "main":
                owned.stopping = True
            elif stop == "shutdown":
                coordinator._closed = True
            else:
                admission.current = lambda lease: False
            owned.master.refreshing = False
            owned.master.refresh_version += 1
            owned.master.refresh_done.set()
        assert observer.result(timeout=1) is False


def test_refresh_owner_never_waits_on_itself():
    coordinator, _admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    owned.master.refreshing = True
    owned.master.refresh_owner = get_ident()
    owned.master.refresh_done.clear()
    assert coordinator._current_dedicated(owned) is False


def test_direct_wait_preserves_caller_total_deadline():
    coordinator, _admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    owned.master.refreshing = True
    owned.master.refresh_done.clear()
    began = time.monotonic()
    assert (
        coordinator._current_dedicated(owned, deadline_monotonic=began + 0.04) is False
    )
    assert time.monotonic() - began < 0.25


def test_slow_valid_observation_cannot_outlive_the_callers_deadline():
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    original = admission.current_main_retention

    def slow(*args):
        time.sleep(0.04)
        return original(*args)

    admission.current_main_retention = slow
    assert (
        coordinator._current_dedicated(
            owned, deadline_monotonic=time.monotonic() + 0.02
        )
        is False
    )
