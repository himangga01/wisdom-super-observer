"""Actual Linux HTTP + PostgreSQL + private S3 asset acceptance fixture."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.support.asset_faults import (
    BarrierControl,
    EpochTracker,
    FaultMode,
    FaultRelay,
    FixtureContractError,
    IdleSnapshot,
    MultipartPageCursor,
    ObjectPageCursor,
    OwnedProcess,
    S3FaultSelector,
    S3Operation,
    TraversalStream,
    native_float,
    raw_http_exchange,
    require,
    validate_idle_snapshot,
)
from tests.support.asset_process import (
    ROLES,
    ProcessMode,
    ProcessSpec,
    build_process_env,
)
from tests.support.asset_provider import AssetProvider
from tests.support.asset_provider import private_json as exclusive_private_json
from tests.support.job_handlers import verify_fixture_database

ROOT = Path(__file__).resolve().parents[2]


class FixturePhase(str, Enum):
    SETUP = "SETUP"
    PRE_AGE = "PRE_AGE"
    AGING = "AGING"
    POST_AGE = "POST_AGE"
    TEARDOWN = "TEARDOWN"


class FixtureDeadlineError(RuntimeError):
    def __init__(self):
        super().__init__("fixture deadline expired")


class FixtureDeadlines:
    def __init__(self, start, *, clock=time.monotonic):
        self.start, self.clock = native_float(start), clock
        self.work = start + 86 * 60
        self.cutoffs = {FixturePhase.SETUP: start + 12 * 60}
        self.age_anchor = None

    def finish_age_seed(self):
        require(self.age_anchor is None)
        self.check(FixturePhase.SETUP)
        self.age_anchor = native_float(self.clock())
        self.cutoffs[FixturePhase.PRE_AGE] = min(self.work, self.age_anchor + 45 * 60)
        self.cutoffs[FixturePhase.AGING] = min(self.work, self.age_anchor + 62 * 60)

    def begin_post_age(self):
        require(
            self.age_anchor is not None and FixturePhase.POST_AGE not in self.cutoffs
        )
        now = native_float(self.clock())
        if now < self.age_anchor + 62 * 60:
            raise FixtureDeadlineError()
        if now >= self.work:
            raise FixtureDeadlineError()
        self.cutoffs[FixturePhase.POST_AGE] = min(self.work, now + 12 * 60)

    def begin_teardown(self):
        require(FixturePhase.TEARDOWN not in self.cutoffs)
        self.cutoffs[FixturePhase.TEARDOWN] = min(
            self.start + 94 * 60, native_float(self.clock()) + 8 * 60
        )

    def check(self, phase):
        require(type(phase) is FixturePhase and phase in self.cutoffs)
        if native_float(self.clock()) >= self.cutoffs[phase]:
            raise FixtureDeadlineError()

    def allowance(self, cap, phase):
        native_float(cap)
        require(cap > 0 and phase is not FixturePhase.AGING)
        require(type(phase) is FixturePhase and phase in self.cutoffs)
        now = native_float(self.clock())
        if now >= self.cutoffs[phase]:
            raise FixtureDeadlineError()
        return min(cap, self.cutoffs[phase] - now)


class RuntimeAccess:
    def __init__(self, provider, deadlines, phase):
        import boto3
        from botocore.config import Config

        from tests.support.asset_minio import RelayCommands
        from tests.support.asset_rustfs import BudgetS3Client

        self.provider, self.deadlines, self.phase = provider, deadlines, phase
        self.stop = threading.Event()
        self.commands = RelayCommands(self.stop)
        self.clients = {}
        for name, (access, secret) in provider.credentials.items():
            client = boto3.client(
                "s3",
                endpoint_url=provider.endpoint,
                region_name="us-east-1",
                aws_access_key_id=access,
                aws_secret_access_key=secret,
                config=Config(
                    signature_version="s3v4",
                    connect_timeout=3,
                    read_timeout=5,
                    retries={"total_max_attempts": 1},
                    s3={"addressing_style": "path"},
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
            )
            self.clients[name] = BudgetS3Client(client, self)

    def allowance(self, cap):
        return self.deadlines.allowance(float(cap), self.phase)

    def check(self):
        self.deadlines.check(self.phase)

    def assert_mapping(self, cutoff):
        require(self.provider.relay_pin is not None)
        self.provider.relay.assert_healthy()
        return self.provider.read_relay_identity(cutoff, self.stop, self.commands)

    def assert_settled(self):
        require(all(not client.streams for client in self.clients.values()))
        require(not self.commands.records)

    def close(self):
        first = None
        for client in self.clients.values():
            try:
                client.close()
            except Exception as error:  # noqa: BLE001 -- attempt every exact owned pool
                first = first or error
        self.stop.set()
        try:
            self.commands.cancel(
                min(time.monotonic() + 3, self.deadlines.cutoffs[self.phase])
            )
            self.assert_settled()
        except Exception as error:  # noqa: BLE001 -- retain earliest settlement failure
            first = first or error
        if first is not None:
            raise RuntimeError("runtime inspection settlement refused") from None


@dataclass(repr=False)
class BrowserActor:
    tenant_id: object
    user_id: object
    token: str = field(repr=False)
    csrf: str = field(repr=False)
    expires_at: datetime | None = field(default=None, repr=False)


class OwnedCall:
    """A real caller with one immutable cutoff and unconditional local join."""

    def __init__(self, function, cutoff, release=None):
        self.cutoff, self.release_action = cutoff, release
        self.done, self.value, self.error = threading.Event(), None, None

        def run():
            try:
                self.value = function()
            except BaseException as error:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
                self.error = error
            finally:
                self.done.set()

        self.thread = threading.Thread(target=run, name="owned-asset-fixture-caller")
        self.thread.start()

    def release(self):
        if self.release_action is not None:
            self.release_action()

    def result(self, *, error_allowed=False):
        require(self.done.wait(max(0, self.cutoff - time.monotonic())))
        self.thread.join(max(0, self.cutoff - time.monotonic()))
        require(not self.thread.is_alive() and time.monotonic() < self.cutoff)
        if self.error is not None:
            require(error_allowed and isinstance(self.error, httpx.HTTPError))
            return None
        return self.value

    def close(self):
        first = None
        try:
            self.release()
        except BaseException as error:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
            first = error
        finally:
            self.thread.join(max(0, self.cutoff - time.monotonic()))
        require(first is None and not self.thread.is_alive())


def synthetic_image(*, width=24, height=24, format="PNG", noise=False):
    from PIL import Image

    image = (
        Image.frombytes("RGB", (width, height), secrets.token_bytes(width * height * 3))
        if noise
        else Image.new("RGB", (width, height), "#1357ad")
    )
    stream = io.BytesIO()
    image.save(stream, format=format)
    return stream.getvalue()


class AssetHarness:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.owner = uuid4().hex
        self.provider = AssetProvider(self.directory)
        self.admin = None
        self.process = None
        self.command = None
        self.start_time = None
        self.log = None
        self.actors = []
        self.base_url = None
        self.evidence = {"schema_version": 1, "stage": "SETUP_STARTED"}
        self.deadlines = FixtureDeadlines(float(time.monotonic()))
        self.phase = FixturePhase.SETUP
        self.modes, self.faults = {}, []
        self.access = None
        self.namespace = None
        self.key_files, self.active_key = {}, "K1"
        self.age_seeds, self.young_seeds = [], []
        self.upload_sizes = {}
        self.conservative = set()
        self.callers = []
        self.launches = []
        self.jobs_context = None
        self.provider_evidence = (
            ROOT / ".superpowers/verification/private-assets-green-provider.json"
        )

    def write_red_evidence(self):
        """Overwrite a fixed sanitized receipt; never copy private fixture state."""
        directory = ROOT / ".superpowers" / "verification"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "private-assets-red-evidence.json"
        temporary = directory / (".private-assets-red-" + self.owner + ".tmp")

        exclusive_private_json(temporary, self.evidence)
        temporary.replace(target)

    def __enter__(self):
        if sys.platform != "linux":
            pytest.fail("private_assets requires actual owned Linux S3/HTTP; no skip")
        try:
            require(
                os.environ.get("CI") == "true"
                and os.environ.get("WSO_CI_DISPOSABLE_POSTGRES") == "1"
            )
            anchor = os.environ.get("WSO_TEST_ASSET_SUITE_STARTED_MONOTONIC", "")
            require(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", anchor) is not None)
            started = float(anchor)
            require(math.isfinite(started) and 0 <= started <= time.monotonic())
            self.deadlines = FixtureDeadlines(started)
            self.deadlines.check(FixturePhase.SETUP)
            self.provider_evidence.unlink(missing_ok=True)
            self.admin = create_engine(
                os.environ["WSO_TEST_ADMIN_DATABASE_URL"],
                hide_parameters=True,
                connect_args={"connect_timeout": 5},
            )
            verify_fixture_database(self.admin, domain_only=False)
            admin_url = make_url(self.admin.url)
            for name, role in ROLES.items():
                url = make_url(os.environ[f"WSO_TEST_{name}_DATABASE_URL"])
                if (url.host, url.port, url.database, url.username, url.drivername) != (
                    admin_url.host,
                    admin_url.port,
                    admin_url.database,
                    role,
                    "postgresql+psycopg",
                ) or url.query:
                    raise ValueError("asset fixture runtime role target mismatch")
            self.assert_role_logins()
            self.provider.start()
            with self.provider.relay.lock:
                acceptors = [
                    thread
                    for thread in self.provider.relay.threads
                    if thread.name == "owned-asset-relay"
                ]
                require(len(acceptors) == 1)
                self.acceptor = acceptors[0]
            self.deadlines.check(self.phase)
            from wso_core.storage import InstallationNamespace

            self.namespace = InstallationNamespace(
                self.provider.installation_id, self.provider.bucket
            )
            for client in self.provider.clients.values():
                client.close()
            self.fresh_runtime_access(self.phase)
            self.install_namespace_and_keys()
            self.new_actor()
            self.new_actor()
            self.start_api()
            self.verify_http_identity()
            self.seed_age_window()
            self.deadlines.finish_age_seed()
            self.young_witness = self.reconcile_epoch(expected_counts=(6, 5))
            self.phase = FixturePhase.PRE_AGE
            self.fresh_runtime_access(self.phase)
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def new_actor(self, *, tenant_id=None, user_id=None, expires_seconds=600):
        from wso_api.auth import PostgresSessionStore, WebSession, token_digest

        actor = BrowserActor(
            tenant_id or uuid4(),
            user_id or uuid4(),
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(32),
        )
        if user_id is None:
            with self.admin.begin() as db:
                if tenant_id is None:
                    db.execute(
                        text(
                            "INSERT INTO tenants(id,name) VALUES(:id,'asset-fixture')"
                        ),
                        {"id": actor.tenant_id},
                    )
                db.execute(
                    text(
                        "INSERT INTO users(id,oidc_issuer,oidc_subject) "
                        "VALUES(:id,'https://issuer.test',:subject)"
                    ),
                    {"id": actor.user_id, "subject": str(actor.user_id)},
                )
                db.execute(
                    text(
                        "INSERT INTO memberships(tenant_id,user_id,role) VALUES(:t,:u,'OWNER')"
                    ),
                    {"t": actor.tenant_id, "u": actor.user_id},
                )
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(
            os.environ["WSO_TEST_SESSION_DATABASE_URL"], hide_parameters=True
        )
        sessions = PostgresSessionStore(
            os.environ["WSO_TEST_SESSION_DATABASE_URL"],
            session_factory=sessionmaker(engine),
        )
        require(type(expires_seconds) is int and 1 <= expires_seconds <= 600)
        actor.expires_at = datetime.now(UTC) + timedelta(seconds=expires_seconds)
        try:
            created = sessions.create(
                token_digest(actor.token),
                WebSession(
                    "https://issuer.test",
                    str(actor.user_id),
                    actor.user_id,
                    token_digest(actor.csrf),
                    actor.expires_at,
                ),
                token_digest(secrets.token_urlsafe(32)),
            )
            require(created)
        finally:
            engine.dispose()
        self.actors.append(actor)
        return actor

    def start_api(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.api_port = port
        self.api_spec = self.process_spec()
        owned = self.start_mode(ProcessMode.API, self.api_spec)
        self.process, self.command, self.log = (
            owned.process,
            list(owned.command),
            owned.log,
        )
        self.start_time = owned.identity.start_ticks

        def ready():
            if self.process.poll() is not None:
                raise RuntimeError("actual asset API subprocess failed to boot")
            try:
                return (
                    self.request("GET", "/health/live", authenticated=False).status_code
                    == 200
                )
            except httpx.HTTPError:
                return False

        self.await_fact(ready, cap=30)

    @staticmethod
    def process_identity(pid):
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[0], int(fields[2]), int(fields[19])

    def stop_api(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            if not hasattr(os, "pidfd_open") or not hasattr(
                signal, "pidfd_send_signal"
            ):
                raise ValueError("stable API process signaling unavailable")
            try:
                descriptor = os.pidfd_open(self.process.pid, 0)
            except OSError:
                raise ValueError("API process ownership handle unavailable") from None
            try:
                try:
                    state, group, started = self.process_identity(self.process.pid)
                    process_path = Path(f"/proc/{self.process.pid}")
                    environment = (process_path / "environ").read_bytes().split(b"\0")
                    command = (process_path / "cmdline").read_bytes()
                except OSError:
                    raise ValueError(
                        "API process identity unavailable; signal refused"
                    ) from None
                expected_command = (
                    b"\0".join(os.fsencode(part) for part in self.command) + b"\0"
                    if self.command is not None
                    else None
                )
                if (
                    state == "Z"
                    or group != self.process.pid
                    or started != self.start_time
                    or f"WSO_ASSET_FIXTURE_OWNER={self.owner}".encode()
                    not in environment
                    or expected_command is None
                    or command != expected_command
                ):
                    raise ValueError("API process ownership mismatch; signal refused")
                signal.pidfd_send_signal(descriptor, signal.SIGKILL, None, 0)
            finally:
                os.close(descriptor)
        self.process.wait(timeout=10)
        self.process = None
        self.log.close()
        self.log = None

    def request(
        self,
        method,
        path,
        *,
        actor=None,
        authenticated=True,
        csrf=True,
        headers=None,
        **kwargs,
    ):
        actor = actor or self.actors[0]
        outgoing = dict(headers or {})
        if authenticated:
            from wso_api.auth import SESSION_COOKIE

            outgoing["Cookie"] = f"{SESSION_COOKIE}={actor.token}"
        if csrf:
            outgoing["Origin"] = "https://app.test"
            outgoing["X-CSRF-Token"] = actor.csrf
        allowance = self.deadlines.allowance(
            float(
                120
                if method == "PUT"
                else 30
                if path.endswith("/complete")
                or "/complete?" in path
                or method == "GET"
                and "/content?" in path
                else 5
            ),
            self.phase,
        )
        cutoff = time.monotonic() + allowance
        with httpx.Client(
            base_url=self.base_url,
            timeout=allowance,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            result = client.request(method, path, headers=outgoing, **kwargs)
            require(time.monotonic() < cutoff)
            self.deadlines.check(self.phase)
            return result

    def verify_http_identity(self):
        for actor in self.actors:
            me = self.request("GET", "/api/v1/me", actor=actor)
            assert me.status_code == 200, "real PostgreSQL cookie authentication failed"
            assert me.json()["user_id"] == str(actor.user_id)
            stores = self.request(
                "GET", f"/api/v1/stores?tenant_id={actor.tenant_id}", actor=actor
            )
            assert stores.status_code == 200 and stores.json()["items"] == []
            denied = self.request(
                "DELETE", "/api/v1/auth/session", actor=actor, csrf=False
            )
            assert denied.status_code == 403, (
                "actual auth mutation did not enforce CSRF"
            )
        with self.admin.connect() as db:
            assert (
                db.execute(
                    text("SELECT count(*) FROM stores WHERE tenant_id IN (:a,:b)"),
                    {"a": self.actors[0].tenant_id, "b": self.actors[1].tenant_id},
                ).scalar_one()
                == 0
            )
        primary = self.actors[0]
        probe = self.new_actor(tenant_id=primary.tenant_id, user_id=primary.user_id)
        assert (
            self.request("DELETE", "/api/v1/auth/session", actor=probe).status_code
            == 204
        ), "CSRF-valid actual mutation failed"
        self.actors.remove(probe)
        self.evidence["http_preflight"] = {
            "authenticated_tenants": 2,
            "me_statuses": [200, 200],
            "store_counts": [0, 0],
            "csrf_missing_status": 403,
            "csrf_valid_status": 204,
        }
        self.evidence["stage"] = "HTTP_PREFLIGHT_PASSED"

    def begin(
        self,
        data,
        *,
        actor=None,
        content_type="image/png",
        purpose="IMPORT_PHOTO",
        parent_asset_id=None,
        store_id=None,
        **overrides,
    ):
        actor = actor or self.actors[0]
        body = {
            "scope": {"scope_kind": "TENANT", "tenant_id": str(actor.tenant_id)},
            "purpose": purpose,
            "content_type": content_type,
            "byte_size": len(data),
            "checksum": {
                "algorithm": "SHA256",
                "value": hashlib.sha256(data).hexdigest(),
            },
            "parent_asset_id": parent_asset_id,
        }
        if store_id is not None:
            body["scope"] = {
                "scope_kind": "STORE",
                "tenant_id": str(actor.tenant_id),
                "store_id": str(store_id),
            }
        body.update(overrides)
        return self.request("POST", "/api/v1/assets", actor=actor, json=body)

    def put(self, session, data, *, actor=None, content_type="image/png", **kwargs):
        return self._upload_exchange(
            "PUT",
            lambda: self.request(
                "PUT",
                session["upload_path"],
                actor=actor,
                headers={
                    "X-Upload-Session": session["id"],
                    "Content-Type": content_type,
                },
                content=data,
                **kwargs,
            ),
            actor=actor,
        )

    def complete(self, asset_id, *, actor=None):
        actor = actor or self.actors[0]
        return self._upload_exchange(
            "COMPLETE",
            lambda: self.request(
                "POST",
                f"/api/v1/assets/{asset_id}/complete?tenant_id={actor.tenant_id}",
                actor=actor,
            ),
            actor=actor,
        )

    def upload(self, data, *, actor=None, **kwargs):
        response = self.begin(data, actor=actor, **kwargs)
        assert response.status_code == 201, (
            f"authenticated POST /api/v1/assets returned {response.status_code}; expected 201"
        )
        session = response.json()
        assert (
            self.put(
                session,
                data,
                actor=actor,
                content_type=kwargs.get("content_type", "image/png"),
            ).status_code
            == 204
        )
        complete = self.complete(session["asset_id"], actor=actor)
        assert complete.status_code == 200
        return complete.json()

    def ticket(self, asset_id, *, actor=None):
        actor = actor or self.actors[0]
        return self.request(
            "POST",
            f"/api/v1/assets/{asset_id}/download-tickets?tenant_id={actor.tenant_id}",
            actor=actor,
        )

    def download(self, asset_id, *, actor=None, ticket=None):
        issued = self.ticket(asset_id, actor=actor) if ticket is None else ticket
        if hasattr(issued, "status_code"):
            if issued.status_code != 201:
                return issued
            issued = issued.json()
        return self.request(
            "GET",
            issued["download_path"],
            actor=actor,
            headers={"X-Asset-Ticket": issued["token"]},
        )

    def delete(self, asset_id, *, actor=None):
        actor = actor or self.actors[0]
        return self.request(
            "DELETE",
            f"/api/v1/assets/{asset_id}?tenant_id={actor.tenant_id}",
            actor=actor,
        )

    image = staticmethod(synthetic_image)

    @staticmethod
    def chunks(data):
        for offset in range(0, len(data), 262144):
            yield data[offset : offset + 262144]

    @staticmethod
    def animated_image():
        from PIL import Image

        stream = io.BytesIO()
        Image.new("RGB", (24, 24), "red").save(
            stream,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGB", (24, 24), "blue")],
            duration=100,
            loop=0,
        )
        return stream.getvalue()

    @staticmethod
    def large_image():
        data = synthetic_image(width=1800, height=1800, noise=True)
        require(5242880 < len(data) <= 20971520)
        return data

    def await_fact(self, predicate, *, cap):
        cutoff = time.monotonic() + self.deadlines.allowance(float(cap), self.phase)
        while time.monotonic() < cutoff:
            value = predicate()
            if time.monotonic() >= cutoff:
                raise FixtureDeadlineError()
            if value:
                return value
            time.sleep(min(0.05, cutoff - time.monotonic()))
        raise RuntimeError("owned fixture observation deadline")

    def fresh_runtime_access(self, phase):
        if self.access is not None:
            self.access.close()
        self.access = RuntimeAccess(self.provider, self.deadlines, phase)
        self.access.assert_mapping(
            time.monotonic() + self.deadlines.allowance(2.0, phase)
        )
        return self.access

    def process_spec(self, *, endpoint=None, keys=None, active=None, broker=None):
        from wso_core.storage import S3Credentials

        control = self.directory / ("control-" + uuid4().hex)
        control.mkdir(mode=0o700)
        return ProcessSpec(
            self.owner,
            self.directory.resolve(),
            control.resolve(),
            self.namespace,
            endpoint or self.provider.endpoint,
            "us-east-1",
            S3Credentials(*self.provider.credentials["gateway"]),
            S3Credentials(*self.provider.credentials["cleanup"]),
            keys or self.key_files,
            active or self.active_key,
            broker or "redis://127.0.0.1:1/0",
            "asset-fixture-" + self.owner,
        )

    def start_mode(self, mode, spec, *, argument=None):
        selected = {
            f"WSO_TEST_{name}_DATABASE_URL": os.environ[f"WSO_TEST_{name}_DATABASE_URL"]
            for name in ROLES
        }
        selected.update(
            {
                name: os.environ[name]
                for name in (
                    "PATH",
                    "LANG",
                    "LC_ALL",
                    "CI",
                    "WSO_CI_DISPOSABLE_POSTGRES",
                )
                if name in os.environ
            }
        )
        selected["TMPDIR"] = str(self.directory.resolve())
        environment = build_process_env(mode, selected, spec)
        argument = (
            str(self.api_port)
            if mode is ProcessMode.API and argument is None
            else str(argument or 1)
        )
        command = [
            sys.executable,
            "-m",
            "tests.support.asset_process",
            mode.value,
            argument,
        ]
        log_path = spec.control_path / "private.log"
        log = log_path.open("xb")
        os.chmod(log_path, 0o600)
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.launches.append((process, log))
        descriptor = os.pidfd_open(process.pid, 0)
        try:
            from tests.support.asset_faults import process_identity

            cutoff = time.monotonic() + self.deadlines.allowance(2.0, self.phase)
            while True:
                require(time.monotonic() < cutoff and process.poll() is None)
                try:
                    identity = process_identity(process.pid, self.owner)
                except (FileNotFoundError, FixtureContractError):
                    time.sleep(min(0.01, max(0, cutoff - time.monotonic())))
                    continue
                if identity.command == tuple(command) and identity.pgid == process.pid:
                    break
                time.sleep(min(0.01, max(0, cutoff - time.monotonic())))
            owned = OwnedProcess(
                process,
                owner=self.owner,
                command=command,
                log=log,
                cutoff=self.deadlines.start + 94 * 60,
            )
            require(owned.identity == identity)
        finally:
            os.close(descriptor)
        self.launches.remove((process, log))
        owned.spec, owned.mode = spec, mode
        self.modes[process.pid] = owned
        return owned

    def stop_mode(self, owned, *, force=False, cleanup_cutoff=None):
        if owned.process.pid not in self.modes:
            owned.assert_settled()
            return
        if (
            owned.mode in {ProcessMode.API, ProcessMode.JOB_WORKER}
            and owned.process.poll() is None
        ):
            self.assert_helpers_settled(owned, cleanup_cutoff=cleanup_cutoff)
        if cleanup_cutoff is not None:
            require(time.monotonic() < cleanup_cutoff)
        owned.stop(force=force)
        if cleanup_cutoff is not None:
            require(time.monotonic() < cleanup_cutoff)
        require(owned.process.poll() is not None)
        self.modes.pop(owned.process.pid)
        if not force and owned.mode is ProcessMode.API:
            require(
                json.loads((owned.spec.control_path / "settled.json").read_bytes())
                == {"owner": self.owner, "settled": True}
            )

    def assert_helpers_settled(self, owned, *, cleanup_cutoff=None):
        path = owned.spec.control_path / "helpers.json"

        def settled():
            if not path.exists():
                return False
            value = json.loads(path.read_bytes())
            require(value["owner"] == self.owner)
            return value["pids"] == [] and value["complete"] is True

        if cleanup_cutoff is None:
            self.await_fact(settled, cap=3)
        else:
            self.await_owned_cleanup(settled, min(cleanup_cutoff, time.monotonic() + 3))

    def await_owned_cleanup(self, predicate, cutoff):
        native_float(cutoff)
        require(cutoff <= self.deadlines.start + 94 * 60)
        while time.monotonic() < cutoff:
            value = predicate()
            require(time.monotonic() < cutoff)
            if value:
                return value
            time.sleep(min(0.05, cutoff - time.monotonic()))
        raise FixtureDeadlineError()

    def run_mode(self, mode, *, spec=None, cap=35, limit=1):
        spec = spec or self.process_spec()
        owned = self.start_mode(mode, spec, argument=limit)
        self.await_fact(lambda: owned.process.poll() is not None, cap=cap)
        require(owned.process.returncode == 0)
        record = json.loads((spec.control_path / "result.json").read_bytes())
        require(record["owner"] == self.owner)
        record["process_identity"] = owned.identity
        self.stop_mode(owned)
        return record

    def install_namespace_and_keys(self):
        engine = create_engine(
            os.environ["WSO_TEST_MIGRATOR_DATABASE_URL"], hide_parameters=True
        )
        try:
            with engine.begin() as db:
                db.execute(
                    text(
                        "SELECT public.wso_install_asset_runtime_configuration(:id,:bucket)"
                    ),
                    {
                        "id": self.namespace.installation_id,
                        "bucket": self.namespace.bucket,
                    },
                )
        finally:
            engine.dispose()
        with self.admin.begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.asset_settings SET session_seconds=30,version=version+1 WHERE singleton"
                )
            )
            row = db.execute(
                text(
                    "SELECT installation_id,bucket FROM wso_private.asset_settings WHERE singleton"
                )
            ).one()
            require(
                tuple(row) == (self.namespace.installation_id, self.namespace.bucket)
            )
        for key in ("K1", "K2"):
            path = self.directory / key
            path.write_bytes(secrets.token_bytes(32))
            os.chmod(path, 0o600)
            self.key_files[key] = path.resolve()
        self.key_files = {"K1": self.key_files["K1"]}

    def query(self, sql, values=None):
        with self.admin.begin() as db:
            db.execute(text("SET LOCAL statement_timeout=5000"))
            return [dict(row) for row in db.execute(text(sql), values or {}).mappings()]

    def row(self, asset_id):
        return self.query(
            "SELECT a.*,u.id AS attempt_id,u.status AS upload_status,u.multipart_id,u.lease_expires_at,u.failure_code,u.remote_uncertain,u.remote_observed,u.completion_dispatched FROM public.assets a LEFT JOIN wso_private.asset_uploads u ON u.asset_id=a.id WHERE a.id=:id",
            {"id": UUID(str(asset_id))},
        )[0]

    def require_begin(self, data, **kwargs):
        self._upload_trial = min(33, getattr(self, "_upload_trial", 0) + 1)
        response = self._upload_exchange(
            "BEGIN",
            lambda: self.begin(data, **kwargs),
            actor=kwargs.get("actor"),
            expected=201,
        )
        require(response.status_code == 201)
        session = response.json()
        self.upload_sizes[session["id"]] = len(data)
        return session

    def metadata(self, asset_id, *, actor=None):
        actor = actor or self.actors[0]
        return self.request(
            "GET", f"/api/v1/assets/{asset_id}?tenant_id={actor.tenant_id}", actor=actor
        )

    def require_ticket(self, asset_id, *, actor=None):
        response = self.ticket(asset_id, actor=actor)
        require(response.status_code == 201)
        return response.json()

    def _upload_exchange(self, stage, operation, *, actor=None, expected=None):
        self._upload_stage, self._upload_started = stage, time.monotonic()
        actors = getattr(self, "actors", ())
        self._upload_actor = actor or (actors[0] if actors else None)
        try:
            response = operation()
        except BaseException:
            self.upload_diagnostic(None, expected=expected, caller="ERROR")
            raise
        self.upload_diagnostic(response, expected=expected)
        return response

    def upload_diagnostic(self, response, *, expected=None, caller="FINISHED"):
        """Bounded categorical evidence only; no request or response values escape."""
        count = getattr(self, "_upload_diagnostic_count", 0)
        if count >= 128:
            return
        self._upload_diagnostic_count = count + 1
        status = getattr(response, "status_code", None)
        code = "UNKNOWN"
        content = getattr(response, "content", b"")
        if type(content) is bytes and len(content) <= 8192:
            try:
                value = json.loads(content)
                candidate = value.get("error", {}).get("code")
                if type(candidate) is str and candidate in {
                    "ASSET_INTEGRITY",
                    "ASSET_LENGTH",
                    "ASSET_TYPE",
                    "ASSET_LIMIT",
                    "ASSET_UNAVAILABLE",
                    "ASSET_DEADLINE",
                    "ASSET_NOT_FOUND",
                    "ASSET_CONFLICT",
                    "ASSET_FORBIDDEN",
                }:
                    code = candidate
            except (ValueError, TypeError, AttributeError, RecursionError):
                pass
        now = time.monotonic()
        elapsed = max(0, now - getattr(self, "_upload_started", now))
        actor = getattr(self, "_upload_actor", None)
        expires = getattr(actor, "expires_at", None)
        remaining = (
            (expires - datetime.now(UTC)).total_seconds()
            if isinstance(expires, datetime) and expires.tzinfo
            else None
        )
        trial = getattr(self, "_upload_trial", 0)
        stage = getattr(self, "_upload_stage", "UNKNOWN")
        diagnostic = {
            "schema": 1,
            "trial": f"UPLOAD_{trial:02d}"
            if type(trial) is int and 1 <= trial <= 32
            else "OTHER",
            "stage": stage
            if type(stage) is str and stage in {"BEGIN", "PUT", "COMPLETE", "RECOVERY"}
            else "UNKNOWN",
            "expected": expected
            if type(expected) is int and 100 <= expected <= 599
            else "ABSENT",
            "actual": status
            if type(status) is int and 100 <= status <= 599
            else "ABSENT",
            "error_code": code,
            "disconnected": getattr(response, "disconnected", False) is True,
            "elapsed": "LT_1S"
            if elapsed < 1
            else "LE_30S"
            if elapsed <= 30
            else "LE_120S"
            if elapsed <= 120
            else "GT_120S",
            "session_remaining": "UNKNOWN"
            if remaining is None
            else "EXPIRED"
            if remaining <= 0
            else "LE_30S"
            if remaining <= 30
            else "LE_300S"
            if remaining <= 300
            else "GT_300S",
            "caller": caller
            if type(caller) is str and caller in {"FINISHED", "ERROR", "RUNNING"}
            else "UNKNOWN",
            "event_wait": False,
        }
        try:
            print(
                "WSO_ASSET_UPLOAD_DIAGNOSTIC=" + json.dumps(diagnostic, sort_keys=True)
            )
        except (OSError, ValueError):
            pass

    def assert_error(self, response, status, code=None):
        self.upload_diagnostic(response, expected=status)
        require(response.status_code == status)
        body = response.json()
        require(
            set(body) == {"error", "request_id"}
            and set(body["error"]) == {"code", "message"}
        )
        require(body["error"]["message"] == "Asset request failed")
        require(body["request_id"] is None or type(body["request_id"]) is str)
        if code is not None:
            require(body["error"]["code"] == code)
        require(response.headers["content-type"].split(";")[0] == "application/json")
        require(
            response.headers["cache-control"] == "no-store"
            and response.headers["vary"] == "Cookie"
        )

    def assert_no_image(self, response, status, code, *, asset_id):
        self.assert_error(response, status, code)
        require(self.event_count("DOWNLOAD_FIRST_CHUNK", asset_id) == 0)

    def event_count(self, name, asset_id):
        count = 0
        for owned in self.modes.values():
            event = owned.spec.control_path / "last-event.json"
            if event.exists():
                row = json.loads(event.read_bytes())
                count += row["event"] == name and row["id"] == str(asset_id)
        return count

    def assert_never_ready(self, asset_id):
        require(self.row(asset_id)["state"] != "READY")
        response = self.ticket(asset_id)
        require(response.status_code != 201)

    def raw_put(self, session, body, *, mode):
        from wso_api.auth import SESSION_COOKIE

        actor = self.actors[0]
        length = (
            self.upload_sizes[session["id"]] + 1
            if mode == "different-length"
            else self.upload_sizes[session["id"]]
        )
        if mode == "different-length":
            body = body + b"x"
        header = (
            f"PUT {session['upload_path']} HTTP/1.1\r\nHost: {urlsplit(self.base_url).netloc}\r\nCookie: {SESSION_COOKIE}={actor.token}\r\nOrigin: https://app.test\r\nX-CSRF-Token: {actor.csrf}\r\nX-Upload-Session: {session['id']}\r\nContent-Type: image/png\r\nContent-Length: {length}\r\nConnection: close\r\n\r\n"
        ).encode()
        return self._upload_exchange(
            "PUT",
            lambda: raw_http_exchange(
                self.base_url,
                header,
                (body,),
                time.monotonic() + self.deadlines.allowance(120.0, self.phase),
            ),
            actor=actor,
        )

    @staticmethod
    def assert_parser_disconnect(response):
        require(
            response.disconnected
            or response.status_code is not None
            and response.status_code >= 400
        )

    def wait_until_utc(self, boundary, *, cap):
        self.await_fact(
            lambda: datetime.now(UTC) > boundary + timedelta(seconds=1), cap=cap
        )

    def locator(self, asset):
        from wso_core.storage import ObjectLocator

        row = self.row(asset["id"] if isinstance(asset, dict) else asset)
        return ObjectLocator(
            self.namespace.installation_id,
            row["tenant_id"],
            row["id"],
            row["attempt_id"],
        )

    def raw_object(self, asset):
        from wso_core.storage import object_key

        body = self.access.clients["bootstrap"].get_object(
            Bucket=self.provider.bucket, Key=object_key(self.locator(asset))
        )["Body"]
        try:
            data = body.read(20971520 + 37)
            require(len(data) <= 20971520 + 36)
            return data
        finally:
            body.close()

    def physical_inventory(self):
        client = self.access.clients["bootstrap"]
        objects, uploads = {}, {}
        token, markers, seen = None, {}, set()
        for _ in range(128):
            response = client.list_objects_v2(
                Bucket=self.provider.bucket,
                Prefix=self.provider.prefix,
                MaxKeys=1,
                **({"ContinuationToken": token} if token else {}),
            )
            for row in response.get("Contents", []):
                require(row["Key"] not in objects)
                objects[row["Key"]] = (row["Size"], row["LastModified"])
            if not response.get("IsTruncated"):
                break
            token = response["NextContinuationToken"]
            require(token and token not in seen)
            seen.add(token)
        else:
            raise RuntimeError("owned object inventory bound")
        seen.clear()
        for _ in range(128):
            response = client.list_multipart_uploads(
                Bucket=self.provider.bucket,
                Prefix=self.provider.prefix,
                MaxUploads=1,
                **markers,
            )
            for row in response.get("Uploads", []):
                identity = (row["Key"], row["UploadId"])
                require(identity not in uploads)
                uploads[identity] = row["Initiated"]
            if not response.get("IsTruncated"):
                break
            markers = {
                "KeyMarker": response["NextKeyMarker"],
                "UploadIdMarker": response["NextUploadIdMarker"],
            }
            pair = tuple(markers.values())
            require(all(pair) and pair not in seen)
            seen.add(pair)
        else:
            raise RuntimeError("owned multipart inventory bound")
        return objects, uploads

    def assert_physical_absence(self, asset):
        from wso_core.storage import object_key

        key = object_key(self.locator(asset))
        objects, uploads = self.physical_inventory()
        require(key not in objects and not any(k == key for k, _ in uploads))

    def assert_deleted(self, asset):
        require(self.row(asset["id"])["state"] == "DELETED")
        self.assert_physical_absence(asset)

    def cleanup_success_count(self, asset_id):
        return self.query(
            "SELECT count(*) AS n FROM public.audit_events WHERE entity_id=:id AND action='ASSET_CLEANUP_SUCCESS'",
            {"id": UUID(str(asset_id))},
        )[0]["n"]

    def drain_cleanup(self, ids, cutoff):
        def done():
            self.run_mode(
                ProcessMode.MAINTENANCE,
                limit=100,
                cap=min(180, cutoff - time.monotonic()),
            )
            return all(self.row(value)["state"] == "DELETED" for value in ids)

        cap = min(180, cutoff - time.monotonic())
        require(cap > 0)
        self.await_fact(done, cap=cap)
        for value in ids:
            self.assert_physical_absence({"id": value})
            require(self.cleanup_success_count(value) == 1)

    def erase(self, *assets, actor=None, key_free=False):
        if key_free:
            self.stop_current_api()
        for asset in assets:
            if not key_free:
                response = self.delete(asset["id"], actor=actor)
                require(response.status_code == 202)
            else:
                # Tombstone through normal authorized API before retiring keys.
                self.start_api()
                require(self.delete(asset["id"], actor=actor).status_code == 202)
                self.stop_current_api()
        self.drain_cleanup(
            [a["id"] for a in assets],
            time.monotonic() + self.deadlines.allowance(180.0, self.phase),
        )
        if key_free:
            self.start_api()

    def recover_rejected(self, session, *, natural_expiry=False):
        return self._upload_exchange(
            "RECOVERY",
            lambda: self._recover_rejected(session, natural_expiry=natural_expiry),
        )

    def _recover_rejected(self, session, *, natural_expiry=False):
        row = self.row(session["asset_id"])
        if natural_expiry or row["state"] == "PENDING":
            self.wait_until_utc(datetime.fromisoformat(session["expires_at"]), cap=180)
        if row["lease_expires_at"] is not None:
            self.wait_until_utc(
                row["lease_expires_at"] + timedelta(seconds=10), cap=180
            )
        if row["state"] == "READY":
            require(self.delete(session["asset_id"]).status_code == 202)
        # Real normal reconciliation recovers unrecorded create/part gaps. These
        # transient populations are deliberately outside the fixed aging epochs.
        for _ in range(64):
            self.run_mode(ProcessMode.RECONCILE, limit=1)
            if all(value is None for value in self.cursor_state().values()):
                break
        else:
            raise RuntimeError("transient reconciliation bound")
        self.drain_cleanup(
            [session["asset_id"]],
            time.monotonic() + self.deadlines.allowance(180.0, self.phase),
        )

    def stop_current_api(self, *, force=False):
        if self.process is not None:
            owned = self.modes.get(self.process.pid)
            if owned is not None:
                self.stop_mode(owned, force=force)
            else:
                self.stop_api()
            self.process, self.log = None, None

    def restart_api(self, *, keys=None, active=None, endpoint=None):
        self.stop_current_api()
        if keys is not None:
            self.key_files = {k: (self.directory / k).resolve() for k in keys}
        if active is not None:
            self.active_key = active
        self.start_api()
        if endpoint is not None:
            self.stop_current_api()
            self.api_spec = self.process_spec(endpoint=endpoint)
            owned = self.start_mode(ProcessMode.API, self.api_spec)
            self.process, self.log, self.command = (
                owned.process,
                owned.log,
                list(owned.command),
            )
            self.await_fact(
                lambda: (
                    self.request("GET", "/health/live", authenticated=False).status_code
                    == 200
                ),
                cap=30,
            )

    @contextmanager
    def policy(self, **changes):
        allowed = {
            "max_bytes",
            "max_dimension",
            "max_pixels",
            "max_frames",
            "session_seconds",
            "retention_seconds",
        }
        require(
            set(changes) <= allowed
            and all(type(v) is int and v > 0 for v in changes.values())
        )
        self.stop_current_api()
        original = self.query(
            "SELECT * FROM wso_private.asset_settings WHERE singleton"
        )[0]

        def change(values):
            with self.admin.begin() as db:
                db.execute(
                    text(
                        "UPDATE wso_private.asset_settings SET "
                        + ",".join(f"{k}=:{k}" for k in values)
                        + ",version=version+1 WHERE singleton"
                    ),
                    values,
                )

        change(changes)
        self.start_api()
        try:
            yield
        finally:
            self.stop_current_api()
            change({k: original[k] for k in changes})
            self.start_api()

    def same_user_session(self):
        return self.new_actor(
            tenant_id=self.actors[0].tenant_id, user_id=self.actors[0].user_id
        )

    def same_tenant_actor(self):
        return self.new_actor(tenant_id=self.actors[0].tenant_id)

    def revoke_session(self, actor):
        from sqlalchemy.orm import sessionmaker
        from wso_api.auth import PostgresSessionStore, token_digest

        engine = create_engine(
            os.environ["WSO_TEST_SESSION_DATABASE_URL"], hide_parameters=True
        )
        try:
            store = PostgresSessionStore(
                os.environ["WSO_TEST_SESSION_DATABASE_URL"],
                session_factory=sessionmaker(engine),
            )
            require(store.revoke(token_digest(actor.token), token_digest(actor.csrf)))
        finally:
            engine.dispose()

    def revoke_asset_authority(self, actor):
        """R45: revoke current OWNER authority, retaining membership and audit."""
        values = {"t": actor.tenant_id, "u": actor.user_id}
        audit_sql = "SELECT * FROM public.audit_events WHERE tenant_id=:t AND actor_user_id=:u ORDER BY id"
        before = self.query(audit_sql, values)
        require(before)
        with self.admin.begin() as db:
            changed = db.execute(
                text(
                    "UPDATE public.memberships SET role='STAFF' WHERE tenant_id=:t AND user_id=:u AND role='OWNER'"
                ),
                values,
            )
            require(changed.rowcount == 1)
        require(self.query(audit_sql, values) == before)
        require(
            self.query(
                "SELECT role FROM public.memberships WHERE tenant_id=:t AND user_id=:u",
                values,
            )
            == [{"role": "STAFF"}]
        )
        require(self.request("GET", "/api/v1/me", actor=actor).status_code == 200)
        require(
            self.request(
                "GET", f"/api/v1/connections?tenant_id={actor.tenant_id}", actor=actor
            ).status_code
            == 403
        )
        require(self.begin(self.image(), actor=actor).status_code == 403)

    def revoke_membership(self, actor):
        """Legacy actual14 caller spelling; R45 means asset authority revocation."""
        self.revoke_asset_authority(actor)

    def assert_no_stores(self):
        require(
            self.query(
                "SELECT count(*) AS n FROM stores WHERE tenant_id IN (:a,:b)",
                {"a": self.actors[0].tenant_id, "b": self.actors[1].tenant_id},
            )[0]["n"]
            == 0
        )

    def assert_role_logins(self):
        # Desired restricted flags are literal provisioner expectations, never observations.
        for name, expected in ROLES.items():
            cutoff = time.monotonic() + self.deadlines.allowance(
                5.0, FixturePhase.SETUP
            )
            engine = create_engine(
                os.environ[f"WSO_TEST_{name}_DATABASE_URL"],
                hide_parameters=True,
                connect_args={
                    "connect_timeout": max(1, min(5, int(cutoff - time.monotonic())))
                },
            )
            try:
                with engine.connect() as db:
                    db.execute(text("SET LOCAL statement_timeout=5000"))
                    row = db.execute(
                        text(
                            "SELECT current_user AS actor, r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls,r.rolinherit,r.rolcanlogin,(SELECT count(*) FROM pg_auth_members m WHERE m.member=r.oid OR m.roleid=r.oid) AS memberships FROM pg_roles r WHERE r.rolname=current_user"
                        )
                    ).one()
                    require(row.actor == expected)
                    if name == "ADMIN":
                        require(
                            row.rolsuper is True
                            and row.rolcanlogin is True
                            and row.memberships == 0
                            and all(type(flag) is bool for flag in tuple(row)[1:8])
                        )
                    else:
                        require(
                            tuple(row)[1:]
                            == (False, False, False, False, False, False, True, 0)
                        )
                    require(time.monotonic() < cutoff)
            finally:
                engine.dispose()
            require(time.monotonic() < cutoff)

    def prepare_case(self):
        self.deadlines.check(self.phase)
        self._upload_trial, self._upload_diagnostic_count = 0, 0
        for index in (0, 1):
            actor = self.actors[index]
            if actor.expires_at is None or actor.expires_at <= datetime.now(
                UTC
            ) + timedelta(minutes=5):
                self.actors[index] = self.new_actor(
                    tenant_id=actor.tenant_id, user_id=actor.user_id
                )

    def control_for(self, owned=None):
        owned = owned or self.modes[self.process.pid]
        return BarrierControl(owned.spec.control_path, self.owner)

    def wait_event(self, control, cutoff, call):
        try:
            return control.wait(cutoff)
        except BaseException:
            diagnostic = {
                "schema": 1,
                "event_wait": True,
                "caller": "RUNNING"
                if not call.done.is_set()
                else "ERROR"
                if call.error is not None
                else "FINISHED",
                "cutoff_expired": time.monotonic() >= cutoff,
            }
            try:
                print(
                    "WSO_ASSET_EVENT_DIAGNOSTIC="
                    + json.dumps(diagnostic, sort_keys=True)
                )
            except (OSError, ValueError):
                pass
            raise

    def call(self, function, *, cap, release=None):
        call = OwnedCall(
            function,
            time.monotonic() + self.deadlines.allowance(float(cap), self.phase),
            release,
        )
        self.callers.append(call)
        return call

    @contextmanager
    def paused_upload(self, session, data, *, after):
        require(type(after) is int and 0 < after < len(data))
        released, reached = threading.Event(), threading.Event()
        cutoff = time.monotonic() + self.deadlines.allowance(120.0, self.phase)

        def body():
            yield data[:after]
            reached.set()
            require(
                released.wait(max(0, cutoff - time.monotonic()))
                and time.monotonic() < cutoff
            )
            yield data[after:]

        call = self.call(
            lambda: self.put(session, body()), cap=120, release=released.set
        )
        try:
            require(reached.wait(max(0, cutoff - time.monotonic())))
            yield call
        finally:
            call.close()
            self.callers.remove(call)

    def wait_parts(self, session):
        from wso_core.storage import object_key

        key = object_key(self.locator(session["asset_id"]))

        def parts():
            row = self.row(session["asset_id"])
            if not row["multipart_id"]:
                return None
            response = self.access.clients["bootstrap"].list_parts(
                Bucket=self.provider.bucket,
                Key=key,
                UploadId=row["multipart_id"],
                MaxParts=100,
            )
            return response.get("Parts")

        return self.await_fact(parts, cap=10)

    def envelope_snapshot(self, asset):
        row = self.query(
            "SELECT key_id,wrapped_dek,wrap_nonce,object_nonce FROM wso_private.asset_uploads WHERE asset_id=:id",
            {"id": UUID(asset["id"])},
        )[0]
        return {
            name: bytes(value) if name != "key_id" else value
            for name, value in row.items()
        }

    @staticmethod
    def assert_not_image(data):
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(io.BytesIO(data)):
                raise RuntimeError("stored image was not encrypted")
        except UnidentifiedImageError:
            pass

    def clear_events(self):
        for owned in self.modes.values():
            (owned.spec.control_path / "last-event.json").unlink(missing_ok=True)

    @contextmanager
    def wrong_key(self, name):
        require(name in {"K1", "K2"})
        self.stop_current_api()
        path = self.directory / name
        original = path.read_bytes()
        require(len(original) == 32)
        path.write_bytes(secrets.token_bytes(32))
        os.chmod(path, 0o600)
        try:
            yield
        finally:
            self.stop_current_api()
            path.write_bytes(original)
            os.chmod(path, 0o600)
            self.start_api()

    @contextmanager
    def corruption(self, asset, trial, *, donor):
        from wso_core.storage import object_key

        require(
            trial
            in {"wrong-key", "tag", "magic", "nonce", "truncate", "other-envelope"}
        )
        original, envelope = self.raw_object(asset), self.envelope_snapshot(asset)
        key = object_key(self.locator(asset))
        client = self.access.clients["bootstrap"]
        self.stop_current_api()
        original_key = None
        try:
            if trial == "wrong-key":
                path = self.directory / envelope["key_id"]
                original_key = path.read_bytes()
                path.write_bytes(secrets.token_bytes(32))
            elif trial == "other-envelope":
                values = self.envelope_snapshot(donor)
                with self.admin.begin() as db:
                    db.execute(
                        text(
                            "UPDATE wso_private.asset_uploads SET wrapped_dek=:dek,wrap_nonce=:nonce WHERE asset_id=:id"
                        ),
                        {
                            "dek": values["wrapped_dek"],
                            "nonce": values["wrap_nonce"],
                            "id": UUID(asset["id"]),
                        },
                    )
            else:
                value = bytearray(original)
                if trial == "truncate":
                    value = value[:-1]
                else:
                    value[{"tag": -1, "magic": 0, "nonce": 8}[trial]] ^= 1
                client.put_object(
                    Bucket=self.provider.bucket, Key=key, Body=bytes(value)
                )
            self.start_api()
            self.clear_events()
            yield
        finally:
            self.stop_current_api()
            if original_key is not None:
                (self.directory / envelope["key_id"]).write_bytes(original_key)
            client.put_object(Bucket=self.provider.bucket, Key=key, Body=original)
            with self.admin.begin() as db:
                db.execute(
                    text(
                        "UPDATE wso_private.asset_uploads SET wrapped_dek=:dek,wrap_nonce=:nonce WHERE asset_id=:id"
                    ),
                    {
                        "dek": envelope["wrapped_dek"],
                        "nonce": envelope["wrap_nonce"],
                        "id": UUID(asset["id"]),
                    },
                )
            self.start_api()

    def assert_evidence_unsupported(self, data):
        before = self.asset_count()
        require(self.begin(data, purpose="EVIDENCE").status_code in {403, 422})
        require(self.asset_count() == before)

    def prove_runtime_authority_denials(self, asset):
        from sqlalchemy.exc import DBAPIError

        before = self.row(asset["id"])
        for role in ("APP", "JOB", "DISPATCH", "WORKER", "ASSET_MAINTENANCE"):
            engine = create_engine(
                os.environ[f"WSO_TEST_{role}_DATABASE_URL"],
                hide_parameters=True,
                connect_args={"connect_timeout": 5},
            )
            try:
                for statement in (
                    "SELECT * FROM wso_private.asset_uploads",
                    "UPDATE wso_private.asset_settings SET version=version+1",
                    "UPDATE public.assets SET state='DELETED' WHERE id=:id",
                ):
                    with engine.connect() as db:
                        transaction = db.begin()
                        try:
                            db.execute(text("SET LOCAL statement_timeout=5000"))
                            db.execute(
                                text(
                                    "SELECT set_config('wso.user_id',:id,true),set_config('wso.tenant_id',:tenant,true)"
                                ),
                                {
                                    "id": str(self.actors[0].user_id),
                                    "tenant": str(self.actors[0].tenant_id),
                                },
                            )
                            db.execute(text(statement), {"id": UUID(asset["id"])})
                        except DBAPIError as error:
                            require(getattr(error.orig, "sqlstate", None) == "42501")
                        else:
                            raise RuntimeError("runtime asset authority expanded")
                        finally:
                            transaction.rollback()
            finally:
                engine.dispose()
        require(self.row(asset["id"]) == before)
        staff = self.new_actor(tenant_id=self.actors[0].tenant_id)
        with self.admin.begin() as db:
            db.execute(
                text(
                    "UPDATE public.memberships SET role='STAFF' WHERE tenant_id=:tenant AND user_id=:user"
                ),
                {"tenant": staff.tenant_id, "user": staff.user_id},
            )
        require(
            self.request(
                "DELETE",
                f"/api/v1/assets/{asset['id']}?tenant_id={staff.tenant_id}",
                actor=staff,
                headers={"X-Role": "OWNER", "X-User-Id": str(self.actors[0].user_id)},
            ).status_code
            == 403
        )
        self.assert_error(
            self.request(
                "GET",
                f"/api/v1/assets/{asset['id']}?tenant_id={self.actors[1].tenant_id}",
                actor=self.actors[1],
                headers={
                    "X-Role": "OWNER",
                    "X-Tenant-Id": str(self.actors[0].tenant_id),
                },
            ),
            404,
        )
        expired = self.new_actor(
            tenant_id=self.actors[0].tenant_id,
            user_id=self.actors[0].user_id,
            expires_seconds=2,
        )
        self.wait_until_utc(expired.expires_at, cap=5)
        require(self.metadata(asset["id"], actor=expired).status_code == 401)
        require(self.row(asset["id"]) == before)

    def create_stores(self, count):
        require(type(count) is int and 1 <= count <= 2)
        identifiers = [uuid4() for _ in range(count)]
        with self.admin.begin() as db:
            for identifier in identifiers:
                db.execute(
                    text(
                        "INSERT INTO public.stores(id,tenant_id,name,timezone) VALUES(:id,:tenant,'asset-fixture','Asia/Seoul')"
                    ),
                    {"id": identifier, "tenant": self.actors[0].tenant_id},
                )
        return identifiers

    def asset_count(self):
        return self.query("SELECT count(*) AS n FROM public.assets")[0]["n"]

    def ready_child_count(self, parent):
        return self.query(
            "SELECT count(*) AS n FROM public.assets WHERE parent_asset_id=:id AND state='READY'",
            {"id": UUID(parent)},
        )[0]["n"]

    def prove_invalid_parents(self, parent, child, *, other_store):
        data = self.image()
        pending = self.require_begin(data, store_id=parent["store_id"])
        before = self.asset_count()
        for kwargs in (
            {"parent_asset_id": pending["asset_id"], "store_id": parent["store_id"]},
            {"parent_asset_id": child["id"], "store_id": parent["store_id"]},
            {"parent_asset_id": parent["id"], "store_id": other_store},
            {
                "parent_asset_id": parent["id"],
                "store_id": parent["store_id"],
                "actor": self.actors[1],
            },
        ):
            require(
                self.begin(data, purpose="IMPORT_CROP", **kwargs).status_code
                in {404, 409, 422}
            )
            require(self.asset_count() == before)
        self.recover_rejected(pending)
        failed = self.require_begin(data)
        wrong = data[:-1] + bytes([data[-1] ^ 1])
        self.assert_error(self.put(failed, wrong), 422, "ASSET_INTEGRITY")
        require(self.row(failed["asset_id"])["state"] == "REJECTED")
        before = self.asset_count()
        require(
            self.begin(
                data, purpose="IMPORT_CROP", parent_asset_id=failed["asset_id"]
            ).status_code
            in {404, 409, 422}
        )
        require(self.asset_count() == before)
        self.recover_rejected(failed)

    def natural_parent_expiry_trial(self):
        with self.policy(retention_seconds=30):
            parent = self.upload(self.image())
            boundary = datetime.fromisoformat(parent["expires_at"])
            self.wait_until_utc(boundary, cap=35)
            before = self.asset_count()
            require(
                self.begin(
                    self.image(), purpose="IMPORT_CROP", parent_asset_id=parent["id"]
                ).status_code
                in {404, 409, 410}
            )
            require(self.asset_count() == before)
            self.drain_cleanup(
                [parent["id"]],
                time.monotonic() + self.deadlines.allowance(180.0, self.phase),
            )

    def jobs(self):
        from tests.support.asset_broker import AssetJobs

        require(self.jobs_context is None)
        self.jobs_context = AssetJobs(self)
        return self.jobs_context

    def adapter_action(self, asset, action):
        from tests.support.asset_faults import snapshot_json as private_json

        spec, locator = self.process_spec(), self.locator(asset)
        private_json(
            spec.control_path / "adapter.json",
            {
                "owner": self.owner,
                "cutoff": time.monotonic()
                + self.deadlines.allowance(120.0, self.phase),
                **{
                    name: str(getattr(locator, name))
                    for name in (
                        "installation_id",
                        "tenant_id",
                        "asset_id",
                        "attempt_id",
                    )
                },
                "probe_asset": str(uuid4()),
                "probe_attempt": str(uuid4()),
                "direct_probe_asset": str(uuid4()),
                "direct_probe_attempt": str(uuid4()),
            },
        )
        owned = self.start_mode(ProcessMode.API, spec, argument=action)
        self.await_fact(lambda: owned.process.poll() is not None, cap=120)
        if owned.process.returncode != 0:
            from tests.support.asset_process import read_adapter_failure

            print(
                "WSO_ASSET_ADAPTER_DIAGNOSTIC="
                + json.dumps(read_adapter_failure(spec.control_path), sort_keys=True)
            )
        require(owned.process.returncode == 0)
        result = json.loads((spec.control_path / "adapter-result.json").read_bytes())
        require(result["owner"] == self.owner)
        owned.stop()
        self.modes.pop(owned.process.pid)
        if action == "adapter":
            data = json.loads((spec.control_path / "adapter.json").read_bytes())
            maintenance_spec = self.process_spec()
            private_json(maintenance_spec.control_path / "adapter.json", data)
            remaining = data["cutoff"] - time.monotonic()
            require(remaining > 0)
            deleted = self.run_mode(
                ProcessMode.MAINTENANCE,
                spec=maintenance_spec,
                cap=remaining,
                limit="adapter-delete",
            )
            require(
                deleted["result"]
                == {"deleted": True, "identity": "wso_asset_maintenance"}
                and time.monotonic() < data["cutoff"]
            )
        return result

    def exercise_normal_adapter(self, asset):
        require(
            self.adapter_action(asset, "adapter")
            == {"owner": self.owner, "accepted": True}
        )
        self.assert_foreign_preserved()

    def exercise_presign(self, asset, *, expires_seconds):
        require(expires_seconds == 1)
        result = self.adapter_action(asset, "presign")
        parsed = urlsplit(result["url"])
        require(
            parsed.scheme == "http"
            and parsed.netloc == urlsplit(self.provider.endpoint).netloc
        )
        expected = hashlib.sha256(self.raw_object(asset)).digest()
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = client.get(result["url"])
            require(
                response.status_code == 200
                and hashlib.sha256(response.content).digest() == expected
            )
        from urllib.parse import parse_qs

        date = parse_qs(parsed.query)["X-Amz-Date"][0]
        boundary = datetime.strptime(date, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=UTC
        ) + timedelta(seconds=1)
        # Every stream and SDK pool is closed before the real expiry wait.
        self.access.close()
        self.access = None
        self.wait_until_utc(boundary, cap=5)
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            require(client.get(result["url"]).status_code == 403)
        self.fresh_runtime_access(self.phase)

    def assert_anonymous_and_maintenance_denials(self, asset):
        from botocore.exceptions import ClientError
        from wso_core.storage import object_key

        path = f"/{self.provider.bucket}/{object_key(self.locator(asset))}"
        expected = self.raw_object(asset)
        with httpx.Client(
            base_url=self.provider.endpoint,
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            for method in ("GET", "HEAD"):
                require(client.request(method, path).status_code == 403)
        for method in ("get_object", "head_object"):
            try:
                value = getattr(self.access.clients["cleanup"], method)(
                    Bucket=self.provider.bucket, Key=object_key(self.locator(asset))
                )
                if "Body" in value:
                    value["Body"].close()
            except ClientError as error:
                status, code = (
                    error.response["ResponseMetadata"]["HTTPStatusCode"],
                    error.response["Error"]["Code"],
                )
                require(
                    status == 403
                    and code
                    in (
                        {"AccessDenied", "403"}
                        if method == "head_object"
                        else {"AccessDenied"}
                    )
                )
            else:
                raise RuntimeError("maintenance ciphertext read accepted")
        before_inventory = self.physical_inventory()
        anonymous_key = object_key(self.seed_locator())
        with httpx.Client(
            base_url=self.provider.endpoint,
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            require(
                client.get(
                    "/" + self.provider.bucket,
                    params={
                        "list-type": "2",
                        "prefix": self.provider.prefix,
                        "max-keys": "1",
                    },
                ).status_code
                == 403
            )
            require(
                client.put(
                    "/" + self.provider.bucket + "/" + anonymous_key,
                    content=b"denied-owned-probe",
                ).status_code
                == 403
            )
        require(
            self.physical_inventory() == before_inventory
            and self.raw_object(asset) == expected
        )

    def assert_maintenance_no_read(self):
        from tests.support.asset_faults import snapshot_json as private_json

        spec = self.process_spec()
        locator = self.locator(self.survivor["asset"])
        private_json(
            spec.control_path / "no-read.json",
            {
                "owner": self.owner,
                "installation_id": str(locator.installation_id),
                "tenant_id": str(locator.tenant_id),
                "asset_id": str(locator.asset_id),
                "attempt_id": str(locator.attempt_id),
                "cutoff": time.monotonic() + self.deadlines.allowance(10.0, self.phase),
            },
        )
        record = self.run_mode(
            ProcessMode.MAINTENANCE, spec=spec, cap=10, limit="no-read"
        )
        require(record["result"] == {"no_read": True} and record["pages"] == [])
        self.assert_anonymous_and_maintenance_denials(self.survivor["asset"])

    @contextmanager
    def fault(self, selector, mode):
        cutoff = time.monotonic() + self.deadlines.allowance(60.0, self.phase)
        gate = FaultRelay(
            self.provider.endpoint, self.owner, self.access.assert_mapping, cutoff
        )
        gate.__enter__()
        self.faults.append(gate)
        try:
            gate.arm(selector, mode)
            yield gate
        finally:
            gate.close()
            self.faults.remove(gate)

    def gateway_crash_trial(self, position):
        data = self.large_image() if position == "uploaded-part" else self.image()
        session = self.require_begin(data)
        if position == "uploaded-part":
            with self.paused_upload(session, data, after=6291456) as call:
                require(self.wait_parts(session))
                self.assert_helpers_settled(self.modes[self.process.pid])
                self.stop_current_api(force=True)
                call.release()
                call.result(error_allowed=True)
        else:
            control = self.control_for()
            control.reset()
            cutoff = time.monotonic() + self.deadlines.allowance(10.0, self.phase)
            control.arm(position, asset_id=UUID(session["asset_id"]), cutoff=cutoff)
            if position == "VALIDATED_BEFORE_FINALIZE":
                require(self.put(session, data).status_code == 204)
                call = self.call(lambda: self.complete(session["asset_id"]), cap=30)
            else:
                call = self.call(lambda: self.put(session, data), cap=120)
            try:
                self.wait_event(control, cutoff, call)
                self.assert_helpers_settled(self.modes[self.process.pid])
                self.stop_current_api(force=True)
                call.result(error_allowed=True)
            finally:
                call.close()
                self.callers.remove(call)
        require(self.process is None)
        self.start_api()
        self.assert_never_ready(session["asset_id"])
        self.recover_rejected(session)

    def live_helper_crash_trial(self, operation, hold):
        require(operation in {"CREATE_MULTIPART", "UPLOAD_PART", "COMPLETE_MULTIPART"})
        data = self.large_image()
        session = self.require_begin(data)
        locator = self.locator(session["asset_id"])
        # A real create-response hold obtains the actual opaque ID before the
        # API records it. No guessed upload identity or substitute SDK is used.
        create = S3FaultSelector(S3Operation.CREATE_MULTIPART, self.namespace, locator)
        with self.fault(
            create,
            FaultMode.HOLD_RESPONSE if operation == "UPLOAD_PART" else FaultMode(hold),
        ) as gate:
            self.restart_api(endpoint=gate.endpoint)
            if operation == "COMPLETE_MULTIPART":
                with self.paused_upload(session, data, after=6291456) as call:
                    gate.wait_match(time.monotonic() + 5)
                    gate.release()
                    require(self.wait_parts(session))
                    self.await_fact(lambda: not gate.snapshot()["active"], cap=3)
                    upload = self.row(session["asset_id"])["multipart_id"]
                    gate.arm(
                        S3FaultSelector(
                            S3Operation.COMPLETE_MULTIPART,
                            self.namespace,
                            locator,
                            upload_id=upload,
                        ),
                        FaultMode(hold),
                    )
                    call.release()
                    self.kill_matched_helper(gate)
                    call.result(error_allowed=True)
            elif operation == "UPLOAD_PART":
                with self.paused_upload(session, data, after=32) as call:
                    gate.wait_match(time.monotonic() + 5)
                    from wso_core.storage import object_key

                    def observed_upload():
                        _, uploads = self.physical_inventory()
                        ids = [
                            upload
                            for key, upload in uploads
                            if key == object_key(locator)
                        ]
                        require(len(ids) <= 1)
                        return ids[0] if ids else None

                    upload = self.await_fact(observed_upload, cap=3)
                    gate.release()
                    self.await_fact(lambda: not gate.snapshot()["active"], cap=3)
                    gate.arm(
                        S3FaultSelector(
                            S3Operation.UPLOAD_PART,
                            self.namespace,
                            locator,
                            upload_id=upload,
                            part_number=1,
                        ),
                        FaultMode(hold),
                    )
                    call.release()
                    self.kill_matched_helper(gate)
                    call.result(error_allowed=True)
            else:
                call = self.call(lambda: self.put(session, data), cap=120)
                try:
                    self.kill_matched_helper(gate)
                    call.result(error_allowed=True)
                finally:
                    call.close()
                    self.callers.remove(call)
            self.assert_helpers_settled(self.modes[self.process.pid])
            self.stop_current_api()
        self.start_api()
        self.assert_never_ready(session["asset_id"])
        self.recover_rejected(session)

    def kill_matched_helper(self, gate):
        from tests.support.asset_faults import snapshot_json as private_json

        gate.wait_match(time.monotonic() + self.deadlines.allowance(5.0, self.phase))
        snapshot = gate.snapshot()
        require(snapshot["matched"] and snapshot["active"])
        path = self.modes[self.process.pid].spec.control_path

        def observed_helper():
            record = json.loads((path / "helpers.json").read_bytes())
            require(record["owner"] == self.owner and len(record["pids"]) <= 1)
            return record if len(record["pids"]) == 1 else None

        self.await_fact(observed_helper, cap=3)
        private_json(path / "kill-helper.json", {"owner": self.owner, "kill": True})
        self.await_fact(lambda: not (path / "kill-helper.json").exists(), cap=3)
        gate.release()
        self.assert_helpers_settled(self.modes[self.process.pid])

    def delete_during_complete_trial(self, position):
        data = self.image()
        session = self.require_begin(data)
        asset = {"id": session["asset_id"]}
        if position == "callback":
            control = self.control_for()
            control.reset()
            cutoff = time.monotonic() + self.deadlines.allowance(10.0, self.phase)
            control.arm(
                "OBJECT_COMPLETED_BEFORE_SEAL",
                asset_id=UUID(asset["id"]),
                cutoff=cutoff,
            )
            call = self.call(lambda: self.put(session, data), cap=120)
            try:
                record = self.wait_event(control, cutoff, call)
                require(self.raw_object(asset))
                require(self.delete(asset["id"]).status_code == 202)
                control.release(record)
                response = call.result()
                require(response.status_code >= 400)
            finally:
                call.close()
                self.callers.remove(call)
                control.reset()
        else:
            with self.fault(
                S3FaultSelector(
                    S3Operation.CREATE_MULTIPART, self.namespace, self.locator(asset)
                ),
                FaultMode.HOLD_RESPONSE,
            ) as gate:
                self.restart_api(endpoint=gate.endpoint)
                with self.paused_upload(session, data, after=32) as call:
                    gate.wait_match(time.monotonic() + 5)
                    from wso_core.storage import object_key

                    _, uploads = self.physical_inventory()
                    ids = [
                        u
                        for key, u in uploads
                        if key == object_key(self.locator(asset))
                    ]
                    require(len(ids) == 1)
                    gate.release()
                    self.await_fact(lambda: not gate.snapshot()["active"], cap=3)
                    gate.arm(
                        S3FaultSelector(
                            S3Operation.COMPLETE_MULTIPART,
                            self.namespace,
                            self.locator(asset),
                            upload_id=ids[0],
                        ),
                        FaultMode.HOLD_RESPONSE,
                    )
                    call.release()
                    gate.wait_match(time.monotonic() + 5)
                    self.await_fact(
                        lambda: bool(
                            self.physical_inventory()[0].get(
                                object_key(self.locator(asset))
                            )
                        ),
                        cap=5,
                    )
                    require(self.delete(asset["id"]).status_code == 202)
                    gate.release()
                    require(call.result().status_code >= 400)
                self.stop_current_api()
            self.start_api()
        require(self.row(asset["id"])["state"] != "READY")
        self.recover_rejected(session)

    def absence_only_uncertainty_trial(self):
        data = self.image()
        session = self.require_begin(data)
        asset = {"id": session["asset_id"]}
        with self.fault(
            S3FaultSelector(
                S3Operation.CREATE_MULTIPART, self.namespace, self.locator(asset)
            ),
            FaultMode.HOLD_RESPONSE,
        ) as gate:
            self.restart_api(endpoint=gate.endpoint)
            with self.paused_upload(session, data, after=32) as call:
                gate.wait_match(time.monotonic() + 5)
                from wso_core.storage import object_key

                _, uploads = self.physical_inventory()
                ids = [
                    u for key, u in uploads if key == object_key(self.locator(asset))
                ]
                require(len(ids) == 1)
                gate.release()
                self.await_fact(lambda: not gate.snapshot()["active"], cap=3)
                gate.arm(
                    S3FaultSelector(
                        S3Operation.COMPLETE_MULTIPART,
                        self.namespace,
                        self.locator(asset),
                        upload_id=ids[0],
                    ),
                    FaultMode.RESET_BEFORE_FORWARD,
                )
                call.release()
                gate.wait_match(time.monotonic() + 5)
                response = call.result(error_allowed=True)
                require(response is None or response.status_code >= 400)
                require(
                    gate.snapshot()["forwarded"] == 0
                    and gate.snapshot()["dispatches"] == 0
                )
            self.stop_current_api()
        self.start_api()
        row = self.row(asset["id"])
        require(
            row["completion_dispatched"]
            and row["remote_uncertain"]
            and not row["remote_observed"]
        )
        require(self.delete(asset["id"]).status_code == 202)
        if row["lease_expires_at"]:
            self.wait_until_utc(
                row["lease_expires_at"] + timedelta(seconds=10), cap=180
            )
        for _ in range(2):
            self.run_mode(ProcessMode.MAINTENANCE, limit=100)
        self.assert_physical_absence(asset)
        row = self.row(asset["id"])
        require(
            row["state"] == "DELETING"
            and row["remote_uncertain"]
            and not row["remote_observed"]
        )
        require(self.cleanup_success_count(asset["id"]) == 0)
        self.conservative.add(asset["id"])

    def cleanup_transport_failure_trial(self, asset, operation):
        from wso_core.asset_s3_worker import _multipart_page_limit

        op = S3Operation(operation)
        selector = S3FaultSelector(
            op,
            self.namespace,
            self.locator(asset),
            limit=min(100, _multipart_page_limit())
            if op is S3Operation.LIST_MULTIPART
            else 100
            if op is S3Operation.LIST_OBJECTS
            else None,
        )
        before = self.row(asset["id"])
        if before["lease_expires_at"]:
            self.wait_until_utc(
                before["lease_expires_at"] + timedelta(seconds=10), cap=180
            )
        with self.fault(selector, FaultMode.RESET_BEFORE_FORWARD) as gate:
            record = self.run_mode(
                ProcessMode.MAINTENANCE,
                spec=self.process_spec(endpoint=gate.endpoint),
                limit=100,
            )
            require(gate.snapshot()["matched"] and gate.snapshot()["forwarded"] == 0)
            require(
                self.row(asset["id"])["state"] != "DELETED"
                and self.cleanup_success_count(asset["id"]) == 0
            )
            require(record["result"] == 0)
        self.drain_cleanup(
            [asset["id"]],
            time.monotonic() + self.deadlines.allowance(180.0, self.phase),
        )

    def cleanup_effect_crash_trial(self, asset, *, lease_seconds, observation_seconds):
        require((lease_seconds, observation_seconds) == (30, 90))
        from tests.support.asset_faults import snapshot_json

        observation_cutoff = time.monotonic() + self.deadlines.allowance(
            float(observation_seconds), self.phase
        )

        def remaining():
            value = observation_cutoff - time.monotonic()
            require(value > 0)
            return value

        due = self.query(
            "SELECT due_at FROM wso_private.asset_cleanup WHERE asset_id=:id AND status<>'DONE'",
            {"id": UUID(asset["id"])},
        )
        require(len(due) == 1)
        self.wait_until_utc(due[0]["due_at"], cap=remaining())
        spec = self.process_spec()
        control = BarrierControl(spec.control_path, self.owner)
        cutoff = min(
            observation_cutoff,
            time.monotonic() + self.deadlines.allowance(20.0, self.phase),
        )
        control.arm(
            "CLEANUP_EFFECT_BEFORE_ACK", asset_id=UUID(asset["id"]), cutoff=cutoff
        )
        owned = self.start_mode(ProcessMode.MAINTENANCE, spec, argument=1)
        record = control.wait(cutoff)
        self.assert_helpers_settled(owned)
        self.assert_physical_absence(asset)
        work = self.query(
            "SELECT * FROM wso_private.asset_cleanup WHERE id=:id",
            {"id": UUID(record["id"])},
        )[0]
        require(
            work["status"] == "LEASED" and self.row(asset["id"])["state"] != "DELETED"
        )
        require(self.cleanup_success_count(asset["id"]) == 0)
        former = json.loads((spec.control_path / "cleanup-claim.json").read_bytes())
        require(
            former["owner"] == self.owner and former["claim"]["work_id"] == record["id"]
        )
        self.stop_mode(owned, force=True)
        self.wait_until_utc(work["lease_expires_at"], cap=remaining())
        self.drain_cleanup(
            [asset["id"]],
            observation_cutoff,
        )
        finished = self.query(
            "SELECT generation,status FROM wso_private.asset_cleanup WHERE id=:id",
            {"id": UUID(record["id"])},
        )[0]
        require(
            finished["status"] == "DONE" and finished["generation"] > work["generation"]
        )

        before = self.query(
            "SELECT * FROM wso_private.asset_cleanup WHERE id=:id",
            {"id": UUID(record["id"])},
        )
        stale_spec = self.process_spec()
        snapshot_json(
            stale_spec.control_path / "stale-cleanup.json",
            dict(former["claim"], owner=self.owner),
        )
        denied = self.run_mode(
            ProcessMode.MAINTENANCE,
            spec=stale_spec,
            cap=remaining(),
            limit="stale-cleanup",
        )
        require(
            denied["result"] == {"denied": True}
            and self.query(
                "SELECT * FROM wso_private.asset_cleanup WHERE id=:id",
                {"id": UUID(record["id"])},
            )
            == before
        )
        require(self.cleanup_success_count(asset["id"]) == 1)
        remaining()

    def revoke(self, mutation, actor, asset, parent=None):
        if mutation == "delete":
            require(self.delete(asset["id"], actor=actor).status_code == 202)
        elif mutation == "session":
            self.revoke_session(actor)
        elif mutation == "membership":
            self.revoke_asset_authority(actor)
        else:
            require(mutation == "parent" and parent is not None)
            require(self.delete(parent["id"], actor=actor).status_code == 202)

    def raw_download(self, asset, actor, ticket, cutoff):
        from wso_api.auth import SESSION_COOKIE

        path = ticket["download_path"]
        require(path.startswith(f"/api/v1/assets/{asset['id']}/content?"))
        headers = f"GET {path} HTTP/1.1\r\nHost: {urlsplit(self.base_url).netloc}\r\nCookie: {SESSION_COOKIE}={actor.token}\r\nX-Asset-Ticket: {ticket['token']}\r\nConnection: close\r\n\r\n".encode()
        return raw_http_exchange(self.base_url, headers, (), cutoff)

    def revocation_trial(self, mutation, *, before_yield):
        actor = self.new_actor()
        data = self.image()
        parent = self.upload(data, actor=actor) if mutation == "parent" else None
        asset = self.upload(
            data,
            actor=actor,
            **(
                {"purpose": "IMPORT_CROP", "parent_asset_id": parent["id"]}
                if parent
                else {}
            ),
        )
        ticket = self.require_ticket(asset["id"], actor=actor)
        if before_yield:
            control = self.control_for()
            control.reset()
            cutoff = time.monotonic() + self.deadlines.allowance(10.0, self.phase)
            control.arm(
                "DOWNLOAD_FIRST_CHUNK", asset_id=UUID(asset["id"]), cutoff=cutoff
            )
            call = self.call(
                lambda: self.raw_download(asset, actor, ticket, time.monotonic() + 30),
                cap=30,
            )
            try:
                record = self.wait_event(control, cutoff, call)
                self.assert_helpers_settled(self.modes[self.process.pid])
                self.revoke(mutation, actor, asset, parent)
                control.release(record)
                response = call.result()
                # Headers may already have started on the immutable streaming
                # API. Incomplete EOF with zero image bytes is not a completed
                # successful content response.
                require(
                    response.content == b""
                    or response.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                )
                require(
                    response.disconnected
                    or response.status_code in {401, 403, 404, 410}
                )
            finally:
                call.close()
                self.callers.remove(call)
                control.reset()
        else:
            self.revoke(mutation, actor, asset, parent)
            response = self.download(asset["id"], actor=actor, ticket=ticket)
            require(
                response.status_code in {401, 403, 404, 410}
                and not response.headers.get("content-type", "").startswith("image/")
            )
        if mutation in {"session", "membership"}:
            cleanup_actor = self.new_actor(tenant_id=actor.tenant_id)
        else:
            cleanup_actor = actor
        self.erase(*((parent,) if parent else ()), asset, actor=cleanup_actor)

    def prove_backpressure_deadline(
        self, asset, *, original_seconds, observation_seconds
    ):
        require((original_seconds, observation_seconds) == (30, 45))
        from wso_api.auth import SESSION_COOKIE

        actor, ticket = self.actors[0], self.require_ticket(asset["id"])
        cutoff = time.monotonic() + self.deadlines.allowance(45.0, self.phase)
        stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        stream.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        stream.settimeout(min(5, cutoff - time.monotonic()))
        parsed = urlsplit(self.base_url)
        data = bytearray()
        try:
            stream.connect(("127.0.0.1", parsed.port))
            path = ticket["download_path"]
            stream.sendall(
                f"GET {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nCookie: {SESSION_COOKIE}={actor.token}\r\nX-Asset-Ticket: {ticket['token']}\r\nConnection: close\r\n\r\n".encode()
            )
            while b"\r\n\r\n" not in data or len(data) == data.index(b"\r\n\r\n") + 4:
                require(len(data) < 65536 and time.monotonic() < cutoff)
                chunk = stream.recv(4096)
                require(bool(chunk))
                data.extend(chunk)
            require(data.startswith(b"HTTP/1.1 200"))
            header_end = data.index(b"\r\n\r\n") + 4
            declared = int(
                re.search(rb"(?i)content-length: ([0-9]+)", data[:header_end]).group(1)
            )
            require(declared > 5242880 and len(data) > header_end)
            path = self.modes[self.process.pid].spec.control_path / "send.json"

            def blocked():
                records = json.loads(path.read_bytes())
                starts = [
                    r
                    for r in records
                    if r["phase"] == "begin"
                    and r["type"] == "http.response.body"
                    and r["count"] > 0
                    and type(r["deadline"]) is float
                ]
                ends = {r["started"] for r in records if r["phase"] == "end"}
                return next(
                    (
                        r
                        for r in starts
                        if r["at"] not in ends and time.monotonic() - r["at"] >= 0.1
                    ),
                    None,
                )

            witness = self.await_fact(blocked, cap=5)
            deadline = witness["deadline"]
            require(deadline < cutoff)
            require(self.delete(asset["id"]).status_code == 202)
            self.run_mode(ProcessMode.MAINTENANCE, limit=1)
            require(self.row(asset["id"])["state"] != "DELETED")
            require(self.raw_object(asset))
            while time.monotonic() <= deadline + 0.1:
                self.deadlines.check(self.phase)
                time.sleep(min(0.05, max(0.001, deadline + 0.1 - time.monotonic())))
            self.assert_helpers_settled(self.modes[self.process.pid])
            records = json.loads(path.read_bytes())
            require(
                all(
                    r["at"] < r["deadline"]
                    for r in records
                    if r["phase"] == "begin"
                    and r["type"] == "http.response.body"
                    and r["count"]
                    and type(r["deadline"]) is float
                )
            )
            stream.settimeout(max(0.001, min(5, cutoff - time.monotonic())))
            while time.monotonic() < cutoff:
                chunk = stream.recv(65536)
                if not chunk:
                    break
                data.extend(chunk)
                require(len(data) <= 20971520 + 65536)
            else:
                raise RuntimeError("slow client did not settle")
            require(len(data) - header_end < declared)
        finally:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            stream.close()
        self.drain_cleanup(
            [asset["id"]],
            time.monotonic() + self.deadlines.allowance(180.0, self.phase),
        )

    def parent_overlap_trial(self, order):
        require(order in {"crop-first", "delete-first"})
        parent, data = self.upload(self.image()), self.image()
        calls = []
        try:
            with self.admin.connect() as db:
                transaction = db.begin()
                try:
                    db.execute(text("SET LOCAL statement_timeout=5000"))
                    blocker = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
                    db.execute(
                        text("SELECT id FROM public.assets WHERE id=:id FOR UPDATE"),
                        {"id": UUID(parent["id"])},
                    )
                    begin = lambda: self.begin(
                        data, purpose="IMPORT_CROP", parent_asset_id=parent["id"]
                    )
                    delete = lambda: self.delete(parent["id"])
                    actions = (
                        (begin, delete) if order == "crop-first" else (delete, begin)
                    )
                    names = (
                        ("wso_begin_asset_upload", "wso_tombstone_asset")
                        if order == "crop-first"
                        else ("wso_tombstone_asset", "wso_begin_asset_upload")
                    )
                    first_pid = None
                    for action, name in zip(actions, names, strict=True):
                        calls.append(self.call(action, cap=5))

                        def waiting(name=name, prior_pid=first_pid):
                            rows = self.query(
                                "SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE datname=current_database() AND usename='wso_app' AND wait_event_type='Lock' AND position(:name in query)>0",
                                {"name": name},
                            )
                            valid = [
                                row
                                for row in rows
                                if blocker in row["blockers"]
                                or prior_pid is not None
                                and prior_pid in row["blockers"]
                            ]
                            require(len(valid) <= 1)
                            return valid[0]["pid"] if valid else None

                        pid = self.await_fact(waiting, cap=1)
                        if first_pid is None:
                            first_pid = pid
                    transaction.commit()
                finally:
                    if transaction.is_active:
                        transaction.rollback()
            results = [call.result() for call in calls]
            crop, deleted = results if order == "crop-first" else results[::-1]
            require(deleted.status_code == 202)
            if order == "crop-first":
                require(crop.status_code == 201)
                child = crop.json()
                require(child["asset_id"] != parent["id"])
                self.recover_rejected(child)
            else:
                require(crop.status_code in {404, 409, 410})
            self.drain_cleanup(
                [parent["id"]],
                time.monotonic() + self.deadlines.allowance(180.0, self.phase),
            )
        finally:
            primary = sys.exc_info()[1]
            first = None
            for call in calls:
                try:
                    call.close()
                    self.callers.remove(call)
                except BaseException as error:  # noqa: BLE001 -- retain owned settlement failures without raw exception output.
                    first = first or error
            if first is not None and primary is None:
                raise RuntimeError("parent overlap callers did not settle") from None

    def job_denial_trial(self, jobs, variant):
        from tests.support.asset_faults import snapshot_json as private_json

        require(
            variant
            in {
                "other-tenant",
                "other-store",
                "no-attachment",
                "payload-other",
                "tombstoned",
                "parent-deleted",
                "membership-revoked",
                "photo-only-crop",
                "no-asset-read",
                "unknown-kind",
                "stale-generation",
                "guc-spoof",
            }
        )
        if variant == "stale-generation":
            require(jobs.last_lease is not None)
            old = jobs.last_lease
            current = jobs.job(old["job_id"])
            require(
                current["state"] == "SUCCEEDED"
                and current["lease_generation"] > old["generation"]
            )
            spec = self.process_spec(broker=jobs.broker.identity.endpoint_url)
            private_json(
                spec.control_path / "stale-lease.json",
                {"owner": self.owner, "lease": old},
            )
            owned = self.start_mode(ProcessMode.JOB_WORKER, spec, argument="stale")
            self.await_fact(lambda: owned.process.poll() is not None, cap=10)
            require(
                owned.process.returncode == 0
                and json.loads((spec.control_path / "stale-result.json").read_bytes())
                == {"owner": self.owner, "denied": True}
            )
            owned.stop()
            self.modes.pop(owned.process.pid)
            return
        actor = self.new_actor()
        cleanup_actor = self.new_actor(tenant_id=actor.tenant_id)
        data, parent = self.image(), None
        store = None
        if variant == "other-store":
            stores = [uuid4(), uuid4()]
            with self.admin.begin() as db:
                for identifier in stores:
                    db.execute(
                        text(
                            "INSERT INTO public.stores(id,tenant_id,name,timezone) VALUES(:id,:tenant,'asset-job','Asia/Seoul')"
                        ),
                        {"id": identifier, "tenant": actor.tenant_id},
                    )
            target = self.upload(data, actor=actor, store_id=stores[1])
            store = stores[0]
        elif variant in {"parent-deleted", "photo-only-crop"}:
            parent = self.upload(data, actor=actor)
            target = self.upload(
                data, actor=actor, purpose="IMPORT_CROP", parent_asset_id=parent["id"]
            )
        elif variant == "other-tenant":
            target = self.upload(data, actor=self.new_actor())
        else:
            target = self.upload(data, actor=actor)
        digest = hashlib.sha256(self.raw_object(target)).digest()
        attached, extras = target, []
        if variant == "payload-other":
            attached = self.upload(data, actor=actor)
            extras.append(attached)
        kind = (
            "ASSET_FIXTURE_STORE_READ"
            if store
            else "ASSET_FIXTURE_PHOTO_ONLY"
            if variant == "photo-only-crop"
            else "ASSET_FIXTURE_NO_ASSET_READ"
            if variant == "no-asset-read"
            else "ASSET_FIXTURE_UNKNOWN"
            if variant == "unknown-kind"
            else "ASSET_FIXTURE_TENANT_READ"
        )
        before = self.query("SELECT count(*) AS n FROM public.jobs")[0]["n"]
        result = jobs.enqueue(
            target,
            actor=actor,
            kind=kind,
            attached=attached,
            store_id=store,
            attach=variant != "no-attachment",
        )
        atomic = variant in {
            "other-tenant",
            "other-store",
            "photo-only-crop",
            "no-asset-read",
            "unknown-kind",
        }
        if atomic:
            require(result["accepted"] is False)
            require(
                self.query("SELECT count(*) AS n FROM public.jobs")[0]["n"] == before
            )
            if variant == "unknown-kind":
                self.erase(target, actor=cleanup_actor)
                return
            # A real unattached job exercises the protected read-negative path
            # independently of the atomic attach rejection.
            result = jobs.enqueue(
                target, actor=actor, kind=kind, store_id=store, attach=False
            )
        require(result["accepted"])
        job_id = result["job_id"]
        if variant == "guc-spoof":
            spec = self.process_spec(broker=jobs.broker.identity.endpoint_url)
            private_json(
                spec.control_path / "spoof.json",
                {
                    "owner": self.owner,
                    "job_id": job_id,
                    "asset_id": target["id"],
                    "actor": str(actor.user_id),
                    "tenant": str(actor.tenant_id),
                    "token": "unauthorized-fixture-token",
                },
            )
            owned = self.start_mode(ProcessMode.JOB_WORKER, spec, argument="spoof")
            self.await_fact(lambda: owned.process.poll() is not None, cap=10)
            require(
                owned.process.returncode == 0
                and json.loads((spec.control_path / "spoof-result.json").read_bytes())
                == {"owner": self.owner, "denied": True}
            )
            owned.stop()
            self.modes.pop(owned.process.pid)
            # Cancel through the normal APP-authorized API, not fixture SQL.
            require(
                self.request(
                    "POST",
                    f"/api/v1/jobs/{job_id}/cancel?tenant_id={actor.tenant_id}",
                    actor=actor,
                ).status_code
                == 200
            )
        else:
            if variant == "tombstoned":
                require(self.delete(target["id"], actor=actor).status_code == 202)
            elif variant == "parent-deleted":
                require(self.delete(parent["id"], actor=actor).status_code == 202)
            elif variant == "membership-revoked":
                self.revoke_asset_authority(actor)
            worker = jobs.launch_worker()
            jobs.launch_dispatch()
            self.await_fact(
                lambda: jobs.job(job_id)["state"] in {"FAILED", "CANCELLED"}, cap=160
            )
            if variant == "membership-revoked":
                current = jobs.job(job_id)
                require(current["failure_code"] == "AUTHORIZATION_REVOKED")
            else:
                path = worker.spec.control_path / ("denied-" + job_id + ".json")
                denied = json.loads(path.read_bytes())
                require(
                    denied["owner"] == self.owner
                    and denied["job_id"] == job_id
                    and denied["status"] in {403, 404}
                )
                self.await_fact(
                    lambda: any(
                        row["event"] == "acked"
                        for row in jobs.broker.transport_facts(job_id)
                    ),
                    cap=160,
                )
            jobs.stop_processes()
        require(
            self.query(
                "SELECT count(*) AS n FROM public.job_items WHERE job_id=:id AND state='SUCCEEDED'",
                {"id": UUID(job_id)},
            )[0]["n"]
            == 0
        )
        require(
            self.query(
                "SELECT count(*) AS n FROM wso_private.asset_read_leases WHERE job_id=:id",
                {"id": UUID(job_id)},
            )[0]["n"]
            == 0
        )
        require(hashlib.sha256(self.raw_object(target)).digest() == digest)
        owner_actor = next(
            a
            for a in self.actors
            if str(a.tenant_id) == str(self.row(target["id"])["tenant_id"])
        )
        if variant == "other-tenant":
            cleanup_actor = owner_actor
        self.erase(*((parent,) if parent else ()), target, *extras, actor=cleanup_actor)

    def seed_locator(self):
        from wso_core.storage import ObjectLocator

        return ObjectLocator(self.namespace.installation_id, uuid4(), uuid4(), uuid4())

    def seed_one(self, *, multipart):
        from wso_core.storage import object_key

        locator = self.seed_locator()
        key = object_key(locator)
        client = self.access.clients["bootstrap"]
        if multipart:
            upload = client.create_multipart_upload(
                Bucket=self.provider.bucket, Key=key
            )["UploadId"]
            response = client.list_multipart_uploads(
                Bucket=self.provider.bucket, Prefix=key
            )
            rows = [
                row
                for row in response.get("Uploads", [])
                if row["Key"] == key and row["UploadId"] == upload
            ]
            require(len(rows) == 1)
            return {
                "locator": locator,
                "key": key,
                "upload": upload,
                "timestamp": rows[0]["Initiated"],
            }
        body = b"owned-age-seed-" + secrets.token_bytes(64)
        client.put_object(Bucket=self.provider.bucket, Key=key, Body=body)
        response = client.head_object(Bucket=self.provider.bucket, Key=key)
        return {
            "locator": locator,
            "key": key,
            "upload": None,
            "timestamp": response["LastModified"],
            "sha256": hashlib.sha256(body).hexdigest(),
            "size": len(body),
        }

    def seed_age_window(self):
        for multipart in (False, True):
            for _ in range(4):
                self.age_seeds.append(self.seed_one(multipart=multipart))
        client = self.access.clients["bootstrap"]
        malformed = self.provider.prefix + "malformed-sentinel"
        client.put_object(
            Bucket=self.provider.bucket,
            Key=malformed,
            Body=b"owned-malformed-preserved",
        )
        self.malformed_upload = client.create_multipart_upload(
            Bucket=self.provider.bucket, Key=malformed
        )["UploadId"]
        self.malformed_key = malformed
        actor = self.new_actor()
        body = synthetic_image()
        asset = self.upload(body, actor=actor)
        self.survivor = {
            "asset": asset,
            "actor": actor,
            "sha256": hashlib.sha256(body).hexdigest(),
            "cipher_sha256": hashlib.sha256(self.raw_object(asset)).hexdigest(),
        }
        self.seed_inventory = self.physical_inventory()
        require(tuple(map(len, self.seed_inventory)) == (6, 5))
        self.assert_seed_database_absence(self.age_seeds)

    def assert_seed_database_absence(self, seeds):
        ids = [item["locator"].asset_id for item in seeds]
        require(
            self.query(
                "SELECT count(*) AS n FROM public.assets WHERE id=ANY(:ids)",
                {"ids": ids},
            )[0]["n"]
            == 0
        )
        require(
            self.query(
                "SELECT count(*) AS n FROM wso_private.asset_uploads WHERE asset_id=ANY(:ids)",
                {"ids": ids},
            )[0]["n"]
            == 0
        )

    def cursor_state(self):
        return self.query(
            "SELECT object_cursor,multipart_cursor FROM wso_private.asset_reconciliation WHERE singleton"
        )[0]

    @staticmethod
    def typed_cursor(stream, value):
        from wso_core.asset_s3_worker import _cursor_read

        if value is None:
            return None
        if stream is TraversalStream.OBJECTS:
            return ObjectPageCursor(_cursor_read(value, {"token"})["token"])
        fields = _cursor_read(value, {"key", "upload"})
        return MultipartPageCursor(fields["key"], fields["upload"])

    def reconcile_epoch(self, *, expected_counts, restart=False):
        from wso_core.storage import ObjectLocator, object_key, parse_object_key

        inventory = self.physical_inventory()
        if tuple(map(len, inventory)) != expected_counts:
            original = getattr(self, "seed_inventory", ({}, {}))
            print(
                "WSO_ASSET_INVENTORY_DIAGNOSTIC="
                + json.dumps(
                    {
                        "schema": 1,
                        "objects": min(len(inventory[0]), 4096),
                        "multiparts": min(len(inventory[1]), 4096),
                        "original_objects_present": min(
                            len(set(inventory[0]) & set(original[0])), 4096
                        ),
                        "original_multiparts_present": min(
                            len(set(inventory[1]) & set(original[1])), 4096
                        ),
                        "extra_objects": min(
                            len(set(inventory[0]) - set(original[0])), 4096
                        ),
                        "extra_multiparts": min(
                            len(set(inventory[1]) - set(original[1])), 4096
                        ),
                        "original_metadata_matches": inventory == original,
                    },
                    sort_keys=True,
                )
            )
        require(tuple(map(len, inventory)) == expected_counts)
        tracker = EpochTracker(
            {
                TraversalStream.OBJECTS: frozenset(
                    key
                    for key in inventory[0]
                    if parse_object_key(self.namespace, key) is not None
                ),
                TraversalStream.MULTIPART: frozenset(
                    pair
                    for pair in inventory[1]
                    if parse_object_key(self.namespace, pair[0]) is not None
                ),
            }
        )
        candidates, records, prior_identity = [], [], None
        for index in range(64):
            require(self.deadlines.allowance(28.0, self.phase) == 28.0)
            before = self.cursor_state()
            tracker.begin_iteration()
            result = self.run_mode(ProcessMode.RECONCILE)
            identity = result["process_identity"]
            require(
                prior_identity is None
                or (identity.pid, identity.start_ticks)
                != (prior_identity.pid, prior_identity.start_ticks)
            )
            prior_identity = identity
            after = self.cursor_state()
            require(len(result["pages"]) == 2)
            for method, arguments, page in result["pages"]:
                stream = (
                    TraversalStream.OBJECTS
                    if method == "list_objects"
                    else TraversalStream.MULTIPART
                )
                name = (
                    "object_cursor"
                    if stream is TraversalStream.OBJECTS
                    else "multipart_cursor"
                )
                require(
                    arguments["cursor"] == before[name]
                    and arguments["limit"] == 1
                    and page["next_cursor"] == after[name]
                )
                identities = []
                for item in page["items"]:
                    locator = ObjectLocator(
                        **{k: UUID(v) for k, v in item["locator"].items()}
                    )
                    key = object_key(locator)
                    identities.append(
                        key
                        if stream is TraversalStream.OBJECTS
                        else (key, item["upload_id"])
                    )
                tracker.record_page(
                    stream,
                    cursor_before=self.typed_cursor(stream, before[name]),
                    cursor_after=self.typed_cursor(stream, after[name]),
                    identities=tuple(identities),
                    committed=True,
                )
            for transaction in result["transactions"]:
                for statement in transaction:
                    if "wso_reconcile_asset_candidate" in statement["statement"]:
                        require(
                            statement["consumed"] and type(statement["scalar"]) is bool
                        )
                        candidates.append(statement)
            records.append(result)
            if restart and index == 0:
                require(
                    before == {"object_cursor": None, "multipart_cursor": None}
                    and all(after.values())
                )
            summary = tracker.summary()
            if (
                summary.objects_full
                and summary.multipart_full
                and summary.simultaneous_null
            ):
                break
        else:
            raise RuntimeError("actual reconciliation epoch limit")
        tracker.assert_complete()
        require(
            all(
                count == expected
                for stream, expected in zip(
                    TraversalStream, expected_counts, strict=True
                )
                for count in tracker.streams[stream]["completed_pages"]
            )
        )
        require(self.physical_inventory() == inventory)
        return {
            "tracker": tracker,
            "candidates": candidates,
            "records": records,
            "inventory": inventory,
        }

    def assert_young_epoch_witness(self):
        witness = self.young_witness
        witness["tracker"].assert_complete()
        require(all(item["scalar"] is False for item in witness["candidates"]))
        ids = [x["locator"].asset_id for x in self.age_seeds]
        require(
            self.query(
                "SELECT count(*) AS n FROM wso_private.asset_cleanup WHERE asset_id=ANY(:ids)",
                {"ids": ids},
            )[0]["n"]
            == 0
        )
        require(witness["inventory"] == self.seed_inventory)

    def assert_foreign_preserved(self):
        client, item = self.access.clients["bootstrap"], self.provider.foreign_inventory
        body = client.get_object(Bucket=self.provider.bucket, Key=item["key"])["Body"]
        try:
            require(body.read(64) == b"foreign-preserved")
        finally:
            body.close()
        rows = client.list_multipart_uploads(
            Bucket=self.provider.bucket, Prefix=item["prefix"]
        )
        require(
            any(
                x["Key"] == item["key"] and x["UploadId"] == item["upload"]
                for x in rows.get("Uploads", [])
            )
        )
        require(
            client.head_bucket(Bucket=item["bucket"])["ResponseMetadata"][
                "HTTPStatusCode"
            ]
            == 200
        )

    def prepare_idle(self):
        self.pre_idle_witness = self.reconcile_epoch(expected_counts=(6, 5))
        require(self.pre_idle_witness["inventory"] == self.seed_inventory)
        self.assert_foreign_preserved()
        for owned in tuple(self.modes.values()):
            self.stop_mode(owned)
        self.process, self.log = None, None
        for fault in self.faults:
            fault.close()
        self.faults.clear()
        self.access.close()
        self.access = None
        require(
            self.query(
                "SELECT count(*) AS n FROM wso_private.asset_read_leases WHERE closed_at IS NULL AND expires_at>clock_timestamp()"
            )[0]["n"]
            == 0
        )
        require(
            self.query(
                "SELECT count(*) AS n FROM wso_private.asset_uploads WHERE lease_expires_at>clock_timestamp()"
            )[0]["n"]
            == 0
        )
        relay = self.provider.relay

        def settled():
            if not relay.lock.acquire(blocking=False):
                return False
            try:
                threads = tuple(relay.threads)
                acceptors = [
                    t for t in threads if t.name == "owned-asset-relay" and t.is_alive()
                ]
                if len(acceptors) != 1:
                    return False
                require(acceptors[0] is self.acceptor)
                snapshot = IdleSnapshot(
                    relay.state == "RUNNING"
                    and not relay.failed
                    and not relay.stop.is_set(),
                    relay.connections,
                    len(relay.sockets),
                    len(threads),
                    relay.sockets == {relay.listener},
                    threads == (self.acceptor,),
                    self.acceptor.is_alive(),
                    not relay.commands.records,
                )
                try:
                    validate_idle_snapshot(snapshot)
                except FixtureContractError:
                    return False
                return True
            finally:
                relay.lock.release()

        self.await_fact(settled, cap=20)
        self.phase = FixturePhase.AGING

    def resume_after_age(self):
        boundary = self.deadlines.age_anchor + 62 * 60
        while time.monotonic() < boundary:
            require(
                self.provider.relay.state == "RUNNING"
                and not self.provider.relay.failed
                and self.acceptor.is_alive()
            )
            time.sleep(min(1.0, boundary - time.monotonic()))
        self.deadlines.begin_post_age()
        self.phase = FixturePhase.POST_AGE
        self.fresh_runtime_access(self.phase)
        self.assert_original_seed_metadata()
        self.actors.clear()
        self.new_actor()
        self.new_actor()
        self.start_api()

    def oldest_eligible_boundary(self):
        return max(item["timestamp"] for item in self.age_seeds) + timedelta(hours=1)

    def assert_original_seed_metadata(self):
        inventory = self.physical_inventory()
        require(
            inventory == self.seed_inventory
            and datetime.now(UTC) >= self.oldest_eligible_boundary()
        )
        self.assert_seed_database_absence(self.age_seeds)

    def seed_post_age_young(self):
        self.young_seeds = [
            self.seed_one(multipart=multipart)
            for multipart in (False, True)
            for _ in range(2)
        ]
        self.assert_seed_database_absence(self.young_seeds)
        require(tuple(map(len, self.physical_inventory())) == (8, 7))

    def prove_persisted_restart_and_full_epochs(self):
        self.aged_witness = self.reconcile_epoch(expected_counts=(8, 7), restart=True)

    def assert_aged_work_and_young_refusals(self):
        old = [item["locator"].asset_id for item in self.age_seeds]
        young = [item["locator"].asset_id for item in self.young_seeds]
        rows = self.query(
            "SELECT asset_id,operation,multipart_id,status FROM wso_private.asset_cleanup WHERE asset_id=ANY(:ids)",
            {"ids": old},
        )
        require(len(rows) == 8 and {row["asset_id"] for row in rows} == set(old))
        require(
            self.query(
                "SELECT count(*) AS n FROM wso_private.asset_cleanup WHERE asset_id=ANY(:ids)",
                {"ids": young},
            )[0]["n"]
            == 0
        )
        require(self.row(self.survivor["asset"]["id"])["state"] == "READY")
        for candidate in self.aged_witness["candidates"]:
            locator = json.loads(candidate["values"]["locator"])
            if (
                UUID(locator["asset_id"]) in young
                or locator["asset_id"] == self.survivor["asset"]["id"]
            ):
                require(candidate["scalar"] is False)

    def drain_aged_cleanup(self):
        old = [item["locator"].asset_id for item in self.age_seeds]

        def complete():
            self.run_mode(ProcessMode.MAINTENANCE, limit=100, cap=180)
            rows = self.query(
                "SELECT status FROM wso_private.asset_cleanup WHERE asset_id=ANY(:ids)",
                {"ids": old},
            )
            return len(rows) == 8 and all(row["status"] == "DONE" for row in rows)

        self.await_fact(complete, cap=180)

    def assert_seed_absence_and_survivors(self):
        inventory = self.physical_inventory()
        old_keys = {seed["key"] for seed in self.age_seeds if seed["upload"] is None}
        old_uploads = {
            (seed["key"], seed["upload"])
            for seed in self.age_seeds
            if seed["upload"] is not None
        }
        previous = self.aged_witness["inventory"]
        require(
            inventory
            == (
                {
                    key: value
                    for key, value in previous[0].items()
                    if key not in old_keys
                },
                {
                    key: value
                    for key, value in previous[1].items()
                    if key not in old_uploads
                },
            )
        )
        require(
            inventory[0][self.malformed_key]
            == self.seed_inventory[0][self.malformed_key]
            and inventory[1][(self.malformed_key, self.malformed_upload)]
            == self.seed_inventory[1][(self.malformed_key, self.malformed_upload)]
        )
        for seed in self.young_seeds:
            if seed["upload"] is not None:
                require(
                    inventory[1][(seed["key"], seed["upload"])] == seed["timestamp"]
                )
            else:
                require(inventory[0][seed["key"]] == (seed["size"], seed["timestamp"]))
                body = self.access.clients["bootstrap"].get_object(
                    Bucket=self.provider.bucket, Key=seed["key"]
                )["Body"]
                try:
                    require(
                        hashlib.sha256(body.read(1024)).hexdigest() == seed["sha256"]
                    )
                finally:
                    body.close()
        body = self.access.clients["bootstrap"].get_object(
            Bucket=self.provider.bucket, Key=self.malformed_key
        )["Body"]
        try:
            require(body.read(1024) == b"owned-malformed-preserved")
        finally:
            body.close()
        require(
            self.row(self.survivor["asset"]["id"])["state"] == "READY"
            and hashlib.sha256(self.raw_object(self.survivor["asset"])).hexdigest()
            == self.survivor["cipher_sha256"]
        )
        from wso_core.storage import object_key

        ready_key = object_key(self.locator(self.survivor["asset"]))
        require(inventory[0][ready_key] == self.seed_inventory[0][ready_key])
        self.assert_foreign_preserved()

    def assert_final_cursors_null(self):
        require(
            self.cursor_state() == {"object_cursor": None, "multipart_cursor": None}
        )

    def assert_no_unfinished_owned_work_except_conservative_negative(self):
        rows = self.query(
            "SELECT asset_id FROM wso_private.asset_cleanup WHERE status<>'DONE'"
        )
        require({str(row["asset_id"]) for row in rows} <= self.conservative)

    def __exit__(self, *_exc):
        errors, cleanup_causes = [], []
        receipt = None
        stage = "CUTOFF"

        def record(category, error):
            errors.append(category)
            cleanup_causes.append(error)

        try:
            # Establish custody's existing deadline before any filesystem or
            # launch operation. The outer finally also covers this setup.
            if FixturePhase.TEARDOWN not in self.deadlines.cutoffs:
                self.deadlines.begin_teardown()
            self.phase = FixturePhase.TEARDOWN
            self.provider.cleanup_cutoff = min(
                self.provider.cleanup_cutoff
                if self.provider.cleanup_cutoff is not None
                else time.monotonic() + 180,
                self.deadlines.cutoffs[self.phase],
            )
            stage = "RECEIPT"
            try:
                self.provider_evidence.unlink(missing_ok=True)
            except BaseException as error:  # noqa: BLE001 -- retain filesystem failure.
                record(stage, error)
            stage = "CALLER"
            for call in tuple(self.callers):
                try:
                    call.close()
                except BaseException as error:  # noqa: BLE001 -- continue owned cleanup.
                    record(stage, error)
                else:
                    self.callers.remove(call)
            stage = "LAUNCH"
            for process, log in tuple(self.launches):
                try:
                    if process.poll() is None:
                        errors.append("UNVERIFIED_PROCESS")
                        continue
                    process.wait(
                        timeout=max(
                            0,
                            min(
                                3, self.deadlines.cutoffs[self.phase] - time.monotonic()
                            ),
                        )
                    )
                    log.close()
                except BaseException as error:  # noqa: BLE001 -- retain exact launch custody.
                    record(stage, error)
                else:
                    self.launches.remove((process, log))
            stage = "JOB"
            if self.jobs_context is not None:
                try:
                    self.jobs_context.__exit__(*_exc)
                except BaseException as error:  # noqa: BLE001 -- continue owned cleanup.
                    record(stage, error)
            stage = "PROCESS"
            for owned in tuple(self.modes.values()):
                try:
                    self.stop_mode(owned)
                except BaseException as error:  # noqa: BLE001 -- retain exact process custody.
                    record(stage, error)
            stage = "FAULT"
            for fault in tuple(self.faults):
                try:
                    fault.close()
                except BaseException as error:  # noqa: BLE001 -- continue owned cleanup.
                    record(stage, error)
                else:
                    self.faults.remove(fault)
            stage = "SDK"
            if self.access is not None:
                try:
                    self.access.close()
                except BaseException as error:  # noqa: BLE001 -- continue owned cleanup.
                    record(stage, error)
                else:
                    self.access = None
            stage = "SQL"
            if self.admin is not None:
                try:
                    self.admin.dispose()
                except BaseException as error:  # noqa: BLE001 -- retain SQL failure before recycling.
                    record(stage, error)
            if not errors:
                stage = "PROVIDER"
                from scripts.asset_provider_receipt import validate_provider_receipt

                if self.provider.receipt is not None:
                    receipt = dict(self.provider.receipt)
                    validate_provider_receipt(receipt)
                self.deadlines.check(self.phase)
                self.provider.close()
                stage = "KEYS"
                for name in ("K1", "K2"):
                    (self.directory / name).unlink(missing_ok=True)
                self.deadlines.check(self.phase)
                stage = "RECEIPT"
                if (
                    receipt is not None
                    and getattr(self, "suite_success", False)
                    and not (_exc and _exc[0])
                ):
                    self.provider_evidence.parent.mkdir(parents=True, exist_ok=True)
                    exclusive_private_json(self.provider_evidence, receipt)
        except BaseException as error:  # noqa: BLE001 -- every early operation reaches finally.
            record(stage, error)
        finally:
            if errors:
                try:
                    if self.provider.cleanup_cutoff is None:
                        # Deadline setup itself failed: no fresh cleanup allowance.
                        self.provider.cleanup_cutoff = min(
                            time.monotonic(), self.deadlines.start + 94 * 60
                        )
                    self.provider.quiesce_local()
                except BaseException as error:  # noqa: BLE001 -- retain initiating failure too.
                    record("LOCAL_UNSETTLED", error)
                else:
                    errors.append("LOCAL_QUIESCED_TARGET_RETAINED")
        if errors:
            refusal = RuntimeError(
                "asset fixture cleanup refused: " + ",".join(sorted(set(errors)))
            )
            refusal.cleanup_causes = tuple(cleanup_causes)
            raise refusal from (
                _exc[1]
                if len(_exc) > 1 and _exc[1] is not None
                else cleanup_causes[0]
                if cleanup_causes
                else None
            )


@pytest.fixture(scope="module")
def asset_harness(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("private-assets")
    os.chmod(directory, 0o700)
    with AssetHarness(directory) as harness:
        try:
            yield harness
        finally:
            harness.suite_success = request.session.testsfailed == 0
