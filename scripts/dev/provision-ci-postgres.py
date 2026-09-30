"""Bootstrap only the fresh, labelled PostgreSQL container owned by this CI job.

Inputs and generated credentials are environment-only. Never use this helper on
the Windows development cluster or an existing business database.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

ROOT = Path(__file__).resolve().parents[2]
ROLES = {
    "APP": "wso_app",
    "IDENTITY": "wso_identity_bootstrap",
    "MIGRATOR": "wso_migrator",
    "SESSION": "wso_web_session",
    "WORKER": "wso_connection_worker",
    "DISPATCH": "wso_dispatcher",
    "JOB": "wso_job_worker",
}


def parse_admin_url(value: str, *, ci: str, disposable: str) -> URL:
    if ci != "true" or disposable != "1":
        raise ValueError("explicit disposable CI opt-in is required")
    if not value or any(character in value for character in "\r\n\x00"):
        raise ValueError("invalid connection target")
    try:
        url = make_url(value)
    except (ArgumentError, ValueError) as error:
        raise ValueError("invalid connection target") from error
    if (
        url.drivername != "postgresql+psycopg"
        or url.host != "127.0.0.1"
        or url.database != "wso_ci_test"
        or url.username != "postgres"
        or not url.password
        or any(character in (url.password or "") for character in "\r\n\x00")
        or url.port is None
        or not 1024 <= url.port <= 65535
        or url.query
    ):
        raise ValueError("only an explicit loopback CI admin target is permitted")
    return url


def assert_owned_container(data: dict[str, Any], owner: str, url: URL) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", owner):
        raise ValueError("invalid CI resource owner")
    if (
        data.get("Name") != f"/wso-ci-postgres-{owner}"
        or data.get("Config", {}).get("Labels", {}).get("wso.ci.owner") != owner
        or not re.fullmatch(
            r"postgres@sha256:[0-9a-f]{64}",
            data.get("Config", {}).get("Image", ""),
        )
        or data.get("State", {}).get("Running") is not True
        or data.get("NetworkSettings", {}).get("Ports", {}).get("5432/tcp")
        != [{"HostIp": "127.0.0.1", "HostPort": str(url.port)}]
    ):
        raise ValueError("CI resource identity or endpoint mismatch")


def assert_fresh_database(state: dict[str, Any]) -> None:
    if (
        state["database"] != "wso_ci_test"
        or state["user"] != "postgres"
        or state["owner"] != "postgres"
        or state["superuser"] is not True
        or state["version"] != 170011
        or state["schemas"] != ["public"]
        or state["objects"] != 0
        or state["extensions"] != ["plpgsql"]
        or sorted(state["databases"]) != ["postgres", "wso_ci_test"]
        or state["custom_roles"] != ["postgres"]
    ):
        raise ValueError("database is not a fresh dedicated PostgreSQL 17.11 cluster")


def database_snapshot(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    row = connection.execute(
        "SELECT current_database(), current_user, "
        "pg_get_userbyid(datdba), "
        "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user), "
        "current_setting('server_version_num')::integer "
        "FROM pg_database WHERE datname = current_database()"
    ).fetchone()
    if row is None:
        raise ValueError("database identity is unavailable")
    state = dict(
        zip(
            ("database", "user", "owner", "superuser", "version"),
            row,
            strict=True,
        )
    )
    queries = {
        "schemas": "SELECT nspname FROM pg_namespace WHERE "
        "nspname !~ '^pg_' AND nspname <> 'information_schema' ORDER BY 1",
        "extensions": "SELECT extname FROM pg_extension ORDER BY 1",
        "databases": "SELECT datname FROM pg_database WHERE NOT datistemplate "
        "ORDER BY 1",
        "custom_roles": "SELECT rolname FROM pg_roles WHERE rolname !~ "
        "'^pg_' ORDER BY 1",
    }
    for key, query in queries.items():
        state[key] = [item[0] for item in connection.execute(query).fetchall()]
    # Any user table, view, sequence, routine, or type disqualifies this target.
    state["objects"] = connection.execute(
        "SELECT sum(n) FROM ("
        "SELECT count(*) n FROM pg_class c JOIN pg_namespace ns "
        "ON ns.oid=c.relnamespace WHERE ns.nspname='public' UNION ALL "
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace ns "
        "ON ns.oid=p.pronamespace WHERE ns.nspname='public' UNION ALL "
        "SELECT count(*) FROM pg_type t JOIN pg_namespace ns "
        "ON ns.oid=t.typnamespace WHERE ns.nspname='public') counts"
    ).fetchone()[0]
    return state


def assert_restricted_roles(rows: dict[str, tuple[Any, ...]]) -> None:
    if set(rows) != set(ROLES.values()):
        raise ValueError("required migration-created CI role is missing")
    for flags in rows.values():
        # superuser, createdb, createrole, replication, bypassrls, inherit,
        # canlogin, and memberships in either direction.
        if len(flags) != 8 or any(flags[:6]) or flags[6] is not True or flags[7]:
            raise ValueError("migration-created role exceeds the allowed scope")


def restricted_role_snapshot(
    connection: psycopg.Connection[Any],
) -> dict[str, tuple[Any, ...]]:
    return {
        row[0]: tuple(row[1:])
        for row in connection.execute(
            "SELECT r.rolname, r.rolsuper, r.rolcreatedb, r.rolcreaterole, "
            "r.rolreplication, r.rolbypassrls, r.rolinherit, r.rolcanlogin, "
            "(SELECT count(*) FROM pg_auth_members m "
            "WHERE m.member=r.oid OR m.roleid=r.oid) "
            "FROM pg_roles r WHERE r.rolname = ANY(%s)",
            (list(ROLES.values()),),
        ).fetchall()
    }


def export_environment(url: URL, passwords: dict[str, str], output: Path) -> None:
    pairs = [("ADMIN", url)] + [
        (key, url.set(username=role, password=passwords[role]))
        for key, role in ROLES.items()
    ]
    entries = []
    masks = []
    for key, connection_url in pairs:
        password = connection_url.password or ""
        value = connection_url.render_as_string(hide_password=False)
        if any(character in password + value for character in "\r\n\x00"):
            raise ValueError("invalid environment credential")
        # GitHub command escaping differs from URL escaping.
        masks += [password, value]
        entries.append(f"WSO_TEST_{key}_DATABASE_URL={value}\n")
    for secret in masks:
        escaped = secret.replace("%", "%25").replace("\r", "%0D")
        escaped = escaped.replace("\n", "%0A")
        print(f"::add-mask::{escaped}")
    with output.open("a", encoding="utf-8", newline="\n") as stream:
        stream.writelines(entries)


def connect(url: URL) -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        password=url.password,
        connect_timeout=5,
        autocommit=True,
    )


def main() -> None:
    url = parse_admin_url(
        os.environ.get("WSO_CI_ADMIN_DATABASE_URL", ""),
        ci=os.environ.get("CI", ""),
        disposable=os.environ.get("WSO_CI_DISPOSABLE_POSTGRES", ""),
    )
    owner = os.environ.get("WSO_CI_RUNTIME_OWNER", "")
    if not re.fullmatch(r"[0-9a-f]{32}", owner):
        raise ValueError("CI container ownership is required")
    output = Path(os.environ["GITHUB_ENV"])
    if not output.is_file():
        raise ValueError("GitHub environment file is unavailable")
    container = f"wso-ci-postgres-{owner}"
    inspected = subprocess.run(
        ["docker", "inspect", container],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert_owned_container(json.loads(inspected.stdout)[0], owner, url)
    with connect(url) as connection:
        assert_fresh_database(database_snapshot(connection))
    config = Config(str(ROOT / "infra/alembic.ini"))
    # ConfigParser interprets percent escapes; retain the exact credential URL.
    config.set_main_option(
        "sqlalchemy.url",
        url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    command.upgrade(config, "head")
    passwords = {role: secrets.token_urlsafe(36) for role in ROLES.values()}
    if len(set(passwords.values()) | {url.password}) != len(ROLES) + 1:
        raise ValueError("CI role credentials must be distinct")
    with connect(url) as connection:
        assert_restricted_roles(restricted_role_snapshot(connection))
        for role, password in passwords.items():
            connection.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role),
                    sql.Literal(password),
                )
            )
        connection.execute(
            sql.SQL("GRANT CREATE ON DATABASE {} TO wso_migrator").format(
                sql.Identifier("wso_ci_test")
            )
        )
    for role, password in passwords.items():
        with connect(url.set(username=role, password=password)) as connection:
            if connection.execute("SELECT current_user").fetchone()[0] != role:
                raise ValueError("restricted CI role login failed")
    export_environment(url, passwords, output)
    print("Disposable PostgreSQL 17.11: head applied; seven restricted role logins OK.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 -- sanitize every credential-bearing error
        # Driver, SQLAlchemy and subprocess errors can include SQL/credentials.
        print(
            f"CI bootstrap refused or failed ({type(error).__name__}).", file=sys.stderr
        )
        sys.exit(1)
