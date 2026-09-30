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


class RelayCommands:
    """Exact inspect child handles, bounded streams and cancellation ownership."""

    MAX_CAPTURE = 1048576

    def __init__(self, stop):
        self.stop = stop
        self.lock = threading.Lock()
        self.records = {}

    def run(self, command, environment, deadline):
        record = {"process": None}
        identity = id(record)
        with self.lock:
            if self.stop.is_set() or time.monotonic() >= deadline:
                raise RuntimeError("relay validation cancelled")
            self.records[identity] = record
        try:
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
            process = record["process"]
            if process is None:
                with self.lock:
                    self.records.pop(identity, None)
            else:
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass  # Keep exact unsettled ownership for guarded cleanup.
                if process.poll() is not None:
                    for stream in (process.stdout, process.stderr):
                        if stream:
                            stream.close()
                    with self.lock:
                        self.records.pop(identity, None)

    def cancel(self, deadline):
        # Pending creations remain registered until their owning worker settles.
        while True:
            with self.lock:
                records = list(self.records.items())
            for identity, record in records:
                process = record["process"]
                if process is None:
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
                    with self.lock:
                        self.records.pop(identity, None)
            with self.lock:
                if not self.records:
                    return
            if time.monotonic() >= deadline:
                raise RuntimeError("owned relay child cleanup unsettled")
            time.sleep(0.01)


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

    def _check_cutoff(self, deadline):
        if self.stop.is_set() or time.monotonic() >= deadline:
            raise RuntimeError("relay control cutoff")

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
            except Exception:  # noqa: BLE001 -- retain all partial startup ownership
                self.failed = True
                self.state = "STOPPING"
                self.stop.set()
                if listener is not None:
                    listener.close()
                    self.sockets.discard(listener)
                raise RuntimeError("owned relay startup failed") from None

    def _accept(self):
        while not self.stop.is_set():
            try:
                if self.socket_identity(self.listener) != self.listener_identity:
                    raise RuntimeError("relay listener identity differs")
                client, _ = self.listener.accept()
            except TimeoutError:
                continue
            except (OSError, RuntimeError):
                if not self.stop.is_set():
                    self.failed = True
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
                    if self.state == "RUNNING":
                        self.failed = True
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
                except RuntimeError:
                    self.failed = True
                    client.close()
                    self.sockets.discard(client)
                    self.connections -= 1

    def _register_backend(self):
        with self.lock:
            if self.state != "RUNNING" or self.failed or self.stop.is_set():
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
        except Exception:  # noqa: BLE001 -- close registered socket; expose no raw details
            stream.close()
            with self.lock:
                self.sockets.discard(stream)
            raise RuntimeError("owned relay connect failed") from None

    def _worker(self, client, accepted):
        upstream = None
        try:
            absolute = accepted + self.ABSOLUTE_SECONDS
            initial_idle = accepted + self.IDLE_SECONDS
            cutoff = min(
                absolute, initial_idle, time.monotonic() + self.VALIDATION_SECONDS
            )
            address = self.validate(cutoff, self.stop, self.commands)
            ipaddress.IPv4Address(address)  # Numeric only; no resolver/fallback.
            if self.stop.is_set() or time.monotonic() >= cutoff:
                raise RuntimeError("relay validation cutoff")
            upstream = self._connect((address, 9000), min(absolute, initial_idle))
            with self.lock:
                if self.state != "RUNNING" or self.stop.is_set():
                    raise RuntimeError("relay stopped before forwarding")
                self.sockets.add(upstream)
            self._pump(client, upstream, absolute, initial_idle)
        except Exception:  # noqa: BLE001 -- poison transport and settle exact handles
            if not self.stop.is_set():
                self.failed = True
        finally:
            for stream in (client, upstream):
                if stream:
                    stream.close()
                    with self.lock:
                        self.sockets.discard(stream)
            with self.lock:
                self.connections -= 1

    def _pump(self, client, upstream, absolute, idle):
        streams = [client, upstream]
        queues = [bytearray(), bytearray()]
        eof = [False, False]
        half_closed = [False, False]
        total = 0
        for stream in streams:
            stream.setblocking(False)
            self._check_cutoff(min(absolute, idle))
        while not all(half_closed):
            cutoff = min(absolute, idle)
            self._check_cutoff(cutoff)
            readers = [
                streams[i]
                for i in range(2)
                if not eof[i] and len(queues[i]) < self.MAX_BUFFER
            ]
            writers = [streams[1 - i] for i in range(2) if queues[i]]
            readable, writable, _ = select.select(
                readers,
                writers,
                [],
                min(0.05, max(0, cutoff - time.monotonic())),
            )
            self._check_cutoff(cutoff)
            for i in range(2):
                if streams[i] in readable:
                    cutoff = min(absolute, idle)
                    self._check_cutoff(cutoff)
                    block = streams[i].recv(self.MAX_BUFFER - len(queues[i]))
                    self._check_cutoff(cutoff)
                    if block:
                        if total + len(block) > self.MAX_BYTES:
                            raise RuntimeError("relay byte bound")
                        queues[i].extend(block)
                        total += len(block)
                        idle = time.monotonic() + self.IDLE_SECONDS
                    else:
                        eof[i] = True
                if queues[i] and streams[1 - i] in writable:
                    cutoff = min(absolute, idle)
                    self._check_cutoff(cutoff)
                    sent = streams[1 - i].send(queues[i])
                    self._check_cutoff(cutoff)
                    if sent <= 0:
                        raise RuntimeError("relay send failed")
                    del queues[i][:sent]
                    idle = time.monotonic() + self.IDLE_SECONDS
                if eof[i] and not queues[i] and not half_closed[i]:
                    cutoff = min(absolute, idle)
                    self._check_cutoff(cutoff)
                    streams[1 - i].shutdown(socket.SHUT_WR)
                    self._check_cutoff(cutoff)
                    half_closed[i] = True

    def assert_healthy(self):
        if self.failed or self.state != "RUNNING" or self.stop.is_set():
            raise RuntimeError("owned relay transport failed")
        if self.socket_identity(self.listener) != self.listener_identity:
            raise RuntimeError("owned relay transport failed")

    def close(self):
        deadline = time.monotonic() + self.CLEANUP_SECONDS
        with self.lock:
            self.state = "STOPPING"
            self.stop.set()
            streams = tuple(self.sockets)
            threads = tuple(self.threads)
        for stream in streams:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            stream.close()
        self.commands.cancel(deadline)
        for thread in threads:
            if thread.ident is not None:
                thread.join(max(0, deadline - time.monotonic()))
        if self.live_threads or self.commands.records:
            raise RuntimeError("owned relay cleanup unsettled")
        with self.lock:
            self.sockets.clear()
            self.threads.clear()
            self.state = "CLOSED"


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
