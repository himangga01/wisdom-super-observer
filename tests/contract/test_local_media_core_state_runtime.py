"""Runtime wiring controls using inert original factories and temporary files."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.contract.test_local_media_core_state_debug import helper_module

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def runtime():
    spec = importlib.util.spec_from_file_location(
        "core_state_fixture_runtime", ROOT / "scripts/test-local-devices/runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def owners():
    coordinator = SimpleNamespace(
        current=lambda *_: False,
        _fence=lambda *_: None,
        _close_viewer=lambda *_: True,
        shutdown=lambda: True,
    )
    admission = SimpleNamespace(
        worker_epoch=object(),
        current_transport=lambda *_: True,
        current_slot=lambda *_: True,
        current_viewer=lambda *_: True,
        shutdown=lambda: True,
    )
    return admission, coordinator


def test_default_off_and_setup_baseexception_keep_exact_bound_methods(
    runtime, monkeypatch, tmp_path
):
    configure = getattr(runtime, "configure_core_state_debug", None)
    assert configure is not None, "runtime state hooks missing"
    for key in ("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "WSO_TEST_LOCAL_MEDIA_OBSERVE"):
        monkeypatch.delenv(key, raising=False)
    admission, coordinator = owners()
    original = coordinator.current
    assert configure(admission, coordinator, tmp_path) is None
    assert coordinator.current is original
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")

    def broken(*args):
        raise KeyboardInterrupt("private-setup")

    monkeypatch.setattr(runtime, "_private_debug_writer", broken)
    assert configure(admission, coordinator, tmp_path) is None
    assert coordinator.current is original


def test_fixed_state_file_has_exclusive_owned_writer_and_no_hook_io(
    runtime, monkeypatch, tmp_path
):
    configure = getattr(runtime, "configure_core_state_debug", None)
    assert configure is not None, "fixed state diagnostic file missing"
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    project = tmp_path / "root"
    folder = project / "auth-state" / ("local-devices-" + "c" * 32)
    folder.mkdir(parents=True)
    evidence = (
        project / ".superpowers/verification/local-device-browser-runtime" / folder.name
    )
    evidence.mkdir(parents=True)
    monkeypatch.setattr(runtime, "ROOT", project)
    monkeypatch.setattr(runtime, "EVIDENCE_ROOT", evidence.parent)
    monkeypatch.setattr(runtime, "core_state_debug_helper", helper_module)
    acl = []
    monkeypatch.setattr(
        runtime,
        "borrowed_helpers",
        lambda: SimpleNamespace(
            private_directory=lambda path, **kwargs: acl.append(path)
        ),
    )
    admission, coordinator = owners()
    sink = configure(admission, coordinator, folder)
    assert sink is not None
    target = evidence / "media-core-state-debug.jsonl"
    assert acl == [evidence] and target.read_bytes() == b""
    original = coordinator.current
    assert configure(admission, coordinator, folder) is None
    assert coordinator.current is original
    assert coordinator.current(object()) is False and target.read_bytes() == b""
    assert sink.close() is True
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["COORDINATOR_CURRENT", "SUMMARY"]
    assert str(project) not in target.read_text()
    with pytest.raises(ValueError):
        runtime._private_debug_writer(folder, "private-path.jsonl")


def test_composition_installs_and_retains_before_executor_monitor_starts(
    runtime, monkeypatch, tmp_path
):
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    monkeypatch.setattr(
        runtime, "core_state_debug_helper", helper_module, raising=False
    )
    written, names, retained, phases = [], [], [], []
    monkeypatch.setattr(
        runtime,
        "_private_debug_writer",
        lambda folder, name: (names.append(name), written.append)[1],
    )
    monkeypatch.setattr(runtime, "configure_core_debug", lambda *args: None)
    admission, coordinator = owners()
    original = coordinator.current
    factories = {
        name: lambda *args, **kwargs: object()
        for name in (
            "MuxOriginalBudget",
            "WindowsSocketProvider",
            "NativeLocalMuxProvider",
            "MediaCreditLedger",
            "MuxSourceFactory",
        )
    }
    factories["SqlMuxAdmission"] = lambda *args: admission
    factories["DeviceEpochCoordinator"] = lambda *args: coordinator

    def retain(sink):
        assert coordinator.current is not original
        retained.append(sink)
        phases.append("retained")

    def executor(given_admission, given_coordinator):
        assert given_admission is admission and given_coordinator is coordinator
        assert coordinator.current is not original and len(retained) == 1
        assert coordinator.current(object()) is False
        phases.append("executor")
        return SimpleNamespace(start=object())

    factories["MuxMediaExecutor"] = executor

    def worker(*args, **kwargs):
        result = object()
        kwargs["retain_owner"](result)
        phases.append("worker")
        return result

    factories["LocalMediaWorker"] = worker
    runtime.compose_shared_media(
        "inert",
        object(),
        object(),
        tmp_path,
        factories=factories,
        core_debug_folder=tmp_path,
        retain_core_state_debug=retain,
    )
    assert phases == ["retained", "executor", "worker"]
    assert (
        names == ["media-native-startup-debug.jsonl", "media-core-state-debug.jsonl"]
        and written == []
    )
    assert retained[0].close() is True
    assert json.loads(written[0])["event"] == "COORDINATOR_CURRENT"


def test_native_default_off_and_optional_setup_failure_preserve_provider_options(
    runtime, monkeypatch, tmp_path
):
    configure = getattr(runtime, "configure_native_startup_debug", None)
    assert configure is not None, "runtime native sink wiring missing"
    for key in ("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "WSO_TEST_LOCAL_MEDIA_OBSERVE"):
        monkeypatch.delenv(key, raising=False)
    assert configure(tmp_path) is None
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")

    def broken(*args):
        raise SystemExit("private-native-setup")

    monkeypatch.setattr(runtime, "_private_debug_writer", broken)
    assert configure(tmp_path) is None


def test_native_sink_is_same_original_passed_to_provider_and_shared_publisher(
    runtime, monkeypatch, tmp_path
):
    from wso_tvt_bridge.local_live_diagnostics import NativeFirstKeySink

    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    monkeypatch.setattr(
        runtime, "core_state_debug_helper", helper_module, raising=False
    )
    names, retained, actual = [], [], []
    monkeypatch.setattr(
        runtime,
        "_private_debug_writer",
        lambda folder, name: (names.append(name), lambda _: None)[1],
    )
    monkeypatch.setattr(runtime, "configure_core_debug", lambda *args: None)
    admission, coordinator = owners()
    factories = {
        name: lambda *args, **kwargs: object()
        for name in (
            "MuxOriginalBudget",
            "WindowsSocketProvider",
            "MediaCreditLedger",
            "MuxSourceFactory",
        )
    }
    factories["SqlMuxAdmission"] = lambda *args: admission
    factories["DeviceEpochCoordinator"] = lambda *args: coordinator
    factories["MuxMediaExecutor"] = lambda *args: SimpleNamespace(start=object())

    def provider(native, **kwargs):
        assert kwargs["admission"] is admission
        actual.append(kwargs["first_key_debug"])
        assert type(actual[0]) is NativeFirstKeySink
        return object()

    factories["NativeLocalMuxProvider"] = provider

    def worker(*args, **kwargs):
        result = object()
        kwargs["retain_owner"](result)
        return result

    factories["LocalMediaWorker"] = worker
    runtime.compose_shared_media(
        "inert",
        object(),
        object(),
        tmp_path,
        factories=factories,
        core_debug_folder=tmp_path,
        retain_core_state_debug=retained.append,
    )
    assert names == ["media-native-startup-debug.jsonl", "media-core-state-debug.jsonl"]
    assert len(retained) == 1 and retained[0]._native_sink is actual[0]
    assert retained[0].close() is True


def test_worker_retains_publisher_until_server_native_and_admission_disposal(
    runtime, monkeypatch, tmp_path
):
    from io import StringIO

    from wso_core import secrets
    from wso_core.tvt import local_admission
    from wso_tvt_bridge import server as server_module
    from wso_tvt_bridge import windows_socket

    helper = helper_module()
    events, files, owners = [], [], []
    for key, value in {
        "WSO_TEST_LOCAL_DEVICE_NATIVE": "real",
        "WSO_TEST_LOCAL_MEDIA_BROWSER": "1",
        "WSO_TEST_LOCAL_MEDIA_SHARED": "1",
        "WSO_TEST_LOCAL_MEDIA_API_DEBUG": "1",
        "WSO_WORKER_DATABASE_URL": "inert",
        "WSO_CONNECTION_KEY_FILE": "inert",
        "WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE": "inert",
        "WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256": "a" * 64,
        "WSO_TVT_WINDOWS_DECODER_PYTHON": "inert",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", raising=False)
    monkeypatch.setattr(runtime, "verify_source_approval", lambda *args: {})
    monkeypatch.setattr(
        runtime, "required_provider", lambda _: SimpleNamespace(_config=object())
    )
    monkeypatch.setattr(
        runtime,
        "borrowed_helpers",
        lambda: SimpleNamespace(
            write_private=lambda path, value: files.append((path.name, value))
        ),
    )
    monkeypatch.setattr(secrets, "FileKeyProvider", lambda _: object())
    monkeypatch.setattr(
        local_admission,
        "LocalDeviceAdmission",
        lambda *args: SimpleNamespace(shutdown=lambda: events.append("admission")),
    )
    monkeypatch.setattr(windows_socket, "pending_owner_snapshot", list)
    monkeypatch.setattr(runtime, "compose_shared_controls", lambda *args: object())
    monkeypatch.setattr(runtime.sys, "stdin", StringIO("\n"))

    def compose(*args, **kwargs):
        owner = helper.BoundedCoreStateDiagnostics(lambda raw: events.append("file"))
        owners.append(owner)
        kwargs["retain_core_state_debug"](owner)
        owner.capture("COORDINATOR_CURRENT", "NONE", "FALSE", {}, [], False)
        return object(), object()

    monkeypatch.setattr(runtime, "compose_shared_media", compose)

    def dispose_media(*args):
        assert owners[0].status()["publisher_settled"] is False
        events.append("media")

    monkeypatch.setattr(runtime, "settle_media", dispose_media)

    class Server:
        def __init__(self, *args, dispose, **kwargs):
            self.dispose = dispose
            self.calls = 0

        def start(self):
            return 1234

        def close(self, *, grace):
            self.calls += 1
            if self.calls == 1:
                return False
            self.dispose()
            return True

    monkeypatch.setattr(server_module, "AccountRpcServer", Server)
    folder = tmp_path / "bridge"
    folder.mkdir()
    for name in ("ca.pem", "server.pem", "server.key"):
        (folder / name).write_bytes(b"inert")
    runtime.worker_process(folder)
    assert owners[0].status()["publisher_settled"] is True
    assert owners[0]._thread is not None and not owners[0]._thread.is_alive()
    assert events[:2] == ["media", "admission"]
    assert files[-2][1]["custodyRetained"] is True
    assert files[-1][1]["custodyRetained"] is False
    assert files[-1][1]["mediaCoreStateDebug"]["publisher_settled"] is True
