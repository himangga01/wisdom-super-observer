"""Fixture-only typed job handlers and observable process barriers."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import make_url
from wso_contracts.models import WireModel
from wso_core.jobs import JobKind, JobRegistry


class CounterPayload(WireModel):
    schema_version: Literal[1] = 1
    operation_id: UUID
    barrier: Literal["before-effect", "media-parked"] | None = None


class ExternalPayload(WireModel):
    schema_version: Literal[1] = 1
    operation_id: UUID
    unreadable: bool = False


def announce(name: str) -> None:
    directory = Path(os.environ["WSO_RECOVERY_CONTROL"])
    target = directory / f"{name}.json"
    temporary = directory / f".{name}.{os.getpid()}.tmp"
    fields = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()
    temporary.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "start_time": int(fields[19]),
                "group": int(fields[2]),
                "owner": os.environ["WSO_RECOVERY_OWNER"],
            }
        ),
        encoding="utf-8",
    )
    temporary.replace(target)


def barrier(name: str, *, timeout: float = 45) -> None:
    """Block on a private release file, with a real bounded process deadline."""
    announce(name)
    release = Path(os.environ["WSO_RECOVERY_CONTROL"]) / f"{name}.release"
    deadline = time.monotonic() + timeout
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"fixture barrier timed out: {name}")
        time.sleep(0.025)


def counter(step):
    payload = step.payload
    if payload.barrier and step.lease.generation == 1:
        try:
            if payload.barrier == "media-parked":
                # Model a bounded media/CLI process inside the dedicated pool.
                process = subprocess.Popen(
                    [sys.executable, "-m", "tests.support.job_process", "park"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    process.wait(timeout=20)
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=5)
            else:
                barrier(payload.barrier)
        finally:
            if payload.barrier == "media-parked":
                announce("media-parked-closed")
    step.session.execute(
        text(
            "INSERT INTO public.job_recovery_effects(tenant_id,job_id,effect_count) "
            "SELECT tenant_id,id,1 FROM public.jobs WHERE id=:job "
            "ON CONFLICT(job_id) DO UPDATE SET "
            "effect_count=job_recovery_effects.effect_count+1"
        ),
        {"job": step.lease.job_id},
    )
    return {"effect_count": 1}


def upstream_url(operation: UUID) -> str:
    endpoint = os.environ["WSO_RECOVERY_UPSTREAM"]
    # Test callbacks can only reach the owned server, never a vendor endpoint.
    from urllib.parse import urlsplit

    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise ValueError("fixture upstream must be loopback HTTP")
    return endpoint + "/" + str(operation)


def external(step):
    # Explicit durable intent before the independent HTTP transaction.
    step.mark_submitted()
    request = Request(
        upstream_url(step.payload.operation_id), data=b"{}", method="POST"
    )
    with urlopen(request, timeout=35) as response:
        result = json.load(response)
    return result


def reconcile_external(step):
    try:
        with urlopen(upstream_url(step.payload.operation_id), timeout=5) as response:
            return json.load(response)
    except (HTTPError, OSError, ValueError):
        return None


REGISTRY = JobRegistry(
    (
        JobKind("RECOVERY_COUNTER", CounterPayload, "TENANT", handler=counter),
        JobKind(
            "RECOVERY_STORE",
            CounterPayload,
            "STORE",
            permission="STAFF",
            handler=counter,
        ),
        JobKind(
            "RECOVERY_MEDIA",
            CounterPayload,
            "TENANT",
            queue="wso.media",
            handler=counter,
        ),
        JobKind(
            "RECOVERY_EXTERNAL",
            ExternalPayload,
            "TENANT",
            effect_mode="EXTERNAL_WRITE",
            handler=external,
            reconcile=reconcile_external,
        ),
    )
)


def verify_fixture_database(engine, *, domain_only=False):
    """Refuse all DDL until managed database identity has been proven."""
    root = Path(__file__).resolve().parents[2]
    url = make_url(engine.url)
    expected_database = "wso_test" if domain_only else "wso_ci_test"
    configured = os.environ.get("WSO_TEST_ADMIN_DATABASE_URL", "")
    if not configured or url != make_url(configured):
        raise ValueError("fixture URL differs from explicit administrator environment")
    if (
        url.database != expected_database
        or url.host != "127.0.0.1"
        or url.username != "postgres"
        or url.drivername != "postgresql+psycopg"
        or url.query
        or url.port is None
        or not 1024 <= url.port <= 65535
    ):
        raise ValueError("fixture administrator target mismatch")
    runtime = root / ".superpowers/runtime/postgresql17"
    if domain_only:
        if sys.platform != "win32":
            raise ValueError("domain_only requires the owned Windows runtime")
        state = json.loads((runtime / "credentials.json").read_text(encoding="utf-8"))
        if (
            url != make_url(state["urls"]["WSO_TEST_ADMIN_DATABASE_URL"])
            or url.port != state["port"]
            or state["database"] != "wso_test"
        ):
            raise ValueError("fixture target differs from managed runtime state")
    else:
        if (
            sys.platform != "linux"
            or os.environ.get("CI") != "true"
            or os.environ.get("WSO_CI_DISPOSABLE_POSTGRES") != "1"
            or os.environ.get("WSO_TEST_RECOVERY_DATABASE_NAME") != "wso_ci_test"
            or os.environ.get("WSO_TEST_RECOVERY_DATABASE_OWNER") != "postgres"
        ):
            raise ValueError("requires explicitly owned disposable Linux CI database")
        owner = os.environ.get("WSO_CI_RUNTIME_OWNER", "")
        if not re.fullmatch(r"[0-9a-f]{32}", owner):
            raise ValueError("CI database container owner absent")
        try:
            inspected = subprocess.run(
                ["docker", "inspect", f"wso-ci-postgres-{owner}"],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            container = json.loads(inspected.stdout)[0]
            valid = (
                container["Name"] == f"/wso-ci-postgres-{owner}"
                and re.fullmatch(
                    r"postgres@sha256:[0-9a-f]{64}", container["Config"]["Image"]
                )
                and container["Config"]["Labels"]["wso.ci.owner"] == owner
                and container["State"]["Running"]
                and container["NetworkSettings"]["Ports"]["5432/tcp"]
                == [{"HostIp": "127.0.0.1", "HostPort": str(url.port)}]
            )
        except (OSError, subprocess.SubprocessError, KeyError, ValueError):
            raise ValueError("owned CI database container unavailable") from None
        if not valid:
            raise ValueError("CI database container ownership mismatch")
        networks = container["NetworkSettings"]["Networks"]
        if set(networks) != {"bridge"}:
            raise ValueError("owned CI database network mismatch")
        listener = str(ipaddress.IPv4Address(networks["bridge"]["IPAddress"]))
        volume_name = f"wso-ci-postgres-data-{owner}"
        mounts = [
            mount
            for mount in container["Mounts"]
            if mount.get("Destination") == "/var/lib/postgresql/data"
        ]
        if (
            len(mounts) != 1
            or mounts[0].get("Type") != "volume"
            or mounts[0].get("Name") != volume_name
            or mounts[0].get("RW") is not True
        ):
            raise ValueError("owned CI database data mount mismatch")
        try:
            inspected = subprocess.run(
                ["docker", "volume", "inspect", volume_name],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            volume = json.loads(inspected.stdout)[0]
            if (
                volume["Name"] != volume_name
                or volume["Labels"]["wso.ci.owner"] != owner
            ):
                raise ValueError("owned CI database volume mismatch")
        except (OSError, subprocess.SubprocessError, KeyError, ValueError):
            raise ValueError(
                "owned CI database volume unavailable or mismatched"
            ) from None
    with engine.connect() as db:
        state = (
            db.execute(
                text(
                    "SELECT current_database() AS db,current_user AS actor,"
                    "pg_get_userbyid(datdba) AS owner,"
                    "current_setting('server_version_num') AS version,"
                    "host(inet_server_addr()) AS address,inet_server_port() AS port,"
                    "current_setting('data_directory') AS directory "
                    "FROM pg_database WHERE datname=current_database()"
                )
            )
            .mappings()
            .one()
        )
        if any(
            state[key] != value
            for key, value in {
                "db": expected_database,
                "actor": "postgres",
                "owner": "postgres",
                "version": "170011",
            }.items()
        ):
            raise ValueError("fixture database ownership/version/listener mismatch")
        if domain_only and (
            state["address"] != "127.0.0.1"
            or state["port"] != url.port
            or not Path(state["directory"]).samefile(runtime / "data")
        ):
            raise ValueError("fixture database data directory/listener mismatch")
        if not domain_only and (
            state["address"] != listener
            or state["port"] != 5432
            or state["directory"] != "/var/lib/postgresql/data"
        ):
            raise ValueError(
                "fixture database differs from owned container listener/data directory"
            )


def install_fixture_schema(engine, *, domain_only=False):
    """Install only fixture metadata/effects after verifying the owned database."""
    verify_fixture_database(engine, domain_only=domain_only)
    with engine.begin() as db:
        db.execute(
            text("""
            CREATE TABLE IF NOT EXISTS public.job_recovery_effects(
                tenant_id uuid NOT NULL,job_id uuid PRIMARY KEY
                REFERENCES public.jobs(id) ON DELETE CASCADE,
                effect_count bigint NOT NULL CHECK(effect_count>0));
            ALTER TABLE public.job_recovery_effects OWNER TO wso_migrator;
            ALTER TABLE public.job_recovery_effects ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.job_recovery_effects FORCE ROW LEVEL SECURITY;
            REVOKE ALL ON public.job_recovery_effects FROM PUBLIC;
            GRANT SELECT,INSERT,UPDATE ON public.job_recovery_effects TO wso_job_worker;
            DROP POLICY IF EXISTS recovery_worker ON public.job_recovery_effects;
            CREATE POLICY recovery_worker ON public.job_recovery_effects
                TO wso_job_worker USING(job_id=public.wso_current_job_id())
                WITH CHECK(job_id=public.wso_current_job_id());
        """)
        )
        for kind in REGISTRY.kinds.values():
            values = {
                "kind": kind.kind,
                "scope": kind.scope_kind,
                "permission": kind.permission,
                "queue": kind.queue,
                "mode": kind.effect_mode,
                "attempts": kind.max_attempts,
                "credentials": kind.credential_use,
            }
            db.execute(
                text(
                    "INSERT INTO wso_private.job_kinds(kind,payload_version,scope_kind,"
                    "permission,queue,effect_mode,max_attempts,credential_use) "
                    "VALUES(:kind,1,:scope,:permission,:queue,:mode,:attempts,:credentials) "
                    "ON CONFLICT(kind,payload_version) DO NOTHING"
                ),
                values,
            )
            actual = (
                db.execute(
                    text(
                        "SELECT kind,scope_kind AS scope,permission,queue,effect_mode AS mode,"
                        "max_attempts AS attempts,credential_use AS credentials "
                        "FROM wso_private.job_kinds WHERE kind=:kind AND payload_version=1"
                    ),
                    {"kind": kind.kind},
                )
                .mappings()
                .one()
            )
            if dict(actual) != values:
                raise ValueError("fixture registry/database metadata disagreement")
