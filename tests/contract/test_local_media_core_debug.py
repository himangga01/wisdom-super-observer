"""Inert structural exception diagnostics; never opens DB, native or listeners."""

import importlib.util
import json
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest
from wso_core.tvt.local_service import LocalDeviceFailure

ROOT = Path(__file__).resolve().parents[2]


def helper_module():
    path = ROOT / "scripts/test-local-devices/core_debug.py"
    assert path.is_file(), "bounded structural executor diagnostics missing"
    spec = importlib.util.spec_from_file_location("inert_core_debug", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_original_call_return_and_exception_identity():
    helper = helper_module()
    written = []
    marker, args, options = (
        object(),
        (object(),),
        {"cancel": object(), "retain_local": object()},
    )
    calls = []

    def original(*given, **kwargs):
        calls.append((given, kwargs))
        return marker

    wrapped = helper.wrap_start(original, written.append, root=ROOT)
    assert wrapped(*args, **options) is marker
    assert calls == [(args, options)] and written == []
    error = LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)

    def denied(*given, **kwargs):
        calls.append((given, kwargs))
        raise error

    wrapped = helper.wrap_start(denied, written.append, root=ROOT)
    with pytest.raises(LocalDeviceFailure) as failure:
        wrapped(*args, **options)
    assert failure.value is error and len(calls) == 2
    assert written[-1]["code"] == "LOCAL_DEVICE_DENIED" and written[-1]["status"] == 404


def test_exact_coordinator_denial_frame_and_private_text_excluded():
    helper = helper_module()
    from wso_core.tvt.local_media_mux_service import DeviceEpochCoordinator

    coordinator = DeviceEpochCoordinator(
        SimpleNamespace(), SimpleNamespace(), SimpleNamespace()
    )
    written = []
    wrapped = helper.wrap_start(coordinator.attach_dedicated, written.append, root=ROOT)
    with pytest.raises(LocalDeviceFailure):
        wrapped(SimpleNamespace(id=None), budget=object())
    frames = written[-1]["frames"]
    assert any(
        frame["module"] == "mux_service"
        and frame["function"] == "attach_dedicated"
        and frame["line"] == 1509
        for frame in frames
    )
    encoded = json.dumps(written)
    assert str(ROOT) not in encoded and "Local device request failed" not in encoded


def test_callback_baseexception_preserves_original_failure():
    helper = helper_module()
    original = LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)

    def denied():
        raise original

    def broken(record):
        raise KeyboardInterrupt("private-message")

    with pytest.raises(LocalDeviceFailure) as failure:
        helper.wrap_start(denied, broken, root=ROOT)()
    assert failure.value is original


def test_diagnostic_clock_failure_cannot_prevent_original_call(monkeypatch):
    helper = helper_module()
    marker, calls = object(), []

    def original():
        calls.append(1)
        return marker

    def broken_clock():
        raise RuntimeError("private-clock")

    monkeypatch.setattr(helper, "time", SimpleNamespace(monotonic=broken_clock))
    assert helper.wrap_start(original, lambda record: None, root=ROOT)() is marker
    assert calls == [1]


def test_inside_handler_normalization_preserves_bounded_context():
    helper = helper_module()
    original = LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)

    def normalized():
        try:
            raise original
        except LocalDeviceFailure:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404) from None

    written = []
    with pytest.raises(LocalDeviceFailure):
        helper.wrap_start(normalized, written.append, root=ROOT)()
    assert written[-1]["chain_count"] == 2
    assert "normalized" not in json.dumps(written)


def test_normalization_context_and_cycle_bounds():
    helper = helper_module()
    from wso_core.tvt.local_admission import _boundary

    @_boundary
    def denied():
        raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)

    written = []
    with pytest.raises(LocalDeviceFailure):
        helper.wrap_start(denied, written.append, root=ROOT)()
    assert written[-1]["chain_count"] == 1
    assert any(
        frame["module"] == "local_admission" and frame["function"] == "checked"
        for frame in written[-1]["frames"]
    )
    first = LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
    second = RuntimeError("private-message")
    first.__context__, second.__context__ = second, first
    record = helper.project_failure(first, root=ROOT, elapsed_ms=1)
    assert record["chain_count"] == 2 and record["truncated"] is True
    assert "private-message" not in json.dumps(record)


def test_total_frames_and_exception_chain_are_bounded():
    helper = helper_module()
    errors = [RuntimeError("private-message") for _ in range(10)]
    for a, b in pairwise(errors):
        a.__cause__ = b
    record = helper.project_failure(errors[0], root=ROOT, elapsed_ms=1)
    assert record["chain_count"] == 4 and record["truncated"] is True

    def recursive(depth):
        if depth:
            recursive(depth - 1)
        raise errors[0]

    written = []
    with pytest.raises(RuntimeError):
        helper.wrap_start(recursive, written.append, root=ROOT)(30)
    assert len(written[-1]["frames"]) <= 8 and written[-1]["truncated"] is True
    assert "recursive" not in json.dumps(written)


def test_closed_codec_rejects_unknown_private_fields_and_caps_concurrent_writes():
    helper = helper_module()
    from concurrent.futures import ThreadPoolExecutor

    record = helper.project_failure(
        LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404), root=ROOT, elapsed_ms=1
    )
    written = []
    sink = helper.BoundedCoreDiagnostics(written.append)
    sink(record | {"filename": "private-path"})
    sink(record | {"exception": "private-name"})
    sink(
        record
        | {
            "frames": [
                {
                    "module": "mux_service",
                    "function": "private-name",
                    "line": 10,
                    "chain": 0,
                }
            ]
        }
    )
    assert written == []
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(sink, [record for _ in range(500)]))
    assert 0 < len(written) <= 128 and sum(map(len, written)) <= 65536
    assert all(json.loads(raw)["status"] == 404 for raw in written)
