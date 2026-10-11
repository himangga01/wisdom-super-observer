"""Offline shared read initiating-failure diagnostics."""

import ast
import json
from itertools import pairwise
from pathlib import Path

import pytest
from wso_core.tvt.local_live import LiveError
from wso_core.tvt.local_live_mux import MultiplexLiveCodec
from wso_core.tvt.local_media_mux_service import MuxMediaExecutor
from wso_core.tvt.local_media_mux_types import (
    IngressChunk,
    IngressSpan,
    MuxEpochIdentity,
)
from wso_core.tvt.local_service import LocalDeviceFailure

from tests.contract.test_local_media_core_state_debug import helper_module
from tests.tvt_parity.test_local_media_mux_service import attached_pair

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("kind", ["public", "unexpected", "validation"])
def test_real_read_catch_queues_original_failure_before_original_viewer_close(kind):
    helper = helper_module()
    coordinator, admission, _, _, first, _, handle, _ = attached_pair()
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    error = (
        LocalDeviceFailure("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504)
        if kind == "public"
        else KeyboardInterrupt("private-read-error")
    )
    original_close, calls, written = coordinator._close_viewer, [], []
    sink = helper.BoundedCoreStateDiagnostics(written.append)
    callbacks = handle.current_grant, handle.issued_receipt

    def close(*args, **kwargs):
        calls.append((args, kwargs))
        assert written == []
        assert json.loads(sink._queue[0])["event"] == "VIEWER_READ_EXCEPTION", (
            "initiating read failure must precede cleanup"
        )
        return original_close(*args, **kwargs)

    def read(**kwargs):
        raise error

    coordinator._close_viewer = close
    if kind == "validation":
        handle.batch = (object(),)
    else:
        handle.read_frames = read
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(
        LocalDeviceFailure if kind == "validation" else type(error)
    ) as raised:
        executor.read_mux_frames(
            first.id, max_frames=1, max_bytes=1024, deadline_ms=1000
        )
    if kind != "validation":
        assert raised.value is error
    assert len(calls) == 1 and handle.stopped
    assert callbacks == (handle.current_grant, handle.issued_receipt)
    assert sink.close() is True
    rows = [json.loads(raw) for raw in written]
    row = rows[0]
    assert (row["code"], row["status"], row["exception"]) == (
        ("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504, "LocalDeviceFailure")
        if kind == "public"
        else ("LOCAL_DEVICE_PROTOCOL_INVALID", 502, "LocalDeviceFailure")
        if kind == "validation"
        else ("UNEXPECTED", 500, "unexpected")
    )
    assert row["state"]["closing"] is False
    assert any(frame["function"] == "read_mux_frames" for frame in row["frames"])
    for changed in (
        row | {"code": "private-code"},
        row | {"private": "text"},
        row
        | {
            "frames": [
                {
                    "module": "mux_service",
                    "function": "heartbeat",
                    "line": 1,
                    "chain": 0,
                }
            ]
        },
    ):
        with pytest.raises(ValueError):
            helper.checked_record(changed)
    assert rows[1]["event"] == "VIEWER_CLOSE"
    assert "private" not in json.dumps(rows) and str(ROOT) not in json.dumps(rows)
    assert all(type(raw) is bytes for raw in written)


@pytest.mark.parametrize("within_read", [False, True])
def test_normal_close_under_unrelated_handled_error_never_emits_read_failure(
    within_read,
):
    helper = helper_module()
    coordinator, admission, _, _, first, _, handle, _ = attached_pair()
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    sink, written = (
        helper.BoundedCoreStateDiagnostics(lambda raw: written.append(raw)),
        [],
    )
    helper.install_hooks(admission, coordinator, sink, root=ROOT)

    def read(**kwargs):
        assert executor.close(first.id) is True
        return ()

    try:
        raise RuntimeError("private-unrelated")
    except RuntimeError:
        if within_read:
            handle.read_frames = read
            # The success path still performs its normal authority check.
            with pytest.raises(LocalDeviceFailure):
                executor.read_mux_frames(
                    first.id, max_frames=1, max_bytes=1024, deadline_ms=1000
                )
        else:
            assert executor.close(first.id) is True
    sink.close()
    if within_read:
        # The later real read guard may initiate a separate legitimate close;
        # the first normal close must remain first and have no read-exception prefix.
        assert json.loads(written[0])["event"] == "VIEWER_CLOSE"
    assert all(json.loads(raw)["event"] != "VIEWER_READ_EXCEPTION" for raw in written)


@pytest.mark.parametrize("fault", ["projection", "capture", "cleanup"])
def test_read_diagnostic_fault_preserves_original_close_and_error(monkeypatch, fault):
    helper = helper_module()
    coordinator, admission, _, _, first, _, handle, _ = attached_pair()
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    original_error, cleanup_error = (
        SystemExit("private-read"),
        KeyboardInterrupt("private-close"),
    )
    calls = []
    original_close = coordinator._close_viewer
    sink = helper.BoundedCoreStateDiagnostics(lambda _: None)

    def read(**kwargs):
        raise original_error

    def close(*args, **kwargs):
        calls.append((args, kwargs))
        if fault == "cleanup":
            raise cleanup_error
        return original_close(*args, **kwargs)

    def broken(*args, **kwargs):
        raise KeyboardInterrupt("private-diagnostic")

    handle.read_frames, coordinator._close_viewer = read, close
    if fault == "projection":
        monkeypatch.setattr(helper, "project_read_failure", broken)
    elif fault == "capture":
        monkeypatch.setattr(sink, "capture", broken)
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(
        type(cleanup_error if fault == "cleanup" else original_error)
    ) as raised:
        executor.read_mux_frames(
            first.id, max_frames=1, max_bytes=1024, deadline_ms=1000
        )
    assert raised.value is (cleanup_error if fault == "cleanup" else original_error)
    assert len(calls) == 1
    if fault != "cleanup":
        assert handle.stopped and sink.status()["diagnostic_failures"] > 0


def test_read_projection_closed_allowlist_chain_and_unknown_frame_budget():
    helper = helper_module()
    errors = [RuntimeError("private-text") for _ in range(6)]
    for error, cause in pairwise(errors):
        error.__cause__ = cause
    projection, initiating = helper.project_read_failure(errors[0], root=ROOT)
    assert projection["chain_count"] == 4 and projection["truncated"] is True
    assert initiating is False

    def unknown(depth):
        if depth:
            unknown(depth - 1)
        raise errors[0]

    try:
        unknown(40)
    except RuntimeError as error:
        projection, initiating = helper.project_read_failure(error, root=ROOT)
    assert projection["frames"] == [] and projection["truncated"] is True
    assert initiating is False and "private" not in json.dumps(projection)


def test_actual_codec_rejecting_feed_line_survives_deep_wrappers_and_read_close():
    helper = helper_module()
    coordinator, admission, _, _, first, _, handle, _ = attached_pair()
    executor = MuxMediaExecutor(admission, coordinator, monitor_interval=0)
    codec = MultiplexLiveCodec(
        epoch=MuxEpochIdentity(7, bytes([1]) * 16),
        peer_capability=6,
        authorize=lambda _: True,
    )
    written = []
    sink = helper.BoundedCoreStateDiagnostics(written.append)

    def unknown(depth):
        if depth:
            return unknown(depth - 1)
        return codec.feed(IngressChunk(b"", IngressSpan(1, 1)), generation=8)

    def read(**kwargs):
        try:
            return unknown(12)
        except LiveError:
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502) from None

    handle.read_frames = read
    helper.install_hooks(admission, coordinator, sink, root=ROOT)
    with pytest.raises(LocalDeviceFailure):
        executor.read_mux_frames(
            first.id, max_frames=1, max_bytes=1024, deadline_ms=1000
        )
    sink.close()
    failure = json.loads(written[0])
    assert failure["event"] == "VIEWER_READ_EXCEPTION" and failure["chain_count"] == 2
    source = ast.parse((ROOT / helper.SOURCES["mux_codec"]).read_bytes())
    feed_method = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef) and node.name == "_feed"
    )
    rejection_line = min(
        node.lineno for node in ast.walk(feed_method) if isinstance(node, ast.Raise)
    )
    assert {
        "module": "mux_codec",
        "function": "_feed",
        "line": rejection_line,
        "chain": 1,
    } in failure["frames"], (
        "actual codec generation rejection must survive outer/helper frames"
    )
    assert len(failure["frames"]) <= 8 and handle.stopped


def test_read_keeps_deepest_eight_allowlisted_frames_and_marks_output_reduction():
    helper = helper_module()
    namespace = {}
    exec(  # noqa: S102 - fixed inert traceback fixture, no dynamic external code
        compile(
            "def _feed(depth):\n    if depth:\n        return _feed(depth - 1)\n    raise RuntimeError('private')\n",
            str(ROOT / "packages/core/src/wso_core/tvt/local_live_mux.py"),
            "exec",
        ),
        namespace,
    )
    try:
        namespace["_feed"](12)
    except RuntimeError as error:
        failure, _ = helper.project_read_failure(error, root=ROOT)
    assert len(failure["frames"]) == 8
    assert failure["frames"][-1] == {
        "module": "mux_codec",
        "function": "_feed",
        "line": 4,
        "chain": 0,
    }
    assert failure["truncated"] is True and "private" not in json.dumps(failure)


def test_read_inspection_budget_stops_before_known_codec_leaf_beyond_32_frames():
    helper = helper_module()
    codec = MultiplexLiveCodec(
        epoch=MuxEpochIdentity(7, bytes([1]) * 16),
        peer_capability=6,
        authorize=lambda _: True,
    )

    def unknown(depth):
        if depth:
            return unknown(depth - 1)
        return codec.feed(IngressChunk(b"", IngressSpan(1, 1)), generation=8)

    try:
        unknown(40)
    except LiveError as error:
        failure, _ = helper.project_read_failure(error, root=ROOT)
    assert failure["frames"] == [] and failure["truncated"] is True
