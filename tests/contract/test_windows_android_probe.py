"""Offline development controller contracts; no ADB or vendor execution."""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


def offline_child(argv, directory, timeout):
    started = time.time()
    outcome = subprocess.run(
        argv,
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    receipt = {
        "argv": list(argv),
        "cwd": str(Path.cwd()),
        "started": started,
        "ended": time.time(),
        "exit": outcome.returncode,
        "stdout": outcome.stdout.decode("utf-8", errors="replace"),
        "stderr": outcome.stderr.decode("utf-8", errors="replace"),
    }
    path = directory / f"offline-command-{time.time_ns()}.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return outcome


def api():
    try:
        return importlib.import_module("wso_tvt_bridge.windows_android_probe")
    except ModuleNotFoundError:
        pytest.fail("Windows development probe controller is missing")


def device_result(**changes):
    result = {
        "schemaVersion": 1,
        "version": "local-nat-probe-1",
        "abi": "arm64-v8a",
        "is64bit": True,
        "stage": "complete",
        "failure": "none",
        "loaded": True,
        "descriptorsMatched": True,
        "bootstrapped": True,
        "allocationObserved": True,
        "callbacksRemoved": True,
        "interruptRequested": True,
        "destroyRequested": True,
        "cleanupProven": False,
    }
    result.update(changes)
    return json.dumps(result).encode()


def build(tmp_path):
    apk = tmp_path / "probe.apk"
    apk.write_bytes(b"invented offline APK fixture")
    result = {
        "schemaVersion": 1,
        "status": "BUILT_HOST_VERIFIED_DEVICE_NOT_EXECUTED",
        "package": "com.wso.tvt.localprobe",
        "apk": str(apk),
        "apkBytes": apk.stat().st_size,
        "apkSha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
        "developmentOnly": True,
        "signatureVerified": True,
        "manifestVerified": True,
        "nativeVerified": True,
    }
    path = tmp_path / "build-result.json"
    path.write_text(json.dumps(result))
    return path


class AdbBoundary:
    def __init__(
        self,
        module,
        existing=False,
        changed_uid=False,
        timeout_launch=False,
        aosp=False,
    ):
        self.module = module
        self.existing = existing
        self.changed_uid = changed_uid
        self.timeout_launch = timeout_launch
        self.installed = False
        self.calls = []
        self.aosp = aosp
        self.sdk = b"24" if aosp else b"30"
        self.launched = False
        self.install_stdout = b"Performing Push Install\r\nSuccess\r\n"

    def run(self, argv, timeout, *, max_bytes=4096):
        self.calls.append(argv)
        assert argv[1:7] == (
            "-H",
            "127.0.0.1",
            "-P",
            "5039" if self.aosp else "5038",
            "-s",
            "emulator-5590" if self.aosp else "emulator-5580",
        )
        args = argv[7:]
        out = b""
        if args == ("shell", "getprop", "sys.boot_completed"):
            out = b"1\n"
        elif args == ("shell", "getprop", "ro.product.cpu.abilist"):
            out = b"x86_64,x86,arm64-v8a,armeabi-v7a\n"
        elif args == ("shell", "getprop", "ro.build.version.sdk"):
            out = self.sdk
        elif args == ("shell", "dumpsys", "package", "com.wso.tvt.localprobe"):
            assert max_bytes == 65536
            if self.existing or self.installed:
                uid = 10124 if self.changed_uid and self.launched else 10123
                out = package_dump(uid)
            else:
                out = b"\nDexopt state:\r\n  Unable to find package: com.wso.tvt.localprobe\r\n"
        elif args[0] == "install":
            assert len(args) == 3 and args[1] == "--no-streaming"
            assert args[2].isascii() and Path(args[2]).name == "probe.apk"
            assert Path(args[2]).is_file()
            self.installed = True
            out = self.install_stdout
        elif args == (
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            "com.wso.tvt.localprobe/com.wso.tvt.probe.LocalLoadProbeActivity",
        ):
            self.launched = True
            if self.timeout_launch:
                return self.module.CommandOutcome(1, b"", True, True)
            out = b"Status: ok\n"
        elif args == (
            "exec-out",
            "run-as",
            "com.wso.tvt.localprobe",
            "cat",
            "files/probe-result.json",
        ):
            out = device_result()
        elif args == ("shell", "am", "force-stop", "com.wso.tvt.localprobe"):
            pass
        elif args == ("uninstall", "com.wso.tvt.localprobe"):
            self.installed = False
            out = b"Success\n"
        else:
            raise AssertionError(f"Unexpected fixed argv: {args!r}")
        return self.module.CommandOutcome(0, out, False, True)


def config(module, tmp_path, **kwargs):
    root = kwargs.pop("staging_root", None) or ascii_staging_root(tmp_path)
    return module.ProbeConfig(
        adb=tmp_path / "adb.exe",
        build_result=build(tmp_path),
        image_purpose="development-debug",
        staging_root=root,
        **kwargs,
    )


def ascii_staging_root(tmp_path):
    # Explicit invented-data scratch, distinct from root's private runtime staging.
    path = Path(
        tempfile.mkdtemp(prefix="wso-fix2-offline-", dir="C:/Users/Public/Documents")
    )
    with (tmp_path / "ascii-scratch-roots.txt").open("a", encoding="utf-8") as receipt:
        receipt.write(str(path) + "\n")
    return path


@pytest.mark.parametrize(
    "raw,want",
    [
        (b"Performing Push Install\r\nSuccess\r\n", True),
        (b"Success\n", True),
        (b"Performing Push Install\nSuccess\n", True),
        (b"Success", True),
        (b"Performing Push Install\r\n", False),
        (b"Failure [INSTALL_FAILED]\r\n", False),
        (b"Success\r\nFailure [INSTALL_FAILED]\r\n", False),
        (b"Performing Push Install\r\nSuccess\r\nSuccess\r\n", False),
        (b"unknown preamble\nSuccess\n", False),
        (b" Success\n", False),
        (b"Performing Streamed Install\nSuccess\n", False),
        (b"\nSuccess\n", False),
    ],
    ids=lambda value: (
        "bytes-" + str(len(value)) if isinstance(value, bytes) else str(value)
    ),
)
def test_fix2_install_success_grammar_uses_captured_push_shape(raw, want):
    assert api().is_install_success(raw) is want


def test_fix2_ascii_staging_preserves_accepted_bytes_and_removes_only_owned_file(
    tmp_path,
):
    m = api()
    cfg = config(m, tmp_path)
    unrelated = cfg.staging_root / "operator-preserved.txt"
    unrelated.write_text("invented unrelated file")

    class VerifyInstall(AdbBoundary):
        def run(self, argv, timeout, *, max_bytes=4096):
            if argv[7] == "install":
                staged = Path(argv[9])
                assert staged.parent.parent == cfg.staging_root
                assert staged.read_bytes() == b"invented offline APK fixture"
                assert staged != tmp_path / "probe.apk"
                self.staged = staged
            return super().run(argv, timeout, max_bytes=max_bytes)

    boundary = VerifyInstall(m, aosp=True)
    result = m.run_probe(
        config(
            m,
            tmp_path,
            staging_root=cfg.staging_root,
            runtime_profile="aosp-arm-development",
        ),
        runner=boundary,
    )
    assert result.failure == "none"
    assert result.package_cleanup == "confirmed_absent"
    assert result.staging_cleanup == "removed"
    assert not boundary.staged.exists() and not boundary.staged.parent.exists()
    assert unrelated.read_text() == "invented unrelated file"


@pytest.mark.parametrize("field", ["unicode", "relative", "missing", "long", "file"])
def test_fix2_invalid_staging_root_refused_before_child(tmp_path, field):
    m = api()
    root = ascii_staging_root(tmp_path)
    if field == "unicode":
        invalid = root / "한글"
        invalid.mkdir()
    elif field == "relative":
        invalid = Path("operator-relative")
    elif field == "missing":
        invalid = root / "missing"
    elif field == "long":
        invalid = root / ("x" * 130)
    else:
        invalid = root / "regular-file"
        invalid.write_bytes(b"invented")
    with pytest.raises(ValueError):
        config(m, tmp_path, staging_root=invalid)


def test_fix2_failed_install_retains_supervised_ascii_artifact(tmp_path):
    m = api()
    cfg = config(m, tmp_path)

    class FailedInstall(AdbBoundary):
        def run(self, argv, timeout, *, max_bytes=4096):
            if argv[7] == "install":
                self.calls.append(argv)
                return m.CommandOutcome(
                    4294967295, b"Performing Push Install\r\n", False, True
                )
            return super().run(argv, timeout, max_bytes=max_bytes)

    boundary = FailedInstall(m)
    result = m.run_probe(cfg, runner=boundary)
    assert result.failure == "child_failed"
    assert result.package_cleanup == "uncertain"
    assert result.staging_cleanup == "retained_uncertain"
    assert (
        Path(result.staging_directory) / "probe.apk"
    ).read_bytes() == b"invented offline APK fixture"
    assert not any(call[7] == "uninstall" for call in boundary.calls)


def test_fix2_staged_drift_after_install_prevents_launch_and_retains_evidence(tmp_path):
    m = api()
    cfg = config(m, tmp_path)

    class Drift(AdbBoundary):
        def run(self, argv, timeout, *, max_bytes=4096):
            outcome = super().run(argv, timeout, max_bytes=max_bytes)
            if argv[7] == "install":
                Path(argv[9]).write_bytes(b"changed staged fixture")
            return outcome

    boundary = Drift(m)
    result = m.run_probe(cfg, runner=boundary)
    assert result.failure == "staging_changed"
    assert result.package_cleanup == "confirmed_absent"
    assert result.staging_cleanup == "retained_uncertain"
    assert not any(call[7:10] == ("shell", "am", "start") for call in boundary.calls)
    assert (
        Path(result.staging_directory) / "probe.apk"
    ).read_bytes() == b"changed staged fixture"


def test_fix2_unrelated_child_file_prevents_staging_cleanup(tmp_path):
    m = api()
    cfg = config(m, tmp_path)

    class ExtraFile(AdbBoundary):
        def run(self, argv, timeout, *, max_bytes=4096):
            if argv[7] == "install":
                Path(argv[9]).with_name("operator-extra.txt").write_text(
                    "invented extra"
                )
            return super().run(argv, timeout, max_bytes=max_bytes)

    result = m.run_probe(cfg, runner=ExtraFile(m))
    assert result.failure == "staging_cleanup_uncertain"
    assert result.package_cleanup == "confirmed_absent"
    assert result.staging_cleanup == "retained_uncertain"
    directory = Path(result.staging_directory)
    assert (directory / "probe.apk").exists() and (
        directory / "operator-extra.txt"
    ).exists()


def test_fix2_source_drift_after_copy_is_rejected_before_install(tmp_path, monkeypatch):
    m = api()
    cfg = config(m, tmp_path)
    real_sync = m.os.fsync

    def sync_then_change(fd):
        real_sync(fd)
        (tmp_path / "probe.apk").write_bytes(b"changed source after copy")

    monkeypatch.setattr(m.os, "fsync", sync_then_change)
    boundary = AdbBoundary(m)
    result = m.run_probe(cfg, runner=boundary)
    assert result.failure == "staging_invalid"
    assert result.staging_cleanup == "retained_uncertain"
    assert not any(call[7] == "install" for call in boundary.calls)
    assert (
        Path(result.staging_directory) / "probe.apk"
    ).read_bytes() == b"invented offline APK fixture"


def test_fix2_source_growth_at_copy_is_bounded_by_accepted_size(tmp_path, monkeypatch):
    m = api()
    cfg = config(m, tmp_path)
    source = tmp_path / "probe.apk"
    actual_open = Path.open
    reads = 0

    def growing_open(path, mode="r", *args, **kwargs):
        nonlocal reads
        if path == source and mode == "rb":
            reads += 1
            if reads == 3:
                source.write_bytes(b"invented offline APK fixture" + b"x" * 1024)
        return actual_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)
    boundary = AdbBoundary(m)
    result = m.run_probe(cfg, runner=boundary)
    assert result.failure == "staging_invalid"
    assert not any(call[7] == "install" for call in boundary.calls)
    assert (Path(result.staging_directory) / "probe.apk").stat().st_size == 28


def test_fix2_metadata_size_bound_rejects_before_any_staging_or_adb(tmp_path):
    m = api()
    cfg = config(m, tmp_path)
    metadata = json.loads(cfg.build_result.read_text())
    metadata["apkBytes"] = 12000001
    cfg.build_result.write_text(json.dumps(metadata))
    boundary = AdbBoundary(m)
    result = m.run_probe(cfg, runner=boundary)
    assert result.failure == "build_invalid" and boundary.calls == []
    assert result.staging_cleanup == "not_created"
    assert list(cfg.staging_root.iterdir()) == []


def test_fix2_reparse_staging_root_refused_without_touching_target(tmp_path):
    m = api()
    root = ascii_staging_root(tmp_path)
    target = root / "owned-target"
    target.mkdir()
    (target / "keep.txt").write_text("invented preserved marker")
    link = root / "owned-junction"
    utility = tmp_path / "make-junction.ps1"
    utility.write_text(
        "param($Link,$Target) New-Item -ItemType Junction -Path $Link -Value $Target | Out-Null",
        encoding="utf-8",
    )
    created = offline_child(
        (
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(utility),
            str(link),
            str(target),
        ),
        tmp_path,
        5,
    )
    assert created.returncode == 0, created.stderr
    try:
        with pytest.raises(ValueError):
            config(m, tmp_path, staging_root=link)
    finally:
        assert link.parent == root and link.name == "owned-junction"
        link.rmdir()
    assert (target / "keep.txt").read_text() == "invented preserved marker"


def test_fix2_ambiguous_success_has_no_package_or_launch_authority(tmp_path):
    m = api()
    boundary = AdbBoundary(m)
    boundary.install_stdout = (
        b"Performing Push Install\r\nSuccess\r\nFailure [INSTALL_FAILED]\r\n"
    )
    result = m.run_probe(config(m, tmp_path), runner=boundary)
    assert result.failure == "install_uncertain"
    assert result.package_owned is False
    assert result.staging_cleanup == "retained_uncertain"
    assert not any(
        call[7:10] == ("shell", "am", "start") or call[7] == "uninstall"
        for call in boundary.calls
    )


def google30_absence():
    return (
        b"Queries:\n  invented metadata\n\nPackage Changes:\n  User 0:\n"
        b"    seq=1, package=com.wso.tvt.localprobe\n\nDexopt state:\n"
        b"  Unable to find package: com.wso.tvt.localprobe\n\nCompiler stats:\n"
        b"  Unable to find package: com.wso.tvt.localprobe\n\nAPEX session state:\n\n"
        b"Active APEX packages:\n\nInactive APEX packages:\n\nFactory APEX packages:\n"
    )


def test_fix2_google30_captured_absence_shape_is_supported():
    root = Path(__file__).resolve().parents[2]
    captured = (
        root
        / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-windows-local-native-probe-Fix2-evidence/root-readset/google30-package-absent.stdout"
    )
    if not captured.is_file():
        pytest.skip("Root-owned captured profile evidence is not present")
    raw = captured.read_bytes()
    assert len(raw) == 23759
    assert (
        hashlib.sha256(raw).hexdigest()
        == "37aa507184565a546d2cf1d111057352a3ef33f0c15293ca1e540ddabddfbcc9"
    )
    assert api().parse_package_uid(raw) is None


def test_fix2_google30_supported_sections_allow_package_history_after_uninstall(
    tmp_path,
):
    m = api()

    class Google30(AdbBoundary):
        def run(self, argv, timeout, *, max_bytes=4096):
            if (
                argv[7:] == ("shell", "dumpsys", "package", "com.wso.tvt.localprobe")
                and not self.installed
            ):
                self.calls.append(argv)
                return m.CommandOutcome(0, google30_absence(), False, True)
            return super().run(argv, timeout, max_bytes=max_bytes)

    result = m.run_probe(config(m, tmp_path), runner=Google30(m))
    assert result.failure == "none"
    assert result.package_cleanup == "confirmed_absent"
    assert result.staging_cleanup == "removed"


@pytest.mark.parametrize(
    "raw",
    [
        google30_absence().replace(b"Compiler stats:", b"Unknown stats:"),
        google30_absence().replace(
            b"Compiler stats:\n  Unable to find package: com.wso.tvt.localprobe",
            b"Compiler stats:\n  Unable to find package: com.unrelated.package",
        ),
        google30_absence().replace(b"invented metadata", b"userId=10060"),
        google30_absence().replace(
            b"invented metadata", b"Package [com.wso.tvt.localprobe] (abc123):"
        ),
        google30_absence().replace(b"invented metadata", b"Error: unsupported"),
        google30_absence()
        + b"Compiler stats:\n  Unable to find package: com.wso.tvt.localprobe\n",
        b"  Unable to find package: com.wso.tvt.localprobe\n" + google30_absence(),
    ],
    ids=lambda raw: "bytes-" + str(len(raw)),
)
def test_fix2_google30_absence_rejects_malformed_sections_and_identity(raw):
    with pytest.raises(ValueError):
        api().parse_package_uid(raw)


def test_fix2_changed_staging_root_is_rejected_before_any_child(tmp_path):
    m = api()
    cfg = config(m, tmp_path)
    moved = cfg.staging_root.with_name(cfg.staging_root.name + "-preserved")
    assert moved.parent == cfg.staging_root.parent and moved.name.startswith(
        "wso-fix2-offline-"
    )
    cfg.staging_root.rename(moved)
    cfg.staging_root.mkdir()
    boundary = AdbBoundary(m)
    result = m.run_probe(cfg, runner=boundary)
    assert result.failure == "staging_invalid" and boundary.calls == []
    assert result.staging_cleanup == "not_created"
    assert moved.exists()


def package_dump(uid=10123):
    return (
        f"Packages:\n  Package [com.wso.tvt.localprobe] (17911e1):\n"
        f"    userId={uid}\n    versionCode=1 minSdk=23 targetSdk=36\n"
        "    User 0: installed=true hidden=false\n"
        "\nShared users:\n  SharedUser [invented.shared] (123ab):\n    userId=2000\n"
    ).encode()


def test_api24_supported_uid_query_does_not_accept_legacy_exit0_error(tmp_path):
    m = api()

    class Api24(AdbBoundary):
        def run(self, argv, timeout, *, max_bytes=4096):
            if argv[7:] == (
                "shell",
                "cmd",
                "package",
                "list",
                "packages",
                "-U",
                "com.wso.tvt.localprobe",
            ):
                return m.CommandOutcome(
                    0, b"Error: Unknown option: -U\r\n", False, True
                )
            return super().run(argv, timeout, max_bytes=max_bytes)

    boundary = Api24(m, aosp=True)
    boundary.sdk = b"24"
    result = m.run_probe(
        config(m, tmp_path, runtime_profile="aosp-arm-development"), runner=boundary
    )
    assert result.failure == "none"
    assert result.package_cleanup == "confirmed_absent"
    assert all(
        call[7:]
        != (
            "shell",
            "cmd",
            "package",
            "list",
            "packages",
            "-U",
            "com.wso.tvt.localprobe",
        )
        for call in boundary.calls
    )


@pytest.mark.parametrize(
    "raw,want",
    [
        (
            b"\r\nDexopt state:\r\n  Unable to find package: com.wso.tvt.localprobe\r\n",
            None,
        ),
        (package_dump(), 10123),
        (package_dump(10124), 10124),
        (b"Resolver:\n" + b"    invented line\n" * 1000 + package_dump(), 10123),
    ],
    ids=lambda value: (
        "bytes-" + str(len(value)) if isinstance(value, bytes) else str(value)
    ),
)
def test_uid_parser_scopes_package_block_and_bounds_large_output(raw, want):
    assert api().parse_package_uid(raw) == want


@pytest.mark.parametrize(
    "raw",
    [
        b"Error: Unknown option: -U\r\n",
        b"",
        b"\n",
        b"x" * 65537,
        package_dump().replace(b"userId=10123", b"userId=10123\n    userId=10124"),
        package_dump().replace(b"userId=10123", b"missingUid=10123"),
        package_dump().replace(b"userId=10123", b"userId=10123\n    userId=malformed"),
        package_dump() + package_dump(),
        package_dump()
        + b"  Package [com.unrelated.package] (malformed):\n    userId=10124\n",
        package_dump().replace(b"com.wso.tvt.localprobe", b"com.unrelated.package"),
        b"Unable to find package: com.wso.tvt.localprobe\n",
        package_dump() + b"  Unable to find package: com.wso.tvt.localprobe\n",
    ],
    ids=lambda value: "bytes-" + str(len(value)),
)
def test_uid_parser_rejects_errors_ambiguity_and_unscoped_uid(raw):
    with pytest.raises(ValueError):
        api().parse_package_uid(raw)


def test_fixed_dumpsys_exit0_error_is_not_absence_or_install_authority(tmp_path):
    m = api()

    class ErrorDump(AdbBoundary):
        def run(self, argv, timeout, *, max_bytes=4096):
            if argv[7:] == ("shell", "dumpsys", "package", "com.wso.tvt.localprobe"):
                self.calls.append(argv)
                return m.CommandOutcome(
                    0, b"Error: Unknown option: -U\r\n", False, True
                )
            return super().run(argv, timeout, max_bytes=max_bytes)

    boundary = ErrorDump(m, aosp=True)
    result = m.run_probe(
        config(m, tmp_path, runtime_profile="aosp-arm-development"), runner=boundary
    )
    assert result.failure == "package_identity"
    assert result.package_owned is False
    assert result.package_cleanup == "not_owned"
    assert not any(call[7] in ("install", "uninstall") for call in boundary.calls)


def test_production_and_wrong_target_refused_before_child(tmp_path):
    m = api()
    for fields in (
        {"image_purpose": "production"},
        {"port": 5037},
        {"host": "localhost"},
        {"serial": "phone-serial"},
    ):
        values = {
            "adb": tmp_path / "adb.exe",
            "build_result": build(tmp_path),
            "image_purpose": "development-debug",
            "staging_root": ascii_staging_root(tmp_path),
        }
        values.update(fields)
        with pytest.raises((ValueError, TypeError)):
            m.ProbeConfig(**values)


def test_existing_package_never_claimed_or_removed(tmp_path):
    m = api()
    boundary = AdbBoundary(m, existing=True)
    result = m.run_probe(config(m, tmp_path), runner=boundary)
    assert result.failure == "package_present"
    assert result.package_owned is False
    assert not any(call[7] in ("install", "uninstall") for call in boundary.calls)


def test_aosp_profile_uses_only_its_fixed_owned_target(tmp_path):
    m = api()
    boundary = AdbBoundary(m, aosp=True)
    cfg = config(m, tmp_path, runtime_profile="aosp-arm-development")
    result = m.run_probe(cfg, runner=boundary)
    assert result.failure == "none"
    assert result.runtime_profile == "aosp-arm-development"
    assert result.package_cleanup == "confirmed_absent"
    with pytest.raises(ValueError):
        config(m, tmp_path, runtime_profile="production")


def test_guest_api22_refused_before_install(tmp_path):
    m = api()
    boundary = AdbBoundary(m)
    boundary.sdk = b"22"
    result = m.run_probe(config(m, tmp_path), runner=boundary)
    assert result.failure == "api_unsupported"
    assert not any(call[7] == "install" for call in boundary.calls)


def test_manifest_allows_api25_load_probe_without_network_authority():
    root = Path(__file__).resolve().parents[2]
    manifest = ET.parse(
        root / "services/tvt-android-helper/android-local/AndroidManifest.xml"
    ).getroot()
    ns = "{http://schemas.android.com/apk/res/android}"
    assert int(manifest.find("uses-sdk").get(ns + "minSdkVersion")) <= 25
    assert manifest.findall("uses-permission") == []
    application = manifest.find("application")
    assert [node.tag for node in application] == ["activity"]


def test_complete_stage_io_failure_is_preserved():
    m = api()
    parsed = m.parse_device_result(device_result(stage="complete", failure="io"))
    assert parsed["failure"] == "io"


def test_fixed_argv_probe_and_owned_cleanup(tmp_path):
    m = api()
    boundary = AdbBoundary(m)
    result = m.run_probe(config(m, tmp_path), runner=boundary)
    assert result.device["allocationObserved"] is True
    assert result.device["cleanupProven"] is False
    assert result.package_cleanup == "confirmed_absent"
    assert result.failure == "none"
    assert boundary.calls[-1][7:] == (
        "shell",
        "dumpsys",
        "package",
        "com.wso.tvt.localprobe",
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"x" * 4097,
        device_result(pointer=4),
        device_result(cleanupProven=True),
        device_result(failure="native exception SECRET"),
        device_result(loaded="true"),
        device_result(loaded=False, bootstrapped=True),
        device_result(stage=[]),
        device_result(abi=[]),
        b'{"schemaVersion":1,"schemaVersion":1}',
    ],
)
def test_untrusted_result_cannot_escape_safe_schema(raw):
    m = api()
    with pytest.raises(ValueError):
        m.parse_device_result(raw)


def test_failure_stage_is_preserved_without_success_substitution():
    m = api()
    parsed = m.parse_device_result(
        device_result(
            stage="bootstrap",
            failure="linkage",
            bootstrapped=False,
            allocationObserved=False,
            callbacksRemoved=False,
            interruptRequested=False,
            destroyRequested=False,
        )
    )
    assert parsed["failure"] == "linkage"
    assert parsed["stage"] == "bootstrap"
    assert parsed["allocationObserved"] is False


def test_changed_uid_cleanup_is_uncertain_without_destructive_command(tmp_path):
    m = api()
    boundary = AdbBoundary(m, changed_uid=True)
    result = m.run_probe(config(m, tmp_path), runner=boundary)
    assert result.package_cleanup == "uncertain"
    assert not any(
        call[7:] == ("uninstall", "com.wso.tvt.localprobe") for call in boundary.calls
    )


def test_launch_timeout_keeps_failure_and_checks_owned_cleanup(tmp_path):
    m = api()
    boundary = AdbBoundary(m, timeout_launch=True)
    result = m.run_probe(config(m, tmp_path), runner=boundary)
    assert result.failure == "child_timeout"
    assert result.package_cleanup == "confirmed_absent"


def test_force_stop_timeout_keeps_cleanup_uncertain_without_uninstall(tmp_path):
    m = api()

    class StopTimeout(AdbBoundary):
        def run(self, argv, timeout, *, max_bytes=4096):
            if argv[7:] == ("shell", "am", "force-stop", "com.wso.tvt.localprobe"):
                return m.CommandOutcome(None, b"", True, False)
            return super().run(argv, timeout, max_bytes=max_bytes)

    boundary = StopTimeout(m)
    result = m.run_probe(config(m, tmp_path), runner=boundary)
    assert result.package_cleanup == "uncertain"
    assert not any(call[7] == "uninstall" for call in boundary.calls)


def test_child_runner_retains_handle_and_bounds_capture():
    m = api()
    runner = m.ChildRunner()
    overflow = runner.run(
        (sys.executable, "-c", "import sys;sys.stdout.write('x'*20000)"), 3
    )
    assert overflow.overflow is True
    assert len(overflow.stdout) <= 4096
    timed = runner.run((sys.executable, "-c", "import time;time.sleep(2)"), 0.05)
    assert timed.timed_out is True
    assert len(runner.children) == 2
    assert all(child.poll() is not None for child in runner.children)


def test_changed_apk_refused_before_adb(tmp_path):
    m = api()
    cfg = config(m, tmp_path)
    (tmp_path / "probe.apk").write_bytes(b"changed")
    boundary = AdbBoundary(m)
    result = m.run_probe(cfg, runner=boundary)
    assert result.failure == "build_invalid"
    assert boundary.calls == []


def test_build_rejects_author_receipt_before_tool_or_extraction(tmp_path):
    # Removing the reviewed source gate would execute a missing JDK or touch build paths.
    root = Path(__file__).resolve().parents[2]
    script = root / "services/tvt-android-helper/build-local-load-probe.ps1"
    assert script.is_file(), "Review-gated local builder is missing"
    receipt = tmp_path / "author.json"
    receipt.write_text(json.dumps({"status": "READY_FOR_REVIEW", "files": {}}))
    outcome = offline_child(
        (
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(script),
            "-ApprovedApk",
            str(tmp_path / "never-open.apk"),
            "-TransportReceipt",
            str(receipt),
            "-JdkRoot",
            str(tmp_path / "never-run-jdk"),
        ),
        tmp_path,
        5,
    )
    assert outcome.returncode != 0
    assert b"Root-reviewed transport receipt required" in outcome.stderr
    assert not (tmp_path / "never-run-jdk").exists()


def test_packaged_library_inventory_checks_real_zip_content(tmp_path):
    # A wrong hash or accepting an additional native library breaks this gate.
    import zipfile

    root = Path(__file__).resolve().parents[2]
    builder = root / "services/tvt-android-helper/build-local-load-probe.ps1"
    payload = b"invented native fixture"
    digest = hashlib.sha256(payload).hexdigest()
    accepted = tmp_path / "accepted.zip"
    wrong = tmp_path / "wrong.zip"
    extra = tmp_path / "extra.zip"
    for path, content in (
        (accepted, payload),
        (wrong, b"x" * len(payload)),
        (extra, payload),
    ):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("lib/arm64-v8a/libNatTraveral.so", content)
            archive.writestr("lib/armeabi-v7a/libNatTraveral.so", payload)
            if path == extra:
                archive.writestr("lib/x86/other.so", payload)
    # Execute the actual builder's isolated validation function. Never its build body.
    utility = tmp_path / "zip-validation.ps1"
    utility.write_text(
        """param($Source,$Accepted,$Wrong,$Extra,$Digest,$Length)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'parse failed' }
$node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-ZipInventory'},$true)
Invoke-Expression $node.Extent.Text
Add-Type -AssemblyName System.IO.Compression.FileSystem
$native=@(@{path='lib/arm64-v8a/libNatTraveral.so';bytes=[long]$Length;sha256=$Digest},@{path='lib/armeabi-v7a/libNatTraveral.so';bytes=[long]$Length;sha256=$Digest})
foreach($path in @($Accepted,$Wrong,$Extra)) {
 $zip=[IO.Compression.ZipFile]::OpenRead($path)
 try { Assert-ZipInventory $zip -Packaged; if($path -ne $Accepted){throw 'bad ZIP accepted'}; Write-Output 'ACCEPTED' }
 catch { if($path -eq $Accepted -or $_.Exception.Message -eq 'bad ZIP accepted'){throw}; Write-Output 'REJECTED' }
 finally {$zip.Dispose()}
}
""",
        encoding="utf-8",
    )
    outcome = offline_child(
        (
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(utility),
            str(builder),
            str(accepted),
            str(wrong),
            str(extra),
            digest,
            str(len(payload)),
        ),
        tmp_path,
        5,
    )
    assert outcome.returncode == 0, outcome.stderr
    assert outcome.stdout.split() == [b"ACCEPTED", b"REJECTED", b"REJECTED"]


@pytest.mark.parametrize(
    "static_native,want", [(False, b"ACCEPTED"), (True, b"REJECTED")]
)
def test_probe_independent_reflection_inventory_rejects_native_modifier_drift(
    tmp_path, static_native, want
):
    # Making a JNI method static preserves its descriptor but changes its JNI receiver.
    # These invented stubs never invoke any native declaration or Android SDK code.
    jdk = Path("C:/Android/tools/jdk-21.0.12.1+1/bin")
    assert (jdk / "javac.exe").is_file()
    stub_sources = {
        "Activity.java": 'package android.app; public class Activity { public void onCreate(android.os.Bundle b) {} public void finish() {} public java.io.File getFilesDir() {return new java.io.File(".");}}',
        "Bundle.java": "package android.os; public class Bundle {}",
        "Process.java": "package android.os; public class Process {public static boolean is64Bit(){return true;}}",
        "JniLocalSerialDriver.java": "package com.wso.tvt.local; public class JniLocalSerialDriver { public static JniLocalSerialDriver createAndroid(){return new JniLocalSerialDriver();} public long allocate(){return 1;} public void removeCallbacks(long n){} public boolean interrupt(long n){return false;} public boolean destroy(long n){return false;} }",
        "NatTraveral.java": """package com.tvt.network; public class NatTraveral {
private native int Destroy(long n); private native int InitGlobal(); private native long Initialize();
public native String GetConnInfo(long n); public native int GetConnectType(long n);
public STATIC native int GetErrorCode(long n); public native long GetLastRecvTime(long n); public native int GetTraversalMode(long n);
public native int GetVersionType(long n,String a,String b,int c,String d,int e,byte[] f,int g,int h,boolean i,String j,String k,String l,String m,String o);
public native int Interrupt(long n); public native int Nat2EnablePrintLog(boolean a);
public native String QueryDevInfo(long n,String a,String b,int c,String d,int e,String f,String g,String h,String i,String j);
public native int RecvData(long n,byte[] a,int b); public native int SendData(long n,byte[] a,int b); public native int SetConnectTraversalMode(long n,int a);
public native boolean SetDisableConnFlag(int a); public native boolean SetLanIps(String a); public native int SetValue(long n,String a,String b,int c,int d);
public void Nat2ConnStatusCallback(long n,boolean a,int b,String c){} public int Nat2RecvDataCallback(long n,byte[] a){return 0;} public static void LogPrintCallback(String a){}
} """.replace("STATIC", "static" if static_native else ""),
        "InventoryHarness.java": """public class InventoryHarness {public static void main(String[] args)throws Exception {
java.lang.reflect.Method m=com.wso.tvt.probe.LocalLoadProbeActivity.class.getDeclaredMethod("verifyDescriptors"); m.setAccessible(true);
try {m.invoke(null); System.out.print("ACCEPTED");} catch(java.lang.reflect.InvocationTargetException e){System.out.print("REJECTED");}
}}""",
    }
    sources = []
    for name, contents in stub_sources.items():
        path = tmp_path / name
        path.write_text(contents, encoding="utf-8")
        sources.append(str(path))
    root = Path(__file__).resolve().parents[2]
    probe = (
        root
        / "services/tvt-android-helper/android-local/src/com/wso/tvt/probe/LocalLoadProbeActivity.java"
    )
    compile_result = offline_child(
        (
            str(jdk / "javac.exe"),
            "--release",
            "8",
            "-d",
            str(tmp_path),
            *sources,
            str(probe),
        ),
        tmp_path,
        10,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    execution = offline_child(
        (str(jdk / "java.exe"), "-cp", str(tmp_path), "InventoryHarness"),
        tmp_path,
        5,
    )
    assert execution.returncode == 0
    assert execution.stdout == want


@pytest.mark.parametrize(
    "mode",
    [
        "timeout",
        "kill-failed",
        "inherited-pipe",
        "start-failed",
        "exit-failed",
        "capture-bound",
    ],
)
def test_real_isolated_builder_child_lifecycle_keeps_evidence_and_ownership(
    tmp_path, mode
):
    # The actual Invoke-Tool function runs invented children. Only the kill syscall
    # is faulted in the isolated test snapshot for the uncertain-reap branch.
    root = Path(__file__).resolve().parents[2]
    builder = root / "services/tvt-android-helper/build-local-load-probe.ps1"
    utility = tmp_path / "builder-lifecycle.ps1"
    utility.write_text(
        r"""param($Source,$Python,$Owned,$Mode)
$ErrorActionPreference='Stop'
$owned=$Owned; $capture=Join-Path $Owned 'captures'
New-Item -ItemType Directory -Path $capture -Force | Out-Null
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'parse failed'}
$node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-Tool'},$true)
$text=$node.Extent.Text
if($Mode -eq 'kill-failed'){$text=$text.Replace('$process.Kill()', "throw 'invented kill syscall failure'")}
$text | Set-Content (Join-Path $Owned 'isolated-invoke-tool.ps1')
Invoke-Expression $text
$code="import sys,time;print('partial-out',flush=True);print('partial-err',file=sys.stderr,flush=True);time.sleep(2)"
if($Mode -eq 'inherited-pipe'){$code="import subprocess,sys;print('partial-out',flush=True);print('partial-err',file=sys.stderr,flush=True);subprocess.Popen([sys.executable,'-c','import time;time.sleep(2)'],stdin=subprocess.DEVNULL);"}
if($Mode -eq 'exit-failed'){$code="import sys;print('partial-out',flush=True);print('partial-err',file=sys.stderr,flush=True);sys.exit(7)"}
if($Mode -eq 'capture-bound'){$code="import sys;print('partial-out',flush=True);print('partial-err',file=sys.stderr,flush=True);sys.stdout.write('x'*100000)"}
$exe=$Python
if($Mode -eq 'start-failed'){$exe=Join-Path $Owned 'missing-child.exe'}
$started=[datetime]::UtcNow
try {$null=Invoke-Tool 'synthetic' $exe @('-c',$code) @{} -TimeoutMilliseconds 150 -ReapMilliseconds 50 -PipeMilliseconds 100}
catch { }
$elapsed=([datetime]::UtcNow-$started).TotalSeconds
$record=Get-Content -Raw (Join-Path $capture 'synthetic-command.json') | ConvertFrom-Json
$record | Add-Member -NotePropertyName testElapsedSeconds -NotePropertyValue $elapsed
$retainedCount=0
if(Get-Variable -Name RetainedBuildChildren -Scope Script -ErrorAction SilentlyContinue){$retainedCount=$script:RetainedBuildChildren.Count}
$record | Add-Member -NotePropertyName testRetainedCount -NotePropertyValue $retainedCount
$record | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $Owned 'observed.json')
# Test-only cleanup uses the actual retained original handle, never a PID/tree kill.
if($retainedCount){foreach($entry in $script:RetainedBuildChildren.Values){
 if(!$entry.process.HasExited){$entry.process.Kill();$null=$entry.process.WaitForExit(5000)}
 $null=$entry.stdout.task.Wait(5000);$null=$entry.stderr.task.Wait(5000)
 $entry.process.Dispose()
}}
""",
        encoding="utf-8",
    )
    outcome = offline_child(
        (
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(utility),
            str(builder),
            sys.executable,
            str(tmp_path),
            mode,
        ),
        tmp_path,
        15,
    )
    assert outcome.returncode == 0, outcome.stderr
    observed = json.loads((tmp_path / "observed.json").read_text(encoding="utf-8-sig"))
    assert "exit" in observed and "timedOut" in observed and "reaped" in observed
    assert "captureComplete" in observed and "ownershipRetained" in observed
    assert observed["failure"] != "none"
    assert observed["ended"] and observed["started"]
    if mode == "start-failed":
        assert observed["exit"] is None
        assert observed["startedChild"] is False
        assert observed["ownershipRetained"] is False

        return
    assert "partial-out" in (tmp_path / "captures/synthetic.stdout").read_text(
        encoding="utf-8-sig"
    )
    assert "partial-err" in (tmp_path / "captures/synthetic.stderr").read_text(
        encoding="utf-8-sig"
    )
    if mode == "timeout":
        assert observed["timedOut"] is True
        assert observed["reaped"] is True
        assert observed["captureComplete"] is True
        assert observed["ownershipRetained"] is False
    elif mode == "kill-failed":
        assert observed["killFailed"] is True
        assert observed["reaped"] is False
        assert observed["exit"] is None
        assert observed["ownershipRetained"] is True
        assert observed["testRetainedCount"] == 1
    elif mode == "inherited-pipe":
        assert observed["reaped"] is True
        assert observed["pipesCompleted"] is False
        assert observed["captureComplete"] is False
        assert observed["ownershipRetained"] is True
        assert observed["testRetainedCount"] == 1
        assert observed["testElapsedSeconds"] < 1.8
    elif mode == "exit-failed":
        assert observed["exit"] == 7
        assert observed["failure"] == "child_exit"
        assert observed["ownershipRetained"] is False
    else:
        assert observed["captureTruncated"] is True
        assert observed["failure"] == "capture_bound"
        assert observed["stdoutBytes"] == 65536
        assert observed["ownershipRetained"] is False


def test_actual_builder_passive_owner_waits_for_inherited_pipes(tmp_path):
    # Exercise the real top-level custody trap as well as Invoke-Tool; no build body.
    root = Path(__file__).resolve().parents[2]
    builder = root / "services/tvt-android-helper/build-local-load-probe.ps1"
    exporter = tmp_path / "export-owner.ps1"
    sandbox = tmp_path / "isolated-owner.ps1"
    exporter.write_text(
        r"""param($Source,$Destination)
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
$trap=$ast.Find({param($n) $n -is [Management.Automation.Language.TrapStatementAst]},$true)
$function=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-Tool'},$true)
$body=@'
param($Python,$Owned)
$ErrorActionPreference='Stop'
$script:RetainedBuildChildren=@{}
'@ + "`n" + $trap.Extent.Text + "`n" + $function.Extent.Text + "`n" + @'
$owned=$Owned;$capture=Join-Path $Owned 'captures'
New-Item -ItemType Directory -Path $capture -Force | Out-Null
$code="import subprocess,sys;print('owner-partial',flush=True);subprocess.Popen([sys.executable,'-c','import time;time.sleep(2)'],stdin=subprocess.DEVNULL)"
$null=Invoke-Tool 'passive' $Python @('-c',$code) @{} -TimeoutMilliseconds 300 -ReapMilliseconds 50 -PipeMilliseconds 100
throw 'failed stage must not proceed'
'@
$body | Set-Content $Destination
""",
        encoding="utf-8",
    )
    exported = offline_child(
        (
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(exporter),
            str(builder),
            str(sandbox),
        ),
        tmp_path,
        5,
    )
    assert exported.returncode == 0, exported.stderr
    began = time.monotonic()
    outcome = offline_child(
        (
            shutil.which("pwsh"),
            "-NoProfile",
            "-File",
            str(sandbox),
            sys.executable,
            str(tmp_path),
        ),
        tmp_path,
        10,
    )
    assert outcome.returncode != 0
    assert 1.7 <= time.monotonic() - began < 8
    original = json.loads(
        (tmp_path / "captures/passive-command.json").read_text(encoding="utf-8-sig")
    )
    final = json.loads(
        (tmp_path / "captures/passive-ownership.json").read_text(encoding="utf-8-sig")
    )
    assert original["ownershipRetained"] is True
    assert original["pipesCompleted"] is False
    assert final["ownerReaped"] is True
    assert final["ownerPipesCompleted"] is True
    assert final["ownerCompletionObserved"]
    assert "owner-partial" in (tmp_path / "captures/passive.stdout").read_text()
