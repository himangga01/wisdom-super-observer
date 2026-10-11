"""Offline inner-heartbeat controls; no native, database or browser access."""

import json
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest
from wso_core.tvt.local_media_mux_service import EpochState
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget

from tests.contract.test_local_media_core_state_debug import helper_module
from tests.tvt_parity.test_local_media_mux_service import attached_pair

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("kind", ["public", "unexpected", "malformed"])
def test_inner_refresh_failure_is_queued_before_original_fence_and_reraised(kind):
    helper = helper_module()
    coordinator, admission, provider, _, first, second, _, _ = attached_pair()
    error = (
        LocalDeviceFailure("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504)
        if kind != "unexpected"
        else KeyboardInterrupt("private-heartbeat-message")
    )
    if kind == "malformed":
        error.code = ["private-value"]
    written, calls = [], []
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    original = coordinator._fence
    master = coordinator._viewers[first.id].master

    def fence(record):
        assert record is master
        calls.append(record)
        assert written == [], "hook may enqueue but may not perform writer IO"
        assert any(
            json.loads(raw)["event"] == "HEARTBEAT_EXCEPTION" for raw in sink._queue
        ), "original refresh exception must be queued before original cleanup"
        return original(record)

    def fail_refresh(grant):
        raise error

    coordinator._fence = fence
    admission.refresh_grant = fail_refresh
    callbacks = (provider.prepared.binding_for, provider.prepared.issued_receipt)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(type(error)) as raised:
        coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(2000))
    assert raised.value is error and calls == [master]
    assert master.state is EpochState.QUARANTINED and not master.refreshing
    assert not coordinator.current(first.id) and not coordinator.current(second.id)
    assert callbacks == (
        provider.prepared.binding_for,
        provider.prepared.issued_receipt,
    )
    assert sink.close() is True
    rows = [json.loads(raw) for raw in written]
    failure = next(row for row in rows if row["event"] == "HEARTBEAT_EXCEPTION")
    assert (failure["code"], failure["status"], failure["exception"]) == (
        ("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504, "LocalDeviceFailure")
        if kind == "public"
        else ("UNEXPECTED", 500, "unexpected")
    )
    assert failure["state"]["refreshing"] is True
    assert failure["state"]["master_state"] == "ACTIVE"
    assert failure["chain_count"] == 1
    assert any(
        f["module"] == "mux_service" and f["function"] == "heartbeat"
        for f in failure["frames"]
    )
    assert rows.index(failure) < next(
        i for i, row in enumerate(rows) if row["event"] == "MASTER_FENCE"
    )
    assert "private" not in json.dumps(rows) and str(ROOT) not in json.dumps(rows)
    assert rows[-1]["accepted"] == len(rows) - 1


def test_unrelated_handled_error_never_becomes_heartbeat_failure():
    helper = helper_module()
    calls, written = [], []
    marker, argument, option = object(), object(), object()

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
    try:
        raise RuntimeError("private-unrelated")
    except RuntimeError:
        assert coordinator._fence(argument, option=option) is marker
    assert calls == [((argument,), {"option": option})]
    sink.close()
    assert [json.loads(raw)["event"] for raw in written] == ["MASTER_FENCE", "SUMMARY"]


def test_new_heartbeat_source_does_not_break_existing_close_callchain():
    helper = helper_module()
    namespace = {"capture": lambda: helper.project_callchain(ROOT)}
    exec(  # noqa: S102 - closed inert code with a controlled traceback filename
        compile(
            "def renew():\n    return capture()\n",
            str(ROOT / "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ipc.py"),
            "exec",
        ),
        namespace,
    )
    frames, _ = namespace["renew"]()
    assert frames == []


@pytest.mark.parametrize(
    "path,label,function",
    [
        (
            "packages/core/src/wso_core/tvt/local_media_mux_service.py",
            "mux_service",
            "_check_replacement",
        ),
        (
            "packages/core/src/wso_core/tvt/local_media_mux_admission.py",
            "mux_admission",
            "refresh_grant",
        ),
        (
            "packages/core/src/wso_core/tvt/local_media_mux_admission.py",
            "mux_admission",
            "_refresh_current_grant",
        ),
        (
            "packages/core/src/wso_core/tvt/local_media_mux_admission.py",
            "mux_admission",
            "_record",
        ),
        (
            "packages/core/src/wso_core/tvt/local_media_mux_admission.py",
            "mux_admission",
            "_observe",
        ),
        (
            "packages/core/src/wso_core/tvt/local_media_mux_admission.py",
            "mux_admission",
            "_sql",
        ),
        (
            "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py",
            "mux_provider",
            "refresh_grants",
        ),
        (
            "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py",
            "mux_provider",
            "authority_operation",
        ),
        (
            "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py",
            "mux_provider",
            "replace_grant",
        ),
        (
            "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py",
            "mux_provider",
            "heartbeat",
        ),
        (
            "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ipc.py",
            "mux_ipc",
            "renew",
        ),
        (
            "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ipc.py",
            "mux_ipc",
            "_rpc",
        ),
        (
            "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_ipc.py",
            "mux_ipc",
            "_check",
        ),
    ],
)
def test_fixed_source_function_is_projected_but_other_source_is_omitted(
    path, label, function
):
    helper = helper_module()
    error = RuntimeError("private-error")
    namespace = {"error": error}
    source = f"def {function}():\n    raise error\n"
    exec(compile(source, str(ROOT / path), "exec"), namespace)  # noqa: S102
    try:
        namespace[function]()
    except RuntimeError as original:
        projection = helper.project_heartbeat_failure(original, root=ROOT)
    assert projection["frames"] == [
        {"module": label, "function": function, "line": 2, "chain": 0}
    ]
    assert helper.project_heartbeat_failure(error, root=ROOT / "other")["frames"] == []


def test_original_fence_error_keeps_identity_after_inner_failure_is_queued():
    helper = helper_module()
    coordinator, admission, _, _, _, _, _, _ = attached_pair()
    original, cleanup_error = (
        LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404),
        SystemExit("private-cleanup"),
    )
    calls, written = [], []

    def fail_refresh(grant):
        raise original

    def fence(*args, **kwargs):
        calls.append((args, kwargs))
        raise cleanup_error

    admission.refresh_grant = fail_refresh
    coordinator._fence = fence
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(SystemExit) as raised:
        coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(2000))
    assert raised.value is cleanup_error and len(calls) == 1
    assert sink.close() is True
    failure = json.loads(written[0])
    assert (
        failure["event"] == "HEARTBEAT_EXCEPTION"
        and failure["code"] == "LOCAL_DEVICE_DENIED"
    )


@pytest.mark.parametrize("failure", ["projection", "capture"])
def test_inner_diagnostic_failure_preserves_cleanup_and_original_exception(
    monkeypatch, failure
):
    helper = helper_module()
    coordinator, admission, _, _, first, _, _, _ = attached_pair()
    error = SystemExit("private-original")

    def failed(grant):
        raise error

    def broken(*args, **kwargs):
        raise KeyboardInterrupt("private-diagnostic")

    admission.refresh_grant = failed
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)
    if failure == "projection":
        monkeypatch.setattr(helper, "project_heartbeat_failure", broken)
    else:
        monkeypatch.setattr(sink, "capture", broken)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(SystemExit) as raised:
        coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(2000))
    assert raised.value is error
    assert coordinator._viewers[first.id].master.state is EpochState.QUARANTINED
    assert sink.status()["diagnostic_failures"] > 0


def test_closed_heartbeat_projection_bounds_chain_and_counts_unknown_frames():
    helper = helper_module()
    errors = [RuntimeError("private-message") for _ in range(6)]
    for current, following in pairwise(errors):
        current.__cause__ = following
    record = helper.project_heartbeat_failure(errors[0], root=ROOT)
    assert record["chain_count"] == 4 and record["truncated"] is True
    errors[1].__cause__ = errors[0]
    record = helper.project_heartbeat_failure(errors[0], root=ROOT)
    assert record["chain_count"] == 2 and record["truncated"] is True

    def unknown(depth):
        if depth:
            unknown(depth - 1)
        raise errors[0]

    try:
        unknown(12)
    except RuntimeError as error:
        record = helper.project_heartbeat_failure(error, root=ROOT)
    assert record["frames"] == [] and record["truncated"] is True
    assert "private" not in json.dumps(record)


def test_heartbeat_codec_rejects_unchecked_bytes_and_reports_queue_caps_and_failures():
    helper = helper_module()
    coordinator, admission, _, _, _, _, _, _ = attached_pair()
    error = LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)

    def failed(grant):
        raise error

    admission.refresh_grant = failed
    written = []
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(LocalDeviceFailure):
        coordinator.heartbeat("heartbeat", budget=LocalVerifyBudget(2000))
    sink.publish()
    row = next(
        json.loads(raw)
        for raw in written
        if json.loads(raw)["event"] == "HEARTBEAT_EXCEPTION"
    )
    for change in (
        {"code": "private-code"},
        {"status": True},
        {"chain_count": 5},
        {
            "frames": [
                {
                    "module": "mux_service",
                    "function": "heartbeat",
                    "line": 1,
                    "chain": 1,
                }
            ]
        },
        {
            "frames": [
                {"module": "mux_service", "function": "private", "line": 1, "chain": 0}
            ]
        },
        {"private": "value"},
    ):
        with pytest.raises(ValueError):
            helper.checked_record(row | change)
    # Same retained queue budget applies to startup/close and inner failures.
    for _ in range(500):
        sink.capture(
            "HEARTBEAT_EXCEPTION",
            "NONE",
            "EXCEPTION",
            {},
            row["frames"],
            False,
            exception="LocalDeviceFailure",
            failure={"code": "LOCAL_DEVICE_DENIED", "status": 404, "chain_count": 1},
        )
    assert all(type(raw) is bytes for raw in sink._queue)
    assert sink.close() is True
    assert len(written) <= 128 and sum(map(len, written)) <= 65536
    summary = json.loads(written[-1])
    assert summary["omitted"] > 0 and summary["accepted"] + summary["omitted"] == 504
