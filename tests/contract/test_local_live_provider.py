"""Continuous session tests use invented transport bytes and no TVT device."""

from __future__ import annotations

import importlib
import threading
import time

import pytest


def module(name):
    return importlib.import_module("wso_tvt_bridge." + name)


def test_live_selection_rejects_invalid_stream_and_scope_substitution():
    live = module("local_live_provider")
    selection = live.LiveSelection(b"C" * 16, 17, 3, 1)
    assert selection.channel_guid == b"C" * 16
    for values in [
        (bytes(16), 17, 3, 1),
        (b"C" * 16, 256, 3, 1),
        (b"C" * 16, 17, 3, 0),
        (b"C" * 16, 17, 3, 1, "invalid"),
    ]:
        with pytest.raises(ValueError):
            live.LiveSelection(*values)


def test_live_callback_batch_preserves_fifo_bytes_and_existing_caps():
    import ctypes as ct

    worker = module("windows_socket_worker")
    owner = worker.CallbackOwner(7, 1, capacity=65536)
    chunks = [bytes([index % 256]) * 64 for index in range(192)]
    for chunk in chunks:
        buffer = ct.create_string_buffer(chunk)
        assert owner._data(
            owner.this_address,
            7,
            ct.addressof(buffer),
            len(chunk),
            0,
            owner.context_address,
        ) == len(chunk)
    assert owner.chunks.maxsize == 256 and owner.capacity == 65536
    assert owner.take_live_batch() == b"".join(chunks)
    assert owner.used == 0 and owner.chunks.qsize() == 0
    assert owner.take_live_batch() is None


def test_private_native_exception_is_not_retained_by_public_failure(monkeypatch):
    from pathlib import Path

    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_core.tvt.local_service import LocalDeviceFailure

    live, p = module("local_live_provider"), module("windows_socket")

    class BrokenNative:
        owner = None

        def run(self, *args, **kwargs):
            raise ValueError("INERT_PRIVATE_SUPPLIER_TEXT")

    monkeypatch.setattr(live, "WindowsSocketProvider", BrokenNative)
    provider = live.NativeLocalLiveProvider(
        p.ProviderConfig(
            Path("C:/inert"), Path("C:/inert"), Path("C:/inert/review"), 20
        )
    )
    with pytest.raises(LocalDeviceFailure) as caught:
        provider.open_session(
            LocalDeviceCredentials(
                serial="SYNTHETIC9",
                country="KR",
                username="inert",
                password="inert-secret",
            ),
            live.LiveSelection(b"C" * 16, 3, 2, 1),
            deadline_monotonic=time.monotonic() + 1,
            current=lambda: True,
            cancel=threading.Event(),
        )
    assert caught.value.__context__ is None
    assert "INERT_PRIVATE" not in str(caught.value)


def test_continuous_authority_has_no_128_message_terminal_limit():
    ipc = module("local_live_ipc")
    parent = ipc.LiveParentAuthority(time.monotonic() + 3, threading.Event())
    parent.bind("a" * 32)
    remote = ipc.LiveRemoteAuthority(
        parent.worker_connection, "a" * 32, parent.deadline
    )
    outcomes = []
    caller = threading.get_ident()
    seen = []

    def current():
        seen.append(threading.get_ident())
        return True

    def child():
        for _ in range(140):
            remote.require("send")
            outcomes.append(True)

    worker = threading.Thread(target=child)
    worker.start()
    try:
        while worker.is_alive() and time.monotonic() < parent.deadline:
            parent.pump(current)
            time.sleep(0.001)
        worker.join(1)
        assert len(outcomes) == 140 and not worker.is_alive()
        assert set(seen) == {caller}
    finally:
        remote.close()
        parent.close()


def inert_windows_live_provider(tmp_path, monkeypatch):
    import os

    if os.name != "nt":
        pytest.skip("Windows original Job proof")
    live, p = module("local_live_provider"), module("windows_socket")
    script = tmp_path / "inert_live_child.py"
    script.write_text(
        """import sys,json,time,ctypes as ct,struct
assert sys.stdin.buffer.readline()==b"J\\n"
packet=json.loads(sys.stdin.buffer.read())
k=ct.WinDLL("kernel32",use_last_error=True)
k.GetCurrentProcess.restype=ct.c_void_p
k.IsProcessInJob.argtypes=[ct.c_void_p,ct.c_void_p,ct.POINTER(ct.c_int)]
member=ct.c_int()
assert k.IsProcessInJob(k.GetCurrentProcess(),None,ct.byref(member)) and member.value
sys.path[:0]=SOURCES
from wso_tvt_bridge.local_live_ipc import LiveRemoteAuthority
authority=LiveRemoteAuthority.from_handle(packet["service_authority_handle"],packet["generation"],packet["deadline"])
authority.require("prepare")
selection=packet["live_selection"]
assert packet["request"]["stream"]==selection["stream"]
setup=dict(session=(b"S"*16).hex(),channel=selection["channel_guid"],task=(b"T"*16).hex(),open_request=(b"O"*16).hex(),peer_version=6,callback_generation=int(packet["generation"][:15],16)+1,raw_index=selection["raw_index"],window_index=selection["window_index"],ordinal=selection["ordinal"],stream=selection["stream"],live_basis="explicit_lp",login_accepted=True,serial_matched=True)
packet.pop("request")
authority.setup(setup)
def envelope(command,body,sequence=6):
    return struct.pack("<IiHBBIII",825307441,len(body)+16,6,2,1,command,sequence,max(0,len(body)-72))+body
authority.envelope(envelope(0x10000505,bytes(72)+struct.pack("<i",0)) if setup["stream"]==2 else envelope(0x10000501,b""))
routing=b"O"*16+b"S"*16+bytes.fromhex(selection["channel_guid"])+b"\\x02\\0\\0\\0"+b"T"*16+b"\\x01\\0\\0\\0"
for index in range(1,100):
    payload=b"\\0\\0\\0\\1\\x65inert"
    body=struct.pack("<BBBBiQQ",0,17,0,0,len(payload),116444736000000000+index*10000,116444736000010000+index*10000)+struct.pack("<BBH4shhIB",0,0,0,b"H264",640,480,0,0)+payload+bytes((-len(payload))%4)
    media=struct.pack("<4sHBB",b"RAW!",6,setup["stream"],int(index==1))+bytes.fromhex(selection["channel_guid"])+struct.pack("<iQii",len(body),116444736000020000+index*10000,index,0)+body
    authority.require("frame")
    authority.envelope(envelope(65537,routing+media))
time.sleep(30)
""".replace(
            "SOURCES",
            repr(
                [
                    str(p.ROOT / "services/tvt-bridge/src"),
                    str(p.ROOT / "packages/core/src"),
                ]
            ),
        ),
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
    native = p.WindowsSocketProvider()
    monkeypatch.setattr(live, "WindowsSocketProvider", lambda: native)
    provider = live.NativeLocalLiveProvider(
        p.ProviderConfig(tmp_path, tmp_path, tmp_path / "review", 20)
    )
    return live, p, native, provider


@pytest.mark.parametrize("case", ["close", "revoke", "cancel", "expiry", "dead"])
def test_real_windows_original_process_handoff_bounded_read_and_retirement(
    tmp_path, monkeypatch, case
):
    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_core.tvt.local_service import LocalDeviceFailure

    live, p, native, provider = inert_windows_live_provider(tmp_path, monkeypatch)
    cancel = threading.Event()
    session = provider.open_session(
        LocalDeviceCredentials(
            serial="SYNTHETIC9", country="KR", username="inert", password="inert-secret"
        ),
        live.LiveSelection(b"C" * 16, 3, 2, 1),
        deadline_monotonic=time.monotonic() + 3,
        current=lambda: True,
        cancel=cancel,
    )
    owner = session._owner
    try:
        assert (
            native.owner is None and owner.child.poll() is None and not owner.job.closed
        )
        assert session.proof.codec_supported and session.proof.channel_matched
        assert not hasattr(session, "credentials") and not hasattr(
            session, "current_callback"
        )
        for _ in range(2):
            frames = session.read_frames(
                max_frames=1,
                max_bytes=1 << 20,
                deadline_monotonic=time.monotonic() + 2,
                current=lambda: True,
            )
            assert len(frames) == 1 and frames[0].identity.channel == b"C" * 16
        if case == "revoke":
            with pytest.raises(LocalDeviceFailure):
                session.read_frames(
                    max_frames=1,
                    max_bytes=1 << 20,
                    deadline_monotonic=time.monotonic() + 1,
                    current=lambda: False,
                )
        elif case == "cancel":
            cancel.set()
        elif case == "expiry":
            assert session.current(
                deadline_monotonic=time.monotonic() + 0.1, current=lambda: True
            )
        elif case == "dead":
            owner.request_stop()
            owner.child.wait(timeout=1)
            assert not session.current(
                deadline_monotonic=time.monotonic() + 10, current=lambda: True
            )
        if case in ("cancel", "expiry"):
            end = time.monotonic() + 2
            while not owner.confirmed and time.monotonic() < end:
                time.sleep(0.01)
            assert owner.confirmed and owner.child.poll() is not None
            assert owner.job.closed and owner.service is None
        assert session.close()
        assert owner.confirmed and owner.child.poll() is not None and owner.job.closed
        assert owner.service is None and owner not in p.PENDING_OWNERS
        assert all(output.closed for output in owner.outputs)
        assert not session._authority.frames
        assert not list(tmp_path.glob("*/native.*"))
        assert next(iter(tmp_path.glob("*/result.json"))).stat().st_size == 0
    finally:
        session.close()


def test_sixteen_original_windows_live_sessions_are_isolated_and_seventeenth_is_busy(
    tmp_path, monkeypatch
):
    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_core.tvt.local_service import LocalDeviceFailure

    live, p, _native, provider = inert_windows_live_provider(tmp_path, monkeypatch)

    def opened(guid):
        return provider.open_session(
            LocalDeviceCredentials(
                serial="SYNTHETIC9",
                country="KR",
                username="inert",
                password="inert-secret",
            ),
            live.LiveSelection(guid, 3, 2, 1),
            deadline_monotonic=time.monotonic() + 20,
            current=lambda: True,
            cancel=threading.Event(),
        )

    sessions = []
    try:
        for index in range(16):
            sessions.append(opened(bytes([67 + index]) * 16))
        owners = [session._owner for session in sessions]
        assert (
            owners[0].child is not owners[1].child
            and owners[0].child.pid != owners[1].child.pid
        )
        assert len({owner.child.pid for owner in owners}) == 16
        assert len({owner.job.handle for owner in owners}) == 16
        assert len({s._authority.identity.generation for s in sessions}) == 16
        assert owners[0].job.handle != owners[1].job.handle
        assert (
            sessions[0]._authority.identity.generation
            != sessions[1]._authority.identity.generation
        )
        with pytest.raises(LocalDeviceFailure) as caught:
            opened(b"Z" * 16)
        assert caught.value.code == "LOCAL_DEVICE_BUSY" and caught.value.status == 429
        assert sessions[0].close()
        assert (
            owners[0].confirmed
            and owners[1].child.poll() is None
            and not owners[1].job.closed
        )
        frames = sessions[1].read_frames(
            max_frames=1,
            max_bytes=1 << 20,
            deadline_monotonic=time.monotonic() + 2,
            current=lambda: True,
        )
        assert frames[0].identity.channel == b"D" * 16
        sessions.append(opened(b"Z" * 16))
        assert sessions[-1]._owner.child is not owners[0].child
    finally:
        # close() may return bounded/unconfirmed while its original reaper is
        # still settling. Always service every original before asserting final
        # cleanup; an early assertion would leave the other fifteen live.
        deadline = time.monotonic() + 10
        pending = list(sessions)
        while pending:
            pending = [session for session in pending if not session.close()]
            assert not pending or time.monotonic() < deadline
            if pending:
                time.sleep(0.01)
        assert all(session._owner not in p.PENDING_OWNERS for session in sessions)


def test_heartbeat_extends_only_current_generation_and_cannot_revive_denial():
    ipc = module("local_live_ipc")
    parent = ipc.LiveParentAuthority(time.monotonic() + 1, threading.Event())
    assert parent.renew(time.monotonic() + 10, lambda: True)
    assert not parent.renew(time.monotonic() + 10, lambda: False)
    assert not parent.renew(time.monotonic() + 10, lambda: True)
    assert parent.failure == "denied"
    parent.close()


def test_heartbeat_cannot_revive_expired_generation():
    ipc = module("local_live_ipc")
    parent = ipc.LiveParentAuthority(time.monotonic() - 1, threading.Event())
    assert not parent.renew(time.monotonic() + 10, lambda: True)
    assert parent.failure == "deadline"
    parent.close()


def test_renew_cannot_cross_old_expiry_during_new_deadline_validation(monkeypatch):
    from types import SimpleNamespace

    ipc, inventory_ipc = module("local_live_ipc"), module("local_inventory_ipc")
    ticks = iter((9.8, 9.9, 10.1, 10.2, 10.3))
    clock = SimpleNamespace(monotonic=lambda: next(ticks, 10.4))
    monkeypatch.setattr(ipc, "time", clock)
    monkeypatch.setattr(inventory_ipc, "time", clock)
    parent = ipc.LiveParentAuthority(10.0, threading.Event())
    try:
        assert not parent.renew(20.0, lambda: True)
        assert parent.deadline == 10.0 and parent.failure == "deadline"
        assert parent._stop.is_set()
        assert not parent.renew(20.0, lambda: True)
    finally:
        parent.close()


def test_wire_before_bound_setup_fences_session():
    ipc = module("local_live_ipc")
    parent = ipc.LiveParentAuthority(time.monotonic() + 1, threading.Event())
    parent.bind("a" * 32)
    parent.worker_connection.send_bytes(b"E" + bytes(8))
    assert not parent.pump(lambda: True)
    assert parent.failure == "protocol"
    parent.close()


def helpers():
    import importlib.util
    import sys

    from wso_tvt_bridge.windows_socket import ROOT

    name = "_continuous_live_native_fixtures"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "tests/contract/test_windows_socket.py"
        )
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[name] = loaded
        spec.loader.exec_module(loaded)
    return sys.modules[name]


def test_continuous_small_callback_chunks_reach_keyframe_without_drops():
    import ctypes as ct
    import struct

    fixture = helpers()
    ipc, live, worker = (
        module("local_live_ipc"),
        module("local_live_provider"),
        module("windows_socket_worker"),
    )
    payload = b"\0\0\0\1\x65" + b"I" * 65530

    class ChunkedNative(fixture.LiveNative):
        def __init__(self):
            super().__init__(group="value")
            self.producer = None
            self.callback = None
            self.frame_envelope = b""
            self.produced_bytes = 0

        def call(self, name, *args):
            if name != "send":
                return super().call(name, *args)
            wire = ct.string_at(args[1], args[2])
            command = struct.unpack_from("<I", wire, 12)[0]
            if command == 1282:
                return len(wire)
            if command != 1281:
                return super().call(name, *args)
            self.commands.append(command)
            self.callback = fixture.active_fix1_callback()
            body = struct.pack(
                "<BBBBiQQ",
                0,
                17,
                0,
                0,
                len(payload),
                116444736000000000,
                116444736000010000,
            )
            body += (
                struct.pack("<BBH4shhIB", 0, 0, 0, b"H264", 640, 480, 0, 0)
                + payload
                + bytes((-len(payload)) % 4)
            )
            media = (
                struct.pack("<4sHBB", b"RAW!", 6, 1, 1)
                + wire[56:72]
                + struct.pack("<iQii", len(body), 116444736000020000, 1, 0)
                + body
            )
            self.frame_envelope = fixture.live_packet(65537, wire[24:96] + media)

            def produce():
                fixture.invoke(self.callback, fixture.live_packet(0x10000501, b""))
                time.sleep(0.12)
                for offset in range(0, len(self.frame_envelope), 64):
                    chunk = self.frame_envelope[offset : offset + 64]
                    if fixture.invoke(self.callback, chunk) != len(chunk):
                        break
                    self.produced_bytes += len(chunk)
                    time.sleep(0.002)

            self.producer = threading.Thread(target=produce)
            self.producer.start()
            return len(wire)

    selection = live.LiveSelection(
        bytes.fromhex("67452301ab89efcd0123456789abcdef"), 3, 2, 1
    )
    parent = ipc.LiveParentAuthority(time.monotonic() + 5, threading.Event(), selection)
    parent.bind(fixture.GEN)
    remote = ipc.LiveRemoteAuthority(
        parent.worker_connection, fixture.GEN, parent.deadline
    )
    native = ChunkedNative()
    outcomes = []

    def child():
        outcomes.append(
            worker.drive(
                native,
                fixture.live_request(),
                fixture.GEN,
                parent.deadline,
                lambda *_: None,
                service_authority=remote,
                discard_credentials=lambda: None,
            )
        )
        remote.close()

    thread = threading.Thread(target=child)
    thread.start()
    try:
        # Match the original supervisor's20ms private-authority pump cadence.
        while thread.is_alive() and not parent.ready and not parent.failure:
            parent.tick(lambda: True)
            time.sleep(0.02)
        assert parent.ready and parent.open_ack
        assert not native.callback.failed and native.callback.chunks.maxsize == 256
        assert native.callback.capacity == 1 << 20
        assert parent.frames[0].private_bytes() == payload
        assert native.produced_bytes == len(native.frame_envelope)
        assert native.callback.used == 0 and native.callback.chunks.qsize() == 0
    finally:
        parent.deny("denied")
        parent.close()
        thread.join(2)
        if native.producer is not None:
            native.producer.join(2)
        remote.close()
        assert not thread.is_alive()


def test_private_frame_queue_overflow_discards_all_frames():
    ipc, live = module("local_live_ipc"), module("local_live_provider")
    fixture = helpers()
    parent = ipc.LiveParentAuthority(
        time.monotonic() + 3, threading.Event(), live.LiveSelection(b"C" * 16, 3, 2, 1)
    )
    parent.bind(fixture.GEN)
    setup = {
        "session": (b"S" * 16).hex(),
        "channel": (b"C" * 16).hex(),
        "task": (b"T" * 16).hex(),
        "open_request": (b"O" * 16).hex(),
        "peer_version": 6,
        "stream": 1,
        "callback_generation": int(fixture.GEN[:15], 16) + 1,
        "raw_index": 3,
        "window_index": 2,
        "ordinal": 1,
        "live_basis": "explicit_lp",
        "login_accepted": True,
        "serial_matched": True,
    }
    parent.worker_connection.send_bytes(
        b"J"
        + ipc.encode(
            {"type": "setup", "data": setup, "generation": fixture.GEN, "sequence": 1}
        )
    )
    assert parent.pump(lambda: True)
    parent.worker_connection.recv_bytes()
    parent.worker_connection.send_bytes(b"E" + fixture.live_packet(0x10000501, b""))
    assert parent.pump(lambda: True)
    parent.worker_connection.recv_bytes()
    routing = (
        b"O" * 16 + b"S" * 16 + b"C" * 16 + b"\x02\0\0\0" + b"T" * 16 + b"\x01\0\0\0"
    )
    try:
        # Credit pauses between messages; a single adversarial message still
        # cannot exceed the unchanged parent FIFO count bound during parsing.
        parent.worker_connection.send_bytes(
            b"E"
            + b"".join(
                fixture.live_packet(
                    65537,
                    routing + fixture.live_media(b"C" * 16, index, key=index == 1),
                )
                for index in range(1, 18)
            )
        )
        assert not parent.pump(lambda: True) and parent.failure == "overflow"
        assert not parent.frames and parent.queued_bytes == 0
    finally:
        parent.close()


@pytest.mark.parametrize(
    "relative",
    [
        "packages/core/src/wso_core/tvt/local_media_service.py",
        "packages/contracts/src/wso_contracts/tvt/local_media.py",
        "packages/contracts/src/wso_contracts/tvt/media.py",
    ],
)
def test_source_receipt_pins_imported_media_contracts(tmp_path, monkeypatch, relative):
    fixture, p = helpers(), module("windows_socket")
    context = fixture.inert_provider_root(tmp_path, monkeypatch)
    config = p.ProviderConfig(context["root"], context["root"], context["review"])
    assert p.verify_review(config) == context["manifest"]
    (context["root"] / relative).write_bytes(b"INERT MEDIA CONTRACT DRIFT")
    with pytest.raises(p.ProviderError):
        p.verify_review(config)


@pytest.mark.parametrize("selected_stream", [1, 2])
@pytest.mark.parametrize("wrong", ["", "channel", "permission", "selection"])
def test_original_live_task_current_gate_frame_delivery_and_credential_release(
    wrong, selected_stream
):
    from dataclasses import replace

    ipc, live, worker_module = (
        module("local_live_ipc"),
        module("local_live_provider"),
        module("windows_socket_worker"),
    )
    fixture = helpers()
    guid = bytes.fromhex("67452301ab89efcd0123456789abcdef")
    selection = live.LiveSelection(
        guid,
        4 if wrong == "selection" else 3,
        2,
        1,
        "sub" if selected_stream == 2 else "main",
    )
    parent = ipc.LiveParentAuthority(time.monotonic() + 3, threading.Event(), selection)
    parent.bind(fixture.GEN)
    remote = ipc.LiveRemoteAuthority(
        parent.worker_connection, fixture.GEN, parent.deadline
    )
    dropped = []

    class Native(fixture.LiveNative):
        def call(self, name, *args):
            import ctypes as ct
            import struct

            if name == "send" and struct.unpack_from(
                "<I", ct.string_at(args[1], args[2]), 12
            )[0] in (1281, 1285):
                assert dropped == [True]
                retained_buffers = next(
                    value
                    for value in reversed(worker_module.RETAINED)
                    if type(value) is list
                )
                assert all(
                    b"syntheticUser" not in getattr(value, "raw", b"")
                    for value in retained_buffers
                )
            return super().call(name, *args)

    native = Native(group="value", wrong="" if wrong == "selection" else wrong)
    outcomes = []

    def child():
        outcomes.append(
            worker_module.drive(
                native,
                replace(fixture.live_request(), stream=selected_stream),
                fixture.GEN,
                parent.deadline,
                lambda *_: None,
                service_authority=remote,
                discard_credentials=lambda: dropped.append(True),
            )
        )

    thread = threading.Thread(target=child)
    thread.start()
    try:
        while thread.is_alive() and not parent.ready and not parent.failure:
            parent.pump(lambda: True)
            time.sleep(0.001)
        if wrong:
            assert not parent.ready
        else:
            assert parent.ready and parent.open_ack
            assert parent.frames[0].identity.channel == guid
            assert len(parent.frames[0].private_bytes()) > 0
            assert dropped == [True]
        parent.deny("denied")
        parent.close()
        thread.join(4)
        assert not thread.is_alive()
        assert not parent.frames
        assert native.commands.count(1281) + native.commands.count(1285) <= 1
        assert native.commands.count(1282) <= 1
    finally:
        remote.close()
        parent.close()


@pytest.mark.parametrize("stream", ["main", "sub"])
def test_provider_opens_sub_stream_selection(tmp_path, monkeypatch, stream):
    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_core.tvt.local_media_service import LocalMediaChannel

    _, _, _, provider = inert_windows_live_provider(tmp_path, monkeypatch)
    session = provider.open_session(
        LocalDeviceCredentials(
            serial="SYNTHETIC9", country="KR", username="inert", password="inert"
        ),
        LocalMediaChannel(b"C" * 16, 3, 2, 1, "camera", stream),
        deadline_monotonic=time.monotonic() + 3,
        current=lambda: True,
        cancel=threading.Event(),
    )
    try:
        assert session.proof.channel_matched and session.proof.codec_supported
        assert session._authority.setup_data["stream"] == (2 if stream == "sub" else 1)
    finally:
        assert session.close()


@pytest.mark.parametrize(
    "reason,code,status",
    [
        ("busy", "LOCAL_DEVICE_BUSY", 429),
        ("denied", "LOCAL_DEVICE_UPSTREAM_REJECTED", 502),
        ("refused", "LOCAL_DEVICE_UPSTREAM_REJECTED", 502),
    ],
)
def test_provider_maps_device_refusals(reason, code, status):
    error = module("local_live_provider").failure("device_" + reason)
    assert (error.code, error.status) == (code, status)


def sub_parent_setup():
    ipc, live = module("local_live_ipc"), module("local_live_provider")
    parent = ipc.LiveParentAuthority(
        time.monotonic() + 3,
        threading.Event(),
        live.LiveSelection(b"C" * 16, 3, 2, 1, "sub"),
    )
    parent.bind(helpers().GEN)
    setup = {
        "session": (b"S" * 16).hex(),
        "channel": (b"C" * 16).hex(),
        "task": (b"T" * 16).hex(),
        "open_request": (b"O" * 16).hex(),
        "peer_version": 6,
        "stream": 2,
        "callback_generation": int(helpers().GEN[:15], 16) + 1,
        "raw_index": 3,
        "window_index": 2,
        "ordinal": 1,
        "live_basis": "explicit_lp",
        "login_accepted": True,
        "serial_matched": True,
    }
    return parent, setup


@pytest.mark.parametrize("stream", [1, True, "2", 0, 3, None])
def test_setup_stream_mismatch_denied(stream):
    ipc = module("local_live_ipc")
    parent, setup = sub_parent_setup()
    setup["stream"] = stream
    try:
        with pytest.raises(ipc.AuthorityError):
            parent._setup(setup)
        assert parent.codec is None
    finally:
        parent.close()


@pytest.mark.parametrize(
    "code,reason",
    [(0x20000030, "device_busy"), (0x20000029, "device_denied"), (7, "device_refused")],
)
def test_parent_independently_maps_correlated_refusal(code, reason):
    import struct

    parent, setup = sub_parent_setup()
    try:
        parent._authorized = True
        parent._setup(setup)
        routing = b"O" * 16 + b"S" * 16 + b"C" * 16 + bytes(4) + b"T" * 16 + bytes(4)
        parent.worker_connection.send_bytes(
            b"E" + helpers().live_packet(0x20000505, routing + struct.pack("<i", code))
        )
        assert not parent.pump(lambda: True)
        assert parent.failure == reason and not parent.ready and not parent.frames
        assert not parent.pump(lambda: True)
    finally:
        parent.close()


@pytest.mark.parametrize(
    "code,warning", [(0, False), (0x20000060, True), (0x20000030, False)]
)
def test_sub_ack_warning_is_read_only_and_does_not_create_readiness(code, warning):
    import struct

    parent, setup = sub_parent_setup()
    try:
        parent._authorized = True
        parent._setup(setup)
        parent.worker_connection.send_bytes(
            b"E"
            + helpers().live_packet(0x10000505, bytes(72) + struct.pack("<i", code))
        )
        assert parent.pump(lambda: True)
        assert parent.open_ack and not parent.ready
        assert parent.sub_stream_adaptation_off is warning
        with pytest.raises(AttributeError):
            parent.sub_stream_adaptation_off = False
    finally:
        parent.close()


@pytest.mark.parametrize("stream", [1, 2])
@pytest.mark.parametrize(
    "case,code,reason",
    [
        ("valid", 0x20000030, "device_busy"),
        ("valid", 0x20000029, "device_denied"),
        ("valid", 9, "device_refused"),
        ("wrong_command", 0x20000030, ""),
        ("wrong_task", 0x20000030, ""),
    ],
)
def test_native_refusal_pipe_preserves_reason_and_retires_original(
    stream, case, code, reason
):
    import ctypes as ct
    import struct
    from dataclasses import replace

    fixture = helpers()
    ipc, live, worker = (
        module("local_live_ipc"),
        module("local_live_provider"),
        module("windows_socket_worker"),
    )
    guid = bytes.fromhex("67452301ab89efcd0123456789abcdef")
    parent = ipc.LiveParentAuthority(
        time.monotonic() + 1,
        threading.Event(),
        live.LiveSelection(guid, 3, 2, 1, "sub" if stream == 2 else "main"),
    )
    parent.bind(fixture.GEN)
    remote = ipc.LiveRemoteAuthority(
        parent.worker_connection, fixture.GEN, parent.deadline
    )
    outcomes = []

    class RefusingNative(fixture.LiveNative):
        def call(self, name, *args):
            if name == "send":
                wire = ct.string_at(args[1], args[2])
                command = struct.unpack_from("<I", wire, 12)[0]
                if command in (1281, 1285):
                    self.commands.append(command)
                    body = bytearray(wire[24:96])
                    if case == "wrong_task":
                        body[52:68] = b"X" * 16
                    if case == "wrong_command":
                        command = 1281 if command == 1285 else 1285
                    reply = fixture.live_packet(
                        0x20000000 | command, bytes(body) + struct.pack("<i", code)
                    )
                    fixture.invoke(fixture.active_fix1_callback(), reply)
                    return len(wire)
            return super().call(name, *args)

    native = RefusingNative(group="value")

    def child():
        outcomes.append(
            worker.drive(
                native,
                replace(fixture.live_request(), stream=stream),
                fixture.GEN,
                parent.deadline,
                lambda *_: None,
                service_authority=remote,
                discard_credentials=lambda: None,
            )
        )
        remote.close()

    thread = threading.Thread(target=child)
    thread.start()
    try:
        while (
            thread.is_alive()
            and not parent.failure
            and time.monotonic() < parent.deadline
        ):
            parent.pump(lambda: True)
            time.sleep(0.001)
        assert not parent.ready and not parent.open_ack and not parent.frames
        if reason:
            assert parent.failure == reason
            error = live.failure(parent.failure)
            assert error.code == (
                "LOCAL_DEVICE_BUSY"
                if reason == "device_busy"
                else "LOCAL_DEVICE_UPSTREAM_REJECTED"
            )
        else:
            assert not thread.is_alive()
            assert outcomes[0].failure == "codec"
    finally:
        parent.close()
        thread.join(2)
        remote.close()
    assert not thread.is_alive()
    assert [name for name, _ in native.delegate.calls][-3:] == [
        "stop",
        "destroy",
        "quit",
    ]
    assert fixture.active_fix1_callback().closed


def first_frame_parent(monkeypatch, *, ack=True):
    import struct
    from types import SimpleNamespace

    ipc, inventory = module("local_live_ipc"), module("local_inventory_ipc")
    now = [100.0]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(ipc, "time", clock)
    monkeypatch.setattr(inventory, "time", clock)
    parent, setup = sub_parent_setup()
    parent.deadline = 120.0
    parent._authorized = True
    parent._setup(setup)
    if ack:
        parent.worker_connection.send_bytes(
            b"E" + helpers().live_packet(0x10000505, bytes(72) + struct.pack("<i", 0))
        )
        assert parent.tick(lambda: True)
        assert parent.open_ack and not parent.ready
    return parent, now


def test_ack_without_media_raises_no_signal_at_ten_seconds(monkeypatch):
    parent, now = first_frame_parent(monkeypatch)
    try:
        now[0] = 109.9
        assert parent.tick(lambda: True) and not parent.ready
        now[0] = 110.0
        assert not parent.tick(lambda: True), (
            "accepted open without media must be bounded"
        )
        assert parent.failure == "no_signal" and not parent.frames
        error = module("local_live_provider").failure(parent.failure)
        assert (error.code, error.status) == ("LOCAL_DEVICE_NO_SIGNAL", 504)
        assert not parent.tick(lambda: True)
    finally:
        parent.close()


def first_keyframe_wire(parent):
    fixture = helpers()
    routing = b"O" * 16 + b"S" * 16 + b"C" * 16 + bytes(4) + b"T" * 16 + bytes(4)
    media = bytearray(fixture.live_media(b"C" * 16, 1, key=True))
    media[6] = 2
    return b"E" + fixture.live_packet(65537, routing + bytes(media))


@pytest.mark.parametrize("arrival,ready", [(109.9, True), (110.0, False)])
def test_accepted_ack_first_keyframe_before_or_at_bound(monkeypatch, arrival, ready):
    parent, now = first_frame_parent(monkeypatch)
    try:
        now[0] = arrival
        parent.worker_connection.send_bytes(first_keyframe_wire(parent))
        assert parent.tick(lambda: True) is ready
        assert parent.ready is ready
        if ready:
            assert parent.frames and parent.failure == ""
            now[0] = 111.0
            assert parent.tick(lambda: True)
        else:
            assert parent.failure == "no_signal" and not parent.frames
    finally:
        parent.close()


@pytest.mark.parametrize(
    "case,want",
    [
        ("no_ack", "deadline"),
        ("denied", "denied"),
        ("cancelled", "cancelled"),
        ("deadline", "deadline"),
        ("refused", "device_busy"),
    ],
)
def test_no_signal_preserves_other_startup_failure_reasons(monkeypatch, case, want):
    import struct

    parent, now = first_frame_parent(monkeypatch, ack=case not in ("no_ack", "refused"))
    try:
        now[0] = 110.0
        if case == "no_ack":
            assert parent.tick(lambda: True) and not parent.failure
            now[0] = 120.0
        elif case == "cancelled":
            parent.cancel.set()
        elif case == "deadline":
            parent.deadline = 110.0
        elif case == "refused":
            routing = (
                b"O" * 16 + b"S" * 16 + b"C" * 16 + bytes(4) + b"T" * 16 + bytes(4)
            )
            parent.worker_connection.send_bytes(
                b"E"
                + helpers().live_packet(
                    0x20000505, routing + struct.pack("<i", 0x20000030)
                )
            )
        assert not parent.tick(lambda: case != "denied")
        assert parent.failure == want and not parent.ready and not parent.frames
    finally:
        parent.close()


def test_duplicate_ack_cannot_extend_first_frame_deadline(monkeypatch):
    import struct

    parent, now = first_frame_parent(monkeypatch)
    try:
        now[0] = 109.9
        parent.worker_connection.send_bytes(
            b"E" + helpers().live_packet(0x10000505, bytes(72) + struct.pack("<i", 0))
        )
        assert not parent.tick(lambda: True)
        # The independent codec rejects a duplicate ACK; it never restarts waiting.
        assert parent.failure == "protocol"
        now[0] = 110.0
        assert not parent.tick(lambda: True) and parent.failure == "protocol"
    finally:
        parent.close()


def test_no_signal_takes_fresh_authority_over_cached_tick_result(monkeypatch):
    parent, now = first_frame_parent(monkeypatch)
    calls = []
    try:
        now[0] = 109.95
        assert parent.tick(lambda: True)
        now[0] = 110.0  # ParentAuthority's 100ms poll cache is still fresh.
        assert not parent.tick(lambda: calls.append(1) or False)
        assert calls == [1] and parent.failure == "denied"
    finally:
        parent.close()


@pytest.mark.parametrize("confirmed", [True, False])
def test_provider_no_signal_retains_and_retires_exact_original_owner(
    monkeypatch, confirmed
):
    from pathlib import Path
    from types import SimpleNamespace

    from wso_core.tvt.local_credentials import LocalDeviceCredentials
    from wso_core.tvt.local_service import LocalDeviceFailure

    live, ipc, inventory = (
        module("local_live_provider"),
        module("local_live_ipc"),
        module("local_inventory_ipc"),
    )
    now = [100.0]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    for target in (live, ipc, inventory):
        monkeypatch.setattr(target, "time", clock)
    original = SimpleNamespace(confirmed=False)
    finishes = []
    authority = []

    def finish():
        finishes.append(original)
        original.confirmed = confirmed
        authority[0].close()
        return confirmed

    original.finish = finish

    class Native:
        owner = original

        def run(self, config, request, *, service, current):
            import struct

            authority.append(service)
            service.bind(helpers().GEN)
            unused, setup = sub_parent_setup()
            unused.close()
            # This setup is derived independently from the public selection.
            service._authorized = True
            service._setup(setup)
            service.worker_connection.send_bytes(
                b"E"
                + helpers().live_packet(0x10000505, bytes(72) + struct.pack("<i", 0))
            )
            assert service.tick(current)
            now[0] = 109.9
            assert service.tick(current) and not service.ready
            now[0] = 110.0
            assert not service.tick(current) and service.failure == "no_signal"

    native = Native()
    monkeypatch.setattr(live, "WindowsSocketProvider", lambda: native)
    registry = module("windows_socket")
    registry.register_pending_owner(original)
    try:
        provider = live.NativeLocalLiveProvider(
            module("windows_socket").ProviderConfig(
                Path("C:/inert"), Path("C:/inert"), Path("C:/inert/review"), 20
            )
        )
        with pytest.raises(LocalDeviceFailure) as failure:
            provider.open_session(
                LocalDeviceCredentials(
                    serial="SYNTHETIC9",
                    country="KR",
                    username="inert",
                    password="inert-secret",
                ),
                live.LiveSelection(b"C" * 16, 3, 2, 1, "sub"),
                deadline_monotonic=120.0,
                current=lambda: True,
                cancel=threading.Event(),
            )
        assert (failure.value.code, failure.value.status) == (
            "LOCAL_DEVICE_NO_SIGNAL",
            504,
        )
        assert finishes == [original] and native.owner is original
        assert (original in registry.pending_owner_snapshot()) is (not confirmed)
        assert not authority[0].handed_off and not authority[0].ready
    finally:
        original.confirmed = True
        registry.remove_confirmed_owner(original)
