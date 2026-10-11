"""Offline close-origin diagnostics: no SQL, native, process or browser IO."""

import importlib.util
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest
from wso_core.tvt.local_media_mux_admission import SqlMuxAdmission, _Record
from wso_core.tvt.local_media_mux_service import EpochState
from wso_core.tvt.local_media_mux_types import _GRANT_SEAL

from tests.tvt_parity.test_local_media_mux_service import attached_pair

ROOT = Path(__file__).resolve().parents[2]


def helper_module():
    path = ROOT / "scripts/test-local-devices/core_state_debug.py"
    assert path.is_file(), "runtime-only close-origin diagnostics missing"
    spec = importlib.util.spec_from_file_location("inert_core_state_debug", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rig():
    coordinator, _, provider, _, first, _, handle, _ = attached_pair()
    owned = coordinator._viewers[first.id]
    grant = owned.grant
    admission = object.__new__(SqlMuxAdmission)
    admission._mux_lock = Lock()
    admission._clock = time.monotonic
    admission._mux_closed = False
    admission._records = {
        id(grant): _Record(
            grant, "private-authority", owned.master.master_id, first.native_generation
        )
    }
    admission._denied_masters = set()
    admission._issuer = grant._authority
    return coordinator, admission, provider, first, handle, owned


def test_bound_hooks_preserve_original_args_result_exception_and_success_quiet():
    helper = helper_module()
    calls, written = [], []
    marker, argument, option = object(), object(), object()
    error = KeyboardInterrupt("private-message")

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return marker

    coordinator = SimpleNamespace(
        current=original, _fence=original, _close_viewer=original
    )
    admission = SimpleNamespace(
        current_transport=original, current_slot=original, current_viewer=original
    )
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    for method in (
        coordinator.current,
        admission.current_transport,
        admission.current_slot,
        admission.current_viewer,
    ):
        assert method(argument, budget=option) is marker
    assert written == [] and calls == [((argument,), {"budget": option})] * 4

    def denied(*args, **kwargs):
        calls.append((args, kwargs))
        raise error

    coordinator.current = denied
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(KeyboardInterrupt) as failure:
        coordinator.current(argument, budget=option)
    assert failure.value is error and len(calls) == 5
    sink.close()
    rows = [json.loads(raw) for raw in written]
    assert (
        rows[0]["event"] == "COORDINATOR_CURRENT" and rows[0]["result"] == "EXCEPTION"
    )
    assert "private-message" not in str(rows)


def test_real_coordinator_denial_and_fence_capture_original_origin_and_preclose_state():
    helper = helper_module()
    coordinator, admission, provider, _, first, second, handle, other = attached_pair()
    original_binding, original_receipt = (
        provider.prepared.binding_for,
        provider.prepared.issued_receipt,
    )
    original_view_receipt = handle.issued_receipt
    written = []
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert coordinator.current(first.id) is True
    admission.denied = True
    coordinator.sweep()
    assert handle.stopped and other.stopped and provider.prepared.closing
    assert written == [], "authority call must only enqueue, never write"
    sink.close()
    rows = [json.loads(raw) for raw in written]
    fence = next(row for row in rows if row["event"] == "MASTER_FENCE")
    close = next(row for row in rows if row["event"] == "VIEWER_CLOSE")
    assert any(
        f["module"] == "mux_service" and f["function"] == "sweep"
        for f in fence["frames"]
    )
    assert any(f["function"] == "_fence" for f in close["frames"])
    assert close["state"]["starting"] is False and close["state"]["stopping"] is True
    assert provider.prepared.binding_for == original_binding
    assert provider.prepared.issued_receipt == original_receipt
    assert handle.issued_receipt == original_view_receipt
    assert all("id" not in row["state"] for row in rows)
    assert not coordinator.current(first.id) and not coordinator.current(second.id)


def test_close_entry_is_first_per_original_and_precedes_original_call():
    helper = helper_module()
    coordinator, _, _, first, _, owned = rig()
    entry_states, written = [], []

    def original(given):
        assert given is owned
        entry_states.append(given.starting)
        given.starting = False
        return True

    owned.starting = True
    coordinator._close_viewer = original
    admission = SimpleNamespace(
        current_transport=lambda *_: True,
        current_slot=lambda *_: True,
        current_viewer=lambda *_: True,
    )
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert coordinator._close_viewer(owned) is True
    assert coordinator._close_viewer(owned) is True
    sink.close()
    rows = [json.loads(raw) for raw in written]
    closes = [row for row in rows if row["event"] == "VIEWER_CLOSE"]
    assert len(closes) == 1 and closes[0]["state"]["starting"] is True
    assert entry_states == [True, False] and first.id in coordinator._viewers


def test_superseded_grant_false_reports_refresh_overlap_without_fencing_current():
    helper = helper_module()
    coordinator, admission, _, first, _, owned = rig()
    old = owned.grant
    fresh = replace(old, expires_monotonic=old.expires_monotonic + 1, _seal=_GRANT_SEAL)
    admission._records[id(old)].closed = True
    admission._records[id(fresh)] = _Record(
        fresh, "private-authority", owned.master.master_id, first.native_generation
    )
    owned.grant = fresh
    owned.master.refreshing = True
    written = []
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert admission.current_viewer(old) is False
    assert (
        admission._denied_masters == set() and owned.master.state is EpochState.ACTIVE
    )
    sink.close()
    row = next(
        json.loads(raw)
        for raw in written
        if json.loads(raw)["event"] == "GRANT_CURRENT"
    )
    assert row["purpose"] == "VIEWER"
    assert row["state"]["registered"] is True and row["state"]["closed"] is True
    assert (
        row["state"]["holder_replaced"] is True and row["state"]["refreshing"] is True
    )
    assert row["state"]["snapshot_atomic"] is False


@pytest.mark.parametrize("failure", ["snapshot", "clock", "sink"])
def test_diagnostic_baseexception_cannot_change_original_false_or_exception(
    monkeypatch, failure
):
    helper = helper_module()
    written, calls = [], []
    error = SystemExit("private-error")

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 2:
            raise error
        return False

    def broken(*args, **kwargs):
        raise KeyboardInterrupt("private-diagnostic")

    sink = helper.BoundedCoreStateDiagnostics(written.append)
    coordinator = SimpleNamespace(
        current=original, _fence=original, _close_viewer=original
    )
    admission = SimpleNamespace(
        current_transport=original, current_slot=original, current_viewer=original
    )
    if failure == "snapshot":
        monkeypatch.setattr(helper, "snapshot_state", broken)
    elif failure == "clock":
        monkeypatch.setattr(helper, "time", SimpleNamespace(monotonic=broken))
    else:
        monkeypatch.setattr(sink, "capture", broken)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert coordinator.current(object()) is False
    with pytest.raises(SystemExit) as raised:
        coordinator.current(object())
    assert raised.value is error and len(calls) == 2


def test_closed_codec_rejects_private_fields_wrong_types_and_excess_chain():
    helper = helper_module()
    written = []
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    sink.capture("COORDINATOR_CURRENT", "NONE", "FALSE", {}, [], False)
    sink.close()
    row = json.loads(written[0])
    for candidate in (
        row | {"filename": "private"},
        row | {"event": "private"},
        row | {"state": {"token": "private"}},
        row | {"sequence": True},
        row | {"state": {"registered": 1}},
        row | {"frames": [{"module": "mux_service", "function": "private", "line": 1}]},
        row | {"frames": [{"module": "mux_service", "function": "sweep", "line": -1}]},
        row
        | {"frames": [{"module": "mux_service", "function": "sweep", "line": 1}] * 9},
    ):
        with pytest.raises(ValueError):
            helper.checked_record(candidate)


def test_queue_caps_events_and_bytes_and_summary_reports_omissions():
    helper = helper_module()
    written = []
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    frames = [{"module": "mux_service", "function": "_close_viewer", "line": 20000}] * 8
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda _: sink.capture(
                    "COORDINATOR_CURRENT", "NONE", "FALSE", {}, frames, True
                ),
                range(500),
            )
        )
    assert written == []
    assert sink.close() is True
    assert 1 < len(written) <= 128 and sum(map(len, written)) <= 65536
    rows = [json.loads(raw) for raw in written]
    assert rows[-1]["event"] == "SUMMARY" and rows[-1]["omitted"] > 0
    assert rows[-1]["accepted"] + rows[-1]["omitted"] == 500
    assert [r["sequence"] for r in rows] == list(range(1, len(rows) + 1))


def test_writer_failure_is_bounded_reported_and_never_retried():
    helper = helper_module()
    calls = []

    def broken(raw):
        calls.append(raw)
        raise SystemExit("private-writer")

    sink = helper.BoundedCoreStateDiagnostics(broken)
    sink.capture("COORDINATOR_CURRENT", "NONE", "FALSE", {}, [], False)
    sink.publish()
    sink.publish()
    assert sink.close() is True and sink.close() is True
    assert len(calls) == 2
    assert sink.status()["diagnostic_failures"] == 2 and sink.status()["written"] == 0


def test_publisher_is_retained_joined_and_file_io_never_runs_on_hook_thread():
    helper = helper_module()
    lock, written = Lock(), []

    def writer(raw):
        with lock:
            written.append(raw)

    sink = helper.BoundedCoreStateDiagnostics(writer)
    with lock:
        sink.capture("COORDINATOR_CURRENT", "NONE", "FALSE", {}, [], False)
    sink.start()
    while not sink.close():
        time.sleep(0.01)
    assert sink.status()["publisher_settled"] is True
    assert (
        len(written) == 2 and sink._thread is not None and not sink._thread.is_alive()
    )


def test_fixed_callchain_counts_unknown_frames_and_never_retains_private_names():
    helper = helper_module()

    def private_call(depth):
        if depth:
            return private_call(depth - 1)
        return helper.project_callchain(ROOT)

    frames, truncated = private_call(20)
    assert frames == [] and truncated is True
    assert "private_call" not in str(frames)


def test_native_drain_has_independent_run_budget_across_repeated_queue_drains(
    monkeypatch,
):
    from wso_tvt_bridge.local_live_diagnostics import NativeFirstKeySink

    from tests.contract.test_native_first_key_debug import parent_rig

    helper = helper_module()
    parent, now = parent_rig(monkeypatch)
    now[0] = 110.0
    assert parent._first_frame_current(lambda: True) is False
    record = parent.first_key_snapshot()
    parent.close()
    native_sink, written = NativeFirstKeySink(), []
    owner = helper.BoundedCoreStateDiagnostics(lambda _: None)
    add = getattr(owner, "add_native_sink", None)
    assert add is not None, "owned publisher native drain missing"
    add(native_sink, written.append)
    for _ in range(3):
        for _ in range(128):
            native_sink(record)
        owner.publish()
    assert owner.close() is True
    assert 0 < len(written) <= 128 and sum(map(len, written)) <= 65536
    assert all(json.loads(raw)["event"] == "native_first_key" for raw in written)
    assert owner.status()["native"]["omitted"] > 0
    counts = owner.status()["native"]
    assert counts["accepted"] + counts["omitted"] + counts["queue_dropped"] == 384


def test_publisher_retains_thread_when_start_raises_after_acquisition_and_join_is_uncertain(
    monkeypatch,
):
    from threading import Thread

    helper = helper_module()

    class InterruptedStart(Thread):
        def start(self):
            super().start()
            raise KeyboardInterrupt("private-start")

    monkeypatch.setattr(helper, "Thread", InterruptedStart)
    written = []
    owner = helper.BoundedCoreStateDiagnostics(written.append)
    owner.start()
    original = owner._thread
    assert original is not None and original.ident is not None
    join = original.join

    def uncertain(*args, **kwargs):
        raise SystemExit("private-join")

    monkeypatch.setattr(original, "join", uncertain)
    assert owner.close() is False
    assert owner._thread is original and owner.status()["publisher_settled"] is False
    monkeypatch.setattr(original, "join", join)
    assert owner.close() is True and not original.is_alive()
    assert owner.status()["diagnostic_failures"] == 2


def test_acquired_thread_without_bootstrap_identity_is_not_reported_retired(
    monkeypatch,
):
    from threading import Event, Thread

    helper = helper_module()
    acquired, release, finished = Event(), Event(), Event()

    class InterruptedWait(Event):
        def wait(self, timeout=None):
            raise KeyboardInterrupt("private-start-wait")

    class DelayedBootstrap(Thread):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._started = InterruptedWait()

        def _bootstrap_inner(self):
            acquired.set()
            release.wait()
            try:
                super()._bootstrap_inner()
            finally:
                finished.set()

    monkeypatch.setattr(helper, "Thread", DelayedBootstrap)
    written = []
    owner = helper.BoundedCoreStateDiagnostics(written.append)
    original = None
    try:
        owner.start()
        original = owner._thread
        assert acquired.wait(2), (
            "original platform thread did not reach bootstrap barrier"
        )
        assert original is not None and original.ident is None
        assert original.is_alive() is False
        assert owner.close() is False
        assert owner._thread is original
        assert owner.status()["publisher_settled"] is False and written == []
        assert owner.status()["publisher_start_attempted"] is True
        assert owner.status()["publisher_start_outcome"] == "UNKNOWN"
    finally:
        # Restore the original startup wait and retire the actual acquired thread
        # even when the deliberately RED custody assertion above fails.
        if original is not None:
            original._started.wait = Event.wait.__get__(original._started)
        release.set()
        if original is not None:
            assert finished.wait(2)
            original.join(timeout=2)
            assert not original.is_alive()
    assert owner.close() is True
    assert owner.status()["publisher_settled"] is True
    assert owner.status()["publisher_start_outcome"] == "RETIRED"
    assert len(written) == 1 and json.loads(written[0])["event"] == "SUMMARY"
