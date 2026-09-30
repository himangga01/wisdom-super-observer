"""Safe fixture guard regressions; real Linux recovery has a separate gate.

Container/database records and signal traps exercise refusal and observation
logic without any live PostgreSQL, Docker, Celery worker or process signal.
"""

import json
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url

from tests.support import job_broker_harness as harness_module
from tests.support import job_handlers, job_process

OWNER = "a" * 32
URL = make_url("postgresql+psycopg://postgres:synthetic@127.0.0.1:55432/wso_ci_test")


def container_record():
    return {
        "Name": f"/wso-ci-postgres-{OWNER}",
        "Config": {
            "Labels": {"wso.ci.owner": OWNER},
            "Image": "postgres@sha256:" + "b" * 64,
        },
        "State": {"Running": True},
        "NetworkSettings": {
            "Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55432"}]},
            "Networks": {"bridge": {"IPAddress": "172.17.0.2"}},
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": f"wso-ci-postgres-data-{OWNER}",
                "Destination": "/var/lib/postgresql/data",
                "RW": True,
            }
        ],
    }


class ReadOnlyEngine:
    url = URL

    def __init__(
        self, address="172.17.0.2", port=5432, directory="/var/lib/postgresql/data"
    ):
        self.state = {
            "db": "wso_ci_test",
            "actor": "postgres",
            "owner": "postgres",
            "version": "170011",
            "address": address,
            "port": port,
            "directory": directory,
        }

    @contextmanager
    def connect(self):
        yield SimpleNamespace(
            execute=lambda _sql: SimpleNamespace(
                mappings=lambda: SimpleNamespace(one=lambda: self.state)
            )
        )


def guard_environment(monkeypatch, record=None):
    monkeypatch.setattr(job_handlers.sys, "platform", "linux")
    for name, value in {
        "CI": "true",
        "WSO_CI_DISPOSABLE_POSTGRES": "1",
        "WSO_TEST_RECOVERY_DATABASE_NAME": "wso_ci_test",
        "WSO_TEST_RECOVERY_DATABASE_OWNER": "postgres",
        "WSO_CI_RUNTIME_OWNER": OWNER,
        "WSO_TEST_ADMIN_DATABASE_URL": URL.render_as_string(hide_password=False),
    }.items():
        monkeypatch.setenv(name, value)

    def inspect(arguments, **_kwargs):
        data = (
            {"Labels": {"wso.ci.owner": OWNER}, "Name": f"wso-ci-postgres-data-{OWNER}"}
            if "volume" in arguments
            else record or container_record()
        )
        return SimpleNamespace(stdout=json.dumps([data]))

    monkeypatch.setattr(job_handlers.subprocess, "run", inspect)


def test_owned_linux_bridge_listener_is_valid(monkeypatch):
    guard_environment(monkeypatch)
    job_handlers.verify_fixture_database(ReadOnlyEngine())


@pytest.mark.parametrize(
    "field,value",
    [
        ("address", "172.17.0.3"),
        ("port", 55432),
        ("directory", "/customer/data"),
    ],
)
def test_linux_rejects_listener_outside_owned_container(monkeypatch, field, value):
    guard_environment(monkeypatch)
    with pytest.raises(ValueError):
        job_handlers.verify_fixture_database(ReadOnlyEngine(**{field: value}))


def test_fixture_transport_budget_exceeds_hard_task_and_restoration_fits_deadline(
    monkeypatch,
):
    from kombu.transport.redis import Channel
    from wso_core import job_runtime

    # Worker entrypoint installs a subclass; restore it with the test fixture.
    monkeypatch.setattr(Channel, "QoS", Channel.QoS)
    original = job_runtime.create_app
    apps = []

    def capture(*args, **kwargs):
        app = original(*args, **kwargs)
        app.worker_main = lambda _args: None
        apps.append(app)
        return app

    monkeypatch.setattr(job_runtime, "create_app", capture)
    monkeypatch.setattr(job_process.sys, "argv", ["fixture", "worker"])
    for name, value in {
        "WSO_BROKER_URL": "redis://127.0.0.1:55433/0",
        "WSO_TEST_JOB_DATABASE_URL": "postgresql+psycopg://wso_job_worker:synthetic@127.0.0.1:55432/wso_ci_test",
        "WSO_RECOVERY_QUEUE": "wso.default",
    }.items():
        monkeypatch.setenv(name, value)
    job_process.main()
    app = apps[0]
    visibility = app.conf.broker_transport_options["visibility_timeout"]
    assert app.conf.task_time_limit < visibility
    assert visibility + 100 < getattr(harness_module, "TRANSPORT_DEADLINE_SECONDS", 45)
    assert app.conf.visibility_timeout == visibility
    assert (
        original(
            "redis://127.0.0.1:55433/0",
            "postgresql+psycopg://wso_job_worker:synthetic@127.0.0.1:55432/wso_ci_test",
        ).conf.broker_transport_options["visibility_timeout"]
        == 3600
    )


def test_pop_to_registration_gap_is_not_an_ack():
    harness = harness_module.JobBrokerHarness("unused")
    harness.broker = SimpleNamespace(llen=lambda _: 0, hlen=lambda _: 0)
    with pytest.raises(ValueError, match="explicit"):
        harness.wait_queue_empty()


def test_effect_and_inbox_are_read_after_ack_completion():
    harness = harness_module.JobBrokerHarness("unused")
    events = []
    harness.wait_state = lambda *_args: events.append("state")
    harness.effect_count = lambda _job: events.append("effect") or 1

    @contextmanager
    def db_connect():
        yield SimpleNamespace(
            execute=lambda *_args: SimpleNamespace(
                scalar_one=lambda: events.append("inbox") or "COMPLETED"
            )
        )

    harness.admin = SimpleNamespace(connect=db_connect)
    harness.wait_queue_empty = lambda *args, **kwargs: events.append("actual-acks")
    harness.assert_one_effect(uuid4(), require_consumed=True)
    assert events.index("actual-acks") < events.index("inbox")


@pytest.mark.parametrize("mismatch", ["start_time", "group", "owner"])
def test_child_injection_refuses_identity_mismatch_without_signal(
    monkeypatch, mismatch
):
    harness = harness_module.JobBrokerHarness("unused")
    worker = Mock(pid=6001)
    worker.poll.return_value = None
    harness.processes = {worker: 6001}
    expected = {"pid": 6002, "start_time": 99, "group": 6001, "owner": harness.owner}
    actual = dict(expected)
    actual[mismatch] = {"start_time": 100, "group": 6003, "owner": "foreign"}[mismatch]
    harness.enqueue = lambda **_kwargs: uuid4()
    harness.start_worker = lambda: worker
    harness.start_dispatcher = lambda: None
    harness.wait_barrier = lambda _name: expected
    harness.row = lambda _job: {"state": "RUNNING", "lease_generation": 1}
    harness.effect_count = lambda _job: 0
    monkeypatch.setattr(
        harness,
        "process_identity",
        lambda _pid: ("S", actual["group"], actual["start_time"]),
    )
    monkeypatch.setattr(
        harness_module.os, "getpgid", lambda _pid: actual["group"], raising=False
    )
    monkeypatch.setattr(
        harness_module.Path,
        "read_bytes",
        lambda _path: f"WSO_RECOVERY_OWNER={actual['owner']}".encode(),
    )

    def signal_would_escape(*_args, **_kwargs):
        raise AssertionError("a signal escaped the ownership guard")

    monkeypatch.setattr(harness_module.os, "kill", signal_would_escape)
    monkeypatch.setattr(harness_module.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(
        harness_module.os, "pidfd_open", lambda *_args: 123456, raising=False
    )
    monkeypatch.setattr(
        harness_module.signal, "pidfd_send_signal", signal_would_escape, raising=False
    )
    monkeypatch.setattr(harness_module.os, "close", lambda _fd: None)
    with pytest.raises(ValueError, match="ownership"):
        harness.crash_before_effect(child_only=True)


def test_child_pidfd_is_validated_then_signalled_and_closed(monkeypatch):
    harness = harness_module.JobBrokerHarness("unused")
    worker = Mock(pid=6001)
    harness.processes = {worker: 6001}
    identity = {"pid": 6002, "group": 6001, "start_time": 99, "owner": harness.owner}
    calls = []
    monkeypatch.setattr(harness, "process_identity", lambda _pid: ("S", 6001, 99))
    monkeypatch.setattr(
        harness_module.Path,
        "read_bytes",
        lambda _path: f"WSO_RECOVERY_OWNER={harness.owner}".encode(),
    )
    monkeypatch.setattr(
        harness_module.os,
        "pidfd_open",
        lambda pid, flags: calls.append(("open", pid)) or 123456,
        raising=False,
    )
    monkeypatch.setattr(harness_module.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(
        harness_module.signal,
        "pidfd_send_signal",
        lambda fd, *_args: calls.append(("stable-signal", fd)),
        raising=False,
    )
    monkeypatch.setattr(
        harness_module.os, "kill", lambda *_args: pytest.fail("numeric PID signal used")
    )
    monkeypatch.setattr(
        harness_module.os, "close", lambda fd: calls.append(("close", fd))
    )
    harness.kill_owned_process(identity)
    assert calls == [("open", 6002), ("stable-signal", 123456), ("close", 123456)]


def test_missing_pidfd_refuses_signal(monkeypatch):
    harness = harness_module.JobBrokerHarness("unused")
    monkeypatch.delattr(harness_module.os, "pidfd_open", raising=False)
    monkeypatch.setattr(
        harness_module.os, "kill", lambda *_args: pytest.fail("numeric PID signal used")
    )
    with pytest.raises(ValueError, match="unavailable"):
        harness.kill_owned_process({"pid": 6002})


def test_zero_broker_snapshot_does_not_hide_unacked_published_duplicate(monkeypatch):
    harness = harness_module.JobBrokerHarness("unused")
    harness.broker = SimpleNamespace(llen=lambda _: 0, hlen=lambda _: 0)
    events = [{"event": "acked", "task_id": "first"}]
    harness.transport_observations = lambda: events
    original_wait = harness_module.await_fact
    monkeypatch.setattr(
        harness_module,
        "await_fact",
        lambda predicate, description, _timeout: original_wait(
            predicate, description, 0.01
        ),
    )
    with pytest.raises(AssertionError, match="each explicitly published"):
        harness.wait_queue_empty(expected_task_ids={"first", "second"})
    events.append({"event": "acked", "task_id": "second"})
    harness.wait_queue_empty(expected_task_ids={"first", "second"})


def test_orphan_replay_cannot_precede_actual_visibility_age():
    harness = harness_module.JobBrokerHarness("unused")
    job = uuid4()
    harness.orphaned_reservations[job] = {
        "task_id": "original",
        "delivery_tag": "original-tag",
        "reserved_score": time.time(),
    }
    harness.transport_observations = lambda: [
        {
            "event": "reserved",
            "task_id": "original",
            "delivery_tag": "restored",
            "redelivered": True,
            "observed_at": time.time(),
        },
        {
            "event": "acked",
            "task_id": "original",
            "delivery_tag": "restored",
            "observed_at": time.time(),
        },
    ]
    with pytest.raises(AssertionError):
        harness.wait_replayed_ack(job)


def test_transport_ack_observer_requires_successful_real_delegate(monkeypatch):
    from kombu.transport.redis import Channel, QoS

    events = []
    monkeypatch.setattr(
        job_process, "transport_event", lambda event, record: events.append(event)
    )
    prior = Channel.QoS
    job_process.install_transport_observer()
    try:
        observer = object.__new__(Channel.QoS)
        observer._fixture_records = {"tag": {"task_id": "id"}}

        def failed_ack(_self, _tag):
            raise OSError("synthetic delegate failure")

        monkeypatch.setattr(QoS, "ack", failed_ack)
        with pytest.raises(OSError):
            observer.ack("tag")
        assert events == []
        monkeypatch.setattr(
            QoS, "ack", lambda _self, _tag: events.append("delegate-returned")
        )
        observer.ack("tag")
        assert events == ["delegate-returned", "acked"]
    finally:
        Channel.QoS = prior


@pytest.mark.parametrize(
    "mutation", ["image", "host-port", "label", "mount", "network"]
)
def test_owned_linux_container_mismatches_are_refused(monkeypatch, mutation):
    record = container_record()
    if mutation == "image":
        record["Config"]["Image"] = "postgres:latest"
    elif mutation == "host-port":
        record["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"] = "55434"
    elif mutation == "label":
        record["Config"]["Labels"]["wso.ci.owner"] = "foreign"
    elif mutation == "mount":
        record["Mounts"][0]["Name"] = "customer-volume"
    elif mutation == "network":
        record["NetworkSettings"]["Networks"] = {"foreign": {"IPAddress": "172.17.0.2"}}
    guard_environment(monkeypatch, record)
    with pytest.raises(ValueError):
        job_handlers.verify_fixture_database(ReadOnlyEngine())
