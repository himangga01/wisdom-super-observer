"""Offline guard contracts; AST loading never imports SQL acceptance fixtures."""

import ast
import hashlib
import ipaddress
import json
import re
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
            "count": 36 if platform == "win32" else 40,
        } | changes

    @contextmanager
    def connect(self):
        self.events.append("source-read")
        yield self

    def execute(self, query):
        if "pg_database" in query:
            return SimpleNamespace(
                one=lambda: tuple(
                    self.identity[key] for key in ("name", "oid", "owner")
                )
            )
        if "alembic_version" in query:
            return SimpleNamespace(scalar_one=lambda: self.identity["revision"])
        return SimpleNamespace(
            all=lambda: [
                ("public", f"table_{i}") for i in range(self.identity["count"])
            ]
        )


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
    "platform,count,name", [("win32", 36, "wso_test"), ("linux", 40, "wso_ci_test")]
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
    assert actual[2][("public", f"table_{count - 1}")] == (
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
