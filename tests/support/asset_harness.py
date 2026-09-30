"""Actual Linux HTTP + PostgreSQL + private S3 asset acceptance fixture."""

from __future__ import annotations

import hashlib
import io
import os
import secrets
import signal
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.support.asset_provider import AssetProvider
from tests.support.job_broker_harness import await_fact
from tests.support.job_handlers import verify_fixture_database

ROOT = Path(__file__).resolve().parents[2]


@dataclass(repr=False)
class BrowserActor:
    tenant_id: object
    user_id: object
    token: str = field(repr=False)
    csrf: str = field(repr=False)


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

    def write_red_evidence(self):
        """Overwrite a fixed sanitized receipt; never copy private fixture state."""
        directory = ROOT / ".superpowers" / "verification"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "private-assets-red-evidence.json"
        temporary = directory / (".private-assets-red-" + self.owner + ".tmp")
        from tests.support.asset_provider import private_json

        private_json(temporary, self.evidence)
        temporary.replace(target)

    def __enter__(self):
        if sys.platform != "linux":
            pytest.fail("private_assets requires actual owned Linux S3/HTTP; no skip")
        try:
            baseline = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout.strip()
            if len(baseline) != 40 or any(
                character not in "0123456789abcdef" for character in baseline
            ):
                raise ValueError("asset fixture source identity unavailable")
            self.evidence["baseline_sha"] = baseline
            self.write_red_evidence()
            self.admin = create_engine(
                os.environ["WSO_TEST_ADMIN_DATABASE_URL"],
                hide_parameters=True,
                connect_args={"connect_timeout": 5},
            )
            verify_fixture_database(self.admin, domain_only=False)
            admin_url = make_url(self.admin.url)
            for name, role in (
                ("APP", "wso_app"),
                ("IDENTITY", "wso_identity_bootstrap"),
                ("SESSION", "wso_web_session"),
            ):
                url = make_url(os.environ[f"WSO_TEST_{name}_DATABASE_URL"])
                if (url.host, url.port, url.database, url.username, url.drivername) != (
                    admin_url.host,
                    admin_url.port,
                    admin_url.database,
                    role,
                    "postgresql+psycopg",
                ) or url.query:
                    raise ValueError("asset fixture runtime role target mismatch")
            self.provider.start()
            self.evidence["provider"] = dict(
                self.provider.receipt, owned_resource_mapping=True
            )
            self.evidence["stage"] = "PROVIDER_PREFLIGHT_PASSED"
            self.write_red_evidence()
            self.new_actor()
            self.new_actor()
            self.start_api()
            self.verify_http_identity()
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def new_actor(self, *, tenant_id=None, user_id=None):
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
        sessions = PostgresSessionStore(os.environ["WSO_TEST_SESSION_DATABASE_URL"])
        assert sessions.create(
            token_digest(actor.token),
            WebSession(
                "https://issuer.test",
                str(actor.user_id),
                actor.user_id,
                token_digest(actor.csrf),
                datetime.now(UTC) + timedelta(minutes=10),
            ),
            token_digest(secrets.token_urlsafe(32)),
        )
        self.actors.append(actor)
        return actor

    def start_api(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.log = (self.directory / "api-private.log").open("wb")
        os.chmod(self.directory / "api-private.log", 0o600)
        environment = os.environ.copy()
        environment.update({"WSO_ASSET_FIXTURE_OWNER": self.owner})
        self.command = [
            sys.executable,
            "-m",
            "tests.support.asset_process",
            "api",
            str(port),
        ]
        self.process = subprocess.Popen(
            self.command,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.start_time = self.process_identity(self.process.pid)[2]

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

        await_fact(ready, "actual Uvicorn HTTP listener", 30)

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
        with httpx.Client(
            base_url=self.base_url, timeout=15, trust_env=False, follow_redirects=False
        ) as client:
            return client.request(method, path, headers=outgoing, **kwargs)

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
        self.write_red_evidence()

    def begin(
        self,
        data,
        *,
        actor=None,
        content_type="image/png",
        purpose="IMPORT_PHOTO",
        parent_asset_id=None,
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
        body.update(overrides)
        return self.request("POST", "/api/v1/assets", actor=actor, json=body)

    def put(self, session, data, *, actor=None, content_type="image/png", **kwargs):
        return self.request(
            "PUT",
            session["upload_path"],
            actor=actor,
            headers={"X-Upload-Session": session["id"], "Content-Type": content_type},
            content=data,
            **kwargs,
        )

    def complete(self, asset_id, *, actor=None):
        actor = actor or self.actors[0]
        return self.request(
            "POST",
            f"/api/v1/assets/{asset_id}/complete?tenant_id={actor.tenant_id}",
            actor=actor,
        )

    def upload(self, data, *, actor=None, **kwargs):
        response = self.begin(data, actor=actor, **kwargs)
        self.evidence["asset_begin"] = {
            "expected_status": 201,
            "actual_status": response.status_code,
        }
        self.evidence["stage"] = "ASSET_REQUEST_OBSERVED"
        self.write_red_evidence()
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

    def __exit__(self, *_exc):
        errors = []
        try:
            self.stop_api()
        except Exception:  # noqa: BLE001 -- continue guarded resource cleanup
            errors.append("API process")
        try:
            self.provider.close()
        except Exception:  # noqa: BLE001 -- continue guarded resource cleanup
            errors.append("private S3 resources")
        if self.admin:
            self.admin.dispose()
        # Synthetic rows remain only in the root-owned disposable database, whose
        # guarded CI teardown erases the entire owned volume. Never destroy shared DBs.
        if errors:
            raise RuntimeError("asset cleanup refused/failed: " + ", ".join(errors))


@pytest.fixture
def asset_harness(tmp_path):
    os.chmod(tmp_path, 0o700)
    with AssetHarness(tmp_path) as harness:
        yield harness
