"""Owned fixture transport controls and observational witnesses; no fake S3."""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import select
import signal
import socket
import stat
import struct
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from urllib.parse import unquote_to_bytes, urlsplit
from uuid import UUID

from wso_core.storage import (
    InstallationNamespace,
    ObjectLocator,
    installation_prefix,
    object_key,
)


class FixtureContractError(ValueError):
    def __init__(self):
        super().__init__("invalid fixture contract")


def require(condition):
    if not condition:
        raise FixtureContractError()


def native_float(value):
    require(type(value) is float and math.isfinite(value))
    return value


def private_string(value, maximum=8192):
    require(type(value) is str and 0 < len(value.encode("utf-8")) <= maximum)
    require(all(ord(c) >= 32 and ord(c) != 127 for c in value))
    return value


_snapshot_registration_lock = threading.Lock()


class OwnedSnapshots:
    """Private whole-file publications; exclusive provider artifacts stay separate."""

    def __init__(self, directory: Path, owner: str):
        self.lock = threading.RLock()
        self.closed, self.poisoned = False, False
        self.handles = set()
        self.temporaries = {}
        self.directory_fd = None
        self.directory = directory
        self.owner = private_string(owner, 128)
        require(
            owner.isascii()
            and isinstance(directory, Path)
            and directory.is_absolute()
            and ".." not in directory.parts
        )
        try:
            for ancestor in (directory, *directory.parents):
                require(not ancestor.is_symlink())
            row = directory.stat()
            require(stat.S_ISDIR(row.st_mode))
            if os.name == "posix":
                require(
                    row.st_uid == os.getuid() and stat.S_IMODE(row.st_mode) == 0o700
                )
            self.identity = (row.st_dev, row.st_ino)
            self.directory_fd = (
                os.open(
                    directory,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
                if os.name == "posix"
                else None
            )
            # Same-owner concurrent registrations cannot read a half-written marker.
            with _snapshot_registration_lock:
                locked = False
                try:
                    if os.name == "posix":
                        import fcntl

                        self._pin()
                        fcntl.flock(self.directory_fd, fcntl.LOCK_EX)
                        locked = True
                        self._pin()
                    marker = directory / ".snapshot-owner"
                    try:
                        descriptor = os.open(
                            marker,
                            os.O_CREAT
                            | os.O_EXCL
                            | os.O_WRONLY
                            | getattr(os, "O_NOFOLLOW", 0),
                            0o600,
                        )
                    except FileExistsError:
                        self._file(marker)
                        require(marker.read_bytes() == owner.encode("ascii"))
                    else:
                        self.handles.add(descriptor)
                        require(
                            os.write(descriptor, owner.encode("ascii")) == len(owner)
                        )
                        os.close(descriptor)
                        self.handles.remove(descriptor)
                finally:
                    if locked:
                        fcntl.flock(self.directory_fd, fcntl.LOCK_UN)
        except BaseException:  # noqa: BLE001 -- normalize owned publication failures.
            self.close()
            raise FixtureContractError() from None

    def _pin(self):
        row = self.directory.stat()
        require(
            not self.directory.is_symlink()
            and (row.st_dev, row.st_ino) == self.identity
        )
        if os.name == "posix":
            require(row.st_uid == os.getuid() and stat.S_IMODE(row.st_mode) == 0o700)

        if self.directory_fd is not None:
            retained = os.fstat(self.directory_fd)
            require(
                stat.S_ISDIR(retained.st_mode)
                and (retained.st_dev, retained.st_ino) == self.identity
                and retained.st_uid == os.getuid()
                and stat.S_IMODE(retained.st_mode) == 0o700
            )

    def _file(self, path):
        row = path.lstat()
        require(stat.S_ISREG(row.st_mode) and row.st_nlink == 1)
        if os.name == "posix":
            require(row.st_uid == os.getuid() and stat.S_IMODE(row.st_mode) == 0o600)

    def write(self, name: str, value: object):
        with self.lock:
            require(not self.closed and not self.poisoned)
            require(
                type(name) is str
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) is not None
                and name not in {".", ".."}
            )

            def tree(item, depth=0):
                require(depth <= 32)
                if type(item) is dict:
                    require(all(type(k) is str for k in item))
                    for child in item.values():
                        tree(child, depth + 1)
                elif type(item) is list:
                    for child in item:
                        tree(child, depth + 1)
                else:
                    require(item is None or type(item) in {str, int, float, bool})
                    if type(item) is float:
                        require(math.isfinite(item))

            tree(value)
            try:
                data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode(
                    "utf-8"
                )
                require(len(data) <= 1048576)
                self._pin()
                self._file(self.directory / ".snapshot-owner")
                require(
                    (self.directory / ".snapshot-owner").read_bytes()
                    == self.owner.encode("ascii")
                )
                temporary = ".snapshot-" + secrets.token_hex(16)
                target = self.directory / name
                descriptor = os.open(
                    self.directory / temporary,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                self.handles.add(descriptor)
                custody = {"descriptor": descriptor, "identity": None}
                self.temporaries[temporary] = custody
                row = os.fstat(descriptor)
                custody["identity"] = (row.st_dev, row.st_ino)
                position = 0
                while position < len(data):
                    count = os.write(descriptor, data[position:])
                    require(count > 0)
                    position += count
                os.close(descriptor)
                self.handles.remove(descriptor)
                custody["descriptor"] = None
                self._file(self.directory / temporary)
                self._pin()
                if target.exists() or target.is_symlink():
                    self._file(target)
                if self.directory_fd is not None:
                    os.replace(
                        temporary,
                        name,
                        src_dir_fd=self.directory_fd,
                        dst_dir_fd=self.directory_fd,
                    )
                else:
                    os.replace(self.directory / temporary, target)
                # Successful replacement removes this temporary identity; never retry it.
                del self.temporaries[temporary]
                self._pin()
            except BaseException:  # noqa: BLE001 -- retain failed publication custody.
                self.poisoned = True
                self._settle()
                raise FixtureContractError() from None

    def _settle(self):
        failed = False
        for custody in self.temporaries.values():
            descriptor = custody["descriptor"]
            if descriptor is None:
                continue
            try:
                if custody["identity"] is None:
                    row = os.fstat(descriptor)
                    custody["identity"] = (row.st_dev, row.st_ino)
                else:
                    row = os.fstat(descriptor)
                    require((row.st_dev, row.st_ino) == custody["identity"])
                os.close(descriptor)
            except (OSError, FixtureContractError):
                failed = True
            else:
                self.handles.remove(descriptor)
                custody["descriptor"] = None
        retained = {
            item["descriptor"]
            for item in self.temporaries.values()
            if item["descriptor"] is not None
        }
        for descriptor in tuple(self.handles - retained):
            try:
                os.close(descriptor)
            except OSError:
                failed = True
            else:
                self.handles.remove(descriptor)
        for name, custody in tuple(self.temporaries.items()):
            if custody["descriptor"] is not None:
                continue  # Removal never precedes confirmed descriptor settlement.
            try:
                self._pin()
                path = self.directory / name
                try:
                    row = path.lstat()
                except FileNotFoundError:
                    del self.temporaries[name]
                    continue
                self._file(path)
                require((row.st_dev, row.st_ino) == custody["identity"])
                path.unlink()
                try:
                    path.lstat()
                except FileNotFoundError:
                    del self.temporaries[name]
                else:
                    failed = True
            except (OSError, FixtureContractError):
                failed = True
        return failed

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.poisoned = True  # Closing admission cannot reopen after a refusal.
            failed = self._settle()
            if (
                not self.handles
                and not self.temporaries
                and self.directory_fd is not None
            ):
                try:
                    os.close(self.directory_fd)
                except OSError:
                    failed = True
                else:
                    self.directory_fd = None
            if (
                failed
                or self.handles
                or self.temporaries
                or self.directory_fd is not None
            ):
                raise FixtureContractError() from None
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def snapshot_json(path, value, *, owner=None):
    token = owner or (value.get("owner") if type(value) is dict else None)
    require(type(token) is str)
    with OwnedSnapshots(Path(path).parent, token) as writer:
        writer.write(Path(path).name, value)


class S3Operation(str, Enum):
    CREATE_MULTIPART = "CREATE_MULTIPART"
    UPLOAD_PART = "UPLOAD_PART"
    COMPLETE_MULTIPART = "COMPLETE_MULTIPART"
    DELETE_OBJECT = "DELETE_OBJECT"
    LIST_OBJECTS = "LIST_OBJECTS"
    LIST_MULTIPART = "LIST_MULTIPART"


class MatchResult(str, Enum):
    MATCH = "MATCH"
    UNMATCHED = "UNMATCHED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True, repr=False)
class ObjectPageCursor:
    token: str

    def __post_init__(self):
        private_string(self.token)


@dataclass(frozen=True, slots=True, repr=False)
class MultipartPageCursor:
    key_marker: str
    upload_id_marker: str | None

    def __post_init__(self):
        private_string(self.key_marker)
        if self.upload_id_marker is not None:
            private_string(self.upload_id_marker)


@dataclass(frozen=True, slots=True, repr=False)
class S3FaultSelector:
    operation: S3Operation
    namespace: InstallationNamespace
    locator: ObjectLocator | None = None
    upload_id: str | None = None
    part_number: int | None = None
    cursor: ObjectPageCursor | MultipartPageCursor | None = None
    limit: int | None = None

    def __post_init__(self):
        require(
            type(self.operation) is S3Operation
            and type(self.namespace) is InstallationNamespace
        )
        require(self.namespace.installation_id.int != 0)
        listing = self.operation in {
            S3Operation.LIST_OBJECTS,
            S3Operation.LIST_MULTIPART,
        }
        if self.locator is not None:
            require(type(self.locator) is ObjectLocator)
            require(self.locator.installation_id == self.namespace.installation_id)
            require(
                all(
                    getattr(self.locator, name).int
                    for name in (
                        "installation_id",
                        "tenant_id",
                        "asset_id",
                        "attempt_id",
                    )
                )
            )
        if listing:
            require(self.upload_id is None and self.part_number is None)
            require(type(self.limit) is int and 1 <= self.limit <= 100)
            cursor_type = (
                ObjectPageCursor
                if self.operation is S3Operation.LIST_OBJECTS
                else MultipartPageCursor
            )
            require(self.cursor is None or type(self.cursor) is cursor_type)
        else:
            require(
                type(self.locator) is ObjectLocator
                and self.cursor is None
                and self.limit is None
            )
            require(self.locator.installation_id == self.namespace.installation_id)
            require(
                all(
                    getattr(self.locator, name).int
                    for name in (
                        "installation_id",
                        "tenant_id",
                        "asset_id",
                        "attempt_id",
                    )
                )
            )
            if self.operation in {
                S3Operation.UPLOAD_PART,
                S3Operation.COMPLETE_MULTIPART,
            }:
                private_string(self.upload_id)
            else:
                require(self.upload_id is None)
            if self.operation is S3Operation.UPLOAD_PART:
                require(
                    type(self.part_number) is int and 1 <= self.part_number <= 10000
                )
            else:
                require(self.part_number is None)


def _decode(value):
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        raise FixtureContractError()
    decoded = unquote_to_bytes(value).decode("utf-8", errors="strict")
    require(all(ord(c) >= 32 and ord(c) != 127 for c in decoded))
    return decoded


def match_s3_request(header_bytes, selector):
    require(type(header_bytes) is bytes and type(selector) is S3FaultSelector)
    if len(header_bytes) > 65536 or not header_bytes.endswith(b"\r\n\r\n"):
        return MatchResult.INVALID
    try:
        lines = header_bytes[:-4].decode("ascii").split("\r\n")
        method, target, version = lines[0].split(" ")
        require(
            method in {"GET", "PUT", "POST", "DELETE", "HEAD"} and version == "HTTP/1.1"
        )
        require(
            target.startswith("/") and not target.startswith("//") and "#" not in target
        )
        headers = {}
        for line in lines[1:]:
            name, value = line.split(":", 1)
            require(re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) is not None)
            require(
                name.lower() not in headers and all(32 <= ord(c) < 127 for c in value)
            )
            headers[name.lower()] = value.strip()
        require(bool(headers.get("host")))
        path, separator, query = target.partition("?")
        path = _decode(path)
        values = {}
        if separator:
            require(bool(query))
            for pair in query.split("&"):
                key, _, value = pair.partition("=")
                key, value = _decode(key), _decode(value)
                require(key and key not in values)
                values[key] = value
        op = selector.operation
        if op is S3Operation.LIST_OBJECTS:
            _allowed = {
                "list-type",
                "prefix",
                "max-keys",
                "continuation-token",
                "encoding-type",
            }
            expected = {
                "list-type": "2",
                "prefix": object_key(selector.locator)
                if selector.locator is not None
                else installation_prefix(selector.namespace),
                "max-keys": str(selector.limit),
            }
            if selector.cursor is not None:
                expected["continuation-token"] = selector.cursor.token
            expected_method = "GET"
        elif op is S3Operation.LIST_MULTIPART:
            _allowed = {
                "uploads",
                "prefix",
                "max-uploads",
                "key-marker",
                "upload-id-marker",
                "encoding-type",
            }
            expected = {
                "uploads": "",
                "prefix": object_key(selector.locator)
                if selector.locator is not None
                else installation_prefix(selector.namespace),
                "max-uploads": str(selector.limit),
            }
            if selector.cursor is not None:
                expected["key-marker"] = selector.cursor.key_marker
                if selector.cursor.upload_id_marker is not None:
                    expected["upload-id-marker"] = selector.cursor.upload_id_marker
            expected_method = "GET"
        elif op is S3Operation.CREATE_MULTIPART:
            _allowed, expected, expected_method = {"uploads"}, {"uploads": ""}, "POST"
        elif op is S3Operation.UPLOAD_PART:
            _allowed, expected, expected_method = (
                {"uploadId", "partNumber"},
                {
                    "uploadId": selector.upload_id,
                    "partNumber": str(selector.part_number),
                },
                "PUT",
            )
        elif op is S3Operation.COMPLETE_MULTIPART:
            _allowed, expected, expected_method = (
                {"uploadId"},
                {"uploadId": selector.upload_id},
                "POST",
            )
        else:
            _allowed, expected, expected_method = set(), {}, "DELETE"
        # Validate known grammar independently of the armed operation.
        keys = set(values)
        if "list-type" in keys:
            require(
                values["list-type"] == "2"
                and {"list-type", "prefix", "max-keys"}
                <= keys
                <= {
                    "list-type",
                    "prefix",
                    "max-keys",
                    "continuation-token",
                    "encoding-type",
                }
            )
            numeric = values["max-keys"]
            require(
                numeric.isascii() and numeric.isdecimal() and 1 <= int(numeric) <= 100
            )
            require(method == "GET")
        elif "prefix" in keys or "max-uploads" in keys:
            require(
                {"uploads", "prefix", "max-uploads"}
                <= keys
                <= {
                    "uploads",
                    "prefix",
                    "max-uploads",
                    "key-marker",
                    "upload-id-marker",
                    "encoding-type",
                }
            )
            require(
                values["uploads"] == ""
                and method == "GET"
                and ("upload-id-marker" not in keys or "key-marker" in keys)
            )
            numeric = values["max-uploads"]
            require(
                numeric.isascii() and numeric.isdecimal() and 1 <= int(numeric) <= 100
            )
        elif keys == {"uploads"}:
            require(values["uploads"] == "")
        elif "uploadId" in keys:
            private_string(values["uploadId"], 1024)
            require(keys <= {"uploadId", "partNumber"})
            if "partNumber" in keys:
                part = values["partNumber"]
                require(
                    part.isascii()
                    and part.isdecimal()
                    and 1 <= int(part) <= 10000
                    and method == "PUT"
                )
            else:
                require(method in {"GET", "POST", "DELETE"})
        else:
            require(not keys and method in {"GET", "HEAD", "PUT", "DELETE"})
        if "encoding-type" in values:
            require(values.pop("encoding-type") == "url")
        expected_path = "/" + selector.namespace.bucket
        if selector.locator is not None and op not in {
            S3Operation.LIST_OBJECTS,
            S3Operation.LIST_MULTIPART,
        }:
            expected_path += "/" + object_key(selector.locator)
        return (
            MatchResult.MATCH
            if (method, path, values) == (expected_method, expected_path, expected)
            else MatchResult.UNMATCHED
        )
    except (FixtureContractError, ValueError, UnicodeError, IndexError):
        return MatchResult.INVALID


class TraversalStream(str, Enum):
    OBJECTS = "OBJECTS"
    MULTIPART = "MULTIPART"


@dataclass(frozen=True, slots=True)
class EpochSummary:
    iterations: int
    objects_full: bool
    multipart_full: bool
    simultaneous_null: bool


class EpochTracker:
    def __init__(self, inventories, *, max_calls=64):
        require(
            type(max_calls) is int
            and max_calls == 64
            and set(inventories) == set(TraversalStream)
        )
        require(all(type(v) is frozenset for v in inventories.values()))
        self.inventories = MappingProxyType(dict(inventories))
        self.iterations = 0
        self.streams = {
            s: {
                "initialized": False,
                "cursor": None,
                "tail": False,
                "seen": set(),
                "tokens": set(),
                "full": False,
                "pages": 0,
                "completed_pages": [],
            }
            for s in TraversalStream
        }

    def begin_iteration(self):
        require(self.iterations < 64)
        self.iterations += 1

    def record_page(
        self, stream, *, cursor_before, cursor_after, identities, committed
    ):
        require(
            type(stream) is TraversalStream and type(committed) is bool and committed
        )
        require(type(identities) is tuple)
        kind = (
            ObjectPageCursor
            if stream is TraversalStream.OBJECTS
            else MultipartPageCursor
        )
        require(
            all(c is None or type(c) is kind for c in (cursor_before, cursor_after))
        )
        state = self.streams[stream]
        if state["initialized"]:
            require(cursor_before == state["cursor"])
        else:
            state["initialized"] = True
            state["tail"] = cursor_before is not None
        if cursor_before is None:
            state["seen"].clear()
            state["tokens"].clear()
            state["pages"] = 0
            state["tail"] = False
        require(len(set(identities)) == len(identities))
        require(
            set(identities) <= self.inventories[stream]
            and not set(identities) & state["seen"]
        )
        require(
            cursor_after is None
            or (cursor_after != cursor_before and cursor_after not in state["tokens"])
        )
        state["seen"].update(identities)
        state["pages"] += 1
        state["cursor"] = cursor_after
        if cursor_after is not None:
            state["tokens"].add(cursor_after)
        else:
            if not state["tail"]:
                require(state["seen"] == self.inventories[stream])
                state["full"] = True
                state["completed_pages"].append(state["pages"])

    def summary(self):
        a, b = (self.streams[s] for s in TraversalStream)
        return EpochSummary(
            self.iterations,
            a["full"],
            b["full"],
            a["initialized"]
            and b["initialized"]
            and a["cursor"] is None
            and b["cursor"] is None,
        )

    def assert_complete(self):
        result = self.summary()
        require(
            result.objects_full and result.multipart_full and result.simultaneous_null
        )


@dataclass(frozen=True, slots=True, repr=False)
class ProcessIdentity:
    owner: str
    pid: int
    uid: int
    ppid: int
    pgid: int
    start_ticks: int
    command: tuple[str, ...]

    def __post_init__(self):
        private_string(self.owner, 128)
        for name in ("pid", "uid", "ppid", "pgid", "start_ticks"):
            value = getattr(self, name)
            require(
                type(value) is int and value >= (0 if name in {"uid", "ppid"} else 1)
            )
        require(type(self.command) is tuple and 0 < len(self.command) <= 64)
        for item in self.command:
            private_string(item)


def process_identity_snapshot(identity):
    """Publish the explicit native identity schema without changing its tuple custody."""
    require(type(identity) is ProcessIdentity)
    identity.__post_init__()
    return {
        "owner": identity.owner,
        "pid": identity.pid,
        "uid": identity.uid,
        "ppid": identity.ppid,
        "pgid": identity.pgid,
        "start_ticks": identity.start_ticks,
        "command": list(identity.command),
    }


def validate_process_identity(expected, observed):
    require(
        type(expected) is ProcessIdentity
        and type(observed) is ProcessIdentity
        and expected == observed
    )


def process_identity(pid, owner):
    path = Path(f"/proc/{pid}")
    parts = (path / "stat").read_text().rsplit(")", 1)[1].split()
    require(parts[0] != "Z")
    require(
        f"WSO_ASSET_FIXTURE_OWNER={owner}".encode()
        in (path / "environ").read_bytes().split(b"\0")
    )
    command = tuple(
        os.fsdecode(x) for x in (path / "cmdline").read_bytes().split(b"\0") if x
    )
    return ProcessIdentity(
        owner,
        pid,
        path.stat().st_uid,
        int(parts[1]),
        int(parts[2]),
        int(parts[19]),
        command,
    )


@dataclass(frozen=True, slots=True)
class IdleSnapshot:
    healthy: bool
    connections: int
    sockets: int
    workers: int
    only_listener: bool
    only_pinned_acceptor: bool
    acceptor_alive: bool
    commands_settled: bool


def validate_idle_snapshot(snapshot):
    require(type(snapshot) is IdleSnapshot)
    require(
        all(
            type(getattr(snapshot, x)) is bool and getattr(snapshot, x)
            for x in (
                "healthy",
                "only_listener",
                "only_pinned_acceptor",
                "acceptor_alive",
                "commands_settled",
            )
        )
    )
    require(
        all(
            type(getattr(snapshot, x)) is int
            for x in ("connections", "sockets", "workers")
        )
    )
    require((snapshot.connections, snapshot.sockets, snapshot.workers) == (0, 1, 1))


class OwnedProcess:
    def __init__(self, process, *, owner, command, log, cutoff):
        self.process, self.owner, self.command, self.log, self.cutoff = (
            process,
            owner,
            tuple(command),
            log,
            cutoff,
        )
        self.identity = process_identity(process.pid, owner)
        require(
            self.identity.command == self.command and self.identity.pgid == process.pid
        )

    def stop(self, *, force=False):
        if self.process.poll() is None:
            descriptor = os.pidfd_open(self.process.pid, 0)
            try:
                validate_process_identity(
                    self.identity, process_identity(self.process.pid, self.owner)
                )
                signal.pidfd_send_signal(
                    descriptor, signal.SIGKILL if force else signal.SIGTERM, None, 0
                )
            finally:
                os.close(descriptor)
        self.process.wait(timeout=max(0.001, min(10, self.cutoff - time.monotonic())))
        require(self.process.poll() is not None)
        self.log.close()

    def assert_settled(self):
        require(self.process.poll() is not None)


class BarrierControl:
    EVENTS = frozenset(
        {
            "UPLOAD_INTENT_COMMITTED",
            "MULTIPART_CREATED_BEFORE_RECORD",
            "OBJECT_COMPLETED_BEFORE_SEAL",
            "VALIDATED_BEFORE_FINALIZE",
            "DOWNLOAD_FIRST_CHUNK",
            "CLEANUP_EFFECT_BEFORE_ACK",
            "JOB_AFTER_READ",
            "JOB_AFTER_COMMIT",
            "WORKER_READY",
        }
    )

    def __init__(self, directory, owner):
        self.directory, self.owner = Path(directory), owner
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(
            self.directory.stat().st_uid == os.getuid()
            and self.directory.stat().st_mode & 0o777 == 0o700
        )

    def arm(self, event, *, asset_id=None, cutoff):

        require(event in self.EVENTS)
        native_float(cutoff)
        snapshot_json(
            self.directory / "armed.json",
            {
                "event": event,
                "id": str(asset_id) if asset_id is not None else None,
                "cutoff": cutoff,
                "owner": self.owner,
            },
        )

    def callback(self, event):

        name, opaque_id = event.name, event.work_id or event.asset_id
        require(name in self.EVENTS and type(opaque_id) is UUID)
        record = {
            "event": name,
            "id": str(opaque_id),
            "owner": self.owner,
            "at": time.monotonic(),
        }
        snapshot_json(self.directory / "last-event.json", record)
        armed_path = self.directory / "armed.json"
        if not armed_path.exists():
            return
        armed = json.loads(armed_path.read_bytes())
        require(armed["owner"] == self.owner)
        if armed["event"] != name or (
            armed["id"] is not None and armed["id"] != str(event.asset_id)
        ):
            return
        identity = process_identity(os.getpid(), self.owner)
        record["identity"] = process_identity_snapshot(identity)
        snapshot_json(self.directory / "reached.json", record)
        while not (self.directory / "release.json").exists():
            if time.monotonic() >= armed["cutoff"]:
                raise RuntimeError("owned fixture barrier expired")
            time.sleep(min(0.025, armed["cutoff"] - time.monotonic()))
        release = json.loads((self.directory / "release.json").read_bytes())
        require(release == {"owner": self.owner, "event": name, "id": str(opaque_id)})

    def wait(self, cutoff):
        while not (self.directory / "reached.json").exists():
            require(time.monotonic() < cutoff)
            time.sleep(min(0.025, cutoff - time.monotonic()))
        record = json.loads((self.directory / "reached.json").read_bytes())
        require(record["owner"] == self.owner)
        return record

    def release(self, record):

        snapshot_json(
            self.directory / "release.json",
            {k: record[k] for k in ("owner", "event", "id")},
        )

    def reset(self):
        for name in ("armed.json", "reached.json", "release.json"):
            (self.directory / name).unlink(missing_ok=True)


class HelperObserver:
    """The parent alone opens/signals handles from its actual helper inventory."""

    def __init__(self, control):
        self.control, self.stop_event = control, threading.Event()
        self.thread = threading.Thread(
            target=self._run, name="owned-asset-helper-observer"
        )
        self.failure = None

    def start(self):
        self.parent_identity = process_identity(os.getpid(), self.control.owner)
        self.thread.start()
        return self

    def _run(self):
        from wso_core.asset_process import local_cleanup_complete, owned_helper_pids

        descriptors = {}
        try:
            while not self.stop_event.is_set():
                pids = owned_helper_pids()
                for pid in pids:
                    if pid not in descriptors:
                        try:
                            descriptor = os.pidfd_open(pid, 0)
                        except ProcessLookupError:
                            require(pid not in owned_helper_pids())
                            continue
                        try:
                            identity = process_identity(pid, self.control.owner)
                            require(
                                identity.ppid == os.getpid()
                                and identity.uid == os.getuid()
                            )
                        except BaseException:
                            os.close(descriptor)
                            if pid not in owned_helper_pids():
                                continue
                            # A registered helper may be awaiting its actual
                            # parent's reap. Retain its inventory, do not signal
                            # or report settled from the failed identity read.
                            stat = Path(f"/proc/{pid}/stat")
                            if (
                                stat.exists()
                                and stat.read_text().rsplit(")", 1)[1].split()[0] == "Z"
                            ):
                                continue
                            raise
                        descriptors[pid] = (descriptor, identity)
                for pid in tuple(descriptors):
                    if pid not in pids:
                        os.close(descriptors.pop(pid)[0])
                snapshot_json(
                    self.control.directory / "helpers.json",
                    {
                        "owner": self.control.owner,
                        "pids": list(pids),
                        "complete": local_cleanup_complete(),
                    },
                )
                kill = self.control.directory / "kill-helper.json"
                if kill.exists():
                    command = json.loads(kill.read_bytes())
                    require(
                        command == {"owner": self.control.owner, "kill": True}
                        and len(pids) == 1
                    )
                    pid = pids[0]
                    descriptor, identity = descriptors[pid]
                    validate_process_identity(
                        self.parent_identity,
                        process_identity(os.getpid(), self.control.owner),
                    )
                    validate_process_identity(
                        identity, process_identity(pid, self.control.owner)
                    )
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL, None, 0)
                    kill.unlink()
                self.stop_event.wait(0.025)
        except BaseException:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
            self.failure = RuntimeError("owned helper observation refused")
        finally:
            for descriptor, _ in descriptors.values():
                os.close(descriptor)

    def close(self):
        self.stop_event.set()
        self.thread.join(3)
        require(not self.thread.is_alive() and self.failure is None)


class RecordingObjectStore:
    def __init__(self, inner, journal):
        self.inner, self.journal, self.namespace = inner, journal, inner.namespace

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _page(self, method, **kwargs):
        page = getattr(self.inner, method)(**kwargs)
        self.journal.append((method, dict(kwargs), page))
        return page

    def list_objects(self, **kwargs):
        return self._page("list_objects", **kwargs)

    def list_multipart(self, **kwargs):
        return self._page("list_multipart", **kwargs)


class RecordingTransactions:
    def __init__(self, inner, journal):
        self.inner, self.journal = inner, journal

    @contextmanager
    def __call__(self):
        record = []

        class Observation:
            def __init__(self, session):
                self.session = session

            def execute(self, statement, values=None, **kwargs):
                result = self.session.execute(statement, values, **kwargs)
                item = {
                    "statement": str(statement),
                    "values": dict(values or {}),
                    "scalar": None,
                    "consumed": False,
                }
                record.append(item)

                class ObservedResult:
                    def scalar_one(self):
                        value = result.scalar_one()
                        item["scalar"], item["consumed"] = value, True
                        return value

                    def mappings(self):
                        mapped = result.mappings()

                        class ObservedMappings:
                            def all(self):
                                rows = mapped.all()
                                item["rows"] = [dict(row) for row in rows]
                                item["consumed"] = True
                                return rows

                            def __getattr__(self, name):
                                return getattr(mapped, name)

                        return ObservedMappings()

                    def __getattr__(self, name):
                        return getattr(result, name)

                return ObservedResult()

            def __getattr__(self, name):
                return getattr(self.session, name)

        with self.inner() as session:
            yield Observation(session)
        self.journal.append(tuple(record))


class SendObserver:
    def __init__(self, app, journal):
        self.app, self.journal = app, journal

    async def __call__(self, scope, receive, send):
        async def observed(message):
            started = time.monotonic()
            self.journal(
                {
                    "phase": "begin",
                    "at": started,
                    "count": len(message.get("body", b"")),
                    "deadline": scope.get("wso_asset_download_deadline"),
                    "type": message["type"],
                }
            )
            try:
                await send(message)
            finally:
                self.journal(
                    {
                        "phase": "end",
                        "at": time.monotonic(),
                        "started": started,
                        "count": len(message.get("body", b"")),
                        "deadline": scope.get("wso_asset_download_deadline"),
                        "type": message["type"],
                    }
                )

        await self.app(scope, receive, observed)


class FaultMode(str, Enum):
    PASS = "PASS"
    RESET_BEFORE_FORWARD = "RESET_BEFORE_FORWARD"
    HOLD_REQUEST = "HOLD_REQUEST"
    HOLD_RESPONSE = "HOLD_RESPONSE"


@dataclass(frozen=True, slots=True)
class FaultRequestToken:
    generation: int
    request: int
    matched: bool
    mode: FaultMode


class FaultAdmission:
    def __init__(self):
        self.lock = threading.Lock()
        self.generation = self.request = 0
        self.active = {}
        self.mode = FaultMode.PASS
        self.armed = self.consumed = self.matched = False
        self.counts = {
            k: 0
            for k in (
                "forwarded",
                "returned",
                "dispatches",
                "total_forwarded",
                "total_returned",
                "total_dispatches",
            )
        }

    def arm(self, mode):
        with self.lock:
            require(type(mode) is FaultMode and not self.active)
            self.generation += 1
            self.mode, self.armed, self.consumed, self.matched = (
                mode,
                True,
                False,
                False,
            )
            for key in ("forwarded", "returned", "dispatches"):
                self.counts[key] = 0

    def admit(self, result):
        with self.lock:
            require(type(result) is MatchResult and result is not MatchResult.INVALID)
            matched = self.armed and result is MatchResult.MATCH
            if matched:
                self.armed, self.consumed, self.matched = False, True, True
            self.request += 1
            token = FaultRequestToken(
                self.generation,
                self.request,
                matched,
                self.mode if matched else FaultMode.PASS,
            )
            self.active[token.request] = token
            return token

    def record(self, token, *, forwarded=0, returned=0, dispatches=0):
        with self.lock:
            require(
                type(token) is FaultRequestToken
                and self.active.get(token.request) is token
            )
            values = {
                "forwarded": forwarded,
                "returned": returned,
                "dispatches": dispatches,
            }
            require(
                all(type(v) is int and v >= 0 for v in values.values())
                and dispatches <= 1
            )
            for key, value in values.items():
                self.counts["total_" + key] += value
                if token.matched:
                    self.counts[key] += value

    def finish(self, token):
        with self.lock:
            require(
                type(token) is FaultRequestToken
                and self.active.get(token.request) is token
            )
            del self.active[token.request]

    def snapshot(self):
        with self.lock:
            return dict(
                self.counts,
                armed=self.armed,
                consumed=self.consumed,
                matched=self.matched,
            )


class FaultRelay:
    """One owned request gate. All responses originate at the real backend."""

    def __init__(self, backend, owner, verify_backend, cutoff):
        parsed = urlsplit(backend)
        require(
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port is not None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
        )
        self.target = ("127.0.0.1", parsed.port)
        self.owner, self.verify_backend, self.cutoff = (
            owner,
            verify_backend,
            native_float(cutoff),
        )
        self.lock, self.stop_event, self.released, self.matched = (
            threading.Lock(),
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self.sockets, self.threads, self.active = set(), set(), False
        self.failure, self.selector, self.mode = None, None, FaultMode.PASS
        self.admission = FaultAdmission()
        self.listener = None
        self.endpoint = None

    def __enter__(self):
        self.verify_backend(self.cutoff)
        self._check(self.cutoff)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener = listener
        self.sockets.add(listener)
        try:
            listener.bind(("127.0.0.1", 0))
            self._check(self.cutoff)
            listener.listen(1)
            listener.settimeout(0.1)
            self._check(self.cutoff)
            self.endpoint = f"http://127.0.0.1:{listener.getsockname()[1]}"
            thread = threading.Thread(
                target=self._accept, name="owned-asset-fault-acceptor"
            )
            self.threads.add(thread)
            thread.start()
            return self
        except BaseException:
            self.close()
            raise

    def _check(self, cutoff):
        if self.stop_event.is_set() or time.monotonic() >= cutoff:
            raise RuntimeError("owned fault cutoff")

    def arm(self, selector, mode):
        require(type(selector) is S3FaultSelector and type(mode) is FaultMode)
        with self.lock:
            require(not self.active and self.failure is None)
            self.selector, self.mode = selector, mode
            self.admission.arm(mode)
            self.matched.clear()
            self.released.clear()

    def release(self):
        self.released.set()

    def snapshot(self):
        with self.lock:
            return dict(
                self.admission.snapshot(),
                failed=self.failure is not None,
                active=self.active,
                sockets=len(self.sockets),
                threads=sum(t.is_alive() for t in self.threads),
            )

    def wait_match(self, cutoff):
        require(self.matched.wait(max(0, cutoff - time.monotonic())))
        self._check(cutoff)

    def _accept(self):
        try:
            while not self.stop_event.is_set():
                self._check(self.cutoff)
                try:
                    client, _ = self.listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    if self.stop_event.is_set():
                        break
                    raise
                with self.lock:
                    if (
                        self.active
                        or self.stop_event.is_set()
                        or self.failure is not None
                        or time.monotonic() >= self.cutoff
                    ):
                        client.close()
                        continue
                    self.active = True
                    self.sockets.add(client)
                    worker = threading.Thread(
                        target=self._worker,
                        args=(client, time.monotonic()),
                        name="owned-asset-fault-worker",
                    )
                    self.threads.add(worker)
                worker.start()
        except BaseException:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
            with self.lock:
                self.failure = self.failure or "ACCEPT"

    def _wait_release(self, cutoff):
        while not self.released.is_set():
            self._check(cutoff)
            self.released.wait(min(0.025, max(0, cutoff - time.monotonic())))
        self._check(cutoff)

    def _worker(self, client, accepted):
        backend = None
        token = None
        absolute = min(self.cutoff, accepted + 60)
        idle = min(absolute, accepted + 10)
        try:
            data = bytearray()
            while b"\r\n\r\n" not in data:
                old = min(absolute, idle)
                self._check(old)
                client.settimeout(max(0.001, old - time.monotonic()))
                self._check(old)
                chunk = client.recv(min(4096, 65536 - len(data)))
                self._check(old)
                require(bool(chunk))
                data.extend(chunk)
                require(len(data) <= 65536)
                idle = min(absolute, time.monotonic() + 10)
            header_end = data.index(b"\r\n\r\n") + 4
            match = (
                match_s3_request(bytes(data[:header_end]), self.selector)
                if self.selector is not None
                else MatchResult.UNMATCHED
            )
            require(match is not MatchResult.INVALID)
            token = self.admission.admit(match)
            mode = token.mode
            if token.matched:
                self.matched.set()
            if mode is FaultMode.RESET_BEFORE_FORWARD:
                client.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                return
            if mode is FaultMode.HOLD_REQUEST:
                self._wait_release(min(absolute, idle))
            old = min(absolute, idle)
            self.verify_backend(old)
            self._check(old)
            backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            with self.lock:
                self._check(old)
                self.sockets.add(backend)
            connect_cutoff = min(old, time.monotonic() + 2)
            backend.settimeout(max(0.001, connect_cutoff - time.monotonic()))
            self._check(connect_cutoff)
            backend.connect(self.target)
            self._check(connect_cutoff)
            backend.settimeout(max(0.001, old - time.monotonic()))
            self._check(old)
            backend.sendall(data)
            self._check(old)
            with self.lock:
                self.admission.record(token, forwarded=len(data), dispatches=1)
            open_inputs = {client: backend, backend: client}
            total = len(data)
            while open_inputs:
                old = min(absolute, idle)
                self._check(old)
                readable, _, _ = select.select(
                    tuple(open_inputs), (), (), min(0.1, max(0, old - time.monotonic()))
                )
                self._check(old)
                for source in readable:
                    source.settimeout(max(0.001, old - time.monotonic()))
                    self._check(old)
                    chunk = source.recv(65536)
                    self._check(old)
                    target = open_inputs[source]
                    if not chunk:
                        target.shutdown(socket.SHUT_WR)
                        self._check(old)
                        del open_inputs[source]
                        continue
                    require(total + len(chunk) <= 64 * 1024 * 1024)
                    if source is backend and mode is FaultMode.HOLD_RESPONSE:
                        self._wait_release(old)
                    target.settimeout(max(0.001, old - time.monotonic()))
                    self._check(old)
                    target.sendall(chunk)
                    self._check(old)
                    total += len(chunk)
                    with self.lock:
                        if source is client:
                            self.admission.record(token, forwarded=len(chunk))
                        else:
                            self.admission.record(token, returned=len(chunk))
                    idle = min(absolute, time.monotonic() + 10)
        except BaseException:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
            if not self.stop_event.is_set():
                with self.lock:
                    self.failure = self.failure or "TRANSPORT"
        finally:
            for stream in (client, backend):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        with self.lock:
                            self.failure = self.failure or "CLOSE"
                    else:
                        with self.lock:
                            self.sockets.discard(stream)
            with self.lock:
                if token is not None:
                    self.admission.finish(token)
                self.active = False

    def close(self):
        cutoff = min(self.cutoff, time.monotonic() + 3)
        self.stop_event.set()
        self.released.set()
        errors = False
        for stream in tuple(self.sockets):
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                stream.close()
            except OSError:
                errors = True
            else:
                self.sockets.discard(stream)
        for thread in tuple(self.threads):
            thread.join(max(0, cutoff - time.monotonic()))
        require(
            not errors
            and not self.sockets
            and not any(t.is_alive() for t in self.threads)
        )

    def __exit__(self, *_exc):
        self.close()


@dataclass(frozen=True, slots=True, repr=False)
class RawResponse:
    status_code: int | None
    content: bytes
    headers: Mapping[str, str] = field(default_factory=dict)
    disconnected: bool = False

    def json(self):
        return json.loads(self.content)


def raw_http_exchange(origin, headers, chunks, cutoff, *, write_eof=False):
    parsed = urlsplit(origin)
    require(
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.port is not None
        and parsed.path in {"", "/"}
    )
    require(type(headers) is bytes and b"\r\n\r\n" in headers and len(headers) <= 65536)
    native_float(cutoff)
    require(type(write_eof) is bool)
    data = bytearray()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(max(0.001, min(2, cutoff - time.monotonic())))
        client.connect(("127.0.0.1", parsed.port))
        require(time.monotonic() < cutoff)
        client.sendall(headers)
        for chunk in chunks:
            require(type(chunk) is bytes and time.monotonic() < cutoff)
            client.settimeout(max(0.001, cutoff - time.monotonic()))
            client.sendall(chunk)
            require(time.monotonic() < cutoff)
        if write_eof:
            client.shutdown(socket.SHUT_WR)
        while True:
            require(time.monotonic() < cutoff)
            client.settimeout(max(0.001, cutoff - time.monotonic()))
            try:
                chunk = client.recv(65536)
            except (TimeoutError, ConnectionResetError):
                return RawResponse(None, bytes(data), disconnected=True)
            require(time.monotonic() < cutoff)
            if not chunk:
                break
            data.extend(chunk)
            require(len(data) <= 25 * 1024 * 1024)
    if b"\r\n\r\n" not in data:
        return RawResponse(None, bytes(data), disconnected=True)
    raw_header, body = bytes(data).split(b"\r\n\r\n", 1)
    lines = raw_header.decode("ascii").split("\r\n")
    status = int(lines[0].split(" ")[1])
    response_headers = dict(line.lower().split(": ", 1) for line in lines[1:])
    incomplete = "content-length" in response_headers and len(body) != int(
        response_headers["content-length"]
    )
    return RawResponse(
        status, body, MappingProxyType(response_headers), disconnected=incomplete
    )
