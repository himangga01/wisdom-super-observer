"""Protected download denial and migration roundtrip on one owned disposable DB."""

import io
import os
import re
import sys
import time
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
from wso_core.assets import _database_failure
from wso_core.db import tenant_session
from wso_core.tenancy import identity_session

from tests.support.job_handlers import verify_fixture_database

SIGNATURES = (
    "public.wso_redeem_asset_ticket(uuid,text,text)",
    "public.wso_revalidate_asset_read(uuid,uuid,text)",
)


def _functions(engine):
    with engine.connect() as db:
        return {
            signature: db.execute(
                text("""SELECT p.oid, p.prosrc, p.proowner, p.proacl::text,
                       p.prosecdef, p.proconfig, pg_get_functiondef(p.oid)
                       FROM pg_proc p WHERE p.oid=to_regprocedure(:signature)"""),
                {"signature": signature},
            ).one()
            for signature in SIGNATURES
        }


def _source_content(engine):
    """Hash every managed user table's row multiset without exporting values."""
    with engine.connect() as db:
        tables = db.execute(
            text("""SELECT n.nspname,c.relname FROM pg_class c
              JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r'
              AND n.nspname IN ('public','wso_private') ORDER BY 1,2""")
        ).all()
        quote = engine.dialect.identifier_preparer.quote
        return tuple(
            (
                schema,
                table,
                db.execute(
                    text(
                        f"SELECT md5(coalesce(string_agg(md5(to_jsonb(t)::text), ',' "
                        f"ORDER BY md5(to_jsonb(t)::text)),'')) "
                        f"FROM {quote(schema)}.{quote(table)} t"
                    )
                ).scalar_one(),
            )
            for schema, table in tables
        )


def _sqlstate(call):
    with pytest.raises(DBAPIError) as failed:
        call()
    return failed.value.orig.sqlstate


def _public_failure(call):
    with pytest.raises(DBAPIError) as failed:
        call()
    translated = _database_failure(failed.value)
    return failed.value.orig.sqlstate, translated.status, translated.code


def test_parent_read_denial_and_exact_migration_roundtrip():
    roles = ("ADMIN", "APP", "IDENTITY", "SESSION", "MIGRATOR")
    if not all(os.getenv(f"WSO_TEST_{role}_DATABASE_URL") for role in roles):
        pytest.skip("requires explicit owned PostgreSQL role URLs")
    urls = {
        role: make_url(os.environ[f"WSO_TEST_{role}_DATABASE_URL"]) for role in roles
    }
    source = create_engine(urls["ADMIN"], hide_parameters=True)
    control = None
    engines = {}
    identity = None
    database = "t05a_read_" + uuid4().hex
    marker = "owned-parent-read-" + uuid4().hex
    assert re.fullmatch(r"t05a_read_[0-9a-f]{32}", database)
    try:
        verify_fixture_database(source, domain_only=sys.platform == "win32")
        with source.connect() as db:
            source_head = db.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            source_identity = db.execute(
                text("""SELECT oid,datdba,pg_get_userbyid(datdba)
                FROM pg_database WHERE datname=current_database()""")
            ).one()
        source_content = _source_content(source)
        assert source_head
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
                text("""SELECT oid,datdba,pg_get_userbyid(datdba),
                              shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:name"""),
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
                    text("""SELECT count(*) FROM pg_class c JOIN pg_namespace n
                  ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p')
                  AND n.nspname NOT IN ('pg_catalog','information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%'""")
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
        command.upgrade(config, "0008_tvt_operation_engine")
        before = _functions(admin)

        def emitted(direction, revision):
            output = io.StringIO()
            offline = Config(config.config_file_name, output_buffer=output)
            getattr(command, direction)(offline, revision, sql=True)
            return output.getvalue()

        upgrade_sql = emitted(
            "upgrade", "0008_tvt_operation_engine:0009_asset_read_denial"
        )
        downgrade_sql = emitted(
            "downgrade", "0009_asset_read_denial:0008_tvt_operation_engine"
        )

        def execute_emitted(script):
            with admin.begin() as db:
                db.exec_driver_sql(script.replace("%", "%%"))

        drift_checks = []

        def reject_drift(script, direction, revision):
            expected = _functions(admin)
            for signature, kind in (
                (SIGNATURES[0], "source"),
                ("public.wso_asset_lock(uuid,text,boolean)", "source"),
                (SIGNATURES[1], "security"),
                (SIGNATURES[1], "acl"),
            ):
                with admin.connect() as db:
                    body, definition = db.execute(
                        text("""SELECT prosrc,pg_get_functiondef(oid) FROM pg_proc
                                WHERE oid=to_regprocedure(:signature)"""),
                        {"signature": signature},
                    ).one()
                if kind == "source":
                    assert definition.count(body) == 1
                    mutation = definition.replace(body, body + "\n-- drift probe\n")
                    restore = definition
                elif kind == "security":
                    mutation = f"ALTER FUNCTION {signature} SECURITY INVOKER"
                    restore = definition
                else:
                    mutation = f"REVOKE EXECUTE ON FUNCTION {signature} FROM wso_app"
                    restore = f"GRANT EXECUTE ON FUNCTION {signature} TO wso_app"
                for mode in ("emitted", "online"):
                    with admin.begin() as db:
                        db.exec_driver_sql(mutation.replace("%", "%%"))
                    try:
                        if mode == "emitted":
                            state = _sqlstate(lambda: execute_emitted(script))
                        else:
                            state = _sqlstate(
                                lambda: getattr(command, direction)(config, revision)
                            )
                        assert state == "P0001"
                        drift_checks.append((direction, mode, signature, kind, state))
                    finally:
                        with admin.begin() as db:
                            db.exec_driver_sql(restore.replace("%", "%%"))
                    assert _functions(admin) == expected
                    with admin.connect() as db:
                        assert db.execute(
                            text("SELECT version_num FROM public.alembic_version")
                        ).scalar_one() == (
                            "0008_tvt_operation_engine"
                            if direction == "upgrade"
                            else "0009_asset_read_denial"
                        )

        # Both emitted directions execute their guards on the same owned target.
        reject_drift(upgrade_sql, "upgrade", "0009_asset_read_denial")
        execute_emitted(upgrade_sql)
        emitted_after = _functions(admin)
        reject_drift(downgrade_sql, "downgrade", "0008_tvt_operation_engine")
        execute_emitted(downgrade_sql)
        assert _functions(admin) == before
        tenant, user, parent, child, other_tenant, other_user = (
            uuid4() for _ in range(6)
        )
        digest = token_digest(uuid4().hex)
        other_digest = token_digest(uuid4().hex)
        asset_expiration = datetime.now(UTC) + timedelta(hours=1)
        with admin.begin() as db:
            db.execute(
                text(
                    "INSERT INTO public.tenants(id,name) VALUES(:id,'parent read test')"
                ),
                {"id": tenant},
            )
            db.execute(
                text("""INSERT INTO public.users(id,oidc_issuer,oidc_subject)
                          VALUES(:id,'https://read.test',:subject)"""),
                {"id": user, "subject": str(user)},
            )
            db.execute(
                text("""INSERT INTO public.memberships(tenant_id,user_id,role)
                          VALUES(:tenant,:user,'OWNER')"""),
                {"tenant": tenant, "user": user},
            )
            db.execute(
                text(
                    "INSERT INTO public.tenants(id,name) VALUES(:id,'other read tenant')"
                ),
                {"id": other_tenant},
            )
            db.execute(
                text("""INSERT INTO public.users(id,oidc_issuer,oidc_subject)
                          VALUES(:id,'https://read.test',:subject)"""),
                {"id": other_user, "subject": str(other_user)},
            )
            for assigned_tenant, assigned_user in (
                (tenant, other_user),
                (other_tenant, user),
            ):
                db.execute(
                    text("""INSERT INTO public.memberships(tenant_id,user_id,role)
                              VALUES(:tenant,:user,'OWNER')"""),
                    {"tenant": assigned_tenant, "user": assigned_user},
                )
            db.execute(
                text("""UPDATE wso_private.asset_settings
                          SET installation_id=:id,bucket='parent-read-test' WHERE singleton"""),
                {"id": uuid4()},
            )
            for asset, purpose, parent_id in (
                (parent, "IMPORT_PHOTO", None),
                (child, "IMPORT_CROP", parent),
            ):
                db.execute(
                    text("""INSERT INTO public.assets
                     (id,tenant_id,purpose,parent_asset_id,creator_id,state,checksum_sha256,
                      byte_size,content_type,expires_at,policy_version)
                     VALUES(:id,:tenant,:purpose,:parent,:creator,'READY',:checksum,9,
                            'image/png',:expiration,1)"""),
                    {
                        "id": asset,
                        "tenant": tenant,
                        "purpose": purpose,
                        "parent": parent_id,
                        "creator": user,
                        "checksum": "a" * 64,
                        "expiration": asset_expiration,
                    },
                )
                db.execute(
                    text("""INSERT INTO wso_private.asset_uploads
                   (asset_id,tenant_id,creator_id,session_digest,expires_at,status,
                    object_key,key_id,wrapped_dek,wrap_nonce,object_nonce)
                   VALUES(:asset,:tenant,:creator,:digest,clock_timestamp()+interval '1 hour',
                          'FINISHED',:object_key,'test-key',:dek,:nonce,:nonce)"""),
                    {
                        "asset": asset,
                        "tenant": tenant,
                        "creator": user,
                        "digest": digest,
                        "object_key": str(asset),
                        "dek": bytes(48),
                        "nonce": bytes(12),
                    },
                )
        session_store = PostgresSessionStore(
            urls["SESSION"]
            .set(database=database)
            .render_as_string(hide_password=False),
            session_factory=sessionmaker(engines["SESSION"]),
        )
        assert session_store.create(
            digest,
            WebSession(
                "https://read.test",
                str(user),
                user,
                token_digest(uuid4().hex),
                datetime.now(UTC) + timedelta(minutes=5),
            ),
            token_digest(uuid4().hex),
        )
        assert session_store.create(
            other_digest,
            WebSession(
                "https://read.test",
                str(other_user),
                other_user,
                token_digest(uuid4().hex),
                datetime.now(UTC) + timedelta(minutes=5),
            ),
            token_digest(uuid4().hex),
        )

        @contextmanager
        def authorized(actor=user, scope=tenant):
            with identity_session(
                "https://read.test",
                str(actor),
                session_factory=sessionmaker(engines["IDENTITY"]),
            ) as lookup:
                choice = lookup.authorize_tenant(scope)
            with tenant_session(
                scope,
                authorization=choice,
                session_factory=sessionmaker(engines["APP"]),
            ) as db:
                yield db

        def ticket():
            with authorized() as db:
                return db.execute(
                    text(
                        "SELECT token FROM public.wso_issue_asset_ticket(:id,:session)"
                    ),
                    {"id": child, "session": digest},
                ).scalar_one()

        def redeem(secret):
            with authorized() as db:
                return (
                    db.execute(
                        text(
                            "SELECT * FROM public.wso_redeem_asset_ticket(:id,:token,:session)"
                        ),
                        {"id": child, "token": secret, "session": digest},
                    )
                    .mappings()
                    .one()
                )

        # Normal download admission and revalidation use actual protected SQL.
        normal = redeem(ticket())
        assert normal["asset_id"] == child and normal["read_use"] == "DOWNLOAD"
        with authorized() as db:
            assert db.execute(
                text("SELECT public.wso_revalidate_asset_read(:id,:lease,:session)"),
                {"id": child, "lease": normal["lease_id"], "session": digest},
            ).scalar_one()

        pending = ticket()
        command.upgrade(config, "0009_asset_read_denial")
        after = _functions(admin)
        assert after == emitted_after
        assert all(
            after[s][0] == before[s][0] and after[s][2:5] == before[s][2:5]
            for s in SIGNATURES
        )
        upgraded_normal = redeem(ticket())
        assert upgraded_normal["asset_id"] == child
        with authorized() as db:
            assert db.execute(
                text("SELECT public.wso_revalidate_asset_read(:id,:lease,:session)"),
                {
                    "id": child,
                    "lease": upgraded_normal["lease_id"],
                    "session": digest,
                },
            ).scalar_one()
        assert _public_failure(lambda: redeem("0" * 64)) == (
            "P0002",
            404,
            "ASSET_NOT_FOUND",
        )
        actor_ticket = ticket()
        with authorized() as db:
            assert _public_failure(
                lambda: db.execute(
                    text(
                        "SELECT * FROM public.wso_redeem_asset_ticket(:id,:token,:session)"
                    ),
                    {"id": child, "token": actor_ticket, "session": "0" * 64},
                ).one()
            ) == ("42501", 403, "ASSET_DENIED")
        expired_ticket = ticket()
        with admin.begin() as db:
            db.execute(
                text("""UPDATE wso_private.asset_tickets
                   SET expires_at=clock_timestamp()-interval '1 second'
                   WHERE token_digest=sha256(convert_to(:token,'UTF8'))"""),
                {"token": expired_ticket},
            )
        assert _public_failure(lambda: redeem(expired_ticket)) == (
            "P0002",
            404,
            "ASSET_NOT_FOUND",
        )
        with authorized(other_user) as db:
            assert _public_failure(
                lambda: db.execute(
                    text(
                        "SELECT * FROM public.wso_redeem_asset_ticket(:id,:token,:session)"
                    ),
                    {"id": child, "token": pending, "session": other_digest},
                ).one()
            ) == ("P0002", 404, "ASSET_NOT_FOUND")
        with authorized(user, other_tenant) as db:
            assert _public_failure(
                lambda: db.execute(
                    text(
                        "SELECT * FROM public.wso_redeem_asset_ticket(:id,:token,:session)"
                    ),
                    {"id": child, "token": pending, "session": digest},
                ).one()
            ) == ("P0002", 404, "ASSET_NOT_FOUND")
        with authorized() as db:
            assert _public_failure(
                lambda: db.execute(
                    text(
                        "SELECT * FROM public.wso_prepare_asset_write(:id,:upload,:session)"
                    ),
                    {"id": child, "upload": uuid4(), "session": digest},
                ).one()
            ) == ("55000", 409, "ASSET_CONFLICT")
        with admin.begin() as db:
            db.execute(
                text("""UPDATE public.assets SET state='DELETING',
                          access_generation=access_generation+1 WHERE id=:id"""),
                {"id": parent},
            )
        assert _public_failure(lambda: redeem(pending)) == (
            "P0002",
            404,
            "ASSET_NOT_FOUND",
        )
        with admin.connect() as db:
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM wso_private.asset_read_leases WHERE asset_id=:id"
                    ),
                    {"id": child},
                ).scalar_one()
                == 2
            )
        with authorized() as db:
            assert (
                _sqlstate(
                    lambda: db.execute(
                        text(
                            "SELECT public.wso_revalidate_asset_read(:id,:lease,:session)"
                        ),
                        {"id": child, "lease": normal["lease_id"], "session": digest},
                    ).scalar_one()
                )
                == "P0002"
            )
        command.downgrade(config, "0008_tvt_operation_engine")
        assert _functions(admin) == before
        assert _sqlstate(lambda: redeem(pending)) == "55000"
        command.upgrade(config, "0009_asset_read_denial")
        assert _functions(admin) == after
        assert _sqlstate(lambda: redeem(pending)) == "P0002"
        with admin.begin() as db:
            db.execute(
                text("UPDATE public.assets SET state='DELETED' WHERE id=:id"),
                {"id": parent},
            )
        assert _public_failure(lambda: redeem(pending)) == (
            "P0002",
            404,
            "ASSET_NOT_FOUND",
        )
        with admin.connect() as db:
            assert db.execute(
                text("""SELECT redeemed_at IS NULL FROM wso_private.asset_tickets
                 WHERE token_digest=sha256(convert_to(:token,'UTF8'))"""),
                {"token": pending},
            ).scalar_one()
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM wso_private.asset_read_leases WHERE asset_id=:id"
                    ),
                    {"id": child},
                ).scalar_one()
                == 2
            )
        exp_parent, exp_child = uuid4(), uuid4()
        expires = datetime.now(UTC) + timedelta(seconds=5)
        with admin.begin() as db:
            for asset, purpose, parent_id in (
                (exp_parent, "IMPORT_PHOTO", None),
                (exp_child, "IMPORT_CROP", exp_parent),
            ):
                db.execute(
                    text("""INSERT INTO public.assets
                     (id,tenant_id,purpose,parent_asset_id,creator_id,state,checksum_sha256,
                      byte_size,content_type,expires_at,policy_version)
                     VALUES(:id,:tenant,:purpose,:parent,:creator,'READY',:checksum,9,
                            'image/png',:expiration,1)"""),
                    {
                        "id": asset,
                        "tenant": tenant,
                        "purpose": purpose,
                        "parent": parent_id,
                        "creator": user,
                        "checksum": "a" * 64,
                        "expiration": expires,
                    },
                )
        with authorized() as db:
            exp_ticket = db.execute(
                text("SELECT token FROM public.wso_issue_asset_ticket(:id,:session)"),
                {"id": exp_child, "session": digest},
            ).scalar_one()
        time.sleep(max(0.0, expires.timestamp() - time.time()) + 0.1)
        with authorized() as db:
            assert _public_failure(
                lambda: db.execute(
                    text(
                        "SELECT * FROM public.wso_redeem_asset_ticket(:id,:token,:session)"
                    ),
                    {"id": exp_child, "token": exp_ticket, "session": digest},
                ).one()
            ) == ("P0002", 404, "ASSET_NOT_FOUND")
        with source.connect() as db:
            assert (
                db.execute(
                    text("SELECT version_num FROM public.alembic_version")
                ).scalar_one()
                == source_head
            )
            assert (
                db.execute(
                    text("""SELECT oid,datdba,pg_get_userbyid(datdba)
                FROM pg_database WHERE datname=current_database()""")
                ).one()
                == source_identity
            )
        assert _source_content(source) == source_content
    finally:
        for engine in engines.values():
            engine.dispose()
        if control is not None:
            try:
                if identity is not None:
                    verify_fixture_database(source, domain_only=sys.platform == "win32")
                    assert re.fullmatch(r"t05a_read_[0-9a-f]{32}", database)
                    with control.connect() as db:
                        current = db.execute(
                            text("""SELECT oid,datdba,pg_get_userbyid(datdba),
                            shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:name"""),
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
