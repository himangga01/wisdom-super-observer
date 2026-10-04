"""Fixed Windows development probe controller. Never owns ADB or the VM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol

PACKAGE = "com.wso.tvt.localprobe"
ACTIVITY = "com.wso.tvt.probe.LocalLoadProbeActivity"
CAP = 4096
UID_CAP = 65536
STAGES = frozenset(
    (
        "created",
        "reflection",
        "load",
        "bootstrap",
        "allocate",
        "remove_callbacks",
        "interrupt",
        "destroy",
        "complete",
    )
)
FAILURES = frozenset(
    (
        "none",
        "linkage",
        "reflection",
        "security",
        "runtime",
        "allocation_zero",
        "io",
        "unknown",
    )
)
FLAGS = (
    "is64bit",
    "loaded",
    "descriptorsMatched",
    "bootstrapped",
    "allocationObserved",
    "callbacksRemoved",
    "interruptRequested",
    "destroyRequested",
    "cleanupProven",
)


@dataclass(frozen=True, slots=True)
class ProbeConfig:
    adb: Path
    build_result: Path
    image_purpose: str
    staging_root: Path
    _staging_identity: tuple[int, int] = field(init=False, repr=False)
    runtime_profile: str = "google-translation-development"
    host: str = field(default="127.0.0.1", init=False)
    port: int = field(default=5038, init=False)
    serial: str = field(default="emulator-5580", init=False)
    command_seconds: float = 15.0
    probe_seconds: float = 45.0

    def __post_init__(self) -> None:
        if (
            self.image_purpose != "development-debug"
            or self.runtime_profile
            not in ("google-translation-development", "aosp-arm-development")
            or not self.adb.is_absolute()
            or self.adb.name.lower() != "adb.exe"
            or not self.build_result.is_absolute()
            or not 0 < self.command_seconds <= 30
            or not 0 < self.probe_seconds <= 120
        ):
            raise ValueError("Fixed development probe target required")
        object.__setattr__(
            self, "_staging_identity", _validate_staging_root(self.staging_root)
        )
        if self.runtime_profile == "aosp-arm-development":
            object.__setattr__(self, "port", 5039)
            object.__setattr__(self, "serial", "emulator-5590")


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    exit_code: int | None
    stdout: bytes
    timed_out: bool
    reaped: bool
    overflow: bool = False


class Runner(Protocol):
    def run(
        self, argv: tuple[str, ...], timeout: float, *, max_bytes: int = CAP
    ) -> CommandOutcome: ...


class ChildRunner:
    """Drain privately, retain handles, cap both pipes, kill only our child."""

    def __init__(self) -> None:
        self.children: list[subprocess.Popen[bytes]] = []
        self.receipts: list[dict[str, object]] = []

    def run(
        self, argv: tuple[str, ...], timeout: float, *, max_bytes: int = CAP
    ) -> CommandOutcome:
        if max_bytes not in (CAP, UID_CAP):
            raise ValueError("Fixed capture bound required")
        # Explicit remote -H 127.0.0.1 prevents this installed ADB's server start.
        # The supervisor owns the already running loopback server.
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
        }
        started = time.time()
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.children.append(child)
        captured = bytearray()
        overflow = threading.Event()

        def drain(pipe: BinaryIO | None, retain: bool) -> None:
            assert pipe is not None
            count = 0
            try:
                while True:
                    chunk = pipe.read(1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if retain:
                        captured.extend(chunk[: max(0, max_bytes - len(captured))])
                    if count > (max_bytes if retain else CAP):
                        overflow.set()
            finally:
                pipe.close()

        threads = [
            threading.Thread(target=drain, args=(child.stdout, True), daemon=True),
            threading.Thread(target=drain, args=(child.stderr, False), daemon=True),
        ]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        for thread in threads:
            thread.join(timeout=1)
        reaped = child.poll() is not None and all(not t.is_alive() for t in threads)
        self.receipts.append(
            {
                "argv": list(argv),
                "started": started,
                "ended": time.time(),
                "exit": child.poll(),
                "timedOut": timed_out,
                "reaped": reaped,
                "overflow": overflow.is_set(),
                "stdoutByteLimit": max_bytes,
                "stderrByteLimit": CAP,
            }
        )
        return CommandOutcome(
            child.poll(), bytes(captured), timed_out, reaped, overflow.is_set()
        )


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _json(raw: bytes, cap: int) -> dict[str, object]:
    if not 0 < len(raw) <= cap:
        raise ValueError("Bounded JSON required")
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs)
    if type(value) is not dict:
        raise ValueError("JSON object required")
    return value


def parse_device_result(raw: bytes) -> dict[str, object]:
    value = _json(raw, CAP)
    expected = set(FLAGS) | {"schemaVersion", "version", "abi", "stage", "failure"}
    if (
        set(value) != expected
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["version"] != "local-nat-probe-1"
        or any(type(value[key]) is not str for key in ("abi", "stage", "failure"))
        or value["abi"] not in ("arm64-v8a", "armeabi-v7a", "unknown")
        or value["stage"] not in STAGES
        or value["failure"] not in FAILURES
        or any(type(value[key]) is not bool for key in FLAGS)
        or value["cleanupProven"] is not False
    ):
        raise ValueError("Invalid fixed probe schema")
    chain = (
        "loaded",
        "bootstrapped",
        "allocationObserved",
        "callbacksRemoved",
        "interruptRequested",
        "destroyRequested",
    )
    if any(value[chain[i]] and not value[chain[i - 1]] for i in range(1, len(chain))):
        raise ValueError("Impossible stage evidence")
    if value["bootstrapped"] and not value["descriptorsMatched"]:
        raise ValueError("Unreviewed bootstrap")
    if (
        value["stage"] == "complete"
        and value["failure"] == "none"
        and not value["destroyRequested"]
    ):
        raise ValueError("Incomplete success evidence")
    return value


def _supported_package_absence(text: str) -> bool:
    absent = "  Unable to find package: " + PACKAGE
    if text.strip() == "Dexopt state:\n" + absent:
        return True
    # Exact API30 top-level section grammar from root's captured stock image.
    headings = (
        "Queries:",
        "Package Changes:",
        "Dexopt state:",
        "Compiler stats:",
        "APEX session state:",
        "Active APEX packages:",
        "Inactive APEX packages:",
        "Factory APEX packages:",
    )
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line and not line[0].isspace():
            sections.append((line, []))
        elif line.strip():
            if not sections or not line.startswith("  "):
                return False
            sections[-1][1].append(line)
    if tuple(name for name, _ in sections) != headings:
        return False
    bodies = {name: lines for name, lines in sections}
    if bodies["Dexopt state:"] != [absent] or bodies["Compiler stats:"] != [absent]:
        return False
    if any(bodies[name] for name in headings[4:]):
        return False
    if any(
        "Unable to find package:" in line
        for name in headings[:2]
        for line in bodies[name]
    ):
        return False
    return not re.search(
        r"^\s*(?:Package\s+\[|userId(?:=|\s|$)|pkg=Package|applicationInfo=ApplicationInfo)",
        text,
        re.MULTILINE,
    )


def parse_package_uid(raw: bytes) -> int | None:
    """Only the exact Packages block owns a UID; shared-user sections do not."""
    if not 0 < len(raw) <= UID_CAP:
        raise ValueError("Bounded package inspection required")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if "\r" in text or "\x00" in text:
        raise ValueError("Malformed package inspection")
    if re.search(
        r"^\s*(?:Error:|Unknown option:|Failure\b|Exception\b)", text, re.MULTILINE
    ):
        raise ValueError("Package inspection failed")
    if _supported_package_absence(text):
        return None
    if "Unable to find package:" in text or re.search(
        r"^(?:Error:|Unknown option:)", text, re.MULTILINE
    ):
        raise ValueError("Package inspection failed")
    markers = list(
        re.finditer(r"^  Package \[([^\]\n]+)\] \([0-9a-f]+\):$", text, re.MULTILINE)
    )
    if (
        len(markers) != 1
        or len(re.findall(r"^  Package \[", text, re.MULTILINE)) != 1
        or markers[0].group(1) != PACKAGE
    ):
        raise ValueError("Exact package block required")
    marker = markers[0]
    if not text[: marker.start()].endswith("Packages:\n"):
        raise ValueError("Scoped package section required")
    block: list[str] = []
    for line in text[marker.end() :].splitlines()[1:]:
        if line and not line.startswith("    "):
            break
        block.append(line)
    uid_lines = [line for line in block if re.match(r"    userId(?:=|\s|$)", line)]
    match = (
        re.fullmatch(r"    userId=([0-9]{1,6})", uid_lines[0])
        if len(uid_lines) == 1
        else None
    )
    if not match or not 0 < int(match.group(1)) <= 999999:
        raise ValueError("Unique scoped package UID required")
    return int(match.group(1))


@dataclass(frozen=True, slots=True)
class _BuildArtifact:
    path: Path
    size: int
    sha256: str


def _identity(path: Path, *, directory: bool) -> tuple[int, int]:
    info = path.stat(follow_symlinks=False)
    if getattr(
        info, "st_file_attributes", 0
    ) & stat.FILE_ATTRIBUTE_REPARSE_POINT or not (
        stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    ):
        raise ValueError("Owned regular path required")
    return info.st_dev, info.st_ino


def _validate_staging_root(path: Path) -> tuple[int, int]:
    raw = str(path)
    if (
        not path.is_absolute()
        or path.drive.upper() != "C:"
        or not raw.isascii()
        or not 1 < len(raw) <= 120
        or len(path.parts) < 3
        or any(ord(char) < 32 for char in raw)
        or any(part == ".." or part.endswith((".", " ")) for part in path.parts[1:])
    ):
        raise ValueError("Explicit existing bounded ASCII local staging root required")
    try:
        for ancestor in (*path.parents, path):
            _identity(ancestor, directory=True)
        return _identity(path, directory=True)
    except OSError:
        raise ValueError("Existing owned staging root required") from None


def _verify_artifact(path: Path, artifact: _BuildArtifact) -> None:
    _identity(path, directory=False)
    if path.stat().st_size != artifact.size:
        raise ValueError("APK size changed")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != artifact.sha256:
            raise ValueError("APK digest changed")


def _load_build(path: Path) -> _BuildArtifact:
    with path.open("rb") as stream:
        value = _json(stream.read(65537), 65536)
    if (
        value.get("schemaVersion") != 1
        or value.get("status") != "BUILT_HOST_VERIFIED_DEVICE_NOT_EXECUTED"
        or value.get("package") != PACKAGE
        or any(
            value.get(key) is not True
            for key in (
                "developmentOnly",
                "signatureVerified",
                "manifestVerified",
                "nativeVerified",
            )
        )
        or type(value.get("apk")) is not str
        or type(value.get("apkBytes")) is not int
        or not 0 < value["apkBytes"] <= 12000000  # type: ignore[operator]
        or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("apkSha256")))
    ):
        raise ValueError("Reviewed development build metadata required")
    apk = Path(str(value["apk"]))
    if not apk.is_absolute() or apk.suffix != ".apk" or not apk.is_file():
        raise ValueError("Absolute APK required")
    artifact = _BuildArtifact(apk, int(str(value["apkBytes"])), str(value["apkSha256"]))
    _verify_artifact(apk, artifact)
    return artifact


@dataclass(slots=True)
class _Staging:
    root: Path
    directory: Path
    artifact: _BuildArtifact
    root_identity: tuple[int, int]
    directory_identity: tuple[int, int] | None = None
    file_identity: tuple[int, int] | None = None

    @property
    def apk(self) -> Path:
        return self.directory / "probe.apk"


def _copy_to_stage(stage: _Staging) -> None:
    if _validate_staging_root(stage.root) != stage.root_identity:
        raise ValueError("Staging root changed")
    stage.directory.mkdir(mode=0o700)
    stage.directory_identity = _identity(stage.directory, directory=True)
    _verify_artifact(stage.artifact.path, stage.artifact)
    with stage.artifact.path.open("rb") as source, stage.apk.open("xb") as output:
        info = os.fstat(output.fileno())
        stage.file_identity = (info.st_dev, info.st_ino)
        remaining = stage.artifact.size
        while remaining:
            chunk = source.read(min(remaining, 65536))
            if not chunk:
                raise ValueError("Source APK changed during copy")
            output.write(chunk)
            remaining -= len(chunk)
        if source.read(1):
            raise ValueError("Source APK exceeded accepted bound")
        output.flush()
        os.fsync(output.fileno())
    _verify_artifact(stage.artifact.path, stage.artifact)
    _verify_stage(stage)


def _verify_stage(stage: _Staging) -> None:
    if (
        stage.directory.parent != stage.root
        or not re.fullmatch(r"probe-[0-9a-f]{32}", stage.directory.name)
        or _validate_staging_root(stage.root) != stage.root_identity
        or _identity(stage.directory, directory=True) != stage.directory_identity
        or _identity(stage.apk, directory=False) != stage.file_identity
    ):
        raise ValueError("Staged artifact ownership changed")
    _verify_artifact(stage.apk, stage.artifact)


def _remove_stage(stage: _Staging) -> None:
    _verify_stage(stage)
    # Read at most two names. Any extra entry prevents deletion; never recurse.
    with os.scandir(stage.directory) as contents:
        first = next(contents, None)
        second = next(contents, None)
    if first is None or first.name != "probe.apk" or second is not None:
        raise ValueError("Owned staging directory contents changed")
    stage.apk.unlink()
    stage.directory.rmdir()


def is_install_success(raw: bytes) -> bool:
    return bool(
        re.fullmatch(rb"(?:Performing Push Install\r?\n)?Success(?:\r?\n)?", raw)
    )


@dataclass(slots=True)
class ProbeResult:
    schema_version: int = 1
    purpose: str = "development-debug"
    runtime_profile: str = "google-translation-development"
    failure: str = "none"
    package_owned: bool = False
    package_cleanup: str = "not_owned"
    native_cleanup: str = "unproved"
    staging_directory: str | None = None
    staging_cleanup: str = "not_created"
    device: dict[str, object] = field(default_factory=dict)
    matched: int = 0
    release_ready: bool = False


class _Failure(Exception):
    pass


def run_probe(config: ProbeConfig, *, runner: Runner | None = None) -> ProbeResult:
    result = ProbeResult(runtime_profile=config.runtime_profile)
    boundary = runner or ChildRunner()
    base = (
        str(config.adb),
        "-H",
        config.host,
        "-P",
        str(config.port),
        "-s",
        config.serial,
    )
    owned_uid: int | None = None
    install_attempted = False
    stage: _Staging | None = None

    def command(*args: str, max_bytes: int = CAP) -> bytes:
        outcome = boundary.run(base + args, config.command_seconds, max_bytes=max_bytes)
        if outcome.timed_out:
            raise _Failure("child_timeout")
        if not outcome.reaped:
            raise _Failure("child_unreaped")
        if outcome.overflow or len(outcome.stdout) > max_bytes:
            raise _Failure("child_output_bound")
        if outcome.exit_code != 0:
            raise _Failure("child_failed")
        return outcome.stdout

    def uid() -> int | None:
        raw = command("shell", "dumpsys", "package", PACKAGE, max_bytes=UID_CAP)
        try:
            return parse_package_uid(raw)
        except (ValueError, UnicodeError):
            raise _Failure("package_identity") from None

    try:
        try:
            artifact = _load_build(config.build_result)
        except (ValueError, OSError, UnicodeError):
            raise _Failure("build_invalid") from None
        try:
            if _validate_staging_root(config.staging_root) != config._staging_identity:
                raise ValueError("Staging root changed")
        except (ValueError, OSError):
            raise _Failure("staging_invalid") from None
        if command("shell", "getprop", "sys.boot_completed").strip() != b"1":
            raise _Failure("boot_not_ready")
        sdk = command("shell", "getprop", "ro.build.version.sdk").strip()
        if not re.fullmatch(rb"[0-9]{1,3}", sdk) or int(sdk) < 23:
            raise _Failure("api_unsupported")
        abis = command("shell", "getprop", "ro.product.cpu.abilist").strip().split(b",")
        if b"arm64-v8a" not in abis and b"armeabi-v7a" not in abis:
            raise _Failure("abi_missing")
        if uid() is not None:
            raise _Failure("package_present")
        # Recheck immediately before the single non-replacing install.
        if uid() is not None:
            raise _Failure("package_present")
        stage = _Staging(
            config.staging_root,
            config.staging_root / ("probe-" + uuid.uuid4().hex),
            artifact,
            config._staging_identity,
        )
        result.staging_directory = str(stage.directory)
        try:
            _copy_to_stage(stage)
        except (ValueError, OSError):
            raise _Failure("staging_invalid") from None
        install_attempted = True
        if not is_install_success(
            command("install", "--no-streaming", stage.apk.as_posix())
        ):
            raise _Failure("install_uncertain")
        owned_uid = uid()
        if owned_uid is None:
            raise _Failure("install_uncertain")
        result.package_owned = True
        result.package_cleanup = "uncertain"
        try:
            _verify_stage(stage)
        except (ValueError, OSError):
            raise _Failure("staging_changed") from None
        command("shell", "am", "start", "-W", "-n", PACKAGE + "/" + ACTIVITY)
        deadline = time.monotonic() + config.probe_seconds
        while time.monotonic() < deadline:
            try:
                raw = command(
                    "exec-out", "run-as", PACKAGE, "cat", "files/probe-result.json"
                )
            except _Failure as failure:
                if str(failure) != "child_failed":
                    raise
            else:
                try:
                    result.device = parse_device_result(raw)
                except (ValueError, UnicodeError, TypeError):
                    raise _Failure("result_invalid") from None
                if result.device["failure"] != "none":
                    result.failure = "probe_failed"
                    break
                if result.device["stage"] == "complete":
                    break
            time.sleep(0.1)
        else:
            raise _Failure("probe_timeout")
    except _Failure as failure:
        result.failure = str(failure)
    except OSError:
        result.failure = "host_process_failed"
    finally:
        if install_attempted and not result.package_owned:
            result.package_cleanup = "uncertain"
        if result.package_owned:
            try:
                if uid() != owned_uid:
                    raise _Failure("package_identity")
                command("shell", "am", "force-stop", PACKAGE)
                if uid() != owned_uid:
                    raise _Failure("package_identity")
                if (
                    command("uninstall", PACKAGE).strip() != b"Success"
                    or uid() is not None
                ):
                    raise _Failure("cleanup_uncertain")
                result.package_cleanup = "confirmed_absent"
            except (_Failure, OSError):
                result.package_cleanup = "uncertain"
        if stage is not None:
            if (
                result.failure == "none"
                and result.package_cleanup == "confirmed_absent"
            ):
                try:
                    _remove_stage(stage)
                    result.staging_cleanup = "removed"
                except (ValueError, OSError):
                    result.failure = "staging_cleanup_uncertain"
                    result.staging_cleanup = "retained_uncertain"
            else:
                result.staging_cleanup = (
                    "retained_uncertain"
                    if result.package_cleanup == "uncertain"
                    or result.failure in ("staging_invalid", "staging_changed")
                    else "retained_failed"
                )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--build-result", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument(
        "--image-purpose", choices=("development-debug",), required=True
    )
    parser.add_argument(
        "--runtime-profile",
        choices=("google-translation-development", "aosp-arm-development"),
        required=True,
    )
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    config = ProbeConfig(
        args.adb,
        args.build_result,
        args.image_purpose,
        args.staging_root,
        args.runtime_profile,
    )
    if os.name != "nt" or not config.adb.is_file():
        parser.error("Existing Windows adb.exe required")
    if not args.result.is_absolute() or args.result.exists():
        parser.error("New absolute private result path required")
    boundary = ChildRunner()
    result = run_probe(config, runner=boundary)
    with args.result.open("x", encoding="utf-8") as stream:
        json.dump(
            {"result": asdict(result), "commands": boundary.receipts}, stream, indent=2
        )
    print(json.dumps(asdict(result)))
    return (
        0
        if result.failure == "none"
        and result.package_cleanup == "confirmed_absent"
        and result.staging_cleanup == "removed"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
