"""Offline local OWNER runtime contracts; never opens DB, SDK or a listener."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "scripts/test-local-devices/runtime.py"


@pytest.fixture
def runtime():
    assert RUNTIME.is_file(), "new owned local-device runtime is not implemented"
    spec = importlib.util.spec_from_file_location("local_browser_runtime", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_mode_requires_media_and_exact_explicit_flag(runtime, monkeypatch):
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_SHARED", raising=False)
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_BROWSER", raising=False)
    assert runtime.shared_enabled() is False
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_SHARED", "1")
    with pytest.raises(ValueError, match="shared"):
        runtime.shared_enabled()
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    assert runtime.shared_enabled() is True
    for value in ("0", "true", "", "false"):
        monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_SHARED", value)
        with pytest.raises(ValueError, match="shared"):
            runtime.shared_enabled()


@pytest.mark.parametrize("change", [None, "profile", "legacy", "extra", "off"])
def test_shared_approval_binds_profile_before_any_resource(
    runtime, monkeypatch, tmp_path, change
):
    import hashlib

    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_SHARED", "1")
    root = tmp_path / "root"
    root.mkdir()
    (root / "source.py").write_bytes(b"inert")
    private = {}
    for name in runtime.PRIVATE_MEDIA_KEYS:
        path = tmp_path / name
        path.write_bytes(b"inert")
        monkeypatch.setenv(name, str(path))
        private[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(b"inert").hexdigest(),
        }
    body = {
        "schema_version": 3,
        "scope": "owned-local-device-shared-media-browser-only",
        "root_explicitly_accepted": True,
        "shared_profile": {
            "base_originals": 2,
            "main_originals": 1,
            "viewers": 12,
            "physical_slots": 16,
            "worker_process_bytes": 2 << 30,
            "native_process_bytes": 512 << 20,
            "decoder_process_bytes": 512 << 20,
            "retained_host_bytes": 1 << 30,
        },
        "sources": {"source.py": hashlib.sha256(b"inert").hexdigest()},
        "private_sources": private,
    }
    if change == "profile":
        body["shared_profile"]["worker_process_bytes"] = 4 << 30
    elif change == "legacy":
        body.pop("shared_profile")
        body.update(schema_version=2, scope="owned-local-device-media-browser-only")
    elif change == "extra":
        body["shared_profile"]["skip_native_review"] = True
    elif change == "off":
        monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_SHARED")
    raw = json.dumps(body).encode()
    approval = tmp_path / "approval.json"
    approval.write_bytes(raw)
    args = (approval, hashlib.sha256(raw).hexdigest())
    if change is None:
        assert (
            runtime.verify_source_approval(
                *args, root=root, required_paths={"source.py"}
            )
            == body["sources"]
        )
    else:
        with pytest.raises(ValueError, match="source approval"):
            runtime.verify_source_approval(
                *args, root=root, required_paths={"source.py"}
            )


def test_shared_environment_and_context_are_closed(runtime, tmp_path):
    decoder = tmp_path / "inert.exe"
    decoder.write_bytes(b"inert")
    roles = {name: "inert" for name in ("APP", "IDENTITY", "SESSION", "WORKER")}
    native = dict.fromkeys(runtime.NATIVE_KEYS, "inert")
    native[runtime.NATIVE_KEYS[0]] = "1"
    bridge = dict.fromkeys(
        ("ENDPOINT", "CA_FILE", "CLIENT_CERT_FILE", "CLIENT_KEY_FILE"), "inert"
    )
    api = runtime.api_environment(
        roles, {}, bridge, tmp_path / "key", tmp_path / "ca", media=True, shared=True
    )
    worker = runtime.worker_environment(
        roles,
        native,
        tmp_path / "key",
        media=True,
        shared=True,
        decoder=decoder,
        source_approval=(tmp_path / "approval.json", "a" * 64),
    )
    assert (
        api["WSO_TEST_LOCAL_MEDIA_SHARED"]
        == worker["WSO_TEST_LOCAL_MEDIA_SHARED"]
        == "1"
    )
    assert "WSO_WORKER_DATABASE_URL" not in api
    assert not any(name.startswith("WSO_TVT_WINDOWS_") for name in api)
    assert worker["WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256"] == "a" * 64
    assert "WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256" not in api
    assert runtime.shared_context(False) == {}
    assert runtime.shared_context(True) == {
        "sharedMedia": {
            "schemaVersion": 1,
            "enabled": True,
            "profile": runtime.SHARED_PROFILE,
        }
    }
    with pytest.raises(ValueError, match="shared"):
        runtime.api_environment(
            roles, {}, bridge, tmp_path / "key", tmp_path / "ca", shared=True
        )
    with pytest.raises(ValueError, match="approval"):
        runtime.worker_environment(
            roles, native, tmp_path / "key", media=True, shared=True, decoder=decoder
        )


def test_shared_worker_checks_approval_before_native_or_database(
    runtime, monkeypatch, tmp_path
):
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_SHARED", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_DEVICE_NATIVE", "real")
    monkeypatch.setenv(
        "WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE", str(tmp_path / "approval.json")
    )
    monkeypatch.setenv("WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256", "a" * 64)
    calls = []

    def refuse(*args, **kwargs):
        calls.append("review")
        raise ValueError("source approval inert rejection")

    def forbidden(*args):
        pytest.fail("unapproved worker reached native provider")

    monkeypatch.setattr(runtime, "verify_source_approval", refuse)
    monkeypatch.setattr(runtime, "required_provider", forbidden)
    with pytest.raises(ValueError, match="source approval inert rejection"):
        runtime.worker_process(tmp_path)
    assert calls == ["review"]


def test_shared_observation_requires_schema3_before_provider(
    runtime, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_SHARED", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_DEVICE_NATIVE", "real")
    monkeypatch.setenv(
        "WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE", str(tmp_path / "approval.json")
    )
    monkeypatch.setenv("WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256", "a" * 64)
    monkeypatch.setattr(runtime, "verify_source_approval", lambda *args: None)
    monkeypatch.setattr(runtime, "borrowed_helpers", lambda: object())

    def observer(write, *, shared):
        assert shared is True
        return SimpleNamespace(snapshot=lambda: {"schema_version": 2})

    monkeypatch.setattr(
        runtime,
        "observation_helper",
        lambda: SimpleNamespace(MediaObservation=observer),
    )

    def forbidden(*args):
        pytest.fail("legacy observation reached shared native provider")

    monkeypatch.setattr(runtime, "required_provider", forbidden)
    with pytest.raises(ValueError, match="shared observation"):
        runtime.worker_process(tmp_path)


def test_shared_required_closure_and_migration_are_explicit(runtime):
    required = {
        "scripts/test-local-devices/worker_job.py",
        "infra/migrations/versions/0016_tvt_device_media_epochs.py",
        "packages/core/src/wso_core/tvt/local_media_mux_admission.py",
        "packages/core/src/wso_core/tvt/local_media_mux_service.py",
        "services/tvt-bridge/src/wso_tvt_bridge/local_live_mux_provider.py",
        "services/tvt-bridge/src/wso_tvt_bridge/local_media_mux_rpc.py",
        "services/tvt-media/src/wso_tvt_media/mux_source.py",
        "services/tvt-media/src/wso_tvt_media/mux_budget.py",
        "services/api/src/wso_api/tvt/local_media_mux.py",
        "apps/web/src/app/monitoring/page.tsx",
    }
    assert required <= runtime.SHARED_SOURCES
    assert runtime.media_revision(shared=True) == "0017_tvt_main_return_retention"
    assert runtime.media_revision(shared=False) == "0015_tvt_local_media_capacity"


def test_shared_composition_retains_exact_instances(runtime, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4

    events = []

    def constructor(name):
        def make(*args, **kwargs):
            value = SimpleNamespace(
                name=name, args=args, kwargs=kwargs, worker_epoch=uuid4()
            )
            events.append(value)
            if name == "LocalMediaWorker" and "retain_owner" in kwargs:
                kwargs["retain_owner"](value)
            return value

        return make

    names = (
        "SqlMuxAdmission",
        "MuxOriginalBudget",
        "WindowsSocketProvider",
        "NativeLocalMuxProvider",
        "DeviceEpochCoordinator",
        "MuxMediaExecutor",
        "MediaCreditLedger",
        "MuxSourceFactory",
        "LocalMediaWorker",
    )
    factories = {name: constructor(name) for name in names}
    worker, admission = runtime.compose_shared_media(
        "inert", object(), object(), tmp_path / "inert.exe", factories=factories
    )
    objects = {item.name: item for item in events}
    assert tuple(item.name for item in events) == names
    assert admission is objects["SqlMuxAdmission"]
    budget = objects["MuxOriginalBudget"]
    assert budget.kwargs["worker_epoch"] is admission.worker_epoch
    provider = objects["NativeLocalMuxProvider"]
    assert provider.kwargs == {"budget": budget, "admission": admission}
    coordinator = objects["DeviceEpochCoordinator"]
    assert coordinator.args == (admission, provider, budget)
    executor = objects["MuxMediaExecutor"]
    assert executor.args == (admission, coordinator)
    factory = objects["MuxSourceFactory"]
    assert factory.args == (executor, objects["MediaCreditLedger"])
    assert worker.args == (executor,)
    assert worker.kwargs["source_factory"] is factory


def test_shared_launch_retains_owner_and_uses_inert_isolated_bootstrap(
    runtime, tmp_path
):
    from types import SimpleNamespace

    calls = []
    marker = object()

    def launch(command, **kwargs):
        calls.append((command, kwargs))
        return marker

    env = {
        "WSO_TEST_LOCAL_MEDIA_SHARED": "1",
        "WSO_TEST_LOCAL_MEDIA_BROWSER": "1",
        "PRIVATE_INERT": "do-not-embed",
    }
    assert (
        runtime.spawn_shared_worker(tmp_path, env, SimpleNamespace(launch=launch))
        is marker
    )
    command, kwargs = calls[0]
    assert command[1:4] == ["-I", "-S", "-c"]
    assert command[0] == sys._base_executable
    assert "do-not-embed" not in " ".join(command)
    assert kwargs["env"] is env
    assert kwargs["cwd"] == ROOT


def test_shared_worker_receipt_failure_stays_failed_after_reap(runtime, tmp_path):
    from types import SimpleNamespace

    entries = []
    owner = SimpleNamespace(
        close_step=lambda: True, receipt=lambda: {"failed": True, "exit": 1}
    )
    with pytest.raises(RuntimeError, match="failed after settlement"):
        runtime.settle_shared_worker(owner, tmp_path, receipt=entries.append)
    assert entries == [{"failed": True, "exit": 1}]


def test_shared_api_selects_mux_client_and_refuses_worker_constructors(
    runtime, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    import sqlalchemy
    from wso_api import auth, main
    from wso_core.secrets import SecretCipher
    from wso_core.tvt.local_admission import LocalDeviceAdmission
    from wso_core.tvt.local_media_admission import LocalMediaAdmission
    from wso_core.tvt.local_media_mux_admission import SqlMuxAdmission
    from wso_core.tvt.local_media_mux_service import (
        DeviceEpochCoordinator,
        MuxMediaExecutor,
    )
    from wso_core.tvt.local_media_service import LocalMediaExecutor
    from wso_core.tvt.local_service import LocalVerificationExecutor
    from wso_core.tvt.token_vault import TokenVault
    from wso_tvt_bridge.local_live_mux_ownership import MuxOriginalBudget
    from wso_tvt_bridge.local_live_mux_provider import NativeLocalMuxProvider
    from wso_tvt_bridge.local_live_provider import NativeLocalLiveProvider
    from wso_tvt_bridge.windows_socket import WindowsSocketProvider

    constructors = (
        LocalDeviceAdmission,
        LocalMediaAdmission,
        LocalMediaExecutor,
        LocalVerificationExecutor,
        TokenVault,
        NativeLocalLiveProvider,
        SqlMuxAdmission,
        DeviceEpochCoordinator,
        MuxMediaExecutor,
        NativeLocalMuxProvider,
        MuxOriginalBudget,
        WindowsSocketProvider,
    )
    for factory in constructors:
        monkeypatch.setattr(factory, "__init__", factory.__init__)
    monkeypatch.setattr(SecretCipher, "open", SecretCipher.open)
    for key in (
        *runtime.NATIVE_KEYS,
        "WSO_WORKER_DATABASE_URL",
        "WSO_TVT_WINDOWS_DECODER_PYTHON",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_SHARED", "1")
    for role in ("APP", "IDENTITY", "SESSION"):
        monkeypatch.setenv("WSO_" + role + "_DATABASE_URL", "inert")
    monkeypatch.setattr(runtime, "borrowed_helpers", lambda: object())
    monkeypatch.setattr(
        auth.AuthSettings,
        "from_environment",
        lambda: SimpleNamespace(session_database_url="inert"),
    )
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: object())
    calls = []

    def create_app(**kwargs):
        calls.append(kwargs)
        for factory in constructors:
            with pytest.raises(RuntimeError, match="capability forbidden"):
                factory.__init__(object())
        raise ValueError("inert stop before API runtime")

    monkeypatch.setattr(main, "create_app", create_app)
    with pytest.raises(ValueError, match="inert stop"):
        runtime.api_process(tmp_path)
    assert calls == [{"shared_media_enabled": True}]


def test_shared_media_constructor_failure_settles_exact_executor_before_admission(
    runtime, tmp_path
):
    from types import SimpleNamespace
    from uuid import uuid4

    events = []
    admission = SimpleNamespace(
        worker_epoch=uuid4(), shutdown=lambda: events.append("admission") or True
    )
    executor = SimpleNamespace(shutdown=lambda: events.append("executor") or True)

    def fail(*args, **kwargs):
        raise ValueError("inert failed media constructor")

    factories = dict.fromkeys(
        (
            "MuxOriginalBudget",
            "WindowsSocketProvider",
            "NativeLocalMuxProvider",
            "DeviceEpochCoordinator",
            "MediaCreditLedger",
            "MuxSourceFactory",
        ),
        lambda *args, **kwargs: object(),
    )
    factories.update(
        SqlMuxAdmission=lambda *args: admission,
        MuxMediaExecutor=lambda *args: executor,
        LocalMediaWorker=fail,
    )
    with pytest.raises(ValueError, match="failed media constructor"):
        runtime.compose_shared_media(
            "inert", object(), object(), tmp_path / "inert", factories=factories
        )
    assert events == ["executor", "admission"]


def test_shared_observer_wraps_provider_before_coordinator_and_preserves_source_hook(
    runtime, tmp_path
):
    from types import SimpleNamespace
    from uuid import uuid4

    events = []
    original, wrapped = object(), object()
    source_hook = lambda: None

    def wrap(provider):
        assert provider is original
        events.append("wrap")
        return wrapped

    def coordinator(admission, provider, budget):
        assert provider is wrapped
        events.append("coordinator")
        return object()

    def worker(*args, **kwargs):
        assert kwargs["observation_factory"] is source_hook
        value = object()
        if "retain_owner" in kwargs:
            kwargs["retain_owner"](value)
        return value

    factories = dict.fromkeys(
        (
            "MuxOriginalBudget",
            "WindowsSocketProvider",
            "MuxMediaExecutor",
            "MediaCreditLedger",
            "MuxSourceFactory",
        ),
        lambda *args, **kwargs: object(),
    )
    factories.update(
        SqlMuxAdmission=lambda *args: SimpleNamespace(worker_epoch=uuid4()),
        NativeLocalMuxProvider=lambda *args, **kwargs: original,
        DeviceEpochCoordinator=coordinator,
        LocalMediaWorker=worker,
    )
    runtime.compose_shared_media(
        "inert",
        object(),
        object(),
        tmp_path / "inert",
        factories=factories,
        observer=SimpleNamespace(wrap_mux_provider=wrap, begin_source=source_hook),
    )
    assert events == ["wrap", "coordinator"]


@pytest.mark.parametrize("returned", [False, True])
def test_r1_partial_media_owner_is_retained_before_start_and_settled_first(
    runtime, monkeypatch, tmp_path, returned
):
    from types import SimpleNamespace
    from uuid import uuid4

    events = []
    admission = SimpleNamespace(
        worker_epoch=uuid4(), shutdown=lambda: events.append("admission") or True
    )
    executor = SimpleNamespace(shutdown=lambda: events.append("executor") or True)

    class Partial:
        attempts = 0

        def shutdown(self):
            self.attempts += 1
            events.append(
                "partial-pending" if self.attempts == 1 else "partial-settled"
            )
            return self.attempts > 1

    partial = Partial()

    def constructor(*args, retain_owner=None, **kwargs):
        assert callable(retain_owner), (
            "original media owner must be retained before start"
        )
        retain_owner(partial)
        events.append("thread-start-attempt")
        if returned:
            return object()  # A different return may not replace the retained owner.
        raise ValueError("inert readiness failed")

    factories = dict.fromkeys(
        (
            "MuxOriginalBudget",
            "WindowsSocketProvider",
            "NativeLocalMuxProvider",
            "DeviceEpochCoordinator",
            "MediaCreditLedger",
            "MuxSourceFactory",
        ),
        lambda *args, **kwargs: object(),
    )
    factories.update(
        SqlMuxAdmission=lambda *args: admission,
        MuxMediaExecutor=lambda *args: executor,
        LocalMediaWorker=constructor,
    )

    def pause(_):
        assert "executor" not in events and "admission" not in events
        events.append("retained-wait")

    monkeypatch.setattr(runtime.time, "sleep", pause)
    with pytest.raises(ValueError):
        runtime.compose_shared_media(
            "inert", object(), object(), tmp_path / "inert", factories=factories
        )
    assert events == [
        "thread-start-attempt",
        "partial-pending",
        "retained-wait",
        "partial-settled",
        "executor",
        "admission",
    ]


@pytest.mark.parametrize("phase", ["ready_timeout", "interrupted_start"])
def test_r1_actual_media_constructor_retention_with_fake_loop_and_thread(
    runtime, monkeypatch, tmp_path, phase
):
    import threading
    from types import SimpleNamespace
    from uuid import uuid4

    from wso_tvt_media import worker as media_module

    events, threads = [], []

    class Event:
        def __init__(self):
            self.value = False

        def set(self):
            self.value = True

        def clear(self):
            self.value = False

        def is_set(self):
            return self.value

        def wait(self, timeout=None):
            return self.value

    class Loop:
        closed = False

        def is_closed(self):
            return self.closed

        def is_running(self):
            return False

        def close(self):
            events.append("loop-closed")
            self.closed = True

        def create_task(self, coroutine):
            coroutine.close()
            return SimpleNamespace(cancel=lambda: None)

        def run_forever(self):
            events.append("loop-run")

        def stop(self):
            pass

        def call_soon_threadsafe(self, callback):
            callback()

    loop = Loop()

    class Thread:
        def __init__(self, *, target, **kwargs):
            self.target, self.ident, self.alive = target, None, False
            threads.append(self)

        def start(self):
            events.append("thread-start-attempt")
            if phase == "interrupted_start":
                raise KeyboardInterrupt()
            self.ident, self.alive = 7, True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            events.append("thread-joined")

        def finish_original(self):
            self.ident, self.alive = 7, True
            try:
                self.target()
            finally:
                self.alive = False

    def forbidden_future(*args):
        raise AssertionError("unready fake media loop must not schedule foreign work")

    monkeypatch.setattr(
        media_module,
        "threading",
        SimpleNamespace(Event=Event, Lock=threading.Lock, Thread=Thread),
    )
    monkeypatch.setattr(
        media_module,
        "asyncio",
        SimpleNamespace(
            new_event_loop=lambda: loop,
            set_event_loop=lambda _: None,
            run_coroutine_threadsafe=forbidden_future,
        ),
    )

    def executor_stop():
        assert loop.closed
        events.append("executor")
        return True

    executor = SimpleNamespace(shutdown=executor_stop)
    admission = SimpleNamespace(
        worker_epoch=uuid4(), shutdown=lambda: events.append("admission") or True
    )
    factories = dict.fromkeys(
        (
            "MuxOriginalBudget",
            "WindowsSocketProvider",
            "NativeLocalMuxProvider",
            "DeviceEpochCoordinator",
            "MediaCreditLedger",
        ),
        lambda *args, **kwargs: object(),
    )
    factories.update(
        SqlMuxAdmission=lambda *args: admission,
        MuxMediaExecutor=lambda *args: executor,
        MuxSourceFactory=lambda *args: SimpleNamespace(executor=executor),
        LocalMediaWorker=media_module.LocalMediaWorker,
    )

    def pause(_):
        assert (
            len(threads) == 1 and "executor" not in events and "admission" not in events
        )
        events.append("original-retained")
        threads[0].finish_original()

    monkeypatch.setattr(runtime.time, "sleep", pause)
    decoder = tmp_path / "inert-decoder.exe"
    decoder.write_bytes(b"inert")
    expected = KeyboardInterrupt if phase == "interrupted_start" else Exception
    with pytest.raises(expected):
        runtime.compose_shared_media(
            "inert", object(), object(), decoder, factories=factories
        )
    assert "original-retained" in events
    assert (
        events.index("loop-closed")
        < events.index("executor")
        < events.index("admission")
    )
    assert not threads[0].is_alive() and loop.closed


def test_shared_control_adapter_preserves_same_worker_before_observation(
    runtime, monkeypatch
):
    from types import SimpleNamespace

    from wso_tvt_bridge import local_media_mux_rpc

    events = []
    worker, adapter, wrapped = object(), object(), object()

    def construct(original):
        assert original is worker
        events.append("adapter")
        return adapter

    def wrap(original):
        assert original is adapter
        events.append("wrap")
        return wrapped

    monkeypatch.setattr(local_media_mux_rpc, "LocalMuxWorkerAdapter", construct)
    observer = SimpleNamespace(wrap_mux_controls=wrap)
    assert runtime.compose_shared_controls(worker, observer) is wrapped
    assert events == ["adapter", "wrap"]
    assert runtime.compose_shared_controls(worker) is adapter


@pytest.mark.parametrize("failure", [None, "controls", "server"])
def test_shared_worker_runtime_selects_same_media_and_mux_server(
    runtime, monkeypatch, tmp_path, failure
):
    import io
    from types import SimpleNamespace

    from wso_core import secrets
    from wso_core.tvt import local_admission
    from wso_tvt_bridge import server, windows_socket

    monkeypatch.setenv("WSO_TEST_LOCAL_DEVICE_NATIVE", "real")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_SHARED", "1")
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_OBSERVE", raising=False)
    monkeypatch.setenv("WSO_WORKER_DATABASE_URL", "inert")
    monkeypatch.setenv("WSO_CONNECTION_KEY_FILE", "inert")
    monkeypatch.setenv("WSO_TVT_WINDOWS_DECODER_PYTHON", str(tmp_path / "inert.exe"))
    monkeypatch.setenv(
        "WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE", str(tmp_path / "approval.json")
    )
    monkeypatch.setenv("WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256", "a" * 64)
    events, written = [], {}
    monkeypatch.setattr(
        runtime, "verify_source_approval", lambda *args: events.append("review")
    )
    monkeypatch.setattr(secrets, "FileKeyProvider", lambda _: object())
    inventory = SimpleNamespace(shutdown=lambda: events.append("inventory-close"))
    monkeypatch.setattr(
        local_admission, "LocalDeviceAdmission", lambda *args: inventory
    )
    provider = SimpleNamespace(_config=object())
    monkeypatch.setattr(runtime, "required_provider", lambda _: provider)
    media = SimpleNamespace(
        shutdown=lambda: events.append("media-close") or True,
        executor=SimpleNamespace(coordinator=object()),
    )
    admission = SimpleNamespace(
        shutdown=lambda: events.append("admission-close") or True
    )

    def compose(url, keys, config, decoder):
        assert config is provider._config
        events.append("compose")
        return media, admission

    monkeypatch.setattr(runtime, "compose_shared_media", compose)
    monkeypatch.setattr(
        runtime,
        "borrowed_helpers",
        lambda: SimpleNamespace(
            write_private=lambda path, data: written.update({path.name: data})
        ),
    )
    monkeypatch.setattr(windows_socket, "pending_owner_snapshot", lambda: ())
    monkeypatch.setattr(runtime.sys, "stdin", io.StringIO("close\n"))
    for name in ("ca.pem", "server.pem", "server.key"):
        (tmp_path / name).write_bytes(b"inert")

    class Server:
        def __init__(self, *args, **kwargs):
            assert kwargs["shared_media_enabled"] is True
            assert kwargs["local_media_worker"] is media
            assert kwargs["local_media_mux_worker"].worker is media
            if failure == "server":
                raise ValueError("inert server construction failure")
            self.dispose = kwargs["dispose"]

        def start(self):
            return 1234

        def close(self, **kwargs):
            self.dispose()
            return True

    monkeypatch.setattr(server, "AccountRpcServer", Server)
    monkeypatch.setattr(server, "ServerConfig", lambda **kwargs: object())
    if failure == "controls":

        def fail_controls(*args):
            raise ValueError("inert controls construction failure")

        monkeypatch.setattr(runtime, "compose_shared_controls", fail_controls)
    if failure is None:
        runtime.worker_process(tmp_path)
        assert written["worker-ready.json"]["sharedMediaEnabled"] is True
    else:
        with pytest.raises(ValueError, match="construction failure"):
            runtime.worker_process(tmp_path)
        assert "worker-ready.json" not in written
    assert events == [
        "review",
        "compose",
        "media-close",
        "admission-close",
        "inventory-close",
    ]


def inert_input():
    return {
        "schema_version": 1,
        "devices": [
            {
                "alias": "Recorder one",
                "store_label": "Store one",
                "credentials": {
                    "schema_version": 1,
                    "kind": "TVT_DEVICE",
                    "serial": "TEST123",
                    "country": "KR",
                    "username": "private-user",
                    "password": "private-password",
                },
            },
            {
                "alias": "Recorder two",
                "store_label": "Store two",
                "credentials": {
                    "schema_version": 1,
                    "kind": "TVT_DEVICE",
                    "serial": "TEST456",
                    "country": "KR",
                    "username": "private-user",
                    "password": "private-password",
                },
            },
        ],
    }


def test_cli_without_activation_cannot_read_inputs_or_start_children(tmp_path):
    assert RUNTIME.is_file(), "new explicit local-device activation boundary missing"
    result = subprocess.run(
        [sys.executable, str(RUNTIME)],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if not k.startswith("WSO_")},
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == b""
    assert (
        result.stderr.strip()
        == b"Local device browser fixture requires explicit activation."
    )
    assert list(tmp_path.iterdir()) == []


def test_private_input_is_closed_two_devices_and_never_represented(runtime):
    items = runtime.parse_input(json.dumps(inert_input()).encode())
    assert len(items) == 2
    assert [item.alias for item in items] == ["Recorder one", "Recorder two"]
    assert "private-password" not in repr(items) and "TEST123" not in repr(items)
    assert items[0].credentials.to_encrypt_bytes().startswith(b'{"schema_version":1,')


@pytest.mark.parametrize(
    "change",
    ["actor", "endpoint", "one", "duplicate", "secret-label", "duplicate-json"],
)
def test_private_input_rejects_scope_or_transport_selection(runtime, change):
    body = inert_input()
    if change == "actor":
        body["actor"] = "owner"
    elif change == "endpoint":
        body["devices"][0]["endpoint"] = "https://evil.test"
    elif change == "one":
        body["devices"] = body["devices"][:1]
    elif change == "duplicate":
        body["devices"][1]["credentials"] = body["devices"][0]["credentials"]
    elif change == "secret-label":
        body["devices"][0]["alias"] = "private-password"
    raw = (
        b'{"schema_version":1,"schema_version":1,"devices":[]}'
        if change == "duplicate-json"
        else json.dumps(body).encode()
    )
    with pytest.raises(ValueError, match="private local input"):
        runtime.parse_input(raw)


def test_api_and_worker_environment_keep_capabilities_separate(runtime):
    roles = {
        key: "private-" + key
        for key in ["ADMIN", "APP", "IDENTITY", "SESSION", "WORKER"]
    }
    auth = {
        "WSO_OIDC_ISSUER": "https://localhost:1234",
        "WSO_OIDC_CLIENT_ID": "fixture-web",
        "WSO_OIDC_JWKS_URL": "https://localhost:1234/jwks",
        "WSO_AUTH_EXCHANGE_KEY": "exchange",
        "WSO_PUBLIC_ORIGIN": "https://localhost:3543",
    }
    bridge = {
        "ENDPOINT": "localhost:12345",
        "CA_FILE": "ca",
        "CLIENT_CERT_FILE": "client",
        "CLIENT_KEY_FILE": "key",
    }
    api = runtime.api_environment(
        roles, auth, bridge, Path("owned/key"), Path("owned/ca.pem")
    )
    assert {k for k in api if k.endswith("DATABASE_URL")} == {
        "WSO_APP_DATABASE_URL",
        "WSO_IDENTITY_DATABASE_URL",
        "WSO_SESSION_DATABASE_URL",
    }
    assert api["WSO_CONNECTION_KEY_FILE"] == str(Path("owned/key"))
    assert not any(k.startswith("WSO_TVT_WINDOWS_") for k in api)
    native = {k: "approved" for k in runtime.NATIVE_KEYS}
    native[runtime.NATIVE_KEYS[0]] = "1"
    worker = runtime.worker_environment(roles, native, Path("owned/key"))
    assert {k for k in worker if k.endswith("DATABASE_URL")} == {
        "WSO_WORKER_DATABASE_URL"
    }
    assert all(worker[k] == native[k] for k in runtime.NATIVE_KEYS)
    assert "WSO_APP_DATABASE_URL" not in worker and "WSO_OIDC_ISSUER" not in worker


def test_real_mode_refuses_missing_native_loader_before_admission(runtime):
    with pytest.raises(ValueError, match="reviewed native provider unavailable"):
        runtime.required_provider(lambda: None)


def test_real_mode_refuses_inert_provider_substitution(runtime):
    with pytest.raises(ValueError, match="reviewed native provider unavailable"):
        runtime.required_provider(lambda: object())


def test_source_anchors_match_independently_reviewed_current_receipts(runtime):
    assert all(len(value) == 64 for value in runtime.ANCHORS.values()), (
        "malformed approval pin"
    )
    sources = runtime.anchored_sources()
    assert len(sources) == 24
    assert (
        sources["infra/migrations/versions/0012_tvt_local_devices.py"]
        == "883b4e09532dad7f9df62621a160b45a9561757599281737f98d1cfa54271ab3"
    )
    assert (
        sources["services/api/src/wso_api/main.py"]
        == "8c4770bef1c943814832198040423e98f2abbf66b025375d190e675a56d122b1"
    )
    assert (
        sources["apps/web/src/lib/tvt/local-device-api.ts"]
        == "50cb1e4288494834dd072595016c2b189316beb39e1c5852abfb2694164d328a"
    )


def test_node_stop_is_durable_and_cli_without_activation_is_inert(tmp_path):
    module = (ROOT / "scripts/test-local-devices/server.mjs").as_uri()
    code = f"""const {{installDurableStop}}=await import({json.dumps(module)});
let present=false,calls=0;const check=installDurableStop('owned-shutdown',async()=>{{calls++}},{{exists:()=>present}});
await check();if(calls)throw Error('implicit stop');present=true;await check();if(calls!==1)throw Error('durable stop ignored');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        cwd=tmp_path,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        ["node", str(ROOT / "scripts/test-local-devices/server.mjs")],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if not k.startswith("WSO_")},
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1 and result.stdout == b""
    assert list(tmp_path.iterdir()) == []


def test_approval_is_exact_root_receipt_and_source_identity(runtime, tmp_path):
    import hashlib

    root = tmp_path / "root"
    root.mkdir()
    (root / "file.py").write_bytes(b"approved\n")
    body = {
        "schema_version": 1,
        "root_explicitly_accepted": True,
        "scope": "owned-local-device-browser-only",
        "sources": {
            "file.py": "f7d9e9c2b3c9b23f73ba33e5fa8e1d99e5f2ebd9a8e9e8c9d0611b4a9e2fccef"
        },
    }
    # Independently fixed exact bytes for this inert single-file fixture.
    body["sources"]["file.py"] = hashlib.sha256(b"approved\n").hexdigest()
    raw = json.dumps(body).encode()
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(raw)
    approved = hashlib.sha256(raw).hexdigest()
    runtime.verify_source_approval(
        receipt, approved, required_paths={"file.py"}, root=root
    )
    (root / "file.py").write_bytes(b"unapproved\n")
    with pytest.raises(ValueError, match="source approval"):
        runtime.verify_source_approval(
            receipt, approved, required_paths={"file.py"}, root=root
        )
    with pytest.raises(ValueError, match="source approval"):
        runtime.verify_source_approval(
            receipt, "0" * 64, required_paths={"file.py"}, root=root
        )


def test_resource_owner_outlives_reporting_deadline_without_termination(runtime):
    class Child:
        def __init__(self):
            self.polls, self.stdin = 0, self

        def write(self, value):
            assert value == b"close\n"

        def flush(self):
            pass

        def poll(self):
            self.polls += 1
            return None if self.polls < 5 else 0

        def terminate(self):
            pytest.fail("resource owner was terminated")

    receipts = []
    with pytest.raises(RuntimeError, match="after settlement"):
        runtime.settle_child(
            Child(),
            Path("unused"),
            "worker",
            budget=0,
            receipt=lambda value: receipts.append(value),
            pause=lambda _: None,
        )
    assert any(value["custody_retained"] for value in receipts)
    assert receipts[-1]["exit"] == 0


@pytest.mark.parametrize("media,shared", [(False, False), (True, False), (True, True)])
def test_owned_migration_unwinds_before_original_database_owner(
    runtime, monkeypatch, tmp_path, media, shared
):
    from types import SimpleNamespace

    from alembic import command

    from tests.integration import test_tvt_directory_admission as accepted

    events = []
    name = "w07_directory_" + "a" * 32

    class Db:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement):
            assert "current_database" in str(statement)
            return SimpleNamespace(
                one=lambda: (name, "owned-w07-directory-" + "b" * 32)
            )

    engine = SimpleNamespace(
        url=SimpleNamespace(
            database=name,
            render_as_string=lambda **kwargs: (
                "postgresql+psycopg://inert@localhost/" + name
            ),
        ),
        connect=Db,
    )

    def generator():
        events.append("original-owner-enter")
        try:
            yield {"ADMIN": engine}
        finally:
            events.append("original-owner-exit")

    monkeypatch.setattr(
        accepted, "directory_database", SimpleNamespace(__wrapped__=generator)
    )
    monkeypatch.setattr(
        command, "upgrade", lambda cfg, revision: events.append(("upgrade", revision))
    )
    monkeypatch.setattr(
        command,
        "downgrade",
        lambda cfg, revision: events.append(("downgrade", revision)),
    )
    with (
        pytest.raises(ValueError, match="body failed"),
        runtime.owned_database(tmp_path, media=media, shared=shared),
    ):
        raise ValueError("body failed")
    expected = ["original-owner-enter", ("upgrade", "0012_tvt_local_devices")]
    if media:
        expected += [
            (
                "upgrade",
                "0017_tvt_main_return_retention"
                if shared
                else "0015_tvt_local_media_capacity",
            ),
            ("downgrade", "0012_tvt_local_devices"),
        ]
    assert events == expected + [
        ("downgrade", "0011_tvt_directory_read_tickets"),
        "original-owner-exit",
    ]


def test_denied_source_approval_never_executes_borrowed_python(
    runtime, monkeypatch, tmp_path
):
    monkeypatch.setenv("WSO_TEST_LOCAL_DEVICE_NATIVE", "real")
    monkeypatch.setenv("WSO_TEST_BROWSER_TLS_DIR", str(tmp_path))
    path = ROOT / "auth-state" / ("local-devices-" + "0" * 32) / "context.json"
    monkeypatch.setenv("WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE", str(path))
    monkeypatch.setenv(
        "WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_FILE", str(tmp_path / "denied.json")
    )
    monkeypatch.setenv("WSO_TEST_LOCAL_BROWSER_SOURCE_APPROVAL_SHA256", "0" * 64)
    imported = []

    def loader():
        imported.append(True)
        raise AssertionError("unadmitted borrowed code executed")

    def deny(*args, **kwargs):
        raise ValueError("source approval test denial")

    monkeypatch.setattr(runtime, "borrowed_helpers", loader)
    monkeypatch.setattr(runtime, "verify_source_approval", deny)
    with pytest.raises(ValueError, match="source approval test denial"):
        runtime.coordinate()
    assert imported == []


def test_node_queues_stop_until_original_runtime_folder_exists():
    module = (ROOT / "scripts/test-local-devices/server.mjs").as_uri()
    code = f"""const m=await import({json.dumps(module)});let present=false,marker=false,pauses=0,overrun=0;
const child={{exitCode:null,signalCode:null,kill(){{throw Error('resource owner killed')}}}};
if(typeof m.deliverRuntimeStop!=='function')throw Error('queued marker delivery missing');
await m.deliverRuntimeStop(child,'owned',{{deadline:0,now:()=>1,exists:()=>present,write:()=>{{marker=true;child.exitCode=0}},pause:async()=>{{if(++pauses===3)present=true}},onOverrun:()=>{{overrun++}}}});
if(!marker||pauses!==3||overrun!==1)throw Error('early stop lost or reporting custody reset');
let writes=0;await m.deliverRuntimeStop({{exitCode:1,signalCode:null}},'absent',{{write:()=>{{writes++}}}});if(writes)throw Error('retired owner received marker');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        cwd=ROOT,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_node_checks_borrowed_hash_before_dynamic_execution():
    module = (ROOT / "scripts/test-local-devices/server.mjs").as_uri()
    code = f"""const m=await import({json.dumps(module)});let imported=0;
if(typeof m.admittedHelpers!=='function')throw Error('borrowed source admission missing');
let refused=false;try{{await m.admittedHelpers({{read:()=>Buffer.from('unadmitted source'),importer:async()=>{{imported++;return {{}}}}}})}}catch{{refused=true}}
if(!refused||imported!==0)throw Error('unadmitted borrowed module executed');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        cwd=ROOT,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows direct interpreter admission")
def test_direct_base_child_restores_venv_prefix_before_native_admission(
    runtime, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    probe = tmp_path / "probe.py"
    probe.write_text(
        """import json,os,sys
from pathlib import Path
from wso_tvt_bridge.windows_socket import direct_interpreter
try:
 direct,site=direct_interpreter(); admitted=True
except Exception:
 admitted=False
print(json.dumps({'pid':os.getpid(),'prefix_ok':Path(sys.prefix).name=='.venv','admitted':admitted}))
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "__file__", str(probe))
    actual = subprocess.Popen
    commands = []

    def spawn(argv, **kwargs):
        commands.append(argv)
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return actual(argv, **kwargs)

    monkeypatch.setattr(
        runtime,
        "subprocess",
        SimpleNamespace(
            Popen=spawn,
            PIPE=subprocess.PIPE,
            DEVNULL=subprocess.DEVNULL,
            CREATE_NO_WINDOW=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ),
    )
    child = runtime.spawn_python([], runtime.borrowed_helpers().child_environment())
    stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, stderr
    result = json.loads(stdout)
    assert commands[0][0] == sys._base_executable
    assert result["pid"] == child.pid, "venv redirector hid the original child"
    assert result["prefix_ok"] and result["admitted"], (
        "direct base launcher lost admitted venv context"
    )


def test_next_subordinate_exits_after_close_even_with_retained_dev_handles():
    module = (ROOT / "scripts/test-local-devices/server.mjs").as_uri()
    code = f"""const m=await import({json.dumps(module)});setInterval(()=>{{}},60000);
if(typeof m.closeNextOwned!=='function')throw Error('deliberate Next exit missing');
await m.closeNextOwned({{close:async()=>{{await new Promise(r=>setTimeout(r,5));process.stdout.write('app-closed\\n')}}}},{{close(){{}},closeAllConnections(){{}}}});
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", code],
        cwd=ROOT,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"app-closed\n"


def test_owner_banner_distinguishes_synthetic_owner_from_real_devices(runtime):
    html = "Sign in as synthetic directory staff; Synthetic directory fixture; Invented account and devices. No vendor connection."
    text = runtime.owner_page_text(html)
    assert "synthetic owner" in text
    assert "real registered devices" in text
    assert "read-only verification" in text
    assert "No vendor connection" not in text


def test_media_mode_requires_exact_opt_in(runtime, monkeypatch):
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_BROWSER", raising=False)
    assert runtime.media_enabled() is False
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    assert runtime.media_enabled() is True
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "true")
    with pytest.raises(ValueError, match="media mode"):
        runtime.media_enabled()


def test_media_decoder_configuration_remains_worker_only(runtime, tmp_path):
    decoder = tmp_path / "python.exe"
    decoder.write_bytes(b"inert executable marker")
    roles = {key: "private-" + key for key in ["APP", "IDENTITY", "SESSION", "WORKER"]}
    native = {key: "reviewed" for key in runtime.NATIVE_KEYS}
    native[runtime.NATIVE_KEYS[0]] = "1"
    worker = runtime.worker_environment(
        roles, native, tmp_path / "key", media=True, decoder=decoder
    )
    assert worker["WSO_TEST_LOCAL_MEDIA_BROWSER"] == "1"
    assert worker["WSO_TVT_WINDOWS_DECODER_PYTHON"] == str(decoder)
    api = runtime.api_environment(
        roles,
        {},
        {
            key: "owned"
            for key in ["ENDPOINT", "CA_FILE", "CLIENT_CERT_FILE", "CLIENT_KEY_FILE"]
        },
        tmp_path / "key",
        tmp_path / "ca",
        media=True,
    )
    assert api["WSO_TEST_LOCAL_MEDIA_BROWSER"] == "1"
    assert "WSO_TVT_WINDOWS_DECODER_PYTHON" not in api
    assert "WSO_WORKER_DATABASE_URL" not in api


def test_media_shutdown_retains_original_until_both_owners_confirm(runtime):
    events = []

    class Worker:
        def __init__(self):
            self.calls = 0

        def shutdown(self):
            self.calls += 1
            events.append("worker")
            return self.calls >= 3

    class Admission:
        def __init__(self):
            self.calls = 0

        def shutdown(self):
            self.calls += 1
            events.append("admission")
            return self.calls >= 2

    runtime.settle_media(
        Worker(), Admission(), pause=lambda _: events.append("retained")
    )
    assert events == [
        "worker",
        "retained",
        "worker",
        "retained",
        "worker",
        "admission",
        "retained",
        "admission",
    ]


def test_v2_media_approval_binds_private_paths_and_requires_opt_in(
    runtime, monkeypatch, tmp_path
):
    import hashlib

    root = tmp_path / "root"
    root.mkdir()
    (root / "file.py").write_bytes(b"approved\n")
    private = {}
    for key in [
        "WSO_TVT_WINDOWS_LOCAL_INVENTORY_SOURCE_REVIEW",
        "WSO_TVT_WINDOWS_LOCAL_INVENTORY_RUNTIME_REVIEW",
        "WSO_TVT_WINDOWS_DECODER_PYTHON",
    ]:
        path = tmp_path / key
        path.write_bytes(b"inert approved private input")
        monkeypatch.setenv(key, str(path))
        private[key] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    body = {
        "schema_version": 2,
        "root_explicitly_accepted": True,
        "scope": "owned-local-device-media-browser-only",
        "sources": {"file.py": hashlib.sha256(b"approved\n").hexdigest()},
        "private_sources": private,
    }
    raw = json.dumps(body).encode()
    path = tmp_path / "approval.json"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setenv("WSO_TEST_LOCAL_MEDIA_BROWSER", "1")
    runtime.verify_source_approval(path, digest, required_paths={"file.py"}, root=root)
    Path(private["WSO_TVT_WINDOWS_DECODER_PYTHON"]["path"]).write_bytes(b"drift")
    with pytest.raises(ValueError, match="source approval"):
        runtime.verify_source_approval(
            path, digest, required_paths={"file.py"}, root=root
        )
    monkeypatch.delenv("WSO_TEST_LOCAL_MEDIA_BROWSER")
    with pytest.raises(ValueError, match="source approval"):
        runtime.verify_source_approval(
            path, digest, required_paths={"file.py"}, root=root
        )


def test_media_approval_sources_pin_capacity_migration(runtime):
    assert (
        "infra/migrations/versions/0015_tvt_local_media_capacity.py"
        in runtime.MEDIA_SOURCES
    )


@pytest.mark.parametrize("phase", ["dispose", "readback"])
def test_runtime_cleanup_snapshot_cannot_skip_unconfirmed_successor(
    runtime, monkeypatch, tmp_path, phase
):
    import io
    from types import SimpleNamespace

    from wso_core import secrets
    from wso_core.tvt import local_admission
    from wso_tvt_bridge import server, windows_socket

    from tests.contract.test_local_owner_registry import RetiringPredecessor

    predecessor = RetiringPredecessor(1)

    def passive_wait():
        lock = getattr(windows_socket, "PENDING_OWNERS_LOCK", None)
        assert lock is None or not lock.locked()

    uncertain = SimpleNamespace(confirmed=False, passive_wait=passive_wait)
    monkeypatch.setattr(windows_socket, "PENDING_OWNERS", [predecessor, uncertain])
    shutdown, written = [], {}
    monkeypatch.setattr(secrets, "FileKeyProvider", lambda path: object())
    monkeypatch.setattr(
        local_admission,
        "LocalDeviceAdmission",
        lambda *args: SimpleNamespace(shutdown=lambda: shutdown.append(True)),
    )
    monkeypatch.setattr(runtime, "required_provider", lambda loader: object())
    monkeypatch.setattr(
        runtime,
        "borrowed_helpers",
        lambda: SimpleNamespace(
            write_private=lambda path, data: written.update({path.name: data})
        ),
    )
    monkeypatch.setattr(runtime, "media_enabled", lambda: False)
    monkeypatch.setattr(runtime.sys, "stdin", io.StringIO("\n"))
    monkeypatch.setenv("WSO_TEST_LOCAL_DEVICE_NATIVE", "real")
    monkeypatch.setenv("WSO_WORKER_DATABASE_URL", "inert")
    monkeypatch.setenv("WSO_CONNECTION_KEY_FILE", "inert")
    for filename in ("ca.pem", "server.pem", "server.key"):
        (tmp_path / filename).write_bytes(b"inert")

    class Server:
        def __init__(self, *args, dispose, **kwargs):
            self.dispose = dispose

        def start(self):
            return 12345

        def close(self, **kwargs):
            if phase == "dispose":
                self.dispose()
            return True

    monkeypatch.setattr(server, "AccountRpcServer", Server)
    monkeypatch.setattr(server, "ServerConfig", lambda **kwargs: object())
    try:
        if phase == "dispose":
            with pytest.raises(RuntimeError, match="native custody remains"):
                runtime.worker_process(tmp_path)
            assert not shutdown and "worker-close.json" not in written
        else:
            runtime.worker_process(tmp_path)
            assert written["worker-close.json"]["nativeOwnersConfirmed"] is False
        assert not uncertain.confirmed and predecessor.removed
    finally:
        predecessor.join()
