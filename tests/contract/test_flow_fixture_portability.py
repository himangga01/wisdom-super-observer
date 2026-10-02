"""Offline guard contracts; AST loading never imports SQL acceptance fixtures."""

import ast
import hashlib
import ipaddress
import json
import re
import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
PIN = "3a2fc52bb33a86058d5f13d36f6112986f1ef4117032c64cc268e2e88f61572e"
SOURCE = ROOT / "tests/integration/test_tvt_account_flow_admission.py"

# Independent canonical inputs copied from Root e216 offline0010 inventory.
# Offline SQL (strict LF) SHA256: 5b0b4e165056d76d3e488164bdfe84a76fac09a17ec35ce315cbbd22f72cd19e
APPROVED_LINUX_TABLES = (
    "public.alembic_version",
    "public.assets",
    "public.audit_events",
    "public.connections",
    "public.inbox_dedup",
    "public.job_assets",
    "public.job_connections",
    "public.job_items",
    "public.jobs",
    "public.memberships",
    "public.outbox",
    "public.store_connections",
    "public.store_memberships",
    "public.stores",
    "public.tenants",
    "public.users",
    "public.web_sessions",
    "wso_private.asset_audit_outbox",
    "wso_private.asset_cleanup",
    "wso_private.asset_job_kinds",
    "wso_private.asset_read_leases",
    "wso_private.asset_reconciliation",
    "wso_private.asset_settings",
    "wso_private.asset_tickets",
    "wso_private.asset_uploads",
    "wso_private.connection_handles",
    "wso_private.connection_leases",
    "wso_private.connection_revocations",
    "wso_private.connection_secrets",
    "wso_private.dispatch_ready",
    "wso_private.domain_credential_capabilities",
    "wso_private.domain_credential_connections",
    "wso_private.job_contexts",
    "wso_private.job_kinds",
    "wso_private.job_settings",
    "wso_private.operation_constraint_backup",
    "wso_private.operation_holds",
    "wso_private.operation_target_observations",
    "wso_private.operation_tickets",
    "wso_private.operations",
    "wso_private.tenant_contexts",
    "wso_private.tenant_grants",
    "wso_private.tvt_account_challenges",
    "wso_private.tvt_account_sessions",
    "wso_private.tvt_account_storage",
    "wso_private.tvt_account_tickets",
    "wso_private.tvt_account_tokens",
    "wso_private.tvt_capability_snapshots",
    "wso_private.tvt_channels",
    "wso_private.tvt_device_links",
    "wso_private.tvt_device_store_links",
    "wso_private.tvt_flow_intents",
    "wso_private.tvt_flow_policies",
    "wso_private.tvt_flow_tickets",
    "wso_private.tvt_flows",
    "wso_private.tvt_identities",
    "wso_private.tvt_identity_grants",
    "wso_private.tvt_upstream_grants",
    "wso_private.tvt_user_consents",
    "wso_private.tvt_user_preferences",
    "wso_private.tyco_capability_snapshots",
    "wso_private.tyco_identities",
    "wso_private.tyco_identity_grants",
    "wso_private.tyco_panels",
    "wso_private.tyco_upstream_grants",
)


def extracted(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
    exec(  # noqa: S102 -- trusted repository functions, no module import or SQL startup
        compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace
    )
    return namespace


def helpers(platform="win32", environment=None):
    namespace = {
        "sys": SimpleNamespace(platform=platform),
        "os": SimpleNamespace(environ=environment or {}),
        "hashlib": hashlib,
        "re": re,
        "pytest": pytest,
        "ROOT": ROOT,
        "text": lambda value: value,
        "make_url": make_url,
    }
    return extracted(
        SOURCE,
        {
            "flow_source_expectations",
            "flow_parent_sha256",
            "flow_source_snapshot",
            "flow_linux_table_roster",
            "verify_flow_linux_tables",
            "verify_flow_recovery_fixture",
        },
        namespace,
    )


class ReadOnlySource:
    def __init__(self, platform, events, **changes):
        self.events = events
        self.identity = {
            "name": "wso_test" if platform == "win32" else "wso_ci_test",
            "oid": 16384 if platform == "win32" else 16385,
            "owner": "postgres",
            "revision": "0003a_assets"
            if platform == "win32"
            else "0010_tvt_account_flows",
            "count": 36 if platform == "win32" else 65,
        } | changes
        canonical = [tuple(name.split(".")) for name in APPROVED_LINUX_TABLES]
        self.tables = (
            [("public", f"table_{i}") for i in range(self.identity["count"])]
            if platform == "win32"
            else canonical[: self.identity["count"]]
        )
        if platform == "linux" and self.identity["count"] > 65:
            self.tables += [("public", "job_recovery_effects")]
        self.recovery = {
            "identity": ("wso_migrator", True, True, "r", "p", False, True, True),
            "columns": [
                (name, kind, True, None, "", "", True)
                for name, kind in [
                    ("tenant_id", "uuid"),
                    ("job_id", "uuid"),
                    ("effect_count", "bigint"),
                ]
            ],
            "constraints": [
                (
                    "c",
                    ["effect_count"],
                    None,
                    None,
                    [],
                    None,
                    None,
                    False,
                    False,
                    True,
                    "effect_count>0",
                ),
                (
                    "f",
                    ["job_id"],
                    "public",
                    "jobs",
                    ["id"],
                    "a",
                    "c",
                    False,
                    False,
                    True,
                    None,
                ),
                ("p", ["job_id"], None, None, [], None, None, False, False, True, None),
            ],
            "policies": [
                (
                    "recovery_worker",
                    "*",
                    True,
                    ["wso_job_worker"],
                    "(job_id = wso_current_job_id())",
                    "(job_id = wso_current_job_id())",
                )
            ],
            "acls": [
                ("wso_migrator", "wso_job_worker", privilege, False)
                for privilege in ("INSERT", "SELECT", "UPDATE")
            ],
        }

    @contextmanager
    def connect(self):
        self.events.append("source-read")
        yield self

    def execute(self, query):
        for signature, field in [
            ("AS recovery_owner", "identity"),
            ("FROM pg_attribute", "columns"),
            ("FROM pg_constraint", "constraints"),
            ("FROM pg_policy", "policies"),
            ("aclexplode", "acls"),
        ]:
            if signature in query:
                self.events.append(("recovery-read", field))
                result = self.recovery[field]
                if field == "constraints" and "confmatchtype" in query:
                    result = [
                        (
                            *row[:7],
                            self.recovery.get("fk_match", "s")
                            if row[0] == "f"
                            else None,
                            self.recovery.get("check_noinherit", False)
                            if row[0] == "c"
                            else None,
                            *row[7:],
                        )
                        for row in result
                    ]
                return SimpleNamespace(
                    one=lambda result=result: result,
                    all=lambda result=result: result,
                )
        if "pg_database" in query:
            return SimpleNamespace(
                one=lambda: tuple(
                    self.identity[key] for key in ("name", "oid", "owner")
                )
            )
        if "alembic_version" in query:
            return SimpleNamespace(scalar_one=lambda: self.identity["revision"])
        if "c.relkind::text" in query:
            return SimpleNamespace(
                all=lambda: [(schema, name, "r") for schema, name in self.tables]
            )
        return SimpleNamespace(all=lambda: self.tables)


def snapshot_helpers(platform, events, *, guard_error=False):
    namespace = helpers(platform)

    def guard(source, *, domain_only):
        events.append(("managed-guard", domain_only))
        if guard_error:
            raise ValueError("managed guard refused")

    namespace["verify_fixture_database"] = guard
    namespace["foundation_contents"] = lambda db, tables: {
        table: ("wso_migrator", f"digest_{i}") for i, table in enumerate(tables)
    }
    return namespace


@pytest.mark.parametrize(
    "platform,count,name", [("win32", 36, "wso_test"), ("linux", 65, "wso_ci_test")]
)
def test_snapshot_validates_platform_source_and_keeps_all_owner_row_digests(
    platform, count, name
):
    events = []
    actual = snapshot_helpers(platform, events)["flow_source_snapshot"](
        ReadOnlySource(platform, events)
    )
    assert actual[0][0] == name
    assert len(actual[2]) == count
    last = (
        ("public", "table_35")
        if platform == "win32"
        else ("wso_private", "tyco_upstream_grants")
    )
    assert actual[2][last] == (
        "wso_migrator",
        f"digest_{count - 1}",
    )
    assert events == [("managed-guard", platform == "win32"), "source-read"]


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize(
    "change",
    [
        {"name": "business"},
        {"owner": "foreign"},
        {"oid": 0},
        {"oid": -1},
        {"oid": True},
        {"revision": "0009_asset_read_denial"},
        {"revision": "head"},
        {"count": 39},
        {"count": 41},
    ],
)
def test_source_metadata_mismatch_is_refused(platform, change):
    events = []
    with pytest.raises((AssertionError, ValueError)):
        snapshot_helpers(platform, events)["flow_source_snapshot"](
            ReadOnlySource(platform, events, **change)
        )


def test_windows_source_oid_is_exact():
    events = []
    with pytest.raises((AssertionError, ValueError)):
        snapshot_helpers("win32", events)["flow_source_snapshot"](
            ReadOnlySource("win32", events, oid=16385)
        )


@pytest.mark.parametrize("platform", ["darwin", "cygwin", "win64", ""])
def test_unsupported_platform_cannot_select_an_owned_source(platform):
    with pytest.raises(ValueError):
        helpers(platform)["flow_source_expectations"]()


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_guard_refusal_prevents_source_read(platform):
    events = []
    with pytest.raises(ValueError, match="managed guard refused"):
        snapshot_helpers(platform, events, guard_error=True)["flow_source_snapshot"](
            ReadOnlySource(platform, events)
        )
    assert events == [("managed-guard", platform == "win32")]


def test_missing_activation_skips_without_reading_parent():
    with pytest.raises(pytest.skip.Exception):
        helpers()["flow_parent_sha256"]()


@pytest.mark.parametrize("activation", ["0", "true", "2", " 1"])
def test_invalid_explicit_activation_is_refused(activation):
    with pytest.raises(AssertionError):
        helpers(
            environment={
                "WSO_TEST_W06_FLOW_ACCEPTANCE": activation,
                "WSO_TEST_W06_PARENT_SHA256": PIN,
            }
        )["flow_parent_sha256"]()


@pytest.mark.parametrize("pin", [None, "", "a" * 64, PIN.upper(), PIN + "\n"])
def test_missing_or_nonreviewed_parent_pin_is_refused(pin):
    env = {"WSO_TEST_W06_FLOW_ACCEPTANCE": "1"}
    if pin is not None:
        env["WSO_TEST_W06_PARENT_SHA256"] = pin
    with pytest.raises(AssertionError):
        helpers(environment=env)["flow_parent_sha256"]()


def test_reviewed_parent_bytes_are_accepted_and_changed_bytes_refused(tmp_path):
    namespace = helpers(
        environment={
            "WSO_TEST_W06_FLOW_ACCEPTANCE": "1",
            "WSO_TEST_W06_PARENT_SHA256": PIN,
        }
    )
    assert namespace["flow_parent_sha256"]() == PIN
    namespace["ROOT"] = tmp_path
    parent = tmp_path / "infra/migrations/versions/0009_asset_read_denial.py"
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"unreviewed parent")
    with pytest.raises(AssertionError):
        namespace["flow_parent_sha256"]()
    namespace["os"].environ["WSO_TEST_W06_PARENT_SHA256"] = hashlib.sha256(
        parent.read_bytes()
    ).hexdigest()
    with pytest.raises(AssertionError):
        namespace["flow_parent_sha256"]()


def test_fixture_activation_precedes_url_access_and_engine_creation():
    namespace = helpers()
    namespace["flow_parent_sha256"] = lambda: pytest.skip("not activated")
    namespace["create_engine"] = lambda *args, **kwargs: pytest.fail("opened SQL")
    extracted(SOURCE, {"flow_database"}, namespace)
    with pytest.raises(pytest.skip.Exception):
        next(namespace["flow_database"]())


def test_linux_fixture_reaches_managed_source_guard_before_private_database_control():
    roles = (
        "ADMIN",
        "APP",
        "IDENTITY",
        "MIGRATOR",
        "SESSION",
        "WORKER",
        "DISPATCH",
        "JOB",
        "ASSET_MAINTENANCE",
    )
    env = {
        f"WSO_TEST_{role}_DATABASE_URL": "postgresql+psycopg://postgres:synthetic@127.0.0.1:55432/wso_ci_test"
        for role in roles
    }
    env.update(WSO_TEST_W06_FLOW_ACCEPTANCE="1", WSO_TEST_W06_PARENT_SHA256=PIN)
    namespace = helpers("linux", env)
    events = []

    class GuardReached(Exception):
        pass

    def snapshot(source):
        raise GuardReached

    def engine(url, **options):
        events.append(url.database)
        return SimpleNamespace()

    namespace.update(
        flow_source_snapshot=snapshot, create_engine=engine, uuid4=uuid4, re=re
    )
    extracted(SOURCE, {"flow_database"}, namespace)
    with pytest.raises(GuardReached):
        next(namespace["flow_database"]())
    assert events == ["wso_ci_test"]


def managed_guard(tmp_path, platform, *, missing=None, invalid=None):
    owner = "a" * 32
    database = "wso_test" if platform == "win32" else "wso_ci_test"
    url = make_url(
        f"postgresql+psycopg://postgres:synthetic@127.0.0.1:55432/{database}"
    )
    runtime = tmp_path / ".superpowers/runtime/postgresql17"
    (runtime / "data").mkdir(parents=True)
    (runtime / "credentials.json").write_text(
        json.dumps(
            {
                "urls": {
                    "WSO_TEST_ADMIN_DATABASE_URL": url.render_as_string(
                        hide_password=False
                    )
                },
                "port": 55432,
                "database": "wso_test",
            }
        )
    )
    env = {
        "WSO_TEST_ADMIN_DATABASE_URL": url.render_as_string(hide_password=False),
        "CI": "true",
        "WSO_CI_DISPOSABLE_POSTGRES": "1",
        "WSO_TEST_RECOVERY_DATABASE_NAME": "wso_ci_test",
        "WSO_TEST_RECOVERY_DATABASE_OWNER": "postgres",
        "WSO_CI_RUNTIME_OWNER": owner,
    }
    if missing:
        env.pop(missing)
    if invalid:
        env[invalid] = (
            url.set(database="business").render_as_string(hide_password=False)
            if invalid == "WSO_TEST_ADMIN_DATABASE_URL"
            else "foreign"
        )
    container = {
        "Name": f"/wso-ci-postgres-{owner}",
        "Config": {
            "Image": "postgres@sha256:" + "b" * 64,
            "Labels": {"wso.ci.owner": owner},
        },
        "State": {"Running": True},
        "NetworkSettings": {
            "Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55432"}]},
            "Networks": {"bridge": {"IPAddress": "172.17.0.2"}},
        },
        "Mounts": [
            {
                "Destination": "/var/lib/postgresql/data",
                "Type": "volume",
                "Name": f"wso-ci-postgres-data-{owner}",
                "RW": True,
            }
        ],
    }
    volume = {
        "Name": f"wso-ci-postgres-data-{owner}",
        "Labels": {"wso.ci.owner": owner},
    }
    namespace = {
        "__file__": str(tmp_path / "tests/support/job_handlers.py"),
        "Path": Path,
        "make_url": make_url,
        "re": re,
        "json": json,
        "ipaddress": ipaddress,
        "sys": SimpleNamespace(platform=platform),
        "os": SimpleNamespace(environ=env),
        "text": lambda value: value,
        "subprocess": SimpleNamespace(
            SubprocessError=subprocess.SubprocessError,
            run=lambda args, **kw: SimpleNamespace(
                stdout=json.dumps([volume if "volume" in args else container])
            ),
        ),
    }
    extracted(
        ROOT / "tests/support/job_handlers.py", {"verify_fixture_database"}, namespace
    )
    state = {
        "db": database,
        "actor": "postgres",
        "owner": "postgres",
        "version": "170011",
        "address": "127.0.0.1" if platform == "win32" else "172.17.0.2",
        "port": 55432 if platform == "win32" else 5432,
        "directory": str(runtime / "data")
        if platform == "win32"
        else "/var/lib/postgresql/data",
    }
    source = ReadOnlySource(platform, [])
    source.url = url
    metadata_execute = source.execute
    source.execute = lambda query: (
        SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: state))
        if "current_database() AS db" in query
        else metadata_execute(query)
    )
    return namespace["verify_fixture_database"], source, container


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_real_managed_guard_accepts_only_platform_owned_runtime(tmp_path, platform):
    guard, source, _ = managed_guard(tmp_path, platform)
    namespace = snapshot_helpers(platform, [])
    namespace["verify_fixture_database"] = guard
    result = namespace["flow_source_snapshot"](source)
    assert result[0][0] == ("wso_test" if platform == "win32" else "wso_ci_test")


@pytest.mark.parametrize(
    "key",
    [
        "WSO_TEST_ADMIN_DATABASE_URL",
        "CI",
        "WSO_CI_DISPOSABLE_POSTGRES",
        "WSO_TEST_RECOVERY_DATABASE_NAME",
        "WSO_TEST_RECOVERY_DATABASE_OWNER",
        "WSO_CI_RUNTIME_OWNER",
    ],
)
@pytest.mark.parametrize("mode", ["missing", "invalid"])
def test_real_linux_guard_refuses_missing_or_invalid_ownership_activation(
    tmp_path, key, mode
):
    guard, source, _ = managed_guard(tmp_path, "linux", **{mode: key})
    namespace = helpers("linux")
    namespace["verify_fixture_database"] = guard
    with pytest.raises(ValueError):
        namespace["flow_source_snapshot"](source)


def test_real_linux_guard_refuses_container_owner_mismatch(tmp_path):
    guard, source, container = managed_guard(tmp_path, "linux")
    container["Config"]["Labels"]["wso.ci.owner"] = "foreign"
    namespace = helpers("linux")
    namespace["verify_fixture_database"] = guard
    with pytest.raises(ValueError, match="ownership mismatch"):
        namespace["flow_source_snapshot"](source)


@pytest.mark.parametrize(
    "with_recovery", [False, True], ids=["canonical65", "known-recovery66"]
)
def test_linux_accepts_exact_canonical_roster_and_validated_optional_fixture(
    with_recovery,
):
    events = []
    source = ReadOnlySource("linux", events, count=66 if with_recovery else 65)
    actual = snapshot_helpers("linux", events)["flow_source_snapshot"](source)
    assert len(actual[2]) == (66 if with_recovery else 65)
    assert actual[0] == ("wso_ci_test", 16385, "postgres")
    assert (
        any(event == ("recovery-read", "identity") for event in events) is with_recovery
    )


def test_linux_refuses_legacy_same_count_foreign_roster():
    events = []
    source = ReadOnlySource("linux", events, count=40)
    source.tables = [("public", f"foreign_{i}") for i in range(40)]
    with pytest.raises((AssertionError, ValueError)):
        snapshot_helpers("linux", events)["flow_source_snapshot"](source)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "substituted", "duplicate", "recovery-wrong-schema"],
)
def test_linux_refuses_any_noncanonical_roster_even_at_accepted_count(mutation):
    events = []
    source = ReadOnlySource("linux", events)
    if mutation == "missing":
        source.tables.pop()
    elif mutation == "extra":
        source.tables.append(("public", "foreign"))
    elif mutation == "substituted":
        source.tables[-1] = ("public", "foreign")
    elif mutation == "duplicate":
        source.tables[-1] = source.tables[0]
    else:
        source.tables.append(("wso_private", "job_recovery_effects"))
    with pytest.raises((AssertionError, ValueError)):
        snapshot_helpers("linux", events)["flow_source_snapshot"](source)


@pytest.mark.parametrize(
    "field,index,value",
    [
        ("identity", 0, "postgres"),
        ("identity", 1, False),
        ("identity", 2, False),
        ("identity", 3, "p"),
        ("identity", 4, "u"),
        ("identity", 5, True),
        ("identity", 6, False),
        ("identity", 7, False),
    ],
)
def test_optional_recovery_identity_and_owner_acl_are_exact(field, index, value):
    events = []
    source = ReadOnlySource("linux", events, count=66)
    changed = list(source.recovery[field])
    changed[index] = value
    source.recovery[field] = tuple(changed)
    with pytest.raises((AssertionError, ValueError)):
        snapshot_helpers("linux", events)["flow_source_snapshot"](source)


@pytest.mark.parametrize(
    "mutation",
    [
        "column-name",
        "column-type",
        "nullable",
        "default",
        "identity",
        "generated",
        "column-acl",
        "extra-column",
        "constraint-check",
        "constraint-delete",
        "constraint-reference",
        "constraint-deferrable",
        "constraint-unvalidated",
        "extra-constraint",
        "policy-name",
        "policy-command",
        "policy-restrictive",
        "policy-role",
        "policy-using",
        "policy-check",
        "extra-policy",
        "missing-acl",
        "extra-acl",
        "public-acl",
        "acl-grant-option",
        "acl-grantor",
    ],
)
def test_optional_recovery_schema_policy_and_acl_mismatches_fail_closed(mutation):
    events = []
    source = ReadOnlySource("linux", events, count=66)
    if mutation.startswith("column-") or mutation == "nullable":
        position = {
            "column-name": 0,
            "column-type": 1,
            "nullable": 2,
            "default": 3,
            "identity": 4,
            "generated": 5,
            "column-acl": 6,
        }.get(mutation, 0)
        value = {0: "foreign", 1: "text", 2: False, 6: False}.get(position, "foreign")
        row = list(source.recovery["columns"][0])
        row[position] = value
        source.recovery["columns"][0] = tuple(row)
    elif mutation in {"default", "identity", "generated"}:
        position = {"default": 3, "identity": 4, "generated": 5}[mutation]
        row = list(source.recovery["columns"][0])
        row[position] = "foreign"
        source.recovery["columns"][0] = tuple(row)
    elif mutation == "extra-column":
        source.recovery["columns"].append(source.recovery["columns"][0])
    elif mutation.startswith("constraint-"):
        row_index, position, value = {
            "constraint-check": (0, 10, "effect_count>=0"),
            "constraint-delete": (1, 6, "a"),
            "constraint-reference": (1, 3, "users"),
            "constraint-deferrable": (1, 7, True),
            "constraint-unvalidated": (1, 9, False),
        }[mutation]
        row = list(source.recovery["constraints"][row_index])
        row[position] = value
        source.recovery["constraints"][row_index] = tuple(row)
    elif mutation == "extra-constraint":
        source.recovery["constraints"].append(source.recovery["constraints"][0])
    elif mutation.startswith("policy-"):
        position, value = {
            "policy-name": (0, "foreign"),
            "policy-command": (1, "r"),
            "policy-restrictive": (2, False),
            "policy-role": (3, ["PUBLIC"]),
            "policy-using": (4, "true"),
            "policy-check": (5, "true"),
        }[mutation]
        row = list(source.recovery["policies"][0])
        row[position] = value
        source.recovery["policies"][0] = tuple(row)
    elif mutation == "extra-policy":
        source.recovery["policies"].append(source.recovery["policies"][0])
    elif mutation == "missing-acl":
        source.recovery["acls"].pop()
    elif mutation in {"extra-acl", "public-acl"}:
        source.recovery["acls"].append(
            (
                "wso_migrator",
                "PUBLIC" if mutation == "public-acl" else "wso_app",
                "SELECT",
                False,
            )
        )
    else:
        row = list(source.recovery["acls"][0])
        row[3 if mutation == "acl-grant-option" else 0] = (
            True if mutation == "acl-grant-option" else "postgres"
        )
        source.recovery["acls"][0] = tuple(row)
    with pytest.raises((AssertionError, ValueError)):
        snapshot_helpers("linux", events)["flow_source_snapshot"](source)


def test_optional_recovery_public_qualified_policy_is_accepted():
    events = []
    source = ReadOnlySource("linux", events, count=66)
    source.recovery["policies"] = [
        (
            "recovery_worker",
            "*",
            True,
            ["wso_job_worker"],
            "(job_id = public.wso_current_job_id())",
            "(job_id = public.wso_current_job_id())",
        )
    ]
    assert (
        len(snapshot_helpers("linux", events)["flow_source_snapshot"](source)[2]) == 66
    )


def test_linux_roster_is_bound_to_reviewed0010_source_bytes():
    assert (
        hashlib.sha256(
            (ROOT / "infra/migrations/versions/0010_tvt_account_flows.py").read_bytes()
        ).hexdigest()
        == "a8c39baf215e3b8fea4b92e5df96c21bf1701b9edbb7d61f62e27860af2e5958"
    )
    assert helpers("linux")["flow_linux_table_roster"]() == frozenset(
        tuple(name.split(".")) for name in APPROVED_LINUX_TABLES
    )


@pytest.mark.parametrize("field,value", [("fk_match", "f"), ("check_noinherit", True)])
def test_optional_recovery_constraint_match_and_inheritance_are_exact(field, value):
    events = []
    source = ReadOnlySource("linux", events, count=66)
    source.recovery[field] = value
    with pytest.raises((AssertionError, ValueError)):
        snapshot_helpers("linux", events)["flow_source_snapshot"](source)


class CatalogSource(ReadOnlySource):
    """Execute the extracted query's real predicate on an offline catalog."""

    def __init__(self, platform, events, objects):
        super().__init__(platform, events)
        self.catalog = sqlite3.connect(":memory:")
        self.catalog.execute("CREATE TABLE pg_namespace(oid integer,nspname text)")
        self.catalog.execute(
            "CREATE TABLE pg_class(relnamespace integer,relname text,relkind text)"
        )
        self.catalog.executemany(
            "INSERT INTO pg_namespace VALUES (?,?)",
            [(1, "public"), (2, "wso_private")],
        )
        self.catalog.executemany(
            "INSERT INTO pg_class VALUES (?,?,?)",
            [
                (1 if schema == "public" else 2, name, kind)
                for schema, name, kind in objects
            ],
        )
        self.inventory_queries = []
        self.inventory_observations = []

    def execute(self, query):
        if query.lstrip().startswith("SELECT n.nspname,c.relname"):
            self.inventory_queries.append(query)
            # SQLite supplies only the catalog rows. Remove PostgreSQL's text
            # cast; keep the actual SELECT/JOIN/namespace/kind predicate/order.
            result = self.catalog.execute(
                query.replace("c.relkind::text", "c.relkind")
            ).fetchall()
            self.inventory_observations = result
            return SimpleNamespace(all=lambda: result)
        return super().execute(query)


def catalog_snapshot_helpers(platform, events):
    namespace = snapshot_helpers(platform, events)
    capture_contents = namespace["foundation_contents"]

    def contents(db, tables):
        events.append("foundation-row-read")
        return capture_contents(db, tables)

    namespace["foundation_contents"] = contents
    return namespace


@pytest.mark.parametrize("kind", ["p", "f"], ids=["partitioned", "foreign"])
@pytest.mark.parametrize(
    "location",
    [
        ("public", "job_recovery_effects", False),
        ("public", "arbitrary_extra", False),
        ("wso_private", "arbitrary_extra", False),
        ("public", "assets", True),
        ("wso_private", "tvt_flows", True),
    ],
    ids=[
        "recovery",
        "public-extra",
        "private-extra",
        "canonical-public",
        "canonical-private",
    ],
)
def test_linux_catalog_rejects_nonordinary_table_objects_before_any_row_read(
    kind, location
):
    events = []
    schema, name, replacement = location
    objects = [(*table.split("."), "r") for table in APPROVED_LINUX_TABLES]
    if replacement:
        objects.remove((schema, name, "r"))
    objects.append((schema, name, kind))
    source = CatalogSource("linux", events, objects)
    try:
        with pytest.raises(AssertionError):
            catalog_snapshot_helpers("linux", events)["flow_source_snapshot"](source)
        assert len(source.inventory_queries) == 1
        assert (schema, name, kind) in source.inventory_observations
        assert "foundation-row-read" not in events
        assert not any(
            isinstance(event, tuple) and event[0] == "recovery-read" for event in events
        )
    finally:
        source.catalog.close()


@pytest.mark.parametrize(
    "recovery", [False, True], ids=["canonical65", "ordinary-recovery66"]
)
def test_linux_real_catalog_predicate_accepts_canonical_ordinary_inventory(recovery):
    events = []
    objects = [(*table.split("."), "r") for table in APPROVED_LINUX_TABLES]
    if recovery:
        objects.append(("public", "job_recovery_effects", "r"))
    source = CatalogSource("linux", events, objects)
    try:
        result = catalog_snapshot_helpers("linux", events)["flow_source_snapshot"](
            source
        )
        assert len(result[2]) == (66 if recovery else 65)
        assert len(source.inventory_queries) == 1
        assert events.count("foundation-row-read") == 1
        assert (("recovery-read", "identity") in events) is recovery
    finally:
        source.catalog.close()


@pytest.mark.parametrize("kind", ["p", "f"])
def test_windows_catalog_path_retains_owned36_ordinary_table_selection(kind):
    events = []
    objects = [("public", f"table_{i}", "r") for i in range(36)]
    objects.append(("public", "extra_nonordinary", kind))
    source = CatalogSource("win32", events, objects)
    try:
        result = catalog_snapshot_helpers("win32", events)["flow_source_snapshot"](
            source
        )
        assert len(result[2]) == 36
        assert events[0] == ("managed-guard", True)
        assert events.count("foundation-row-read") == 1
        assert not any(
            isinstance(event, tuple) and event[0] == "recovery-read" for event in events
        )
    finally:
        source.catalog.close()
