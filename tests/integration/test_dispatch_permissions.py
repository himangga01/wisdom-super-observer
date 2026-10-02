"""Durable job security checks against real PostgreSQL."""

import os

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture(autouse=True)
def require_postgresql_roles():
    if not all(
        os.getenv(f"WSO_TEST_{role}_DATABASE_URL")
        for role in ("ADMIN", "APP", "IDENTITY", "SESSION", "WORKER", "DISPATCH", "JOB")
    ):
        pytest.skip(
            "requires explicit PostgreSQL runtime role URLs; strict PostgreSQL gate rejects skips"
        )


def test_jobs_are_durable_forced_rls_tables():
    url = os.environ["WSO_TEST_ADMIN_DATABASE_URL"]
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as db:
            rows = db.execute(
                text(
                    "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('jobs','outbox','inbox_dedup','dispatch_ready','job_contexts','job_kinds','job_connections','job_items')"
                )
            ).all()
            assert {r.relname for r in rows} == {
                "jobs",
                "outbox",
                "inbox_dedup",
                "dispatch_ready",
                "job_contexts",
                "job_kinds",
                "job_connections",
                "job_items",
            }
            assert all(r.relrowsecurity and r.relforcerowsecurity for r in rows)
    finally:
        engine.dispose()


@pytest.mark.parametrize("role", ["DISPATCH", "JOB", "IDENTITY", "SESSION", "WORKER"])
@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM wso_private.connection_secrets",
        "SELECT * FROM wso_private.tenant_contexts",
        "SELECT * FROM wso_private.job_contexts",
        "SELECT * FROM wso_private.job_kinds",
        "SELECT * FROM wso_private.job_settings",
        "SELECT * FROM public.memberships",
        "SET ROLE wso_job_owner",
        "SET ROLE wso_dispatch_owner",
    ],
)
def test_restricted_roles_cannot_read_private_authority(role, query):
    from sqlalchemy.exc import DBAPIError

    engine = create_engine(
        os.environ[f"WSO_TEST_{role}_DATABASE_URL"], hide_parameters=True
    )
    try:
        with engine.connect() as db:
            with pytest.raises(DBAPIError) as denied:
                db.execute(text(query))
            assert denied.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()


@pytest.mark.parametrize("role", ["DISPATCH", "IDENTITY", "SESSION", "WORKER"])
@pytest.mark.parametrize(
    "table", ["jobs", "outbox", "job_items", "job_connections", "inbox_dedup"]
)
def test_non_job_roles_denied_business_job_tables(role, table):
    from sqlalchemy.exc import DBAPIError

    engine = create_engine(
        os.environ[f"WSO_TEST_{role}_DATABASE_URL"], hide_parameters=True
    )
    try:
        with engine.connect() as db:
            with pytest.raises(DBAPIError) as denied:
                db.execute(text(f"SELECT * FROM public.{table}"))
            assert denied.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "role", ["APP", "JOB", "DISPATCH", "IDENTITY", "SESSION", "WORKER"]
)
@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO wso_private.dispatch_ready(outbox_id,job_id,tenant_id,kind,queue) VALUES(gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),'IMPORT','wso.browser')",
        "UPDATE wso_private.dispatch_ready SET state='READY'",
        "SELECT public.wso_finish_job(gen_random_uuid(),'SUCCEEDED',NULL,'{}'::jsonb)",
        "SELECT public.wso_revoke_tenant_jobs(gen_random_uuid())",
    ],
)
def test_runtime_cannot_create_projection_or_invoke_internal_mutators(role, query):
    from sqlalchemy.exc import DBAPIError

    engine = create_engine(
        os.environ[f"WSO_TEST_{role}_DATABASE_URL"], hide_parameters=True
    )
    try:
        with engine.connect() as db:
            with pytest.raises(DBAPIError) as denied:
                db.execute(text(query))
            assert denied.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()


def test_worker_guc_forgery_and_new_transaction_cannot_grant_authority():
    from uuid import uuid4

    engine = create_engine(
        os.environ["WSO_TEST_JOB_DATABASE_URL"], hide_parameters=True
    )
    try:
        with engine.begin() as db:
            db.execute(
                text(
                    "SELECT set_config('app.tenant_id',:tenant,true),set_config('app.job_id',:job,true)"
                ),
                {"tenant": str(uuid4()), "job": str(uuid4())},
            )
            assert (
                db.execute(text("SELECT public.wso_current_job_id()")).scalar_one()
                is None
            )
            assert db.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0
        with engine.begin() as db:
            assert (
                db.execute(text("SELECT public.wso_current_job_id()")).scalar_one()
                is None
            )
    finally:
        engine.dispose()


def test_owners_runtime_flags_functions_and_projection_privilege_inventory():
    engine = create_engine(
        os.environ["WSO_TEST_ADMIN_DATABASE_URL"], hide_parameters=True
    )
    try:
        with engine.connect() as db:
            roles = db.execute(
                text(
                    "SELECT rolname,rolcanlogin,rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname IN ('wso_job_owner','wso_dispatch_owner','wso_job_worker','wso_dispatcher')"
                )
            ).all()
            assert len(roles) == 4
            for role in roles:
                assert role.rolcanlogin == (
                    role.rolname in {"wso_job_worker", "wso_dispatcher"}
                )
                assert not any(tuple(role)[2:])
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM pg_auth_members WHERE member IN ('wso_job_owner'::regrole,'wso_dispatch_owner'::regrole,'wso_job_worker'::regrole,'wso_dispatcher'::regrole) OR roleid IN ('wso_job_owner'::regrole,'wso_dispatch_owner'::regrole,'wso_job_worker'::regrole,'wso_dispatcher'::regrole)"
                    )
                ).scalar_one()
                == 0
            )
            inventory = (
                db.execute(
                    text(
                        "SELECT n.nspname||'.'||c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wso_private') AND c.relkind='r' AND (has_table_privilege('wso_dispatch_owner',c.oid,'SELECT') OR has_table_privilege('wso_dispatch_owner',c.oid,'INSERT') OR has_table_privilege('wso_dispatch_owner',c.oid,'UPDATE') OR has_table_privilege('wso_dispatch_owner',c.oid,'DELETE'))"
                    )
                )
                .scalars()
                .all()
            )
            assert inventory == ["wso_private.dispatch_ready"]
            functions = db.execute(
                text(
                    "SELECT p.proname,p.prosecdef,p.proconfig,r.rolname owner,EXISTS(SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE') public_execute FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE r.rolname IN ('wso_job_owner','wso_dispatch_owner')"
                )
            ).all()
            assert len(functions) >= 14
            for f in functions:
                assert (
                    f.prosecdef
                    and f.proconfig == ["search_path=pg_catalog"]
                    and not f.public_execute
                )
                assert (f.owner == "wso_dispatch_owner") == (
                    f.proname
                    in {
                        "wso_claim_dispatch_batch",
                        "wso_ack_dispatch",
                        "wso_nack_dispatch",
                    }
                )
    finally:
        engine.dispose()


def _assert_approved_job_kinds(kinds):
    # Reviewed 0003 and 0008 admission contracts; unknown kinds/versions fail.
    assert set(kinds) == {
        ("IMPORT", 1),
        ("REGISTRATION", 1),
        ("TVT_ACCOUNT_OPERATION", 1),
        ("TVT_DEVICE_OPERATION", 1),
        ("TYCO_OPERATION", 1),
    }, "unexpected job kind or payload version"


@pytest.mark.parametrize(
    "unapproved",
    [("UNREVIEWED_OPERATION", 1), ("TVT_ACCOUNT_OPERATION", 2)],
)
def test_job_kind_inventory_rejects_unapproved_kind_or_version(unapproved):
    approved = [
        ("IMPORT", 1),
        ("REGISTRATION", 1),
        ("TVT_ACCOUNT_OPERATION", 1),
        ("TVT_DEVICE_OPERATION", 1),
        ("TYCO_OPERATION", 1),
    ]
    with pytest.raises(AssertionError, match="unexpected job kind or payload version"):
        _assert_approved_job_kinds([*approved, unapproved])


def test_migration_roundtrip_restores_t04_on_owned_disposable_database():
    from pathlib import Path
    from uuid import uuid4

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["WSO_TEST_ADMIN_DATABASE_URL"])
    database = "t05_roundtrip_" + uuid4().hex
    control = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True
    )
    isolated = None
    try:
        with control.connect() as db:
            db.execute(text(f'CREATE DATABASE "{database}" OWNER wso_migrator'))
        isolated = create_engine(url.set(database=database), hide_parameters=True)
        config = Config(str(Path(__file__).resolve().parents[2] / "infra/alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            url.set(database=database)
            .render_as_string(hide_password=False)
            .replace("%", "%%"),
        )
        command.upgrade(config, "0002_connections")
        with isolated.connect() as db:
            before = dict(
                db.execute(
                    text(
                        "SELECT proname,pg_get_functiondef(oid) FROM pg_proc WHERE proname IN ('wso_issue_connection_handle','wso_redeem_connection_handle','wso_use_connection_lease')"
                    )
                ).all()
            )
        command.upgrade(config, "head")
        with isolated.connect() as db:
            _assert_approved_job_kinds(
                db.execute(
                    text("SELECT kind,payload_version FROM wso_private.job_kinds")
                ).all()
            )
        command.downgrade(config, "0002_connections")
        with isolated.connect() as db:
            after = dict(
                db.execute(
                    text(
                        "SELECT proname,pg_get_functiondef(oid) FROM pg_proc WHERE proname IN ('wso_issue_connection_handle','wso_redeem_connection_handle','wso_use_connection_lease')"
                    )
                ).all()
            )
            assert before == after
            assert (
                db.execute(text("SELECT to_regclass('public.jobs')")).scalar_one()
                is None
            )
            assert not db.execute(
                text(
                    "SELECT has_any_column_privilege('wso_job_owner','public.memberships','UPDATE')"
                )
            ).scalar_one()
        command.upgrade(config, "head")
        command.downgrade(config, "base")
    finally:
        if isolated is not None:
            isolated.dispose()
        with control.connect() as db:
            db.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        control.dispose()


@pytest.mark.parametrize(
    "change",
    [{"database": "customer_production"}, {"port": 59999}, {"host": "192.0.2.4"}],
)
def test_fixture_schema_rejects_foreign_targets_before_connection(change):
    from sqlalchemy.engine import make_url

    from tests.support.job_handlers import install_fixture_schema

    class NeverConnect:
        url = make_url(os.environ["WSO_TEST_ADMIN_DATABASE_URL"]).set(**change)

        def connect(self):
            raise AssertionError("unverified database was contacted")

        def begin(self):
            raise AssertionError("unverified fixture DDL attempted")

    with pytest.raises(ValueError):
        install_fixture_schema(NeverConnect(), domain_only=True)
