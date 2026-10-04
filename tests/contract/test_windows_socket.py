"""Inert physical/native fakes and original child ownership; no vendor loads."""

from __future__ import annotations

import ctypes as ct
import hashlib
import io
import json
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, cast

import pytest
from wso_core.tvt import local_inventory as inventory_codec
from wso_core.tvt.local_live import LiveCodec, LiveError, PrivateLiveFrame
from wso_core.tvt.local_n9000 import (
    CodecError,
    Greeting,
    LoginHandshake,
    LoginResult,
    N9000Stream,
    Packet,
)
from wso_tvt_bridge import windows_socket as p
from wso_tvt_bridge import windows_socket_worker as w

GEN = "a" * 32


def inventory_request() -> p.PrivateRequest:
    return p.PrivateRequest(
        "inventory",
        "KR",
        "synthetic9",
        "syntheticUser",
        "syntheticSecret",
        metadata_read_opt_in=True,
    )


def metadata_reply(index: int, *, sequence: int | None = None) -> bytes:
    urls = ("queryBasicCfg", "queryNodeList", "doLogin", "queryAuthGroup")
    contents = (
        (
            '<content supplierAttr="ignored"><sn>SYNTHETIC9</sn>'
            "<name>Inert &amp; recorder</name><additionalCfg><item/></additionalCfg>"
            "</content>"
        ),
        (
            '<content total="catalog" count="ignored" supplierAttr="ignored">'
            '<item id="{01234567-89AB-CDEF-0123-456789ABCDEF}">'
            "<name>Private Camera &amp; side</name><chlIndex>3</chlIndex>"
            "<chlType>digital</chlType><winIndex>2</winIndex>"
            "<ignoredCfg><item/></ignoredCfg></item><itemType/></content>"
        ),
        (
            '<content supplierAttr="ignored"><userId>PRIVATE_USER</userId>'
            "<authGroupId>PRIVATE_GROUP</authGroupId><adminName>A &amp; B</adminName>"
            "<systemAuth><net>false</net><unusedCfg><child/></unusedCfg></systemAuth>"
            "<unknownMeta><item/></unknownMeta></content>"
        ),
        (
            '<content supplierAttr="ignored"><group><chlAuth>'
            '<item id="{01234567-89AB-CDEF-0123-456789ABCDEF}" extra="ignored">'
            "<auth>@lp</auth><other/></item><itemType/></chlAuth>"
            "<systemAuth><previewAndSnap>false</previewAndSnap><unknownMeta/></systemAuth>"
            "</group><unknown/></content>"
        ),
    )
    body = (
        bytes((0, 255, 1, 2)) * 29
        + (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<response clientType="MOBILE" cmdId="opaque" cmdUrl="{urls[index]}">'
            '<status>success</status><types><languageType><enum value="inert">English</enum>'
            '</languageType><catalogExtra><item kind="inert"/></catalogExtra></types>'
            f"{contents[index]}</response>"
        ).encode()
    )
    return (
        struct.pack(
            "<IIHBBIII",
            825307441,
            len(body) + 16,
            9,
            0,
            1,
            0x1000091B,
            index + 2 if sequence is None else sequence,
            len(body),
        )
        + body
    )


def inventory_login_reply(*, with_tail: bool = True) -> bytes:
    """Invented complete roster; detail replies cannot establish a missing one."""
    raw = bytearray(receive_login_reply())
    if with_tail:
        raw.extend(
            struct.pack("<hhhh", 1, 1, 20, 1)
            + bytes((1, 2, 3, 0))
            + bytes.fromhex("67452301ab89efcd0123456789abcdef")
            + struct.pack("<hhhh", 2, 1, 12, 1)
            + b"SYNTHETIC9\0\0"
        )
        struct.pack_into("<I", raw, 4, len(raw) - 8)
        struct.pack_into("<I", raw, 20, len(raw) - 24)
    return bytes(raw)


class InventoryNative:
    # The delegate is constructed at call time after ReceiveNative is defined.
    def __init__(self, *, coalesced: bool = False, bad: str = "") -> None:
        self.delegate = ReceiveNative()
        self.wires: list[bytes] = []
        self.coalesced, self.bad = coalesced, bad

    def call(self, name: str, *args: Any) -> Any:
        if self.delegate.observer is not None:
            assert not active_fix1_callback().lock.locked()
        if name != "send":
            return self.delegate.call(name, *args)
        wire = ct.string_at(args[1], args[2])
        self.wires.append(wire)
        index = len(self.wires) - 1
        response = (
            inventory_login_reply(with_tail=self.bad != "no_tail")
            if index == 0
            else metadata_reply(index - 1)
        )
        if index == 0 and self.bad == "login_rejected":
            response = receive_login_reply(rejected=19)
        if index == 0 and self.bad == "tail":
            tail_raw = bytearray(response + struct.pack("<hhhh", 77, 0, 0, 0))
            struct.pack_into("<I", tail_raw, 4, len(tail_raw) - 8)
            struct.pack_into("<I", tail_raw, 20, len(tail_raw) - 24)
            response = bytes(tail_raw)
        if index == 1 and self.bad == "serial":
            response = metadata_reply(0).replace(b"SYNTHETIC9", b"SYNTHETIC8")
        if index == 0 and self.coalesced:
            response += struct.pack("<II", 825307441, 0) + metadata_reply(0)
        if index == 1 and self.coalesced:
            response = b""
        if index == 2:
            if self.bad == "sequence":
                response = metadata_reply(1, sequence=99)
            elif self.bad == "rejected":
                body = struct.pack("<I", 17) + bytes(264)
                response = (
                    struct.pack(
                        "<IIHBBIII", 825307441, 284, 9, 0, 1, 0x2000091B, 3, 268
                    )
                    + body
                )
            elif self.bad == "error":
                raise OSError("PRIVATE_SUPPLIER_TEXT")
            elif self.bad == "interrupt":
                raise KeyboardInterrupt()
            elif self.bad == "overflow":
                response = bytes(65536)
            elif self.bad == "notification":
                response = receive_event()
            elif self.bad == "timeout":
                response = b""
            elif self.bad == "fragment":
                response = struct.pack("<II", 825307441, 0xFFFFFFFF)
        if index == 4 and self.bad == "trailing":
            response += receive_event()
        width = 65536 if self.bad == "overflow" and index == 2 else 17
        for start in range(0, len(response), width):
            raw = response[start : start + width]
            buffer = ct.create_string_buffer(raw)
            assert self.delegate.observer.contents.vptr.contents.data(
                self.delegate.observer,
                0x80000001,
                buffer,
                len(raw),
                None,
                self.delegate.context,
            ) == len(raw)
        if self.bad == "partial" and index == 2:
            return len(wire) - 1
        return len(wire)


def inventory_drive(native: InventoryNative) -> p.SafeResult:
    return w.drive(
        native,
        inventory_request(),
        GEN,
        time.monotonic() + 0.15,
        lambda name, raw: None,
    )


@pytest.mark.parametrize("value", [None, False, 1, "true"])
def test_inventory_requires_explicit_exact_boolean_optin(value: Any) -> None:
    with pytest.raises(p.ProviderError):
        p.PrivateRequest(
            "inventory",
            "KR",
            "synthetic9",
            "user",
            "secret",
            metadata_read_opt_in=value,
        )


@pytest.mark.parametrize("coalesced", [False, True])
def test_inventory_four_serialized_reads_preserve_login_and_transition(
    monkeypatch: pytest.MonkeyPatch,
    coalesced: bool,
) -> None:
    sessions: list[inventory_codec.InventorySession] = []
    bindings: list[dict[str, Any]] = []
    handshakes, _ = receive_observers(monkeypatch)
    original = inventory_codec.InventorySession

    def construct(**kwargs: Any) -> inventory_codec.InventorySession:
        bindings.append(kwargs.copy())
        obj = original(**kwargs)
        sessions.append(obj)
        return obj

    monkeypatch.setattr(w, "InventorySession", construct, raising=False)
    native = InventoryNative(coalesced=coalesced)
    result = inventory_drive(native)
    assert result.failure == "none" and result.inventory_complete
    assert result.inventory_queries_sent == result.inventory_replies == 4
    assert result.channel_count == 1 and result.serial_matched
    assert (
        result.channels_complete
        and result.permissions_complete
        and result.user_observed
    )
    assert len(native.wires) == 5
    assert [struct.unpack_from("<I", wire, 16)[0] for wire in native.wires] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert [wire[88:152].rstrip(b"\0") for wire in native.wires[1:]] == [
        b"queryBasicCfg",
        b"queryNodeList",
        b"doLogin",
        b"queryAuthGroup",
    ]
    assert bindings[0]["login"] is handshakes[0].history[-1]
    assert bindings[0]["generation"] == active_fix1_callback().generation
    assert bindings[0]["peer_version"] == 9 and bindings[0]["security"] == 0
    assert sessions[0].state == "terminal" and active_fix1_callback().closed
    assert not result.authorized and not result.live and not result.production_ready
    assert p.parse_result(result.to_json(), GEN) == result
    assert all(
        value not in result.to_json()
        for value in (
            b"Private Camera",
            b"PRIVATE_USER",
            b"PRIVATE_GROUP",
            b"synthetic",
            b"01234567",
        )
    )


@pytest.mark.parametrize(
    "bad,failure",
    [
        ("sequence", "codec"),
        ("notification", "deadline"),
        ("fragment", "unsupported"),
        ("timeout", "deadline"),
        ("partial", "send"),
    ],
)
def test_inventory_later_failure_keeps_only_login_history_no_retry(
    bad: str, failure: str
) -> None:
    native = InventoryNative(bad=bad)
    result = inventory_drive(native)
    assert result.failure == failure and result.reply_accepted
    assert not result.inventory_complete and not result.serial_matched
    assert len(native.wires) == 3 and result.inventory_replies == 1
    assert p.parse_result(result.to_json(), GEN) == result


@pytest.mark.parametrize("kind", ["close", "generation", "deadline", "callback"])
def test_inventory_postparse_guard_rejects_revocation(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    original = inventory_codec._xml

    def revoked(raw: bytes, limits: Any) -> Any:
        parsed = original(raw, limits)
        owner = active_fix1_callback()
        if kind == "close":
            owner.closed = True
        elif kind == "generation":
            owner.context.value += 1
        elif kind == "callback":
            owner.mark_failed()
        else:
            monkeypatch.setattr(time, "monotonic", lambda: 1e30)
        return parsed

    monkeypatch.setattr(inventory_codec, "_xml", revoked)
    native = InventoryNative()
    result = inventory_drive(native)
    assert result.failure != "none" and not result.inventory_complete
    assert result.inventory_replies == 0 and len(native.wires) == 2
    assert result.reply_accepted and not result.authorized


def test_inventory_safe_dto_rejects_inconsistent_projection() -> None:
    result = p.SafeResult(GEN)
    data = json.loads(result.to_json())
    for key, value in (
        ("inventory_complete", True),
        ("serial_matched", True),
        ("inventory_replies", 5),
        ("channel_count", 257),
        ("inventory_queries_sent", True),
    ):
        changed = {**data, key: value}
        with pytest.raises(p.ProviderError):
            p.parse_result(json.dumps(changed).encode(), GEN)


def test_inventory_owned_direct_interpreter_job_custody(tmp_path: Path) -> None:
    # Real CPython and Windows Job only. The marker PID must be the Popen PID;
    # killing a venv redirector instead would leave the actual interpreter alive.
    direct, site = p.direct_interpreter()
    assert direct.name.lower() == "python.exe" and direct.parent.name != "Scripts"
    assert site == Path(sys.prefix) / "Lib/site-packages"
    outputs = ((tmp_path / "stdout").open("w+b"), (tmp_path / "stderr").open("w+b"))
    owner = p.ChildOwner(None, None, outputs)
    try:
        owner.job = p.OwnedJob()
        owner.job.create()
        owner.child = subprocess.Popen(
            [
                str(direct),
                "-I",
                "-S",
                "-c",
                (
                    "import sys,os,time,subprocess\n"
                    "sys.stdin.buffer.read(1)\n"
                    "blocked = False\n"
                    "try:\n"
                    "    other = subprocess.Popen([sys.executable, '-I', '-S', '-c', 'pass'])\n"
                    "    other.wait(timeout=2)\n"
                    "except OSError:\n"
                    "    blocked = True\n"
                    "print(str(os.getpid()) + ':' + str(int(blocked)), flush=True)\n"
                    "time.sleep(30)\n"
                ),
            ],
            stdin=subprocess.PIPE,
            stdout=outputs[0],
            stderr=outputs[1],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        owner.job.admit(owner.child)
        assert owner.child.stdin is not None
        owner.child.stdin.write(b"J")
        owner.child.stdin.flush()
        limit = time.monotonic() + 3
        observed = b""
        while time.monotonic() < limit and not observed:
            outputs[0].seek(0)
            observed = outputs[0].read()
            time.sleep(0.01)
        observed_pid, blocked = observed.strip().split(b":")
        assert int(observed_pid) == owner.child.pid and blocked == b"1"
        assert owner.finish(2)
        assert owner.child.poll() is not None and owner.job.closed
        assert all(output.closed for output in outputs)
    finally:
        owner.finish(2)


def test_inventory_bootstrap_denies_before_application_import(tmp_path: Path) -> None:
    # The real bootstrap is given EOF without an admission marker. No worker
    # module or venv package activation can occur, even outside a Job.
    command = p.worker_command()
    child = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=tmp_path,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    stdout, stderr = child.communicate(b"", timeout=5)
    assert child.returncode != 0 and stdout == stderr == b""


class FakeNative:
    def __init__(
        self,
        *,
        status: int = 1,
        greeting_count: int = 64,
        send: int = 260,
        reply: bytes | None = None,
        initialized: bool = True,
        connected: bool = True,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.status = status
        self.greeting_count = greeting_count
        self.send = send
        self.reply = reply
        self.initialized = initialized
        self.connected = connected
        self.observer: Any = None
        self.context: Any = None

    def call(self, name: str, *args: Any) -> Any:
        self.calls.append((name, args))
        if name == "initial":
            return self.initialized
        if name == "last_error":
            return 0x20000001
        if name == "connect_sn":
            return 0x80000001
        if name == "connect_result":
            ct.cast(args[1], ct.POINTER(ct.c_int32))[0] = self.status
            return True
        if name == "connected":
            return self.connected
        if name == "greeting":
            greeting = bytearray(64)
            struct.pack_into("<i", greeting, 12, 10)
            ct.memmove(args[1], bytes(greeting), 64)
            return self.greeting_count
        if name == "register":
            self.observer = ct.cast(args[1], ct.POINTER(w.Observer))
            self.context = args[2]
            return True
        if name == "start":
            return True
        if name == "send":
            assert args[4] == 0 and args[5] is None
            assert args[3] is not None
            if self.reply is not None:
                for raw in (self.reply[:7], self.reply[7:31], self.reply[31:]):
                    buffer = ct.create_string_buffer(raw)
                    assert self.observer.contents.vptr.contents.data(
                        self.observer, 0x80000001, buffer, len(raw), None, self.context
                    ) == len(raw)
            return self.send
        return None


def reply(*, rejection: int | None = None, sequence: int = 1) -> bytes:
    body = bytearray(132 if rejection is None else 268)
    if rejection is not None:
        struct.pack_into("<I", body, 0, rejection)
    command = 0x10000101 if rejection is None else 0x20000101
    return (
        struct.pack(
            "<IIHBBIII",
            825307441,
            16 + len(body),
            3,
            0,
            1,
            command,
            sequence,
            len(body),
        )
        + body
    )


def execute(native: FakeNative, mode: p.Mode = "handshake") -> p.SafeResult:
    request = (
        p.PrivateRequest(mode)
        if mode in ("load", "initialize")
        else p.PrivateRequest(
            mode,
            "KR",
            "synthetic9",
            "syntheticUser" if mode == "handshake" else "",
            "syntheticSecret" if mode == "handshake" else "",
        )
    )
    return w.drive(
        native, request, GEN, time.monotonic() + 0.06, lambda name, raw: None
    )


def test_exact_header_symbols_signatures_and_physical_layout() -> None:
    # Independent approved header names/order, no DLL load or compiler.
    text = (
        p.ROOT / "services/tvt-windows-helper/include/tvt_socket_verified.h"
    ).read_text()
    w.validate_layout(production=False)
    assert len(w.SPECS) == 15
    for symbol, _, _ in w.SPECS.values():
        assert f'"{symbol}"' in text
    assert w.SPECS["initial"][1:] == (
        ct.c_bool,
        (ct.c_int32, ct.c_int32, ct.c_char_p, ct.c_uint32),
    )
    assert w.SPECS["connect_result"][2] == (
        ct.c_int32,
        ct.POINTER(ct.c_int32),
        ct.c_uint32,
    )
    assert w.SPECS["connect_sn"][2] == (ct.c_uint32, ct.c_char_p, ct.c_uint16)
    assert w.SPECS["send"][2] == (
        ct.c_int32,
        ct.c_char_p,
        ct.c_uint64,
        ct.c_char_p,
        ct.c_uint64,
        ct.c_void_p,
        ct.c_uint32,
    )
    assert tuple(w.DATA._argtypes_) == (
        ct.c_void_p,
        ct.c_uint32,
        ct.c_void_p,
        ct.c_int32,
        ct.c_void_p,
        ct.c_void_p,
    )
    assert w.DATA._restype_ is ct.c_int32
    assert ct.sizeof(w.Observer) == 8 and ct.sizeof(w.ObserverTable) == 16
    assert w.ObserverTable.data.offset == 8


@pytest.mark.parametrize(
    "mode,names",
    [
        ("load", []),
        ("initialize", ["initial", "quit"]),
    ],
)
def test_modes_bound_native_calls(mode: p.Mode, names: list[str]) -> None:
    native = FakeNative()
    result = execute(native, mode)
    assert [name for name, _ in native.calls] == names
    assert result.stage == "complete" and not result.authorized and not result.live
    assert not result.quiescence_verified


def test_initial_false_and_same_thread_error_no_config_or_quit() -> None:
    native = FakeNative(initialized=False)
    result = execute(native)
    assert [name for name, _ in native.calls] == ["initial", "last_error"]
    assert result.native_error == 0x20000001 and result.failure == "runtime"


@pytest.mark.parametrize("status,connected", [(-1, True), (0, True), (1, False)])
def test_only_established_plus_state_permits_greeting(
    status: int, connected: bool
) -> None:
    native = FakeNative(status=status, connected=connected)
    result = execute(native)
    assert not result.transport and not result.reply_accepted
    assert "greeting" not in [name for name, _ in native.calls]


@pytest.mark.parametrize("count", [-1, 0, 63, 65])
def test_only_exact64_cached_greeting_is_admitted(count: int) -> None:
    native = FakeNative(greeting_count=count)
    result = execute(native)
    assert result.failure == "greeting"
    assert "send" not in [name for name, _ in native.calls]
    assert len([name for name, _ in native.calls if name == "greeting"]) == 1


def test_signed_handle_config_observer_order_and_connect_not_auth() -> None:
    native = FakeNative()
    result = execute(native, "connect")
    names = [name for name, _ in native.calls]
    assert names.index("register") < names.index("start")
    assert names[-3:] == ["stop", "destroy", "quit"]
    assert next(args for name, args in native.calls if name == "config") == (
        None,
        0,
        False,
        b"cli-nat20.autonatap.com",
        7968,
    )
    assert next(args for name, args in native.calls if name == "connect_sn") == (
        0,
        b"SYNTHETIC9",
        0,
    )
    assert all(
        args[0] == -2147483647
        for name, args in native.calls
        if name in ("greeting", "register", "start", "stop", "destroy")
    )
    assert result.transport and result.greeting_bytes == 64
    assert not result.reply_accepted and not result.authorized


def test_partial_callback_frames_one_login_and_acceptance_is_not_authority() -> None:
    native = FakeNative(reply=reply())
    result = execute(native)
    assert result.reply_accepted and result.key_extracted and not result.proof_verified
    assert not result.authorized and not result.live
    assert result.received_bytes == len(reply())
    assert [name for name, _ in native.calls].count("send") == 1


def test_typed_rejection_no_retries() -> None:
    native = FakeNative(reply=reply(rejection=17))
    result = execute(native)
    assert result.failure == "rejected" and result.native_error == 17
    assert not result.reply_accepted
    assert [name for name, _ in native.calls].count("send") == 1


def test_wrong_sequence_fences_acceptance() -> None:
    result = execute(FakeNative(reply=reply(sequence=2)))
    assert result.failure == "codec" and not result.reply_accepted


@pytest.mark.parametrize("send", [-1, 0, 260])
def test_enqueue_without_reply_never_passes(send: int) -> None:
    native = FakeNative(send=send)
    result = execute(native)
    assert result.failure == ("deadline" if send > 0 else "send")
    assert not result.reply_accepted
    assert [name for name, _ in native.calls].count("send") == 1


def invoke(owner: w.CallbackOwner, raw: bytes, **kwargs: Any) -> int:
    buffer = ct.create_string_buffer(raw)
    return owner._data(
        kwargs.get("this", owner.this_address),
        kwargs.get("handle", owner.handle),
        ct.addressof(buffer),
        len(raw),
        kwargs.get("opaque", 0),
        kwargs.get("context", owner.context_address),
    )


def test_callback_copies_borrowed_data_without_reentry() -> None:
    owner = w.CallbackOwner(-1, 1)
    buffer = ct.create_string_buffer(b"abc")
    assert (
        owner._data(
            owner.this_address,
            0xFFFFFFFF,
            ct.addressof(buffer),
            3,
            0,
            owner.context_address,
        )
        == 3
    )
    buffer[0] = b"z"
    assert owner.take() == b"abc"
    assert owner in w.RETAINED


@pytest.mark.parametrize("foreign", ["this", "handle", "context", "opaque"])
def test_callback_foreign_physical_ownership_fails(foreign: str) -> None:
    owner = w.CallbackOwner(7, 1)
    assert invoke(owner, b"abc", **{foreign: 999}) == 0
    assert owner.failed and owner.take() is None


def test_callback_overflow_reentrant_lock_and_closed_generation() -> None:
    owner = w.CallbackOwner(7, 1, capacity=4)
    assert invoke(owner, b"abc") == 3
    assert invoke(owner, b"de") == 0 and owner.failed
    owner = w.CallbackOwner(7, 2)
    owner.lock.acquire()
    try:
        assert invoke(owner, b"abc") == 0
    finally:
        owner.lock.release()
    owner = w.CallbackOwner(7, 3)
    owner.closed = True
    assert invoke(owner, b"abc") == 0
    assert owner._delete(owner.this_address, 1) == owner.this_address
    assert owner in w.RETAINED


@pytest.mark.parametrize("serial", ["", "A" * 64, "A\0B", "a/b", "é"])
def test_private_serial_bounds(serial: str) -> None:
    with pytest.raises(p.ProviderError):
        p.PrivateRequest("connect", "KR", serial)


def test_duplicate_json_and_safe_projection_excludes_private_values() -> None:
    with pytest.raises(p.ProviderError) as error:
        p.json_object(b'{"serial":"syntheticSecret","serial":"x"}')
    assert "syntheticSecret" not in str(error.value)
    assert error.value.__context__ is None
    safe = p.SafeResult(GEN)
    assert p.parse_result(safe.to_json(), GEN) == safe
    raw = json.loads(safe.to_json())
    raw["secret"] = "syntheticSecret"
    with pytest.raises(p.ProviderError):
        p.parse_result(json.dumps(raw).encode(), GEN)
    assert "synthetic" not in repr(
        p.PrivateRequest(
            "handshake", "KR", "synthetic9", "syntheticUser", "syntheticSecret"
        )
    )


@pytest.mark.parametrize(
    "sddl",
    [
        "O:S-1-5-21-1D:(A;;FA;;;S-1-5-21-1)",
        "O:S-1-5-21-1D:P(A;;FA;;;WD)",
        "O:S-1-5-21-1D:P(A;;FR;;;S-1-5-21-1)",
    ],
)
def test_unprotected_public_or_partial_acl_fails(sddl: str) -> None:
    with pytest.raises(p.ProviderError):
        p.validate_sddl(sddl, "S-1-5-21-1")


def test_owner_system_protected_acl() -> None:
    p.validate_sddl(
        "O:S-1-5-21-1D:P(A;OICI;FA;;;S-1-5-21-1)(A;OICI;FA;;;SY)", "S-1-5-21-1"
    )


def test_bundle_mismatch_fails_before_native_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered: list[bool] = []
    monkeypatch.setattr(ct, "CDLL", lambda *a, **kw: entered.append(True))
    monkeypatch.setattr(w, "validate_layout", lambda: None)
    manifest = [
        {"name": f"test{i}.dll", "bytes": 4, "sha256": "0" * 64} for i in range(14)
    ]
    directory = Path("C:/inert-manifest")
    monkeypatch.setattr(p, "identity", lambda *args, **kwargs: (1, 2))
    monkeypatch.setattr(
        Path,
        "iterdir",
        lambda self: iter(directory / str(row["name"]) for row in manifest),
    )
    monkeypatch.setattr(p, "file_hash", lambda path: {"bytes": 4, "sha256": "1" * 64})
    with pytest.raises(p.ProviderError):
        w.NativeSurface(directory, manifest)
    assert not entered


def test_foreign_mapped_dependency_rejected(tmp_path: Path) -> None:
    with pytest.raises(p.ProviderError):
        w.verify_mapped(
            tmp_path,
            [{"name": "NetSocket.dll", "bytes": 1, "sha256": "0" * 64}],
            {"NetSocket.dll": (1, 2)},
            lambda name: tmp_path.parent / name,
        )


class UncertainChild:
    def __init__(self) -> None:
        self.kills = 0
        self.exited = False
        self.stdin = io.BytesIO()

    def poll(self) -> int | None:
        return 1 if self.exited else None

    def kill(self) -> None:
        self.kills += 1
        raise OSError("syntheticSecret")

    def wait(self, timeout: float) -> int:
        if not self.exited:
            raise subprocess.TimeoutExpired("syntheticSecret", timeout)
        return 1


class CancellableFixtureOwner(p.ChildOwner):
    """Test waiter cancellation only; production finish/stdin proof stays real."""

    def __init__(
        self,
        child: subprocess.Popen[bytes],
        writer: threading.Thread,
        outputs: tuple[BinaryIO, BinaryIO],
    ) -> None:
        super().__init__(child, writer, outputs)
        self.cancel_wait = threading.Event()
        self.wait_started = threading.Event()

    def passive_wait(self) -> None:
        self.wait_started.set()
        while not self.confirmed and not self.cancel_wait.wait(0.01):
            self.finish(timeout=0.01)


def finish_uncertain_fixture(
    owner: CancellableFixtureOwner,
    child: UncertainChild,
    waiter: threading.Thread,
) -> None:
    child.exited = True
    # Cancellation is test-local and never sets confirmed or replaces finish.
    owner.cancel_wait.set()
    if waiter.ident is not None:
        waiter.join(timeout=1)
    assert not waiter.is_alive(), "Inert waiter did not leave its cancelled loop"
    assert owner.finish(timeout=0.01), "Original inert handles did not confirm cleanup"


def test_original_uncertain_child_retained_blocks_next_attempt_and_cli_exit() -> None:
    child = UncertainChild()
    writer = threading.Thread(target=lambda: None, daemon=False)
    writer.start()
    outputs = (io.BytesIO(), io.BytesIO())
    owner = CancellableFixtureOwner(
        cast(subprocess.Popen[bytes], child),
        writer,
        cast(tuple[BinaryIO, BinaryIO], outputs),
    )
    provider = p.WindowsSocketProvider()
    provider.owner = owner
    waiter = threading.Thread(target=p.cli_lifetime, args=(provider,), daemon=False)
    try:
        assert not owner.finish(0.001) and not owner.confirmed
        assert child.kills == 1 and not outputs[0].closed
        with pytest.raises(p.ProviderError):
            provider.run(
                p.ProviderConfig(
                    Path("C:/inert"), Path("C:/inert"), Path("C:/inert/receipt")
                ),
                p.PrivateRequest("load"),
            )
        waiter.start()
        assert owner.wait_started.wait(timeout=1)
        assert waiter.is_alive() and child.kills == 1
        child.exited = True
        waiter.join(timeout=1)
        assert not waiter.is_alive() and owner.confirmed and outputs[0].closed
        assert child.stdin.closed and child.kills == 1
    finally:
        finish_uncertain_fixture(owner, child, waiter)


def test_original_real_inert_child_is_killed_reaped_and_pipe_writer_joined() -> None:
    # Actual owned Python only: no vendor modules/network/device/input secrets.
    child = subprocess.Popen(
        [
            str(p.direct_interpreter()[0]),
            "-I",
            "-S",
            "-c",
            "import time; time.sleep(30)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def close_input() -> None:
        assert child.stdin is not None
        child.stdin.close()

    writer = threading.Thread(target=close_input, daemon=False)
    writer.start()
    outputs = (io.BytesIO(), io.BytesIO())
    owner = p.ChildOwner(child, writer, cast(tuple[BinaryIO, BinaryIO], outputs))
    try:
        assert owner.finish(2)
        assert child.poll() is not None and not writer.is_alive()
        assert outputs[0].closed and owner.confirmed
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_root_receipt_gate_rejects_author_owned_packet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inert_provider_root(tmp_path, monkeypatch)
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"status":"AUTHOR_READY"}')
    with pytest.raises(p.ProviderError):
        p.verify_review(p.ProviderConfig(tmp_path, tmp_path, receipt))


def test_all15_primitive_argument_and_return_widths() -> None:
    # Independently transcribed from approved header primitive declarations.
    expected = {
        "initial": (ct.c_bool, (ct.c_int32, ct.c_int32, ct.c_char_p, ct.c_uint32)),
        "quit": (None, ()),
        "last_error": (ct.c_uint32, ()),
        "config": (
            None,
            (ct.c_char_p, ct.c_uint32, ct.c_bool, ct.c_char_p, ct.c_uint32),
        ),
        "connect_sn": (ct.c_int32, (ct.c_uint32, ct.c_char_p, ct.c_uint16)),
        "connect_result": (
            ct.c_bool,
            (ct.c_int32, ct.POINTER(ct.c_int32), ct.c_uint32),
        ),
        "connected": (ct.c_bool, (ct.c_int32,)),
        "register": (
            ct.c_bool,
            (ct.c_int32, ct.POINTER(w.Observer), ct.c_void_p, ct.c_int32, ct.c_int32),
        ),
        "start": (ct.c_bool, (ct.c_int32,)),
        "stop": (None, (ct.c_int32,)),
        "destroy": (None, (ct.c_int32,)),
        "del_connect": (None, (ct.c_int32,)),
        "unregister": (None, (ct.c_int32,)),
        "greeting": (
            ct.c_int32,
            (ct.c_int32, ct.POINTER(ct.c_char), ct.c_int32, ct.c_bool, ct.c_uint32),
        ),
        "send": (
            ct.c_int32,
            (
                ct.c_int32,
                ct.c_char_p,
                ct.c_uint64,
                ct.c_char_p,
                ct.c_uint64,
                ct.c_void_p,
                ct.c_uint32,
            ),
        ),
    }
    assert {name: spec[1:] for name, spec in w.SPECS.items()} == expected


def test_stale_context_value_fences_same_addresses() -> None:
    owner = w.CallbackOwner(7, 1)
    owner.context.value = 2
    assert invoke(owner, b"abc") == 0 and owner.failed


def test_parent_hard_deadline_owns_original_inert_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = subprocess.Popen
    spawned: list[subprocess.Popen[bytes]] = []
    argv_seen: list[list[str]] = []

    def inert_launch(argv: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        argv_seen.append(argv)
        child = original(
            [
                str(p.direct_interpreter()[0]),
                "-I",
                "-S",
                "-c",
                "import time; time.sleep(30)",
            ],
            **kwargs,
        )
        spawned.append(child)
        return child

    monkeypatch.setattr(p, "verify_review", lambda config: [])
    monkeypatch.setattr(p, "validate_bundle", lambda directory, manifest: {})
    monkeypatch.setattr(p, "check_private_acl", lambda path: None)
    monkeypatch.setattr(p, "protect_created_acl", lambda path: None)
    # pytest's current-user temp path is Unicode; this explicit inert hook
    # bypasses ASCII staging only for the original-child ownership test.
    monkeypatch.setattr(p.ProviderConfig, "__post_init__", lambda self: None)
    monkeypatch.setattr(subprocess, "Popen", inert_launch)
    provider = p.WindowsSocketProvider()
    started = time.monotonic()
    result = provider.run(
        p.ProviderConfig(tmp_path, tmp_path, tmp_path / "receipt", 1),
        p.PrivateRequest("load"),
    )
    assert time.monotonic() - started < 4
    assert result.stage == "deadline" and result.failure == "deadline" and result.reaped
    assert provider.owner is not None and provider.owner.child is spawned[0]
    assert spawned[0].poll() is not None and provider.owner.confirmed
    assert argv_seen == [p.worker_command()]


def test_pending_original_owner_fences_a_new_provider() -> None:
    child = UncertainChild()
    writer = threading.Thread(target=lambda: None, daemon=False)
    writer.start()
    owner = p.ChildOwner(
        cast(subprocess.Popen[bytes], child),
        writer,
        cast(tuple[BinaryIO, BinaryIO], (io.BytesIO(), io.BytesIO())),
    )
    p.PENDING_OWNERS.append(owner)
    try:
        with pytest.raises(p.ProviderError):
            p.WindowsSocketProvider().run(
                p.ProviderConfig(
                    Path("C:/inert"), Path("C:/inert"), Path("C:/inert/receipt")
                ),
                p.PrivateRequest("load"),
            )
    finally:
        child.exited = True
        assert owner.finish()
        assert child.stdin.closed and not writer.is_alive()


def test_fix2_waiter_fixture_finalizes_after_body_assertion() -> None:
    child = UncertainChild()
    writer = threading.Thread(target=lambda: None, daemon=False)
    writer.start()
    outputs = (io.BytesIO(), io.BytesIO())
    owner = CancellableFixtureOwner(
        cast(subprocess.Popen[bytes], child),
        writer,
        cast(tuple[BinaryIO, BinaryIO], outputs),
    )
    provider = p.WindowsSocketProvider()
    provider.owner = owner
    waiter = threading.Thread(target=p.cli_lifetime, args=(provider,), daemon=False)
    with pytest.raises(AssertionError, match="synthetic fixture body failure"):
        try:
            waiter.start()
            assert owner.wait_started.wait(timeout=1)
            assert waiter.is_alive() and not owner.confirmed
            raise AssertionError("synthetic fixture body failure")
        finally:
            finish_uncertain_fixture(owner, child, waiter)
    assert owner.confirmed and not waiter.is_alive() and not writer.is_alive()
    assert child.stdin.closed and all(output.closed for output in outputs)


def runtime_row() -> dict[str, Any]:
    return {
        "path": "C:/inert-python/VCRUNTIME140.dll",
        "bytes": 120400,
        "sha256": "052ad6a20d375957e82aa6a3c441ea548d89be0981516ca7eb306e063d5027f4",
        "version": "14.42.34438.0",
    }


def runtime_rows() -> dict[str, dict[str, Any]]:
    return {
        "vcruntime140.dll": runtime_row(),
        "vcruntime140_1.dll": {
            "path": "C:/inert-python/VCRUNTIME140_1.dll",
            "bytes": 49776,
            "sha256": "6a99bc0128e0c7d6cbbf615fcc26909565e17d4ca3451b97f8987f9c6acbc6c8",
            "version": "14.42.34438.0",
        },
    }


def runtime_hash(rows: dict[str, dict[str, Any]], path: Path) -> dict[str, Any]:
    row = rows[path.name.lower()]
    return {k: row[k] for k in ("bytes", "sha256")}


def inert_provider_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """Only synthetic isolated approvals; never read/publish local Root packets."""
    assert p.ABI_RECEIPT == p.SDD + "W04-windows-socket-abi-reviewed-root-receipt.json"
    assert (
        p.RUNTIME_RECEIPT
        == p.SDD
        + "W04-windows-python-crypto-runtime-override-reviewed-root-receipt.json"
    )
    assert (
        p.ACCEPTED_HASHES[p.ABI_RECEIPT]
        == "75fc1cc60907375b7306c484562f22d6944f5ea92f5203201a629fb3f5e6abdf"
    )
    assert (
        p.ACCEPTED_HASHES[p.RUNTIME_RECEIPT]
        == "77eb86a01a0c53a5e9998417f67b337aa38b96c0e5d62e1ee2ce333309eec45d"
    )
    root = tmp_path / "inert-provider-root"
    root.mkdir()
    assert (
        not (root / p.ABI_RECEIPT).exists() and not (root / p.RUNTIME_RECEIPT).exists()
    )

    def write(relative: str, raw: bytes) -> dict[str, str | int]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def receipt(relative: str, value: dict[str, Any]) -> dict[str, str | int]:
        return write(relative, json.dumps(value, sort_keys=True).encode())

    names = (
        "libeay32.dll",
        "log4cxx.dll",
        "msvcr100.dll",
        "ssleay32.dll",
        "mfc140u.dll",
        "msvcp100.dll",
        "msvcp140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "NatClientSDK.dll",
        "Network.dll",
        "OpensslSDK.dll",
        "NetSocket.dll",
        "ShareLib.dll",
    )
    manifest = [
        {
            "name": name,
            "bytes": len(name),
            "sha256": hashlib.sha256(("INERT:" + name).encode()).hexdigest(),
        }
        for name in names
    ]
    abi_files = {"inert/abi.txt": write("inert/abi.txt", b"INERT ABI TEXT")}
    abi = receipt(
        p.ABI_RECEIPT,
        {
            "inertFixture": True,
            "status": "ACCEPTED_WINDOWS_SOCKET_ABI_ROOT_REVIEW",
            "files": abi_files,
            "bundle": manifest,
        },
    )
    codec_files = {
        relative: write(relative, ("INERT:" + relative).encode())
        for relative in (
            "packages/core/src/wso_core/tvt/local_n9000.py",
            "tests/tvt_parity/test_local_n9000.py",
            "docs/integrations/tvt-local-n9000-codec.md",
        )
    }
    codec = receipt(
        p.CODEC_RECEIPT,
        {
            "inertFixture": True,
            "status": "SOURCE_ACCEPTED_UNPUBLISHED",
            "files": codec_files,
        },
    )
    inventory_files = {
        relative: write(relative, ("INERT:" + relative).encode())
        for relative in (
            "packages/core/src/wso_core/tvt/local_inventory.py",
            "tests/tvt_parity/test_local_inventory.py",
            "docs/integrations/tvt-local-inventory-codec.md",
        )
    }
    inventory = receipt(
        p.INVENTORY_RECEIPT,
        {
            "inertFixture": True,
            "status": "SOURCE_ACCEPTED_UNPUBLISHED",
            "files": inventory_files,
        },
    )
    live_files = {
        relative: write(relative, ("INERT:" + relative).encode())
        for relative in (
            "packages/core/src/wso_core/tvt/local_live.py",
            "tests/tvt_parity/test_local_live.py",
            "docs/integrations/tvt-local-live-codec.md",
        )
    }
    frame_path = "packages/core/src/wso_core/tvt/frames.py"
    frame_identity = write(frame_path, b"INERT READONLY FRAME TIMESTAMP")
    live = receipt(
        p.LIVE_RECEIPT,
        {
            "inertFixture": True,
            "status": "SOURCE_ACCEPTED_WITH_EVIDENCE_QUALIFICATION_UNPUBLISHED",
            "files": live_files,
            "dependencies": {frame_path: frame_identity},
        },
    )
    runtime = receipt(
        p.RUNTIME_RECEIPT, {"inertFixture": True, "allowedOverrides": runtime_rows()}
    )
    old_runtime = receipt(
        p.SDD + "W04-windows-python-runtime-override-reviewed-root-receipt.json",
        {"inertFixture": True, "allowedOverrides": {"vcruntime140.dll": runtime_row()}},
    )
    for relative in (
        "packages/core/src/wso_core/tvt/local_bootstrap.py",
        "packages/core/src/wso_core/tvt/device_qr.py",
        "packages/core/src/wso_core/tvt/local_credentials.py",
        "packages/core/src/wso_core/tvt/local_service.py",
        "packages/contracts/src/wso_contracts/tvt/local_device.py",
    ):
        write(relative, b"INERT DEPENDENCY")

    def identity(path: Path, *, directory: bool = False) -> tuple[int, int]:
        assert path.is_relative_to(root) or path.is_relative_to(tmp_path)
        info = path.stat()
        assert path.is_dir() == directory
        return info.st_dev, info.st_ino

    pins = {
        p.ABI_RECEIPT: abi["sha256"],
        p.CODEC_RECEIPT: codec["sha256"],
        p.INVENTORY_RECEIPT: inventory["sha256"],
        p.LIVE_RECEIPT: live["sha256"],
        p.RUNTIME_RECEIPT: runtime["sha256"],
    }
    own_files = {
        relative: write(relative, ("INERT OWN:" + relative).encode())
        for relative in p.OWNED
    }
    dependencies = {
        relative: write(relative, b"INERT DEPENDENCY")
        for relative in (
            "packages/core/src/wso_core/tvt/local_bootstrap.py",
            "packages/core/src/wso_core/tvt/device_qr.py",
            "packages/core/src/wso_core/tvt/local_credentials.py",
            "packages/core/src/wso_core/tvt/local_service.py",
            "packages/contracts/src/wso_contracts/tvt/local_device.py",
        )
    }
    dependencies.update(
        {
            p.ABI_RECEIPT: abi,
            p.CODEC_RECEIPT: codec,
            p.RUNTIME_RECEIPT: runtime,
            p.INVENTORY_RECEIPT: inventory,
            p.LIVE_RECEIPT: live,
            frame_path: frame_identity,
        }
    )
    review = receipt(
        "inert/source-review.unit.json",
        {
            "status": "ACCEPTED_WINDOWS_NATIVE_PROVIDER_ROOT_REVIEW",
            "files": own_files,
            "dependencies": dependencies,
            "critical": 0,
            "important": 0,
            "minor": 0,
        },
    )
    monkeypatch.setattr(p, "ROOT", root)
    monkeypatch.setattr(p, "identity", identity)
    monkeypatch.setattr(p, "ACCEPTED_HASHES", pins)
    monkeypatch.setattr(p, "check_private_acl", lambda path: None)
    monkeypatch.setattr(p.ProviderConfig, "__post_init__", lambda self: None)
    return {
        "root": root,
        "manifest": manifest,
        "codecFiles": codec_files,
        "inventoryFiles": inventory_files,
        "liveFiles": live_files,
        "framePath": frame_path,
        "runtime": runtime,
        "oldRuntime": old_runtime,
        "pins": pins,
        "review": root / "inert/source-review.unit.json",
        "reviewIdentity": review,
    }


def test_narrow_r90_two_runtime_identities_disclosed_and_original14_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = inert_provider_root(tmp_path, monkeypatch)
    rows = runtime_rows()
    bundle = Path("C:/inert-package")
    manifest = fixture["manifest"]
    package_rows = {row["name"].lower(): row for row in manifest}

    def file_identity(path: Path) -> dict[str, Any]:
        if path.parent == Path("C:/inert-python"):
            return runtime_hash(rows, path)
        row = package_rows[path.name.lower()]
        return {k: row[k] for k in ("bytes", "sha256")}

    monkeypatch.setattr(w, "file_hash", file_identity)
    monkeypatch.setattr(w, "identity", lambda path: (1, 2))
    assert (
        w.verify_mapped(
            bundle,
            manifest,
            {row["name"]: (1, 2) for row in manifest},
            lambda name: Path(rows[name]["path"]) if name in rows else bundle / name,
            rows,
        )
        == 2
    )
    safe = p.SafeResult(GEN, runtime_substitutions=2)
    parsed = p.parse_result(safe.to_json(), GEN)
    assert parsed.runtime_substitutions == 2 and parsed.development_debug_only
    assert not parsed.production_ready
    assert all(row["path"] not in safe.to_json().decode() for row in rows.values())


@pytest.mark.parametrize(
    "field,value", [("bytes", 120401), ("version", "14.43.0"), ("sha256", "0" * 64)]
)
@pytest.mark.parametrize("name", ["vcruntime140.dll", "vcruntime140_1.dll"])
def test_r90_metadata_tamper_rejected(
    name: str,
    field: str,
    value: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = runtime_rows()
    monkeypatch.setattr(w, "file_hash", lambda path: runtime_hash(runtime_rows(), path))
    rows[name][field] = value
    with pytest.raises(p.ProviderError):
        w.verify_runtime_override(rows, lambda name: Path(rows[name]["path"]))


@pytest.mark.parametrize("name", ["vcruntime140.dll", "vcruntime140_1.dll"])
def test_r90_wrong_mapped_path_or_current_hash_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    rows = runtime_rows()
    monkeypatch.setattr(w, "file_hash", lambda path: runtime_hash(rows, path))
    with pytest.raises(p.ProviderError):
        w.verify_runtime_override(
            rows,
            lambda module: (
                Path("C:/other") / module
                if module == name
                else Path(rows[module]["path"])
            ),
        )
    monkeypatch.setattr(
        w,
        "file_hash",
        lambda path: (
            {"bytes": rows[name]["bytes"], "sha256": "0" * 64}
            if path.name.lower() == name
            else runtime_hash(rows, path)
        ),
    )
    with pytest.raises(p.ProviderError):
        w.verify_runtime_override(rows, lambda name: Path(rows[name]["path"]))


def test_r90_cannot_override_another_runtime_or_vendor() -> None:
    for name in ("NetSocket.dll", "msvcp140.dll", "msvcr100.dll"):
        rows = runtime_rows()
        rows[name] = runtime_row()
        with pytest.raises(p.ProviderError):
            w.verify_runtime_override(rows, lambda name: Path("C:/inert"))


@pytest.mark.parametrize("missing", ["vcruntime140.dll", "vcruntime140_1.dll"])
def test_r90_requires_complete_two_runtime_map(missing: str) -> None:
    rows = runtime_rows()
    del rows[missing]
    with pytest.raises(p.ProviderError):
        w.verify_runtime_override(rows, lambda name: Path("C:/inert"))


@pytest.mark.parametrize("count", [0, 1, 2])
def test_r90_safe_projection_accepts_only_bounded_development_disclosure(
    count: int,
) -> None:
    result = p.SafeResult(GEN, runtime_substitutions=count)
    assert p.parse_result(result.to_json(), GEN) == result
    for forbidden in (3, -1):
        with pytest.raises(p.ProviderError):
            p.parse_result(
                p.SafeResult(GEN, runtime_substitutions=forbidden).to_json(), GEN
            )


def test_r90_private_receipt_pin_rejects_old_or_tampered_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inert_provider_root(tmp_path, monkeypatch)
    receipt = tmp_path / "runtime-receipt.json"
    receipt.write_bytes((p.ROOT / p.RUNTIME_RECEIPT).read_bytes())
    config = p.ProviderConfig(
        Path("C:/inert"), Path("C:/inert"), tmp_path / "review.json", 1, receipt
    )
    monkeypatch.setattr(p, "check_private_acl", lambda path: None)
    assert (
        p.runtime_override(config)
        == p.read_json(p.ROOT / p.RUNTIME_RECEIPT)["allowedOverrides"]
    )
    receipt.write_bytes(
        (
            p.ROOT
            / p.SDD
            / "W04-windows-python-runtime-override-reviewed-root-receipt.json"
        ).read_bytes()
    )
    with pytest.raises(p.ProviderError):
        p.runtime_override(config)
    receipt.write_bytes((p.ROOT / p.RUNTIME_RECEIPT).read_bytes() + b" ")
    with pytest.raises(p.ProviderError):
        p.runtime_override(config)


def test_r90_valid_two_runtime_exception_still_rejects_foreign_vendor_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = runtime_rows()
    monkeypatch.setattr(w, "file_hash", lambda path: runtime_hash(rows, path))
    with pytest.raises(p.ProviderError):
        w.verify_mapped(
            Path("C:/inert-package"),
            [{"name": "NetSocket.dll", "bytes": 462848, "sha256": "0" * 64}],
            {"NetSocket.dll": (1, 2)},
            lambda name: (
                Path(rows[name]["path"]) if name in rows else Path("C:/foreign") / name
            ),
            rows,
        )


class Fix1Child(UncertainChild):
    def __init__(self) -> None:
        super().__init__()
        self.stdin = io.BytesIO()
        self.poll_error: BaseException | None = None

    def poll(self) -> int | None:
        if self.poll_error is not None:
            error, self.poll_error = self.poll_error, None
            raise error
        return super().poll()


class Fix1Writer:
    ident = 1

    def __init__(self) -> None:
        self.join_error: BaseException | None = None

    def join(self, timeout: float) -> None:
        if self.join_error is not None:
            error, self.join_error = self.join_error, None
            raise error

    def is_alive(self) -> bool:
        return False


class Fix1Output(io.BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.close_error: BaseException | None = None

    def close(self) -> None:
        if self.close_error is not None:
            error, self.close_error = self.close_error, None
            raise error
        super().close()


@pytest.mark.parametrize("phase", ["poll", "join", "stdin", "close"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_fix1_finish_interrupt_retains_same_owner_and_fences_until_passive_completion(
    phase: str,
    error_type: type[BaseException],
) -> None:
    child, writer, output = Fix1Child(), Fix1Writer(), Fix1Output()
    child.exited = True
    if phase == "poll":
        child.poll_error = error_type()
    elif phase == "join":
        writer.join_error = error_type()
    elif phase == "stdin":
        child.stdin = Fix1Output()
        child.stdin.close_error = error_type()
    else:
        output.close_error = error_type()
    outputs = (output, io.BytesIO())
    owner = p.ChildOwner(
        cast(subprocess.Popen[bytes], child),
        cast(threading.Thread, writer),
        cast(tuple[BinaryIO, BinaryIO], outputs),
    )
    p.PENDING_OWNERS.append(owner)
    try:
        outcome: bool | None = None
        try:
            outcome = owner.finish(0.001)
        except BaseException:  # noqa: BLE001 -- observe escaped interruption
            outcome = None
        assert outcome is False
        assert owner.child is cast("subprocess.Popen[bytes]", child)
        assert owner.writer is cast(threading.Thread, writer)
        assert not owner.confirmed and not output.closed and not outputs[1].closed
        with pytest.raises(p.ProviderError):
            p.WindowsSocketProvider().run(
                p.ProviderConfig(
                    Path("C:/inert"), Path("C:/inert"), Path("C:/inert/receipt")
                ),
                p.PrivateRequest("load"),
            )
        provider = p.WindowsSocketProvider()
        provider.owner = owner
        p.cli_lifetime(provider)
        assert owner.confirmed and outputs[0].closed and outputs[1].closed
        assert child.kills == 0
    finally:
        child.poll_error = None
        writer.join_error = None
        output.close_error = None
        if isinstance(child.stdin, Fix1Output):
            child.stdin.close_error = None
        owner.finish(0.001)


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, RuntimeError])
def test_fix1_writer_construction_after_spawn_retains_original_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    child = Fix1Child()
    captured: list[tuple[BinaryIO, BinaryIO]] = []

    def spawn(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        captured.append((kwargs["stdout"], kwargs["stderr"]))
        # String type avoids evaluating/subscripting the monkeypatched Popen.
        return cast("subprocess.Popen[bytes]", child)

    def broken_writer(*args: Any, **kwargs: Any) -> threading.Thread:
        raise error_type()

    monkeypatch.setattr(p, "verify_review", lambda config: [])
    monkeypatch.setattr(p, "validate_bundle", lambda *args: {})
    monkeypatch.setattr(p, "check_private_acl", lambda path: None)
    monkeypatch.setattr(p, "protect_created_acl", lambda path: None)
    monkeypatch.setattr(p.ProviderConfig, "__post_init__", lambda self: None)
    monkeypatch.setattr(p.OwnedJob, "admit", lambda self, process: None)
    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(threading, "Thread", broken_writer)
    provider = p.WindowsSocketProvider()
    try:
        result = provider.run(
            p.ProviderConfig(tmp_path, tmp_path, tmp_path / "receipt"),
            p.PrivateRequest("load"),
        )
        assert provider.owner is not None
        assert provider.owner.child is cast("subprocess.Popen[bytes]", child)
        assert provider.owner in p.PENDING_OWNERS
        assert not provider.owner.confirmed
        assert result.failure == "custody" and not result.reaped
        assert all(not output.closed for output in captured[0])
        assert child.kills == 1
        with pytest.raises(p.ProviderError):
            p.WindowsSocketProvider().run(
                p.ProviderConfig(tmp_path, tmp_path, tmp_path / "receipt"),
                p.PrivateRequest("load"),
            )
    finally:
        child.exited = True
        if provider.owner is not None:
            provider.owner.passive_wait()
        else:
            for output in captured[0]:
                output.close()
    assert provider.owner is not None and provider.owner.confirmed
    assert child.kills == 1


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_fix1_cli_outer_finally_waits_after_baseexception(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    child, writer = Fix1Child(), Fix1Writer()
    child.exited = True
    outputs = (io.BytesIO(), io.BytesIO())
    owner = p.ChildOwner(
        cast(subprocess.Popen[bytes], child),
        cast(threading.Thread, writer),
        cast(tuple[BinaryIO, BinaryIO], outputs),
    )

    class InterruptedProvider(p.WindowsSocketProvider):
        def run(
            self, config: p.ProviderConfig, request: p.PrivateRequest
        ) -> p.SafeResult:
            self.owner = owner
            raise error_type()

    class PrivateIO:
        def __init__(self, raw: bytes = b"") -> None:
            self.buffer = io.BytesIO(raw)

    private_input = PrivateIO(
        json.dumps(
            {
                "config": {
                    "bundle": "C:/inert",
                    "staging": "C:/inert",
                    "review_receipt": "C:/inert/receipt",
                    "deadline_seconds": 1,
                },
                "request": {"mode": "load"},
            }
        ).encode()
    )
    private_output = PrivateIO()
    monkeypatch.setattr(p, "WindowsSocketProvider", InterruptedProvider)
    monkeypatch.setattr(sys, "stdin", private_input)
    monkeypatch.setattr(sys, "stdout", private_output)
    try:
        exit_code: int | None = None
        try:
            exit_code = p.main()
        except BaseException:  # noqa: BLE001 -- observe escaped interruption
            exit_code = None
        assert exit_code == 1
        assert owner.confirmed and all(output.closed for output in outputs)
        assert p.json_object(private_output.buffer.getvalue())["failure"] == "invalid"
    finally:
        owner.finish(0.001)


def active_fix1_callback() -> w.CallbackOwner:
    return next(
        value for value in reversed(w.RETAINED) if isinstance(value, w.CallbackOwner)
    )


def test_fix1_callback_failure_during_final_reply_capture_wins_over_success() -> None:
    native = FakeNative(reply=reply())
    received = 0

    def capture(name: str, raw: bytes) -> None:
        nonlocal received
        if name == "reply.bin":
            received += len(raw)
            if received == len(reply()):
                owner = active_fix1_callback()
                assert invoke(owner, b"foreign", handle=999) == 0

    request = p.PrivateRequest(
        "handshake", "KR", "synthetic9", "syntheticUser", "syntheticSecret"
    )
    result = w.drive(native, request, GEN, time.monotonic() + 0.2, capture)
    assert result.failure == "callback" and not result.reply_accepted
    assert not result.key_extracted and not result.proof_verified
    assert [name for name, _ in native.calls].count("send") == 1


def test_fix1_receive_limit_retains_bounded_safe_counter_and_true_failure() -> None:
    heartbeat = struct.pack("<II", 825307441, 0)
    native = FakeNative(reply=heartbeat * 8192)
    received = 0

    def capture(name: str, raw: bytes) -> None:
        nonlocal received
        if name == "reply.bin":
            received += len(raw)
            if received == 65536:
                assert invoke(active_fix1_callback(), heartbeat) == len(heartbeat)

    request = p.PrivateRequest(
        "handshake", "KR", "synthetic9", "syntheticUser", "syntheticSecret"
    )
    result = w.drive(native, request, GEN, time.monotonic() + 0.2, capture)
    assert result.failure == "callback" and result.received_bytes == 65536
    assert not result.reply_accepted and p.parse_result(result.to_json(), GEN) == result


def test_fix1_success_seal_closes_admission_and_preserves_first_terminal_decision() -> (
    None
):
    owner = w.CallbackOwner(7, 1)
    assert owner.seal_success() is True
    assert owner.closed and not owner.failed
    assert invoke(owner, b"late", handle=999) == 0
    assert not owner.failed and owner.seal_success() is True
    failed = w.CallbackOwner(7, 2)
    assert invoke(failed, b"foreign", handle=999) == 0
    assert failed.seal_success() is False and failed.failed


def test_fix1_callback_lock_contention_precedes_seal_and_wins() -> None:
    owner = w.CallbackOwner(7, 3)
    owner.lock.acquire()
    try:
        assert invoke(owner, b"valid") == 0
    finally:
        owner.lock.release()
    assert owner.failed and owner.seal_success() is False


def test_fix1_sealed_reply_commits_with_queue_lock_and_no_native_call_holds_it() -> (
    None
):
    class LockCheckedNative(FakeNative):
        def __init__(self) -> None:
            super().__init__(reply=reply())
            self.owner: w.CallbackOwner | None = None
            self.checked = 0

        def call(self, name: str, *args: Any) -> Any:
            if name == "register":
                self.owner = active_fix1_callback()
            if self.owner is not None:
                assert not self.owner.lock.locked()
                self.checked += 1
            return super().call(name, *args)

    native = LockCheckedNative()
    result = execute(native)
    assert result.reply_accepted and result.failure == "none"
    assert native.owner is not None and native.owner.closed and not native.owner.failed
    assert native.checked == 6  # Register, Start, Send, Stop, Destroy, Quit.


def test_fix1_interrupted_start_keeps_writer_uncertainty_after_child_reap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Fix1Child()

    class PendingWriter(Fix1Writer):
        ident: Any = None

        def start(self) -> None:
            raise KeyboardInterrupt()

    writer = PendingWriter()
    monkeypatch.setattr(p, "verify_review", lambda config: [])
    monkeypatch.setattr(p, "validate_bundle", lambda *args: {})
    monkeypatch.setattr(p, "check_private_acl", lambda path: None)
    monkeypatch.setattr(p, "protect_created_acl", lambda path: None)
    monkeypatch.setattr(p.ProviderConfig, "__post_init__", lambda self: None)
    monkeypatch.setattr(p.OwnedJob, "admit", lambda self, process: None)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(threading, "Thread", lambda *args, **kwargs: writer)
    provider = p.WindowsSocketProvider()
    result = provider.run(
        p.ProviderConfig(tmp_path, tmp_path, tmp_path / "receipt"),
        p.PrivateRequest("load"),
    )
    assert result.failure == "custody" and provider.owner is not None
    owner = provider.owner
    try:
        child.exited = True
        assert owner.finish(0.001) is False
        assert not owner.confirmed and all(
            not output.closed for output in owner.outputs
        )
        with pytest.raises(p.ProviderError):
            p.WindowsSocketProvider().run(
                p.ProviderConfig(
                    Path("C:/inert"), Path("C:/inert"), Path("C:/inert/receipt")
                ),
                p.PrivateRequest("load"),
            )
    finally:
        child.exited = True
        writer.ident = 1
        owner.passive_wait()
    assert owner.confirmed and all(output.closed for output in owner.outputs)


def receive_event(
    *,
    command: int = 2563,
    sequence: int = 0,
    flags: int = 0,
    encoding: int = 0,
    body: bytes = bytes(36),
    declared: int | None = None,
) -> bytes:
    return (
        struct.pack(
            "<IIHBBIII",
            825307441,
            16 + len(body),
            6,
            flags,
            encoding,
            command,
            sequence,
            len(body) if declared is None else declared,
        )
        + body
    )


def receive_login_reply(*, rejected: int | None = None, peer_version: int = 9) -> bytes:
    raw = bytearray(reply(rejection=rejected))
    struct.pack_into("<H", raw, 8, peer_version)
    return bytes(raw)


class ReceiveNative(FakeNative):
    def call(self, name: str, *args: Any) -> Any:
        observed = super().call(name, *args)
        if name == "greeting":
            raw = bytearray(64)
            struct.pack_into("<i", raw, 12, 6)
            ct.memmove(args[1], bytes(raw), 64)
        return observed


class ReceiveHandshake(LoginHandshake):
    def __init__(self, **kwargs: Any) -> None:
        self.close_calls = 0
        self.history: list[LoginResult | None] = []
        self.stale = False
        super().__init__(**kwargs)

    def accept_reply(self, packet: Packet, *, generation: int) -> LoginResult | None:
        result = super().accept_reply(packet, generation=generation + int(self.stale))
        self.history.append(result)
        return result

    def close(self) -> None:
        self.close_calls += 1
        super().close()


class ReceiveStream(N9000Stream):
    def __init__(self, *, greeting: Greeting | None = None) -> None:
        self.close_calls = 0
        self.bound = greeting
        super().__init__(greeting=greeting)

    def close(self) -> None:
        self.close_calls += 1
        super().close()


def receive_observers(
    monkeypatch: pytest.MonkeyPatch, *, stale: bool = False
) -> tuple[list[ReceiveHandshake], list[ReceiveStream]]:
    handshakes: list[ReceiveHandshake] = []
    streams: list[ReceiveStream] = []

    def handshake(**kwargs: Any) -> ReceiveHandshake:
        instance = ReceiveHandshake(**kwargs)
        instance.stale = stale
        handshakes.append(instance)
        return instance

    def stream(*, greeting: Greeting | None = None) -> ReceiveStream:
        instance = ReceiveStream(greeting=greeting)
        streams.append(instance)
        return instance

    monkeypatch.setattr(w, "LoginHandshake", handshake)
    monkeypatch.setattr(w, "N9000Stream", stream)
    return handshakes, streams


def receive_drive(
    native: ReceiveNative, *, deadline: float | None = None, capture: Any = None
) -> p.SafeResult:
    request = p.PrivateRequest(
        "handshake", "KR", "synthetic9", "syntheticUser", "syntheticSecret"
    )
    return w.drive(
        native,
        request,
        GEN,
        time.monotonic() + 0.05 if deadline is None else deadline,
        (lambda name, raw: None) if capture is None else capture,
    )


def assert_receive_terminal(
    native: ReceiveNative,
    handshakes: list[ReceiveHandshake],
    streams: list[ReceiveStream],
) -> None:
    assert [name for name, _ in native.calls].count("send") == 1
    assert handshakes[0].close_calls >= 1 and handshakes[0].state == "terminal"
    assert streams[0].close_calls >= 1
    with pytest.raises(CodecError):
        streams[0].feed(b"")


def test_receive_adapter_event_then_reply_preserves_attempt_and_final_peer_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    heartbeat = struct.pack("<II", 825307441, 0)
    native = ReceiveNative(reply=heartbeat + receive_event() + receive_login_reply())
    result = receive_drive(native)
    assert (
        result.reply_accepted
        and result.failure == "none"
        and result.stage == "complete"
    )
    assert not result.authorized and not result.live and result.key_extracted
    assert streams[0].bound is not None and streams[0].bound.version == 6
    assert handshakes[0].history[0] is None
    accepted = handshakes[0].history[1]
    assert accepted is not None and accepted.peer_version == 9
    assert len(handshakes) == 1 and len(streams) == 1
    assert_receive_terminal(native, handshakes, streams)


def test_receive_adapter_notification_alone_never_seals_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    native = ReceiveNative(reply=receive_event())
    result = receive_drive(native)
    assert (
        result.failure == "deadline"
        and not result.reply_accepted
        and result.stage == "handshake"
    )
    assert not result.key_extracted and not result.proof_verified
    assert handshakes[0].history == [None]
    assert active_fix1_callback().closed
    assert_receive_terminal(native, handshakes, streams)


def test_receive_adapter_repeated_events_keep_original_deadline_and_one_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    ticks = 0

    def clock() -> float:
        nonlocal ticks
        ticks += 1
        return float(ticks)

    monkeypatch.setattr(time, "monotonic", clock)
    native = ReceiveNative(reply=receive_event())
    captured = 0

    def capture(name: str, raw: bytes) -> None:
        nonlocal captured
        if name == "reply.bin":
            captured += len(raw)
            if captured % 60 == 0:
                assert invoke(active_fix1_callback(), receive_event()) == 60

    result = receive_drive(native, deadline=10.0, capture=capture)
    assert result.failure == "deadline" and not result.reply_accepted
    assert ticks == 10 and len(handshakes[0].history) > 1
    assert all(entry is None for entry in handshakes[0].history)
    assert_receive_terminal(native, handshakes, streams)


@pytest.mark.parametrize(
    "event,expected",
    [
        (receive_event(command=2564), "unsupported"),
        (receive_event(command=0x10000A03), "unsupported"),
        (receive_event(sequence=1), "unsupported"),
        (receive_event(flags=1), "unsupported"),
        (receive_event(encoding=1), "unsupported"),
        (receive_event(body=bytes(35)), "unsupported"),
        (receive_event(body=bytes(35), declared=36), "codec"),
    ],
)
def test_receive_adapter_bad_event_fails_and_closes_both(
    monkeypatch: pytest.MonkeyPatch,
    event: bytes,
    expected: str,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    native = ReceiveNative(reply=event + receive_login_reply())
    result = receive_drive(native)
    assert result.failure == expected and not result.reply_accepted
    assert_receive_terminal(native, handshakes, streams)


def test_receive_adapter_stale_generation_event_fails_before_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes, streams = receive_observers(monkeypatch, stale=True)
    native = ReceiveNative(reply=receive_event())
    result = receive_drive(native)
    assert result.failure == "codec" and not result.reply_accepted
    assert handshakes[0].history == []
    assert_receive_terminal(native, handshakes, streams)


def test_receive_adapter_rejection_after_event_stays_typed_without_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    native = ReceiveNative(reply=receive_event() + receive_login_reply(rejected=17))
    result = receive_drive(native)
    assert (
        result.failure == "rejected"
        and result.native_error == 17
        and not result.reply_accepted
    )
    assert handshakes[0].history == [None]
    assert_receive_terminal(native, handshakes, streams)


def test_receive_adapter_event_stream_keeps_cumulative_byte_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    wire = receive_event() * 1092
    native = ReceiveNative(reply=wire)
    captured = 0

    def capture(name: str, raw: bytes) -> None:
        nonlocal captured
        if name == "reply.bin":
            captured += len(raw)
            if captured == len(wire):
                assert invoke(active_fix1_callback(), receive_event()) == 60

    result = receive_drive(native, deadline=time.monotonic() + 1, capture=capture)
    assert result.failure == "callback" and not result.reply_accepted
    assert result.received_bytes == len(wire) <= 65536
    assert p.parse_result(result.to_json(), GEN) == result
    assert_receive_terminal(native, handshakes, streams)


def test_receive_adapter_failure_during_event_plus_reply_capture_prevents_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    wire = receive_event() + receive_login_reply()
    native = ReceiveNative(reply=wire)
    captured = 0

    def capture(name: str, raw: bytes) -> None:
        nonlocal captured
        if name == "reply.bin":
            captured += len(raw)
            if captured == len(wire):
                assert invoke(active_fix1_callback(), b"foreign", handle=999) == 0

    result = receive_drive(native, capture=capture)
    assert result.failure == "callback" and not result.reply_accepted
    assert not result.proof_verified and not result.key_extracted
    assert_receive_terminal(native, handshakes, streams)


def test_receive_adapter_source_gate_pins_exact_approved_receive_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = p.SDD + "W04-local-n9000-login-field-reviewed-root-receipt.json"
    digest = "03f6adbac6499d8a48bc9342c5a29dadc3ec0fd871eb042559f27c1ffb2d971e"
    assert p.CODEC_RECEIPT == expected and p.ACCEPTED_HASHES[p.CODEC_RECEIPT] == digest
    fixture = inert_provider_root(tmp_path, monkeypatch)
    assert p.file_hash(p.ROOT / expected)["sha256"] == fixture["pins"][expected]
    original = p.file_hash

    def old_receipt_hash(path: Path) -> dict[str, str | int]:
        if path == p.ROOT / expected:
            return {
                "bytes": 1,
                "sha256": "97bbfc551988e4740927da07ba798c8900516be4550d19d4ed5a1e7dc6f34e6c",
            }
        return original(path)

    review = tmp_path / "author.json"
    review.write_text('{"status":"INERT_AUTHOR_FIXTURE"}')
    monkeypatch.setattr(p, "file_hash", old_receipt_hash)
    with pytest.raises(p.ProviderError):
        p.verify_review(p.ProviderConfig(Path("C:/inert"), Path("C:/inert"), review))


def startup_chain() -> bytes:
    return b"".join(
        receive_event(command=command, body=bytes(size))
        for command, size in ((2561, 92), (2562, 40), (2563, 36))
    )


def test_startup_adapter_chain_then_reply_same_generation_one_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    native = ReceiveNative(
        reply=struct.pack("<II", 825307441, 0) + startup_chain() + receive_login_reply()
    )
    result = receive_drive(native)
    assert result.failure == "none" and result.reply_accepted
    assert handshakes[0].history[:3] == [None, None, None]
    assert len(handshakes[0].history) == 4 and not result.authorized and not result.live
    assert_receive_terminal(native, handshakes, streams)


@pytest.mark.parametrize("command,size", [(2561, 92), (2562, 40), (2563, 36)])
def test_startup_adapter_wrong_shape_never_skips_to_reply(
    monkeypatch: pytest.MonkeyPatch,
    command: int,
    size: int,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    native = ReceiveNative(
        reply=receive_event(command=command, body=bytes(size + 1))
        + receive_login_reply()
    )
    result = receive_drive(native)
    assert result.failure == "unsupported" and not result.reply_accepted
    assert_receive_terminal(native, handshakes, streams)


def test_startup_adapter_chain_only_stays_pending_to_original_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes, streams = receive_observers(monkeypatch)
    ticks = 0

    def clock() -> float:
        nonlocal ticks
        ticks += 1
        return float(ticks)

    monkeypatch.setattr(time, "monotonic", clock)
    native = ReceiveNative(reply=startup_chain() * 2)
    result = receive_drive(native, deadline=10)
    assert result.failure == "deadline" and not result.reply_accepted and ticks == 10
    assert handshakes[0].history == [None] * 6
    assert_receive_terminal(native, handshakes, streams)


@pytest.mark.parametrize("file_index", [0, 1, 2])
def test_startup_adapter_inert_source_gate_validates_all_three_codec_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_index: int,
) -> None:
    expected = p.SDD + "W04-local-n9000-login-field-reviewed-root-receipt.json"
    assert p.CODEC_RECEIPT == expected
    assert (
        p.ACCEPTED_HASHES[p.CODEC_RECEIPT]
        == "03f6adbac6499d8a48bc9342c5a29dadc3ec0fd871eb042559f27c1ffb2d971e"
    )
    fixture = inert_provider_root(tmp_path, monkeypatch)
    config = p.ProviderConfig(fixture["root"], fixture["root"], fixture["review"])
    assert p.verify_review(config) == fixture["manifest"]
    relative = list(fixture["codecFiles"])[file_index]
    (fixture["root"] / relative).write_bytes(b"INERT CHANGED CODEC INPUT")
    with pytest.raises(p.ProviderError):
        p.verify_review(config)


@pytest.mark.parametrize(
    "bad,sends,failure",
    [
        ("serial", 2, "codec"),
        ("login_rejected", 1, "rejected"),
        ("trailing", 5, "unsupported"),
        ("rejected", 3, "rejected"),
        ("error", 3, "runtime"),
    ],
)
def test_inventory_identity_login_reject_or_trailing_frame_never_completes(
    bad: str,
    sends: int,
    failure: str,
) -> None:
    native = InventoryNative(bad=bad)
    result = inventory_drive(native)
    assert result.failure == failure and not result.inventory_complete
    assert len(native.wires) == sends and not result.authorized
    assert result.reply_accepted == (bad != "login_rejected")


@pytest.mark.parametrize("failure", ["callback", "deadline"])
def test_inventory_final_publication_guard_after_four_real_replies(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    original = inventory_codec.InventorySession.accept_reply
    observed: list[inventory_codec.InventoryEvidence] = []

    def accept(
        self: inventory_codec.InventorySession, wire: bytes, *, generation: int
    ) -> inventory_codec.InventoryEvidence:
        evidence = original(self, wire, generation=generation)
        observed.append(evidence)
        if len(observed) == 4:
            if failure == "callback":
                active_fix1_callback().mark_failed()
            else:
                monkeypatch.setattr(time, "monotonic", lambda: 1e30)
        return evidence

    monkeypatch.setattr(inventory_codec.InventorySession, "accept_reply", accept)
    native = InventoryNative()
    result = inventory_drive(native)
    assert len(observed) == 4 and result.inventory_replies == 4
    assert result.failure != "none" and not result.inventory_complete
    assert not result.serial_matched and not result.permissions_complete
    assert p.parse_result(result.to_json(), GEN) == result


def test_inventory_original_deadline_applies_before_initial_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = InventoryNative()

    def capture(name: str, raw: bytes) -> None:
        monkeypatch.setattr(time, "monotonic", lambda: 1e30)

    result = w.drive(native, inventory_request(), GEN, time.monotonic() + 1, capture)
    assert result.failure == "deadline" and native.wires == []


def test_inventory_transport_cap_and_frame_bounds_are_finite() -> None:
    stream = w.OrdinaryFrames()
    stream.feed(struct.pack("<II", 825307441, 0) * 8192)
    assert stream.take() is None
    stream.feed(bytes(65536))
    with pytest.raises(CodecError):
        stream.feed(b"x")
    stream.close()
    for length in (1, 15, 65529):
        stream = w.OrdinaryFrames()
        stream.feed(struct.pack("<II", 825307441, length))
        with pytest.raises(CodecError):
            stream.take()


@pytest.mark.parametrize("file_index", [0, 1, 2])
def test_inventory_source_gate_checks_all_accepted_inventory_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_index: int,
) -> None:
    assert (
        p.ACCEPTED_HASHES[p.INVENTORY_RECEIPT]
        == "2b8b158ef441ec374dc237c21157562c4fe02ce8fdcd76dadfe78cf8df686e9e"
    )
    fixture = inert_provider_root(tmp_path, monkeypatch)
    config = p.ProviderConfig(fixture["root"], fixture["root"], fixture["review"])
    assert p.verify_review(config) == fixture["manifest"]
    (fixture["root"] / list(fixture["inventoryFiles"])[file_index]).write_bytes(
        b"INERT CHANGED INVENTORY"
    )
    with pytest.raises(p.ProviderError):
        p.verify_review(config)


def test_inventory_absent_optin_is_denied() -> None:
    with pytest.raises(p.ProviderError):
        p.PrivateRequest("inventory", "KR", "synthetic9", "user", "secret")


@pytest.mark.parametrize(
    "bad,failure", [("overflow", "callback"), ("interrupt", "runtime")]
)
def test_inventory_total_budget_and_baseexception_cleanup(
    bad: str, failure: str
) -> None:
    native = InventoryNative(bad=bad)
    result = inventory_drive(native)
    assert result.failure == failure and result.reply_accepted
    assert 0 < result.received_bytes <= 65536 and not result.inventory_complete
    assert len(native.wires) == 3
    assert [name for name, _ in native.delegate.calls][-3:] == [
        "stop",
        "destroy",
        "quit",
    ]
    assert (
        active_fix1_callback().closed
        and p.parse_result(result.to_json(), GEN) == result
    )


@pytest.mark.parametrize("change", ["home", "duplicate", "system"])
def test_inventory_direct_interpreter_rejects_untrusted_cfg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    venv = tmp_path / ".venv"
    venv.mkdir()
    cfg = "home = " + sys.base_prefix + "\ninclude-system-site-packages = false\n"
    if change == "home":
        cfg = cfg.replace(sys.base_prefix, "C:/untrusted-interpreter")
    elif change == "duplicate":
        cfg += "home = " + sys.base_prefix + "\n"
    else:
        cfg = cfg.replace("false", "true")
    (venv / "pyvenv.cfg").write_text(cfg, encoding="utf-8")
    monkeypatch.setattr(p, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "prefix", str(venv))
    with pytest.raises(p.ProviderError):
        p.direct_interpreter()


@pytest.mark.parametrize(
    "changes",
    [
        {"stage": "load"},
        {"stage": "handshake"},
        {"key_extracted": False},
        {"loaded": False},
        {"initialized": False},
        {"greeting_bytes": 0},
        {"send_count": 0},
        {
            "inventory_complete": False,
            "serial_matched": False,
            "channels_complete": False,
            "permissions_complete": False,
            "user_observed": False,
            "channel_count": 0,
            "inventory_availability": "unavailable",
        },
    ],
)
def test_inventory_parent_rejects_inconsistent_phase_flags(
    changes: dict[str, Any],
) -> None:
    result = inventory_drive(InventoryNative())
    data = {**json.loads(result.to_json()), **changes}
    with pytest.raises(p.ProviderError):
        p.parse_result(json.dumps(data).encode(), GEN)


def test_inventory_unsupported_tail_retains_login_but_sends_no_metadata() -> None:
    native = InventoryNative(bad="tail")
    result = inventory_drive(native)
    assert result.failure == "unsupported" and result.reply_accepted
    assert (
        len(native.wires) == 1
        and result.inventory_queries_sent == result.inventory_replies == 0
    )
    assert not result.inventory_complete and not result.channels_complete
    assert p.parse_result(result.to_json(), GEN) == result


@pytest.mark.parametrize("after_assignment", [False, True])
def test_inventory_job_admission_interruption_never_releases_worker_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_assignment: bool,
) -> None:
    direct = str(p.direct_interpreter()[0])
    admit = p.OwnedJob.admit

    def interrupted(self: p.OwnedJob, child: subprocess.Popen[bytes]) -> None:
        if after_assignment:
            admit(self, child)
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        p,
        "worker_command",
        lambda: [
            direct,
            "-I",
            "-S",
            "-c",
            "import sys; data=sys.stdin.buffer.read(); print('RELEASED' if data else '')",
        ],
    )
    monkeypatch.setattr(p.OwnedJob, "admit", interrupted)
    monkeypatch.setattr(p, "verify_review", lambda config: [])
    monkeypatch.setattr(p, "validate_bundle", lambda *args: {})
    monkeypatch.setattr(p, "check_private_acl", lambda path: None)
    monkeypatch.setattr(p, "protect_created_acl", lambda path: None)
    monkeypatch.setattr(p.ProviderConfig, "__post_init__", lambda self: None)
    provider = p.WindowsSocketProvider()
    result = provider.run(
        p.ProviderConfig(tmp_path, tmp_path, tmp_path / "review", 1),
        p.PrivateRequest("load"),
    )
    assert result.failure == "custody" and result.reaped
    assert provider.owner is not None and provider.owner.writer is None
    assert provider.owner.child is not None and provider.owner.child.poll() is not None
    assert provider.owner.job is not None and provider.owner.job.closed
    assert all(output.closed for output in provider.owner.outputs)
    assert (tmp_path / result.generation / "native.stdout").read_bytes() == b""


@pytest.mark.parametrize("revocation", ["deadline", "callback", "context"])
@pytest.mark.parametrize("allocation", ["query", "sentinel"])
def test_inventory_fix1_final_send_guard_after_buffer_preparation(
    monkeypatch: pytest.MonkeyPatch,
    revocation: str,
    allocation: str,
) -> None:
    """A final-guard removal must send once after revocation and fail this test."""
    allocate = ct.create_string_buffer
    prepared = False
    injected = False

    def prepare(value: int | bytes, size: int | None = None) -> Any:
        nonlocal prepared, injected
        buffer = allocate(value) if size is None else allocate(value, size)
        is_query = (
            isinstance(value, bytes)
            and len(value) >= 24
            and struct.unpack_from("<I", value, 12)[0] == 2331
        )
        prepared = prepared or is_query
        selected = is_query if allocation == "query" else prepared and value == 1
        if selected and not injected:
            injected = True
            owner = active_fix1_callback()
            if revocation == "deadline":
                monkeypatch.setattr(time, "monotonic", lambda: 1e30)
            elif revocation == "callback":
                owner.mark_failed()
            else:
                owner.context.value += 1
        return buffer

    monkeypatch.setattr(ct, "create_string_buffer", prepare)
    native = InventoryNative()
    result = inventory_drive(native)
    assert prepared and injected
    assert result.inventory_queries_sent == 0 and len(native.wires) == 1
    assert result.reply_accepted and result.inventory_replies == 0
    assert result.failure != "none" and not result.inventory_complete
    assert not result.authorized and not result.live
    assert active_fix1_callback().closed
    assert p.parse_result(result.to_json(), GEN) == result


def test_inventory_fix1_rebind_rejects_previous_receipt_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        p.INVENTORY_RECEIPT
        == p.SDD + "W04-local-inventory-xml-Fix3-Fix1-reviewed-root-receipt.json"
    )
    assert (
        p.ACCEPTED_HASHES[p.INVENTORY_RECEIPT]
        == "2b8b158ef441ec374dc237c21157562c4fe02ce8fdcd76dadfe78cf8df686e9e"
    )
    fixture = inert_provider_root(tmp_path, monkeypatch)
    config = p.ProviderConfig(fixture["root"], fixture["root"], fixture["review"])
    assert p.verify_review(config) == fixture["manifest"]
    actual = p.file_hash

    def previous_digest(path: Path) -> dict[str, str | int]:
        if path == p.ROOT / p.INVENTORY_RECEIPT:
            return {
                "bytes": 1,
                "sha256": "dcdad2181cd36004679fc5a012cce2910532b8bdc71c9f4f7cd5ceb3fd8b5ec9",
            }
        return actual(path)

    monkeypatch.setattr(p, "file_hash", previous_digest)
    with pytest.raises(p.ProviderError):
        p.verify_review(config)


class Fix2NotificationNative(InventoryNative):
    def __init__(
        self,
        notifications: bytes | None = None,
        *,
        layout: str = "combined",
        replies: bool = True,
        foreign: bool = False,
    ) -> None:
        super().__init__()
        self.notifications = startup_chain() if notifications is None else notifications
        self.layout, self.replies, self.foreign = layout, replies, foreign

    def call(self, name: str, *args: Any) -> Any:
        if name != "send":
            return super().call(name, *args)
        assert not active_fix1_callback().lock.locked()
        wire = ct.string_at(args[1], args[2])
        self.wires.append(wire)
        index = len(self.wires) - 1
        if index == 0:
            response = inventory_login_reply()
            if self.layout == "handoff":
                response += self.notifications + metadata_reply(0)
        elif index == 1 and self.layout == "handoff":
            response = b""
        else:
            response = self.notifications
            if self.replies:
                response += metadata_reply(index - 1)
        if index and self.foreign:
            assert invoke(active_fix1_callback(), response, handle=999) == 0
        else:
            width = 7 if self.layout == "split" else max(1, len(response))
            for offset in range(0, len(response), width):
                assert invoke(
                    active_fix1_callback(), response[offset : offset + width]
                ) == len(response[offset : offset + width])
        return len(wire)


@pytest.mark.parametrize("layout", ["combined", "split", "handoff"])
def test_inventory_fix2_exact_events_keep_pending_query_and_complete_chain(
    monkeypatch: pytest.MonkeyPatch,
    layout: str,
) -> None:
    handshakes, _ = receive_observers(monkeypatch)
    sessions: list[inventory_codec.InventorySession] = []
    metadata_calls: list[bytes] = []
    notifications: list[int] = []
    construct, accept = (
        inventory_codec.InventorySession,
        inventory_codec.InventorySession.accept_reply,
    )
    feed = N9000Stream.feed

    def session(**kwargs: Any) -> inventory_codec.InventorySession:
        result = construct(**kwargs)
        sessions.append(result)
        return result

    def metadata(
        self: inventory_codec.InventorySession, wire: bytes, *, generation: int
    ) -> inventory_codec.InventoryEvidence:
        metadata_calls.append(wire)
        return accept(self, wire, generation=generation)

    def decode(self: N9000Stream, wire: bytes | bytearray) -> tuple[Packet, ...]:
        command = struct.unpack_from("<I", wire, 12)[0]
        if command in (2561, 2562, 2563):
            assert sessions and sessions[0].state == "awaiting_reply"
            before = sessions[0].inventory
            packets = feed(self, wire)
            assert (
                sessions[0].inventory is before
                and sessions[0].state == "awaiting_reply"
            )
            notifications.append(command)
            return packets
        return feed(self, wire)

    monkeypatch.setattr(w, "InventorySession", session)
    monkeypatch.setattr(inventory_codec.InventorySession, "accept_reply", metadata)
    monkeypatch.setattr(N9000Stream, "feed", decode)
    native = Fix2NotificationNative(layout=layout)
    result = inventory_drive(native)
    assert result.failure == "none" and result.inventory_complete
    assert notifications == [2561, 2562, 2563] * 4
    assert len(handshakes[0].history) == 1 and handshakes[0].history[0] is not None
    assert len(metadata_calls) == 4 and len(native.wires) == 5
    assert [struct.unpack_from("<I", raw, 16)[0] for raw in metadata_calls] == [
        2,
        3,
        4,
        5,
    ]
    assert result.inventory_queries_sent == result.inventory_replies == 4
    assert result.channel_count == 1 and result.serial_matched
    assert not result.authorized and not result.live and not result.production_ready
    assert p.parse_result(result.to_json(), GEN) == result


@pytest.mark.parametrize("command,size", [(2561, 92), (2562, 40), (2563, 36)])
@pytest.mark.parametrize(
    "change", ["length", "declared", "sequence", "flags", "encoding", "reply", "error"]
)
def test_inventory_fix2_malformed_notification_never_reaches_metadata(
    command: int,
    size: int,
    change: str,
) -> None:
    values: dict[str, Any] = {"command": command, "body": bytes(size)}
    if change == "length":
        values["body"] = bytes(size + 1)
    elif change == "declared":
        values["declared"] = size + 1
    elif change in ("sequence", "flags", "encoding"):
        values[change] = 1
    else:
        values["command"] |= 0x10000000 if change == "reply" else 0x20000000
    native = Fix2NotificationNative(receive_event(**values))
    result = inventory_drive(native)
    assert result.failure == "unsupported" and result.reply_accepted
    assert result.inventory_queries_sent == 1 and result.inventory_replies == 0
    assert len(native.wires) == 2 and not result.inventory_complete
    assert not result.serial_matched and not result.permissions_complete


@pytest.mark.parametrize(
    "command",
    [
        257,
        261,
        1281,
        1282,
        1285,
        1286,
        1793,
        1794,
        2049,
        2051,
        2055,
        2057,
        2058,
        2066,
        2067,
        2068,
        2070,
        2071,
        2819,
        2820,
        65537,
        131073,
        131074,
        131075,
        196609,
        196610,
        2560,
        2564,
        2565,
    ],
)
def test_inventory_fix2_other_dispatch_families_never_default_skip(
    command: int,
) -> None:
    native = Fix2NotificationNative(receive_event(command=command))
    result = inventory_drive(native)
    assert result.failure == "unsupported" and result.inventory_replies == 0
    assert len(native.wires) == 2 and not result.inventory_complete


@pytest.mark.parametrize("revocation", ["context", "callback", "deadline"])
@pytest.mark.parametrize("when", ["capture", "parse"])
def test_inventory_fix2_notification_current_guard_prevents_later_xml(
    monkeypatch: pytest.MonkeyPatch,
    revocation: str,
    when: str,
) -> None:
    native = Fix2NotificationNative(replies=False)
    feed = N9000Stream.feed
    injected = False

    def revoke() -> None:
        nonlocal injected
        injected = True
        if revocation == "context":
            active_fix1_callback().context.value += 1
        elif revocation == "callback":
            active_fix1_callback().mark_failed()
        else:
            monkeypatch.setattr(time, "monotonic", lambda: 1e30)

    def capture(name: str, raw: bytes) -> None:
        if when == "capture" and name == "reply.bin" and len(native.wires) == 2:
            revoke()

    def decode(self: N9000Stream, raw: bytes | bytearray) -> tuple[Packet, ...]:
        packets = feed(self, raw)
        if when == "parse" and struct.unpack_from("<I", raw, 12)[0] == 2561:
            revoke()
        return packets

    monkeypatch.setattr(N9000Stream, "feed", decode)
    result = w.drive(native, inventory_request(), GEN, time.monotonic() + 0.1, capture)
    assert injected and result.failure in ("codec", "callback", "deadline")
    assert result.inventory_queries_sent == 1 and result.inventory_replies == 0
    assert len(native.wires) == 2 and not result.inventory_complete
    if when == "parse":
        assert (
            result.failure == "codec"
        )  # immediate post-validation guard, no wait/reset


def test_inventory_fix2_foreign_callback_generation_cannot_supply_event() -> None:
    native = Fix2NotificationNative(foreign=True)
    result = inventory_drive(native)
    assert result.failure == "callback" and result.inventory_replies == 0
    assert len(native.wires) == 2 and not result.inventory_complete


def test_inventory_fix2_events_alone_keep_original_deadline_no_resend() -> None:
    native = Fix2NotificationNative(replies=False)
    result = w.drive(
        native,
        inventory_request(),
        GEN,
        time.monotonic() + 0.03,
        lambda name, raw: None,
    )
    assert result.failure == "deadline" and result.reply_accepted
    assert result.received_bytes == len(inventory_login_reply()) + len(startup_chain())
    assert result.inventory_queries_sent == 1 and result.inventory_replies == 0
    assert len(native.wires) == 2 and not result.authorized


def test_inventory_fix2_event_skips_preserve_total_receive_ceiling() -> None:
    heartbeat = struct.pack("<II", 825307441, 0)
    events = receive_event(command=2561, body=bytes(92)) * 563 + heartbeat * 3
    assert len(events) + len(inventory_login_reply()) == 65536
    native = Fix2NotificationNative(events, replies=False)

    def capture(name: str, raw: bytes) -> None:
        if name == "reply.bin" and raw == events:
            assert invoke(active_fix1_callback(), heartbeat) == 8

    result = w.drive(native, inventory_request(), GEN, time.monotonic() + 1, capture)
    assert result.failure == "callback" and result.received_bytes == 65536
    assert result.inventory_queries_sent == 1 and result.inventory_replies == 0
    assert len(native.wires) == 2 and not result.inventory_complete
    assert p.parse_result(result.to_json(), GEN) == result


def test_inventory_xml_rebind_source_shaped_all_four_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence: list[inventory_codec.InventoryEvidence] = []
    original = inventory_codec.InventorySession.accept_reply

    def accepted(
        self: inventory_codec.InventorySession, wire: bytes, *, generation: int
    ) -> inventory_codec.InventoryEvidence:
        result = original(self, wire, generation=generation)
        evidence.append(result)
        return result

    monkeypatch.setattr(inventory_codec.InventorySession, "accept_reply", accepted)
    native = InventoryNative()
    result = inventory_drive(native)
    assert result.failure == "none" and result.inventory_complete
    assert len(evidence) == 4 and len(native.wires) == 5
    assert evidence[-1].channels[0].name == "Private Camera & side"
    assert evidence[-1].permission_system == (("previewAndSnap", False),)
    for index in range(4):
        body = metadata_reply(index)[24:]
        assert body.find(b"<?xml") == 116 and b"<types>" in body
        assert b"cmdUrl=" in body and b"supplierAttr=" in body
    assert result.inventory_queries_sent == result.inventory_replies == 4
    assert result.channel_count == 1 and not result.authorized and not result.live
    assert p.parse_result(result.to_json(), GEN) == result


def test_inventory_xml_rebind_no_tail_details_cannot_enable_permissions() -> None:
    native = InventoryNative(bad="no_tail")
    result = inventory_drive(native)
    assert result.reply_accepted and result.failure == "unsupported"
    assert result.inventory_queries_sent == result.inventory_replies == 3
    assert len(native.wires) == 4 and not result.inventory_complete
    assert not result.channels_complete and not result.permissions_complete
    assert not result.authorized and not result.live
    assert p.parse_result(result.to_json(), GEN) == result


def live_request() -> p.PrivateRequest:
    return p.PrivateRequest(
        "live",
        "KR",
        "synthetic9",
        "syntheticUser",
        "syntheticSecret",
        metadata_read_opt_in=True,
        live_read_opt_in=True,
        store_ref="INERT_STORE",
        channel_position=1,
    )


def live_packet(command: int, body: bytes, sequence: int = 6) -> bytes:
    return (
        struct.pack(
            "<IiHBBIII",
            825307441,
            len(body) + 16,
            6,
            2,
            1,
            command,
            sequence,
            max(0, len(body) - 72),
        )
        + body
    )


def live_media(channel: bytes, index: int, *, key: bool, wrong: bool = False) -> bytes:
    payload = b"\0\0\0\1\x65inert"
    extension = struct.pack("<BBH4shhIB", 0, 0, 0, b"H264", 640, 480, 0, 0)
    body = struct.pack(
        "<BBBBiQQ",
        0,
        17,
        0,
        0,
        len(payload),
        116444736000000000 + index * 10000,
        116444736000010000 + index * 10000,
    )
    body += extension + payload + bytes((-len(payload)) % 4)
    return (
        struct.pack("<4sHBB", b"RAW!", 6, 1, int(key))
        + (b"X" * 16 if wrong else channel)
        + struct.pack("<iQii", len(body), 116444736000020000 + index * 10000, index, 0)
        + body
    )


class LiveNative(InventoryNative):
    def __init__(
        self,
        *,
        group: str = "empty",
        pre_key: int = 0,
        frames: int = 4,
        wrong: str = "",
        fragmented: bool = False,
    ) -> None:
        super().__init__()
        self.group, self.pre_key, self.frames = group, pre_key, frames
        self.wrong, self.fragmented = wrong, fragmented
        self.commands: list[int] = []
        self.open_wire = b""

    def call(self, name: str, *args: Any) -> Any:
        if name != "send":
            return super().call(name, *args)
        assert not active_fix1_callback().lock.locked()
        wire = ct.string_at(args[1], args[2])
        self.wires.append(wire)
        command = struct.unpack_from("<I", wire, 12)[0]
        self.commands.append(command)
        if command == 257:
            raw = bytearray(inventory_login_reply(with_tail=self.wrong != "no_tail"))
            raw[24:40], raw[108:124] = b"D" * 16, b"S" * 16
            response = bytes(raw)
        elif command == 2331:
            sequence = struct.unpack_from("<I", wire, 16)[0]
            response = metadata_reply(sequence - 2)
            body = response[24:]
            if sequence == 4:
                fields = {
                    "missing": b"",
                    "empty": b"<authGroupId/>",
                    "space": b"<authGroupId> </authGroupId>",
                    "comment": b"<authGroupId><!--empty--></authGroupId>",
                    "cdata": b"<authGroupId><![CDATA[]]></authGroupId>",
                    "value": b"<authGroupId>PRIVATE_GROUP</authGroupId>",
                }
                body = body.replace(
                    b"<authGroupId>PRIVATE_GROUP</authGroupId>", fields[self.group]
                )
            if sequence == 5 and self.wrong == "permission":
                body = body.replace(b"@lp", b"")
            header = bytearray(response[:24])
            struct.pack_into("<I", header, 4, len(body) + 16)
            struct.pack_into("<I", header, 20, len(body))
            response = bytes(header) + body
        elif command == 1281:
            self.open_wire = wire
            sequence = struct.unpack_from("<I", wire, 16)[0]
            routing = bytearray(wire[24:96])
            if self.wrong == "task":
                routing[52:68] = b"T" * 16
            response = live_packet(0x10000501, b"", sequence) + startup_chain()
            for index in range(1, self.pre_key + self.frames + 1):
                frame = live_packet(
                    65537,
                    bytes(routing)
                    + live_media(
                        wire[56:72],
                        index,
                        key=index == self.pre_key + 1,
                        wrong=self.wrong == "channel",
                    ),
                )
                if self.fragmented and index == 1:
                    inner = frame[8:]
                    split = len(inner) // 2
                    pieces = (inner[:split], inner[split:])
                    frame = b"".join(
                        struct.pack(
                            "<Ii6i", 77, -1, 9, 2, len(inner), i + 1, len(part), 4
                        )
                        + part
                        for i, part in enumerate(pieces)
                    )
                response += frame
        elif command == 1282:
            return len(wire)
        else:
            raise AssertionError("Unexpected diagnostic command")
        if response:
            assert invoke(active_fix1_callback(), response) == len(response)
        return len(wire)


def drive_live_inert(native: LiveNative) -> tuple[p.SafeResult, dict[str, bytes]]:
    captures: dict[str, bytes] = {}

    def capture(name: str, raw: bytes) -> None:
        captures[name] = captures.get(name, b"") + raw

    result = w.drive(
        native,
        live_request(),
        GEN,
        time.monotonic() + 0.5,
        capture,
        source_provenance={
            "source_review": {"bytes": 1, "sha256": "0" * 64},
            "receipts": {},
            "files": {},
        },
    )
    return result, captures


@pytest.mark.parametrize("group", ["missing", "empty"])
def test_live_integration_three_read_no_group_metadata_branch(group: str) -> None:
    native = LiveNative(group=group)
    result = w.drive(
        native, inventory_request(), GEN, time.monotonic() + 0.2, lambda name, raw: None
    )
    assert result.failure == "none" and result.metadata_branch_complete
    assert result.inventory_replies == result.inventory_queries_sent == 3
    assert result.permissions_availability == "not_requested_no_group"
    assert not result.permissions_complete and not result.inventory_complete
    assert result.serial_matched and result.channels_complete and result.user_observed
    assert native.commands == [257, 2331, 2331, 2331]
    assert p.parse_result(result.to_json(), GEN) == result


@pytest.mark.parametrize("group", ["space", "comment", "cdata"])
def test_live_integration_group_text_not_empty_provenance(group: str) -> None:
    native = LiveNative(group=group)
    result = w.drive(
        native, inventory_request(), GEN, time.monotonic() + 0.2, lambda name, raw: None
    )
    assert result.failure == "unsupported" and not result.metadata_branch_complete
    assert native.commands == [257, 2331, 2331, 2331]


@pytest.mark.parametrize("group", ["empty", "value"])
@pytest.mark.parametrize("fragmented", [False, True])
def test_live_integration_same_owner_key_capture_four_then_one_close(
    group: str, fragmented: bool
) -> None:
    native = LiveNative(group=group, pre_key=2, fragmented=fragmented)
    result, captures = drive_live_inert(native)
    assert result.failure == "none" and result.capture_status == "complete"
    assert result.live_frames == 4 and result.pre_key_frames == 2
    assert result.live_frames_validated == 6 and result.live_open_ack
    assert result.live_open_attempts == result.live_close_attempts == 1
    assert native.commands == [257] + [2331] * (3 if group == "empty" else 4) + [
        1281,
        1282,
    ]
    assert struct.unpack_from("<I", native.open_wire, 164)[0] == 1  # stream1 only
    manifest = json.loads(captures["live-capture.json"])
    assert manifest["schema"] == 1 and manifest["capture_starts_at_key"]
    assert manifest["binding"]["store_ref"] == "INERT_STORE"
    assert manifest["binding"]["generation"] == GEN
    assert manifest["binding"]["session_guid_le"] == (b"S" * 16).hex()
    assert len(manifest["frames"]) == 4
    first = json.loads(captures["live-000.json"])
    assert first["frame_index"] == 3 and first["key_frame"]
    assert first["device_timestamp"]["ticks"] == 116444736000030000
    assert (
        first["payload_sha256"] == hashlib.sha256(captures["live-000.bin"]).hexdigest()
    )
    assert first["capture_admission"]["current"] and first["encrypted"] is False
    assert not result.authorized and not result.live and not result.production_ready
    assert p.parse_result(result.to_json(), GEN) == result


@pytest.mark.parametrize("wrong", ["task", "channel", "permission", "no_tail"])
def test_live_integration_identity_permission_and_roster_fences(wrong: str) -> None:
    result, captures = drive_live_inert(LiveNative(group="value", wrong=wrong))
    assert result.failure != "none" and result.live_frames == 0
    assert "live-000.bin" not in captures and not result.authorized


@pytest.mark.parametrize("optin", [False, None, 1, "true"])
def test_live_integration_requires_separate_exact_optin(optin: Any) -> None:
    with pytest.raises(p.ProviderError):
        p.PrivateRequest(
            "live",
            "KR",
            "synthetic9",
            "user",
            "secret",
            metadata_read_opt_in=True,
            live_read_opt_in=optin,
            store_ref="INERT",
            channel_position=1,
        )


@pytest.mark.parametrize("command", [1281, 1282])
@pytest.mark.parametrize("revocation", ["deadline", "callback", "context", "store"])
def test_live_integration_final_send_guard_after_buffers(
    monkeypatch: pytest.MonkeyPatch,
    command: int,
    revocation: str,
) -> None:
    request = live_request()
    native = LiveNative()
    allocate = ct.create_string_buffer
    injected = False

    def prepare(value: int | bytes, size: int | None = None) -> Any:
        nonlocal injected
        buffer = allocate(value) if size is None else allocate(value, size)
        if (
            isinstance(value, bytes)
            and len(value) >= 24
            and struct.unpack_from("<I", value, 12)[0] == command
        ):
            injected = True
            if revocation == "deadline":
                monkeypatch.setattr(time, "monotonic", lambda: 1e30)
            elif revocation == "callback":
                active_fix1_callback().mark_failed()
            elif revocation == "context":
                active_fix1_callback().context.value += 1
            else:
                object.__setattr__(request, "store_ref", "FOREIGN_STORE")
        return buffer

    monkeypatch.setattr(ct, "create_string_buffer", prepare)
    result = w.drive(
        native,
        request,
        GEN,
        time.monotonic() + 0.5,
        lambda name, raw: None,
        source_provenance={"source_review": {}, "receipts": {}, "files": {}},
    )
    assert injected and result.failure != "none" and result.capture_status == "failed"
    assert native.commands.count(command) == 0
    assert (
        result.live_open_attempts if command == 1281 else result.live_close_attempts
    ) == 0
    assert p.parse_result(result.to_json(), GEN) == result


def test_live_integration_postparse_authority_precedes_frame_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = LiveCodec.feed
    injected = False

    def feed(self: Any, raw: bytes, *, generation: int) -> Any:
        nonlocal injected
        frames = original(self, raw, generation=generation)
        if any(isinstance(frame, PrivateLiveFrame) for frame in frames):
            injected = True
            active_fix1_callback().context.value += 1
        return frames

    monkeypatch.setattr(LiveCodec, "feed", feed)
    result, captures = drive_live_inert(LiveNative())
    assert injected and result.failure == "denied" and result.live_frames == 0
    assert "live-000.bin" not in captures and "live-capture.json" not in captures
    assert p.parse_result(result.to_json(), GEN) == result


def test_live_integration_revocation_during_capture_withholds_manifest() -> None:
    native = LiveNative()
    names: list[str] = []

    def capture(name: str, raw: bytes) -> None:
        names.append(name)
        if name == "live-000.bin":
            active_fix1_callback().mark_failed()

    result = w.drive(
        native,
        live_request(),
        GEN,
        time.monotonic() + 0.5,
        capture,
        source_provenance={"source_review": {}, "receipts": {}, "files": {}},
    )
    assert result.failure == "denied" and result.live_frames == 0
    assert "live-000.bin" in names and "live-000.json" not in names
    assert (
        "live-capture.json" not in names
        and p.parse_result(result.to_json(), GEN) == result
    )


def test_live_integration_key_wait_is_bounded_and_closes_once() -> None:
    native = LiveNative(pre_key=64, frames=0)
    result, captures = drive_live_inert(native)
    assert result.failure == "unsupported" and result.capture_status == "failed"
    assert (
        result.live_frames_validated == result.pre_key_frames == 64
        and result.live_frames == 0
    )
    assert native.commands[-2:] == [1281, 1282] and native.commands.count(1282) == 1
    assert json.loads(captures["live-capture.json"])["capture_starts_at_key"] is False
    assert p.parse_result(result.to_json(), GEN) == result


@pytest.mark.parametrize("failure", ["partial", "interrupt"])
def test_live_integration_uncertain_open_never_resends_or_closes_wire(
    failure: str,
) -> None:
    class UncertainLive(LiveNative):
        def call(self, name: str, *args: Any) -> Any:
            observed = super().call(name, *args)
            if (
                name == "send"
                and struct.unpack_from("<I", ct.string_at(args[1], args[2]), 12)[0]
                == 1281
            ):
                if failure == "interrupt":
                    raise KeyboardInterrupt()
                return int(args[2]) - 1
            return observed

    native = UncertainLive()
    result, captures = drive_live_inert(native)
    assert result.failure in ("send", "runtime") and result.capture_status == "failed"
    assert native.commands.count(1281) == 1 and native.commands.count(1282) == 0
    assert "live-000.bin" not in captures
    assert [name for name, _ in native.delegate.calls][-3:] == [
        "stop",
        "destroy",
        "quit",
    ]
    assert p.parse_result(result.to_json(), GEN) == result


@pytest.mark.parametrize("file_index", [0, 1, 2, 3])
def test_live_integration_qualified_source_gate_and_frames_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_index: int,
) -> None:
    assert (
        p.ACCEPTED_HASHES[p.LIVE_RECEIPT]
        == "8039ff625abdb21c34214014af129286ee8becc3ed102986920b7289a1ae0b75"
    )
    fixture = inert_provider_root(tmp_path, monkeypatch)
    config = p.ProviderConfig(fixture["root"], fixture["root"], fixture["review"])
    assert p.verify_review(config) == fixture["manifest"]
    paths = [*fixture["liveFiles"], fixture["framePath"]]
    (fixture["root"] / paths[file_index]).write_bytes(b"INERT CHANGED LIVE DEPENDENCY")
    with pytest.raises(p.ProviderError):
        p.verify_review(config)


def test_live_integration_payload_wait_quota_and_raw_buffer_are_bounded() -> None:
    mux = w.LiveEnvelopes()
    with pytest.raises(LiveError):
        mux.feed(bytes((1 << 20) + 1))
    native = LiveNative(frames=0)
    injected = 0

    def capture(name: str, raw: bytes) -> None:
        nonlocal injected
        if name != "live-receive.bin" or injected >= 5:
            return
        injected += 1
        payload = b"P" * ((1 << 20) - 256)
        channel = native.open_wire[56:72]
        extension = struct.pack("<BBH4shhIB", 0, 0, 0, b"H264", 640, 480, 0, 0)
        body = (
            struct.pack("<BBBBiQQ", 0, 17, 0, 0, len(payload), 0, 0)
            + extension
            + payload
        )
        media = (
            struct.pack("<4sHBB", b"RAW!", 6, 1, 0)
            + channel
            + struct.pack("<iQii", len(body), 0, injected, 0)
            + body
        )
        frame = live_packet(65537, native.open_wire[24:96] + media)
        assert invoke(active_fix1_callback(), frame) == len(frame)

    result = w.drive(
        native,
        live_request(),
        GEN,
        time.monotonic() + 2,
        capture,
        source_provenance={"source_review": {}, "receipts": {}, "files": {}},
    )
    assert injected == 5 and result.failure == "codec"
    assert result.live_frames == 0 and result.pre_key_frames == 4
    assert result.live_payload_received == 4 * ((1 << 20) - 256)
    assert result.live_received_bytes < 8 << 20
    assert p.parse_result(result.to_json(), GEN) == result


@pytest.mark.parametrize(
    "changes",
    [
        {"authorized": True},
        {"live": True},
        {"capture_status": "pending"},
        {"live_frames": 5},
        {"live_close_attempts": 2},
        {"live_payload_received": (4 << 20) + 1},
        {"permissions_availability": "observed"},
        {"metadata_branch_complete": False},
    ],
)
def test_live_integration_parent_schema_rejects_false_completion(
    changes: dict[str, Any],
) -> None:
    result, _ = drive_live_inert(LiveNative())
    with pytest.raises(p.ProviderError):
        p.parse_result(
            json.dumps({**json.loads(result.to_json()), **changes}).encode(), GEN
        )


def test_live_integration_parent_reap_record_uses_original_owned_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct = str(p.direct_interpreter()[0])
    monkeypatch.setattr(
        p,
        "worker_command",
        lambda: [direct, "-I", "-S", "-c", "import time; time.sleep(30)"],
    )
    monkeypatch.setattr(p, "verify_review", lambda config: [])
    monkeypatch.setattr(p, "validate_bundle", lambda *args: {})
    monkeypatch.setattr(p, "check_private_acl", lambda path: None)
    monkeypatch.setattr(p, "protect_created_acl", lambda path: None)
    monkeypatch.setattr(p.ProviderConfig, "__post_init__", lambda self: None)
    provider = p.WindowsSocketProvider()
    result = provider.run(
        p.ProviderConfig(tmp_path, tmp_path, tmp_path / "receipt", 1), live_request()
    )
    assert result.reaped and result.failure == "deadline"
    assert provider.owner is not None and provider.owner.child is not None
    assert provider.owner.child.poll() is not None and provider.owner.confirmed
    assert provider.owner.job is not None and provider.owner.job.closed
    assert all(output.closed for output in provider.owner.outputs)
    raw = (tmp_path / result.generation / "live-owner.json").read_bytes()
    assert p.parse_result(raw, result.generation) == result


def test_live_integration_mux_near_cap_split_and_coalesced_tail() -> None:
    mux = w.LiveEnvelopes()
    first = live_packet(0x10000501, bytes((1 << 20) - 24))
    second = live_packet(65537, bytes(160))
    assert len(first) == 1 << 20
    assert list(mux.receive(first[:16])) == []
    assert list(mux.receive(first[16:] + second[:16])) == [(first, False)]
    assert list(mux.receive(second[16:])) == [(second, False)]


@pytest.mark.parametrize(
    "admin_xml",
    [
        b"<userType>default_admin</userType><adminName>OTHER</adminName>",
        b"<adminName> syntheticUser </adminName>",
        b"<adminName><!--OTHER-->syntheticUser</adminName>",
        b"<adminName>syntheticUser</adminName>",
    ],
)
def test_live_fix1_group_admin_without_actual_lp_denied_before_open(
    monkeypatch: pytest.MonkeyPatch,
    admin_xml: bytes,
) -> None:
    original = metadata_reply

    def reply_with_admin(index: int, *, sequence: int | None = None) -> bytes:
        raw = original(index, sequence=sequence)
        if index != 2:
            return raw
        body = raw[24:].replace(b"<adminName>A &amp; B</adminName>", admin_xml)
        header = bytearray(raw[:24])
        struct.pack_into("<I", header, 4, len(body) + 16)
        struct.pack_into("<I", header, 20, len(body))
        return bytes(header) + body

    monkeypatch.setattr(sys.modules[__name__], "metadata_reply", reply_with_admin)
    native = LiveNative(group="value", wrong="permission")
    result, captures = drive_live_inert(native)
    assert result.metadata_branch_complete and result.permissions_complete
    assert result.inventory_replies == 4 and result.failure == "denied"
    assert result.live_open_attempts == 0 and 1281 not in native.commands
    assert result.live_frames == 0 and "live-000.bin" not in captures
    assert p.parse_result(result.to_json(), GEN) == result


def test_live_fix1_actual_selected_lp_remains_positive_with_admin_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = metadata_reply

    def reply_with_admin(index: int, *, sequence: int | None = None) -> bytes:
        raw = original(index, sequence=sequence)
        if index != 2:
            return raw
        body = raw[24:].replace(
            b"<adminName>A &amp; B</adminName>",
            b"<userType>default_admin</userType><adminName>OTHER</adminName>",
        )
        header = bytearray(raw[:24])
        struct.pack_into("<I", header, 4, len(body) + 16)
        struct.pack_into("<I", header, 20, len(body))
        return bytes(header) + body

    monkeypatch.setattr(sys.modules[__name__], "metadata_reply", reply_with_admin)
    result, captures = drive_live_inert(LiveNative(group="value"))
    assert result.failure == "none" and result.live_frames == 4
    assert (
        json.loads(captures["live-capture.json"])["upstream_eligibility"]
        == "explicit_lp"
    )
    assert not result.authorized and not result.live


@pytest.mark.parametrize(
    "route,ack,expected",
    [
        (0, True, "none"),
        (0, False, "unsupported"),
        (1, True, "unsupported"),
        (2, True, "none"),
    ],
)
def test_live_taskless_rebind_first_only_ack_capture_and_strict_routes(
    monkeypatch: pytest.MonkeyPatch,
    route: int,
    ack: bool,
    expected: str,
) -> None:
    original_packet = live_packet
    original_codec = LiveCodec
    constructors: list[dict[str, Any]] = []

    def build_codec(**values: Any) -> LiveCodec:
        constructors.append(values.copy())
        return original_codec(**values)

    def packet(command: int, body: bytes, sequence: int = 6) -> bytes:
        if command == 0x10000501 and not ack:
            return b""
        if command == 65537 and route != 2:
            raw = bytearray(
                original_packet(command, body[72:] if route == 0 else body, 0)
            )
            raw[10] = route
            return bytes(raw)
        return original_packet(command, body, sequence)

    monkeypatch.setattr(w, "LiveCodec", build_codec)
    monkeypatch.setattr(sys.modules[__name__], "live_packet", packet)
    native = LiveNative(fragmented=True)
    result, captures = drive_live_inert(native)
    assert len(constructors) == 1 and constructors[0]["exclusive_first_task"] is True
    assert constructors[0]["stream"] == 1
    assert native.commands.count(1281) == 1 and native.commands.count(1282) <= 1
    assert [name for name, _ in native.delegate.calls].count("connect_sn") == 1
    assert [name for name, _ in native.delegate.calls][-3:] == [
        "stop",
        "destroy",
        "quit",
    ]
    assert active_fix1_callback().closed and result.failure == expected
    if expected == "none":
        assert result.live_frames == 4 and result.capture_status == "complete"
        frame = json.loads(captures["live-000.json"])
        assert frame["media_route"] == route and frame["wire_task_present"] == (
            route == 2
        )
        assert len(bytes.fromhex(frame["source_header_hex"])) == (
            16 if route == 0 else 88
        )
        assert frame["wire_task_guid_le"] == (
            frame["binding"]["task_guid_le"] if route == 2 else None
        )
        assert frame["binding"]["task_guid_provenance"] == "local_owner_generated"
        assert frame["task_correlation"] == (
            "wire_task" if route == 2 else "exclusive_first_task_after_matching_ack"
        )
    else:
        assert result.live_frames == 0 and "live-000.bin" not in captures
    assert p.parse_result(result.to_json(), GEN) == result


def test_live_taskless_rebind_codec_default_remains_strict() -> None:
    from wso_core.tvt.local_live import LiveIdentity, UnsupportedLive

    identity = LiveIdentity(
        generation=1, session=b"S" * 16, channel=b"C" * 16, task=b"T" * 16
    )
    codec = LiveCodec(
        identity=identity,
        peer_capability=6,
        channel_number=0,
        stream=1,
        authorize=lambda _: True,
    )
    codec.open(request_guid=b"R" * 16, sequence=6)
    codec.feed(live_packet(0x10000501, b"", 6), generation=1)
    frame = bytearray(live_packet(65537, live_media(b"C" * 16, 1, key=True), 0))
    frame[10] = 0
    with pytest.raises(UnsupportedLive):
        codec.feed(bytes(frame), generation=1)


def test_live_taskless_rebind_callback_first_claim_cannot_be_replaced() -> None:
    owner = w.CallbackOwner(7, 1)
    assert owner.claim_first_live()
    assert not owner.claim_first_live()
    owner.closed = True
    assert not owner.claim_first_live()
    closed = w.CallbackOwner(8, 2)
    closed.closed = True
    assert not closed.claim_first_live()
