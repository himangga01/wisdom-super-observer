"""M1 tests: inert native and original-process IPC only; no device/SDK."""

from __future__ import annotations

import importlib
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from wso_core.tvt.local_credentials import LocalDeviceCredentials
from wso_core.tvt.local_service import LocalDeviceFailure


def module(name: str) -> Any:
    return importlib.import_module("wso_tvt_bridge." + name)


def test_loader_default_unconfigured_and_exact_optin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = module("local_inventory_config")
    for key in list(config.ENV_KEYS):
        monkeypatch.delenv(key, raising=False)
    assert config.load_local_inventory_provider() is None
    for value in ("true", "yes", "0", "1"):
        monkeypatch.setenv("WSO_TVT_WINDOWS_LOCAL_INVENTORY_ENABLED", value)
        assert config.load_local_inventory_provider() is None


def test_current_runs_on_caller_thread_and_denial_is_not_cached() -> None:
    ipc = module("local_inventory_ipc")
    parent = ipc.ParentAuthority(time.monotonic() + 2, threading.Event())
    parent.bind("a" * 32)
    remote = ipc.RemoteAuthority(parent.worker_connection, "a" * 32, parent.deadline)
    seen: list[int] = []
    outcomes: list[bool] = []
    caller = threading.get_ident()

    def current() -> bool:
        seen.append(threading.get_ident())
        return len(seen) == 1

    def child() -> None:
        for _ in range(2):
            try:
                remote.require("send")
                outcomes.append(True)
            except ipc.AuthorityError:
                outcomes.append(False)
                break

    worker = threading.Thread(target=child)
    worker.start()
    try:
        while worker.is_alive() and time.monotonic() < parent.deadline:
            parent.pump(current)
            time.sleep(0.001)
        worker.join(1)
        assert not worker.is_alive() and outcomes == [True, False]
        assert seen == [caller, caller]
    finally:
        remote.close()
        parent.close(1)


@pytest.mark.parametrize("case", ["cancel", "expired", "denied", "throw"])
def test_adapter_initial_gate_precedes_credentials_and_child(
    tmp_path: Path,
    case: str,
) -> None:
    adapter = module("local_inventory_provider")
    from wso_tvt_bridge.windows_socket import ProviderConfig

    provider = adapter.NativeLocalInventoryProvider(
        ProviderConfig(Path("C:/inert"), Path("C:/inert"), Path("C:/inert/review"), 20)
    )
    cancel = threading.Event()
    if case == "cancel":
        cancel.set()
    deadline = time.monotonic() + (-1 if case == "expired" else 2)

    def current() -> bool:
        if case == "throw":
            raise RuntimeError("INERT_PRIVATE_FAILURE")
        return case != "denied"

    credentials = LocalDeviceCredentials(
        serial="SYNTHETIC9", country="KR", username="inert", password="inert-secret"
    )
    with pytest.raises(LocalDeviceFailure) as caught:
        provider.verify(
            credentials, deadline_monotonic=deadline, current=current, cancel=cancel
        )
    assert "INERT_PRIVATE" not in str(caught.value)
    assert not hasattr(provider, "credentials") and not hasattr(provider, "owner")


def helpers() -> Any:
    import importlib.util
    import sys

    from wso_tvt_bridge.windows_socket import ROOT

    name = "_m1_native_fixtures"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "tests/contract/test_windows_socket.py"
        )
        assert spec is not None and spec.loader is not None
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[name] = loaded
        spec.loader.exec_module(loaded)
    return sys.modules[name]


@pytest.mark.parametrize("deny_at", ["none", "prepared", "publish"])
def test_worker_real_inventory_export_and_caller_authority(
    monkeypatch: pytest.MonkeyPatch,
    deny_at: str,
) -> None:
    import ctypes as ct
    import struct

    fixture = helpers()
    ipc = module("local_inventory_ipc")
    adapter = module("local_inventory_provider")
    parent = ipc.ParentAuthority(time.monotonic() + 3, threading.Event())
    parent.bind(fixture.GEN)
    remote = ipc.RemoteAuthority(parent.worker_connection, fixture.GEN, parent.deadline)
    original_login = fixture.inventory_login_reply

    def two_channels(*, with_tail: bool = True) -> bytes:
        raw = bytearray(original_login(with_tail=with_tail))
        if with_tail:
            struct.pack_into("<h", raw, 162, 2)
            raw[184:184] = bytes((0, 9, 42, 0)) + b"H" * 16
            struct.pack_into("<I", raw, 4, len(raw) - 8)
            struct.pack_into("<I", raw, 20, len(raw) - 24)
        return bytes(raw)

    monkeypatch.setattr(fixture, "inventory_login_reply", two_channels)
    native = fixture.LiveNative(group="empty")
    prepared = threading.Event()
    original_allocate = ct.create_string_buffer

    def allocate(value: int | bytes, size: int | None = None) -> Any:
        buffer = (
            original_allocate(value) if size is None else original_allocate(value, size)
        )
        if (
            isinstance(value, bytes)
            and len(value) > 24
            and struct.unpack_from("<I", value, 12)[0] == 2331
        ):
            prepared.set()
        return buffer

    monkeypatch.setattr(ct, "create_string_buffer", allocate)
    caller_id = threading.get_ident()
    seen: list[int] = []

    def current() -> bool:
        seen.append(threading.get_ident())
        if deny_at == "prepared" and prepared.is_set():
            return False
        return not (deny_at == "publish" and parent._publish_sequence is not None)

    output: list[Any] = []
    worker = threading.Thread(
        target=lambda: output.append(
            fixture.w.drive(
                native,
                fixture.inventory_request(),
                fixture.GEN,
                parent.deadline,
                lambda name, raw: None,
                service_authority=remote,
            )
        )
    )
    worker.start()
    try:
        while worker.is_alive() and time.monotonic() < parent.deadline:
            parent.pump(current)
            time.sleep(0.001)
        worker.join(1)
        parent.pump(current)
        assert not worker.is_alive() and seen and set(seen) == {caller_id}
        if deny_at == "none":
            assert output[0].failure == "none" and parent.observation is not None
            observed = adapter.observation(parent.observation, cleanup_confirmed=True)
            assert [
                (c.raw_index, c.window_index, c.ordinal, c.kind)
                for c in observed.channels
            ] == [(3, 2, 1, "digital"), (42, 9, 2, "analog")]
            assert observed.channels[1].guid == b"H" * 16
            assert (
                observed.group_provenance == "empty"
                and not observed.permissions_complete
            )
            assert (
                b"SYNTHETIC9" not in parent.observation
                and b"syntheticSecret" not in parent.observation
            )
        else:
            assert parent.observation is None
            assert native.commands.count(257) == 1
            if deny_at == "prepared":
                assert native.commands.count(2331) == 0
    finally:
        remote.close()
        parent.close(1)


@pytest.mark.parametrize(
    "message",
    [
        b'{"type":"current","generation":"foreign","sequence":1,"purpose":"send"}',
        b'{"type":"current","generation":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","sequence":2,"purpose":"send"}',
        b'{"type":"current","generation":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","sequence":1,"purpose":"unsafe"}',
        b'{"type":"current","type":"current"}',
    ],
)
def test_malformed_authority_requests_never_call_current(message: bytes) -> None:
    ipc = module("local_inventory_ipc")
    parent = ipc.ParentAuthority(time.monotonic() + 1, threading.Event())
    parent.bind("a" * 32)
    calls: list[bool] = []
    try:
        parent.worker_connection.send_bytes(message)
        assert not parent.pump(lambda: calls.append(True) or True)
        assert calls == [] and parent.failure == "protocol"
    finally:
        parent.close()


def test_broken_or_expired_authority_is_not_an_allow() -> None:
    ipc = module("local_inventory_ipc")
    parent = ipc.ParentAuthority(time.monotonic() + 0.02, threading.Event())
    parent.bind("a" * 32)
    remote = ipc.RemoteAuthority(parent.worker_connection, "a" * 32, parent.deadline)
    parent.connection.close()
    try:
        with pytest.raises(ipc.AuthorityError):
            remote.require("send")
    finally:
        parent.close()


@pytest.mark.parametrize(
    "case",
    [
        "allow",
        "send_denied",
        "cancel_wait",
        "late",
        "final_denied",
        "cleanup_uncertain",
        "close_before_receipt",
    ],
)
def test_original_windows_child_ipc_and_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    import json
    import os

    p = module("windows_socket")
    adapter = module("local_inventory_provider")
    if os.name != "nt":
        pytest.skip("Windows original Job proof")
    fixture = helpers()
    safe = fixture.w.drive(
        fixture.LiveNative(group="empty"),
        fixture.inventory_request(),
        fixture.GEN,
        time.monotonic() + 3,
        lambda name, raw: None,
    )
    assert safe.failure == "none"
    data = {
        "login_accepted": True,
        "same_original_session": True,
        "serial_matched": True,
        "channels_complete": True,
        "metadata_branch_complete": True,
        "permissions_complete": False,
        "proof_verified": False,
        "group_provenance": "empty",
        "channels": [
            {
                "guid": (b"G" * 16).hex(),
                "raw_index": 3,
                "window_index": 2,
                "ordinal": 1,
                "kind": "digital",
            }
        ],
    }
    # Stdlib-only substitute consumes the same original stdin/duplicated HANDLE.
    # It never loads a native vendor module or contacts a device.
    script = tmp_path / "inert_child.py"
    script.write_text(
        """import sys,json,time,ctypes as ct
from pathlib import Path
assert sys.stdin.buffer.readline()==b"J\\n"
packet=json.loads(sys.stdin.buffer.read())
k=ct.WinDLL("kernel32",use_last_error=True)
k.GetCurrentProcess.restype=ct.c_void_p
k.IsProcessInJob.argtypes=[ct.c_void_p,ct.c_void_p,ct.POINTER(ct.c_int)]
member=ct.c_int()
assert k.IsProcessInJob(k.GetCurrentProcess(),None,ct.byref(member)) and member.value
sys.path.insert(0,SOURCE)
from wso_tvt_bridge.local_inventory_ipc import RemoteAuthority,encode
authority=RemoteAuthority.from_handle(packet["service_authority_handle"],packet["generation"],packet["deadline"])
authority.require("prepare")
if CASE=="cancel_wait":
    Path("waiting.marker").write_text("inert")
    time.sleep(30)
buffer=ct.create_string_buffer(b"INERT")
authority.require("send")
Path("sent.marker").write_text("inert")
authority.require("publish")
authority.publish(encode(DATA))
authority.close()
if CASE=="close_before_receipt":
    time.sleep(.3)
result=RESULT
result["generation"]=packet["generation"]
Path("result.json").write_text(json.dumps(result))
time.sleep(30)
""".replace("SOURCE", repr(str(p.ROOT / "services/tvt-bridge/src")))
        .replace("CASE", repr(case))
        .replace("DATA", repr(data))
        .replace("RESULT", repr(json.loads(safe.to_json()))),
        encoding="utf-8",
    )
    direct = str(p.direct_interpreter()[0])
    monkeypatch.setattr(p, "worker_command", lambda: [direct, "-I", "-S", str(script)])
    monkeypatch.setattr(p, "verify_review", lambda config: [])
    monkeypatch.setattr(p, "runtime_override", lambda config: {})
    monkeypatch.setattr(p, "validate_bundle", lambda *args: {})
    monkeypatch.setattr(p, "check_private_acl", lambda path: None)
    monkeypatch.setattr(p, "protect_created_acl", lambda path: None)
    monkeypatch.setattr(p.ProviderConfig, "__post_init__", lambda self: None)
    if case == "cleanup_uncertain":
        ipc = module("local_inventory_ipc")
        real_close = ipc.ParentAuthority.close
        first_close = [True]

        def close_once_uncertain(self: Any, timeout: float = 1) -> bool:
            if first_close.pop() if first_close else False:
                return False
            return bool(real_close(self, timeout))

        monkeypatch.setattr(ipc.ParentAuthority, "close", close_once_uncertain)
    actual_provider = p.WindowsSocketProvider()
    monkeypatch.setattr(adapter, "WindowsSocketProvider", lambda: actual_provider)
    cancel = threading.Event()
    caller = threading.get_ident()
    seen: list[int] = []
    deadline = time.monotonic() + (1 if case == "late" else 3)
    retained: list[Any] = []

    def current() -> bool:
        seen.append(threading.get_ident())
        owner = actual_provider.owner
        if owner and owner.service:
            if owner not in retained:
                retained.append(owner)
            if case == "cancel_wait" and list(tmp_path.glob("*/waiting.marker")):
                cancel.set()
            if owner.service._expected == 3 and case in ("send_denied", "late"):
                if case == "late":
                    time.sleep(max(0, deadline - time.monotonic()) + 0.1)
                    assert owner.child.poll() is not None
                    return True
                return False
        return not (case == "final_denied" and owner is None and len(seen) > 2)

    provider = adapter.NativeLocalInventoryProvider(
        p.ProviderConfig(tmp_path, tmp_path, tmp_path / "review", 20)
    )
    credentials = LocalDeviceCredentials(
        serial="SYNTHETIC9", country="KR", username="inert", password="inert-secret"
    )
    if case in ("allow", "close_before_receipt"):
        result = provider.verify(
            credentials, deadline_monotonic=deadline, current=current, cancel=cancel
        )
        assert result.cleanup_confirmed and result.channels[0].raw_index == 3
    else:
        with pytest.raises(LocalDeviceFailure) as caught:
            provider.verify(
                credentials, deadline_monotonic=deadline, current=current, cancel=cancel
            )
        expected = {
            "cancel_wait": "LOCAL_DEVICE_CANCELLED",
            "late": "LOCAL_DEVICE_DEADLINE_EXCEEDED",
            "cleanup_uncertain": "LOCAL_DEVICE_UNAVAILABLE",
        }.get(case, "LOCAL_DEVICE_DENIED")
        assert caught.value.code == expected
    assert seen and set(seen) == {caller}
    assert len(retained) == 1
    if case == "cleanup_uncertain":
        assert actual_provider.owner is retained[0] and not retained[0].confirmed
        assert retained[0] in p.PENDING_OWNERS and retained[0].service is not None
        assert retained[0].finish(0.5)
        p.PENDING_OWNERS.remove(retained[0])
        actual_provider.owner = None
    assert retained[0].confirmed
    assert retained[0].child is not None and retained[0].child.poll() is not None
    assert retained[0].job.closed and retained[0].service is None
    assert all(output.closed for output in retained[0].outputs)
    owners = [
        owner
        for owner in p.PENDING_OWNERS
        if owner.outputs and owner.service is not None
    ]
    assert not owners and actual_provider.owner is None
    assert not list(tmp_path.glob("*/native.*"))
    if case in ("send_denied", "cancel_wait", "late"):
        assert not list(tmp_path.glob("*/sent.marker"))
    else:
        assert len(list(tmp_path.glob("*/sent.marker"))) == 1


def test_loader_configured_and_nonwindows(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    config = module("local_inventory_config")
    env = {
        config.PREFIX + key: value
        for key, value in {
            "ENABLED": "1",
            "BUNDLE": "C:/inert/bundle",
            "STAGING": "C:/inert/staging",
            "SOURCE_REVIEW": "C:/inert/source.json",
            "RUNTIME_REVIEW": "C:/inert/runtime.json",
        }.items()
    }
    monkeypatch.setattr(config, "os", SimpleNamespace(name="nt", environ=env))
    result = config.load_local_inventory_provider()
    assert type(result).__name__ == "NativeLocalInventoryProvider"
    assert result._config.deadline_seconds == 20
    monkeypatch.setattr(config, "os", SimpleNamespace(name="posix", environ=env))
    assert config.load_local_inventory_provider() is None


@pytest.mark.parametrize(
    "relative",
    [
        "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_provider.py",
        "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_ipc.py",
        "services/tvt-bridge/src/wso_tvt_bridge/local_inventory_config.py",
        "packages/core/src/wso_core/tvt/local_service.py",
        "packages/core/src/wso_core/tvt/local_credentials.py",
        "packages/contracts/src/wso_contracts/tvt/local_device.py",
    ],
)
def test_source_receipt_pins_service_executables_and_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    fixture = helpers()
    p = module("windows_socket")
    context = fixture.inert_provider_root(tmp_path, monkeypatch)
    config = p.ProviderConfig(context["root"], context["root"], context["review"])
    assert p.verify_review(config) == context["manifest"]
    (context["root"] / relative).write_bytes(b"INERT DRIFT")
    with pytest.raises(p.ProviderError):
        p.verify_review(config)


@pytest.mark.parametrize(
    "case",
    ["extra", "no_roster", "zero_guid", "duplicate", "unreaped", "serial", "group"],
)
def test_private_observation_rejects_incomplete_or_extra_material(case: str) -> None:
    ipc = module("local_inventory_ipc")
    adapter = module("local_inventory_provider")
    row = {
        "guid": (b"G" * 16).hex(),
        "raw_index": 42,
        "window_index": 2,
        "ordinal": 1,
        "kind": "digital",
    }
    data = {
        "login_accepted": True,
        "same_original_session": True,
        "serial_matched": True,
        "channels_complete": True,
        "metadata_branch_complete": True,
        "permissions_complete": False,
        "proof_verified": False,
        "group_provenance": "empty",
        "channels": [row],
    }
    if case == "extra":
        data["serial"] = "SYNTHETIC9"
    elif case == "no_roster":
        data.pop("channels")
        data["channel_count"] = 1
    elif case == "zero_guid":
        row["guid"] = "0" * 32
    elif case == "duplicate":
        data["channels"] = [row, row]
    elif case == "serial":
        data["serial_matched"] = False
    elif case == "group":
        data["permissions_complete"] = True
    with pytest.raises((ValueError, LocalDeviceFailure)):
        adapter.observation(ipc.encode(data), cleanup_confirmed=case != "unreaped")


@pytest.mark.parametrize("case", ["foreign", "late"])
def test_remote_rejects_wrong_or_late_allow(case: str) -> None:
    ipc = module("local_inventory_ipc")
    parent = ipc.ParentAuthority(time.monotonic() + 0.1, threading.Event())
    parent.bind("a" * 32)
    remote = ipc.RemoteAuthority(parent.worker_connection, "a" * 32, parent.deadline)

    def reply() -> None:
        request = ipc.decode(parent.connection.recv_bytes(ipc.MAX_MESSAGE))
        if case == "late":
            time.sleep(0.15)
        try:
            parent.connection.send_bytes(
                ipc.encode(
                    {
                        **request,
                        "type": "decision",
                        "allow": True,
                        "generation": "b" * 32 if case == "foreign" else "a" * 32,
                    }
                )
            )
        except (BrokenPipeError, OSError):
            pass

    worker = threading.Thread(target=reply)
    worker.start()
    try:
        with pytest.raises(ipc.AuthorityError):
            remote.require("send")
    finally:
        worker.join(1)
        parent.close()


@pytest.mark.parametrize(
    "case",
    ["before", "accepted", "other_error", "missing_observation", "receive_error"],
)
def test_postpublication_close_only_accepts_windows_poll_109(case: str) -> None:
    import os
    from types import SimpleNamespace

    if os.name != "nt":
        pytest.skip("Windows pipe close semantics")
    ipc = module("local_inventory_ipc")
    parent = ipc.ParentAuthority(time.monotonic() + 1, threading.Event())
    parent._done = case != "before"
    parent.observation = (
        b"{}" if case not in ("before", "missing_observation") else None
    )
    error = BrokenPipeError()
    error.winerror = 5 if case == "other_error" else 109

    def fail(*args: Any) -> Any:
        raise error

    parent.connection = SimpleNamespace(
        poll=(lambda timeout: True) if case == "receive_error" else fail,
        recv_bytes=fail,
    )
    called: list[bool] = []
    allowed = parent.pump(lambda: called.append(True) or True)
    assert called == []
    assert allowed is (case == "accepted")
    assert parent._peer_closed is (case == "accepted")
    assert parent.failure == ("" if case == "accepted" else "protocol")


def test_extra_message_after_publication_still_denied_when_peer_closes() -> None:
    ipc = module("local_inventory_ipc")
    parent = ipc.ParentAuthority(time.monotonic() + 1, threading.Event())
    parent.bind("a" * 32)
    peer = parent.worker_connection
    try:
        peer.send_bytes(
            ipc.encode(
                {
                    "type": "current",
                    "generation": "a" * 32,
                    "sequence": 1,
                    "purpose": "publish",
                }
            )
        )
        assert parent.pump(lambda: True)
        peer.recv_bytes(ipc.MAX_MESSAGE)
        peer.send_bytes(
            ipc.encode(
                {
                    "type": "observation",
                    "generation": "a" * 32,
                    "sequence": 1,
                    "data": {},
                }
            )
        )
        assert parent.pump(lambda: True) and parent._done
        peer.send_bytes(
            ipc.encode(
                {
                    "type": "current",
                    "generation": "a" * 32,
                    "sequence": 2,
                    "purpose": "send",
                }
            )
        )
        peer.close()
        assert not parent.pump(lambda: True)
        assert parent.failure == "protocol" and not parent._peer_closed
    finally:
        parent.close()


@pytest.mark.parametrize("reason", ["cancelled", "deadline", "denied"])
def test_postpublication_closed_pipe_keeps_current_budget_gates(reason: str) -> None:
    ipc = module("local_inventory_ipc")
    parent = ipc.ParentAuthority(time.monotonic() + 1, threading.Event())
    parent._done = parent._peer_closed = True
    parent.observation = b"{}"
    if reason == "cancelled":
        parent.cancel.set()
    elif reason == "deadline":
        parent.deadline = time.monotonic() - 1
    assert not parent.tick(lambda: reason != "denied")
    assert parent.failure == reason
