"""Owned Linux Celery/Valkey recovery laboratory with real PostgreSQL authority.

No eager task calls, shared broker resets, forged contexts, or selected skips.
The only administrator writes are fixture metadata and synthetic fixture rows.
"""

from __future__ import annotations

import base64
import importlib.metadata
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.support.job_process import TRANSPORT_DEADLINE_SECONDS

ROOT = Path(__file__).resolve().parents[2]
LABEL = "wso.recovery.owner"


def await_fact(predicate, description, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"deadline waiting for {description}")


class JobBrokerHarness:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.owner = uuid4().hex
        self.containers = []
        self.volumes = []
        self.processes = {}
        self.process_start_times = {}
        self.log_files = []
        self.engines = []
        self.settings = None
        self.admin = None
        self.server = None
        self.server_thread = None
        self.tenant = uuid4()
        self.actor = uuid4()
        self.operations = {}
        self.orphaned_reservations = {}
        self.env = os.environ.copy()
        self.env.update(
            {
                "WSO_RECOVERY_CONTROL": str(self.directory),
                "WSO_RECOVERY_TENANT": str(self.tenant),
                "WSO_RECOVERY_ACTOR": str(self.actor),
                "WSO_RECOVERY_OWNER": self.owner,
            }
        )

    def __enter__(self):
        if sys.platform != "linux":
            pytest.fail("jobs_recovery requires actual Linux Celery/Valkey; no skip")
        try:
            self.preflight()
            self.install_fixtures()
            self.start_upstream()
            self.new_broker()
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def docker(self, *args):
        try:
            result = subprocess.run(
                ["docker", *args],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("owned recovery Docker operation failed") from None

    def preflight(self):
        if (
            os.environ.get("CI") != "true"
            or os.environ.get("WSO_CI_DISPOSABLE_POSTGRES") != "1"
            or os.environ.get("WSO_TEST_RECOVERY_DATABASE_NAME") != "wso_ci_test"
            or os.environ.get("WSO_TEST_RECOVERY_DATABASE_OWNER") != "postgres"
        ):
            pytest.fail("requires the explicitly owned disposable Linux CI database")
        for package, version in {
            "celery": "5.6.3",
            "kombu": "5.6.2",
            "redis": "6.4.0",
        }.items():
            assert importlib.metadata.version(package) == version
        admin_url = make_url(os.environ["WSO_TEST_ADMIN_DATABASE_URL"])
        assert admin_url.database == "wso_ci_test"
        assert admin_url.username == "postgres" and admin_url.host == "127.0.0.1"
        assert admin_url.drivername == "postgresql+psycopg" and not admin_url.query
        owner = os.environ.get("WSO_CI_RUNTIME_OWNER", "")
        assert re.fullmatch(r"[0-9a-f]{32}", owner)
        inspected = json.loads(self.docker("inspect", f"wso-ci-postgres-{owner}"))[0]
        assert inspected["Config"]["Labels"]["wso.ci.owner"] == owner
        assert inspected["State"]["Running"]
        assert inspected["NetworkSettings"]["Ports"]["5432/tcp"] == [
            {"HostIp": "127.0.0.1", "HostPort": str(admin_url.port)}
        ]
        self.admin = create_engine(
            admin_url, hide_parameters=True, connect_args={"connect_timeout": 5}
        )
        self.engines.append(self.admin)
        with self.admin.connect() as db:
            state = (
                db.execute(
                    text(
                        "SELECT current_database() AS db,current_user AS actor,"
                        "pg_get_userbyid(datdba) AS owner,"
                        "current_setting('server_version_num') AS version "
                        "FROM pg_database WHERE datname=current_database()"
                    )
                )
                .mappings()
                .one()
            )
            assert dict(state) == {
                "db": "wso_ci_test",
                "actor": "postgres",
                "owner": "postgres",
                "version": "170011",
            }
        for name, role in {
            "APP": "wso_app",
            "IDENTITY": "wso_identity_bootstrap",
            "SESSION": "wso_web_session",
            "DISPATCH": "wso_dispatcher",
            "JOB": "wso_job_worker",
        }.items():
            url = make_url(os.environ[f"WSO_TEST_{name}_DATABASE_URL"])
            assert (url.host, url.port, url.database) == (
                admin_url.host,
                admin_url.port,
                admin_url.database,
            )
            assert url.username == role
            engine = create_engine(
                url, hide_parameters=True, connect_args={"connect_timeout": 5}
            )
            self.engines.append(engine)
            with engine.connect() as db:
                assert db.execute(text("SELECT current_user")).scalar_one() == role
        self.image = os.environ.get(
            "WSO_TEST_VALKEY_IMAGE",
            "valkey/valkey:9.1.2",
        )
        self.docker("pull", self.image)
        digests = json.loads(self.docker("image", "inspect", self.image))[0][
            "RepoDigests"
        ]
        if "@sha256:" in self.image:
            assert self.image in digests
        else:
            self.image = next(
                digest for digest in digests if "valkey@sha256:" in digest
            )

    def install_fixtures(self):
        from tests.support.job_handlers import install_fixture_schema

        install_fixture_schema(self.admin)
        with self.admin.begin() as db:
            self.settings = dict(
                db.execute(
                    text("SELECT * FROM wso_private.job_settings WHERE singleton")
                )
                .mappings()
                .one()
            )
            db.execute(
                text(
                    "UPDATE wso_private.job_settings SET lease_seconds=4,"
                    "dispatch_seconds=2,watchdog_seconds=2,step_seconds=2,retry_seconds=1 "
                    "WHERE singleton"
                )
            )
            db.execute(
                text("INSERT INTO tenants(id,name) VALUES(:id,'recovery-fixture')"),
                {"id": self.tenant},
            )
            db.execute(
                text(
                    "INSERT INTO users(id,oidc_issuer,oidc_subject) "
                    "VALUES(:id,'https://issuer.test',:subject)"
                ),
                {"id": self.actor, "subject": str(self.actor)},
            )
            db.execute(
                text(
                    "INSERT INTO memberships(tenant_id,user_id,role) VALUES(:t,:u,'OWNER')"
                ),
                {"t": self.tenant, "u": self.actor},
            )

    @contextmanager
    def fixture_environment(self):
        previous = {
            key: os.environ.get(key)
            for key in self.env
            if key.startswith("WSO_RECOVERY_")
        }
        os.environ.update({key: self.env[key] for key in previous})
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def enqueue(
        self, *, barrier=None, queue="wso.default", external=False, unreadable=False
    ):
        from tests.support.job_process import enqueue

        operation = uuid4()
        with self.fixture_environment():
            job = enqueue(
                operation,
                barrier_name=barrier,
                queue=queue,
                external=external,
                unreadable=unreadable,
            )
        self.operations[job] = operation
        return job

    def launch(self, mode, **extra):
        env = self.env | extra
        log = (self.directory / f"{mode}-{len(self.processes)}.log").open("wb")
        self.log_files.append(log)
        process = subprocess.Popen(
            [sys.executable, "-m", "tests.support.job_process", mode],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes[process] = process.pid
        self.process_start_times[process] = self.process_identity(process.pid)[2]
        return process

    def start_worker(self, *, queue="wso.default", barrier=None):
        return self.launch(
            "worker", WSO_RECOVERY_QUEUE=queue, WSO_RECOVERY_BARRIER=barrier or ""
        )

    def start_dispatcher(self, *, barrier=None):
        return self.launch("dispatch", WSO_RECOVERY_BARRIER=barrier or "")

    @staticmethod
    def process_identity(pid):
        # The command in stat can contain spaces; fields after its final ')' are stable.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[0], int(fields[2]), int(fields[19])

    def kill_group(self, process):
        group = self.processes[process]
        if process.poll() is None:
            assert os.getpgid(process.pid) == group == process.pid
            assert (
                self.process_identity(process.pid)[2]
                == self.process_start_times[process]
            )
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                state, process_group, _started = self.process_identity(int(entry.name))
                if process_group != group or state == "Z":
                    continue
                environment = (entry / "environ").read_bytes().split(b"\0")
            except FileNotFoundError:
                continue
            assert f"WSO_RECOVERY_OWNER={self.owner}".encode() in environment
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)
        await_fact(
            lambda: not Path(f"/proc/{process.pid}").exists(), "process exit", 10
        )

    def wait_barrier(self, name):
        path = self.directory / f"{name}.json"

        def observed():
            if not path.exists():
                return None
            identity = json.loads(path.read_text(encoding="utf-8"))
            self.verify_owned_process(identity)
            return identity

        return await_fact(observed, name)

    def verify_owned_process(self, expected):
        try:
            state, group, start_time = self.process_identity(expected["pid"])
            environment = (
                Path(f"/proc/{expected['pid']}/environ").read_bytes().split(b"\0")
            )
            owned = (
                state != "Z"
                and group == expected["group"]
                and group in self.processes.values()
                and start_time == expected["start_time"]
                and expected["owner"] == self.owner
                and f"WSO_RECOVERY_OWNER={self.owner}".encode() in environment
            )
        except (FileNotFoundError, ProcessLookupError, KeyError):
            raise ValueError("process ownership identity unavailable") from None
        if not owned:
            raise ValueError("process ownership identity mismatch")

    def kill_owned_process(self, expected):
        # A pidfd pins the observed process even if its numeric PID is reused.
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise ValueError("stable owned process signaling unavailable")
        try:
            descriptor = os.pidfd_open(expected["pid"], 0)
        except OSError:
            raise ValueError("process ownership handle unavailable") from None
        try:
            self.verify_owned_process(expected)
            signal.pidfd_send_signal(descriptor, signal.SIGKILL, None, 0)
        finally:
            os.close(descriptor)

    def release_barrier(self, name):
        (self.directory / f"{name}.release").touch()

    def assert_process_closed(self, pid):
        await_fact(
            lambda: not Path(f"/proc/{pid}").exists(), "fixture subprocess closed", 10
        )

    def row(self, job):
        with self.admin.connect() as db:
            return dict(
                db.execute(
                    text(
                        "SELECT id,state,attempts,lease_generation,failure_code,"
                        "lease_expires_at,submitted_at FROM jobs WHERE id=:j"
                    ),
                    {"j": job},
                )
                .mappings()
                .one()
            )

    def projection(self, job):
        with self.admin.connect() as db:
            return dict(
                db.execute(
                    text(
                        "SELECT outbox_id,job_id,tenant_id,kind,queue,dispatch_generation,"
                        "state,last_published_at FROM wso_private.dispatch_ready WHERE job_id=:j"
                    ),
                    {"j": job},
                )
                .mappings()
                .one()
            )

    def wait_state(self, job, state, timeout=45):
        def observed():
            row = self.row(job)
            assert row["state"] not in {"FAILED", "PARTIAL"}, (
                "unexpected durable failure"
            )
            return row if row["state"] == state else None

        return await_fact(observed, "durable job state " + state, timeout)

    def effect_count(self, job):
        with self.admin.connect() as db:
            return db.execute(
                text(
                    "SELECT coalesce(sum(effect_count),0) FROM job_recovery_effects WHERE job_id=:j"
                ),
                {"j": job},
            ).scalar_one()

    def assert_one_effect(
        self, job, *, timeout=45, require_consumed=False, expected_task_ids=None
    ):
        self.wait_state(job, "SUCCEEDED", timeout)
        if require_consumed:
            self.wait_queue_empty(expected_task_ids=expected_task_ids)
        assert self.effect_count(job) == 1
        with self.admin.connect() as db:
            assert (
                db.execute(
                    text("SELECT state FROM inbox_dedup WHERE job_id=:j"), {"j": job}
                ).scalar_one()
                == "COMPLETED"
            )

    def crashed_producer(self):
        operation = uuid4()
        producer = self.launch("producer", WSO_RECOVERY_OPERATION=str(operation))
        self.wait_barrier("producer-committed")
        self.kill_group(producer)
        with self.admin.connect() as db:
            job = db.execute(
                text("SELECT id FROM jobs WHERE tenant_id=:t AND idempotency_key=:key"),
                {"t": self.tenant, "key": str(operation)},
            ).scalar_one()
        self.operations[job] = operation
        assert self.projection(job)["state"] == "READY"
        assert self.queue_length() == 0
        return job

    def crash_before_effect(self, *, child_only):
        job = self.enqueue(barrier="before-effect")
        worker = self.start_worker()
        self.start_dispatcher()
        identity = self.wait_barrier("before-effect")
        pid = identity["pid"]
        assert pid != worker.pid
        assert self.row(job)["state"] == "RUNNING"
        assert self.row(job)["lease_generation"] == 1
        assert self.effect_count(job) == 0
        if child_only:
            if identity["group"] != self.processes[worker]:
                raise ValueError("child process ownership group mismatch")
            self.kill_owned_process(identity)
            await_fact(
                lambda: not Path(f"/proc/{pid}").exists(), "killed child exit", 10
            )
            assert worker.poll() is None
        else:
            self.kill_group(worker)
            self.start_worker()
        self.assert_one_effect(job)
        assert self.row(job)["lease_generation"] >= 2

    def dispatcher(self):
        from wso_core.dispatch import Dispatcher
        from wso_core.outbox import CeleryPublisher

        from tests.support.job_handlers import REGISTRY
        from tests.support.job_process import create_fixture_app

        app = create_fixture_app(
            self.env["WSO_BROKER_URL"],
            self.env["WSO_TEST_JOB_DATABASE_URL"],
        )
        dispatcher = Dispatcher(
            self.env["WSO_TEST_DISPATCH_DATABASE_URL"],
            CeleryPublisher(app),
            registry=REGISTRY,
        )
        self.engines.append(dispatcher.engine)
        return dispatcher

    def dispatch_once(self):
        assert self.dispatcher().run_once() >= 1

    def wait_published(self, jobs):
        await_fact(
            lambda: all(
                self.projection(job)["last_published_at"] is not None for job in jobs
            ),
            "database publish acknowledgments",
        )

    def publish_reference(self, job):
        from wso_contracts.jobs import DispatchReference
        from wso_core.outbox import CeleryPublisher

        from tests.support.job_process import create_fixture_app

        projection = self.projection(job)
        reference = DispatchReference(
            job_id=job,
            outbox_id=projection["outbox_id"],
            tenant_id=projection["tenant_id"],
            kind=projection["kind"],
            lease_generation=projection["dispatch_generation"],
        )
        app = create_fixture_app(
            self.env["WSO_BROKER_URL"],
            self.env["WSO_TEST_JOB_DATABASE_URL"],
        )
        from celery.signals import after_task_publish

        published = []

        def observe_publish(headers, **_kwargs):
            published.append(headers["id"])

        after_task_publish.connect(
            observe_publish, sender="wso.execute_job", weak=False
        )
        try:
            CeleryPublisher(app)(reference, projection["queue"])
        finally:
            after_task_publish.disconnect(observe_publish, sender="wso.execute_job")
        assert len(published) == 1
        return published[0]

    def check_resource(self, kind, name):
        data = json.loads(self.docker(kind, "inspect", name))[0]
        labels = data["Config"]["Labels"] if kind == "container" else data["Labels"]
        assert labels[LABEL] == self.owner
        assert name.startswith("wso-recovery-") and self.owner in name
        return data

    def new_broker(self):
        suffix = str(len(self.volumes))
        volume = f"wso-recovery-{self.owner}-data-{suffix}"
        container = f"wso-recovery-{self.owner}-broker-{suffix}"
        self.docker("volume", "create", "--label", f"{LABEL}={self.owner}", volume)
        self.volumes.append(volume)
        self.docker(
            "run",
            "--detach",
            "--name",
            container,
            "--label",
            f"{LABEL}={self.owner}",
            "--publish",
            "127.0.0.1::6379",
            "--volume",
            f"{volume}:/data",
            self.image,
            "valkey-server",
            "--appendonly",
            "yes",
            "--appendfsync",
            "always",
            "--save",
            "",
            "--bind",
            "0.0.0.0",
            "--protected-mode",
            "no",
        )
        self.containers.append(container)
        self.container, self.volume = container, volume
        self.connect_broker()

    def connect_broker(self):
        data = self.check_resource("container", self.container)
        ports = data["NetworkSettings"]["Ports"]["6379/tcp"]
        assert len(ports) == 1 and ports[0]["HostIp"] == "127.0.0.1"
        self.env["WSO_BROKER_URL"] = f"redis://127.0.0.1:{ports[0]['HostPort']}/0"
        self.broker = redis.Redis.from_url(self.env["WSO_BROKER_URL"], socket_timeout=2)

        def ready():
            try:
                return self.broker.ping()
            except redis.RedisError:
                return False

        await_fact(ready, "owned Valkey readiness", 30)
        info = self.broker.info("server")
        assert info.get("valkey_version", info.get("redis_version")) == "9.1.2"
        print(
            "Recovery runtime: PostgreSQL 17.11, Celery 5.6.3, Kombu 5.6.2, Redis 6.4.0, Valkey 9.1.2"
        )

    def queue_length(self):
        return self.broker.llen("wso.default")

    def queued_task_ids(self, job):
        identifiers = set()
        for raw in self.broker.lrange("wso.default", 0, -1):
            message = json.loads(raw)
            body = json.loads(base64.b64decode(message["body"]))
            if body[1]["reference"]["job_id"] == str(job):
                identifiers.add(message["headers"]["id"])
        return identifiers

    def transport_observations(self):
        observations = []
        for path in self.directory.glob("transport-*.jsonl"):
            data = path.read_text(encoding="utf-8")
            # An in-progress final write has not established an observation yet.
            for line in data.splitlines(keepends=True):
                if not line.endswith("\n"):
                    continue
                event = json.loads(line)
                assert event["owner"] == self.owner
                assert event["pid"] in self.processes.values()
                assert event["event"] in {"reserved", "acked"}
                observations.append(event)
        return observations

    def capture_orphan_reservation(self, job):
        def observed():
            for event in reversed(self.transport_observations()):
                if (
                    event["event"] != "reserved"
                    or event["job_id"] != str(job)
                    or not self.broker.hexists("unacked", event["delivery_tag"])
                ):
                    continue
                score = self.broker.zscore("unacked_index", event["delivery_tag"])
                if score is not None:
                    return dict(event, reserved_score=score)
            return None

        reservation = await_fact(observed, "real broker reservation before worker loss")
        self.orphaned_reservations[job] = reservation
        return reservation

    def assert_orphan_present(self, job):
        reservation = self.orphaned_reservations[job]
        assert self.broker.hexists("unacked", reservation["delivery_tag"])
        assert (
            self.broker.zscore("unacked_index", reservation["delivery_tag"])
            == reservation["reserved_score"]
        )

    def wait_replayed_ack(self, job):
        from tests.support.job_process import FIXTURE_VISIBILITY_SECONDS

        original = self.orphaned_reservations[job]

        def replayed_and_acked():
            events = self.transport_observations()
            for delivery in events:
                if (
                    delivery["event"] != "reserved"
                    or not delivery["redelivered"]
                    or delivery["task_id"] != original["task_id"]
                ):
                    continue
                # This age comes from the genuine Redis transport score, unchanged.
                assert (
                    delivery["observed_at"]
                    >= original["reserved_score"] + FIXTURE_VISIBILITY_SECONDS
                )
                if any(
                    ack["event"] == "acked"
                    and ack["task_id"] == delivery["task_id"]
                    and ack["delivery_tag"] == delivery["delivery_tag"]
                    and ack["observed_at"] >= delivery["observed_at"]
                    for ack in events
                ):
                    return delivery
            return None

        delivery = await_fact(
            replayed_and_acked,
            "original reservation restored, replayed and ACKed",
            TRANSPORT_DEADLINE_SECONDS,
        )
        assert not self.broker.hexists("unacked", original["delivery_tag"])
        assert not self.broker.hexists("unacked", delivery["delivery_tag"])
        return original["task_id"]

    def wait_queue_empty(self, *, expected_task_ids=None):
        if not expected_task_ids:
            raise ValueError(
                "explicit published delivery identities are required for ACK evidence"
            )
        required = set(expected_task_ids)

        def acked():
            return required <= {
                event["task_id"]
                for event in self.transport_observations()
                if event["event"] == "acked"
            }

        await_fact(
            acked,
            "each explicitly published delivery ACKed",
            TRANSPORT_DEADLINE_SECONDS,
        )
        await_fact(
            lambda: self.queue_length() == 0 and self.broker.hlen("unacked") == 0,
            "broker deliveries acknowledged",
            TRANSPORT_DEADLINE_SECONDS,
        )

    def wait_aof_synced(self):
        def synced():
            info = self.broker.info("persistence")
            return (
                info["aof_enabled"] == 1
                and info["aof_last_write_status"] == "ok"
                and info.get("aof_pending_bio_fsync", 0) == 0
                and info.get("aof_buffer_length", 0) == 0
            )

        await_fact(synced, "AOF durable write")

    def stop_broker(self):
        self.check_resource("container", self.container)
        self.docker("kill", "--signal=KILL", self.container)
        assert not self.check_resource("container", self.container)["State"]["Running"]

    def restart_broker_same_volume(self):
        original_volume = self.volume
        self.stop_broker()
        self.check_resource("volume", original_volume)
        self.docker("start", self.container)
        self.connect_broker()
        mounts = self.check_resource("container", self.container)["Mounts"]
        assert any(mount.get("Name") == original_volume for mount in mounts)
        print("Owned Valkey process killed and restarted with original AOF volume")

    def replace_broker_empty_preserving_original(self):
        original_container, original_volume = self.container, self.volume
        self.stop_broker()
        self.new_broker()
        assert self.volume != original_volume
        self.check_resource("volume", original_volume)
        assert not self.check_resource("container", original_container)["State"][
            "Running"
        ]
        print("Owned empty broker created; original AOF volume preserved")

    def start_upstream(self):
        self.upstream_path = self.directory / "upstream.sqlite3"
        with sqlite3.connect(self.upstream_path) as db:
            db.execute(
                "CREATE TABLE effects(operation TEXT PRIMARY KEY,submissions INTEGER,reads INTEGER,unreadable INTEGER)"
            )
        harness = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def operation(self):
                return str(UUID(self.path.removeprefix("/")))

            def do_POST(self):
                operation = self.operation()
                with sqlite3.connect(harness.upstream_path) as db:
                    existing = db.execute(
                        "SELECT submissions FROM effects WHERE operation=?",
                        (operation,),
                    ).fetchone()
                    if existing:
                        db.execute(
                            "UPDATE effects SET submissions=submissions+1 WHERE operation=?",
                            (operation,),
                        )
                    else:
                        db.execute(
                            "INSERT INTO effects VALUES(?,1,0,?)",
                            (operation, int(harness.unreadable)),
                        )
                # Separate durable database has committed before this barrier.
                (harness.directory / "upstream-accepted.json").write_text(
                    json.dumps({"operation": operation}),
                    encoding="utf-8",
                )
                await_fact(
                    lambda: (harness.directory / "upstream-accepted.release").exists(),
                    "test upstream response release",
                    40,
                )
                self.respond(200, {"effect_count": 1})

            def do_GET(self):
                operation = self.operation()
                with sqlite3.connect(harness.upstream_path) as db:
                    db.execute(
                        "UPDATE effects SET reads=reads+1 WHERE operation=?",
                        (operation,),
                    )
                    row = db.execute(
                        "SELECT unreadable FROM effects WHERE operation=?", (operation,)
                    ).fetchone()
                self.respond(503 if row is None or row[0] else 200, {"effect_count": 1})

            def respond(self, status, body):
                data = json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.unreadable = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        self.env["WSO_RECOVERY_UPSTREAM"] = (
            f"http://127.0.0.1:{self.server.server_port}"
        )

    def crash_external_write(self, *, unreadable):
        self.unreadable = unreadable
        job = self.enqueue(external=True, unreadable=unreadable)
        worker = self.start_worker()
        dispatcher = self.start_dispatcher()
        await_fact(
            lambda: (self.directory / "upstream-accepted.json").exists(),
            "independently durable upstream acceptance",
        )
        assert self.row(job)["submitted_at"] is not None
        assert self.row(job)["state"] == "RUNNING"
        assert self.upstream_count(job) == 1
        self.capture_orphan_reservation(job)
        self.kill_group(worker)
        self.assert_orphan_present(job)
        self.kill_group(dispatcher)
        (self.directory / "upstream-accepted.release").touch()
        return job

    def upstream_stat(self, job, column):
        assert column in {"submissions", "reads"}
        with sqlite3.connect(self.upstream_path) as db:
            return db.execute(
                f"SELECT {column} FROM effects WHERE operation=?",
                (str(self.operations[job]),),
            ).fetchone()[0]

    def upstream_count(self, job):
        with sqlite3.connect(self.upstream_path) as db:
            return db.execute(
                "SELECT count(*) FROM effects WHERE operation=?",
                (str(self.operations[job]),),
            ).fetchone()[0]

    def upstream_submissions(self, job):
        return self.upstream_stat(job, "submissions")

    def upstream_reads(self, job):
        return self.upstream_stat(job, "reads")

    def assert_http_status(self, job, expected):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from fastapi.testclient import TestClient
        from wso_api.main import create_app

        from tests.auth_support import login
        from tests.support.job_process import auth_service

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        service, engines = auth_service(key)
        self.engines.extend(engines.values())
        app = create_app()
        app.state.auth_service = service
        with TestClient(app, base_url="https://app.test") as client:
            login(client, key, {"owner": self.actor}, subject="owner")
            response = client.get(
                f"/api/v1/jobs/{job}", params={"tenant_id": str(self.tenant)}
            )
            assert response.status_code == 200
            assert response.json()["state"] == expected
            assert response.headers["cache-control"] == "no-store"
            assert self.effect_count(job) == 1

    def cancel(self, job):
        from datetime import UTC, datetime, timedelta

        from wso_api.auth import WebSession
        from wso_api.stores.router import require_tenant
        from wso_core.jobs import JobService

        from tests.support.job_process import auth_service

        errors = []

        def cancel_job():
            service, engines = auth_service()
            try:
                principal = WebSession(
                    "https://issuer.test",
                    str(self.actor),
                    self.actor,
                    "",
                    datetime.now(UTC) + timedelta(minutes=5),
                )
                with require_tenant(
                    "jobs:cancel", self.tenant, service=service, principal=principal
                ) as scope:
                    JobService(scope.session).cancel(job)
            except Exception as error:  # noqa: BLE001 -- retain sanitized thread failures
                errors.append(error)
            finally:
                for engine in engines.values():
                    engine.dispose()

        thread = threading.Thread(target=cancel_job, daemon=True)
        thread.start()

        # The parked step holds its authorized lock. Observe actual lock waiting,
        # and real step expiry, then close the fixture process before cancellation.
        def cancellation_waiting():
            with self.admin.connect() as db:
                return db.execute(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE "
                        "usename='wso_app' AND wait_event_type='Lock')"
                    )
                ).scalar_one()

        await_fact(
            cancellation_waiting, "authorized cancellation waiting for step lock", 10
        )
        with self.admin.connect() as db:
            expires = db.execute(
                text("SELECT lease_expires_at FROM jobs WHERE id=:j"), {"j": job}
            ).scalar_one()

        def elapsed():
            with self.admin.connect() as db:
                return db.execute(
                    text("SELECT clock_timestamp()>=:expires"),
                    {"expires": expires},
                ).scalar_one()

        await_fact(elapsed, "real protected lease deadline", 10)
        self.release_barrier("media-parked")
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert not errors, "authorized cancellation failed"

    def __exit__(self, *_exc):
        failures = []
        for process in self.processes:
            try:
                self.kill_group(process)
            except Exception:  # noqa: BLE001 -- continue guarded resource cleanup
                failures.append("process cleanup")
        if self.server:
            (self.directory / "upstream-accepted.release").touch()
            self.server.shutdown()
            self.server.server_close()
        for container in reversed(self.containers):
            try:
                self.check_resource("container", container)
                self.docker("container", "rm", "--force", container)
            except Exception:  # noqa: BLE001 -- continue guarded resource cleanup
                failures.append("container cleanup")
        for volume in reversed(self.volumes):
            try:
                self.check_resource("volume", volume)
                self.docker("volume", "rm", volume)
            except Exception:  # noqa: BLE001 -- continue guarded resource cleanup
                failures.append("volume cleanup")
        if self.admin is not None and self.settings is not None:
            try:
                with self.admin.begin() as db:
                    db.execute(
                        text("DELETE FROM jobs WHERE tenant_id=:t"), {"t": self.tenant}
                    )
                    db.execute(
                        text("DELETE FROM memberships WHERE tenant_id=:t"),
                        {"t": self.tenant},
                    )
                    db.execute(
                        text("DELETE FROM web_sessions WHERE user_id=:u"),
                        {"u": self.actor},
                    )
                    db.execute(text("DELETE FROM users WHERE id=:u"), {"u": self.actor})
                    db.execute(
                        text("DELETE FROM tenants WHERE id=:t"), {"t": self.tenant}
                    )
                    db.execute(
                        text(
                            "UPDATE wso_private.job_settings SET lease_seconds=:lease_seconds,"
                            "dispatch_seconds=:dispatch_seconds,watchdog_seconds=:watchdog_seconds,"
                            "step_seconds=:step_seconds,retry_seconds=:retry_seconds WHERE singleton"
                        ),
                        self.settings,
                    )
            except Exception:  # noqa: BLE001 -- continue guarded resource cleanup
                failures.append("synthetic fixture cleanup")
        for engine in self.engines:
            engine.dispose()
        for log in self.log_files:
            log.close()
        if failures:
            raise AssertionError(
                "recovery cleanup refused or failed: " + ", ".join(failures)
            )
