"""Offline fixture safety tests are not S3/HTTP lifecycle acceptance."""

import json
import socket
import subprocess
import sys
import tarfile
import threading
import time
from io import BytesIO
from unittest.mock import Mock

import pytest

from tests.support.asset_harness import AssetHarness
from tests.support.asset_provider import LABEL, AssetProvider


def relay_fixture(tmp_path, monkeypatch, validate=None):
    from tests.support import asset_minio

    upstream, backend = socket.socketpair()
    observed = []

    def connect(self, target, deadline):
        observed.append(target)
        return upstream

    monkeypatch.setattr(asset_minio.LoopbackRelay, "_connect", connect)
    relay = asset_minio.LoopbackRelay(validate or (lambda *_: "172.28.0.2"), tmp_path)
    relay.start(deadline=time.monotonic() + 2)
    client = socket.create_connection(relay.address, timeout=2)
    client.settimeout(2)
    backend.settimeout(2)
    return relay, client, backend, observed


def receive_eof(stream):
    result = bytearray()
    while block := stream.recv(65536):
        result.extend(block)
    return bytes(result)


def test_relay_preserves_opaque_signed_bytes_and_half_close(tmp_path, monkeypatch):
    relay, client, backend, observed = relay_fixture(tmp_path, monkeypatch)
    request = (
        b"PUT /private/key?uploadId=opaque%2Fvalue HTTP/1.1\r\n"
        b"Host: 127.0.0.1:54321\r\nAuthorization: AWS4-HMAC-SHA256 fixture\r\n"
        b"Content-Length: 4\r\n\r\n\x00\xff\x10\x80"
    )
    response = b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n\xff\x00\x81"
    try:
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        assert receive_eof(backend) == request
        backend.sendall(response)
        backend.shutdown(socket.SHUT_WR)
        assert receive_eof(client) == response
        assert observed == [("172.28.0.2", 9000)]
        assert relay.address[0] == "127.0.0.1"
        assert 0 < relay.address[1] < 65536
    finally:
        client.close()
        backend.close()
        relay.close()
    assert not relay.live_threads and not relay.active_sockets


def test_relay_authority_failure_closes_client_without_backend_connect(
    tmp_path, monkeypatch
):
    def refuse(*_):
        raise RuntimeError("foreign endpoint")

    relay, client, backend, observed = relay_fixture(tmp_path, monkeypatch, refuse)
    try:
        assert client.recv(1) == b""
        assert not observed
        with pytest.raises(RuntimeError, match="relay transport failed"):
            relay.assert_healthy()
    finally:
        client.close()
        backend.close()
        relay.close()


@pytest.mark.parametrize("bound", ["bytes", "idle", "absolute"])
def test_relay_transport_bounds_close_owned_sockets(tmp_path, monkeypatch, bound):
    from tests.support import asset_minio

    if bound == "bytes":
        monkeypatch.setattr(asset_minio.LoopbackRelay, "MAX_BYTES", 3)
    elif bound == "idle":
        monkeypatch.setattr(asset_minio.LoopbackRelay, "IDLE_SECONDS", 0.05)
    else:
        monkeypatch.setattr(asset_minio.LoopbackRelay, "ABSOLUTE_SECONDS", 0.05)
    relay, client, backend, _ = relay_fixture(tmp_path, monkeypatch)
    try:
        if bound == "bytes":
            client.sendall(b"over")
        assert client.recv(1) == b""
        with pytest.raises(RuntimeError, match="relay transport failed"):
            relay.assert_healthy()
    finally:
        client.close()
        backend.close()
        relay.close()
    assert not relay.live_threads and not relay.active_sockets


def test_relay_admission_and_close_cancel_owned_validation(tmp_path, monkeypatch):
    from tests.support import asset_minio

    monkeypatch.setattr(asset_minio.LoopbackRelay, "MAX_CONNECTIONS", 1)
    entered = threading.Event()

    def validate(deadline, stop, children):
        entered.set()
        assert stop.wait(2)
        raise RuntimeError("cancelled")

    relay, client, backend, observed = relay_fixture(tmp_path, monkeypatch, validate)
    extra = None
    try:
        assert entered.wait(1)
        extra = socket.create_connection(relay.address, timeout=2)
        extra.settimeout(2)
        assert extra.recv(1) == b""
        started = time.monotonic()
        relay.close()
        assert time.monotonic() - started < 3
        assert not observed and not relay.live_threads and not relay.active_sockets
    finally:
        client.close()
        backend.close()
        if extra:
            extra.close()
        relay.close()


@pytest.mark.parametrize("late_stage", ["select", "recv"])
@pytest.mark.parametrize("refusal", ["expired", "stopped"])
def test_late_readiness_cannot_revive_original_idle_cutoff(
    tmp_path, monkeypatch, late_stage, refusal
):
    from tests.support import asset_minio

    first, client = socket.socketpair()
    second, backend = socket.socketpair()
    now = [100.0]
    calls = []

    def refuse():
        if refusal == "expired":
            now[0] = 102.0
        else:
            relay.stop.set()

    class DelayedRead:
        def setblocking(self, value):
            first.setblocking(value)

        def recv(self, size):
            block = first.recv(size)
            if late_stage == "recv":
                refuse()
            return block

    reader = DelayedRead()

    def readiness(readers, writers, errors, timeout):
        calls.append((readers, writers))
        if len(calls) == 1:
            if late_stage == "select":
                refuse()
            return [reader], [], []
        if len(calls) == 2:
            return [], [second], []
        now[0] = 200.0
        return [], [], []

    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    monkeypatch.setattr(asset_minio.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(asset_minio.select, "select", readiness)
    try:
        client.sendall(b"late-idle-byte")
        with pytest.raises(RuntimeError, match="cutoff"):
            relay._pump(reader, second, 160.0, 101.0)
        backend.setblocking(False)
        with pytest.raises(BlockingIOError):
            backend.recv(100)
        assert len(calls) == 1
    finally:
        for stream in (first, client, second, backend):
            stream.close()


@pytest.mark.parametrize("refusal", ["expired", "stopped"])
def test_late_send_return_cannot_refresh_idle_or_do_more_work(
    tmp_path, monkeypatch, refusal
):
    from tests.support import asset_minio

    now = [100.0]
    readiness_calls = []
    sent = []
    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)

    class Stream:
        def setblocking(self, value):
            pass

        def recv(self, size):
            return b"queued"

        def send(self, block):
            sent.append(bytes(block))
            if refusal == "expired":
                now[0] = 111.0
            else:
                relay.stop.set()
            return 1

    client, backend = Stream(), Stream()

    def readiness(*_):
        readiness_calls.append(1)
        if len(readiness_calls) == 1:
            return [client], [], []
        if len(readiness_calls) == 2:
            return [], [backend], []
        now[0] = 200.0
        return [], [], []

    monkeypatch.setattr(asset_minio.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(asset_minio.select, "select", readiness)
    with pytest.raises(RuntimeError, match="cutoff"):
        relay._pump(client, backend, 160.0, 101.0)
    assert sent == [b"queued"] and len(readiness_calls) == 2


@pytest.mark.parametrize("late_stage", ["settimeout", "connect"])
def test_late_successful_connect_return_refuses_original_subdeadline(
    tmp_path, monkeypatch, late_stage
):
    from tests.support import asset_minio

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    now = [100.0]
    timeouts = []
    connected = []
    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.state = "RUNNING"

    class DelayedConnect:
        def settimeout(self, timeout):
            timeouts.append(timeout)
            stream.settimeout(timeout)
            if late_stage == "settimeout":
                now[0] = 103.0

        def connect(self, target):
            connected.append(target)
            stream.connect(target)
            now[0] = 103.0

        def close(self):
            stream.close()

    monkeypatch.setattr(asset_minio.socket, "socket", lambda *_: DelayedConnect())
    monkeypatch.setattr(asset_minio.time, "monotonic", lambda: now[0])
    try:
        with pytest.raises(RuntimeError, match="relay connect failed"):
            relay._connect(listener.getsockname(), 110.0)
        assert timeouts == [2.0]
        assert len(connected) == (late_stage == "connect")
        assert stream.fileno() == -1 and not relay.active_sockets
    finally:
        stream.close()
        listener.close()


@pytest.mark.parametrize("late_stage", ["socket", "bind"])
@pytest.mark.parametrize("refusal", ["expired", "stopped"])
def test_late_startup_return_cannot_listen_or_admit(
    tmp_path, monkeypatch, late_stage, refusal
):
    from tests.support import asset_minio

    now = [100.0]
    stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen = Mock()
    admission = Mock()

    def refuse():
        if refusal == "expired":
            now[0] = 102.0
        else:
            relay.stop.set()

    class DelayedListener:
        def bind(self, address):
            stream.bind(address)
            if late_stage == "bind":
                refuse()

        def listen(self, backlog):
            listen(backlog)

        def settimeout(self, timeout):
            stream.settimeout(timeout)

        def getsockname(self):
            return stream.getsockname()

        def fileno(self):
            return stream.fileno()

        def close(self):
            stream.close()

    def create(*_):
        if late_stage == "socket":
            refuse()
        return DelayedListener()

    monkeypatch.setattr(asset_minio.socket, "socket", create)
    monkeypatch.setattr(asset_minio.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        asset_minio.threading, "Thread", lambda **_: Mock(start=admission)
    )
    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    try:
        with pytest.raises(RuntimeError, match="relay startup failed"):
            relay.start(deadline=101.0)
        assert not listen.called and not admission.called
        assert relay.state == "STOPPING"
        # Observe fixture cleanup before the test's defensive socket close.
        assert not relay.active_sockets and stream.fileno() == -1
    finally:
        stream.close()


def test_expired_relay_inspection_starts_no_child(monkeypatch):
    from tests.support.asset_minio import RelayCommands

    runner = Mock(side_effect=RuntimeError("must not spawn"))
    monkeypatch.setattr("tests.support.asset_minio.subprocess.Popen", runner)
    commands = RelayCommands(threading.Event())
    with pytest.raises(RuntimeError):
        commands.run(["offline-command"], {}, time.monotonic() - 1)
    assert not runner.called and not commands.records


@pytest.mark.parametrize("stream", [1, 2])
def test_relay_inspect_bounds_both_streams_and_reaps_owned_child(monkeypatch, stream):
    from tests.support.asset_minio import RelayCommands

    monkeypatch.setattr(RelayCommands, "MAX_CAPTURE", 128)
    commands = RelayCommands(threading.Event())
    try:
        with pytest.raises(RuntimeError, match="owned relay inspect failed") as failure:
            commands.run(
                [
                    sys.executable,
                    "-c",
                    f"import os,time;os.write({stream},b'PRIVATE_FIXTURE_OUTPUT'*100);time.sleep(10)",
                ],
                {},
                time.monotonic() + 2,
            )
        assert "PRIVATE_FIXTURE_OUTPUT" not in str(failure.value)
    finally:
        commands.stop.set()
        commands.cancel(time.monotonic() + 3)
    assert not commands.records


def test_delayed_relay_validation_sends_zero_backend_bytes(tmp_path, monkeypatch):
    from tests.support.asset_minio import LoopbackRelay

    monkeypatch.setattr(LoopbackRelay, "VALIDATION_SECONDS", 0.03)

    def late(*_):
        time.sleep(0.06)
        return "172.28.0.2"

    relay, client, backend, observed = relay_fixture(tmp_path, monkeypatch, late)
    try:
        assert client.recv(1) == b""
        assert not observed
        with pytest.raises(RuntimeError, match="relay transport failed"):
            relay.assert_healthy()
    finally:
        client.close()
        backend.close()
        relay.close()


def test_relay_stop_prevents_connect_after_validation_returns(tmp_path, monkeypatch):
    entered = threading.Event()

    def validated_after_stop(deadline, stop, children):
        entered.set()
        assert stop.wait(2)
        return "172.28.0.2"

    relay, client, backend, observed = relay_fixture(
        tmp_path, monkeypatch, validated_after_stop
    )
    try:
        assert entered.wait(1)
        relay.close()
        assert not observed and not relay.live_threads and not relay.active_sockets
    finally:
        client.close()
        backend.close()
        relay.close()


def test_unsettled_relay_cleanup_retains_target_and_aggregate_cutoff(
    tmp_path, monkeypatch
):
    from tests.support.asset_minio import LoopbackRelay

    monkeypatch.setattr(LoopbackRelay, "CLEANUP_SECONDS", 0.05)
    entered, release = threading.Event(), threading.Event()

    def blocked(*_):
        entered.set()
        release.wait(2)
        return "172.28.0.2"

    relay, client, backend, observed = relay_fixture(tmp_path, monkeypatch, blocked)
    provider = AssetProvider(tmp_path)
    provider.relay = relay
    provider.receipt = {"must": "clear"}
    provider.created = [
        ("network", provider.network),
        ("container", provider.container),
    ]
    docker = Mock()
    monkeypatch.setattr(provider, "docker", docker)
    try:
        assert entered.wait(1)
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="target retained"):
            provider.close()
        assert time.monotonic() - started < 0.5
        assert not docker.called and provider.receipt is None
        assert relay.live_threads
    finally:
        release.set()
        client.close()
        backend.close()
        relay.close()
    assert not observed


def test_sixteen_pending_validations_exclude_seventeenth(tmp_path):
    from tests.support.asset_minio import LoopbackRelay

    entered = threading.Event()
    lock = threading.Lock()
    count = 0

    def validate(deadline, stop, children):
        nonlocal count
        with lock:
            count += 1
            if count == 16:
                entered.set()
        stop.wait(2)
        return "172.28.0.2"

    relay = LoopbackRelay(validate, tmp_path)
    clients = []
    relay.start(deadline=time.monotonic() + 2)
    try:
        for _ in range(16):
            clients.append(socket.create_connection(relay.address, timeout=2))
        assert entered.wait(1)
        overflow = socket.create_connection(relay.address, timeout=2)
        clients.append(overflow)
        overflow.settimeout(2)
        assert overflow.recv(1) == b""
        assert count == 16 and relay.connections == 16
        assert len(relay.live_threads) == 17
    finally:
        relay.close()
        for client in clients:
            client.close()
    assert not relay.live_threads and not relay.active_sockets


def test_reverse_half_close_and_partial_writes_preserve_queued_bytes(
    tmp_path, monkeypatch
):
    from tests.support.asset_minio import LoopbackRelay

    first, client = socket.socketpair()
    second, backend = socket.socketpair()
    first.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
    second.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
    client.settimeout(2)
    backend.settimeout(2)
    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    response = b"opaque response" * 20000
    request = bytes(range(256)) * 2000
    errors = []
    observed = []

    def forward():
        try:
            now = time.monotonic()
            relay._pump(first, second, now + 3, now + 2)
        except (OSError, RuntimeError) as error:
            errors.append(type(error).__name__)
        finally:
            first.close()
            second.close()

    def target():
        backend.sendall(response)
        backend.shutdown(socket.SHUT_WR)
        observed.append(receive_eof(backend))

    worker = threading.Thread(target=forward)
    target_thread = threading.Thread(target=target)
    worker.start()
    target_thread.start()
    try:
        assert receive_eof(client) == response
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        target_thread.join(2)
        worker.join(2)
        assert observed == [request] and not errors
        assert not worker.is_alive() and not target_thread.is_alive()
    finally:
        relay.stop.set()
        for stream in (client, backend, first, second):
            stream.close()
        worker.join(2)
        target_thread.join(2)


def test_stopping_barrier_refuses_backend_registration(tmp_path):
    from tests.support.asset_minio import LoopbackRelay

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.start(deadline=time.monotonic() + 2)
    relay.close()
    with pytest.raises(RuntimeError, match="stopped before connect"):
        relay._connect(("172.28.0.2", 9000), time.monotonic() + 2)
    assert not relay.active_sockets


def test_validation_child_is_cancelled_and_reaped_before_cleanup_returns(tmp_path):
    from tests.support.asset_minio import LoopbackRelay

    entered = threading.Event()

    def validate(deadline, stop, commands):
        entered.set()
        commands.run([sys.executable, "-c", "import time;time.sleep(10)"], {}, deadline)
        return "172.28.0.2"

    relay = LoopbackRelay(validate, tmp_path)
    relay.start(deadline=time.monotonic() + 2)
    client = socket.create_connection(relay.address, timeout=2)
    try:
        assert entered.wait(1)
        limit = time.monotonic() + 1
        while not relay.commands.records and time.monotonic() < limit:
            time.sleep(0.01)
        assert relay.commands.records
        relay.close()
        assert not relay.commands.records and not relay.live_threads
    finally:
        client.close()
        relay.close()


def test_registered_backend_is_closed_before_late_connect_can_forward(
    tmp_path, monkeypatch
):
    from tests.support import asset_minio

    validating, validated, connecting, closed = (threading.Event() for _ in range(4))
    upstream, backend = socket.socketpair()
    observed = []

    def validate(*_):
        validating.set()
        assert validated.wait(2)
        return "172.28.0.2"

    class PendingConnect:
        def settimeout(self, value):
            assert 0 < value <= 2

        def connect(self, target):
            observed.append(target)
            connecting.set()
            assert closed.wait(2)

        def shutdown(self, how):
            upstream.shutdown(how)

        def close(self):
            closed.set()
            upstream.close()

    relay = asset_minio.LoopbackRelay(validate, tmp_path)
    relay.start(deadline=time.monotonic() + 2)
    client = socket.create_connection(relay.address, timeout=2)
    pump = Mock()
    monkeypatch.setattr(relay, "_pump", pump)
    try:
        assert validating.wait(1)
        monkeypatch.setattr(asset_minio.socket, "socket", lambda *_: PendingConnect())
        validated.set()
        assert connecting.wait(1)
        relay.close()
        assert closed.is_set() and not pump.called
        assert observed == [("172.28.0.2", 9000)]
        assert not relay.active_sockets and not relay.live_threads
    finally:
        validated.set()
        closed.set()
        client.close()
        backend.close()
        upstream.close()
        relay.close()


def test_unsettled_workers_share_one_cleanup_cutoff(tmp_path, monkeypatch):
    from tests.support import asset_minio

    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    calls = []

    class Unsettled:
        ident = 1

        def is_alive(self):
            return True

        def join(self, timeout):
            calls.append(timeout)

    relay.threads = {Unsettled(), Unsettled(), Unsettled()}
    monkeypatch.setattr(relay, "CLEANUP_SECONDS", 0.03)
    now = iter([1000.0, 1000.02, 1000.04, 1000.06])
    monkeypatch.setattr(asset_minio.time, "monotonic", lambda: next(now))
    with pytest.raises(RuntimeError, match="cleanup unsettled"):
        relay.close()
    assert calls[0] == pytest.approx(0.01)
    assert calls[1:] == [0, 0]
    assert len(relay.threads) == 3 and relay.state == "STOPPING"


def test_late_socket_control_return_cannot_start_backend_connect(tmp_path, monkeypatch):
    from tests.support import asset_minio

    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.state = "RUNNING"
    connected = []

    class DelayedSocket:
        def settimeout(self, timeout):
            time.sleep(0.05)

        def connect(self, target):
            connected.append(target)

        def close(self):
            pass

    monkeypatch.setattr(asset_minio.socket, "socket", lambda *_: DelayedSocket())
    with pytest.raises(RuntimeError, match="relay connect failed"):
        relay._connect(("172.28.0.2", 9000), time.monotonic() + 0.02)
    assert not connected and not relay.active_sockets


def test_completed_relay_thread_is_joined_before_registry_pruning(
    tmp_path, monkeypatch
):
    from tests.support.asset_minio import LoopbackRelay

    entered = threading.Event()

    def validate(deadline, stop, commands):
        entered.set()
        stop.wait(2)
        return "172.28.0.2"

    completed = threading.Thread(target=lambda: None)
    completed.start()
    completed.join()
    joined = Mock(wraps=completed.join)
    monkeypatch.setattr(completed, "join", joined)
    relay = LoopbackRelay(validate, tmp_path)
    relay.start(deadline=time.monotonic() + 2)
    with relay.lock:
        relay.threads.add(completed)
    client = socket.create_connection(relay.address, timeout=2)
    try:
        assert entered.wait(1)
        joined.assert_called_once_with(0)
        assert completed not in relay.threads
    finally:
        client.close()
        relay.close()


def volume_archive(
    *, uid=65532, gid=65532, mode=0o700, name="data", kind=tarfile.DIRTYPE, extra=False
):
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.uid, info.gid, info.mode, info.type = uid, gid, mode, kind
        archive.addfile(info)
        if extra:
            archive.addfile(tarfile.TarInfo("DO_NOT_EMIT_extra_private_name"))
    return output.getvalue()


@pytest.mark.parametrize(
    "case,stage",
    [
        ("uid", "entry_identity"),
        ("mode", "entry_identity"),
        ("name", "entry_name"),
        ("type", "entry_type"),
        ("extra", "entry_count"),
        ("malformed", "archive_parse"),
        ("nonzero", "command"),
        ("timeout", "command"),
    ],
)
def test_volume_failure_exposes_only_bounded_structured_metadata(
    tmp_path, monkeypatch, case, stage
):
    provider = AssetProvider(tmp_path)
    monkeypatch.setattr(
        provider, "docker_invocation", lambda *_: (["fixed-local-docker"], {})
    )
    payload = volume_archive(
        uid=0 if case == "uid" else 65532,
        mode=0o755 if case == "mode" else 0o700,
        name="DO_NOT_EMIT_private_name" if case == "name" else "data",
        kind=tarfile.REGTYPE if case == "type" else tarfile.DIRTYPE,
        extra=case == "extra",
    )
    if case == "malformed":
        payload = b"DO_NOT_EMIT_private_body"
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, stdout=payload, stderr=b"DO_NOT_EMIT_private_stderr"
        )
    )
    if case == "nonzero":
        runner.side_effect = subprocess.CalledProcessError(
            2,
            ["DO_NOT_EMIT_private_path"],
            output=b"DO_NOT_EMIT_private_body",
            stderr=b"DO_NOT_EMIT_private_stderr",
        )
    elif case == "timeout":
        runner.side_effect = subprocess.TimeoutExpired(
            ["DO_NOT_EMIT_private_path"], 15, output=b"DO_NOT_EMIT_private_body"
        )
    monkeypatch.setattr("tests.support.asset_provider.subprocess.run", runner)
    with pytest.raises(RuntimeError, match="nonroot data volume") as failure:
        provider.verify_data_volume()
    message = str(failure.value)
    assert "DO_NOT_EMIT" not in message
    assert len(message) < 512
    assert ": {" in message
    diagnostic = json.loads(message.partition(": ")[2])
    assert set(diagnostic) == {
        "stage",
        "returncode",
        "archive_bytes",
        "entry_count",
        "directory",
        "type",
        "uid",
        "gid",
        "mode",
    }
    assert diagnostic["stage"] == stage
    assert diagnostic["returncode"] == (
        2 if case == "nonzero" else None if case == "timeout" else 0
    )
    if case in {"malformed", "nonzero", "timeout"}:
        assert diagnostic["entry_count"] is None
        assert diagnostic["directory"] == "unobserved"
        assert diagnostic["uid"] is None
    else:
        assert diagnostic["entry_count"] == (2 if case == "extra" else 1)
        assert diagnostic["directory"] == (
            "unexpected" if case == "name" else "expected_data"
        )
        assert diagnostic["uid"] == (0 if case == "uid" else 65532)
        assert diagnostic["gid"] == 65532
        assert diagnostic["mode"] == (0o755 if case == "mode" else 0o700)
        assert diagnostic["type"] == ("regular" if case == "type" else "directory")
    assert provider.receipt is None


def test_exact_nonroot_volume_archive_still_passes(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    monkeypatch.setattr(
        provider, "docker_invocation", lambda *_: (["fixed-local-docker"], {})
    )
    monkeypatch.setattr(
        "tests.support.asset_provider.subprocess.run",
        Mock(
            return_value=subprocess.CompletedProcess(
                [], 0, stdout=volume_archive(), stderr=b""
            )
        ),
    )
    provider.verify_data_volume()
    assert provider.receipt is None


def test_scratch_build_copies_private_data_as_child_with_explicit_metadata(
    tmp_path, monkeypatch
):
    from tests.support import asset_provider

    provider = AssetProvider(tmp_path)
    monkeypatch.setattr(asset_provider, "require_linux_ci", lambda: None)
    monkeypatch.setattr(asset_provider, "LocalDocker", lambda *_: object())
    binary_bytes = b"offline fixture bytes, never an executable"

    def artifact(directory, name):
        target = directory / name
        target.write_bytes(binary_bytes)
        return target

    monkeypatch.setattr(asset_provider, "download_artifact", artifact)
    monkeypatch.setattr(asset_provider, "verify_binary_version", lambda *_: None)

    class BuildBoundaryReached(Exception):
        pass

    def stop_at_build(*arguments):
        assert arguments[:2] == ("build", "--network=none")
        raise BuildBoundaryReached

    monkeypatch.setattr(provider, "docker", stop_at_build)
    with pytest.raises(BuildBoundaryReached):
        provider.start()
    context = provider.work / "image"
    instructions = (context / "Dockerfile").read_text().splitlines()
    copies = [line.split() for line in instructions if line.startswith("COPY ")]
    assert len(copies) == 2
    data_copy = next(line for line in copies if "--chown=65532:65532" in line)
    assert data_copy[1:3] == ["--chown=65532:65532", "--chmod=0700"]
    # COPY directory contents into an existing root. /data must be a child,
    # not the destination root whose newly created metadata BuildKit preserves.
    assert data_copy[-1] == "/"
    data_root = context / data_copy[-2]
    assert data_root.is_dir() and not data_root.is_symlink()
    assert [entry.name for entry in data_root.iterdir()] == ["data"]
    data = data_root / "data"
    assert data.is_dir() and not data.is_symlink() and not list(data.iterdir())
    assert (context / "minio").read_bytes() == binary_bytes
    assert "USER 65532:65532" in instructions
    assert 'VOLUME ["/data"]' in instructions
    assert 'ENTRYPOINT ["/minio"]' in instructions
    assert not any(line.startswith(("RUN ", "ADD ")) for line in instructions)
    assert provider.receipt is None


@pytest.mark.parametrize("command", ["build", "create", "inspect", "remove", "copy"])
def test_all_docker_commands_pin_local_socket_and_private_config_despite_saved_context(
    tmp_path, monkeypatch, command
):
    from tests.support import asset_minio

    ambient = tmp_path / "ambient"
    ambient.mkdir()
    (ambient / "config.json").write_text('{"currentContext":"remote-deployment"}')
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    (alternate / "config.json").write_text('{"currentContext":"another-remote"}')
    monkeypatch.setenv("DOCKER_CONFIG", str(ambient))
    monkeypatch.setenv("HOME", str(ambient))
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("BUILDKIT_HOST", "tcp://remote-builder.invalid:1234")
    monkeypatch.setattr(asset_minio, "require_linux_ci", lambda: None)
    monkeypatch.setattr(
        asset_minio, "local_socket_identity", lambda: (1, 2, 0), raising=False
    )
    # Windows has no POSIX chmod/uid; only this OS boundary is emulated.
    monkeypatch.setattr(
        asset_minio, "verify_private_path", lambda *_: None, raising=False
    )
    provider = AssetProvider(tmp_path)
    provider.work = tmp_path / "owned"
    provider.work.mkdir()
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        if "cp" in arguments:
            import io
            import tarfile

            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w") as archive:
                info = tarfile.TarInfo("data")
                info.type, info.uid, info.gid, info.mode = (
                    tarfile.DIRTYPE,
                    65532,
                    65532,
                    0o700,
                )
                archive.addfile(info)
            return subprocess.CompletedProcess(
                arguments, 0, stdout=data.getvalue(), stderr=b""
            )
        return subprocess.CompletedProcess(arguments, 0, stdout="[]", stderr="")

    monkeypatch.setattr("tests.support.asset_provider.subprocess.run", run)
    if command == "copy":
        provider.verify_data_volume()
    elif command == "remove":
        provider.docker("container", "rm", "owned-resource")
    else:
        provider.docker(command, "owned-resource")
    monkeypatch.setenv("DOCKER_CONFIG", str(alternate))
    monkeypatch.setenv("DOCKER_CONTEXT", "remote-after-initialization")
    provider.docker("inspect", "owned-resource")
    for arguments, options in calls:
        assert arguments[:5] == [
            "docker",
            "--config",
            str(provider.work / "docker-config"),
            "--host",
            "unix:///var/run/docker.sock",
        ]
        assert options["env"]["DOCKER_CONFIG"] == str(provider.work / "docker-config")
        assert options["env"]["HOME"] == str(provider.work)
        assert not (
            {"DOCKER_HOST", "DOCKER_CONTEXT", "BUILDKIT_HOST"} & options["env"].keys()
        )
    assert json.loads((provider.work / "docker-config/config.json").read_text()) == {}


def test_changed_local_socket_refuses_docker_before_subprocess(tmp_path, monkeypatch):
    from tests.support import asset_minio

    monkeypatch.setattr(asset_minio, "require_linux_ci", lambda: None)
    monkeypatch.setattr(
        asset_minio, "verify_private_path", lambda *_: None, raising=False
    )
    observations = iter([(1, 2, 0), (1, 2, 0), (1, 99, 0)])
    monkeypatch.setattr(
        asset_minio, "local_socket_identity", lambda: next(observations), raising=False
    )
    provider = AssetProvider(tmp_path)
    provider.work = tmp_path / "owned"
    provider.work.mkdir()
    runner = Mock(
        return_value=subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
    )
    monkeypatch.setattr("tests.support.asset_provider.subprocess.run", runner)
    provider.docker("inspect", "owned")
    with pytest.raises(RuntimeError, match="local Docker socket identity changed"):
        provider.docker("remove", "owned")
    assert runner.call_count == 1


def owned_container_state(provider):
    provider.image = "sha256:" + "a" * 64
    return {
        "Name": "/" + provider.container,
        "Image": provider.image,
        "Config": {
            "Image": provider.image,
            "User": "65532:65532",
            "Entrypoint": ["/minio"],
            "Cmd": [
                "server",
                "/data",
                "--address",
                ":9000",
                "--console-address",
                ":9001",
                "--quiet",
            ],
            "Env": [
                "MINIO_ROOT_USER=" + provider.credentials["bootstrap"][0],
                "MINIO_ROOT_PASSWORD=" + provider.credentials["bootstrap"][1],
                "MINIO_BROWSER=off",
                "MINIO_UPDATE=off",
            ],
        },
        "NetworkSettings": {
            "Networks": {provider.network: {}},
            "Ports": {"9000/tcp": None},
        },
        "Mounts": [
            {
                "Destination": "/data",
                "Type": "volume",
                "Name": provider.volume,
                "RW": True,
            }
        ],
        "HostConfig": {
            "NetworkMode": provider.network,
            "Privileged": False,
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 2147483648,
            "NanoCpus": 2000000000,
            "PidsLimit": 128,
            "LogConfig": {"Type": "none"},
            "PortBindings": None,
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,nodev,size=64m,mode=0700,uid=65532,gid=65532"
            },
        },
    }


@pytest.mark.parametrize("mutation", ["public-port", "tmpfs-size", "tmpfs-mode"])
def test_container_mapping_refuses_public_port_or_unbounded_tmpfs(
    tmp_path, monkeypatch, mutation
):
    provider = AssetProvider(tmp_path)
    state = owned_container_state(provider)
    monkeypatch.setattr(
        provider,
        "inspect",
        lambda kind, _: (
            {"Name": provider.volume}
            if kind == "volume"
            else {"Internal": True}
            if kind == "network"
            else {}
        ),
    )
    monkeypatch.setattr(provider, "assert_image", lambda _: None)
    if mutation == "public-port":
        state["HostConfig"]["PortBindings"] = {
            "9000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "1234"}]
        }
    elif mutation == "tmpfs-size":
        state["HostConfig"]["Tmpfs"]["/tmp"] = "rw,size=8g"
    else:
        state["HostConfig"]["Tmpfs"]["/tmp"] = "rw,size=64m,mode=0777"
    with pytest.raises(RuntimeError, match="mapping mismatch"):
        provider.assert_container_mapping(state)


def test_unowned_provider_resource_refuses_cleanup(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    provider.created.append(("volume", provider.volume))
    calls = []

    def docker(*arguments):
        calls.append(arguments)
        return json.dumps([{"Name": provider.volume, "Labels": {LABEL: "foreign"}}])

    monkeypatch.setattr(provider, "docker", docker)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.close()
    assert not any("rm" in arguments for arguments in calls)


def test_unowned_local_image_refuses_cleanup(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    provider.created.append(("image", provider.image_tag))
    calls = []

    def docker(*arguments):
        calls.append(arguments)
        return json.dumps([{"Config": {"Labels": {LABEL: "foreign"}}}])

    monkeypatch.setattr(provider, "docker", docker)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.close()
    assert not any("rm" in arguments for arguments in calls)


def test_client_close_failure_does_not_prevent_owned_resource_teardown(
    tmp_path, monkeypatch
):
    provider = AssetProvider(tmp_path)
    client = Mock()
    client.close.side_effect = RuntimeError("transport close failed")
    provider.clients["bootstrap"] = client
    provider.created.append(("volume", provider.volume))
    calls = []

    def docker(*arguments):
        calls.append(arguments)
        return json.dumps(
            [{"Name": provider.volume, "Labels": {LABEL: provider.owner}}]
        )

    monkeypatch.setattr(provider, "docker", docker)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.close()
    assert ("volume", "rm", provider.volume) in calls


def test_private_directory_foreign_owner_refuses_deletion(tmp_path):
    provider = AssetProvider(tmp_path)
    provider.work = tmp_path / ("minio-" + provider.owner)
    provider.work.mkdir()
    (provider.work / "owner.json").write_text(json.dumps({"owner": "foreign"}))
    sentinel = provider.work / "keep"
    sentinel.write_text("owned by another task")
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.close()
    assert sentinel.exists()


def test_provider_start_refuses_windows_before_download_or_docker(
    tmp_path, monkeypatch
):
    provider = AssetProvider(tmp_path)
    monkeypatch.setattr("tests.support.asset_minio.sys.platform", "win32")
    docker = Mock()
    monkeypatch.setattr(provider, "docker", docker)
    with pytest.raises(RuntimeError, match="Linux amd64 CI"):
        provider.start()
    assert not docker.called and provider.work is None


def test_selected_asset_fixture_refuses_windows_without_skip(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.support.asset_harness.sys.platform", "win32")
    with pytest.raises(pytest.fail.Exception, match="actual owned Linux"):
        AssetHarness(tmp_path).__enter__()


def test_foreign_process_identity_refuses_signal(tmp_path, monkeypatch):
    harness = AssetHarness(tmp_path)

    class Process:
        pid = 123

        def poll(self):
            return None

    harness.process = Process()
    harness.start_time = 5
    monkeypatch.setattr(
        "tests.support.asset_harness.os.pidfd_open", lambda *_: 999, raising=False
    )
    monkeypatch.setattr("tests.support.asset_harness.os.close", lambda *_: None)
    monkeypatch.setattr(
        "tests.support.asset_harness.signal.pidfd_send_signal",
        lambda *_: None,
        raising=False,
    )
    monkeypatch.setattr(harness, "process_identity", lambda _: ("S", 456, 5))
    monkeypatch.setattr(
        "pathlib.Path.read_bytes", lambda _: b"WSO_ASSET_FIXTURE_OWNER=foreign"
    )
    with pytest.raises(ValueError, match="ownership mismatch"):
        harness.stop_api()


def process_fixture(tmp_path, monkeypatch):
    """Emulate a pinned subprocess handle; never call an operating-system signal."""
    harness = AssetHarness(tmp_path)
    events = []
    pinned = {"value": False}

    class Process:
        pid = 123

        def poll(self):
            return None

        def wait(self, timeout):
            events.append("wait")

    class Log:
        def close(self):
            events.append("log-close")

    harness.process = Process()
    harness.log = Log()
    harness.start_time = 5
    harness.command = [
        "fixture-python",
        "-m",
        "tests.support.asset_process",
        "api",
        "1234",
    ]

    def pin(*_):
        pinned["value"] = True
        events.append("pin")
        return 999

    def identity(_):
        events.append("identity")
        return "S", 123, 5

    def read(path):
        if path.name == "cmdline":
            return b"\0".join(part.encode() for part in harness.command) + b"\0"
        return f"WSO_ASSET_FIXTURE_OWNER={harness.owner}".encode()

    monkeypatch.setattr(harness, "process_identity", identity)
    monkeypatch.setattr("pathlib.Path.read_bytes", read)
    monkeypatch.setattr("tests.support.asset_harness.os.pidfd_open", pin, raising=False)
    monkeypatch.setattr(
        "tests.support.asset_harness.os.close", lambda *_: events.append("close")
    )
    monkeypatch.setattr(
        "tests.support.asset_harness.signal.pidfd_send_signal",
        lambda *_: events.append("signal"),
        raising=False,
    )
    monkeypatch.setattr("tests.support.asset_harness.signal.SIGKILL", 9, raising=False)
    return harness, events, pinned


def test_owned_process_pinned_before_signal_with_descriptor_closed(
    tmp_path, monkeypatch
):
    harness, events, _ = process_fixture(tmp_path, monkeypatch)
    harness.stop_api()
    assert events.index("pin") < events.index("identity") < events.index("signal")
    assert events.index("signal") < events.index("close") < events.index("wait")
    assert harness.process is None


def test_identity_change_during_pidfd_open_denies_signal_and_closes_handle(
    tmp_path, monkeypatch
):
    harness, events, pinned = process_fixture(tmp_path, monkeypatch)

    def changed(_):
        events.append("identity")
        return "S", 123, 999 if pinned["value"] else 5

    monkeypatch.setattr(harness, "process_identity", changed)
    with pytest.raises(ValueError, match="ownership mismatch"):
        harness.stop_api()
    assert "signal" not in events and "close" in events


def test_command_change_refuses_signal_and_closes_handle(tmp_path, monkeypatch):
    harness, events, _ = process_fixture(tmp_path, monkeypatch)
    original = __import__("pathlib").Path.read_bytes

    def read(path):
        return b"unrelated-process\0" if path.name == "cmdline" else original(path)

    monkeypatch.setattr("pathlib.Path.read_bytes", read)
    with pytest.raises(ValueError, match="ownership mismatch"):
        harness.stop_api()
    assert "signal" not in events and "close" in events


def test_process_disappearing_after_pin_refuses_signal_and_closes_handle(
    tmp_path, monkeypatch
):
    harness, events, _ = process_fixture(tmp_path, monkeypatch)

    def vanished(_):
        raise FileNotFoundError("process exited")

    monkeypatch.setattr(harness, "process_identity", vanished)
    with pytest.raises(ValueError, match="identity unavailable"):
        harness.stop_api()
    assert "signal" not in events and "close" in events
