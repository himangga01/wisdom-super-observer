"""Offline fixed-path API log wiring; no process, DB, listener or native worker."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def runtime():
    spec = importlib.util.spec_from_file_location(
        "debug_fixture_runtime", ROOT / "scripts/test-local-devices/runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_debug_default_off_and_independent_explicit_optin(runtime, monkeypatch):
    for key in (
        "WSO_TEST_LOCAL_MEDIA_BROWSER",
        "WSO_TEST_LOCAL_MEDIA_OBSERVE",
        "WSO_TEST_LOCAL_MEDIA_API_DEBUG",
    ):
        monkeypatch.delenv(key, raising=False)
    enabled = getattr(runtime, "api_debug_enabled", None)
    assert enabled is not None, "independent API diagnostics opt-in missing"
    assert enabled() is False
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    assert enabled() is True and runtime.observation_enabled() is False
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", "1")
    assert enabled() is True
    for value in ("true", "", "0"):
        monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", value)
        with pytest.raises(ValueError):
            enabled()


def test_debug_fixed_current_run_jsonl_and_api_child_flag(
    runtime, monkeypatch, tmp_path
):
    from tests.tvt_parity.test_local_media_diagnostics import safe_record

    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", raising=False)
    root = tmp_path / "root"
    folder = root / "auth-state" / ("local-devices-" + "a" * 32)
    folder.mkdir(parents=True)
    evidence = (
        root / ".superpowers/verification/local-device-browser-runtime" / folder.name
    )
    evidence.mkdir(parents=True)
    monkeypatch.setattr(runtime, "ROOT", root)
    monkeypatch.setattr(runtime, "EVIDENCE_ROOT", evidence.parent)
    acl = []
    monkeypatch.setattr(
        runtime,
        "borrowed_helpers",
        lambda: SimpleNamespace(
            private_directory=lambda path, **kwargs: acl.append(path),
            child_environment=dict,
        ),
    )
    configure = getattr(runtime, "configure_api_debug", None)
    assert configure is not None, "API app state file sink wiring missing"
    app = SimpleNamespace(state=SimpleNamespace(tvt_local_media_diagnostics_sink=None))
    configure(app, folder)
    sink = app.state.tvt_local_media_diagnostics_sink
    assert sink is not None
    sink(safe_record())
    target = evidence / "media-api-debug.jsonl"
    assert acl == [evidence]
    assert json.loads(target.read_text())["phase"] == "rpc"
    env = runtime.api_environment(
        {role: "offline" for role in ("APP", "IDENTITY", "SESSION")},
        {},
        {
            name: "offline"
            for name in ("ENDPOINT", "CA_FILE", "CLIENT_CERT_FILE", "CLIENT_KEY_FILE")
        },
        root / "key",
        root / "ca",
        media=True,
    )
    assert env["WSO_TEST_LOCAL_MEDIA_API_DEBUG"] == "1"
    assert "WSO_TEST_LOCAL_MEDIA_OBSERVE" not in env


def test_default_off_and_failed_writer_setup_do_not_touch_app(
    runtime, monkeypatch, tmp_path
):
    configure = getattr(runtime, "configure_api_debug", None)
    assert configure is not None, "API optional sink setup missing"
    for key in ("WSO_TEST_LOCAL_MEDIA_OBSERVE", "WSO_TEST_LOCAL_MEDIA_API_DEBUG"):
        monkeypatch.delenv(key, raising=False)
    app = SimpleNamespace(state=SimpleNamespace(tvt_local_media_diagnostics_sink=None))
    configure(app, tmp_path / "unowned")
    assert app.state.tvt_local_media_diagnostics_sink is None

    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    configure(app, tmp_path / "unowned")
    assert app.state.tvt_local_media_diagnostics_sink is None


def test_core_debug_wires_exact_original_once_and_fixed_private_file(
    runtime, monkeypatch, tmp_path
):
    from wso_core.tvt.local_service import LocalDeviceFailure

    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", raising=False)
    project = tmp_path / "root"
    folder = project / "auth-state" / ("local-devices-" + "b" * 32)
    folder.mkdir(parents=True)
    evidence = (
        project / ".superpowers/verification/local-device-browser-runtime" / folder.name
    )
    evidence.mkdir(parents=True)
    monkeypatch.setattr(runtime, "EVIDENCE_ROOT", evidence.parent)

    # Fixed helper source lives in the real root; custody root is test-only.
    def helper():
        from tests.contract.test_local_media_core_debug import helper_module

        return helper_module()

    monkeypatch.setattr(runtime, "core_debug_helper", helper, raising=False)
    monkeypatch.setattr(runtime, "ROOT", project)
    acl = []
    monkeypatch.setattr(
        runtime,
        "borrowed_helpers",
        lambda: SimpleNamespace(
            private_directory=lambda path, **kwargs: acl.append(path)
        ),
    )
    original_error = LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
    calls = []

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        raise original_error

    executor = SimpleNamespace(start=original)
    configure = getattr(runtime, "configure_core_debug", None)
    assert configure is not None, "worker executor file sink missing"
    configure(executor, folder)
    first = executor.start
    configure(executor, folder)
    assert executor.start is first
    args, kwargs = (object(),), {"cancel": object(), "retain_local": object()}
    with pytest.raises(LocalDeviceFailure) as failure:
        executor.start(*args, **kwargs)
    assert failure.value is original_error and calls == [(args, kwargs)]
    raw = (evidence / "media-core-debug.jsonl").read_bytes()
    assert json.loads(raw)["code"] == "LOCAL_DEVICE_DENIED"
    assert str(project).encode() not in raw and "private" not in raw.decode()
    assert acl


def test_core_debug_default_off_and_writer_setup_failure_keep_bound_original(
    runtime, monkeypatch, tmp_path
):
    configure = getattr(runtime, "configure_core_debug", None)
    assert configure is not None, "optional core sink missing"
    for key in ("WSO_TEST_LOCAL_MEDIA_OBSERVE", "WSO_TEST_LOCAL_MEDIA_API_DEBUG"):
        monkeypatch.delenv(key, raising=False)
    executor = SimpleNamespace(start=lambda *args, **kwargs: object())
    original = executor.start
    configure(executor, tmp_path / "unowned")
    assert executor.start is original
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    configure(executor, tmp_path / "unowned")
    assert executor.start is original


def test_core_debug_worker_child_receives_independent_optin(
    runtime, monkeypatch, tmp_path
):
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", raising=False)
    monkeypatch.setattr(
        runtime, "borrowed_helpers", lambda: SimpleNamespace(child_environment=dict)
    )
    decoder = tmp_path / "decoder"
    decoder.write_bytes(b"inert")
    env = runtime.worker_environment(
        {"WORKER": "offline"},
        {key: "1" for key in runtime.NATIVE_KEYS},
        tmp_path / "key",
        media=True,
        decoder=decoder,
    )
    assert env.get("WSO_TEST_LOCAL_MEDIA_API_DEBUG") == "1", (
        "worker independent debug flag was filtered"
    )
    assert "WSO_TEST_LOCAL_MEDIA_OBSERVE" not in env


def test_core_debug_worker_selects_owned_folder_before_worker_construction(
    runtime, monkeypatch, tmp_path
):
    from wso_core import secrets
    from wso_core.tvt import local_admission

    monkeypatch.setenv("WSO_TEST_LOCAL_DEVICE_NATIVE", "real")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_SHARED", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_API_DEBUG", "1")
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", raising=False)
    for key in (
        "WSO_WORKER_DATABASE_URL",
        "WSO_CONNECTION_KEY_FILE",
        "WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE",
        "WSO_TVT_WINDOWS_DECODER_PYTHON",
    ):
        monkeypatch.setenv(key, "inert")
    monkeypatch.setenv("WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256", "a" * 64)
    monkeypatch.setattr(runtime, "verify_source_approval", lambda *args: {})
    monkeypatch.setattr(
        runtime, "required_provider", lambda _: SimpleNamespace(_config=object())
    )
    monkeypatch.setattr(secrets, "FileKeyProvider", lambda _: object())
    monkeypatch.setattr(
        local_admission,
        "LocalDeviceAdmission",
        lambda *args: SimpleNamespace(shutdown=lambda: True),
    )
    folders = []

    def compose(*args, **kwargs):
        folders.append(kwargs.get("core_debug_folder"))
        raise RuntimeError("inert composition stop")

    monkeypatch.setattr(runtime, "compose_shared_media", compose)
    with pytest.raises(RuntimeError, match="inert composition stop"):
        runtime.worker_process(tmp_path / "bridge")
    assert folders == [tmp_path], "worker did not pass its exact owned context folder"


def test_core_debug_composition_keeps_executor_and_installs_before_media_worker(
    runtime, monkeypatch, tmp_path
):
    marker, executor, calls = object(), SimpleNamespace(start=object()), []

    def configure(given, folder):
        assert given is executor and folder is tmp_path
        given.start = marker
        calls.append("debug")

    monkeypatch.setattr(runtime, "configure_core_debug", configure)
    factories = {
        name: lambda *args, **kwargs: object()
        for name in (
            "MuxOriginalBudget",
            "WindowsSocketProvider",
            "NativeLocalMuxProvider",
            "DeviceEpochCoordinator",
            "MediaCreditLedger",
            "MuxSourceFactory",
        )
    }
    factories["SqlMuxAdmission"] = lambda *args: SimpleNamespace(worker_epoch=object())
    factories["MuxMediaExecutor"] = lambda *args: executor

    def worker(given, **kwargs):
        assert given is executor and given.start is marker
        calls.append("worker")
        value = object()
        kwargs["retain_owner"](value)
        return value

    factories["LocalMediaWorker"] = worker
    runtime.compose_shared_media(
        "inert",
        object(),
        object(),
        tmp_path / "decoder",
        factories=factories,
        core_debug_folder=tmp_path,
    )
    assert calls == ["debug", "worker"]
