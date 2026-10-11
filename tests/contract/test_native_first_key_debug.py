"""Parent-only first-key controls: invented bytes, no pipe/process/SQL/SDK."""

import importlib
import json
import struct
import threading
from dataclasses import replace

import pytest

from tests.contract import test_dedicated_main_startup_authority as startup
from tests.tvt_parity.test_local_live import (
    CHANNEL,
    REQUEST,
    SESSION,
    TASK,
    media,
    packet,
    yz,
)


def debug_module():
    return importlib.import_module("wso_tvt_bridge.local_live_diagnostics")


@pytest.fixture
def startup_rig(monkeypatch):
    yield from startup.rig.__wrapped__(monkeypatch)


class Connection:
    def __init__(self):
        self.incoming, self.answers = [], []
        self.closed = False

    def poll(self, timeout):
        return bool(self.incoming)

    def recv_bytes(self, limit):
        result = self.incoming.pop(0)
        assert len(result) <= limit
        return result

    def send_bytes(self, raw):
        self.answers.append(raw)

    def close(self):
        self.closed = True


def parent_rig(monkeypatch, *, enabled=True):
    from wso_tvt_bridge import local_live_ipc as ipc
    from wso_tvt_bridge.local_live_provider import LiveSelection

    now = [100.0]
    monkeypatch.setattr(ipc.time, "monotonic", lambda: now[0])
    parent = ipc.LiveParentAuthority(
        120.0,
        threading.Event(),
        LiveSelection(CHANNEL, 3, 2, 1, "main"),
        diagnostics=enabled,
    )
    parent.generation = "a" * 32
    parent.connection = Connection()
    prime_parent(parent)
    return parent, now


def prime_parent(parent, current=lambda: True):
    from wso_tvt_bridge import local_live_ipc as ipc

    channel = parent.selection.channel_guid
    setup = {
        "session": SESSION.hex(),
        "channel": channel.hex(),
        "task": TASK.hex(),
        "open_request": REQUEST.hex(),
        "peer_version": 6,
        "callback_generation": int(parent.generation[:15], 16) + 1,
        "raw_index": parent.selection.raw_index,
        "window_index": parent.selection.window_index,
        "ordinal": parent.selection.ordinal,
        "stream": 1,
        "live_basis": "explicit_lp",
        "login_accepted": True,
        "serial_matched": True,
    }
    parent.connection.incoming.append(
        b"J"
        + ipc.encode(
            {
                "type": "setup",
                "data": setup,
                "generation": parent.generation,
                "sequence": 1,
            }
        )
    )
    assert parent.pump(current)
    parent.connection.incoming.append(
        b"E" + packet(0x10000501, b"", sequence=6, declared=0)
    )
    assert parent.pump(current)


@pytest.mark.parametrize("case", ["ack_only", "nonkey", "latekey", "ready", "denied"])
def test_original_parent_readiness_outcomes_and_closed_snapshot(monkeypatch, case):
    parent, now = parent_rig(monkeypatch)
    if case in ("nonkey", "latekey", "ready"):
        now[0] = 110.0 if case == "latekey" else 109.0
        raw = packet(
            65537, yz() + media(kind=1, ip=0 if case == "nonkey" else 128), sequence=6
        )
        parent.connection.incoming.append(b"E" + raw)
        assert parent.pump(lambda: True) is (case != "latekey")
    now[0] = 110.0
    if case == "ready":
        assert parent._first_frame_current(lambda: True)
    else:
        assert not parent._first_frame_current(lambda: case != "denied")
    record = parent.first_key_snapshot()
    assert record.outcome == (
        "ready" if case == "ready" else "denied" if case == "denied" else "no_signal"
    )
    assert record.open_ack and record.ack_command == 1281 and record.ack_ms == 0
    assert record.parsed_frames == int(case in ("nonkey", "latekey", "ready"))
    assert record.nonkey_frames == int(case == "nonkey")
    assert record.key_frames == int(case in ("latekey", "ready"))
    assert record.first_key_late is (case == "latekey")
    assert record.first_key_ms == (
        10000 if case == "latekey" else 9000 if case == "ready" else None
    )
    assert record.worker_observed is False
    parent.close()
    assert parent.first_key_snapshot() is record
    encoded = debug_module().encode_first_key_record(record)
    for private in (
        SESSION.hex(),
        CHANNEL.hex(),
        TASK.hex(),
        REQUEST.hex(),
        parent.generation,
        "inert",
        "RAW!",
    ):
        assert private.encode() not in encoded
    assert set(json.loads(encoded)) == {
        "event",
        "version",
        *record.__dataclass_fields__,
    }


def test_partial_fragment_snapshot_survives_codec_close(monkeypatch):
    parent, now = parent_rig(monkeypatch)
    parent.connection.incoming.append(
        b"E" + struct.pack("<Ii6i", 825307441, -1, 77, 2, 32, 1, 16, 88) + bytes(16)
    )
    assert parent.pump(lambda: True)
    parent.connection.incoming.append(
        b"E" + struct.pack("<Ii6i", 825307441, -1, 77, 2, 32, 2, 16, 88)[:12]
    )
    # A partial next outer header is permitted while the fragment is pending.
    assert parent.pump(lambda: True)
    now[0] = 110.0
    assert not parent._first_frame_current(lambda: True)
    record = parent.first_key_snapshot()
    assert record.partial_bytes == 12 and record.assembly_bytes == 16
    assert record.fragment_pending and record.fragment_count == 2
    assert record.fragment_next == 2 and record.fragment_total_bytes == 32
    assert not parent.codec._buffer and not parent.codec._assembly


def test_default_off_and_original_current_call_count_are_preserved(monkeypatch):
    outcomes = []
    for enabled in (False, True):
        parent, now = parent_rig(monkeypatch, enabled=enabled)
        calls = []

        def current(calls=calls, now=now):
            calls.append(1)
            now[0] += 0.025
            return True

        assert parent.check(current)
        assert len(calls) == 1
        if enabled:
            record = parent.first_key_snapshot()
            assert record.authority_check_calls == 7
            assert record.authority_check_elapsed_max_ms == 25
        else:
            assert parent.first_key_snapshot() is None and parent._diagnostics is None
        outcomes.append(
            (
                parent.failure,
                parent.ready,
                parent._live_sequence,
                len(parent.connection.answers),
            )
        )
        parent.close()
    assert outcomes[0] == outcomes[1]


def test_closed_codec_validation_and_sink_count_byte_bounds(monkeypatch):
    parent, _ = parent_rig(monkeypatch)
    record = parent.first_key_snapshot()
    module = debug_module()
    for changed in (
        {"outcome": "PRIVATE_TEXT"},
        {"parsed_frames": True},
        {"ack_ms": -1},
        {"received_bytes": 1 << 40},
    ):
        with pytest.raises(ValueError):
            module.encode_first_key_record(replace(record, **changed))
    with pytest.raises(ValueError):
        module.encode_first_key_record({"serial": "PRIVATE_TEXT"})
    sink = module.NativeFirstKeySink()
    for _ in range(300):
        sink(record)
    lines = sink.drain()
    assert 0 < len(lines) <= 128 and sum(map(len, lines)) <= 65536
    assert sink.dropped == 300 - len(lines) and sink.drain() == ()
    assert all(json.loads(line)["event"] == "native_first_key" for line in lines)
    parent.close()


def test_diagnostic_faults_do_not_change_denial_or_current_exception(monkeypatch):
    parent, now = parent_rig(monkeypatch)

    def broken(*args, **kwargs):
        raise KeyboardInterrupt("PRIVATE_DIAG_TEXT")

    monkeypatch.setattr(type(parent._diagnostics), "snapshot", broken)
    now[0] = 110.0
    assert not parent._first_frame_current(lambda: True)
    assert parent.failure == "no_signal" and parent.first_key_snapshot() is None
    parent.close()


@pytest.mark.parametrize("case", ["ready", "no_signal", "exception", "default_off"])
def test_prepared_original_emits_once_after_run_cleanup_outside_locks(
    startup_rig, monkeypatch, case
):
    from types import SimpleNamespace

    from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget
    from wso_tvt_bridge import local_inventory_ipc
    from wso_tvt_bridge import local_live_ipc as ipc

    _gate, _sql, prepared, credentials, channel = startup_rig
    now = [100.0]
    monkeypatch.setattr(ipc.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        local_inventory_ipc.multiprocessing,
        "Pipe",
        lambda **kwargs: (Connection(), Connection()),
    )
    seen, authorities = [], []
    original = KeyboardInterrupt("ORIGINAL_PRIVATE_EXCEPTION")

    def emit(record):
        authority = authorities[0]
        assert not authority._transition_lock._is_owned()
        assert not prepared.custodian._lock._is_owned()
        assert (
            prepared.custodian._constructor_finished and not prepared.custodian._active
        )
        if case != "ready":
            assert prepared._stopping and prepared.owner.confirmed
            assert prepared._raw_credit is None
        seen.append(record)
        raise SystemExit("PRIVATE_DIAGNOSTIC_FAULT")

    prepared.provider.first_key_debug = None if case == "default_off" else emit

    def run(config, request, *, service, current):
        authorities.append(service)
        prepared.custodian.create_legacy_pipe(service)
        prime_parent(service, current)
        if case == "exception":
            raise original
        if case == "no_signal":
            now[0] = 110.0
            assert not service._first_frame_current(current)
            raise LocalDeviceFailure("LOCAL_DEVICE_NO_SIGNAL", 504)
        now[0] = 109.0
        service.connection.incoming.append(
            b"E"
            + packet(
                65537,
                yz(channel=channel.guid) + media(kind=1, channel=channel.guid),
                sequence=6,
            )
        )
        assert service.pump(current) and service.ready
        service.handed_off = True
        return SimpleNamespace(failure="")

    monkeypatch.setattr(prepared.native, "run", run)
    if case == "exception":
        with pytest.raises(KeyboardInterrupt) as caught:
            prepared.start(
                credentials,
                channel,
                budget=LocalVerifyBudget(20000, clock=lambda: now[0]),
            )
        assert caught.value is original
    elif case == "no_signal":
        with pytest.raises(LocalDeviceFailure) as caught:
            prepared.start(
                credentials,
                channel,
                budget=LocalVerifyBudget(20000, clock=lambda: now[0]),
            )
        assert (
            caught.value.code == "LOCAL_DEVICE_NO_SIGNAL" and caught.value.status == 504
        )
    else:
        session = prepared.start(
            credentials, channel, budget=LocalVerifyBudget(20000, clock=lambda: now[0])
        )
        assert session is not None
    assert len(seen) == int(case != "default_off")
    if seen:
        assert seen[0].outcome == (
            "ready"
            if case == "ready"
            else "no_signal"
            if case == "no_signal"
            else "closed"
        )
    prepared.close_native()
    assert len(seen) == int(case != "default_off")


def test_diagnostic_clock_fault_does_not_skip_original_check(monkeypatch):
    from wso_tvt_bridge import local_live_ipc as ipc
    from wso_tvt_bridge.local_inventory_ipc import ParentAuthority

    parent, _ = parent_rig(monkeypatch)
    calls = []
    sentinel = BaseException("ORIGINAL_CHECK_EXCEPTION")

    def original(self, current):
        calls.append(current)
        raise sentinel

    def clock_fault():
        raise KeyboardInterrupt("PRIVATE_CLOCK")

    monkeypatch.setattr(ParentAuthority, "check", original)
    monkeypatch.setattr(ipc.time, "monotonic", clock_fault)
    current = lambda: True
    with pytest.raises(BaseException) as caught:
        parent.check(current)
    assert caught.value is sentinel and calls == [current]
    parent.close()


def test_diagnostic_numeric_state_saturates_and_is_immutable(monkeypatch):
    from dataclasses import FrozenInstanceError

    parent, now = parent_rig(monkeypatch)
    module = debug_module()
    limit = module.MAX_DIAGNOSTIC_VALUE
    diag = parent._diagnostics
    diag.ipc_messages = diag.ipc_received_bytes = diag.parsed_frames = (
        diag.key_frames
    ) = limit
    diag.authority_check_calls = limit
    diag.received(999, True)
    diag.frame(True, now[0], False)
    diag.checked(0, float(limit))
    record = parent.first_key_snapshot()
    assert (
        record.ipc_messages
        == record.ipc_received_bytes
        == record.parsed_frames
        == record.key_frames
        == limit
    )
    assert (
        record.authority_check_calls == record.authority_check_elapsed_max_ms == limit
    )
    with pytest.raises(FrozenInstanceError):
        record.parsed_frames = 0
    assert len(module.encode_first_key_record(record)) <= 2048
    parent.close()
