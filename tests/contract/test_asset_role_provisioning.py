"""Execute both real provisioners against isolated role catalogs and state files."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from psycopg import sql

ROOT = Path(__file__).parents[2]
LEGACY_ROLES = (
    "postgres",
    "wso_app",
    "wso_identity_bootstrap",
    "wso_migrator",
    "wso_web_session",
    "wso_connection_worker",
    "wso_dispatcher",
    "wso_job_worker",
)
ASSET_ROLE = "wso_asset_maintenance"
SAFE = (False,) * 6 + (True, 0)
OLD_HEADS = (
    "0001_tenants",
    "0001b_tenant_grants",
    "0001c_auth_sessions",
    "0002_connections",
    "0003_jobs",
)


@pytest.fixture(params=["local", "ci"])
def helper(request, tmp_path):
    kind = request.param
    if kind == "local":
        source = (ROOT / "scripts/dev/postgres-runtime.ps1").read_text("utf-8")
        embedded = source.split("$helper = @'\n", 1)[1].split("\n'@", 1)[0]
        namespace = {
            "__name__": "isolated_runtime",
            "__file__": str(ROOT / "a/b/runtime.py"),
        }
        exec(compile(embedded, "embedded-runtime.py", "exec"), namespace)  # noqa: S102 -- execute owned extracted helper without its CLI
        module = SimpleNamespace(**namespace)
        # Functions use their original globals, so set isolated paths there.
        namespace.update(RUNTIME=tmp_path, STATE=tmp_path / "credentials.json")
        module._globals = namespace
    else:
        path = ROOT / "scripts/dev/provision-ci-postgres.py"
        spec = importlib.util.spec_from_file_location("isolated_ci", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return kind, module


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Catalog:
    """Model only the actual catalog/utility SQL boundary; reject other SQL."""

    def __init__(self, revisions=("0003a_assets",), rows=None, user="postgres"):
        self.revisions = revisions
        self.rows = (
            rows
            if rows is not None
            else {role: SAFE for role in (*LEGACY_ROLES[1:], ASSET_ROLE)}
        )
        self.user = user
        self.writes = []
        self.catalog_reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, statement, parameters=None):
        query = (
            statement.as_string()
            if isinstance(statement, sql.Composable)
            else statement
        )
        if query == "SELECT version_num FROM alembic_version":
            return Result([(value,) for value in self.revisions])
        if "FROM pg_database WHERE datname = %s" in query:
            return Result([(True,)])
        if query.startswith("SELECT EXISTS (SELECT 1 FROM pg_roles"):
            self.catalog_reads += 1
            return Result([(parameters[0] in self.rows,)])
        if "FROM pg_roles r WHERE r.rolname = ANY(%s)" in query:
            self.catalog_reads += 1
            # Both membership directions must contribute to the returned count.
            both = "m.member=r.oid OR m.roleid=r.oid" in query
            return Result(
                [
                    (role, *flags[:-1], sum(flags[-1]) if both else flags[-1][0])
                    if isinstance(flags[-1], tuple)
                    else (role, *flags)
                    for role, flags in self.rows.items()
                    if role in parameters[0]
                ]
            )
        if query.startswith(("ALTER ROLE ", "GRANT CREATE ")):
            self.writes.append(query)
            return Result([])
        if query == "SELECT current_user":
            return Result([(self.user,)])
        if "SELECT version(), current_setting('listen_addresses')" in query:
            return Result([("PostgreSQL 17.11 fixture", "127.0.0.1", "57056")])
        if "FROM pg_roles WHERE rolname = current_user" in query:
            return Result([(self.user, *self.rows[self.user][:7])])
        if "SELECT count(*) FROM pg_auth_members" in query:
            membership = self.rows[parameters[0]][-1]
            count = sum(membership) if isinstance(membership, tuple) else membership
            return Result([(count,)])
        raise AssertionError(f"Unexpected SQL: {query}")


def old_state():
    return {
        "passwords": {role: f"fixture-{role}" for role in LEGACY_ROLES},
        "urls": {
            f"WSO_TEST_{key}_DATABASE_URL": f"saved-{key}?application_name=retained"
            for key in (
                "ADMIN",
                "APP",
                "IDENTITY",
                "MIGRATOR",
                "SESSION",
                "WORKER",
                "DISPATCH",
                "JOB",
            )
        },
        "database": "wso_test",
        "port": 57056,
        "drive": "Z:",
        "metadata": {"owned": "unchanged"},
        "provisioned_roles": list(LEGACY_ROLES[1:]),
    }


def invoke(helper, catalog, monkeypatch, tmp_path, *, status=False):
    kind, module = helper
    if kind == "local":
        state = old_state()
        state["passwords"][ASSET_ROLE] = "fixture-asset"
        module._globals["connect"] = lambda state, role="postgres", **kwargs: (
            catalog if role == "postgres" else Catalog(rows=catalog.rows, user=role)
        )
        (module.status if status else module.provision)(state)
        return state
    url = module.parse_admin_url(
        "postgresql+psycopg://postgres:fixture-admin@127.0.0.1:55432/wso_ci_test",
        ci="true",
        disposable="1",
    )
    output = tmp_path / "github-env"
    output.touch()
    for name, value in {
        "WSO_CI_ADMIN_DATABASE_URL": url.render_as_string(hide_password=False),
        "CI": "true",
        "WSO_CI_DISPOSABLE_POSTGRES": "1",
        "WSO_CI_RUNTIME_OWNER": "a" * 32,
        "GITHUB_ENV": str(output),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="[{}]")
    )
    monkeypatch.setattr(module, "assert_owned_container", lambda *args: None)
    monkeypatch.setattr(module, "database_snapshot", lambda connection: {})
    monkeypatch.setattr(module, "assert_fresh_database", lambda snapshot: None)
    monkeypatch.setattr(module.command, "upgrade", lambda *args: None)
    monkeypatch.setattr(
        module,
        "connect",
        lambda url: (
            catalog
            if url.username == "postgres"
            else Catalog(rows=catalog.rows, user=url.username)
        ),
    )
    module.main()
    return output


def test_new_role_is_provisioned_without_any_owner_login(helper, monkeypatch, tmp_path):
    catalog = Catalog()
    output = invoke(helper, catalog, monkeypatch, tmp_path)
    password_writes = [
        query for query in catalog.writes if query.startswith("ALTER ROLE")
    ]
    assert len(password_writes) == 8
    assert any('"wso_asset_maintenance"' in query for query in password_writes)
    assert not any("wso_asset_owner" in query for query in password_writes)
    if helper[0] == "ci":
        entries = output.read_text("utf-8").splitlines()
        assert len(entries) == 9
        assert any(
            line.startswith("WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL=")
            for line in entries
        )


@pytest.mark.parametrize("head", ("0003a_assets", "0004_future"))
def test_missing_required_asset_role_refuses_before_passwords(
    helper, monkeypatch, tmp_path, head
):
    catalog = Catalog((head,), {role: SAFE for role in LEGACY_ROLES[1:]})
    with pytest.raises((RuntimeError, ValueError), match="missing"):
        invoke(helper, catalog, monkeypatch, tmp_path)
    assert catalog.writes == []


@pytest.mark.parametrize(
    "revisions", [(), ("0003_jobs", "0003a_assets"), ("0003a_assets",) * 2]
)
def test_invalid_revision_cardinality_refuses_before_catalog_and_passwords(
    helper, monkeypatch, tmp_path, revisions
):
    catalog = Catalog(revisions)
    with pytest.raises((RuntimeError, ValueError), match="single"):
        invoke(helper, catalog, monkeypatch, tmp_path)
    assert catalog.writes == []
    assert catalog.catalog_reads == 0


@pytest.mark.parametrize("role", (*LEGACY_ROLES[1:], ASSET_ROLE))
@pytest.mark.parametrize("index", range(9))
def test_every_login_rejects_unsafe_flags_and_both_membership_directions_before_writes(
    helper, monkeypatch, tmp_path, role, index
):
    rows = {name: SAFE for name in (*LEGACY_ROLES[1:], ASSET_ROLE)}
    flags = list(SAFE)
    if index < 7:
        flags[index] = index != 6
    else:
        flags[7] = (1, 0) if index == 7 else (0, 1)
    rows[role] = tuple(flags)
    catalog = Catalog(rows=rows)
    with pytest.raises((RuntimeError, ValueError)):
        invoke(helper, catalog, monkeypatch, tmp_path)
    assert catalog.writes == []


@pytest.mark.parametrize("head", OLD_HEADS)
@pytest.mark.parametrize("helper", ["local"], indirect=True)
def test_exact_legacy_local_heads_allow_absent_asset_role(
    helper, monkeypatch, tmp_path, head
):
    catalog = Catalog((head,), {role: SAFE for role in LEGACY_ROLES[1:]})
    state = invoke(helper, catalog, monkeypatch, tmp_path)
    assert state["provisioned_roles"] == list(LEGACY_ROLES[1:])
    assert (
        len([query for query in catalog.writes if query.startswith("ALTER ROLE")]) == 7
    )


@pytest.mark.parametrize("head", OLD_HEADS[:-1])
@pytest.mark.parametrize("helper", ["local"], indirect=True)
def test_local_pre_job_heads_still_allow_missing_dispatch_and_job(
    helper, monkeypatch, tmp_path, head
):
    catalog = Catalog((head,), {role: SAFE for role in LEGACY_ROLES[1:6]})
    invoke(helper, catalog, monkeypatch, tmp_path)
    assert (
        len([query for query in catalog.writes if query.startswith("ALTER ROLE")]) == 5
    )


@pytest.mark.parametrize("helper", ["local"], indirect=True)
def test_local_load_extends_and_repeats_without_changing_old_state(helper, tmp_path):
    module = helper[1]
    before = old_state()
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(before), "utf-8")
    loaded = module.load()
    assert loaded["passwords"].get(ASSET_ROLE)
    assert loaded["urls"].get("WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL")
    restored = copy.deepcopy(loaded)
    del restored["passwords"][ASSET_ROLE]
    del restored["urls"]["WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL"]
    assert restored == before
    assert module.load() == loaded
    assert json.loads(path.read_text("utf-8")) == loaded
    assert "wso_asset_owner" not in loaded["passwords"]
    assert loaded["passwords"][ASSET_ROLE] not in (tmp_path / "env.ps1").read_text(
        "utf-8"
    )


@pytest.mark.parametrize("helper", ["local"], indirect=True)
def test_local_load_repairs_only_missing_asset_url(helper, tmp_path):
    before = old_state()
    before["passwords"][ASSET_ROLE] = "retained-fixture-asset"
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(before), "utf-8")
    loaded = helper[1].load()
    assert loaded["passwords"] == before["passwords"]
    added_url = loaded["urls"].pop("WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL")
    assert loaded == before
    assert added_url == (
        "postgresql+psycopg://wso_asset_maintenance:retained-fixture-asset"
        "@127.0.0.1:57056/wso_test"
    )


@pytest.mark.parametrize(
    "revisions", [(), ("0003_jobs", "0003a_assets"), ("0003a_assets",) * 2]
)
@pytest.mark.parametrize("helper", ["local"], indirect=True)
def test_local_status_refuses_invalid_revision_rows_before_catalog(
    helper, monkeypatch, tmp_path, revisions
):
    catalog = Catalog(revisions)
    with pytest.raises(RuntimeError, match="single"):
        invoke(helper, catalog, monkeypatch, tmp_path, status=True)
    assert catalog.catalog_reads == 0
    assert catalog.writes == []


@pytest.mark.parametrize("head", ("0003a_assets", "0004_future"))
@pytest.mark.parametrize("helper", ["local"], indirect=True)
def test_local_status_refuses_missing_asset_role_after_migration(
    helper, monkeypatch, tmp_path, head
):
    catalog = Catalog((head,), {role: SAFE for role in LEGACY_ROLES[1:]})
    with pytest.raises(RuntimeError, match="missing"):
        invoke(helper, catalog, monkeypatch, tmp_path, status=True)
    assert catalog.writes == []


@pytest.mark.parametrize("role", LEGACY_ROLES[1:])
@pytest.mark.parametrize("direction", [(1, 0), (0, 1)])
@pytest.mark.parametrize("helper", ["local"], indirect=True)
def test_local_status_rejects_memberships_for_every_legacy_login(
    helper, monkeypatch, tmp_path, role, direction
):
    rows = {name: SAFE for name in (*LEGACY_ROLES[1:], ASSET_ROLE)}
    rows[role] = (*SAFE[:7], direction)
    with pytest.raises(RuntimeError):
        invoke(helper, Catalog(rows=rows), monkeypatch, tmp_path, status=True)
