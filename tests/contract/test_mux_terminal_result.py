"""Private fixed-schema terminal evidence, exact original result custody only."""

import json
import time
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from test_local_live_mux_ipc import rig
from test_local_live_mux_provider import Admission, prepared_inputs, provider_module
from test_local_mux_callback import invoke, key
from wso_tvt_bridge import windows_socket as windows
from wso_tvt_bridge.windows_socket_worker import CallbackOwner, NativeMuxWorker


def test_original_serve_terminal_captures_failed_fifo_without_callback_lock():
    _, _, callback, _, (slot,) = rig()
    for index in range(1, 258):
        invoke(callback, key(slot, index))
    callback.lock = SimpleNamespace(
        acquire=lambda *a: pytest.fail("diagnostics contend with native callback")
    )
    worker = NativeMuxWorker(
        SimpleNamespace(),
        "a" * 32,
        time.monotonic() + 10,
        callback_generation=slot.epoch.generation,
    )
    result = windows.SafeResult("a" * 32)
    worker._original_callback, worker._serve_result = callback, result
    worker.serve(
        SimpleNamespace(),
        7,
        callback,
        {
            "channels": [],
            "peer_capability": 4,
        },
        result=result,
    )
    assert result.mux_terminal_observed and result.mux_callback_failed
    assert result.mux_callback_closed and result.mux_epoch_bound
    assert result.mux_queued_chunks == 256
    assert result.mux_queued_bytes == 256 * len(key(slot))
    assert result.mux_ingress_ordinal == 257  # initial open ACK has ordinal 1
    assert result.mux_capacity_bytes == 1 << 20


def test_cold_callback_terminal_and_foreign_callback_are_separate():
    worker = NativeMuxWorker(
        None, "a" * 32, time.monotonic() + 10, callback_generation=7
    )
    result = windows.SafeResult("a" * 32)
    callback = CallbackOwner(7, 7)
    worker._original_callback, worker._serve_result = callback, result
    worker.capture_terminal(result, CallbackOwner(7, 8))
    assert not result.mux_terminal_observed
    worker.capture_terminal(result, CallbackOwner(7, 7))
    assert not result.mux_terminal_observed
    foreign_result = windows.SafeResult("a" * 32)
    worker.capture_terminal(foreign_result, callback)
    assert not foreign_result.mux_terminal_observed
    callback.mark_failed()
    worker.capture_terminal(result, callback)
    assert result.mux_terminal_observed and result.mux_callback_failed
    assert not result.mux_epoch_bound and result.mux_capacity_bytes == 65536


@pytest.mark.parametrize(
    "field,value",
    [
        ("mux_queued_chunks", 257),
        ("mux_queued_bytes", (1 << 20) + 1),
        ("mux_ingress_ordinal", 1 << 63),
        ("mux_capacity_bytes", -1),
        ("mux_callback_failed", 1),
        ("unexpected", 1),
    ],
)
def test_result_parser_preserves_closed_terminal_schema(field, value):
    data = asdict(windows.SafeResult("a" * 32))
    data[field] = value
    with pytest.raises(windows.ProviderError):
        windows.parse_result(json.dumps(data).encode(), "a" * 32)


def test_terminal_accessor_requires_retired_exact_original_and_original_file(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(windows, "PENDING_OWNERS", [])
    budget, reservation = prepared_inputs()
    master = (
        provider_module()
        .NativeLocalMuxProvider(
            windows.WindowsSocketProvider(), budget=budget, admission=Admission()
        )
        .prepare_master(reservation, budget.reserve("base"))
    )
    native = master.native
    result = windows.SafeResult("a" * 32)
    result.mux_terminal_observed, result.mux_callback_failed = True, True
    result.mux_capacity_bytes = 1 << 20
    path = tmp_path / "result.json"
    path.write_bytes(result.to_json())
    native._original_result_paths = (
        tmp_path,
        windows.identity(tmp_path, directory=True),
        path,
        windows.identity(path),
        result.generation,
    )
    native._result_owner = master.owner
    from wso_tvt_bridge.local_live_diagnostics import NativeFirstKeySink

    sink = NativeFirstKeySink()
    master.provider.first_key_debug = sink
    assert native.original_mux_terminal() is None
    assert master.close() is not None
    (raw,) = sink.drain()
    assert json.loads(raw)["event"] == "native_mux_terminal"
    assert master.close() is not None and sink.drain() == ()
    record = native.original_mux_terminal()
    assert record.failed and record.capacity_bytes == 1 << 20
    native.owner = windows.ChildOwner(None, None, ())
    assert native.original_mux_terminal() is None
    native.owner = master.owner
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(result.to_json())
    replacement.replace(path)
    assert native.original_mux_terminal() is None


def test_terminal_publisher_reuses_finite_diagnostics_queue():
    from wso_tvt_bridge.local_live_diagnostics import (
        NativeFirstKeySink,
        NativeMuxTerminalRecord,
    )

    record = NativeMuxTerminalRecord(True, True, True, 256, 1 << 20, 257, 1 << 20)
    sink = NativeFirstKeySink()
    for _ in range(130):
        sink(record)
    rows = sink.drain()
    assert len(rows) == 128 and sink.dropped == 2
    assert len(b"".join(rows)) <= 64 << 10
    assert all(
        json.loads(row)
        == {
            "event": "native_mux_terminal",
            "version": 1,
            "epoch_bound": True,
            "failed": True,
            "closed": True,
            "queued_chunks": 256,
            "queued_bytes": 1 << 20,
            "ingress_ordinal": 257,
            "capacity_bytes": 1 << 20,
        }
        for row in rows
    )


@pytest.mark.parametrize("publisher_fault", [False, True])
def test_original_terminal_is_written_before_blocked_native_cleanup(
    tmp_path, monkeypatch, publisher_fault
):
    import threading

    from test_windows_socket import GEN, LiveNative
    from wso_tvt_bridge import windows_socket_worker as worker_module

    monkeypatch.setattr(worker_module, "check_private_acl", lambda path: None)

    entered, release = threading.Event(), threading.Event()
    receipt = tmp_path / "result.json"
    receipt.write_bytes(b"")
    publisher = worker_module._OriginalMuxTerminalPublisher(
        tmp_path,
        windows.identity(tmp_path, directory=True),
        receipt,
        windows.identity(receipt),
        GEN,
    )
    if publisher_fault:
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(b"")
        replacement.replace(receipt)

    class Bootstrap(NativeMuxWorker):
        def require(self, purpose):
            pass

        def publish(self, raw):
            pass

        def serve(self, native, handle, callback, setup):
            callback.mark_failed()
            self.capture_terminal(self._serve_result, callback)

    class BlockedCleanup(LiveNative):
        def call(self, name, *args):
            if name == "stop":
                entered.set()
                assert release.wait(2)
            return super().call(name, *args)

    worker = Bootstrap(None, GEN, time.monotonic() + 3, callback_generation=7)
    worker._terminal_publisher = publisher
    request = windows.PrivateRequest(
        "live",
        "KR",
        "synthetic9",
        "syntheticUser",
        "syntheticSecret",
        metadata_read_opt_in=True,
        live_read_opt_in=True,
        store_ref="SERVICE",
        channel_position=1,
        stream=2,
    )
    outcomes = []
    thread = threading.Thread(
        target=lambda: outcomes.append(
            worker_module.drive(
                BlockedCleanup(group="empty"),
                request,
                GEN,
                time.monotonic() + 3,
                lambda *args: None,
                service_authority=worker,
            )
        )
    )
    thread.start()
    try:
        assert entered.wait(1) and thread.is_alive()
        if publisher_fault:
            assert receipt.read_bytes() == b"" and not worker._terminal_published
        else:
            result = windows.parse_result(receipt.read_bytes(), GEN)
            assert result.mux_terminal_observed and result.mux_callback_failed
            assert not result.cleanup_attempted and not result.quiescence_verified
            assert not result.reaped and result.stage == "live"
            assert worker._terminal_published
            # The historical capture-only guard stays strict for legacy results.
            data = asdict(result)
            for name in tuple(data):
                if name.startswith("mux_"):
                    data[name] = asdict(windows.SafeResult(GEN))[name]
            with pytest.raises(windows.ProviderError):
                windows.parse_result(json.dumps(data).encode(), GEN)
    finally:
        release.set()
        thread.join(2)
    assert len(outcomes) == 1
    assert outcomes[0].cleanup_attempted and outcomes[0].failure == "none"
