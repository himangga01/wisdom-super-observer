"""Original grant-refresh failure survives admission boundary sanitization."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from wso_core.tvt.local_media_mux_admission import _Record
from wso_core.tvt.local_service import LocalDeviceFailure

from tests.contract.test_local_media_core_state_debug import helper_module, rig

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("purpose", ["TRANSPORT", "SLOT_RETENTION", "VIEWER"])
def test_actual_sql_refresh_inner_line_queued_before_outer_boundary(purpose):
    helper = helper_module()
    coordinator, admission, _, _, _, owned = rig()
    grant = (
        owned.master.transport
        if purpose == "TRANSPORT"
        else next(iter(owned.master.slots.values())).grant
        if purpose == "SLOT_RETENTION"
        else owned.grant
    )
    admission._issuer = grant._authority
    native = admission._records[id(owned.grant)].native
    admission._records = {
        id(grant): _Record(grant, "synthetic-authority", owned.master.master_id, native)
    }
    calls, written = [], []

    def observe(record):
        calls.append(record)

    admission._observe = observe
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(LocalDeviceFailure) as failure:
        admission.refresh_grant(grant)
    assert failure.value.__context__ is None, "outer boundary must stay sanitized"
    assert len(calls) == 1 and written == []
    assert len(sink._queue) == 1, "inner failure must be queued before sanitization"
    row = json.loads(sink._queue[0])
    assert row["event"] == "GRANT_REFRESH_EXCEPTION" and row["purpose"] == purpose
    assert row["state"] == {} and row["code"] == "LOCAL_DEVICE_DENIED"
    assert any(f["function"] == "_refresh_current_grant" for f in row["frames"])
    assert "synthetic-authority" not in str(row)
    # Same original grant is bounded to its first initiating failure.
    with pytest.raises(LocalDeviceFailure):
        admission.refresh_grant(grant)
    assert len(sink._queue) == 1 and len(calls) == 1
    assert sink.close()


def test_record_expiry_inner_line_preserved_without_sql_observation():
    helper = helper_module()
    coordinator, admission, _, _, _, owned = rig()
    admission._clock = lambda: owned.grant.expires_monotonic + 1
    admission._observe = lambda _: pytest.fail(
        "diagnostics must add no SQL/current call"
    )
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(LocalDeviceFailure):
        admission.refresh_grant(owned.grant)
    assert len(sink._queue) == 1
    row = json.loads(sink._queue[0])
    assert any(f["function"] == "_record" for f in row["frames"])
    assert row["state"] == {} and row["purpose"] == "VIEWER"
    assert sink.close()


@pytest.mark.parametrize("broken", ["first", "capture"])
def test_optional_sink_fault_keeps_original_refresh_error(broken):
    helper = helper_module()
    coordinator, admission, _, _, _, owned = rig()
    admission._clock = lambda: owned.grant.expires_monotonic + 1
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)

    def fail(*args, **kwargs):
        raise KeyboardInterrupt("PRIVATE_DEBUG_TEXT")

    setattr(sink, broken, fail)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(LocalDeviceFailure) as failure:
        admission.refresh_grant(owned.grant)
    assert failure.value.code == "LOCAL_DEVICE_DENIED"
    assert sink._counts["diagnostic_failures"] == 1
    assert sink.close()


def test_actual_successful_refresh_returns_original_fresh_grant_without_trace():
    helper = helper_module()
    coordinator, admission, _, _, _, owned = rig()
    admission._viewer_custody = {}
    calls = []

    def observe(record):
        calls.append(record)
        return {"expires_at": datetime.now(UTC) + timedelta(seconds=5)}

    admission._observe = observe
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    fresh = admission.refresh_grant(owned.grant)
    assert fresh is not owned.grant and type(fresh) is type(owned.grant)
    assert len(calls) == 1 and len(sink._queue) == 0
    assert sink.close()
