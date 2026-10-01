"""Separate owned Valkey and actual Celery transport observations for assets."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import redis
from sqlalchemy import create_engine, text

from tests.support.asset_faults import (
    ProcessIdentity,
    process_identity,
    require,
    validate_process_identity,
)
from tests.support.asset_faults import snapshot_json as private_json
from tests.support.asset_process import ProcessMode
from tests.support.asset_rustfs import OwnedCommands

LABEL = "wso.asset.broker.owner"


@dataclass(frozen=True, slots=True, repr=False)
class BrokerIdentity:
    container_id: str
    image_id: str
    repo_digest: str
    volume_name: str
    endpoint_url: str
    version: str


def install_transport_observer(control):
    """Delegate real QoS append/ACK first, journal only completed operations."""
    from kombu.transport.redis import Channel, QoS

    def event(name, record):
        row = dict(
            record, event=name, owner=control.owner, pid=os.getpid(), at=time.time()
        )
        target = control.directory / "transport.jsonl"
        descriptor = os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            require(os.fstat(descriptor).st_size < 1048576)
            data = (json.dumps(row) + "\n").encode()
            require(os.write(descriptor, data) == len(data))
        finally:
            os.close(descriptor)

    class ObservedQoS(QoS):
        def append(self, message, delivery_tag):
            record = None
            if message.headers.get("task") == "wso.execute_job":
                reference = message.payload[1]["reference"]
                record = {
                    "job_id": str(UUID(reference["job_id"])),
                    "task_id": message.headers["id"],
                    "delivery_tag": str(delivery_tag),
                    "redelivered": bool(
                        message.headers.get("redelivered")
                        or message.delivery_info.get("redelivered")
                    ),
                }
            super().append(message, delivery_tag)
            if record is not None:
                if not hasattr(self, "_owned_asset_records"):
                    self._owned_asset_records = {}
                self._owned_asset_records[delivery_tag] = record
                event("reserved", record)

        def ack(self, delivery_tag):
            record = getattr(self, "_owned_asset_records", {}).get(delivery_tag)
            super().ack(delivery_tag)
            if record is not None:
                event("acked", record)
                self._owned_asset_records.pop(delivery_tag)

    Channel.QoS = ObservedQoS


class AssetBroker:
    def __init__(self, directory, owner, docker_target, cutoff, cleanup_limit):
        self.directory, self.owner, self.target, self.cutoff = (
            Path(directory),
            owner,
            docker_target,
            cutoff,
        )
        self.commands = OwnedCommands()
        self.container = "wso-asset-broker-" + owner
        self.volume = "wso-asset-broker-data-" + owner
        self.created, self.client, self.identity = [], None, None
        self.consumer_pids = set()
        self.cleanup_limit = cleanup_limit
        self.teardown_cutoff = None
        self.closing = False

    def docker(self, *arguments):
        cutoff = self.teardown_cutoff if self.closing else self.cutoff
        if self.closing:
            require(
                arguments[:2]
                in {
                    ("container", "inspect"),
                    ("volume", "inspect"),
                    ("container", "rm"),
                    ("volume", "rm"),
                }
            )
        allowance = min(120, cutoff - time.monotonic())
        require(allowance > 0)
        command, environment = self.target.command(*arguments)
        result = self.commands.run(command, environment, allowance)
        require(time.monotonic() < cutoff)
        return result

    def inspect(self, kind, name):
        result = json.loads(self.docker(kind, "inspect", name))
        require(type(result) is list and len(result) == 1)
        row = result[0]
        labels = row["Config"]["Labels"] if kind == "container" else row["Labels"]
        require(
            labels.get(LABEL) == self.owner and name in {self.container, self.volume}
        )
        return row

    def start(self):
        image = "valkey/valkey:9.1.2"
        self.docker("pull", image)
        metadata = json.loads(self.docker("image", "inspect", image))[0]
        digests = [
            d for d in metadata["RepoDigests"] if d.startswith("valkey/valkey@sha256:")
        ]
        require(len(digests) == 1 and len(digests[0].rsplit(":", 1)[1]) == 64)
        self.docker("volume", "create", "--label", f"{LABEL}={self.owner}", self.volume)
        self.created.append(("volume", self.volume))
        cid = self.docker(
            "run",
            "--detach",
            "--name",
            self.container,
            "--label",
            f"{LABEL}={self.owner}",
            "--publish",
            "127.0.0.1::6379",
            "--volume",
            f"{self.volume}:/data",
            digests[0],
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
        self.created.append(("container", self.container))
        row = self.inspect("container", self.container)
        ports = row["NetworkSettings"]["Ports"]["6379/tcp"]
        require(
            row["Id"] == cid
            and row["Image"] == metadata["Id"]
            and row["State"]["Running"]
        )
        require(
            len(ports) == 1
            and ports[0]["HostIp"] == "127.0.0.1"
            and ports[0]["HostPort"].isascii()
            and ports[0]["HostPort"].isdigit()
        )
        mounts = row["Mounts"]
        require(
            len(mounts) == 1
            and mounts[0]["Type"] == "volume"
            and mounts[0]["Name"] == self.volume
            and mounts[0]["Destination"] == "/data"
        )
        endpoint = "redis://127.0.0.1:" + ports[0]["HostPort"] + "/0"
        self.client = redis.Redis.from_url(
            endpoint, socket_connect_timeout=2, socket_timeout=2
        )
        cutoff = min(self.cutoff, time.monotonic() + 30)
        while time.monotonic() < cutoff:
            try:
                if self.client.ping():
                    break
            except redis.ConnectionError:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("owned asset broker readiness failed")
        version = self.client.info("server").get("valkey_version") or self.client.info(
            "server"
        ).get("redis_version")
        require(version == "9.1.2")
        self.identity = BrokerIdentity(
            cid, metadata["Id"], digests[0], self.volume, endpoint, version
        )
        return self.identity

    def transport_facts(self, job_id):
        facts = []
        for path in self.directory.glob("control-*/transport.jsonl"):
            for line in path.read_bytes().splitlines(keepends=True):
                if not line.endswith(b"\n"):
                    continue
                row = json.loads(line)
                require(
                    row["owner"] == self.owner and row["event"] in {"reserved", "acked"}
                )
                require(type(row["pid"]) is int and row["pid"] in self.consumer_pids)
                if row["job_id"] == str(job_id):
                    facts.append(row)
        return facts

    def assert_settled(self):
        self.commands.assert_settled()
        require(
            self.client.llen("wso.default") == 0
            and self.client.hlen("unacked") == 0
            and self.client.zcard("unacked_index") == 0
        )

    def close(self, cutoff=None):
        self.closing = True
        if self.teardown_cutoff is None:
            self.teardown_cutoff = min(
                self.cleanup_limit,
                time.monotonic() + 8 * 60,
                cutoff if cutoff is not None else float("inf"),
            )
        elif cutoff is not None:
            self.teardown_cutoff = min(self.teardown_cutoff, cutoff)
        self.commands.assert_settled()
        first = None
        if self.client is not None:
            try:
                self.client.close()
            except Exception as error:  # noqa: BLE001 -- keep every owned resource tracked
                first = error
        for kind, name in reversed(self.created):
            try:
                row = self.inspect(kind, name)
                if kind == "container":
                    require(
                        self.identity is not None
                        and row["Id"] == self.identity.container_id
                        and row["Image"] == self.identity.image_id
                    )
                    self.docker("container", "rm", "--force", name)
                else:
                    self.docker("volume", "rm", name)
            except Exception as error:  # noqa: BLE001 -- continue without clearing uncertainty
                first = first or error
            else:
                self.created.remove((kind, name))
        if first is not None or self.created:
            raise RuntimeError("owned asset broker cleanup refused") from None

    def __enter__(self):
        try:
            self.start()
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_exc):
        self.close()


DIAGNOSTIC_STAGES = frozenset(
    {
        "BODY",
        "PARENT_STOP",
        "OBSERVER_PUBLICATION",
        "OBSERVER_PIDFD",
        "OBSERVER_IDENTITY",
        "OBSERVER_JOIN",
        "CHILD_CUTOFF",
        "CHILD_PIDFD",
        "CHILD_PROC",
        "CHILD_WAIT",
        "CRASH_SETUP",
        "CRASH_CHECKPOINT",
        "CRASH_HELPERS",
        "CRASH_IDENTITY",
        "CRASH_SIGNAL",
        "CRASH_READINESS",
        "RECOVERY",
        "BROKER_CLOSE",
    }
)
PROC_STATES = frozenset(
    {
        "R",
        "S",
        "D",
        "Z",
        "T",
        "t",
        "X",
        "x",
        "K",
        "W",
        "P",
        "I",
        "ABSENT",
        "UNKNOWN",
        "IDENTITY_CHANGED",
        "NOT_OBSERVED",
    }
)


def observed_proc_state(identity):
    """Read a bounded stat snapshot; observation never grants signal/reap authority."""
    try:
        with Path(f"/proc/{identity.pid}/stat").open("rb") as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            return "UNKNOWN"
        fields = data[data.rindex(b")") + 2 :].split()
        if int(fields[19]) != identity.start_ticks:
            return "IDENTITY_CHANGED"
        state = fields[0].decode("ascii")
        return state if state in PROC_STATES else "UNKNOWN"
    except FileNotFoundError:
        return "ABSENT"
    except Exception:  # noqa: BLE001 -- observation cannot replace initiating cause.
        return "UNKNOWN"


def exception_category(error):
    from tests.support.asset_faults import FixtureContractError
    from tests.support.asset_harness import FixtureDeadlineError

    for kind, category in (
        (FixtureDeadlineError, "DEADLINE"),
        (FixtureContractError, "CONTRACT"),
        (TimeoutError, "TIMEOUT"),
        (OSError, "OS"),
        (ValueError, "VALUE"),
        (AssertionError, "ASSERTION"),
        (RuntimeError, "RUNTIME"),
    ):
        if isinstance(error, kind):
            return category
    return "OTHER"


@dataclass(frozen=True, slots=True, repr=False)
class PreforkDiagnostic:
    cause: BaseException
    identity: object
    facts: tuple

    def public(self):
        return dict(self.facts)


class PreforkSettlementError(RuntimeError):
    def __init__(self, diagnostic):
        super().__init__("owned prefork settlement refused")
        self.diagnostic = diagnostic


class AssetJobs:
    def __init__(self, harness):
        self.h = harness
        self.broker = AssetBroker(
            harness.directory,
            harness.owner,
            harness.provider.docker_target,
            harness.deadlines.cutoffs[harness.phase],
            harness.deadlines.start + 94 * 60,
        )
        self.processes, self.children = [], {}
        self.references, self.last_lease = {}, None
        self.child_stop = threading.Event()
        self.child_lock = threading.Lock()
        self.child_thread, self.child_failure = None, None
        self.seen_children = set()
        self.diagnostic = None
        self.cleanup_diagnostics = []
        self.diagnostic_lock = threading.Lock()
        self.diagnostic_stage = "CRASH_SETUP"
        self.diagnostic_cutoff = harness.deadlines.cutoffs[harness.phase]

    def record_diagnostic(
        self, stage, error, cutoff, *, identity=None, descriptor=None
    ):
        require(stage in DIAGNOSTIC_STAGES)
        ready, proc = None, "NOT_OBSERVED"
        if descriptor is not None:
            try:
                ready = select_pidfd(descriptor)
            except Exception:  # noqa: BLE001 -- bounded diagnostic only.
                ready = None
        if identity is not None:
            proc = observed_proc_state(identity)
        if stage == "CHILD_WAIT":
            stage = (
                "CHILD_CUTOFF"
                if time.monotonic() >= cutoff
                else "CHILD_PIDFD"
                if ready is False
                else "CHILD_PROC"
                if ready is True and proc != "ABSENT"
                else "CHILD_WAIT"
            )
        remaining = cutoff - time.monotonic()
        with self.child_lock:
            children = len(self.children)
        helpers, helper_complete = 0, True
        for parent in tuple(self.processes):
            try:
                with (parent.spec.control_path / "helpers.json").open("rb") as stream:
                    raw = stream.read(4097)
                require(len(raw) <= 4096)
                value = json.loads(raw)
                require(
                    value["owner"] == self.h.owner
                    and type(value["pids"]) is list
                    and all(type(pid) is int and pid > 0 for pid in value["pids"])
                    and type(value["complete"]) is bool
                )
                helpers += len(value["pids"])
                helper_complete = helper_complete and value["complete"]
            except Exception:  # noqa: BLE001 -- unknown is not settled.
                helpers, helper_complete = -1, None
                break
        facts = {
            "stage": stage,
            "exception": exception_category(error),
            "pidfd_ready": ready,
            "proc_state": proc,
            "cutoff": "EXPIRED"
            if remaining <= 0
            else "LE_3S"
            if remaining <= 3
            else "GT_3S",
            "children": min(children, 999),
            "parents": min(len(self.processes), 999),
            "observers": int(self.child_thread is not None),
            "callers": min(len(self.h.callers), 999),
            "helpers": min(helpers, 999),
            "helpers_complete": helper_complete,
        }
        diagnostic = getattr(error, "diagnostic", None)
        if not isinstance(diagnostic, PreforkDiagnostic):
            diagnostic = PreforkDiagnostic(error, identity, tuple(facts.items()))
        with self.diagnostic_lock:
            if self.diagnostic is None:
                self.diagnostic = diagnostic
            elif (
                diagnostic is not self.diagnostic and len(self.cleanup_diagnostics) < 16
            ):
                self.cleanup_diagnostics.append(diagnostic)
        return diagnostic

    def __enter__(self):
        self.broker.start()
        return self

    def assert_registry_and_runtime_denials(self):
        from tests.support.asset_job_handlers import ASSET_READ_BINDINGS, REGISTRY

        with self.h.admin.begin() as db:
            require(
                db.execute(
                    text(
                        "SELECT count(*) FROM wso_private.job_kinds WHERE kind LIKE 'ASSET_FIXTURE_%'"
                    )
                ).scalar_one()
                == 0
            )
            for kind in REGISTRY.kinds.values():
                db.execute(
                    text(
                        "INSERT INTO wso_private.job_kinds(kind,payload_version,scope_kind,permission,queue,effect_mode,max_attempts,credential_use) VALUES(:kind,1,:scope,:permission,:queue,:effect,:attempts,false)"
                    ),
                    {
                        "kind": kind.kind,
                        "scope": kind.scope_kind,
                        "permission": kind.permission,
                        "queue": kind.queue,
                        "effect": kind.effect_mode,
                        "attempts": kind.max_attempts,
                    },
                )
            for binding in ASSET_READ_BINDINGS:
                db.execute(
                    text(
                        "INSERT INTO wso_private.asset_job_kinds(kind,purpose,operation) VALUES(:kind,:purpose,'READ')"
                    ),
                    {"kind": binding.kind, "purpose": "IMPORT_" + binding.purpose},
                )
        before = self.h.query(
            "SELECT * FROM wso_private.asset_job_kinds WHERE kind LIKE 'ASSET_FIXTURE_%' ORDER BY kind,purpose"
        )
        require(
            {(row["kind"], row["purpose"], row["operation"]) for row in before}
            == {
                ("ASSET_FIXTURE_TENANT_READ", "IMPORT_PHOTO", "READ"),
                ("ASSET_FIXTURE_TENANT_READ", "IMPORT_CROP", "READ"),
                ("ASSET_FIXTURE_STORE_READ", "IMPORT_PHOTO", "READ"),
                ("ASSET_FIXTURE_STORE_READ", "IMPORT_CROP", "READ"),
                ("ASSET_FIXTURE_PHOTO_ONLY", "IMPORT_PHOTO", "READ"),
            }
        )
        kinds_before = self.h.query(
            "SELECT * FROM wso_private.job_kinds WHERE kind LIKE 'ASSET_FIXTURE_%' ORDER BY kind"
        )
        fields = (
            "kind",
            "payload_version",
            "scope_kind",
            "permission",
            "queue",
            "effect_mode",
            "max_attempts",
            "credential_use",
        )
        require(
            {tuple(row[name] for name in fields) for row in kinds_before}
            == {
                (
                    "ASSET_FIXTURE_" + name,
                    1,
                    "STORE" if name == "STORE_READ" else "TENANT",
                    "OWNER",
                    "wso.default",
                    "READ",
                    3,
                    False,
                )
                for name in ("TENANT_READ", "STORE_READ", "PHOTO_ONLY", "NO_ASSET_READ")
            }
        )
        settings_before = self.h.query("SELECT * FROM wso_private.asset_settings")
        for name in ("APP", "JOB", "DISPATCH", "WORKER", "ASSET_MAINTENANCE"):
            engine = create_engine(
                os.environ[f"WSO_TEST_{name}_DATABASE_URL"], hide_parameters=True
            )
            try:
                statements = (
                    "INSERT INTO wso_private.job_kinds(kind,payload_version,scope_kind,permission,queue,effect_mode,max_attempts,credential_use) VALUES('ASSET_FIXTURE_FORGED',1,'TENANT','OWNER','wso.default','READ',3,false)",
                    "UPDATE wso_private.job_kinds SET permission='OWNER' WHERE kind LIKE 'ASSET_FIXTURE_%'",
                    "DELETE FROM wso_private.job_kinds WHERE kind LIKE 'ASSET_FIXTURE_%'",
                    "INSERT INTO wso_private.asset_job_kinds VALUES('ASSET_FIXTURE_NO_ASSET_READ','IMPORT_PHOTO','READ')",
                    "UPDATE wso_private.asset_job_kinds SET operation='READ' WHERE kind LIKE 'ASSET_FIXTURE_%'",
                    "DELETE FROM wso_private.asset_job_kinds WHERE kind LIKE 'ASSET_FIXTURE_%'",
                    "INSERT INTO wso_private.asset_settings(singleton) VALUES(true)",
                    "UPDATE wso_private.asset_settings SET version=version+1",
                    "DELETE FROM wso_private.asset_settings",
                    "ALTER TABLE wso_private.asset_job_kinds ADD COLUMN forged integer",
                )
                for statement in statements:
                    with engine.connect() as db:
                        transaction = db.begin()
                        try:
                            db.execute(text("SET LOCAL statement_timeout=5000"))
                            db.execute(text(statement))
                        except Exception as error:  # noqa: BLE001 -- exact SQLSTATE only escapes privately
                            require(
                                getattr(getattr(error, "orig", None), "sqlstate", None)
                                == "42501"
                            )
                        else:
                            raise RuntimeError("runtime registry mutation accepted")
                        finally:
                            transaction.rollback()
                    require(
                        self.h.query(
                            "SELECT * FROM wso_private.asset_job_kinds WHERE kind LIKE 'ASSET_FIXTURE_%' ORDER BY kind,purpose"
                        )
                        == before
                    )
                    require(
                        self.h.query(
                            "SELECT * FROM wso_private.job_kinds WHERE kind LIKE 'ASSET_FIXTURE_%' ORDER BY kind"
                        )
                        == kinds_before
                    )
                    require(
                        self.h.query("SELECT * FROM wso_private.asset_settings")
                        == settings_before
                    )
            finally:
                engine.dispose()
        require(
            self.h.query(
                "SELECT * FROM wso_private.asset_job_kinds WHERE kind LIKE 'ASSET_FIXTURE_%' ORDER BY kind,purpose"
            )
            == before
        )

    def launch_worker(self, *, cutoff=None):
        spec = self.h.process_spec(broker=self.broker.identity.endpoint_url)
        owned = self.h.start_mode(ProcessMode.JOB_WORKER, spec)
        self.processes.append(owned)
        self.broker.consumer_pids.add(owned.process.pid)
        if self.child_thread is None:
            self.child_stop.clear()
            self.child_thread = threading.Thread(
                target=self.observe_children, name="owned-asset-prefork-observer"
            )
            self.child_thread.start()

        def child():
            require(self.child_failure is None and owned.process.poll() is None)
            with self.child_lock:
                found = [
                    identity
                    for identity, _descriptor, parent in self.children.values()
                    if parent is owned
                ]
            if not found:
                return False
            require(len(found) == 1)
            identity = found[0]
            private_json(
                spec.control_path / f"child-{identity.pid}.release",
                {
                    "owner": self.h.owner,
                    "pid": identity.pid,
                    "start_ticks": identity.start_ticks,
                },
            )
            return identity

        allowance = min(30, cutoff - time.monotonic()) if cutoff is not None else 30
        require(allowance > 0)
        self.h.await_fact(child, cap=allowance)
        if cutoff is not None:
            require(time.monotonic() < cutoff)
        return owned

    def observe_children(self):
        stage = "OBSERVER_PUBLICATION"
        observed_identity = None
        try:
            while not self.child_stop.is_set():
                for parent in tuple(self.processes):
                    if parent.mode is not ProcessMode.JOB_WORKER:
                        continue
                    for path in parent.spec.control_path.glob("child-*.json"):
                        if (
                            path.name.endswith("-settled.json")
                            or path in self.seen_children
                        ):
                            continue
                        stage = "OBSERVER_PUBLICATION"
                        observed_identity = None
                        value = json.loads(path.read_bytes())
                        value["command"] = tuple(value["command"])
                        identity = ProcessIdentity(**value)
                        observed_identity = identity
                        stage = "OBSERVER_PIDFD"
                        descriptor = os.pidfd_open(identity.pid, 0)
                        try:
                            stage = "OBSERVER_IDENTITY"
                            validate_process_identity(
                                identity, process_identity(identity.pid, self.h.owner)
                            )
                            validate_process_identity(
                                parent.identity,
                                process_identity(parent.process.pid, self.h.owner),
                            )
                            require(
                                identity.ppid == parent.process.pid
                                and identity.pgid == parent.process.pid
                                and identity.uid == parent.identity.uid
                                and identity.command == parent.command
                            )
                        except BaseException:
                            os.close(descriptor)
                            raise
                        with self.child_lock:
                            require(identity.pid not in self.children)
                            self.children[identity.pid] = (identity, descriptor, parent)
                            self.seen_children.add(path)
                self.child_stop.wait(0.025)
        except BaseException as error:  # noqa: BLE001 -- private first cause, fixed public failure.
            diagnostic = self.record_diagnostic(
                stage, error, self.diagnostic_cutoff, identity=observed_identity
            )
            self.child_failure = PreforkSettlementError(diagnostic)

    def launch_dispatch(self):
        owned = self.h.start_mode(
            ProcessMode.DISPATCH,
            self.h.process_spec(broker=self.broker.identity.endpoint_url),
        )
        self.processes.append(owned)
        return owned

    def enqueue(
        self,
        asset,
        *,
        actor=None,
        kind="ASSET_FIXTURE_TENANT_READ",
        checkpoint="none",
        attached=None,
        attach=True,
        store_id=None,
    ):
        actor = actor or self.h.actors[0]
        spec = self.h.process_spec(broker=self.broker.identity.endpoint_url)
        scope = (
            {"scope_kind": "TENANT", "tenant_id": str(actor.tenant_id)}
            if store_id is None
            else {
                "scope_kind": "STORE",
                "tenant_id": str(actor.tenant_id),
                "store_id": str(store_id),
            }
        )
        operation = uuid4()
        private_json(
            spec.control_path / "producer.json",
            {
                "owner": self.h.owner,
                "token": actor.token,
                "scope": scope,
                "payload": {
                    "schema_version": 1,
                    "operation_id": str(operation),
                    "asset_id": asset["id"],
                    "checkpoint": checkpoint,
                },
                "kind": kind,
                "idempotency_key": str(operation),
                "attach": attach,
                "attachment_id": attached["id"] if attached else asset["id"],
            },
        )
        before = {
            table: self.h.query("SELECT * FROM public." + table)
            for table in ("jobs", "outbox", "job_assets")
        }
        owned = self.h.start_mode(ProcessMode.PRODUCER, spec)
        self.h.await_fact(lambda: owned.process.poll() is not None, cap=10)
        require(owned.process.returncode == 0)
        result = json.loads((spec.control_path / "producer-result.json").read_bytes())
        self.h.stop_mode(owned)
        require(result["owner"] == self.h.owner)
        if not result["accepted"]:
            after = {
                table: self.h.query("SELECT * FROM public." + table)
                for table in ("jobs", "outbox", "job_assets")
            }
            require(
                all(
                    sorted(map(repr, before[k])) == sorted(map(repr, after[k]))
                    for k in before
                )
            )
        return result

    def job(self, identifier):
        return self.h.query(
            "SELECT * FROM public.jobs WHERE id=:id", {"id": UUID(str(identifier))}
        )[0]

    def stop_processes(self, *, cleanup_cutoff=None):
        first = None
        cutoff = (
            cleanup_cutoff
            if cleanup_cutoff is not None
            else self.h.deadlines.cutoffs[self.h.phase]
        )
        for process in reversed(self.processes):
            try:
                self.h.stop_mode(process, cleanup_cutoff=cleanup_cutoff)
            except Exception as error:  # noqa: BLE001 -- settle all exact parent handles
                self.record_diagnostic(
                    "PARENT_STOP",
                    error,
                    cutoff,
                    identity=getattr(process, "identity", None),
                )
                first = first or error
        self.child_stop.set()
        if self.child_thread is not None:
            try:
                self.child_thread.join(max(0, min(3, cutoff - time.monotonic())))
                if self.child_thread.is_alive() or self.child_failure is not None:
                    raise self.child_failure or RuntimeError(
                        "prefork observer unsettled"
                    )
            except Exception as error:  # noqa: BLE001 -- still attempt every retained child.
                self.record_diagnostic("OBSERVER_JOIN", error, cutoff)
                first = first or error
            else:
                self.child_thread = None
        children_cutoff = min(time.monotonic() + 3, cutoff)
        for pid, (identity, descriptor, _parent) in tuple(self.children.items()):
            try:
                remaining = children_cutoff - time.monotonic()
                require(remaining > 0)
                predicate = lambda pid=pid, descriptor=descriptor: (
                    select_pidfd(descriptor) and not Path(f"/proc/{pid}").exists()
                )
                if cleanup_cutoff is None:
                    self.h.await_fact(predicate, cap=remaining)
                else:
                    self.h.await_owned_cleanup(predicate, children_cutoff)
            except Exception as error:  # noqa: BLE001 -- retain unresolved descriptors
                self.record_diagnostic(
                    "CHILD_WAIT",
                    error,
                    cutoff,
                    identity=identity,
                    descriptor=descriptor,
                )
                first = first or error
            else:
                os.close(descriptor)
                self.children.pop(pid)
        if first is not None:
            raise PreforkSettlementError(self.diagnostic) from None
        self.processes.clear()

    def crash_and_recover(self, asset, position, *, recovery_seconds):
        self.diagnostic_stage = "CRASH_SETUP"
        self.diagnostic_cutoff = self.h.deadlines.cutoffs[self.h.phase]
        try:
            return self._crash_and_recover(
                asset, position, recovery_seconds=recovery_seconds
            )
        except BaseException as error:  # noqa: BLE001 -- retain exact initiating stage.
            self.record_diagnostic(self.diagnostic_stage, error, self.diagnostic_cutoff)
            raise PreforkSettlementError(self.diagnostic) from None

    def _crash_and_recover(self, asset, position, *, recovery_seconds):
        require(position in {"after-read", "after-commit"} and recovery_seconds == 160)
        result = self.enqueue(asset, checkpoint=position)
        require(result["accepted"])
        job_id = result["job_id"]
        worker = self.launch_worker()
        control = self.h.control_for(worker)
        event = "JOB_AFTER_READ" if position == "after-read" else "JOB_AFTER_COMMIT"
        checkpoint_cutoff = time.monotonic() + self.h.deadlines.allowance(
            20.0, self.h.phase
        )
        control.arm(event, asset_id=UUID(job_id), cutoff=checkpoint_cutoff)
        self.launch_dispatch()
        self.diagnostic_stage, self.diagnostic_cutoff = (
            "CRASH_CHECKPOINT",
            checkpoint_cutoff,
        )
        control.wait(checkpoint_cutoff)
        self.diagnostic_stage = "CRASH_HELPERS"
        self.h.assert_helpers_settled(worker)
        self.diagnostic_stage = "CRASH_IDENTITY"
        child = next(
            identity
            for identity, _fd, parent in self.children.values()
            if parent is worker
        )
        descriptor = self.children[child.pid][1]
        validate_process_identity(child, process_identity(child.pid, self.h.owner))
        row = self.job(job_id)
        first_attempt, first_generation = row["attempts"], row["lease_generation"]
        facts = self.broker.transport_facts(job_id)
        reserved = [f for f in facts if f["event"] == "reserved"]
        require(reserved)

        def effects():
            return {
                "items": self.h.query(
                    "SELECT * FROM public.job_items WHERE job_id=:id",
                    {"id": UUID(job_id)},
                ),
                "reads": self.h.query(
                    "SELECT * FROM wso_private.asset_read_leases WHERE job_id=:id",
                    {"id": UUID(job_id)},
                ),
                "audits": self.h.query(
                    "SELECT * FROM public.audit_events WHERE entity_id IN (:job,:asset)",
                    {"job": job_id, "asset": asset["id"]},
                ),
            }

        committed = effects() if position == "after-commit" else None
        if committed is not None:
            require(
                len(committed["reads"]) == 1
                and len(committed["items"]) == 1
                and committed["items"][0]["state"] == "SUCCEEDED"
            )
        recovery_cutoff = time.monotonic() + self.h.deadlines.allowance(
            float(recovery_seconds), self.h.phase
        )

        def remaining():
            value = recovery_cutoff - time.monotonic()
            require(value > 0)
            return value

        self.diagnostic_cutoff = recovery_cutoff
        self.diagnostic_stage = "CRASH_IDENTITY"
        parent_fd = os.pidfd_open(worker.process.pid)
        try:
            validate_process_identity(
                worker.identity, process_identity(worker.process.pid, self.h.owner)
            )
            self.diagnostic_stage = "CRASH_SIGNAL"
            signal.pidfd_send_signal(descriptor, signal.SIGKILL, None, 0)
            signal.pidfd_send_signal(parent_fd, signal.SIGKILL, None, 0)
            self.diagnostic_stage = "CRASH_READINESS"
            try:
                self.h.await_fact(
                    lambda: select_pidfd(descriptor) and select_pidfd(parent_fd), cap=3
                )
            except BaseException as error:
                self.record_diagnostic(
                    "CRASH_READINESS",
                    error,
                    recovery_cutoff,
                    identity=child,
                    descriptor=descriptor,
                )
                raise
        finally:
            os.close(parent_fd)
        self.stop_processes(cleanup_cutoff=recovery_cutoff)
        remaining()
        self.diagnostic_stage = "RECOVERY"
        control.reset()
        if position == "after-read":
            self.last_lease = json.loads(
                (worker.spec.control_path / "job-lease.json").read_bytes()
            )
        remaining()
        self.launch_worker(cutoff=recovery_cutoff)
        remaining()
        self.launch_dispatch()
        self.h.await_fact(
            lambda: self.job(job_id)["state"] == "SUCCEEDED", cap=remaining()
        )
        self.h.await_fact(
            lambda: (
                any(f["event"] == "acked" for f in self.broker.transport_facts(job_id))
                and (
                    position == "after-read"
                    or any(
                        f["event"] == "reserved" and f["redelivered"]
                        for f in self.broker.transport_facts(job_id)
                    )
                )
            ),
            cap=remaining(),
        )
        facts = self.broker.transport_facts(job_id)
        require(any(f["event"] == "acked" for f in facts))
        if position == "after-read":
            current = self.job(job_id)
            require(
                current["attempts"] > first_attempt
                and current["lease_generation"] > first_generation
            )
        else:
            require(any(f["event"] == "reserved" and f["redelivered"] for f in facts))
        items = self.h.query(
            "SELECT * FROM public.job_items WHERE job_id=:id", {"id": UUID(job_id)}
        )
        require(len(items) == 1 and items[0]["state"] == "SUCCEEDED")
        require(
            items[0]["result"]["sha256"] == self.h.row(asset["id"])["checksum_sha256"]
        )
        if committed is not None:
            require(effects() == committed)
        else:
            require(len(effects()["reads"]) == 1)
        self.stop_processes(cleanup_cutoff=recovery_cutoff)
        remaining()

    def denial_trial(self, variant):
        self.h.job_denial_trial(self, variant)

    def assert_settled(self):
        self.stop_processes()
        self.h.await_fact(
            lambda: (
                self.broker.client.llen("wso.default") == 0
                and self.broker.client.hlen("unacked") == 0
            ),
            cap=160,
        )
        self.broker.assert_settled()

    def __exit__(self, *_exc):
        cutoff = self.broker.teardown_cutoff
        if cutoff is None:
            cutoff = min(self.h.deadlines.start + 94 * 60, time.monotonic() + 8 * 60)
        if self.h.phase.value == "TEARDOWN":
            cutoff = min(cutoff, self.h.deadlines.cutoffs[self.h.phase])
        if len(_exc) > 1 and _exc[1] is not None:
            self.record_diagnostic("BODY", _exc[1], self.diagnostic_cutoff)
        self.stop_processes(cleanup_cutoff=cutoff)
        try:
            self.broker.close(cutoff)
        except BaseException as error:  # noqa: BLE001 -- preserve prior body failure.
            self.record_diagnostic("BROKER_CLOSE", error, cutoff)
            raise PreforkSettlementError(self.diagnostic) from None
        self.h.jobs_context = None


def select_pidfd(descriptor):
    import select

    return bool(select.select([descriptor], [], [], 0)[0])
