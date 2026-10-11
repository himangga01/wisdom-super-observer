"""Earliest dedicated maintenance diagnostics remain observational and bounded."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from wso_core.tvt.local_media_mux_admission import SqlMuxAdmission
from wso_core.tvt.local_service import LocalVerifyBudget

from tests.contract.test_local_media_core_state_debug import helper_module
from tests.tvt_parity.test_local_media_mux_service import main_setup

ROOT = Path(__file__).resolve().parents[2]


def test_real_direct_dedicated_false_preserves_preclose_refresh_facts():
    helper = helper_module()
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    owned.master.refreshing = True
    original = coordinator._current_dedicated
    rows = []
    sink = helper.BoundedCoreStateDiagnostics(rows.append)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert original(owned) is False
    assert coordinator._current_dedicated(owned) is False
    assert coordinator._current_dedicated(owned) is False
    assert not owned.stopping and not owned.closing and not rows
    assert len(sink._queue) == 1
    row = json.loads(sink._queue[0])
    assert row["event"] == "DEDICATED_CURRENT"
    assert row["state"]["refreshing_at_entry"] is True
    assert row["state"]["refresh_changed"] is False
    assert row["state"]["stopping"] is False
    assert sink.close()


def test_first_dedicated_close_is_recorded_before_original_flags_change():
    helper = helper_module()
    coordinator, admission, provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    rows = []
    sink = helper.BoundedCoreStateDiagnostics(rows.append)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert coordinator._close_dedicated(owned) is False
    row = json.loads(sink._queue[0])
    assert row["event"] == "DEDICATED_CLOSE" and row["result"] == "ENTRY"
    assert row["state"]["stopping"] is False
    assert owned.stopping and not rows
    provider.main.can_close = True
    coordinator._close_dedicated(owned)
    assert len(sink._queue) == 1
    assert sink.close()


def test_exact_sql_retention_false_adds_no_authority_or_sql_call():
    helper = helper_module()
    coordinator, _admission, _provider, _budget, _first, main, _now = main_setup()
    admission = object.__new__(SqlMuxAdmission)
    admission._sql = lambda *args: (_ for _ in ()).throw(
        AssertionError("unexpected SQL")
    )
    original = admission.current_main_retention
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert original(main, object(), object()) is False
    assert admission.current_main_retention(main, object(), object()) is False
    assert admission.current_main_retention(main, object(), object()) is False
    row = json.loads(sink._queue[0])
    assert row["event"] == "MAIN_RETENTION_CURRENT"
    assert row["state"]["stopping"] is False
    assert len(sink._queue) == 1
    assert sink.close()


def test_substituted_dedicated_method_is_not_wrapped():
    helper = helper_module()
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    calls = []

    def substituted(value, **kwargs):
        calls.append((value, kwargs))
        return False

    coordinator._current_dedicated = substituted
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert coordinator._current_dedicated is substituted
    assert coordinator._current_dedicated(main, budget=LocalVerifyBudget(1000)) is False
    assert len(calls) == 1 and not sink._queue
    assert sink.close()


def test_refresh_change_is_captured_at_return_before_delayed_publication():
    helper = helper_module()
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    observe = admission.current_main_retention

    def crossed(*args):
        accepted = observe(*args)
        owned.master.refresh_version += 1
        owned.master.refreshing = True
        return accepted

    admission.current_main_retention = crossed
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert coordinator._current_dedicated(owned) is False
    owned.master.refreshing = False
    row = json.loads(sink._queue[0])
    assert row["state"]["refreshing_at_entry"] is False
    assert row["state"]["refresh_changed"] is True
    assert row["state"]["refreshing"] is True
    assert row["state"]["stopping"] is False
    assert sink.close()


@pytest.mark.parametrize("fault", ["first", "capture"])
def test_optional_sink_failure_preserves_actual_method_result(fault):
    helper = helper_module()
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    owned.master.refreshing = True
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)

    def broken(*args, **kwargs):
        raise KeyboardInterrupt("PRIVATE_DIAGNOSTIC_TEXT")

    setattr(sink, fault, broken)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    assert coordinator._current_dedicated(owned) is False
    assert not owned.stopping and not sink._queue
    assert sink.close()


def test_dedicated_false_saturation_preserves_existing_caps():
    helper = helper_module()
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    values = [replace(owned, stopping=True) for _ in range(300)]
    for value in values:
        assert coordinator._current_dedicated(value) is False
    assert len(sink._seen) <= 127 and len(sink._queue) <= 128
    assert sum(len(raw) for raw in sink._queue) <= 64 * 1024
    assert sink._counts["omitted"] > 0
    assert sink.close()


def test_actual_bound_method_error_keeps_identity_and_single_original_call():
    helper = helper_module()
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    error = KeyboardInterrupt("PRIVATE_ORIGINAL_ERROR")
    calls = []

    class BrokenLock:
        def __enter__(self):
            calls.append("enter")
            raise error

        def __exit__(self, *args):
            return False

    coordinator._lock = BrokenLock()
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(KeyboardInterrupt) as caught:
        coordinator._current_dedicated(owned)
    assert caught.value is error and calls == ["enter"]
    assert "PRIVATE_ORIGINAL_ERROR" not in str(list(sink._queue))
    assert sink.close()
