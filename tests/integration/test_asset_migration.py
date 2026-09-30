"""Actual asset migration roundtrip on a verified, uniquely owned throwaway DB."""

import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from wso_api.auth import PostgresSessionStore, WebSession, token_digest
from wso_contracts.jobs import ImportJobPayload
from wso_contracts.models import TenantScope
from wso_core.db import tenant_session
from wso_core.jobs import JobService
from wso_core.tenancy import identity_session

from tests.support.job_handlers import verify_fixture_database

ASSET_TABLES = {
    "public.assets",
    "public.job_assets",
    *(
        f"wso_private.asset_{name}"
        for name in (
            "settings",
            "uploads",
            "tickets",
            "read_leases",
            "cleanup",
            "job_kinds",
            "reconciliation",
            "audit_outbox",
        )
    ),
}


def _head(engine):
    with engine.connect() as db:
        return db.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one()


def _jobs_contract(engine):
    with engine.connect() as db:
        return db.execute(
            text("""
            SELECT p.oid::regprocedure::text, pg_get_functiondef(p.oid),
                   p.proacl::text, p.proconfig, r.rolname
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            JOIN pg_roles r ON r.oid=p.proowner
            WHERE n.nspname='public' AND r.rolname IN ('wso_job_owner','wso_dispatch_owner')
            ORDER BY 1
        """)
        ).all()


def _asset_security(engine):
    with engine.connect() as db:
        tables = db.execute(
            text("""
            SELECT n.nspname||'.'||c.relname AS name,c.relrowsecurity,c.relforcerowsecurity,r.rolname
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_roles r ON r.oid=c.relowner
            WHERE n.nspname||'.'||c.relname=ANY(:names) AND c.relkind='r'
        """),
            {"names": sorted(ASSET_TABLES)},
        ).all()
        assert {row.name for row in tables} == ASSET_TABLES
        for row in tables:
            assert row.relrowsecurity and row.relforcerowsecurity
            assert row.rolname == (
                "wso_migrator"
                if row.name.startswith("wso_private.")
                else "wso_asset_owner"
            )
        roles = db.execute(
            text("""
            SELECT rolname,rolcanlogin,rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls
            FROM pg_roles WHERE rolname IN ('wso_asset_owner','wso_asset_maintenance') ORDER BY rolname
        """)
        ).all()
        assert len(roles) == 2
        for role in roles:
            assert role.rolcanlogin == (role.rolname == "wso_asset_maintenance")
            assert not any(tuple(role)[2:])
        assert (
            db.execute(
                text("""
            SELECT count(*) FROM pg_auth_members WHERE member IN ('wso_asset_owner'::regrole,'wso_asset_maintenance'::regrole)
            OR roleid IN ('wso_asset_owner'::regrole,'wso_asset_maintenance'::regrole)
        """)
            ).scalar_one()
            == 0
        )
        functions = db.execute(
            text("""
            SELECT p.oid::regprocedure::text,p.prosecdef,p.proconfig
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.proowner='wso_asset_owner'::regrole
        """)
        ).all()
        assert any(
            row[0].startswith("wso_begin_asset_completion(") for row in functions
        )
        assert all(
            row.prosecdef and row.proconfig == ["search_path=pg_catalog"]
            for row in functions
        )
        assert db.execute(
            text(
                "SELECT has_function_privilege('wso_asset_maintenance','public.wso_claim_asset_cleanup(integer,text)','EXECUTE')"
            )
        ).scalar_one()
        assert not db.execute(
            text(
                "SELECT has_function_privilege('wso_asset_maintenance','public.wso_begin_asset_write(uuid,uuid,text,jsonb)','EXECUTE')"
            )
        ).scalar_one()
        assert not db.execute(
            text(
                "SELECT has_function_privilege('wso_app','public.wso_flush_asset_audits(integer)','EXECUTE')"
            )
        ).scalar_one()
        return {row[0] for row in functions}


def test_asset_migration_roundtrip_on_owned_disposable_database():
    roles = ("ADMIN", "APP", "IDENTITY", "SESSION", "ASSET_MAINTENANCE", "JOB")
    if not all(os.getenv(f"WSO_TEST_{role}_DATABASE_URL") for role in roles):
        pytest.skip(
            "requires explicit owned PostgreSQL role URLs; strict gate rejects skips"
        )
    urls = {
        role: make_url(os.environ[f"WSO_TEST_{role}_DATABASE_URL"]) for role in roles
    }
    source = create_engine(urls["ADMIN"], hide_parameters=True)
    control = None
    engines = {}
    identity = None
    database = "t05a_roundtrip_" + uuid4().hex
    marker = "owned-asset-roundtrip-" + uuid4().hex
    assert re.fullmatch(r"t05a_roundtrip_[0-9a-f]{32}", database)
    try:
        verify_fixture_database(source, domain_only=sys.platform == "win32")
        source_head = _head(source)
        for url in urls.values():
            assert (url.drivername, url.host, url.port, url.database) == (
                urls["ADMIN"].drivername,
                urls["ADMIN"].host,
                urls["ADMIN"].port,
                urls["ADMIN"].database,
            )
        control = create_engine(
            urls["ADMIN"].set(database="postgres"),
            isolation_level="AUTOCOMMIT",
            hide_parameters=True,
        )
        with control.connect() as db:
            assert (
                db.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname=:name"),
                    {"name": database},
                ).scalar_one()
                == 0
            )
            db.execute(
                text(
                    f'CREATE DATABASE "{database}" OWNER wso_migrator TEMPLATE template0'
                )
            )
            db.execute(text(f"COMMENT ON DATABASE \"{database}\" IS '{marker}'"))
            identity = db.execute(
                text(
                    "SELECT oid,datdba,pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:name"
                ),
                {"name": database},
            ).one()
            assert identity[2:] == ("wso_migrator", marker)
        engines = {
            role: create_engine(url.set(database=database), hide_parameters=True)
            for role, url in urls.items()
        }
        admin = engines["ADMIN"]
        with admin.connect() as db:
            assert (
                db.execute(text("SELECT current_database()")).scalar_one() == database
            )
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'"
                    )
                ).scalar_one()
                == 0
            )
        config = Config(str(Path(__file__).resolve().parents[2] / "infra/alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            urls["ADMIN"]
            .set(database=database)
            .render_as_string(hide_password=False)
            .replace("%", "%%"),
        )
        command.upgrade(config, "0003_jobs")
        predecessor = _jobs_contract(admin)
        assert predecessor and _head(admin) == "0003_jobs"
        tenant, user = uuid4(), uuid4()
        with admin.begin() as db:
            db.execute(
                text(
                    "INSERT INTO public.tenants(id,name) VALUES(:id,'asset migration tenant')"
                ),
                {"id": tenant},
            )
            db.execute(
                text(
                    "INSERT INTO public.users(id,oidc_issuer,oidc_subject) VALUES(:id,'https://migration.test',:subject)"
                ),
                {"id": user, "subject": str(user)},
            )
            db.execute(
                text(
                    "INSERT INTO public.memberships(tenant_id,user_id,role) VALUES(:tenant,:user,'OWNER')"
                ),
                {"tenant": tenant, "user": user},
            )

        @contextmanager
        def authorized():
            with identity_session(
                "https://migration.test",
                str(user),
                session_factory=sessionmaker(engines["IDENTITY"]),
            ) as lookup:
                choice = lookup.authorize_tenant(tenant)
            with tenant_session(
                tenant,
                authorization=choice,
                session_factory=sessionmaker(engines["APP"]),
            ) as session:
                yield session

        payload = ImportJobPayload(import_id=uuid4())
        with authorized() as session:
            job = JobService(session).enqueue(
                TenantScope(tenant_id=tenant), "IMPORT", payload, "roundtrip-job"
            )
        digest = token_digest(uuid4().hex)
        session_store = PostgresSessionStore(
            urls["SESSION"]
            .set(database=database)
            .render_as_string(hide_password=False),
            session_factory=sessionmaker(engines["SESSION"]),
        )
        assert session_store.create(
            digest,
            WebSession(
                "https://migration.test",
                str(user),
                user,
                token_digest(uuid4().hex),
                datetime.now(UTC) + timedelta(minutes=5),
            ),
            token_digest(uuid4().hex),
        )
        installation = uuid4()
        first_functions = None
        for pass_number in (1, 2):
            command.upgrade(config, "0003a_assets")
            assert _head(admin) == "0003a_assets"
            functions = _asset_security(admin)
            if first_functions is None:
                first_functions = functions
            else:
                assert functions == first_functions
            with admin.begin() as db:
                db.execute(text("SET LOCAL ROLE wso_migrator"))
                db.execute(
                    text(
                        "SELECT public.wso_install_asset_runtime_configuration(:id,'migration-only-assets')"
                    ),
                    {"id": installation},
                )
            request = {
                "scope": {"scope_kind": "TENANT", "tenant_id": str(tenant)},
                "purpose": "IMPORT_PHOTO",
                "content_type": "image/png",
                "byte_size": 9,
                "checksum": {"algorithm": "SHA256", "value": "a" * 64},
                "parent_asset_id": None,
            }
            with authorized() as session:
                asset = (
                    session.execute(
                        text(
                            "SELECT * FROM public.wso_begin_asset_upload(CAST(:request AS jsonb),:digest)"
                        ),
                        {"request": json.dumps(request), "digest": digest},
                    )
                    .mappings()
                    .one()
                )
                assert (
                    session.execute(
                        text("SELECT state FROM public.assets WHERE id=:id"),
                        {"id": asset["asset_id"]},
                    ).scalar_one()
                    == "PENDING"
                )
                assert JobService(session).get(job.id).state == "QUEUED"
            with authorized() as session:
                assert (
                    session.execute(
                        text(
                            "SELECT state FROM public.wso_tombstone_asset(:id,:digest)"
                        ),
                        {"id": asset["asset_id"], "digest": digest},
                    ).scalar_one()
                    == "DELETING"
                )
            with engines["ASSET_MAINTENANCE"].begin() as db:
                assert (
                    db.execute(text("SELECT public.wso_sweep_assets(100)")).scalar_one()
                    == 0
                )
                assert db.execute(
                    text("SELECT * FROM public.wso_asset_reconciliation_state()")
                ).one() == (None, None)
            for role in ("APP", "ASSET_MAINTENANCE", "JOB"):
                with engines[role].connect() as db, pytest.raises(DBAPIError) as denied:
                    db.execute(text("SELECT * FROM wso_private.asset_uploads"))
                assert denied.value.orig.sqlstate == "42501"
            if pass_number == 1:
                command.downgrade(config, "0003_jobs")
                assert (
                    _head(admin) == "0003_jobs" and _jobs_contract(admin) == predecessor
                )
                with admin.connect() as db:
                    for table in ASSET_TABLES:
                        assert (
                            db.execute(
                                text("SELECT to_regclass(:table)"), {"table": table}
                            ).scalar_one()
                            is None
                        )
                    assert (
                        db.execute(
                            text(
                                "SELECT count(*) FROM pg_proc WHERE pronamespace='public'::regnamespace AND proowner='wso_asset_owner'::regrole"
                            )
                        ).scalar_one()
                        == 0
                    )
                    assert not db.execute(
                        text(
                            "SELECT has_any_column_privilege('wso_asset_owner','public.memberships','SELECT')"
                        )
                    ).scalar_one()
                with authorized() as session:
                    restored = JobService(session).enqueue(
                        TenantScope(tenant_id=tenant),
                        "IMPORT",
                        payload,
                        "roundtrip-job",
                    )
                    assert restored.id == job.id and restored.state == "QUEUED"
                with admin.connect() as db:
                    assert (
                        db.execute(
                            text("SELECT count(*) FROM public.outbox WHERE job_id=:id"),
                            {"id": job.id},
                        ).scalar_one()
                        == 1
                    )
                with (
                    engines["ASSET_MAINTENANCE"].connect() as db,
                    pytest.raises(DBAPIError) as missing,
                ):
                    db.execute(text("SELECT public.wso_sweep_assets(100)"))
                assert missing.value.orig.sqlstate == "42883"
        assert _head(source) == source_head
    finally:
        for engine in engines.values():
            engine.dispose()
        if control is not None:
            try:
                if identity is not None:
                    # Refuse to drop anything unless its exact created identity survives.
                    verify_fixture_database(source, domain_only=sys.platform == "win32")
                    assert re.fullmatch(r"t05a_roundtrip_[0-9a-f]{32}", database)
                    with control.connect() as db:
                        current = db.execute(
                            text(
                                "SELECT oid,datdba,pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:name"
                            ),
                            {"name": database},
                        ).one()
                        assert current == identity
                        db.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
                        assert (
                            db.execute(
                                text(
                                    "SELECT count(*) FROM pg_database WHERE datname=:name"
                                ),
                                {"name": database},
                            ).scalar_one()
                            == 0
                        )
            finally:
                control.dispose()
        source.dispose()
