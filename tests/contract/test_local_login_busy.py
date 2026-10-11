"""Exact original inert child receipt survives pipe EOF only after retirement."""

import json
import threading
import time

import pytest
from wso_core.tvt.local_credentials import LocalDeviceCredentials
from wso_core.tvt.local_service import LocalDeviceFailure

from tests.contract.test_local_live_provider import inert_windows_live_provider, module


def refused_child(tmp_path, monkeypatch, *, kind="busy"):
    live, native_module, native, provider = inert_windows_live_provider(
        tmp_path, monkeypatch
    )
    ipc = module("local_live_ipc")
    source_paths = [
        str(native_module.ROOT / "services/tvt-bridge/src"),
        str(native_module.ROOT / "packages/core/src"),
    ]
    script = """import sys,json,time
from pathlib import Path
assert sys.stdin.buffer.readline()==b"J\\n"
packet=json.loads(sys.stdin.buffer.read())
sys.path[:0]=SOURCES
from wso_tvt_bridge.local_live_ipc import LiveRemoteAuthority
from wso_tvt_bridge.windows_socket import SafeResult
authority=LiveRemoteAuthority.from_handle(packet["service_authority_handle"],packet["generation"],packet["deadline"])
authority.require("prepare")
# Faithful order: original child closes its service pipe before result write.
authority.close()
result=SafeResult(packet["generation"],stage="handshake",failure="rejected",
    loaded=True,initialized=True,transport=True,connect_status=1,greeting_bytes=64,
    send_count=64,received_bytes=292,native_error=536870960,cleanup_attempted=True)
kind=KIND
if kind=="unknown": result.native_error=17
if kind=="no_authority": result.native_error=536870953
if kind=="foreign": result.generation="f"*32
if kind=="wrong_stage": result.stage="connect"
path=Path(packet["config"]["staging"])/"result.json"
raw=result.to_json()
if kind=="truncated": raw=raw[:20]
if kind=="missing": raw=b""
if kind=="substituted":
    replacement=path.with_name("replacement.json")
    replacement.write_bytes(raw)
    replacement.replace(path)
else:
    with path.open("r+b") as stream:
        stream.write(raw)
        stream.flush()
(path.parent/"published.marker").write_text("ready")
while True: time.sleep(0.1)
""".replace("SOURCES", repr(source_paths)).replace("KIND", repr(kind))
    (tmp_path / "inert_live_child.py").write_text(script, encoding="utf-8")
    original_pump = ipc.LiveParentAuthority.pump

    def pump(parent, current):
        if parent._live_sequence >= 2:
            # Schedule the parent after the real original has closed the pipe
            # and completed its own receipt write, before processing that EOF.
            deadline = time.monotonic() + 2
            while not list(tmp_path.glob("*/published.marker")):
                assert time.monotonic() < deadline
                time.sleep(0.002)
        return original_pump(parent, current)

    monkeypatch.setattr(ipc.LiveParentAuthority, "pump", pump)
    return live, native_module, native, provider


def open_refused(provider, live, *, current=lambda: True, cancel=None, deadline=None):
    return provider.open_session(
        LocalDeviceCredentials(
            serial="SYNTHETIC9", country="KR", username="inert", password="inert"
        ),
        live.LiveSelection(b"C" * 16, 3, 2, 1, "sub"),
        deadline_monotonic=deadline or time.monotonic() + 8,
        current=current,
        cancel=cancel or threading.Event(),
    )


def test_original_pipe_close_then_busy_receipt_maps_429_after_confirmed_reap(
    tmp_path, monkeypatch
):
    live, p, native, provider = refused_child(tmp_path, monkeypatch)
    with pytest.raises(LocalDeviceFailure) as caught:
        open_refused(provider, live)
    assert (caught.value.code, caught.value.status) == ("LOCAL_DEVICE_BUSY", 429)
    assert native.owner.confirmed and native.owner.child.poll() is not None
    assert native.owner.job.closed and not native.owner.writer.is_alive()
    assert all(output.closed for output in native.owner.outputs)
    assert native.owner not in p.pending_owner_snapshot()
    results = list(tmp_path.glob("*/live-owner.json"))
    assert len(results) == 1
    value = json.loads(results[0].read_text())
    assert (
        value["stage"],
        value["failure"],
        value["native_error"],
        value["reaped"],
    ) == (
        "handshake",
        "rejected",
        536870960,
        True,
    )


@pytest.mark.parametrize(
    "kind",
    [
        "unknown",
        "no_authority",
        "foreign",
        "truncated",
        "missing",
        "substituted",
        "wrong_stage",
    ],
)
def test_only_exact_original_login_busy_can_map_429(tmp_path, monkeypatch, kind):
    live, p, native, provider = refused_child(tmp_path, monkeypatch, kind=kind)
    with pytest.raises(LocalDeviceFailure) as caught:
        open_refused(provider, live)
    assert (caught.value.code, caught.value.status) == (
        "LOCAL_DEVICE_PROTOCOL_INVALID",
        502,
    )
    assert native.owner.confirmed and native.owner not in p.pending_owner_snapshot()


@pytest.mark.parametrize(
    "precedence,code,status",
    [
        ("cancel", "LOCAL_DEVICE_CANCELLED", 409),
        ("expiry", "LOCAL_DEVICE_DEADLINE_EXCEEDED", 504),
        ("denied", "LOCAL_DEVICE_DENIED", 404),
        ("error", "LOCAL_DEVICE_DENIED", 404),
        ("cancel_during_current", "LOCAL_DEVICE_CANCELLED", 409),
        ("expiry_during_current", "LOCAL_DEVICE_DEADLINE_EXCEEDED", 504),
    ],
)
def test_original_authority_and_deadline_precede_recovered_busy(
    tmp_path, monkeypatch, precedence, code, status
):
    from types import SimpleNamespace

    live, p, native, provider = refused_child(tmp_path, monkeypatch)
    cancel = threading.Event()
    now = [time.monotonic()]
    deadline = now[0] + 8
    monkeypatch.setattr(live, "time", SimpleNamespace(monotonic=lambda: now[0]))
    original_finish = p.ChildOwner.finish
    ready = [False]

    def finish(owner, timeout=1):
        value = original_finish(owner, timeout)
        if value:
            ready[0] = True
            if precedence == "cancel":
                cancel.set()
            elif precedence == "expiry":
                now[0] = deadline
        return value

    def current():
        if ready[0]:
            if precedence == "denied":
                return False
            if precedence == "error":
                raise ValueError("inert private supplier text")
            if precedence == "cancel_during_current":
                cancel.set()
            if precedence == "expiry_during_current":
                now[0] = deadline
        return True

    monkeypatch.setattr(p.ChildOwner, "finish", finish)
    with pytest.raises(LocalDeviceFailure) as caught:
        open_refused(provider, live, current=current, cancel=cancel, deadline=deadline)
    assert (caught.value.code, caught.value.status) == (code, status)
    assert native.owner.confirmed and native.owner not in p.pending_owner_snapshot()


def test_unconfirmed_original_never_reads_receipt_or_becomes_busy(
    tmp_path, monkeypatch
):
    live, p, native, provider = refused_child(tmp_path, monkeypatch)
    allow_finish = threading.Event()
    original_finish = p.ChildOwner.finish
    original_read = p.read_original
    reads = []

    def finish(owner, timeout=1):
        if not allow_finish.is_set():
            return False
        return original_finish(owner, timeout)

    def read(path, expected, cap):
        reads.append(path.name)
        return original_read(path, expected, cap)

    monkeypatch.setattr(p.ChildOwner, "finish", finish)
    monkeypatch.setattr(p, "read_original", read)
    try:
        with pytest.raises(LocalDeviceFailure) as caught:
            open_refused(provider, live)
        assert (caught.value.code, caught.value.status) == (
            "LOCAL_DEVICE_PROTOCOL_INVALID",
            502,
        )
        assert not native.owner.confirmed and native.owner in p.pending_owner_snapshot()
        assert reads == []
    finally:
        allow_finish.set()
        assert native.owner.finish(2)
        p.remove_confirmed_owner(native.owner)


def test_original_directory_identity_is_rechecked_after_reap(tmp_path, monkeypatch):
    live, p, native, provider = refused_child(tmp_path, monkeypatch)
    original_identity = p.identity

    def identity(path, *, directory=False):
        value = original_identity(path, directory=directory)
        if (
            directory
            and path.parent == tmp_path
            and native.owner is not None
            and native.owner.confirmed
        ):
            return value[0], value[1] + 1
        return value

    monkeypatch.setattr(p, "identity", identity)
    with pytest.raises(LocalDeviceFailure) as caught:
        open_refused(provider, live)
    assert (caught.value.code, caught.value.status) == (
        "LOCAL_DEVICE_PROTOCOL_INVALID",
        502,
    )
    assert native.owner.confirmed and native.owner not in p.pending_owner_snapshot()
