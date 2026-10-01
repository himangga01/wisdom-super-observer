"""Real Celery/Kombu configuration, stopped before network or database effects."""

import importlib
import socket
import sys
from urllib.parse import urlsplit

import celery
import pytest
from sqlalchemy.engine import Engine
from wso_core import dispatch, job_runtime, worker

BROKER = "redis://127.0.0.1:55433/0"
JOB_URL = "postgresql+psycopg://wso_job_worker@127.0.0.1/unused"
DISPATCH_URL = "postgresql+psycopg://wso_dispatcher@127.0.0.1/unused"
OVERRIDES = (
    "CELERY_BROKER_URL",
    "CELERY_BROKER_READ_URL",
    "CELERY_BROKER_WRITE_URL",
    "CELERY_RESULT_BACKEND",
)


@pytest.fixture
def runtime_probe(monkeypatch):
    for key in (*OVERRIDES, "WSO_JOB_DATABASE_URL", "WSO_DISPATCH_DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("runtime configuration attempted a network/database effect")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(worker, "JobWorker", forbidden)
    apps, starts = [], []
    real_celery = celery.Celery

    def capture_app(*args, **kwargs):
        app = real_celery(*args, **kwargs)
        apps.append(app)
        return app

    class StopDispatch(Exception):
        pass

    class CaptureDispatcher:
        def __init__(self, database_url, publisher, *, registry):
            expected = {
                "IMPORT": ("TENANT", "READ"),
                "REGISTRATION": ("STORE", "EXTERNAL_WRITE"),
                "TVT_ACCOUNT_OPERATION": ("TENANT", "EXTERNAL_WRITE"),
                "TVT_DEVICE_OPERATION": ("STORE", "EXTERNAL_WRITE"),
                "TYCO_OPERATION": ("TENANT", "EXTERNAL_WRITE"),
            }
            assert {
                name: (registry.get(name).scope_kind, registry.get(name).effect_mode)
                for name in expected
            } == expected
            starts.append(("dispatch", database_url, publisher.app))

        def run_once(self):
            raise StopDispatch

    def capture_worker(app, argv):
        starts.append(("worker", argv, app))

    monkeypatch.setattr(celery, "Celery", capture_app)
    monkeypatch.setattr(real_celery, "worker_main", capture_worker)
    monkeypatch.setattr(dispatch, "Dispatcher", CaptureDispatcher)

    def invoke(mode, broker):
        if mode == "factory":
            return job_runtime.create_app(broker, JOB_URL)
        monkeypatch.setenv("WSO_BROKER_URL", broker)
        if mode == "worker":
            monkeypatch.setenv("WSO_JOB_DATABASE_URL", JOB_URL)
        else:
            # Dispatch must never require or construct a job worker.
            monkeypatch.delenv("WSO_JOB_DATABASE_URL", raising=False)
            monkeypatch.setenv("WSO_DISPATCH_DATABASE_URL", DISPATCH_URL)
        monkeypatch.setattr(sys, "argv", ["job_runtime", mode, "--queue", "wso.media"])
        try:
            job_runtime.main()
        except StopDispatch:
            pass
        return apps[-1]

    yield invoke, apps, starts
    for app in apps:
        app.close()


@pytest.mark.parametrize("mode", ["factory", "worker", "dispatch"])
@pytest.mark.parametrize(
    "broker",
    [
        "",
        " ",
        "redis://",
        "rediss:///0",
        "redis://user:credential-canary@/0",
        "amqp://127.0.0.1:5672/",
        "redis://127.0.0.1:invalid/0",
        "redis://127.0.0.1:0/0",
        "redis://127.0.0.1:65536/0",
        "redis://127.0.0.1:/0",
        "redis://bad host/0",
        "redis://127.0.0.1\n/0",
        "redis://[invalid]/0",
    ],
)
def test_invalid_broker_stops_before_app_or_runtime_construction(
    runtime_probe, mode, broker
):
    invoke, apps, starts = runtime_probe
    with pytest.raises(ValueError) as rejected:
        invoke(mode, broker)
    assert "credential-canary" not in str(rejected.value)
    assert "redis://" not in str(rejected.value)
    assert apps == [] and starts == []


@pytest.mark.parametrize("mode", ["factory", "worker", "dispatch"])
@pytest.mark.parametrize("override", OVERRIDES)
def test_conflicting_ambient_celery_configuration_is_rejected(
    runtime_probe, monkeypatch, mode, override
):
    monkeypatch.setenv(override, "redis://user:ambient-canary@192.0.2.10:56379/1")
    invoke, apps, starts = runtime_probe
    with pytest.raises(ValueError) as rejected:
        invoke(mode, BROKER)
    assert "ambient-canary" not in str(rejected.value)
    assert "192.0.2.10" not in str(rejected.value)
    assert apps == [] and starts == []


@pytest.mark.parametrize("mode", ["factory", "worker", "dispatch"])
@pytest.mark.parametrize(
    "broker",
    [
        BROKER,
        "rediss://localhost:56379/2",
        "redis://[::1]:56379/1",
        "redis://localhost/0",
    ],
)
@pytest.mark.parametrize("ambient", ["absent", "same", "empty"])
def test_effective_read_write_endpoints_and_no_result_contract(
    runtime_probe, monkeypatch, mode, broker, ambient
):
    if ambient != "absent":
        for key in OVERRIDES[:3]:
            monkeypatch.setenv(key, broker if ambient == "same" else "")
        monkeypatch.setenv("CELERY_RESULT_BACKEND", "")
    invoke, apps, starts = runtime_probe
    app = invoke(mode, broker)
    assert apps == [app]
    parsed = urlsplit(broker)
    assert app.conf.broker_read_url == app.conf.broker_write_url == broker
    for connection in (app.connection_for_read(), app.connection_for_write()):
        assert connection.transport_cls == parsed.scheme
        assert connection.hostname == parsed.hostname
        assert connection.info()["port"] == (parsed.port or 6379)
        assert connection.virtual_host == parsed.path.lstrip("/")
    assert app.conf.result_backend is None
    assert app.conf.task_ignore_result is True
    assert app.conf.task_serializer == app.conf.result_serializer == "json"
    assert app.conf.accept_content == ["json"]
    assert app.conf.task_acks_late and app.conf.task_reject_on_worker_lost
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_soft_time_limit == 25 and app.conf.task_time_limit == 30
    assert app.conf.broker_transport_options["visibility_timeout"] == 3600
    # Explicit fixture overrides remain possible without changing production defaults.
    app.conf.broker_transport_options = {"visibility_timeout": 40}
    assert app.connection_for_read().transport_options["visibility_timeout"] == 40
    if mode == "dispatch":
        assert starts == [("dispatch", DISPATCH_URL, app)]
    elif mode == "worker":
        assert starts == [
            ("worker", ["worker", "--loglevel=WARNING", "--queues", "wso.media"], app)
        ]
    else:
        assert starts == []


def test_import_does_not_require_environment_or_create_runtime(
    runtime_probe, monkeypatch
):
    monkeypatch.delenv("WSO_BROKER_URL", raising=False)
    importlib.reload(job_runtime)
    assert runtime_probe[1:] == ([], [])
