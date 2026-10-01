"""Migration SQL generation must not require a live database."""

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "direction,revision",
    [("upgrade", "head"), ("downgrade", "0005_tvt_credentials:0004_tvt_domain")],
)
def test_credential_migration_generates_executable_snapshot_sql(direction, revision):
    config = Config(str(ROOT / "infra/alembic.ini"))
    output = io.StringIO()
    with redirect_stdout(output):
        getattr(command, direction)(config, revision, sql=True)
    sql = output.getvalue()
    assert "pg_get_functiondef" in sql
    assert "EXECUTE definition" in sql
    assert "credential foundation entry point not found" in sql
    for name in (
        "wso_issue_connection_handle",
        "wso_issue_job_connection_handle",
        "wso_redeem_connection_handle",
        "wso_use_connection_lease",
    ):
        assert "wso_private.credential_original_" + name in sql
    assert sql.lstrip().startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;")


@pytest.mark.parametrize("installed", [[], ["old"], ["tip", "other"], ["tip", "tip"]])
def test_budget_fixture_rejects_missing_stale_or_multiple_installed_heads(
    tmp_path, installed
):
    from sqlalchemy import create_engine, text

    from tests.integration.test_asset_db_budget import _assert_source_head

    config = _revision_config(tmp_path)
    with create_engine("sqlite://").begin() as db:
        db.execute(text("CREATE TABLE alembic_version(version_num text)"))
        for revision in installed:
            db.execute(
                text("INSERT INTO alembic_version VALUES(:revision)"),
                {"revision": revision},
            )
        with pytest.raises(AssertionError, match="installed revision"):
            _assert_source_head(db, config)


def _revision_config(tmp_path, *, branches=False):
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "tip.py").write_text("revision = 'tip'\ndown_revision = None\n")
    if branches:
        (versions / "other.py").write_text("revision = 'other'\ndown_revision = None\n")
    config = Config()
    config.set_main_option("script_location", str(tmp_path))
    return config


@pytest.mark.parametrize("branches", [False, True])
def test_budget_fixture_checks_source_graph_instead_of_a_fixed_revision(
    tmp_path, branches
):
    from sqlalchemy import create_engine, text

    from tests.integration.test_asset_db_budget import _assert_source_head

    config = _revision_config(tmp_path, branches=branches)
    with create_engine("sqlite://").begin() as db:
        db.execute(text("CREATE TABLE alembic_version(version_num text)"))
        db.execute(text("INSERT INTO alembic_version VALUES('tip')"))
        if branches:
            with pytest.raises(AssertionError, match="exactly one source head"):
                _assert_source_head(db, config)
        else:
            _assert_source_head(db, config)


def _private_table(name, owner, **changes):
    from types import SimpleNamespace

    values = {
        "relname": name,
        "owner": owner,
        "relrowsecurity": True,
        "relforcerowsecurity": True,
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcanlogin": False,
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "bad",
    [
        ("tvt_identities", "wso_app", {}),
        ("tvt_identities", "wso_migrator", {}),
        ("tvt_identities", None, {}),
        ("unexpected_private", "wso_domain_owner", {}),
        ("dispatch_ready", "wso_domain_owner", {}),
        ("tenant_grants", "wso_domain_owner", {}),
        ("tvt_identities", "wso_domain_owner", {"rolcanlogin": True}),
        ("tvt_identities", "wso_domain_owner", {"rolsuper": True}),
        ("tvt_identities", "wso_domain_owner", {"rolbypassrls": True}),
        ("tvt_identities", "wso_domain_owner", {"rolcreaterole": True}),
        ("tvt_identities", "wso_domain_owner", {"relrowsecurity": False}),
        ("tvt_identities", "wso_domain_owner", {"relforcerowsecurity": False}),
    ],
)
def test_private_table_owner_gate_rejects_unknown_or_unsafe_ownership(bad):
    from tests.integration.test_tenant_isolation import _assert_private_table_owners

    name, owner, changes = bad
    tables = [
        _private_table("tenant_grants", "wso_migrator"),
        _private_table("tenant_contexts", "wso_migrator"),
        _private_table(name, owner, **changes),
    ]
    with pytest.raises(AssertionError):
        _assert_private_table_owners(tables)


def test_private_table_owner_gate_accepts_exact_domain_dispatch_and_foundation_owners():
    from tests.integration.test_tenant_isolation import _assert_private_table_owners

    _assert_private_table_owners(
        [
            _private_table("tenant_grants", "wso_migrator"),
            _private_table("tenant_contexts", "wso_migrator"),
            _private_table("dispatch_ready", "wso_dispatch_owner"),
            _private_table("tvt_identities", "wso_domain_owner"),
            _private_table("domain_credential_capabilities", "wso_domain_owner"),
            _private_table("domain_credential_connections", "wso_domain_owner"),
            _private_table("tvt_user_preferences", "wso_domain_owner"),
            _private_table("tvt_user_consents", "wso_domain_owner"),
        ]
    )


def test_private_table_owner_gate_rejects_missing_foundation_tables():
    from tests.integration.test_tenant_isolation import _assert_private_table_owners

    with pytest.raises(AssertionError):
        _assert_private_table_owners(
            [_private_table("tvt_identities", "wso_domain_owner")]
        )
