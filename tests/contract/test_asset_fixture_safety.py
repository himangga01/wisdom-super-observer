"""Offline fixture safety tests are not S3/HTTP lifecycle acceptance."""

import http.client
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


def settle_owned_test(*operations):
    primary = sys.exception()
    first_cleanup_error = None
    for operation in operations:
        try:
            operation()
        except Exception as error:  # noqa: BLE001 -- attempt all cleanup and retain primary failure
            if first_cleanup_error is None:
                first_cleanup_error = error
    if primary is None and first_cleanup_error is not None:
        raise first_cleanup_error


def join_owned_thread(thread):
    if thread is not None and thread.ident is not None:
        thread.join(1)
        assert not thread.is_alive()


def receive_request_line(stream):
    deadline = time.monotonic() + 1
    result = bytearray()
    while b"\r\n" not in result:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("owned request line exceeded its one-second allowance")
        assert len(result) < 4096, "owned request line exceeded its fixed size cap"
        stream.settimeout(remaining)
        block = stream.recv(4096 - len(result))
        assert block, "owned stream ended before its request-line terminator"
        result.extend(block)
    return bytes(result).split(b"\r\n", 1)[0]


@pytest.mark.parametrize("primary", [False, True])
def test_owned_teardown_attempts_all_and_preserves_first_failure(primary):
    seen = []
    cleanup_error = OSError("owned cleanup failure")
    primary_error = AssertionError("primary test failure")

    def fail():
        seen.append("close")
        raise cleanup_error

    def join():
        seen.append("join")
        raise AssertionError("secondary termination failure")

    expected = primary_error if primary else cleanup_error
    with pytest.raises(type(expected)) as captured:
        try:
            if primary:
                raise primary_error
        finally:
            settle_owned_test(fail, join)
    assert seen == ["close", "join"]
    assert captured.value is expected


def test_owned_http_request_line_accepts_bounded_fragmentation():
    stream = Mock()
    stream.recv.side_effect = [
        b"GET /pending-",
        b"owned-test HTTP/1.1\r",
        b"\nHost: owned",
    ]
    assert receive_request_line(stream) == b"GET /pending-owned-test HTTP/1.1"


class OwnedTcpRelay:
    """Only local test sockets; original registration/connect executes for each pair."""

    def __init__(self, tmp_path, monkeypatch, *, idle=0.2):
        from tests.support import asset_minio

        self.socket_type = socket.socket
        self.listener = self.socket_type(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.listener.settimeout(2)
        self.peers, self.targets, self.validations = [], [], []
        self.completed, self.errors = [], []
        self.condition = threading.Condition()
        self.tracked = []
        original_connect = asset_minio.LoopbackRelay._connect
        original_worker = asset_minio.LoopbackRelay._worker

        def validate(*_):
            self.validations.append(True)
            return "127.0.0.1"

        def connect(relay, target, deadline):
            self.targets.append(target)
            assert target == ("127.0.0.1", 9000)
            # Only the test's fixed owned numeric port changes; all real guards run.
            return original_connect(relay, self.listener.getsockname(), deadline)

        def worker(relay, client, accepted):
            try:
                original_worker(relay, client, accepted)
            except Exception as error:  # noqa: BLE001 -- retain every test worker failure for assertion
                self.errors.append(error)
            finally:
                with self.condition:
                    self.completed.append(client)
                    self.condition.notify_all()

        monkeypatch.setattr(asset_minio.LoopbackRelay, "_connect", connect)
        monkeypatch.setattr(asset_minio.LoopbackRelay, "_worker", worker)
        self.relay = asset_minio.LoopbackRelay(validate, tmp_path)
        self.relay.IDLE_SECONDS = idle
        self.relay.start(deadline=time.monotonic() + 2)

    def open(self):
        client = self.socket_type(socket.AF_INET, socket.SOCK_STREAM)
        self.peers.append(client)
        client.settimeout(1)
        client.connect(self.relay.address)
        backend, _ = self.listener.accept()
        self.peers.append(backend)
        backend.settimeout(1)
        return client, backend

    def wait_completed(self, count):
        with self.condition:
            assert self.condition.wait_for(lambda: len(self.completed) >= count, 2)

    @staticmethod
    def exchange(client, backend, payload=b"owned-request"):
        def exact(stream, size):
            result = bytearray()
            while len(result) < size:
                block = stream.recv(size - len(result))
                assert block, "owned stream ended before its fixed bytes"
                result.extend(block)
            return bytes(result)

        client.sendall(payload)
        assert exact(backend, len(payload)) == payload
        backend.sendall(b"owned-response")
        assert exact(client, 14) == b"owned-response"

    def fault_close(self, monkeypatch, *, failed_role, after):
        from tests.support import asset_minio

        owner = self

        class TrackedSocket(self.socket_type):
            def __init__(self, *args, role, **kwargs):
                super().__init__(*args, **kwargs)
                self.role = role
                self.attempts = 0

            def close(self):
                self.attempts += 1
                if self.role == failed_role and self.attempts == 1:
                    if after:
                        super().close()
                    raise OSError("controlled owned close failure")
                super().close()

        def create(*args, **kwargs):
            name = threading.current_thread().name
            role = (
                "client"
                if name == "owned-asset-relay"
                else "backend"
                if name == "owned-asset-connection"
                else None
            )
            if role is None:
                return owner.socket_type(*args, **kwargs)
            stream = TrackedSocket(*args, role=role, **kwargs)
            owner.tracked.append(stream)
            return stream

        monkeypatch.setattr(asset_minio.socket, "socket", create)

    def close(self):
        settle_owned_test(
            self.relay.close, *(peer.close for peer in self.peers), self.listener.close
        )


def test_idle_retirement_preserves_active_pair_and_fresh_real_replacement(
    tmp_path, monkeypatch
):
    owned = OwnedTcpRelay(tmp_path, monkeypatch)
    stop, progressed = threading.Event(), threading.Event()
    cycles, active_errors = [], []
    active_worker = None
    try:
        retired, retired_backend = owned.open()
        active, active_backend = owned.open()

        def transfer():
            try:
                while not stop.is_set():
                    owned.exchange(active, active_backend)
                    cycles.append(True)
                    progressed.set()
                    stop.wait(0.02)
            except (OSError, AssertionError) as error:
                active_errors.append(error)

        active_worker = threading.Thread(target=transfer)
        active_worker.start()
        assert progressed.wait(1)
        owned.wait_completed(1)
        assert retired.recv(1) == b"" and retired_backend.recv(1) == b""
        assert owned.completed[0].fileno() == -1
        assert owned.relay.connections == 1
        owned.relay.assert_healthy()
        previous = len(cycles)
        progressed.clear()
        assert progressed.wait(1) and len(cycles) > previous
        replacement, replacement_backend = owned.open()
        owned.exchange(replacement, replacement_backend, b"fresh-authorized-pair")
        assert owned.validations == [True, True, True]
        assert owned.targets == [("127.0.0.1", 9000)] * 3
        assert not active_errors and not owned.errors
        assert owned.relay.first_origin is None and owned.relay.failed is False
    finally:
        stop.set()
        settle_owned_test(owned.close, lambda: join_owned_thread(active_worker))
    assert not owned.relay.live_threads and not owned.relay.active_sockets
    assert owned.relay.connections == 0


def test_idle_retirement_exposes_real_pending_http_failure_before_caller_timeout(
    tmp_path, monkeypatch
):
    owned = OwnedTcpRelay(tmp_path, monkeypatch)
    finished = threading.Event()
    errors = []
    connection = http.client.HTTPConnection(*owned.relay.address, timeout=3)

    def request():
        try:
            connection.request("GET", "/pending-owned-test")
            connection.getresponse()
        except (http.client.HTTPException, OSError) as error:
            errors.append(error)
        finally:
            finished.set()
            connection.close()

    caller = threading.Thread(target=request)
    try:
        caller.start()
        backend, _ = owned.listener.accept()
        owned.peers.append(backend)
        backend.settimeout(1)
        assert receive_request_line(backend) == b"GET /pending-owned-test HTTP/1.1"
        assert finished.wait(1)  # Less than the independent caller's three seconds.
        owned.wait_completed(1)
        assert len(errors) == 1
        assert isinstance(errors[0], (http.client.RemoteDisconnected, OSError))
        assert not isinstance(errors[0], TimeoutError)
        owned.relay.assert_healthy()
        assert not owned.errors and owned.relay.connections == 0
    finally:
        settle_owned_test(
            connection.close, owned.close, lambda: join_owned_thread(caller)
        )


@pytest.mark.parametrize("failed_role", ["client", "backend"])
@pytest.mark.parametrize("after", [False, True])
def test_retirement_close_failure_attempts_both_and_retains_owned_slot(
    tmp_path, monkeypatch, failed_role, after
):
    owned = OwnedTcpRelay(tmp_path, monkeypatch)
    owned.fault_close(monkeypatch, failed_role=failed_role, after=after)
    try:
        owned.open()
        owned.wait_completed(1)
        handles = {stream.role: stream for stream in owned.tracked}
        assert set(handles) == {"client", "backend"}
        assert all(stream.attempts == 1 for stream in handles.values())
        assert handles[failed_role] in owned.relay.sockets
        assert (
            handles["backend" if failed_role == "client" else "client"]
            not in owned.relay.sockets
        )
        assert owned.relay.connections == 1
        assert owned.relay.first_origin == ("CONTROL", "OS_OTHER")
        assert owned.relay.failed is True and not owned.errors
        with pytest.raises(RuntimeError, match="transport failed"):
            owned.relay.assert_healthy()
        owned.relay.close()
        assert owned.relay.connections == 1
        assert owned.relay.failed and owned.relay.first_origin == (
            "CONTROL",
            "OS_OTHER",
        )
    finally:
        owned.close()


@pytest.mark.parametrize("pending", [False, True])
def test_idle_close_failure_preserves_prior_or_pending_fatal_origin(
    tmp_path, monkeypatch, pending
):
    owned = OwnedTcpRelay(tmp_path, monkeypatch)
    owned.fault_close(monkeypatch, failed_role="client", after=False)
    entered, release = threading.Event(), threading.Event()
    causal = None
    try:
        owned.open()
        if pending:
            lock = owned.relay.lock

            class PendingMetadata:
                def __enter__(self):
                    if threading.current_thread() is causal:
                        entered.set()
                        assert release.wait(2)
                    lock.acquire()

                def __exit__(self, *_):
                    lock.release()

                def acquire(self, blocking=True):
                    return lock.acquire(blocking=blocking)

                def release(self):
                    lock.release()

            owned.relay.lock = PendingMetadata()
            causal = threading.Thread(
                target=owned.relay._record_failure, args=("RECV", "OS_OTHER")
            )
            causal.start()
            assert entered.wait(1)
            assert owned.relay.failed and owned.relay.first_origin is None
        else:
            owned.relay._record_failure("RECV", "OS_OTHER")
        owned.wait_completed(1)
        assert owned.relay.first_origin == (None if pending else ("RECV", "OS_OTHER"))
        assert all(stream.attempts == 1 for stream in owned.tracked)
        assert owned.relay.connections == 1 and owned.relay.failed
        release.set()
        if causal:
            causal.join(1)
            assert not causal.is_alive()
        assert owned.relay.first_origin == ("RECV", "OS_OTHER")
        assert not owned.errors
    finally:
        release.set()
        if causal:
            causal.join(1)
        owned.close()


def test_stopping_retirement_close_failure_retains_slot_without_failure_metadata(
    tmp_path, monkeypatch
):
    from tests.support import asset_minio

    owned = OwnedTcpRelay(tmp_path, monkeypatch)
    owned.fault_close(monkeypatch, failed_role="client", after=True)

    def stopping_pump(relay, *_):
        with relay.lock:
            relay.state = "STOPPING"
            relay.stop.set()
        raise asset_minio.RelayOriginFailure(
            "PUMP_CUTOFF", "IDLE_CUTOFF", "controlled cutoff"
        )

    monkeypatch.setattr(asset_minio.LoopbackRelay, "_pump", stopping_pump)
    try:
        owned.open()
        owned.wait_completed(1)
        assert all(stream.attempts == 1 for stream in owned.tracked)
        assert owned.relay.connections == 1
        assert owned.relay.failed is False and owned.relay.first_origin is None
        assert (
            next(stream for stream in owned.tracked if stream.role == "client")
            in owned.relay.sockets
        )
        assert not owned.errors
    finally:
        owned.close()


@pytest.mark.parametrize("phase", ["validation", "connect"])
def test_forged_idle_before_forwarding_remains_globally_fatal(
    tmp_path, monkeypatch, phase
):
    from tests.support import asset_minio

    owned = OwnedTcpRelay(tmp_path, monkeypatch)

    def forged(*_):
        raise asset_minio.RelayOriginFailure(
            "PUMP_CUTOFF", "IDLE_CUTOFF", "forged pre-forwarding marker"
        )

    monkeypatch.setattr(
        owned.relay, "validate" if phase == "validation" else "_connect", forged
    )
    try:
        client = owned.socket_type(socket.AF_INET, socket.SOCK_STREAM)
        owned.peers.append(client)
        client.settimeout(1)
        client.connect(owned.relay.address)
        owned.wait_completed(1)
        assert client.recv(1) == b""
        assert owned.relay.failed and owned.relay.first_origin == (
            "PUMP_CUTOFF",
            "IDLE_CUTOFF",
        )
        assert owned.relay.connections == 0 and not owned.errors
    finally:
        owned.close()


@pytest.mark.parametrize(
    "failure", ["matching_text", "unknown", "recv", "send", "half_close", "control"]
)
def test_nonidle_forwarding_faults_remain_globally_fatal(
    tmp_path, monkeypatch, failure
):
    from tests.support import asset_minio

    owned = OwnedTcpRelay(tmp_path, monkeypatch)

    def fault(relay, client, upstream, *_):
        if failure == "matching_text":
            raise RuntimeError("PUMP_CUTOFF IDLE_CUTOFF relay control cutoff")
        if failure == "unknown":
            raise asset_minio.RelayOriginFailure(
                "PUMP_CUTOFF", "UNKNOWN", "controlled unknown cutoff"
            )
        upstream.close()
        stage, operation = {
            "recv": ("RECV", lambda: upstream.recv(1)),
            "send": ("SEND", lambda: upstream.send(b"owned")),
            "half_close": ("HALF_CLOSE", lambda: upstream.shutdown(socket.SHUT_WR)),
            "control": ("CONTROL", lambda: upstream.setblocking(False)),
        }[failure]
        asset_minio.relay_call(stage, operation)

    monkeypatch.setattr(asset_minio.LoopbackRelay, "_pump", fault)
    try:
        owned.open()
        owned.wait_completed(1)
        expected = (
            ("CONTROL", "BUILTIN_RUNTIME")
            if failure == "matching_text"
            else ("PUMP_CUTOFF", "UNKNOWN")
            if failure == "unknown"
            else (
                {
                    "recv": "RECV",
                    "send": "SEND",
                    "half_close": "HALF_CLOSE",
                    "control": "CONTROL",
                }[failure],
                "OS_OTHER",
            )
        )
        assert owned.relay.failed and owned.relay.first_origin == expected
        assert owned.relay.connections == 0 and not owned.errors
        with pytest.raises(RuntimeError, match="transport failed"):
            owned.relay.assert_healthy()
    finally:
        owned.close()


@pytest.mark.parametrize("bound", ["absolute", "tie", "bytes"])
def test_real_owned_absolute_tie_and_byte_bounds_remain_fatal(
    tmp_path, monkeypatch, bound
):
    owned = OwnedTcpRelay(tmp_path, monkeypatch)
    if bound == "absolute":
        owned.relay.ABSOLUTE_SECONDS = 0.1
    elif bound == "tie":
        owned.relay.ABSOLUTE_SECONDS = owned.relay.IDLE_SECONDS
    else:
        owned.relay.MAX_BYTES = 3
    try:
        client, backend = owned.open()
        if bound == "bytes":
            client.sendall(b"overflow")
        owned.wait_completed(1)
        assert client.recv(1) == backend.recv(1) == b""
        expected = (
            ("RECV", "BYTE_LIMIT")
            if bound == "bytes"
            else ("PUMP_CUTOFF", "ABSOLUTE_CUTOFF")
        )
        assert owned.relay.failed and owned.relay.first_origin == expected
        assert owned.relay.connections == 0 and not owned.errors
        assert owned.targets == [("127.0.0.1", 9000)]
    finally:
        owned.close()


def test_relay_validation_failure_retains_first_origin(tmp_path, monkeypatch):
    def refuse(*_):
        raise ValueError("secret-target")

    relay, client, backend, _ = relay_fixture(tmp_path, monkeypatch, refuse)
    try:
        assert receive_eof(client) == b""
        observed = relay.diagnostic_snapshot()
        assert observed["first_stage"] == "VALIDATION"
        assert observed["first_kind"] == "BUILTIN_VALUE"
    finally:
        client.close()
        backend.close()
        relay.close()


def test_relay_first_record_is_concurrent_immutable_and_survives_close(tmp_path):
    from tests.support.asset_minio import LoopbackRelay

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    barrier = threading.Barrier(9)
    origins = [("RECV", "OS_OTHER"), ("SEND", "BUILTIN_VALUE")] * 4

    def record(origin):
        barrier.wait(timeout=1)
        relay._record_failure(*origin)

    workers = [threading.Thread(target=record, args=(origin,)) for origin in origins]
    for worker in workers:
        worker.start()
    barrier.wait(timeout=1)
    for worker in workers:
        worker.join(1)
        assert not worker.is_alive()
    first = relay.first_origin
    assert first in origins and relay.failed is True
    relay._record_failure("CONTROL", "BUILTIN_RUNTIME")
    assert relay.first_origin is first
    relay.close()
    observed = relay.diagnostic_snapshot()
    assert observed["state"] == "CLOSED"
    assert (observed["first_stage"], observed["first_kind"]) == first


def test_relay_admission_is_poisoned_before_metadata_lock_wait(tmp_path):
    from tests.support.asset_minio import LoopbackRelay

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    entered, release = threading.Event(), threading.Event()

    class HeldMetadataLock:
        def __enter__(self):
            entered.set()
            assert release.wait(1)

        def __exit__(self, *_):
            return False

    relay.lock = HeldMetadataLock()
    worker = threading.Thread(target=relay._record_failure, args=("RECV", "OS_OTHER"))
    worker.start()
    try:
        assert entered.wait(0.5)
        assert relay.failed is True
        assert relay.first_origin is None
    finally:
        release.set()
        worker.join(1)
    assert relay.first_origin == ("RECV", "OS_OTHER")


def test_dependent_admission_cannot_mask_pending_worker_origin(tmp_path, monkeypatch):
    from tests.support.asset_minio import LoopbackRelay

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.state = "RUNNING"
    held, poisoned = threading.Event(), threading.Event()
    lock = threading.Lock()
    client = Mock()

    class ObservedLock:
        def __enter__(self):
            if threading.current_thread() is causal:
                poisoned.set()
            lock.acquire()
            if threading.current_thread() is acceptor:
                held.set()
                assert poisoned.wait(1)

        def __exit__(self, *_):
            lock.release()

    calls = []

    def accept():
        calls.append(True)
        if len(calls) == 1:
            return client, None
        relay.stop.set()
        raise OSError("controlled listener close")

    relay.lock = ObservedLock()
    relay.listener = Mock(accept=Mock(side_effect=accept))
    relay.listener_identity = "owned"
    monkeypatch.setattr(relay, "socket_identity", Mock(return_value="owned"))
    acceptor = threading.Thread(target=relay._accept)
    causal = threading.Thread(target=relay._record_failure, args=("RECV", "OS_OTHER"))
    acceptor.start()
    try:
        assert held.wait(0.5)
        causal.start()
        acceptor.join(1)
        causal.join(1)
        assert not acceptor.is_alive() and not causal.is_alive()
        assert relay.failed is True
        assert relay.first_origin == ("RECV", "OS_OTHER")
        client.close.assert_called_once_with()
        assert not relay.sockets and relay.connections == 0
    finally:
        relay.stop.set()
        poisoned.set()
        acceptor.join(1)
        if causal.ident is not None:
            causal.join(1)


def test_dependent_backend_refusal_cannot_mask_pending_worker_origin(tmp_path):
    from tests.support.asset_minio import LoopbackRelay

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.state = "RUNNING"
    relay.connections = 1
    poisoned, release_origin, backend_waiting = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    lock = threading.Lock()
    client = Mock()

    class OrderedLock:
        def __enter__(self):
            if threading.current_thread() is causal:
                poisoned.set()
                assert release_origin.wait(1)
            else:
                backend_waiting.set()
            lock.acquire()

        def __exit__(self, *_):
            lock.release()

    relay.lock = OrderedLock()
    causal = threading.Thread(target=relay._record_failure, args=("RECV", "OS_OTHER"))
    dependent = threading.Thread(target=relay._worker, args=(client, time.monotonic()))
    lock.acquire()
    causal.start()
    try:
        assert poisoned.wait(0.5)
        assert relay.failed is True and relay.first_origin is None
        dependent.start()
        assert backend_waiting.wait(0.5)
    finally:
        lock.release()
    try:
        dependent.join(1)
        assert not dependent.is_alive()
        assert relay.first_origin is None
        client.close.assert_called_once_with()
        assert relay.connections == 0 and not relay.sockets
    finally:
        release_origin.set()
        causal.join(1)
        if dependent.ident is not None:
            dependent.join(1)
    assert not causal.is_alive()
    assert relay.first_origin == ("RECV", "OS_OTHER")


def test_relay_busy_snapshot_returns_without_waiting_for_owned_lock(tmp_path):
    from tests.support.asset_minio import LoopbackRelay, unavailable_relay_snapshot

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    observed, finished = [], threading.Event()

    def snapshot():
        observed.append(relay.diagnostic_snapshot())
        finished.set()

    relay.lock.acquire()
    worker = threading.Thread(target=snapshot)
    worker.start()
    try:
        assert finished.wait(0.5)
        assert observed == [unavailable_relay_snapshot()]
    finally:
        relay.lock.release()
        worker.join(1)
    assert not relay.failed and relay.first_origin is None


@pytest.mark.parametrize("count", [True, 1.0, -1, 4097, None])
def test_relay_snapshot_bounds_counts_and_normalizes_unsafe_labels(tmp_path, count):
    from tests.support.asset_minio import LoopbackRelay

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.connections = count
    relay.state = "secret-state"
    relay.first_origin = ("secret-stage", "secret-kind")
    observed = relay.diagnostic_snapshot()
    assert observed["connections"] is None
    assert (
        observed["state"]
        == observed["first_stage"]
        == observed["first_kind"]
        == "UNKNOWN"
    )
    assert "secret-" not in json.dumps(observed)


def test_relay_snapshot_bounds_all_owned_inventory_counts(tmp_path):
    from tests.support.asset_minio import LoopbackRelay

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.threads = set(range(4097))
    relay.sockets = set(range(4097))
    observed = relay.diagnostic_snapshot()
    assert observed["workers"] is None and observed["sockets"] is None


def test_relay_connect_failure_preserves_native_kind_and_cleanup(tmp_path, monkeypatch):
    from tests.support import asset_minio

    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.state = "RUNNING"
    stream = Mock(connect=Mock(side_effect=TimeoutError("secret-address")))
    monkeypatch.setattr(asset_minio.socket, "socket", Mock(return_value=stream))
    with pytest.raises(asset_minio.RelayOriginFailure) as caught:
        relay._connect(("172.28.0.2", 9000), time.monotonic() + 2)
    assert caught.value.origin == ("CONNECT", "OS_TIMEOUT")
    assert "secret-address" not in str(caught.value)
    stream.close.assert_called_once_with()
    assert not relay.sockets


@pytest.mark.parametrize(
    "stage", ["CONNECT", "PUMP_CUTOFF", "RECV", "SEND", "HALF_CLOSE", "CONTROL"]
)
def test_relay_worker_preserves_typed_failure_origin(tmp_path, stage):
    from tests.support.asset_minio import LoopbackRelay, RelayOriginFailure

    relay = LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.state = "RUNNING"
    relay.connections = 1
    client, upstream = Mock(), Mock()
    relay._connect = Mock(return_value=upstream)
    relay._pump = Mock(
        side_effect=RelayOriginFailure(stage, "OS_OTHER", "fixed failure")
    )
    relay._worker(client, time.monotonic())
    assert relay.first_origin == (stage, "OS_OTHER")
    assert relay.failed and relay.connections == 0
    client.close.assert_called_once_with()
    upstream.close.assert_called_once_with()


@pytest.mark.parametrize("stage", ["RECV", "SEND", "HALF_CLOSE", "CONTROL"])
def test_relay_os_call_origin_uses_fixed_type_and_one_call(stage):
    from tests.support.asset_minio import RelayOriginFailure, relay_call

    operation = Mock(side_effect=OSError("secret-address"))
    with pytest.raises(RelayOriginFailure) as caught:
        relay_call(stage, operation)
    assert caught.value.origin == (stage, "OS_OTHER")
    assert "secret-address" not in str(caught.value)
    operation.assert_called_once_with()


@pytest.mark.parametrize(
    "absolute,idle,expected",
    [
        (200.0, 100.0, "IDLE_CUTOFF"),
        (100.0, 200.0, "ABSOLUTE_CUTOFF"),
        (100.0, 100.0, "ABSOLUTE_CUTOFF"),
    ],
)
def test_pump_cutoff_retains_exact_min_bound(
    tmp_path, monkeypatch, absolute, idle, expected
):
    from tests.support import asset_minio

    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    monkeypatch.setattr(asset_minio.time, "monotonic", Mock(return_value=100.0))
    with pytest.raises(asset_minio.RelayOriginFailure) as caught:
        relay._pump(Mock(), Mock(), absolute, idle)
    assert caught.value.origin == ("PUMP_CUTOFF", expected)


def test_stop_cutoff_retains_branch_without_reading_clock(tmp_path, monkeypatch):
    from tests.support import asset_minio

    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    relay.stop = Mock(is_set=Mock(return_value=True))
    clock = Mock(side_effect=AssertionError("clock must stay short circuited"))
    monkeypatch.setattr(asset_minio.time, "monotonic", clock)
    with pytest.raises(asset_minio.RelayOriginFailure) as caught:
        relay._check_cutoff(100.0)
    assert caught.value.origin == ("CONTROL", "STOPPING_CUTOFF")
    relay.stop.is_set.assert_called_once_with()
    clock.assert_not_called()


@pytest.mark.parametrize(
    "stopped,now,kind,expected",
    [
        (True, 100.0, "IDLE_CUTOFF", "STOPPING_CUTOFF"),
        (False, 99.0, "IDLE_CUTOFF", None),
        (False, 100.0, "IDLE_CUTOFF", "IDLE_CUTOFF"),
        (False, 100.0, "UNKNOWN", "UNKNOWN"),
    ],
)
def test_cutoff_preserves_exact_event_clock_sequence(
    tmp_path, monkeypatch, stopped, now, kind, expected
):
    from tests.support import asset_minio

    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    events = []
    relay.stop = Mock(is_set=Mock(side_effect=lambda: events.append("stop") or stopped))
    clock = Mock(side_effect=lambda: events.append("clock") or now)
    monkeypatch.setattr(asset_minio.time, "monotonic", clock)
    if expected is None:
        relay._check_cutoff(100.0, kind)
    else:
        with pytest.raises(asset_minio.RelayOriginFailure) as caught:
            relay._check_cutoff(100.0, kind)
        assert caught.value.origin == ("CONTROL", expected)
    assert events == (["stop"] if stopped else ["stop", "clock"])


@pytest.mark.parametrize("stage", ["setblocking", "select", "recv", "send", "shutdown"])
@pytest.mark.parametrize("bound_kind", ["idle", "absolute", "tie", "stopping"])
def test_every_late_pump_return_retains_old_bound_and_label(
    tmp_path, monkeypatch, stage, bound_kind
):
    from tests.support import asset_minio

    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    now = [100.0]
    checks, controls, late_pair = [], [], []
    check = relay._check_cutoff

    def observed_check(deadline, kind="UNKNOWN"):
        checks.append((deadline, kind))
        check(deadline, kind)

    def late():
        late_pair.append(checks[-1] if checks else (101.0, "IDLE_CUTOFF"))
        if bound_kind == "stopping":
            relay.stop.set()
        else:
            now[0] = late_pair[-1][0] + 1

    class Stream:
        def __init__(self, name):
            self.name = name

        def setblocking(self, value):
            controls.append((self.name, "setblocking"))
            if stage == "setblocking" and self.name == "client":
                if bound_kind in {"absolute", "tie"}:
                    late_pair.append((101.0, "ABSOLUTE_CUTOFF"))
                    now[0] = 102.0
                else:
                    late()

        def recv(self, size):
            controls.append((self.name, "recv"))
            if stage == "recv":
                late()
            return b"" if stage == "shutdown" else b"queued"

        def send(self, block):
            controls.append((self.name, "send"))
            late()
            return 1

        def shutdown(self, how):
            controls.append((self.name, "shutdown"))
            late()

    client, backend = Stream("client"), Stream("backend")
    readiness_calls = []

    def readiness(*_):
        readiness_calls.append(True)
        controls.append(("pair", "select"))
        if stage == "select":
            late()
        return ([client], [], []) if len(readiness_calls) == 1 else ([], [backend], [])

    absolute, idle = (
        (160.0, 101.0)
        if bound_kind in {"idle", "stopping"}
        else (101.0, 160.0)
        if bound_kind == "absolute"
        else (101.0, 101.0)
    )
    monkeypatch.setattr(relay, "_check_cutoff", observed_check)
    monkeypatch.setattr(asset_minio.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(asset_minio.select, "select", readiness)
    with pytest.raises(asset_minio.RelayOriginFailure) as caught:
        relay._pump(client, backend, absolute, idle)
    expected = (
        "STOPPING_CUTOFF"
        if bound_kind == "stopping"
        else "IDLE_CUTOFF"
        if bound_kind == "idle"
        else "ABSOLUTE_CUTOFF"
    )
    assert caught.value.origin == ("PUMP_CUTOFF", expected)
    assert checks[-1] == late_pair[-1]
    assert controls[-1][1] == stage
    assert sum(control[1] == "send" for control in controls) == (stage == "send")


def test_healthy_intentional_close_does_not_install_stopping_origin(
    tmp_path, monkeypatch
):
    from tests.support import asset_minio

    entered = threading.Event()
    pump = asset_minio.LoopbackRelay._pump

    def observed_pump(self, *args):
        entered.set()
        pump(self, *args)

    monkeypatch.setattr(asset_minio.LoopbackRelay, "_pump", observed_pump)
    relay, client, backend, _ = relay_fixture(tmp_path, monkeypatch)
    try:
        assert entered.wait(1)
        relay.close()
        observed = relay.diagnostic_snapshot()
        assert observed["state"] == "CLOSED" and observed["failed"] is False
        assert observed["first_stage"] == observed["first_kind"] == "UNKNOWN"
        assert (
            observed["connections"] == observed["sockets"] == observed["workers"] == 0
        )
    finally:
        client.close()
        backend.close()
        relay.close()


def test_successful_pump_preserves_whole_control_event_clock_order(
    tmp_path, monkeypatch
):
    from tests.support import asset_minio

    relay = asset_minio.LoopbackRelay(lambda *_: "172.28.0.2", tmp_path)
    events = []
    relay.stop = Mock(is_set=Mock(side_effect=lambda: events.append("stop") or False))
    monkeypatch.setattr(
        asset_minio.time, "monotonic", lambda: events.append("clock") or 100.0
    )

    class Stream:
        def __init__(self, name):
            self.name = name

        def setblocking(self, value):
            events.append(self.name + ".setblocking")
            assert value is False

        def recv(self, size):
            events.append(self.name + ".recv")
            return b""

        def shutdown(self, how):
            events.append(self.name + ".shutdown")
            assert how == socket.SHUT_WR

    client, backend = Stream("client"), Stream("backend")

    def readiness(*_):
        events.append("select")
        return [client, backend], [], []

    monkeypatch.setattr(asset_minio.select, "select", readiness)
    relay._pump(client, backend, 160.0, 110.0)
    assert events == [
        "client.setblocking",
        "stop",
        "clock",
        "backend.setblocking",
        "stop",
        "clock",
        "stop",
        "clock",
        "clock",
        "select",
        "stop",
        "clock",
        "stop",
        "clock",
        "client.recv",
        "stop",
        "clock",
        "stop",
        "clock",
        "backend.shutdown",
        "stop",
        "clock",
        "stop",
        "clock",
        "backend.recv",
        "stop",
        "clock",
        "stop",
        "clock",
        "client.shutdown",
        "stop",
        "clock",
    ]


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
        if bound == "idle":
            relay.assert_healthy()
            assert relay.first_origin is None
        else:
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
