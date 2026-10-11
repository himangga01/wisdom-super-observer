"""Fixed parent-side background failure facts; inert native ports only."""

import json
from dataclasses import replace
from itertools import pairwise

import pytest
from test_local_mux_callback import invoke
from test_mux_command_debug import packet
from test_shared_ingress_consumer import (
    consumer_rig as original_consumer_rig,
)
from test_shared_ingress_consumer import (
    wait_until,
)
from wso_core.tvt.local_live_mux import UnsupportedMuxPacket
from wso_tvt_bridge import local_live_diagnostics as diagnostics


@pytest.fixture
def consumer_rig(monkeypatch):
    yield from original_consumer_rig.__wrapped__(monkeypatch)


@pytest.mark.parametrize(
    "command,route", [(2561, 0), (2562, 2), (2563, 255), (0xFFFFFFFF, 255)]
)
def test_real_parked_consumer_logs_opcode_before_provider_close(
    command, route, consumer_rig, monkeypatch
):
    master, parent, _, callback, _ = consumer_rig
    sink, events = diagnostics.NativeFirstKeySink(), []
    original_stop = master.owner.request_stop

    def stop(owner):
        events.append(("stop", master._closed))
        original_stop()

    def emit(record):
        assert not master._closed and not master._lock._is_owned()
        sink(record)
        events.append(("log", parent.failed))

    monkeypatch.setattr(type(master.owner), "request_stop", stop)
    master.provider.first_key_debug = emit
    invoke(callback, packet(command, route))
    master._start_ingress_consumer()
    wait_until(master._ingress_finished.is_set)
    rows = sink.drain()
    assert len(rows) == 1, "background parser cause must survive parent wrappers"
    assert json.loads(rows[0]) == {
        "event": "native_mux_ingress_failure",
        "version": 1,
        "cause": "unsupported_packet",
        "wire_command": command,
        "wire_route": route,
    }
    assert master._closed and parent.failed
    # IPC already stops on codec failure; logging precedes provider's own stop.
    assert events[0] == ("stop", False)
    assert ("log", True) in events
    assert events[-1] == ("stop", True)


@pytest.mark.parametrize("sink_fault", [False, True])
def test_unknown_background_error_and_sink_fault_preserve_original_fence(
    consumer_rig, sink_fault, monkeypatch
):
    master, parent, _, _, _ = consumer_rig
    rows, stops, calls = [], [], []

    def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE_DIAGNOSTIC_SENTINEL")

    def emit(record):
        assert not master._closed
        calls.append("emit")
        if sink_fault:
            raise SystemExit("PRIVATE_DIAGNOSTIC_SENTINEL")
        rows.append(diagnostics.encode_mux_ingress_failure_record(record))

    parent.pump, master.provider.first_key_debug = broken, emit
    monkeypatch.setattr(
        type(master.owner), "request_stop", lambda owner: stops.append(master._closed)
    )
    master._start_ingress_consumer()
    wait_until(master._ingress_finished.is_set)
    assert master._closed and parent.failed and stops == [True, True]
    assert calls == ["emit"]
    if not sink_fault:
        assert json.loads(rows[0]) == {
            "event": "native_mux_ingress_failure",
            "version": 1,
            "cause": "unknown",
            "wire_command": None,
            "wire_route": None,
        }
        assert b"PRIVATE_DIAGNOSTIC_SENTINEL" not in rows[0]


def test_projection_uses_base_descriptors_and_four_node_bound():
    class Trap(RuntimeError):
        def __getattribute__(self, name):
            if name in ("__cause__", "__context__", "__dict__"):
                raise AssertionError("wrapper attribute access is forbidden")
            return super().__getattribute__(name)

    fact = UnsupportedMuxPacket(2561, 2)
    root = Trap()
    root.__context__ = fact
    record = diagnostics.project_mux_ingress_failure(root)
    assert (record.wire_command, record.wire_route) == (2561, 2)
    errors = [RuntimeError() for _ in range(4)]
    for previous, following in pairwise(errors):
        previous.__cause__ = following
    errors[-1].__context__ = fact
    assert diagnostics.project_mux_ingress_failure(errors[0]).cause == "unknown"
    errors[-2].__cause__ = fact
    assert diagnostics.project_mux_ingress_failure(errors[0]).wire_command == 2561
    cycle = RuntimeError()
    cycle.__cause__ = cycle
    assert diagnostics.project_mux_ingress_failure(cycle).cause == "unknown"


@pytest.mark.parametrize("mutation", ["subclass", "bool", "range", "missing"])
def test_malformed_or_foreign_numeric_facts_are_unknown(mutation):
    class Foreign(UnsupportedMuxPacket):
        pass

    fact = Foreign(2561, 2) if mutation == "subclass" else UnsupportedMuxPacket(2561, 2)
    if mutation == "bool":
        fact.command = True
    elif mutation == "range":
        fact.route = 256
    elif mutation == "missing":
        del fact.command
    assert diagnostics.project_mux_ingress_failure(fact).cause == "unknown"


def test_failure_record_closed_schema_and_existing_finite_sink():
    record = diagnostics.project_mux_ingress_failure(
        UnsupportedMuxPacket(0xFFFFFFFF, 255)
    )
    sink = diagnostics.NativeFirstKeySink()
    for _ in range(130):
        sink(record)
    rows = sink.drain()
    assert len(rows) == 128 and sink.dropped == 2
    assert len(b"".join(rows)) <= 64 << 10
    assert all(len(row) <= 1024 for row in rows)
    for changes in (
        {"wire_command": True},
        {"wire_command": 1 << 32},
        {"wire_route": -1},
        {"cause": "PRIVATE_DIAGNOSTIC_SENTINEL"},
        {"wire_route": None},
    ):
        with pytest.raises(ValueError):
            diagnostics.encode_mux_ingress_failure_record(replace(record, **changes))
    with pytest.raises(ValueError):
        diagnostics.encode_mux_ingress_failure_record({"wire_command": 2561})

    class Hostile:
        def __eq__(self, other):
            raise AssertionError("malformed record must not run comparison hooks")

    with pytest.raises(ValueError):
        diagnostics.encode_mux_ingress_failure_record(replace(record, cause=Hostile()))
