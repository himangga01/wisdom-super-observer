"""Controlled local transport tests; these are not real S3 acceptance."""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID

import pytest


@pytest.fixture
def controlled_http() -> Iterator[tuple[str, dict[str, Any]]]:
    state: dict[str, Any] = {
        "mode": "get",
        "requests": [],
        "received": threading.Event(),
        "release": threading.Event(),
    }

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            state["requests"].append(self.path)
            state["received"].set()
            if state["mode"] == "multipart":
                from urllib.parse import parse_qs, urlsplit
                from xml.sax.saxutils import escape

                from wso_core.storage import object_key

                query = parse_qs(urlsplit(self.path).query)
                limit = int(query["max-uploads"][0])
                state.setdefault("limits", []).append(limit)
                rows = state["uploads"]
                marker = query.get("upload-id-marker", [None])[0]
                start = rows.index(marker) + 1 if marker is not None else 0
                batch = rows[start : start + limit]
                truncated = start + len(batch) < len(rows)
                key = object_key(locator())
                xml = (
                    '<ListMultipartUploadsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>'
                    + str(truncated).lower()
                    + "</IsTruncated>"
                )
                for upload in batch:
                    xml += (
                        "<Upload><Key>"
                        + escape(key)
                        + "</Key><UploadId>"
                        + escape(upload)
                        + "</UploadId><Initiated>2026-09-30T00:00:00Z</Initiated></Upload>"
                    )
                if truncated:
                    xml += (
                        "<NextKeyMarker>"
                        + escape(key)
                        + "</NextKeyMarker><NextUploadIdMarker>"
                        + escape(batch[-1])
                        + "</NextUploadIdMarker>"
                    )
                data = (xml + "</ListMultipartUploadsResult>").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Type", "application/xml")
                self.end_headers()
                self.wfile.write(data)
                return
            if state["mode"] == "redirect":
                self.send_response(301)
                self.send_header("Location", "http://127.0.0.1:1/foreign")
                self.send_header("x-amz-bucket-region", "foreign-region")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", "12")
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            try:
                if state["mode"] == "barrier":
                    state["release"].wait(5)
                    self.wfile.write(b"ciphertext12")
                elif state["mode"] == "drip":
                    for _ in range(12):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.3)
                else:
                    self.wfile.write(b"ciphertext12")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def do_PUT(self) -> None:
            state["received"].set()
            count = int(self.headers["Content-Length"])
            state["put"] = self.rfile.read(count)
            time.sleep(3)
            try:
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

    class ControlledServer(ThreadingHTTPServer):
        def handle_error(self, request: Any, client_address: Any) -> None:
            return  # Expected owned-client termination; no raw transport logs.

    server = ControlledServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()


def runtime(endpoint: str):
    from wso_core.storage import InstallationNamespace, S3Credentials, S3RuntimeConfig

    return S3RuntimeConfig(
        endpoint,
        "us-east-1",
        S3Credentials("fixture-access", "fixture-secret"),
        InstallationNamespace(UUID(int=1), "private-assets"),
        True,
    )


def locator():
    from wso_core.storage import ObjectLocator

    return ObjectLocator(UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4))


def test_real_spawn_sdk_get_and_reaping(controlled_http) -> None:
    from wso_core.asset_process import owned_helper_pids
    from wso_core.storage import IOBudget, S3ObjectStore, SpawnS3Client

    endpoint, state = controlled_http
    ns = runtime(endpoint).namespace
    store = S3ObjectStore(client=SpawnS3Client(config=runtime(endpoint)), namespace=ns)
    with store.get(
        locator(), max_bytes=12, budget=IOBudget(time.monotonic() + 10)
    ) as reader:
        assert reader.read(5) + reader.read(7) == b"ciphertext12"
        assert reader.read(1) == b""
    assert state["received"].is_set()
    assert owned_helper_pids() == ()


def test_absolute_deadline_stops_drip_and_reaps(controlled_http) -> None:
    from wso_core.asset_process import owned_helper_pids
    from wso_core.storage import IOBudget, S3Command, SpawnS3Client, StorageFailure

    endpoint, state = controlled_http
    state["mode"] = "drip"
    start = time.monotonic()
    with pytest.raises(StorageFailure) as failure:
        SpawnS3Client(config=runtime(endpoint)).execute(
            "GET",
            S3Command(locator=locator(), max_bytes=12),
            budget=IOBudget(start + 4),
        )
    assert failure.value.code == "DEADLINE"
    assert not failure.value.outcome_unknown
    assert state["received"].is_set()
    assert time.monotonic() - start < 4.5
    assert owned_helper_pids() == ()


def test_lost_mutation_acknowledgement_is_unknown_and_reaped(controlled_http) -> None:
    from wso_core.asset_process import owned_helper_pids
    from wso_core.storage import IOBudget, S3Command, SpawnS3Client, StorageFailure

    endpoint, state = controlled_http
    with pytest.raises(StorageFailure) as failure:
        SpawnS3Client(config=runtime(endpoint)).execute(
            "PUT",
            S3Command(locator=locator(), body=b"encrypted"),
            budget=IOBudget(time.monotonic() + 4),
        )
    assert failure.value.outcome_unknown
    assert state["put"] == b"encrypted"
    assert "fixture-secret" not in str(failure.value)
    assert owned_helper_pids() == ()


def test_redirect_never_reaches_unapproved_origin(controlled_http) -> None:
    from wso_core.asset_process import owned_helper_pids
    from wso_core.storage import IOBudget, S3Command, SpawnS3Client, StorageFailure

    endpoint, state = controlled_http
    state["mode"] = "redirect"
    with pytest.raises(StorageFailure) as failure:
        SpawnS3Client(config=runtime(endpoint)).execute(
            "GET",
            S3Command(locator=locator(), max_bytes=12),
            budget=IOBudget(time.monotonic() + 10),
        )
    assert failure.value.code == "UNSUPPORTED"
    assert len(state["requests"]) == 1
    assert owned_helper_pids() == ()


def test_ambient_profile_cannot_change_explicit_client(
    controlled_http, monkeypatch
) -> None:
    from wso_core.storage import IOBudget, S3Command, SpawnS3Client

    endpoint, _ = controlled_http
    monkeypatch.setenv("AWS_PROFILE", "no-such-asset-profile")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://127.0.0.1:1")
    assert (
        SpawnS3Client(config=runtime(endpoint)).execute(
            "GET",
            S3Command(locator=locator(), max_bytes=12),
            budget=IOBudget(time.monotonic() + 10),
        )
        == b"ciphertext12"
    )


def incomplete_child(sock: socket.socket) -> None:
    from wso_core.asset_process import child_request

    child_request(sock, 0)
    sock.sendall(struct.pack("!I", 100) + b"{")
    time.sleep(30)


def test_incomplete_ipc_frame_stops_owned_child() -> None:
    from wso_core.asset_process import exchange_owned, owned_helper_pids
    from wso_core.storage import IOBudget, StorageFailure

    start = time.monotonic()
    with pytest.raises(StorageFailure) as failure:
        exchange_owned(
            incomplete_child,
            {},
            b"",
            request_cap=0,
            response_cap=0,
            budget=IOBudget(start + 3),
            mutating=True,
        )
    assert failure.value.code == "DEADLINE"
    assert failure.value.outcome_unknown
    assert owned_helper_pids() == ()


def test_wrong_fields_fail_before_any_child(controlled_http) -> None:
    from wso_core.asset_process import owned_helper_pids
    from wso_core.storage import IOBudget, S3Command, SpawnS3Client, StorageFailure

    endpoint, state = controlled_http
    with pytest.raises(StorageFailure):
        SpawnS3Client(config=runtime(endpoint)).execute(
            "GET",
            S3Command(locator=locator(), body=b"forbidden", max_bytes=12),
            budget=IOBudget(time.monotonic() + 10),
        )
    assert not state["received"].is_set()
    assert owned_helper_pids() == ()


def memory_probe_child(sock: socket.socket) -> None:
    from wso_core.asset_image_worker import _memory_limit
    from wso_core.asset_process import child_request, child_response

    _memory_limit(536870912)
    _, _, deadline = child_request(sock, 0)
    blocked = False
    try:
        allocation = bytearray(600 * 1024 * 1024)
        del allocation
    except MemoryError:
        blocked = True
    child_response(sock, {"blocked": blocked}, b"", 0, deadline)
    sock.close()


def test_kernel_decoder_memory_limit_blocks_allocation() -> None:
    from wso_core.asset_process import exchange_owned, owned_helper_pids
    from wso_core.storage import IOBudget

    control, body = exchange_owned(
        memory_probe_child,
        {},
        b"",
        request_cap=0,
        response_cap=0,
        budget=IOBudget(time.monotonic() + 10),
        mutating=False,
    )
    assert control == {"blocked": True}
    assert body == b""
    assert owned_helper_pids() == ()


def test_parent_cancellation_reaps_owned_child(monkeypatch) -> None:
    import wso_core.asset_process as processes
    from wso_core.storage import IOBudget

    def cancel(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(processes, "receive_frame", cancel)
    with pytest.raises(KeyboardInterrupt):
        processes.exchange_owned(
            incomplete_child,
            {},
            b"",
            request_cap=0,
            response_cap=0,
            budget=IOBudget(time.monotonic() + 5),
            mutating=True,
        )
    assert processes.owned_helper_pids() == ()


def test_local_cleanup_query_ignores_normal_inflight_helper(controlled_http) -> None:
    from wso_core.asset_process import owned_helper_pids
    from wso_core.storage import IOBudget, S3Command, S3ObjectStore, SpawnS3Client

    endpoint, state = controlled_http
    state["mode"] = "barrier"
    client = SpawnS3Client(config=runtime(endpoint))
    store = S3ObjectStore(client=client, namespace=runtime(endpoint).namespace)
    outcome = []

    def read():
        outcome.append(
            client.execute(
                "GET",
                S3Command(locator=locator(), max_bytes=12),
                budget=IOBudget(time.monotonic() + 10),
            )
        )

    thread = threading.Thread(target=read)
    thread.start()
    try:
        assert state["received"].wait(3)
        assert owned_helper_pids()
        assert client.local_cleanup_complete()
        assert store.local_cleanup_complete()
    finally:
        state["release"].set()
        thread.join(5)
    assert not thread.is_alive()
    assert outcome == [b"ciphertext12"]
    assert owned_helper_pids() == ()
    assert client.local_cleanup_complete()
    assert store.local_cleanup_complete()


def test_local_cleanup_query_is_false_for_central_terminal_registry(
    monkeypatch,
) -> None:
    import wso_core.asset_process as processes
    from wso_core.storage import S3ObjectStore, SpawnS3Client

    client = SpawnS3Client(config=runtime("http://127.0.0.1:1"))
    store = S3ObjectStore(
        client=client, namespace=runtime("http://127.0.0.1:1").namespace
    )
    assert client.local_cleanup_complete()
    # Registry is shared by decoder and S3 runners. A synthetic terminal entry
    # proves the query without deliberately leaking a real child process.
    monkeypatch.setattr(processes, "_unreaped", {999: object()})
    assert not client.local_cleanup_complete()
    assert not store.local_cleanup_complete()


class SyntheticProcess:
    pid = 71001
    exitcode = 0

    def __init__(self, *, interrupt_start=False, faults=()):
        self.interrupt_start = interrupt_start
        self.faults = set(faults)
        self.alive = False
        self.calls = []

    def start(self):
        self.alive = True
        self.calls.append("start")
        if self.interrupt_start:
            raise KeyboardInterrupt()

    def is_alive(self):
        self.calls.append("alive")
        if "alive" in self.faults:
            raise OSError("private runtime detail")
        return self.alive

    def terminate(self):
        self.calls.append("terminate")
        if "terminate" in self.faults:
            raise OSError("private runtime detail")
        self.alive = False

    def kill(self):
        self.calls.append("kill")
        if "kill" in self.faults:
            raise OSError("private runtime detail")
        self.alive = False

    def join(self, timeout):
        self.calls.append("join")
        if "join" in self.faults:
            raise OSError("private runtime detail")

    def close(self):
        self.calls.append("close")
        if "close" in self.faults:
            raise OSError("private runtime detail")


def synthetic_runtime(monkeypatch, process):
    import wso_core.asset_process as processes

    monkeypatch.setattr(processes, "_slots", threading.BoundedSemaphore(2))
    monkeypatch.setattr(processes, "_active", set())
    monkeypatch.setattr(processes, "_unreaped", {})
    monkeypatch.setattr(processes, "_owned", {})
    monkeypatch.setattr(
        processes,
        "_OwnedSpawnProcess",
        lambda **kw: process,
    )

    def deadline(*args, **kwargs):
        from wso_core.storage import StorageFailure

        raise StorageFailure("DEADLINE")

    monkeypatch.setattr(processes, "send_frame", deadline)
    return processes


@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("known_pid", [False, True])
def test_interrupted_partial_start_reaps_exact_owned_handle(
    monkeypatch, terminal, known_pid
) -> None:
    from wso_core.storage import IOBudget

    process = SyntheticProcess(
        interrupt_start=True, faults=("terminate", "kill") if terminal else ()
    )
    if not known_pid:
        process.pid = None
    processes = synthetic_runtime(monkeypatch, process)
    with pytest.raises(KeyboardInterrupt):
        processes.exchange_owned(
            incomplete_child,
            {},
            b"",
            request_cap=0,
            response_cap=0,
            budget=IOBudget(time.monotonic() + 5),
            mutating=True,
        )
    assert "terminate" in process.calls
    assert "join" in process.calls
    assert processes.local_cleanup_complete() is not terminal
    assert processes._owned == {}
    if terminal:
        key = process.pid if known_pid else -id(process)
        assert processes._unreaped[key] is process
        assert processes._slots.acquire(blocking=False)
        assert not processes._slots.acquire(blocking=False)
        processes._slots.release()
    else:
        assert not process.alive
        assert processes.owned_helper_pids() == ()
        assert processes._slots.acquire(blocking=False)
        assert processes._slots.acquire(blocking=False)
        processes._slots.release()
        processes._slots.release()


@pytest.mark.parametrize(
    "faults,healthy",
    [
        (("terminate",), True),
        (("join",), False),
        (("terminate", "kill"), False),
        (("alive",), False),
        (("close",), False),
    ],
)
def test_cleanup_faults_are_sanitized_and_preserve_terminal_ownership(
    monkeypatch, faults, healthy
) -> None:
    from wso_core.storage import IOBudget, StorageFailure

    process = SyntheticProcess(faults=faults)
    processes = synthetic_runtime(monkeypatch, process)
    with pytest.raises(StorageFailure) as failure:
        processes.exchange_owned(
            incomplete_child,
            {},
            b"",
            request_cap=0,
            response_cap=0,
            budget=IOBudget(time.monotonic() + 5),
            mutating=True,
        )
    assert failure.value.code in ("DEADLINE", "UNAVAILABLE")
    assert failure.value.outcome_unknown
    assert "private runtime detail" not in str(failure.value)
    assert processes.local_cleanup_complete() is healthy
    if healthy:
        assert not process.alive
        assert processes.owned_helper_pids() == ()
    else:
        assert processes._unreaped[process.pid] is process
        assert processes._slots.acquire(blocking=False)
        assert not processes._slots.acquire(blocking=False)
        processes._slots.release()
        with pytest.raises(StorageFailure):
            processes.exchange_owned(
                incomplete_child,
                {},
                b"",
                request_cap=0,
                response_cap=0,
                budget=IOBudget(time.monotonic() + 5),
                mutating=False,
            )


@pytest.mark.parametrize("terminal", [False, True])
def test_late_start_sends_no_frames_and_retains_exact_ownership(
    monkeypatch, terminal
) -> None:
    from wso_core.storage import IOBudget, StorageFailure

    process = SyntheticProcess(faults=("terminate", "kill") if terminal else ())
    processes = synthetic_runtime(monkeypatch, process)
    clock = [1000.0]
    monkeypatch.setattr(processes.time, "monotonic", lambda: clock[0])

    def late_start():
        process.alive = True
        process.calls.append("start")
        assert processes._owned[id(process)] is process
        clock[0] = 1007.0

    process.start = late_start
    sends = []
    monkeypatch.setattr(processes, "send_frame", lambda *args: sends.append(args))
    with pytest.raises(StorageFailure) as failure:
        processes.exchange_owned(
            incomplete_child,
            {},
            b"",
            request_cap=0,
            response_cap=0,
            budget=IOBudget(1006.0),
            mutating=True,
        )
    assert sends == []
    assert failure.value.code == ("UNAVAILABLE" if terminal else "DEADLINE")
    assert not failure.value.outcome_unknown
    assert processes.local_cleanup_complete() is not terminal
    if terminal:
        assert processes._unreaped[process.pid] is process
        assert processes._slots.acquire(blocking=False)
        assert not processes._slots.acquire(blocking=False)
        processes._slots.release()
    else:
        assert not process.alive
        assert processes.owned_helper_pids() == ()


def test_finite_startup_does_not_reset_transport_budget(monkeypatch) -> None:
    from wso_core.storage import IOBudget, StorageFailure

    process = SyntheticProcess()
    processes = synthetic_runtime(monkeypatch, process)
    clock = [1000.0]
    monkeypatch.setattr(processes.time, "monotonic", lambda: clock[0])

    def finite_start():
        process.alive = True
        clock[0] = 1002.0

    process.start = finite_start
    cutoffs = []

    def send(sock, body, cap, deadline):
        cutoffs.append(deadline)
        raise StorageFailure("DEADLINE")

    monkeypatch.setattr(processes, "send_frame", send)
    with pytest.raises(StorageFailure) as failure:
        processes.exchange_owned(
            incomplete_child,
            {},
            b"",
            request_cap=0,
            response_cap=0,
            budget=IOBudget(1006.0),
            mutating=True,
        )
    assert cutoffs == [1004.0]
    assert failure.value.outcome_unknown
    assert processes.owned_helper_pids() == ()


def test_owned_sdk_multipart_pagination_preserves_all_maximum_ids(
    controlled_http,
) -> None:
    from wso_core.asset_process import owned_helper_pids
    from wso_core.asset_s3_worker import _multipart_page_limit
    from wso_core.storage import IOBudget, S3ObjectStore, SpawnS3Client

    endpoint, state = controlled_http
    state["mode"] = "multipart"
    expected = [chr(0x10000 + index) * 1024 for index in range(7)]
    state["uploads"] = expected
    config = runtime(endpoint)
    store = S3ObjectStore(
        client=SpawnS3Client(config=config), namespace=config.namespace
    )
    cursor = None
    observed = []
    budget = IOBudget(time.monotonic() + 30)
    while True:
        page = store.list_multipart(cursor=cursor, limit=100, budget=budget)
        observed.extend(entry.upload_id for entry in page.items)
        cursor = page.next_cursor
        assert owned_helper_pids() == ()
        if cursor is None:
            break
    assert observed == expected
    assert len(state["limits"]) > 1
    assert max(state["limits"]) == _multipart_page_limit()


def identity_echo_child(sock: socket.socket) -> None:
    import multiprocessing
    import os

    from wso_core.asset_process import child_request, child_response, quiet_child
    from wso_core.storage import CHUNK_BYTES

    quiet_child()
    control, body, deadline = child_request(sock, CHUNK_BYTES + 19)
    assert control == {"operation": "fixture-echo"}
    child_response(
        sock,
        {
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "bootstrap_detached": multiprocessing.current_process()._popen is None,
        },
        body,
        CHUNK_BYTES + 19,
        deadline,
    )
    sock.close()


def daemon_exchange_parent(connection, mode: str) -> None:
    import multiprocessing
    import os

    import wso_core.asset_process as processes
    from wso_core.storage import CHUNK_BYTES, IOBudget, StorageFailure

    processes.quiet_child()
    original_send = processes.send_frame
    custody = []
    native_handles = []
    native_objects = []
    native_closes = set()

    if os.name == "nt":
        original_close = processes._winapi.CloseHandle

        def observed_close(handle):
            with processes._registry_lock:
                owned = [
                    value._popen
                    for value in processes._owned.values()
                    if value._popen is not None
                ]
            retained = [
                value
                for value in owned
                if handle in (value._read_handle, value.sentinel)
            ]
            original_close(handle)
            native_closes.update((id(value), int(handle)) for value in retained)

        processes._winapi.CloseHandle = observed_close

    def record_native(handle):
        if os.name == "nt":
            native_handles.extend(
                (
                    (id(handle._popen), handle._popen._read_handle),
                    (id(handle._popen), handle._popen._handle),
                )
            )
            native_objects.append(handle._popen)

    def observe_send(*args):
        handles = tuple(processes._owned.values())
        assert len(handles) == 1
        custody.append(handles[0].pid)
        record_native(handles[0])
        return original_send(*args)

    processes.send_frame = observe_send
    if mode == "cancel":

        def cancel(*args):
            raise KeyboardInterrupt()

        processes.receive_frame = cancel
    if mode == "kill":

        def refuse_terminate(self):
            raise OSError("private-terminate-error")

        processes._OwnedSpawnProcess.terminate = refuse_terminate
    if mode == "startup-interrupt":
        from billiard import reduction

        original_dump = reduction.dump

        def interrupt_dump(value, stream):
            if isinstance(value, processes._OwnedSpawnProcess):
                record_native(value)
                raise KeyboardInterrupt()
            original_dump(value, stream)

        reduction.dump = interrupt_dump
    started = time.monotonic()
    facts = {"daemon": multiprocessing.current_process().daemon}
    try:
        control, body = processes.exchange_owned(
            identity_echo_child if mode == "echo" else incomplete_child,
            {"operation": "fixture-echo"} if mode == "echo" else {},
            b"x" * (CHUNK_BYTES + 19) if mode == "echo" else b"",
            request_cap=CHUNK_BYTES + 19 if mode == "echo" else 0,
            response_cap=CHUNK_BYTES + 19 if mode == "echo" else 0,
            budget=IOBudget(started + (8 if mode == "echo" else 4)),
            mutating=mode != "echo",
        )
        facts.update(
            exchanged=True,
            direct_child=control["ppid"] == os.getpid(),
            exact_handle=bool(custody) and set(custody) == {control["pid"]},
            frame_bytes=body == b"x" * (CHUNK_BYTES + 19),
            startup_handle_detached=control["bootstrap_detached"],
        )
    except StorageFailure as error:
        facts.update(exchanged=False, code=error.code, unknown=error.outcome_unknown)
    except KeyboardInterrupt:
        facts.update(exchanged=False, code="CANCELLED", dispatched=bool(custody))
    facts.update(
        cleanup_complete=processes.local_cleanup_complete(),
        helpers_empty=processes.owned_helper_pids() == (),
        retained=len(processes._unreaped),
        owned=len(processes._owned),
        elapsed=time.monotonic() - started,
    )
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        get_handle = ctypes.windll.kernel32.GetHandleInformation
        get_handle.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        get_handle.restype = wintypes.BOOL
        flags = wintypes.DWORD()
        # Successful native close plus retained object state proves custody.
        # A later numeric sample cannot identify the original closed object.
        facts["native_handles_closed"] = (
            bool(native_handles)
            and all(handle in native_closes for handle in native_handles)
            and all(
                value._read_handle is None
                and value.sentinel is None
                and value.returncode is not None
                for value in native_objects
            )
        )
        facts["closed_numeric_samples_valid"] = sum(
            bool(get_handle(handle, ctypes.byref(flags)))
            for handle in {value for _identity, value in native_handles}
        )
    connection.send(facts)
    connection.close()


@pytest.mark.parametrize(
    "mode", ["echo", "incomplete", "cancel", "kill", "startup-interrupt"]
)
@pytest.mark.parametrize("parent_backend", ["stdlib", "billiard"])
def test_real_daemon_parent_exchange_has_exact_custody_and_settlement(
    mode, parent_backend
) -> None:
    import multiprocessing
    import os

    import billiard

    if mode == "startup-interrupt" and os.name != "nt":
        pytest.skip("Windows native partial-start custody boundary")

    context = (multiprocessing if parent_backend == "stdlib" else billiard).get_context(
        "spawn"
    )
    receive, send = context.Pipe(duplex=False)
    from wso_core.asset_process import _OwnedSpawnProcess

    process_type = context.Process if parent_backend == "stdlib" else _OwnedSpawnProcess
    parent = process_type(target=daemon_exchange_parent, args=(send, mode), daemon=True)
    started = time.monotonic()
    try:
        parent.start()
        send.close()
        assert receive.poll(11), "bounded owned daemon parent did not report"
        facts = receive.recv()
        parent.join(max(0, 12 - (time.monotonic() - started)))
        assert not parent.is_alive()
        assert parent.exitcode == 0
        print("DAEMON_EXCHANGE " + repr(facts))
        assert facts["daemon"] is True
        assert facts["cleanup_complete"] is True
        assert facts["helpers_empty"] is True
        assert facts["retained"] == facts["owned"] == 0
        if os.name == "nt":
            assert facts["native_handles_closed"] is True
        if mode == "echo":
            assert facts["exchanged"] is True
            assert (
                facts["direct_child"] and facts["exact_handle"] and facts["frame_bytes"]
            )
            assert facts["elapsed"] < 8
            assert facts["startup_handle_detached"] is True
        elif mode == "cancel":
            assert facts["code"] == "CANCELLED" and facts["dispatched"] is True
            assert facts["elapsed"] < 4.5
        elif mode == "startup-interrupt":
            assert facts["code"] == "CANCELLED" and facts["dispatched"] is False
            assert facts["elapsed"] < 4.5
        else:
            assert facts["exchanged"] is False
            assert facts["code"] == "DEADLINE" and facts["unknown"] is True
            assert facts["elapsed"] < 4.5
    finally:
        receive.close()
        send.close()
        if parent.pid is not None:
            if parent.is_alive():
                parent.terminate()
            parent.join(1)
            if parent.is_alive():
                parent.kill()
                parent.join(1)
            assert not parent.is_alive()
        parent.close()
