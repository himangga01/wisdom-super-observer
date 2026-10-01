"""Pinned official artifact and secret-file bootstrap support, not S3 acceptance."""

from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import os
import platform
import select
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

SERVER_VERSION = "RELEASE.2025-04-22T22-12-26Z"
SERVER_SHA = "53e2a2cb16c5366ea6fbbc479c19ddb4c6a0948273e752f740fb1fbf27bb817c"
SERVER_COMMIT = "0d7408fc9969caf07de6a8c3a84f9fbb10a6739e"
CLIENT_VERSION = "RELEASE.2025-04-16T18-13-26Z"
CLIENT_SHA = "ac90da87a35641be5a0ac75d49de5161ddb47d629b5ba01261b0ae9e00aea15f"
CLIENT_COMMIT = "b00526b153a31b36767991a4f5ce2cced435ee8e"
ARTIFACTS = {
    "minio": ("minio", SERVER_VERSION, SERVER_SHA, SERVER_COMMIT, 118849720),
    "mc": ("mc", CLIENT_VERSION, CLIENT_SHA, CLIENT_COMMIT, 30179512),
}
LOCAL_DOCKER_ENDPOINT = "unix:///var/run/docker.sock"

EXCEPTION_TYPES = {
    httpx.ReadTimeout: "HTTPX_READ_TIMEOUT",
    httpx.ConnectTimeout: "HTTPX_CONNECT_TIMEOUT",
    httpx.WriteTimeout: "HTTPX_WRITE_TIMEOUT",
    httpx.PoolTimeout: "HTTPX_POOL_TIMEOUT",
    httpx.ConnectError: "HTTPX_CONNECT_ERROR",
    httpx.ReadError: "HTTPX_READ_ERROR",
    httpx.WriteError: "HTTPX_WRITE_ERROR",
    httpx.RemoteProtocolError: "HTTPX_REMOTE_PROTOCOL_ERROR",
    httpx.LocalProtocolError: "HTTPX_LOCAL_PROTOCOL_ERROR",
    httpx.DecodingError: "HTTPX_DECODING_ERROR",
    httpx.UnsupportedProtocol: "HTTPX_UNSUPPORTED_PROTOCOL",
    TypeError: "BUILTIN_TYPE",
    ValueError: "BUILTIN_VALUE",
    AssertionError: "BUILTIN_ASSERTION",
    AttributeError: "BUILTIN_ATTRIBUTE",
    KeyError: "BUILTIN_KEY",
    IndexError: "BUILTIN_INDEX",
    NameError: "BUILTIN_NAME",
    UnboundLocalError: "BUILTIN_NAME",
    RuntimeError: "BUILTIN_RUNTIME",
}
EXCEPTION_KINDS = frozenset(EXCEPTION_TYPES.values()) | {
    "HTTPX_OTHER",
    "OS_TIMEOUT",
    "OS_OTHER",
    "UNKNOWN",
}
RELAY_STAGES = frozenset(
    {
        "ADMISSION",
        "VALIDATION",
        "CONNECT",
        "PUMP_CUTOFF",
        "RECV",
        "SEND",
        "HALF_CLOSE",
        "CONTROL",
        "UNKNOWN",
    }
)
RELAY_KINDS = EXCEPTION_KINDS | {
    "IDLE_CUTOFF",
    "ABSOLUTE_CUTOFF",
    "STOPPING_CUTOFF",
    "BYTE_LIMIT",
}


def exception_kind(error):
    known = EXCEPTION_TYPES.get(type(error))
    if known is not None:
        return known
    if isinstance(error, httpx.HTTPError):
        return "HTTPX_OTHER"
    if isinstance(error, TimeoutError):
        return "OS_TIMEOUT"
    if isinstance(error, OSError):
        return "OS_OTHER"
    return "UNKNOWN"


def fixed_label(value, choices):
    return value if type(value) is str and value in choices else "UNKNOWN"


def unavailable_relay_snapshot():
    return {
        "available": False,
        "state": "UNKNOWN",
        "failed": None,
        "connections": None,
        "sockets": None,
        "workers": None,
        "first_stage": "UNKNOWN",
        "first_kind": "UNKNOWN",
    }


def normalize_relay_snapshot(value, *, strict=True):
    """Pure closed-schema copy; no unsafe object participates in serialization."""
    unavailable = unavailable_relay_snapshot()
    if type(value) is not dict:
        return unavailable
    keys = tuple(value)
    if (
        any(type(key) is not str for key in keys)
        or set(keys) != set(unavailable)
        or value["available"] is not True
    ):
        return unavailable

    def valid_count(item):
        return item is None or (type(item) is int and 0 <= item <= 4096)

    def count(item):
        return item if type(item) is int and 0 <= item <= 4096 else None

    states = {"RUNNING", "STOPPING", "CLOSED", "UNKNOWN"}
    valid = (
        type(value["state"]) is str
        and value["state"] in states
        and (value["failed"] is None or type(value["failed"]) is bool)
        and all(
            valid_count(value[key]) for key in ("connections", "sockets", "workers")
        )
        and type(value["first_stage"]) is str
        and value["first_stage"] in RELAY_STAGES
        and type(value["first_kind"]) is str
        and value["first_kind"] in RELAY_KINDS
    )
    if strict and not valid:
        return unavailable
    return {
        "available": True,
        "state": fixed_label(value["state"], states),
        "failed": value["failed"] if type(value["failed"]) is bool else None,
        "connections": count(value["connections"]),
        "sockets": count(value["sockets"]),
        "workers": count(value["workers"]),
        "first_stage": fixed_label(value["first_stage"], RELAY_STAGES),
        "first_kind": fixed_label(value["first_kind"], RELAY_KINDS),
    }


class RelayOriginFailure(RuntimeError):
    def __init__(self, stage, kind, message):
        super().__init__(message)
        self.origin = (fixed_label(stage, RELAY_STAGES), fixed_label(kind, RELAY_KINDS))


class RelayPoisonRefusal(RuntimeError):
    """Dependent refusal preserves the already-pending failure's origin."""


def relay_call(stage, operation):
    try:
        return operation()
    except RelayOriginFailure as error:
        message = (
            "relay control cutoff"
            if stage == "PUMP_CUTOFF"
            else "owned relay control failed"
        )
        raise RelayOriginFailure(stage, error.origin[1], message) from None
    except Exception as error:  # noqa: BLE001 -- fixed type classification only
        raise RelayOriginFailure(
            stage, exception_kind(error), "owned relay operation failed"
        ) from None


class RelayCommands:
    """Exact inspect child handles, bounded streams and cancellation ownership."""

    MAX_CAPTURE = 1048576

    def __init__(self, stop):
        self.stop = stop
        self.lock = threading.Lock()
        self.records = {}

    @contextmanager
    def registry(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self.lock.acquire(timeout=remaining):
            raise RuntimeError("owned relay command registry cutoff")
        try:
            if time.monotonic() >= deadline:
                raise RuntimeError("owned relay command registry cutoff")
            yield
            if time.monotonic() >= deadline:
                raise RuntimeError("owned relay command registry cutoff")
        finally:
            self.lock.release()

    def run(self, command, environment, deadline):
        record = {"process": None, "creation_finished": False}
        identity = id(record)
        process = None
        try:
            with self.registry(deadline):
                if self.stop.is_set() or time.monotonic() >= deadline:
                    raise RuntimeError("relay validation cancelled")
                self.records[identity] = record
            # Record pending creation first; no lifecycle lock spans OS creation.
            process = subprocess.Popen(
                command,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            record["process"] = process
            streams = [process.stdout, process.stderr]
            buffers = [bytearray(), bytearray()]
            for stream in streams:
                os.set_blocking(stream.fileno(), False)
            remaining = {0, 1}
            while remaining or process.poll() is None:
                if self.stop.is_set() or time.monotonic() >= deadline:
                    raise RuntimeError("relay validation cutoff")
                for index in tuple(remaining):
                    try:
                        block = os.read(
                            streams[index].fileno(),
                            min(65536, self.MAX_CAPTURE - len(buffers[index]) + 1),
                        )
                    except BlockingIOError:
                        continue
                    if not block:
                        remaining.remove(index)
                    elif len(buffers[index]) + len(block) > self.MAX_CAPTURE:
                        raise RuntimeError("relay validation capture bound")
                    else:
                        buffers[index].extend(block)
                self.stop.wait(min(0.01, max(0, deadline - time.monotonic())))
            if self.stop.is_set() or time.monotonic() >= deadline or process.returncode:
                raise RuntimeError("relay validation refused")
            return json.loads(buffers[0])
        except (OSError, ValueError, subprocess.SubprocessError, RuntimeError):
            raise RuntimeError("owned relay inspect failed") from None
        finally:
            # Admission's post-check may fail after insertion but before Popen.
            # Only this producer can publish that no future creation is possible.
            # A missed operation cutoff leaves this fact for bounded later cleanup.
            record["process"] = process
            record["creation_finished"] = True
            if process is not None:
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass  # Keep exact unsettled ownership for guarded cleanup.
                if process.poll() is not None:
                    for stream in (process.stdout, process.stderr):
                        if stream:
                            stream.close()
                    with self.registry(deadline):
                        self.records.pop(identity, None)

    def cancel(self, deadline):
        # Pending creations remain registered until their owning worker settles.
        while True:
            with self.registry(deadline):
                records = list(self.records.items())
            for identity, record in records:
                process = record["process"]
                if process is None:
                    if record.get("creation_finished") is True:
                        with self.registry(deadline):
                            # Recheck after locking: never discard a concurrently
                            # published exact handle or a genuinely live creator.
                            if (
                                record["process"] is None
                                and record.get("creation_finished") is True
                            ):
                                self.records.pop(identity, None)
                    continue
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass
                if process.poll() is not None:
                    for stream in (process.stdout, process.stderr):
                        if stream:
                            stream.close()
                    with self.registry(deadline):
                        self.records.pop(identity, None)
            with self.registry(deadline):
                if not self.records:
                    return
            if time.monotonic() >= deadline:
                raise RuntimeError("owned relay child cleanup unsettled")
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))


class LoopbackRelay:
    """Fixture-only opaque forwarding; validator supplies the pinned numeric target."""

    MAX_CONNECTIONS = 16
    MAX_BUFFER = 65536
    MAX_BYTES = 67108864
    IDLE_SECONDS = 10
    ABSOLUTE_SECONDS = 60
    VALIDATION_SECONDS = 2
    CONNECT_SECONDS = 2
    CLEANUP_SECONDS = 3

    def __init__(self, validate, directory):
        self.validate = validate
        self.directory = Path(directory)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.commands = RelayCommands(self.stop)
        self.threads = set()
        self.sockets = set()
        self.connections = 0
        self.failed = False
        self.state = "NEW"
        self.listener = None
        self.first_origin = None

    def _record_failure(self, stage, kind, *, locked=False):
        # Preserve the original admission poison before synchronizing metadata.
        self.failed = True

        def record():
            if self.first_origin is None:
                self.first_origin = (
                    fixed_label(stage, RELAY_STAGES),
                    fixed_label(kind, RELAY_KINDS),
                )

        if locked:
            record()
        else:
            with self.lock:
                record()

    def diagnostic_snapshot(self):
        if not self.lock.acquire(blocking=False):
            return unavailable_relay_snapshot()
        try:

            def count(value):
                return value if type(value) is int and 0 <= value <= 4096 else None

            origin = self.first_origin
            if type(origin) is not tuple or len(origin) != 2:
                origin = ("UNKNOWN", "UNKNOWN")
            return {
                "available": True,
                "state": fixed_label(self.state, {"RUNNING", "STOPPING", "CLOSED"}),
                "failed": self.failed if type(self.failed) is bool else None,
                "connections": count(self.connections),
                "sockets": count(len(self.sockets)),
                "workers": count(len(self.threads)),
                "first_stage": fixed_label(origin[0], RELAY_STAGES),
                "first_kind": fixed_label(origin[1], RELAY_KINDS),
            }
        finally:
            self.lock.release()

    @property
    def live_threads(self):
        with self.lock:
            return tuple(thread for thread in self.threads if thread.is_alive())

    @property
    def active_sockets(self):
        with self.lock:
            return tuple(self.sockets)

    @staticmethod
    def socket_identity(stream):
        identity = (id(stream), stream.fileno(), stream.getsockname())
        if sys.platform == "linux":
            observed = os.fstat(stream.fileno())
            if not stat.S_ISSOCK(observed.st_mode):
                raise RuntimeError("relay listener identity differs")
            identity += (observed.st_dev, observed.st_ino)
        return identity

    def _check_cutoff(self, deadline, kind="UNKNOWN"):
        if self.stop.is_set():
            raise RelayOriginFailure(
                "CONTROL", "STOPPING_CUTOFF", "relay control cutoff"
            )
        if time.monotonic() >= deadline:
            raise RelayOriginFailure(
                "CONTROL",
                fixed_label(kind, {"IDLE_CUTOFF", "ABSOLUTE_CUTOFF"}),
                "relay control cutoff",
            )

    def start(self, *, deadline):
        with self.lock:
            if self.state != "NEW":
                raise RuntimeError("relay cannot restart")
            listener = None
            try:
                self._check_cutoff(deadline)
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.listener = listener
                self.sockets.add(listener)
                self._check_cutoff(deadline)
                listener.bind(("127.0.0.1", 0))
                self._check_cutoff(deadline)
                listener.listen(self.MAX_CONNECTIONS)
                self._check_cutoff(deadline)
                listener.settimeout(0.1)
                self._check_cutoff(deadline)
                self.address = listener.getsockname()
                self._check_cutoff(deadline)
                if self.address[0] != "127.0.0.1" or not 0 < self.address[1] < 65536:
                    raise RuntimeError("relay loopback binding differs")
                self.listener_identity = self.socket_identity(listener)
                self._check_cutoff(deadline)
                acceptor = threading.Thread(
                    target=self._accept, name="owned-asset-relay"
                )
                self._check_cutoff(deadline)
                self.threads.add(acceptor)
                self.state = "RUNNING"
                acceptor.start()
                self._check_cutoff(deadline)
            except Exception as error:  # noqa: BLE001 -- retain all partial startup ownership
                kind = (
                    error.origin[1]
                    if isinstance(error, RelayOriginFailure)
                    else exception_kind(error)
                )
                self._record_failure("CONTROL", kind, locked=True)
                self.state = "STOPPING"
                self.stop.set()
                if listener is not None:
                    listener.close()
                    self.sockets.discard(listener)
                raise RuntimeError("owned relay startup failed") from None

    def _accept(self):
        while not self.stop.is_set():
            phase = "CONTROL"
            try:
                if self.socket_identity(self.listener) != self.listener_identity:
                    raise RuntimeError("relay listener identity differs")
                phase = "ADMISSION"
                client, _ = self.listener.accept()
            except TimeoutError:
                continue
            except (OSError, RuntimeError) as error:
                if not self.stop.is_set():
                    self._record_failure(phase, exception_kind(error))
                return
            accepted = time.monotonic()
            with self.lock:
                # Reserve the slot/socket before any validation or worker creation.
                if (
                    self.state != "RUNNING"
                    or self.failed
                    or self.connections >= self.MAX_CONNECTIONS
                ):
                    client.close()
                    if self.state == "RUNNING" and not self.failed:
                        self._record_failure("ADMISSION", "UNKNOWN", locked=True)
                    continue
                for thread in tuple(self.threads):
                    if not thread.is_alive():
                        if thread.ident is not None:
                            thread.join(0)
                        self.threads.discard(thread)
                self.sockets.add(client)
                self.connections += 1
                worker = threading.Thread(
                    target=self._worker,
                    args=(client, accepted),
                    name="owned-asset-connection",
                )
                self.threads.add(worker)
                try:
                    worker.start()
                except RuntimeError as error:
                    self._record_failure(
                        "ADMISSION", exception_kind(error), locked=True
                    )
                    client.close()
                    self.sockets.discard(client)
                    self.connections -= 1

    def _register_backend(self):
        with self.lock:
            if self.state != "RUNNING" or self.failed or self.stop.is_set():
                if self.failed:
                    raise RelayPoisonRefusal("relay stopped before connect")
                raise RuntimeError("relay stopped before connect")
            stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sockets.add(stream)
            return stream

    def _connect(self, target, deadline):
        connect_cutoff = min(deadline, time.monotonic() + self.CONNECT_SECONDS)
        stream = self._register_backend()
        try:
            self._check_cutoff(connect_cutoff)
            stream.settimeout(connect_cutoff - time.monotonic())
            self._check_cutoff(connect_cutoff)
            stream.connect(target)
            self._check_cutoff(connect_cutoff)
            return stream
        except Exception as error:  # noqa: BLE001 -- close registered socket; expose no raw details
            stream.close()
            with self.lock:
                self.sockets.discard(stream)
            kind = (
                error.origin[1]
                if isinstance(error, RelayOriginFailure)
                else exception_kind(error)
            )
            raise RelayOriginFailure(
                "CONNECT", kind, "owned relay connect failed"
            ) from None

    def _worker(self, client, accepted):
        upstream = None
        phase = "VALIDATION"
        forwarding = False
        try:
            absolute = accepted + self.ABSOLUTE_SECONDS
            initial_idle = accepted + self.IDLE_SECONDS
            cutoff = min(
                absolute, initial_idle, time.monotonic() + self.VALIDATION_SECONDS
            )
            address = self.validate(cutoff, self.stop, self.commands)
            ipaddress.IPv4Address(address)  # Numeric only; no resolver/fallback.
            if self.stop.is_set() or time.monotonic() >= cutoff:
                raise RelayOriginFailure(
                    "VALIDATION", "UNKNOWN", "relay validation cutoff"
                )
            phase = "CONNECT"
            upstream = self._connect((address, 9000), min(absolute, initial_idle))
            phase = "CONTROL"
            with self.lock:
                if self.state != "RUNNING" or self.stop.is_set():
                    raise RuntimeError("relay stopped before forwarding")
                self.sockets.add(upstream)
            forwarding = True
            self._pump(client, upstream, absolute, initial_idle)
        except Exception as error:  # noqa: BLE001 -- poison transport and settle exact handles
            if not self.stop.is_set() and not isinstance(error, RelayPoisonRefusal):
                retiring = (
                    forwarding
                    and isinstance(error, RelayOriginFailure)
                    and error.origin == ("PUMP_CUTOFF", "IDLE_CUTOFF")
                )
                if not retiring:
                    stage, kind = (
                        error.origin
                        if isinstance(error, RelayOriginFailure)
                        else (phase, exception_kind(error))
                    )
                    self._record_failure(stage, kind)
        finally:
            settled = True
            for stream in (client, upstream):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception as error:  # noqa: BLE001 -- retain exact unresolved ownership
                        settled = False
                        if (
                            self.state == "RUNNING"
                            and not self.stop.is_set()
                            and not self.failed
                        ):
                            # An already-published pending fatal owns the first origin.
                            self._record_failure("CONTROL", exception_kind(error))
                    else:
                        with self.lock:
                            self.sockets.discard(stream)
            if settled:
                with self.lock:
                    self.connections -= 1

    def _pump(self, client, upstream, absolute, idle):
        streams = [client, upstream]
        queues = [bytearray(), bytearray()]
        eof = [False, False]
        half_closed = [False, False]
        total = 0

        def bound():
            # Absolute owns a numeric tie; label travels with the old deadline.
            return min(absolute, idle), (
                "ABSOLUTE_CUTOFF" if absolute <= idle else "IDLE_CUTOFF"
            )

        def check(deadline, kind):
            relay_call("PUMP_CUTOFF", lambda: self._check_cutoff(deadline, kind))

        for stream in streams:
            relay_call("CONTROL", lambda stream=stream: stream.setblocking(False))
            check(*bound())
        while not all(half_closed):
            cutoff, kind = bound()
            check(cutoff, kind)
            readers = [
                streams[i]
                for i in range(2)
                if not eof[i] and len(queues[i]) < self.MAX_BUFFER
            ]
            writers = [streams[1 - i] for i in range(2) if queues[i]]
            readable, writable, _ = relay_call(
                "CONTROL",
                lambda readers=readers, writers=writers, cutoff=cutoff: select.select(
                    readers,
                    writers,
                    [],
                    min(0.05, max(0, cutoff - time.monotonic())),
                ),
            )
            check(cutoff, kind)
            for i in range(2):
                if streams[i] in readable:
                    cutoff, kind = bound()
                    check(cutoff, kind)
                    block = relay_call(
                        "RECV",
                        lambda i=i: streams[i].recv(self.MAX_BUFFER - len(queues[i])),
                    )
                    check(cutoff, kind)
                    if block:
                        if total + len(block) > self.MAX_BYTES:
                            raise RelayOriginFailure(
                                "RECV", "BYTE_LIMIT", "relay byte bound"
                            )
                        queues[i].extend(block)
                        total += len(block)
                        idle = time.monotonic() + self.IDLE_SECONDS
                    else:
                        eof[i] = True
                if queues[i] and streams[1 - i] in writable:
                    cutoff, kind = bound()
                    check(cutoff, kind)
                    sent = relay_call(
                        "SEND", lambda i=i: streams[1 - i].send(queues[i])
                    )
                    check(cutoff, kind)
                    if sent <= 0:
                        raise RelayOriginFailure("SEND", "UNKNOWN", "relay send failed")
                    del queues[i][:sent]
                    idle = time.monotonic() + self.IDLE_SECONDS
                if eof[i] and not queues[i] and not half_closed[i]:
                    cutoff, kind = bound()
                    check(cutoff, kind)
                    relay_call(
                        "HALF_CLOSE",
                        lambda i=i: streams[1 - i].shutdown(socket.SHUT_WR),
                    )
                    check(cutoff, kind)
                    half_closed[i] = True

    def assert_healthy(self):
        if self.failed or self.state != "RUNNING" or self.stop.is_set():
            raise RuntimeError("owned relay transport failed")
        if self.socket_identity(self.listener) != self.listener_identity:
            raise RuntimeError("owned relay transport failed")

    def close(self, *, deadline=None):
        deadline = min(
            time.monotonic() + self.CLEANUP_SECONDS,
            deadline if deadline is not None else float("inf"),
        )
        self.stop.set()
        if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise RuntimeError("owned relay cleanup lock unsettled")
        try:
            self.state = "STOPPING"
            streams = tuple(self.sockets)
            threads = tuple(self.threads)
        finally:
            self.lock.release()
        socket_failure = False
        for stream in streams:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                stream.close()
            except OSError:
                socket_failure = True
        command_failure = None
        try:
            self.commands.cancel(deadline)
        except Exception as error:  # noqa: BLE001 -- still join owned relay threads.
            command_failure = error
        for thread in threads:
            if thread.ident is not None:
                thread.join(max(0, deadline - time.monotonic()))
        if (
            socket_failure
            or command_failure is not None
            or any(thread.is_alive() for thread in threads)
            or self.commands.records
            or time.monotonic() >= deadline
        ):
            raise RuntimeError("owned relay cleanup unsettled")
        if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise RuntimeError("owned relay cleanup lock unsettled")
        try:
            if time.monotonic() >= deadline:
                raise RuntimeError("owned relay cleanup cutoff")
            self.sockets.clear()
            self.threads.clear()
            self.state = "CLOSED"
        finally:
            self.lock.release()


def verify_private_path(path, mode):
    observed = Path(path).lstat()
    expected_type = stat.S_ISDIR if mode == 0o700 else stat.S_ISREG
    if (
        not expected_type(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != mode
        or observed.st_uid != os.getuid()
    ):
        raise RuntimeError("owned Docker CLI config identity/mode differs")


def local_socket_identity():
    try:
        observed = Path("/var/run/docker.sock").lstat()
        if not stat.S_ISSOCK(observed.st_mode) or observed.st_uid != 0:
            raise ValueError
        return observed.st_dev, observed.st_ino, observed.st_uid
    except (OSError, ValueError):
        raise RuntimeError(
            "required local root-owned Docker socket unavailable"
        ) from None


class LocalDocker:
    """Fixed local socket and owned empty CLI config; never ambient contexts."""

    def __init__(self, directory):
        require_linux_ci()
        self.directory = Path(directory)
        self.config = self.directory / "docker-config"
        self.config.mkdir(mode=0o700)
        private_file(self.config / "config.json", b"{}")
        self.socket = local_socket_identity()
        self.environment = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL", "TZ")
            if key in os.environ
        }
        self.environment.update(
            HOME=str(self.directory),
            TMPDIR=str(self.directory),
            DOCKER_CONFIG=str(self.config),
        )

    def command(self, *arguments):
        for path, mode in (
            (self.directory, 0o700),
            (self.config, 0o700),
            (self.config / "config.json", 0o600),
        ):
            verify_private_path(path, mode)
        if (self.config / "config.json").read_bytes() != b"{}":
            raise RuntimeError("owned Docker CLI configuration changed")
        if local_socket_identity() != self.socket:
            raise RuntimeError("local Docker socket identity changed")
        return (
            [
                "docker",
                "--config",
                str(self.config),
                "--host",
                LOCAL_DOCKER_ENDPOINT,
                *arguments,
            ],
            dict(self.environment),
        )


def require_linux_ci():
    if (
        sys.platform != "linux"
        or os.environ.get("CI") != "true"
        or platform.machine() not in {"x86_64", "amd64"}
    ):
        raise RuntimeError("MinIO provisioning requires explicit Linux amd64 CI")
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT") not in {
        None,
        "default",
    }:
        raise RuntimeError("remote Docker fixture target forbidden")


def validate_download_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname
        not in {
            "github.com",
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
        }
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise RuntimeError("official artifact redirect refused")


def validate_artifact(length, digest, expected_length, expected_digest):
    if length != expected_length or digest != expected_digest:
        raise RuntimeError("official artifact byte length/hash mismatch")


def download_artifact(directory, name):
    require_linux_ci()
    repository, version, digest, _, size = ARTIFACTS[name]
    target = Path(directory) / name
    url = f"https://github.com/minio/{repository}/releases/download/{version}/{name}.linux-amd64.{version}"
    started = time.monotonic()
    created = False
    try:
        with httpx.Client(
            timeout=20, trust_env=False, follow_redirects=False
        ) as client:
            for _ in range(6):
                validate_download_url(url)
                with client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    if response.status_code != 200:
                        raise RuntimeError("official artifact unavailable")
                    descriptor = os.open(
                        target,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                        0o600,
                    )
                    created = True
                    hashed = hashlib.sha256()
                    length = 0
                    with os.fdopen(descriptor, "wb") as output:
                        for chunk in response.iter_bytes(65536):
                            length += len(chunk)
                            if length > size or time.monotonic() - started > 180:
                                raise RuntimeError(
                                    "official artifact download bound exceeded"
                                )
                            hashed.update(chunk)
                            output.write(chunk)
                    validate_artifact(length, hashed.hexdigest(), size, digest)
                    os.chmod(target, 0o700)  # Only verified bytes become executable.
                    return target
            raise RuntimeError("official artifact redirect bound exceeded")
    except (OSError, httpx.HTTPError, RuntimeError):
        if created:
            target.unlink(missing_ok=True)
        raise RuntimeError("official artifact acquisition failed") from None


def private_file(path, data):
    descriptor = os.open(
        path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def safe_run(arguments, directory, *, timeout=30):
    """No raw subprocess output escapes; mc gets no ambient aliases/credentials."""
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TZ")
        if key in os.environ
    }
    environment.update({"HOME": str(directory), "TMPDIR": str(directory)})
    try:
        with (
            tempfile.TemporaryFile(dir=directory) as stdout,
            tempfile.TemporaryFile(dir=directory) as stderr,
        ):
            result = subprocess.run(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=environment,
                timeout=timeout,
                check=False,
            )
            if result.returncode or stdout.tell() > 1048576 or stderr.tell() > 1048576:
                raise RuntimeError("owned bootstrap command failed")
            stdout.seek(0)
            return stdout.read(1048577).decode("utf-8")
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise RuntimeError("owned bootstrap command failed") from None


def verify_binary_version(path, name, directory):
    require_linux_ci()
    _, version, _, commit, _ = ARTIFACTS[name]
    output = safe_run([str(path), "--version"], directory)
    first = output.splitlines()[0] if output else ""
    if first != f"{name} version {version} (commit-id={commit})":
        raise RuntimeError("observed executable version/commit differs from pin")


def validate_import_result(raw, credentials):
    def no_duplicates(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate field")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=no_duplicates)
        if not isinstance(value, dict) or set(value) - {
            "added",
            "skipped",
            "removed",
            "failed",
        }:
            raise ValueError
        allowed = {
            "policies",
            "users",
            "groups",
            "serviceAccounts",
            "userPolicies",
            "groupPolicies",
            "stsPolicies",
        }
        for section in ("skipped", "removed", "failed"):
            entries = value.get(section, {})
            if (
                not isinstance(entries, dict)
                or set(entries) - allowed
                or any(item != [] for item in entries.values())
            ):
                raise ValueError
        added = value["added"]
        if not isinstance(added, dict) or set(added) != {
            "policies",
            "users",
            "userPolicies",
        }:
            raise ValueError
        users = [credentials[name][0] for name in ("gateway", "cleanup")]
        for field in ("users", "policies"):
            if not isinstance(added[field], list) or not all(
                isinstance(item, str) for item in added[field]
            ):
                raise ValueError
        if sorted(added["users"]) != sorted(users) or sorted(added["policies"]) != [
            "wso-gateway",
            "wso-maintenance",
        ]:
            raise ValueError
        mappings = added["userPolicies"]
        expected = [{users[0]: ["wso-gateway"]}, {users[1]: ["wso-maintenance"]}]
        if (
            not isinstance(mappings, list)
            or len(mappings) != 2
            or any(item not in mappings for item in expected)
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("exact IAM import result could not be established") from None


def iam_archive_bytes(credentials, policies):
    users = {
        credentials[name][0]: {"secretKey": credentials[name][1], "status": "enabled"}
        for name in ("gateway", "cleanup")
    }
    mappings = {
        credentials[name][0]: {"version": 1, "policy": policy}
        for name, policy in (("gateway", "wso-gateway"), ("cleanup", "wso-maintenance"))
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        for name, content in (
            ("policies", policies),
            ("users", users),
            ("user_mappings", mappings),
        ):
            zipped.writestr(f"iam-assets/{name}.json", json.dumps(content).encode())
    return stream.getvalue()


def provision_users(directory, endpoint, credentials, policies):
    require_linux_ci()
    config = Path(directory) / "mc-config"
    config.mkdir(mode=0o700)
    bootstrap = credentials["bootstrap"]
    private_file(
        config / "config.json",
        json.dumps(
            {
                "version": "10",
                "aliases": {
                    "fixture": {
                        "url": endpoint,
                        "accessKey": bootstrap[0],
                        "secretKey": bootstrap[1],
                        "api": "S3v4",
                        "path": "on",
                    }
                },
            }
        ).encode(),
    )
    archive = Path(directory) / "iam-import.zip"
    private_file(archive, iam_archive_bytes(credentials, policies))
    for path in (config, config / "config.json", archive):
        expected = 0o700 if path.is_dir() else 0o600
        if path.stat().st_mode & 0o777 != expected or path.stat().st_uid != os.getuid():
            raise RuntimeError("bootstrap private file ownership/mode mismatch")
    output = safe_run(
        [
            str(Path(directory) / "mc"),
            "--config-dir",
            str(config),
            "--json",
            "admin",
            "cluster",
            "iam",
            "import",
            "fixture",
            str(archive),
        ],
        directory,
        timeout=60,
    )
    validate_import_result(output, credentials)
