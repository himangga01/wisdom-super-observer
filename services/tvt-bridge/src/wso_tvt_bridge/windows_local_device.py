"""Private operator integration for one Android local serial discovery/open attempt.

No actor or credential grant is created. Raw request/context/greeting remain private.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol

from wso_core.tvt.local_bootstrap import TrustedAndroidRuntime, select_local_bootstrap

from . import windows_android_probe as custody

PACKAGE = "com.wso.tvt.localdevice"
ACTIVITY = "com.wso.tvt.local.LocalDeviceProbeActivity"
CAP = 4096
DATA_CAP = 10240
ROOT = Path(__file__).resolve().parents[4]
OWNED = (
    "services/tvt-android-helper/android-local-device/AndroidManifest.xml",
    "services/tvt-android-helper/android-local-device/src/com/wso/tvt/local/LocalDeviceProbeActivity.java",
    "services/tvt-android-helper/build-local-device-probe.ps1",
    "services/tvt-bridge/src/wso_tvt_bridge/windows_local_device.py",
    "tests/contract/test_windows_local_device.py",
    "docs/integrations/tvt-windows-local-device.md",
)


TRANSPORT_PATHS = (
    "services/tvt-android-helper/src/main/java/com/tvt/network/NatTraveral.java",
    "services/tvt-android-helper/src/main/java/com/wso/tvt/local/LocalSerialConfig.java",
    "services/tvt-android-helper/src/main/java/com/wso/tvt/local/LocalSerialDriver.java",
    "services/tvt-android-helper/src/main/java/com/wso/tvt/local/JniLocalSerialDriver.java",
    "services/tvt-android-helper/src/main/java/com/wso/tvt/local/LocalSerialTransport.java",
    "services/tvt-android-helper/tests/LocalSerialTransportTest.java",
    "services/tvt-android-helper/verify-local-host.ps1",
    "docs/integrations/tvt-local-serial-transport.md",
)
BOOTSTRAP_PATHS = (
    "packages/core/src/wso_core/tvt/local_bootstrap.py",
    "tests/tvt_parity/test_local_bootstrap.py",
    "docs/integrations/tvt-local-bootstrap-profile.md",
)


def _read_json_file(path: Path, cap: int) -> dict[str, object]:
    identity = custody._identity(path, directory=False)
    if not 0 < path.stat().st_size <= cap:
        raise ValueError("Private file bound exceeded")
    with path.open("rb") as stream:
        raw = stream.read(cap + 1)
    if custody._identity(path, directory=False) != identity:
        raise ValueError("Private file replaced")
    return custody._json(raw, cap)


@dataclass(frozen=True, slots=True, repr=False)
class PrivateDeviceRequest:
    serial: str
    country_code: str
    generation: str
    budget_millis: int = 40000
    greeting_millis: int = 5000
    greeting_bytes: int = DATA_CAP

    def __post_init__(self) -> None:
        if (
            type(self.serial) is not str
            or not re.fullmatch(r"[A-Za-z0-9]{1,63}", self.serial)
            or type(self.generation) is not str
            or not re.fullmatch(r"[a-f0-9]{32}", self.generation)
            or type(self.country_code) is not str
            or not re.fullmatch(r"(?:[A-Z]{2})?", self.country_code)
            or self.country_code in ("AP", "EU")
            or type(self.budget_millis) is not int
            or not 1000 <= self.budget_millis <= 120000
            or type(self.greeting_millis) is not int
            or not 1 <= self.greeting_millis <= 5000
            or self.greeting_millis >= self.budget_millis
            or type(self.greeting_bytes) is not int
            or not 1 <= self.greeting_bytes <= DATA_CAP
        ):
            raise ValueError("Invalid private operator request")
        object.__setattr__(self, "serial", self.serial.upper())


def parse_context(raw: bytes, generation: str) -> TrustedAndroidRuntime:
    value = custody._json(raw, CAP)
    if (
        set(value)
        != {
            "schemaVersion",
            "version",
            "generation",
            "privateFilesPath",
            "singleId",
            "sourceNetworkType",
        }
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["version"] != "local-device-1"
        or value["generation"] != generation
        or type(value["singleId"]) is not str
        or not re.fullmatch(r"[0-9a-fA-F]{32}", value["singleId"])
        or value["privateFilesPath"]
        not in (
            "/data/user/0/" + PACKAGE + "/files",
            "/data/data/" + PACKAGE + "/files",
        )
        or type(value["sourceNetworkType"]) is not int
        or value["sourceNetworkType"] not in (0, 2, 3, 4, 5)
    ):
        raise ValueError("Invalid trusted private context")
    return TrustedAndroidRuntime(
        str(value["privateFilesPath"]),
        str(value["singleId"]),
        int(value["sourceNetworkType"]),
    )


def private_packet(request: PrivateDeviceRequest, context_raw: bytes) -> bytes:
    runtime = parse_context(context_raw, request.generation)
    profile = select_local_bootstrap(
        country_code=request.country_code, runtime=runtime, attempt_branch="initial"
    )
    value = {
        "schemaVersion": 1,
        "version": "local-device-1",
        "generation": request.generation,
        "serial": request.serial,
        "countryCode": request.country_code,
        "budgetMillis": request.budget_millis,
        "greetingMillis": request.greeting_millis,
        "greetingBytes": request.greeting_bytes,
        "profile": json.loads(profile.private_helper_json()),
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > CAP:
        raise ValueError("Private request bound exceeded")
    return raw


def parse_result(raw: bytes, generation: str, greeting_cap: int) -> dict[str, object]:
    value = custody._json(raw, CAP)
    if (
        set(value)
        != {
            "schemaVersion",
            "version",
            "generation",
            "stage",
            "failure",
            "deviceType",
            "nativeError",
            "transportOpen",
            "greetingBytes",
            "cleanup",
            "authenticated",
            "live",
        }
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["version"] != "local-device-1"
        or value["generation"] != generation
        or value["stage"]
        not in (
            "validated",
            "bootstrap",
            "discover",
            "open",
            "greeting",
            "cleanup",
            "complete",
            "deadline",
        )
        or value["failure"]
        not in (
            "none",
            "invalid",
            "linkage",
            "runtime",
            "io",
            "unsupported",
            "open_failed",
            "receive_failed",
            "deadline",
        )
        or type(value["deviceType"]) is not int
        or not -(2**31) <= value["deviceType"] < 2**31
        or type(value["nativeError"]) is not int
        or not -(2**31) <= value["nativeError"] < 2**31
        or type(value["transportOpen"]) is not bool
        or type(value["greetingBytes"]) is not int
        or not 0 <= value["greetingBytes"] <= greeting_cap
        or value["cleanup"] not in ("not_started", "pending", "closed", "quarantined")
        or value["authenticated"] is not False
        or value["live"] is not False
        or (value["transportOpen"] and value["deviceType"] not in (3, 10001, 20001))
        or (value["greetingBytes"] > 0 and not value["transportOpen"])
        or (
            value["stage"] == "complete"
            and value["cleanup"] not in ("closed", "quarantined")
        )
    ):
        raise ValueError("Invalid private safe result")
    return value


@dataclass(frozen=True, slots=True)
class DeviceProbeConfig:
    adb: Path
    build_result: Path
    review_receipt: Path
    image_purpose: str
    staging_root: Path
    runtime_profile: str
    command_seconds: float = 15.0
    _target: custody.ProbeConfig = field(init=False, repr=False)

    def __post_init__(self) -> None:
        target = custody.ProbeConfig(
            self.adb,
            self.build_result,
            self.image_purpose,
            self.staging_root,
            self.runtime_profile,
            command_seconds=self.command_seconds,
        )
        if not self.review_receipt.is_absolute():
            raise ValueError("Explicit independent review required")
        object.__setattr__(self, "_target", target)


class Runner(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        timeout: float,
        *,
        max_bytes: int = CAP,
        input_bytes: bytes | None = None,
    ) -> custody.CommandOutcome: ...


@dataclass(slots=True)
class _OwnedCommand:
    record: dict[str, object]
    expected: tuple[str, ...]
    started: float
    child: subprocess.Popen[bytes] | None = None
    streams: dict[str, BinaryIO | None] = field(default_factory=dict)
    captured_streams: set[str] = field(default_factory=set)
    candidates: dict[str, threading.Thread] = field(default_factory=dict)
    workers: dict[str, threading.Thread] = field(default_factory=dict)
    started_workers: list[threading.Thread] = field(default_factory=list)
    uncertain_starts: set[str] = field(default_factory=set)
    close_attempted: set[str] = field(default_factory=set)
    failed: threading.Event = field(default_factory=threading.Event)


def _thread_admitted(thread: threading.Thread) -> bool:
    # This project pins CPython3.12. Thread.start waits on this exact admission
    # event; ident/is_alive alone cannot prove a start interrupted during bootstrap.
    admission = getattr(thread, "_started", None)
    return bool(admission is not None and admission.is_set())


class PrivateRunner:
    """Own the returned original Popen and streams before admitting any I/O worker."""

    def __init__(self) -> None:
        self.children: list[subprocess.Popen[bytes]] = []
        self.owners: list[tuple[subprocess.Popen[bytes], list[threading.Thread]]] = []
        self._obligations: list[_OwnedCommand] = []
        self.blocked = False
        self._ownership_lock = threading.Lock()
        self._completion_threads: list[threading.Thread] = []
        self.receipts: list[dict[str, object]] = []

    def run(
        self,
        argv: tuple[str, ...],
        timeout: float,
        *,
        max_bytes: int = CAP,
        input_bytes: bytes | None = None,
    ) -> custody.CommandOutcome:
        if max_bytes not in (CAP, DATA_CAP, custody.UID_CAP) or (
            input_bytes is not None and len(input_bytes) > CAP
        ):
            raise ValueError("Fixed private capture/input bound required")
        if self.blocked or any(child.poll() is None for child in self.children):
            raise OSError("Outstanding owned child prevents next command")
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
        }
        captured = bytearray()
        overflow = threading.Event()
        started = time.monotonic()
        record: dict[str, object] = {
            "argv": list(argv),
            "elapsed": 0.0,
            "exit": None,
            "spawned": False,
            "timedOut": False,
            "reaped": False,
            "killFailed": False,
            "killAttempted": False,
            "ownershipRetained": False,
            "inputPresent": input_bytes is not None,
            "overflow": False,
            "pipeFailed": False,
            "setupStage": "spawn",
            "setupFailure": "none",
            "startedWorkers": [],
            "unknownStartWorkers": [],
            "captureIncomplete": False,
        }
        expected = (
            ("stdout", "stderr", "stdin")
            if input_bytes is not None
            else ("stdout", "stderr")
        )
        owner = _OwnedCommand(
            record,
            expected,
            started,
            streams={name: None for name in ("stdout", "stderr", "stdin")},
        )
        # Allocate and retain the obligation/receipt before acquiring the child. The
        # returned original handle binds directly to this already-retained owner.
        self._obligations.append(owner)
        self.receipts.append(record)
        self.blocked = True
        error: BaseException | None = None

        def drain(pipe: BinaryIO | None, retain: bool) -> None:
            assert pipe is not None
            count = 0
            try:
                while chunk := pipe.read(1024):
                    count += len(chunk)
                    if retain:
                        captured.extend(chunk[: max(0, max_bytes - len(captured))])
                    if count > (max_bytes if retain else CAP):
                        overflow.set()
            except BaseException:  # noqa: BLE001 - retained custody includes interruption
                owner.failed.set()
            finally:
                try:
                    pipe.close()
                except BaseException:  # noqa: BLE001 - retained custody includes interruption
                    owner.failed.set()

        def feed() -> None:
            pipe = owner.streams["stdin"]
            assert pipe is not None and input_bytes is not None
            try:
                pipe.write(input_bytes)
                pipe.flush()
            except BaseException:  # noqa: BLE001 - retained custody includes interruption
                owner.failed.set()
            finally:
                try:
                    pipe.close()
                except BaseException:  # noqa: BLE001 - retained custody includes interruption
                    owner.failed.set()

        try:
            owner.child = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE
                if input_bytes is not None
                else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            record["spawned"] = True
            record["ownershipRetained"] = True
            child = owner.child
            self.children.append(child)
            self.owners.append((child, owner.started_workers))
            self._capture_streams(owner)
            for name in expected:
                record["setupStage"] = name + "_construct"
                if owner.streams[name] is None:
                    raise OSError("Required owned stream missing")
                worker = threading.Thread(
                    target=feed if name == "stdin" else drain,
                    args=()
                    if name == "stdin"
                    else (owner.streams[name], name == "stdout"),
                    name="private-" + name,
                    daemon=True,
                )
                owner.candidates[name] = worker
                record["setupStage"] = name + "_start"
                try:
                    worker.start()
                except BaseException as admission_error:
                    if _thread_admitted(worker):
                        self._admit(owner, name, worker)
                    elif not isinstance(admission_error, Exception):
                        owner.uncertain_starts.add(name)
                    raise
                if not _thread_admitted(worker):
                    owner.uncertain_starts.add(name)
                    raise OSError("Worker admission not confirmed")
                self._admit(owner, name, worker)
            record["setupStage"] = "wait"
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["timedOut"] = True
                self._terminate_once(owner)
            for worker in tuple(owner.started_workers):
                worker.join(timeout=1)
            record["setupStage"] = "observe"
        except BaseException as caught:  # noqa: BLE001 - retained custody includes interruption
            error = caught
            record["setupFailure"] = (
                "interrupted" if not isinstance(caught, Exception) else "host_setup"
            )
            record["captureIncomplete"] = True
            if owner.child is not None:
                self._capture_streams(owner)
                self._refresh_workers(owner)
                # An unadmitted stdin has no writer to race; close that original
                # stream to provide EOF. Never abort a possibly started writer.
                if (
                    "stdin" not in owner.workers
                    and "stdin" not in owner.uncertain_starts
                ):
                    self._close_original(owner, "stdin")
                self._terminate_once(owner)
        finally:
            if owner.child is None:
                self.blocked = False
            else:
                if error is not None:
                    self._terminate_once(owner)
                # Even an interruption while taking the bounded observation must
                # hand off this already-acquired obligation before leaving scope.
                self.blocked = True
                record["spawned"] = True
                record["ownershipRetained"] = True
                try:
                    self._capture_streams(owner)
                    self._refresh_workers(owner)
                    exit_code = owner.child.poll()
                    reaped = (
                        exit_code is not None
                        and len(owner.captured_streams) == 3
                        and not owner.uncertain_starts
                        and set(owner.workers) == set(expected)
                        and all(
                            pipe is None or pipe.closed
                            for pipe in owner.streams.values()
                        )
                        and all(
                            not worker.is_alive() for worker in owner.started_workers
                        )
                    )
                    record.update(
                        elapsed=time.monotonic() - started,
                        exit=exit_code,
                        reaped=reaped,
                        ownershipRetained=not reaped,
                        overflow=overflow.is_set(),
                        pipeFailed=owner.failed.is_set(),
                        startedWorkers=list(owner.workers),
                        unknownStartWorkers=sorted(owner.uncertain_starts),
                    )
                    self.blocked = not reaped
                except BaseException as observation_error:  # noqa: BLE001 - retained custody includes interruption
                    record["ownerObservationFailed"] = True
                    record["captureIncomplete"] = True
                    if error is None:
                        error = observation_error
                    self._terminate_once(owner)
                finally:
                    if self.blocked:
                        self._retain(owner)
        if error is not None and (
            owner.child is None or not isinstance(error, Exception)
        ):
            raise error
        return custody.CommandOutcome(
            owner.child.poll() if owner.child is not None else None,
            bytes(captured),
            bool(record["timedOut"]),
            bool(record["reaped"]),
            overflow.is_set() or owner.failed.is_set(),
        )

    @staticmethod
    def _capture_streams(owner: _OwnedCommand) -> None:
        if owner.child is None:
            return
        for name in ("stdout", "stderr", "stdin"):
            if name not in owner.captured_streams:
                try:
                    owner.streams[name] = getattr(owner.child, name)
                    owner.captured_streams.add(name)
                except BaseException:  # noqa: BLE001 - retained custody includes interruption
                    owner.record["ownerObservationFailed"] = True

    @staticmethod
    def _admit(owner: _OwnedCommand, name: str, worker: threading.Thread) -> None:
        if name not in owner.workers:
            owner.workers[name] = worker
            owner.started_workers.append(worker)
        owner.uncertain_starts.discard(name)

    @classmethod
    def _refresh_workers(cls, owner: _OwnedCommand) -> None:
        for name, worker in owner.candidates.items():
            if _thread_admitted(worker):
                cls._admit(owner, name, worker)

    @staticmethod
    def _close_original(owner: _OwnedCommand, name: str) -> bool:
        pipe = owner.streams[name]
        if pipe is None:
            return True
        try:
            if pipe.closed:
                return True
            if name in owner.close_attempted:
                return False
            owner.close_attempted.add(name)
            pipe.close()
            return bool(pipe.closed)
        except BaseException:  # noqa: BLE001 - retained custody includes interruption
            owner.record["ownerStreamReleaseFailed"] = True
            return False

    @staticmethod
    def _terminate_once(owner: _OwnedCommand) -> None:
        if owner.child is None or owner.record["killAttempted"]:
            return
        # Guard precedes the syscall; interruption or uncertain failure cannot permit retry.
        owner.record["killAttempted"] = True
        try:
            owner.child.kill()
        except BaseException:  # noqa: BLE001 - retained custody includes interruption
            owner.record["killFailed"] = True
        try:
            owner.child.wait(timeout=2)
        except BaseException:  # noqa: BLE001 - retained custody includes interruption
            owner.record["ownerReapUncertain"] = True

    def _retain(self, owner: _OwnedCommand) -> None:
        try:
            completion = threading.Thread(
                target=self._observe_completion,
                args=(owner,),
                name="private-child-owner",
                daemon=False,
            )
            try:
                completion.start()
            except BaseException:
                if _thread_admitted(completion):
                    self._completion_threads.append(completion)
                    return
                raise
        except BaseException:  # noqa: BLE001 - retained custody includes interruption
            owner.record["ownerThreadStartFailed"] = True
            self._observe_completion(owner)
        else:
            self._completion_threads.append(completion)

    def _observe_completion(self, owner: _OwnedCommand) -> None:
        # Only original handles/candidates are observed. No PID lookup or kill retry.
        assert owner.child is not None
        while True:
            try:
                self._capture_streams(owner)
                self._refresh_workers(owner)
                exit_code = owner.child.poll()
                if (
                    exit_code is not None
                    and len(owner.captured_streams) == 3
                    and not owner.uncertain_starts
                    and all(not worker.is_alive() for worker in owner.started_workers)
                ):
                    for worker in owner.started_workers:
                        worker.join()
                    released = True
                    for name, pipe in owner.streams.items():
                        if name not in owner.workers:
                            released = self._close_original(owner, name) and released
                        elif pipe is not None and not pipe.closed:
                            released = False
                    if released:
                        with self._ownership_lock:
                            owner.record.update(
                                ownerCompletionObserved=time.time(),
                                ownerCompletionElapsed=time.monotonic() - owner.started,
                                ownerExit=exit_code,
                                ownerReaped=True,
                                ownerWorkersCompleted=True,
                                ownerStreamsReleased=True,
                                ownerStartedWorkers=list(owner.workers),
                                ownerUnadmittedStreams=[
                                    n for n in owner.expected if n not in owner.workers
                                ],
                                ownerPipesCompleted=set(owner.workers)
                                == set(owner.expected)
                                and not owner.failed.is_set(),
                            )
                            self.blocked = False
                        return
                time.sleep(0.1)
            except BaseException:  # noqa: BLE001 - retained custody includes interruption
                owner.record["ownerObservationFailed"] = True

    def wait_for_ownership(self) -> None:
        """Wait for original ownership completion without another termination attempt."""
        for worker in tuple(self._completion_threads):
            worker.join()


class _DefaultRunnerSupervisor:
    """Process-lifetime lease/fence and private sanitized original receipts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: PrivateRunner | None = None
        self._pending: list[PrivateRunner] = []
        self.receipt_history: list[list[dict[str, object]]] = []

    def acquire(self) -> PrivateRunner:
        with self._lock:
            self._pending = [runner for runner in self._pending if runner.blocked]
            if self._active is not None or self._pending:
                raise OSError("Default host owner remains active or retained")
            runner = PrivateRunner()
            self._active = runner
            return runner

    def release(self, runner: PrivateRunner) -> None:
        with self._lock:
            if self._active is not runner:
                raise RuntimeError("Default host owner lease mismatch")
            # Dictionaries retain the original bounded observation plus passive completion;
            # private stdin/pipe contents and process/pipe handles never enter this history.
            if runner.receipts:
                self.receipt_history.append(runner.receipts)
            if runner.blocked:
                self._pending.append(runner)
            self._active = None

    def pending_owners(self) -> tuple[PrivateRunner, ...]:
        with self._lock:
            self._pending = [runner for runner in self._pending if runner.blocked]
            return tuple(self._pending)

    def wait_for_ownership(self) -> None:
        # CLI calls this even when printing/returning raises. Original owner threads also
        # keep normal interpreter shutdown alive if the API caller omits this explicit wait.
        while True:
            with self._lock:
                self._pending = [runner for runner in self._pending if runner.blocked]
                waiting = tuple(self._pending)
                active = self._active
            if active is None and not waiting:
                return
            for runner in waiting:
                runner.wait_for_ownership()
            if active is not None:
                active.wait_for_ownership()
                time.sleep(0.1)


_DEFAULT_SUPERVISOR = _DefaultRunnerSupervisor()


def wait_for_default_ownership() -> None:
    """Keep the operator process alive until original default children/pipes complete."""
    _DEFAULT_SUPERVISOR.wait_for_ownership()


def _load_reviewed(config: DeviceProbeConfig) -> custody._BuildArtifact:
    value = _read_json_file(config.build_result, 65536)
    receipt = _read_json_file(config.review_receipt, 65536)
    files = receipt.get("files")
    if (
        receipt.get("status") != "ACCEPTED_WINDOWS_LOCAL_DEVICE_ROOT_REVIEW"
        or not isinstance(files, dict)
        or set(files) != set(OWNED)
    ):
        raise ValueError("Independent exact six review required")
    for relative in OWNED:
        identity = files[relative]
        if not isinstance(identity, dict) or set(identity) != {"bytes", "sha256"}:
            raise ValueError("Reviewed identities required")
        path = ROOT / relative
        custody._identity(path, directory=False)
        if (
            path.stat().st_size != identity["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != identity["sha256"]
        ):
            raise ValueError("Reviewed source changed")
    if (
        value.get("package") != PACKAGE
        or value.get("status") != "BUILT_HOST_VERIFIED_DEVICE_NOT_EXECUTED"
        or value.get("schemaVersion") != 1
        or value.get("developmentKeyDeleted") is not True
        or any(
            value.get(k) is not True
            for k in (
                "developmentOnly",
                "signatureVerified",
                "manifestVerified",
                "nativeVerified",
            )
        )
        or value.get("sourceHashes") is None
        or value.get("deviceExecution") != "NOT_EXECUTED"
    ):
        raise ValueError("Reviewed build required")
    hashes = value["sourceHashes"]
    if not isinstance(hashes, dict):
        raise TypeError("Reviewed build required")
    for relative in OWNED[:3]:
        if hashes.get(str(ROOT / relative)) != files[relative]["sha256"]:
            raise ValueError("Built source differs from reviewed source")
    if (
        value.get("discoveryReceiptSha256")
        != hashlib.sha256(config.review_receipt.read_bytes()).hexdigest()
    ):
        raise ValueError("Built independent receipt changed")
    dependencies = value.get("dependencies")
    if (
        not isinstance(dependencies, dict)
        or set(dependencies) != {"transport", "bootstrap"}
        or dependencies != receipt.get("dependencies")
    ):
        raise ValueError("Explicit reviewed dependency maps required")
    for group, expected in (
        ("transport", TRANSPORT_PATHS),
        ("bootstrap", BOOTSTRAP_PATHS),
    ):
        mapping = dependencies[group]
        if not isinstance(mapping, dict) or set(mapping) != set(expected):
            raise ValueError("Exact reviewed dependencies required")
        for relative in expected:
            item = mapping[relative]
            if (
                not isinstance(item, dict)
                or set(item) != {"bytes", "sha256"}
                or type(item["bytes"]) is not int
                or type(item["sha256"]) is not str
            ):
                raise ValueError("Dependency identity required")
            dependency = ROOT / relative
            custody._identity(dependency, directory=False)
            if dependency.stat().st_size != item["bytes"]:
                raise ValueError("Reviewed dependency changed")
            with dependency.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                    raise ValueError("Reviewed dependency changed")
        if not re.fullmatch("[a-f0-9]{64}", str(value.get(group + "ReceiptSha256"))):
            raise ValueError("Reviewed receipt identity required")
    for relative in TRANSPORT_PATHS[:5]:
        if hashes.get(relative) != dependencies["transport"][relative]["sha256"]:
            raise ValueError("Built dependency source changed")
    path = Path(str(value.get("apk")))
    size = value.get("apkBytes")
    sha = value.get("apkSha256")
    if (
        not path.is_absolute()
        or type(size) is not int
        or not 0 < size <= 12000000
        or type(sha) is not str
        or not re.fullmatch("[a-f0-9]{64}", sha)
    ):
        raise ValueError("APK identity required")
    artifact = custody._BuildArtifact(path, size, sha)
    custody._verify_artifact(path, artifact)
    return artifact


def parse_local_device_uid(raw: bytes) -> int | None:
    """Adapt the exact owned package while exempting only scoped historical rows."""
    if not 0 < len(raw) <= custody.UID_CAP:
        raise ValueError("Bounded package inspection required")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    historical = False
    old = custody.PACKAGE
    # A blanket old-package substring check misclassified Google's Package Changes
    # history. Only the exact history row is exempt; scoped identities/absences,
    # other sections, suffixes and malformed rows retain the old guard.
    for line in text.splitlines():
        if line and not line[0].isspace():
            historical = line == "Package Changes:"
        if old in line and not (
            historical
            and re.fullmatch(r" +seq=[0-9]+, package=" + re.escape(old), line)
        ):
            raise ValueError("Wrong scoped package identity")
    # Accepted parser still owns all section, absence, header, UID and contradiction
    # checks. Only the new fixed spelling is substituted; it is never modified.
    return custody.parse_package_uid(raw.replace(PACKAGE.encode(), old.encode()))


@dataclass(slots=True)
class DeviceProbeResult:
    failure: str = "none"
    device: dict[str, object] = field(default_factory=dict)
    package_cleanup: str = "not_owned"
    staging_cleanup: str = "not_created"
    private_directory: str | None = None
    matched: int = 0
    release_ready: bool = False
    host_ownership: str = "confirmed"


class _Failure(Exception):
    pass


def run_device_probe(
    config: DeviceProbeConfig,
    request: PrivateDeviceRequest,
    *,
    runner: Runner | None = None,
) -> DeviceProbeResult:
    result = DeviceProbeResult()
    default_owner: PrivateRunner | None = None
    if runner is None:
        try:
            default_owner = _DEFAULT_SUPERVISOR.acquire()
        except OSError:
            result.failure = "host_owner_pending"
            result.host_ownership = "retained"
            return result
        boundary: Runner = default_owner
    else:
        boundary = runner
    target = config._target
    base = (
        str(config.adb),
        "-H",
        target.host,
        "-P",
        str(target.port),
        "-s",
        target.serial,
    )
    owned_uid = None
    install_attempted = False
    stage = None
    private_dir = None
    phase_deadline: float | None = None
    phase_timeout = "context_deadline"

    def remaining() -> float:
        if phase_deadline is None:
            return config.command_seconds
        left = phase_deadline - time.monotonic()
        if left <= 0:
            raise _Failure(phase_timeout)
        return min(config.command_seconds, left)

    def pause_readiness() -> None:
        time.sleep(min(0.1, remaining()))

    def command(
        *args: str, max_bytes: int = CAP, input_bytes: bytes | None = None
    ) -> bytes:
        outcome = boundary.run(
            base + args,
            remaining(),
            max_bytes=max_bytes,
            input_bytes=input_bytes,
        )
        if outcome.timed_out:
            raise _Failure("child_timeout")
        if not outcome.reaped:
            raise _Failure("child_unreaped")
        if outcome.overflow or len(outcome.stdout) > max_bytes:
            raise _Failure("child_output_bound")
        # A late successful child cannot extend or satisfy the original phase.
        remaining()
        if outcome.exit_code != 0:
            raise _Failure("child_failed")
        return outcome.stdout

    def uid() -> int | None:
        raw = command("shell", "dumpsys", "package", PACKAGE, max_bytes=custody.UID_CAP)
        try:
            return parse_local_device_uid(raw)
        except (ValueError, UnicodeError):
            raise _Failure("package_identity") from None

    def require_uid() -> None:
        if uid() != owned_uid:
            raise _Failure("package_identity")

    def read_file(name: str, cap: int = CAP) -> bytes:
        require_uid()
        raw = command(
            "exec-out", "run-as", PACKAGE, "cat", "files/" + name, max_bytes=cap
        )
        require_uid()
        if not raw and name in ("context.json", "result.json"):
            raise _Failure("child_failed")
        return raw

    def write_request(raw: bytes) -> None:
        require_uid()
        command(
            "exec-in",
            "run-as",
            PACKAGE,
            "sh",
            "-c",
            "umask 077; cat > files/request.json",
            input_bytes=raw,
        )
        # This is an argv script argument, not a host-shell quoted command.
        # Exec transport exit0 does not prove the remote write occurred. Admit
        # only exact privately read bytes under the same pre/post-read UID.
        delivered = read_file("request.json")
        if (
            len(delivered) != len(raw)
            or hashlib.sha256(delivered).digest() != hashlib.sha256(raw).digest()
            or delivered != raw
        ):
            raise _Failure("request_delivery")

    try:
        try:
            artifact = _load_reviewed(config)
        except (ValueError, OSError, TypeError, UnicodeError):
            raise _Failure("build_invalid") from None
        if command("shell", "getprop", "sys.boot_completed").strip() != b"1":
            raise _Failure("boot_not_ready")
        expected_sdk = (
            b"24" if target.runtime_profile == "aosp-arm-development" else b"30"
        )
        if command("shell", "getprop", "ro.build.version.sdk").strip() != expected_sdk:
            raise _Failure("profile_mismatch")
        abis = command("shell", "getprop", "ro.product.cpu.abilist").strip().split(b",")
        expected_abi = b"armeabi-v7a" if expected_sdk == b"24" else b"arm64-v8a"
        if expected_abi not in abis:
            raise _Failure("abi_missing")
        if uid() is not None or uid() is not None:
            raise _Failure("package_present")
        stage = custody._Staging(
            config.staging_root,
            config.staging_root / ("probe-" + uuid.uuid4().hex),
            artifact,
            target._staging_identity,
        )
        custody._copy_to_stage(stage)
        custody._verify_stage(stage)
        install_attempted = True
        if not custody.is_install_success(
            command("install", "--no-streaming", stage.apk.as_posix())
        ):
            raise _Failure("install_uncertain")
        owned_uid = uid()
        if owned_uid is None:
            raise _Failure("install_uncertain")
        result.package_cleanup = "uncertain"
        custody._verify_stage(stage)
        # Owned root created with bounded literal name; Windows inherited ACL is a Root prerequisite.
        private_dir = config.staging_root / ("device-" + request.generation)
        private_dir.mkdir(mode=0o700)
        private_identity = custody._identity(private_dir, directory=True)
        result.private_directory = str(private_dir)
        phase_deadline = time.monotonic() + 5
        require_uid()
        command(
            "shell",
            "am",
            "start",
            "-n",
            PACKAGE + "/" + ACTIVITY,
            "--es",
            "phase",
            "context",
            "--es",
            "generation",
            request.generation,
        )
        while True:
            try:
                context_raw = read_file("context.json")
                # File presence and launch acknowledgement are not readiness.
                # Only current UID + exact generation/schema admit the factory.
                packet = private_packet(request, context_raw)
            except _Failure as missing:
                if str(missing) != "child_failed":
                    raise
            except (ValueError, UnicodeError, TypeError):
                # Absent, partial, stale and invalid snapshots never admit input.
                pass
            else:
                remaining()
                break
            pause_readiness()
        phase_deadline = None
        for name, raw in (("context.json", context_raw), ("request.json", packet)):
            with (private_dir / name).open("xb") as stream:
                stream.write(raw)
        write_request(packet)
        phase_timeout = "helper_deadline"
        phase_deadline = time.monotonic() + (request.budget_millis + 10000) / 1000
        require_uid()
        command(
            "shell",
            "am",
            "start",
            "-n",
            PACKAGE + "/" + ACTIVITY,
            "--es",
            "phase",
            "attempt",
            "--es",
            "generation",
            request.generation,
        )
        while True:
            try:
                raw = read_file("result.json")
                observed = parse_result(raw, request.generation, request.greeting_bytes)
            except _Failure as missing:
                if str(missing) != "child_failed":
                    raise
            except (ValueError, UnicodeError, TypeError):
                pass
            else:
                remaining()
                result.device = observed
                if observed["stage"] in ("complete", "deadline"):
                    break
            pause_readiness()
        phase_deadline = None
        count = result.device["greetingBytes"]
        if count:
            greeting = read_file("greeting.bin", DATA_CAP)
            if len(greeting) != count:
                raise _Failure("greeting_identity")
            with (private_dir / "greeting.bin").open("xb") as stream:
                stream.write(greeting)
        if custody._identity(private_dir, directory=True) != private_identity:
            raise _Failure("private_identity")
        result.failure = (
            "none" if result.device["failure"] == "none" else "device_stage_failed"
        )
    except (_Failure, ValueError, OSError, UnicodeError, TypeError) as failure:
        result.failure = (
            str(failure)
            if isinstance(failure, _Failure)
            else "private_boundary_invalid"
        )
    finally:
        # Readiness expiry never authorizes unknown-UID cleanup or disables the
        # original bounded child/stream custody and package cleanup checks.
        phase_deadline = None
        if install_attempted and owned_uid is None:
            result.package_cleanup = "uncertain"
        if owned_uid is not None:
            try:
                require_uid()
                command("shell", "am", "force-stop", PACKAGE)
                require_uid()
                if (
                    command("uninstall", PACKAGE).strip() != b"Success"
                    or uid() is not None
                ):
                    raise _Failure("cleanup_uncertain")
                result.package_cleanup = "confirmed_absent"
            except (_Failure, ValueError, OSError):
                result.package_cleanup = "uncertain"
        if stage is not None:
            try:
                if result.package_cleanup != "confirmed_absent":
                    raise ValueError("uncertain package")
                custody._remove_stage(stage)
                result.staging_cleanup = "removed"
            except (ValueError, OSError):
                result.staging_cleanup = "retained_uncertain"
        if isinstance(boundary, PrivateRunner) and boundary.blocked:
            result.host_ownership = "retained"
        if default_owner is not None:
            _DEFAULT_SUPERVISOR.release(default_owner)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("adb", "build-result", "review-receipt", "staging-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--runtime-profile",
        choices=("google-translation-development", "aosp-arm-development"),
        required=True,
    )
    args = parser.parse_args()
    config = DeviceProbeConfig(
        args.adb,
        args.build_result,
        args.review_receipt,
        "development-debug",
        args.staging_root,
        args.runtime_profile,
    )
    if os.name != "nt" or not config.adb.is_file():
        parser.error("Existing Windows runtime required")
    value = custody._json(sys.stdin.buffer.read(CAP + 1), CAP)
    if set(value) != {
        "serial",
        "country_code",
        "generation",
        "budget_millis",
        "greeting_millis",
        "greeting_bytes",
    }:
        parser.error("Exact private stdin request required")
    request = PrivateDeviceRequest(**value)  # type: ignore[arg-type]
    try:
        result = run_device_probe(config, request)
        print(json.dumps(asdict(result), separators=(",", ":")), flush=True)
        return (
            0
            if result.failure == "none"
            and result.package_cleanup == "confirmed_absent"
            and result.staging_cleanup == "removed"
            else 1
        )
    finally:
        wait_for_default_ownership()


if __name__ == "__main__":
    raise SystemExit(main())
