"""Deferred PostgreSQL 17 acceptance: run only after the root foundation gate.

Requires the existing verified disposable PG fixture and explicit role URLs.
No mock or skipped execution is database acceptance.
"""

import os
import re
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from wso_core.db import tenant_session
from wso_core.tenancy import identity_session
from wso_core.tvt.authorization import (
    AuthorizationDenied,
    DomainTarget,
    authorize,
    recheck,
)

from tests.support.job_handlers import verify_fixture_database

TABLES = (
    "tvt_identities",
    "tvt_device_links",
    "tvt_channels",
    "tvt_device_store_links",
    "tvt_identity_grants",
    "tvt_upstream_grants",
    "tvt_capability_snapshots",
    "tyco_identities",
    "tyco_panels",
    "tyco_identity_grants",
    "tyco_upstream_grants",
    "tyco_capability_snapshots",
)


def foundation_contract(db):
    return (
        db.execute(
            text("""
          SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid),p.proacl::text,p.proconfig
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname='public' AND pg_get_userbyid(p.proowner)<>'wso_domain_owner' ORDER BY 1
        """)
        ).all(),
        db.execute(
            text("""
          SELECT n.nspname,c.relname,c.relacl::text,a.attname,a.attacl::text
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0
          WHERE n.nspname IN ('public','wso_private') AND c.relkind='r'
            AND pg_get_userbyid(c.relowner)<>'wso_domain_owner' ORDER BY 1,2,4
        """)
        ).all(),
        db.execute(
            text("""
          SELECT n.nspname,c.relname,p.polname,p.polpermissive,p.polcmd,
            p.polroles::text,pg_get_expr(p.polqual,p.polrelid),
            pg_get_expr(p.polwithcheck,p.polrelid)
          FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
          JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname IN ('public','wso_private')
            AND pg_get_userbyid(c.relowner)<>'wso_domain_owner' ORDER BY 1,2,3
        """)
        ).all(),
    )


@pytest.fixture
def disposable_domain_db():
    roles = ("ADMIN", "APP", "IDENTITY")
    if (
        os.getenv("WSO_TEST_W02_DOMAIN_ACCEPTANCE") != "1"
        and os.getenv("WSO_TEST_W02_DOMAIN_DIAGNOSTIC") != "1"
    ):
        pytest.skip(
            "W02 PG acceptance requires root activation after the foundation gate"
        )
    if not all(os.getenv(f"WSO_TEST_{role}_DATABASE_URL") for role in roles):
        pytest.fail("activated W02 acceptance requires explicit PostgreSQL role URLs")
    urls = {
        role: make_url(os.environ[f"WSO_TEST_{role}_DATABASE_URL"]) for role in roles
    }
    bounds = {
        "connect_timeout": 5,
        "options": "-c statement_timeout=10000 -c lock_timeout=3000",
    }
    source = create_engine(urls["ADMIN"], hide_parameters=True, connect_args=bounds)
    control = None
    engines = {}
    created_identity = None
    database = "w02_scope_" + uuid4().hex
    marker = "owned-w02-scope-" + uuid4().hex
    try:
        verify_fixture_database(source, domain_only=sys.platform == "win32")
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
            connect_args=bounds,
        )
        with control.connect() as db:
            assert (
                db.execute(text("SHOW server_version_num"))
                .scalar_one()
                .startswith("17")
            )
            assert re.fullmatch(r"w02_scope_[0-9a-f]{32}", database)
            assert (
                db.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname=:n"),
                    {"n": database},
                ).scalar_one()
                == 0
            )
            db.execute(
                text(
                    f'CREATE DATABASE "{database}" OWNER wso_migrator TEMPLATE template0'
                )
            )
            db.execute(text(f"COMMENT ON DATABASE \"{database}\" IS '{marker}'"))
            created_identity = db.execute(
                text(
                    "SELECT oid,datdba,pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:n"
                ),
                {"n": database},
            ).one()
            assert created_identity[2:] == ("wso_migrator", marker)
        engines = {
            role: create_engine(
                url.set(database=database), hide_parameters=True, connect_args=bounds
            )
            for role, url in urls.items()
        }
        config = Config(str(Path(__file__).resolve().parents[2] / "infra/alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            urls["ADMIN"]
            .set(database=database)
            .render_as_string(hide_password=False)
            .replace("%", "%%"),
        )
        command.upgrade(config, "0003a_assets")
        yield engines, config
    finally:
        for engine in engines.values():
            engine.dispose()
        if control is not None:
            try:
                if created_identity is not None:
                    verify_fixture_database(source, domain_only=sys.platform == "win32")
                    assert re.fullmatch(r"w02_scope_[0-9a-f]{32}", database)
                    with control.connect() as db:
                        current = db.execute(
                            text(
                                "SELECT oid,datdba,pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:n"
                            ),
                            {"n": database},
                        ).one()
                        assert current == created_identity
                        db.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            finally:
                control.dispose()
        source.dispose()


def seed_foundation(admin):
    ids = {
        name: uuid4()
        for name in (
            "tenant",
            "other_tenant",
            "staff",
            "owner",
            "store",
            "sibling_store",
            "foreign_store",
            "connection",
            "tyco_connection",
            "foreign_connection",
            "identity",
            "tyco_identity",
            "foreign_identity",
            "device",
            "channel",
            "sibling_channel",
            "link",
            "sibling_link",
            "null_link",
            "grant",
            "tyco_grant",
            "panel",
        )
    }
    with admin.begin() as db:
        for tenant in ("tenant", "other_tenant"):
            db.execute(
                text("INSERT INTO public.tenants(id,name) VALUES(:id,'W02 fixture')"),
                {"id": ids[tenant]},
            )
        for actor, role in (("staff", "STAFF"), ("owner", "OWNER")):
            db.execute(
                text(
                    "INSERT INTO public.users(id,oidc_issuer,oidc_subject) VALUES(:id,'https://w02.test',:sub)"
                ),
                {"id": ids[actor], "sub": str(ids[actor])},
            )
            for tenant in ("tenant", "other_tenant"):
                db.execute(
                    text(
                        "INSERT INTO public.memberships(tenant_id,user_id,role) VALUES(:t,:u,:r)"
                    ),
                    {"t": ids[tenant], "u": ids[actor], "r": role},
                )
        for store, tenant in (
            ("store", "tenant"),
            ("sibling_store", "tenant"),
            ("foreign_store", "other_tenant"),
        ):
            db.execute(
                text(
                    "INSERT INTO public.stores(id,tenant_id,name,timezone) VALUES(:id,:t,'Fixture','UTC')"
                ),
                {"id": ids[store], "t": ids[tenant]},
            )
        db.execute(
            text(
                "INSERT INTO public.store_memberships(tenant_id,user_id,store_id) VALUES(:t,:u,:s)"
            ),
            {"t": ids["tenant"], "u": ids["staff"], "s": ids["store"]},
        )
        for connection, tenant, kind in (
            ("connection", "tenant", "TVT_ACCOUNT"),
            ("tyco_connection", "tenant", "TYCO_ACCOUNT"),
            ("foreign_connection", "other_tenant", "TVT_ACCOUNT"),
        ):
            db.execute(
                text(
                    "INSERT INTO public.connections(id,tenant_id,kind,alias,site,status,generation) VALUES(:id,:t,:k,'Fixture','Fixture','NOT_VERIFIED',1)"
                ),
                {"id": ids[connection], "t": ids[tenant], "k": kind},
            )
    return ids


def seed_domain(admin, ids):
    with admin.begin() as db:
        for domain, identity, tenant, connection in (
            ("tvt", "identity", "tenant", "connection"),
            ("tvt", "foreign_identity", "other_tenant", "foreign_connection"),
            ("tyco", "tyco_identity", "tenant", "tyco_connection"),
        ):
            db.execute(
                text(
                    f"INSERT INTO wso_private.{domain}_identities(id,tenant_id,connection_id,region,brand) VALUES(:id,:t,:c,'test','test')"
                ),
                {"id": ids[identity], "t": ids[tenant], "c": ids[connection]},
            )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_device_links(id,tenant_id,identity_id) VALUES(:device,:tenant,:identity)"
            ),
            ids,
        )
        for channel in ("channel", "sibling_channel"):
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_channels(id,tenant_id,identity_id,device_id) VALUES(:id,:tenant,:identity,:device)"
                ),
                {**ids, "id": ids[channel]},
            )
        for link, store, channel in (
            ("link", "store", "channel"),
            ("sibling_link", "sibling_store", "channel"),
            ("null_link", "store", None),
        ):
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_device_store_links(id,tenant_id,identity_id,device_id,channel_id,store_id,revision) VALUES(:id,:tenant,:identity,:device,:ch,:s,1)"
                ),
                {
                    **ids,
                    "id": ids[link],
                    "ch": ids[channel] if channel else None,
                    "s": ids[store],
                },
            )
        for link, action in (
            ("link", "media.live"),
            ("sibling_link", "media.live"),
            ("null_link", "device.read"),
        ):
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_identity_grants(id,tenant_id,identity_id,actor_id,action,link_id,revision,expires_at) VALUES(:id,:tenant,:identity,:staff,:action,:l,1,clock_timestamp()+interval '1 hour')"
                ),
                {
                    **ids,
                    "id": ids["grant"] if link == "link" else uuid4(),
                    "action": action,
                    "l": ids[link],
                },
            )
        for name in ("tvt_upstream_grants", "tvt_capability_snapshots"):
            for action, channel in (
                ("media.live", ids["channel"]),
                ("device.read", None),
            ):
                db.execute(
                    text(
                        f"INSERT INTO wso_private.{name}(id,tenant_id,identity_id,device_id,channel_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(:id,:tenant,:identity,:device,:ch,:action,true,1,1,clock_timestamp(),clock_timestamp()+interval '1 hour')"
                    ),
                    {**ids, "id": uuid4(), "action": action, "ch": channel},
                )
        db.execute(
            text(
                "INSERT INTO wso_private.tyco_panels(id,tenant_id,identity_id) VALUES(:panel,:tenant,:tyco_identity)"
            ),
            ids,
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tyco_identity_grants(id,tenant_id,identity_id,actor_id,action,panel_id,revision,expires_at) VALUES(:tyco_grant,:tenant,:tyco_identity,:staff,'panel.read',:panel,1,clock_timestamp()+interval '1 hour')"
            ),
            ids,
        )
        for name in ("tyco_upstream_grants", "tyco_capability_snapshots"):
            db.execute(
                text(
                    f"INSERT INTO wso_private.{name}(id,tenant_id,identity_id,panel_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(:id,:tenant,:tyco_identity,:panel,'panel.read',true,1,1,clock_timestamp(),clock_timestamp()+interval '1 hour')"
                ),
                {**ids, "id": uuid4()},
            )


def test_restricted_authority_constraints_revocation_and_migration_roundtrip(
    disposable_domain_db,
):
    engines, config = disposable_domain_db
    admin = engines["ADMIN"]
    ids = seed_foundation(admin)
    with admin.connect() as db:
        baseline = foundation_contract(db)
        rows_before = db.execute(
            text("SELECT * FROM public.connections ORDER BY id")
        ).all()
    command.upgrade(config, "0004_tvt_domain")
    seed_domain(admin, ids)

    @contextmanager
    def authorized(actor="staff", tenant="tenant"):
        with identity_session(
            "https://w02.test",
            str(ids[actor]),
            session_factory=sessionmaker(engines["IDENTITY"]),
        ) as lookup:
            choice = lookup.authorize_tenant(ids[tenant])
        with tenant_session(
            ids[tenant],
            authorization=choice,
            session_factory=sessionmaker(engines["APP"]),
        ) as db:
            yield db

    target = DomainTarget(
        "TVT", ids["identity"], ids["device"], ids["channel"], ids["store"]
    )
    panel = DomainTarget("TYCO", ids["tyco_identity"], panel_id=ids["panel"])
    with authorized() as db:
        scope = authorize(db, target, "media.live")
        assert scope.actor_id == ids["staff"] and scope.tenant_id == ids["tenant"]
        assert authorize(db, panel, "panel.read").actor_id == ids["staff"]
        assert authorize(db, replace(target, channel_id=None), "device.read")
        assert (
            authorize(db, DomainTarget("TVT"), "account.login").target.identity_id
            is None
        )
        for denied in (
            replace(target, channel_id=ids["sibling_channel"]),
            replace(target, channel_id=None),
            replace(target, store_id=ids["sibling_store"]),
            replace(target, store_id=ids["foreign_store"]),
            replace(target, identity_id=ids["foreign_identity"]),
        ):
            with pytest.raises(AuthorizationDenied):
                authorize(db, denied, "media.live")
        for denied, action in (
            (target, "panel.read"),
            (panel, "media.live"),
            (target, "arbitrary.execute"),
        ):
            with pytest.raises(AuthorizationDenied):
                authorize(db, denied, action)
    with authorized("owner") as db:
        for selected, action in ((target, "media.live"), (panel, "panel.read")):
            with pytest.raises(AuthorizationDenied):
                authorize(db, selected, action)
    with authorized(tenant="other_tenant") as db, pytest.raises(AuthorizationDenied):
        authorize(db, target, "media.live")

    # Raw runtime credentials cannot forge consumed context or mint observations.
    with Session(engines["APP"]) as db:
        for key, value in (
            ("app.tenant_id", ids["tenant"]),
            ("app.user_id", ids["staff"]),
            ("app.role", "OWNER"),
        ):
            db.execute(
                text("SELECT set_config(:k,:v,true)"), {"k": key, "v": str(value)}
            )
        with pytest.raises(AuthorizationDenied):
            authorize(db, target, "media.live")
        with pytest.raises(AuthorizationDenied):
            authorize(db, DomainTarget("TVT"), "account.login")
    for sql in (
        "SELECT * FROM wso_private.tvt_identity_grants",
        "SELECT * FROM wso_private.tyco_identity_grants",
        "UPDATE wso_private.tvt_capability_snapshots SET verified=true",
        "DELETE FROM wso_private.tvt_identity_grants",
        "INSERT INTO wso_private.tenant_contexts(backend_pid,transaction_id,tenant_id,user_id,role) VALUES(pg_backend_pid(),txid_current(),:tenant,:staff,'OWNER')",
        "SET ROLE wso_domain_owner",
    ):
        with engines["APP"].begin() as db, pytest.raises(DBAPIError) as denied:
            db.execute(text(sql), ids)
        assert denied.value.orig.sqlstate == "42501"

    with admin.connect() as db:
        secured = db.execute(
            text(
                "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wso_private' AND c.relname=ANY(:names)"
            ),
            {"names": list(TABLES)},
        ).all()
        assert len(secured) == len(TABLES)
        assert all(row[1:] == (True, True, "wso_domain_owner") for row in secured)
        role = db.execute(
            text(
                "SELECT rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='wso_domain_owner'"
            )
        ).one()
        assert not any(role)
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM pg_auth_members WHERE member='wso_domain_owner'::regrole OR roleid='wso_domain_owner'::regrole"
                )
            ).scalar_one()
            == 0
        )
        function = db.execute(
            text(
                "SELECT prosecdef,proconfig,pg_get_userbyid(proowner) FROM pg_proc WHERE oid='public.wso_authorize_domain(text,uuid,uuid,uuid,uuid,uuid,text)'::regprocedure"
            )
        ).one()
        assert function == (True, ["search_path=pg_catalog"], "wso_domain_owner")
        for role in (
            "wso_app",
            "wso_identity_bootstrap",
            "wso_web_session",
            "wso_connection_worker",
            "wso_job_worker",
            "wso_dispatcher",
            "wso_asset_maintenance",
        ):
            assert db.execute(
                text(
                    "SELECT has_function_privilege(:r,'public.wso_authorize_domain(text,uuid,uuid,uuid,uuid,uuid,text)','EXECUTE')"
                ),
                {"r": role},
            ).scalar_one() == (role == "wso_app")
            for table in TABLES:
                assert not db.execute(
                    text(
                        "SELECT has_any_column_privilege(:r,:t,'SELECT,INSERT,UPDATE')"
                    ),
                    {"r": role, "t": "wso_private." + table},
                ).scalar_one()

    invalid_rows = (
        (
            "INSERT INTO wso_private.tvt_device_store_links(id,tenant_id,identity_id,device_id,channel_id,store_id,revision) VALUES(:id,:tenant,:identity,:device,NULL,:store,1)",
            "23505",
        ),
        (
            "INSERT INTO wso_private.tvt_device_store_links(id,tenant_id,identity_id,device_id,store_id,revision) VALUES(:id,:tenant,:identity,:device,:foreign_store,1)",
            "23503",
        ),
        (
            "INSERT INTO wso_private.tvt_device_store_links(id,tenant_id,identity_id,device_id,store_id,revision) VALUES(:id,:other_tenant,:foreign_identity,:device,:foreign_store,1)",
            "23503",
        ),
        (
            "UPDATE wso_private.tvt_identities SET connection_id=:tyco_connection WHERE id=:identity",
            "23503",
        ),
        (
            "INSERT INTO wso_private.tyco_identity_grants(id,tenant_id,identity_id,actor_id,action,panel_id,revision,expires_at) VALUES(:id,:tenant,:identity,:staff,'panel.read',:panel,1,clock_timestamp()+interval '1 hour')",
            "23503",
        ),
    )
    for sql, expected in invalid_rows:
        with admin.begin() as db, pytest.raises(IntegrityError) as denied:
            db.execute(text(sql), {**ids, "id": uuid4()})
        assert denied.value.orig.sqlstate == expected

    # Every current source of authority is independently revocable.
    mutations = (
        (
            "public.store_memberships",
            "DELETE FROM public.store_memberships WHERE user_id=:staff",
            "INSERT INTO public.store_memberships(tenant_id,user_id,store_id) VALUES(:tenant,:staff,:store)",
        ),
        (
            "wso_private.tvt_upstream_grants",
            "UPDATE wso_private.tvt_upstream_grants SET verified=false",
            "UPDATE wso_private.tvt_upstream_grants SET verified=true",
        ),
        (
            "wso_private.tvt_capability_snapshots",
            "UPDATE wso_private.tvt_capability_snapshots SET verified=false",
            "UPDATE wso_private.tvt_capability_snapshots SET verified=true",
        ),
        (
            "wso_private.tvt_device_store_links",
            "UPDATE wso_private.tvt_device_store_links SET active=false",
            "UPDATE wso_private.tvt_device_store_links SET active=true",
        ),
        (
            "public.connections",
            "UPDATE public.connections SET generation=2",
            "UPDATE public.connections SET generation=1",
        ),
        (
            "public.connections",
            "UPDATE public.connections SET status='DISCONNECTED'",
            "UPDATE public.connections SET status='NOT_VERIFIED'",
        ),
    )
    for _name, revoke, restore in mutations:
        with admin.begin() as db:
            db.execute(text(revoke), ids)
        with authorized() as db, pytest.raises(AuthorizationDenied):
            recheck(db, scope)
        with admin.begin() as db:
            db.execute(text(restore), ids)
    with admin.begin() as db:
        db.execute(
            text("DELETE FROM wso_private.tvt_identity_grants WHERE id=:grant"), ids
        )
    with authorized() as db, pytest.raises(AuthorizationDenied):
        recheck(db, scope)

    command.downgrade(config, "0003a_assets")
    with admin.connect() as db:
        assert foundation_contract(db) == baseline
        assert (
            db.execute(text("SELECT * FROM public.connections ORDER BY id")).all()
            == rows_before
        )
        assert (
            db.execute(
                text(
                    "SELECT to_regprocedure('public.wso_authorize_domain(text,uuid,uuid,uuid,uuid,uuid,text)')"
                )
            ).scalar_one()
            is None
        )
        for table in TABLES:
            assert (
                db.execute(
                    text("SELECT to_regclass(:t)"), {"t": "wso_private." + table}
                ).scalar_one()
                is None
            )
    command.upgrade(config, "0004_tvt_domain")
    seed_domain(admin, ids)
    with authorized() as db:
        assert authorize(db, target, "media.live").actor_id == ids["staff"]


@contextmanager
def protected_actor(engines, ids, actor="staff"):
    with identity_session(
        "https://w02.test",
        str(ids[actor]),
        session_factory=sessionmaker(engines["IDENTITY"]),
    ) as lookup:
        choice = lookup.authorize_tenant(ids["tenant"])
    with tenant_session(
        ids["tenant"],
        authorization=choice,
        session_factory=sessionmaker(engines["APP"]),
    ) as db:
        yield db


def test_assignment_writes_require_protected_owner(disposable_domain_db):
    """A raw staff caller must not create the missing independent assignment."""
    engines, config = disposable_domain_db
    admin = engines["ADMIN"]
    ids = seed_foundation(admin)
    command.upgrade(config, "0004_tvt_domain")
    seed_domain(admin, ids)
    sibling = DomainTarget(
        "TVT", ids["identity"], ids["device"], ids["channel"], ids["sibling_store"]
    )
    original = replace(sibling, store_id=ids["store"])
    with protected_actor(engines, ids) as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM public.store_memberships")
            ).scalar_one()
            == 1
        )
        with pytest.raises(AuthorizationDenied):
            authorize(db, sibling, "media.live")
        # Preserve the actual exploit result if the vulnerable SQL accepts this.
        try:
            with db.begin_nested():
                db.execute(
                    text(
                        "INSERT INTO public.store_memberships(tenant_id,user_id,store_id) VALUES(:tenant,:staff,:sibling_store)"
                    ),
                    ids,
                )
        except DBAPIError as denied:
            assert denied.orig.sqlstate == "42501"
        else:
            authorize(db, sibling, "media.live")
            pytest.fail(
                "STAFF self-assignment INSERT succeeded and enabled sibling-store authorization"
            )
        db.execute(text("SELECT set_config('app.role','OWNER',true)"))
        for actor in ("staff", "owner"):
            with pytest.raises(DBAPIError) as denied, db.begin_nested():
                db.execute(
                    text(
                        "INSERT INTO public.store_memberships(tenant_id,user_id,store_id) VALUES(:tenant,:actor,:sibling_store)"
                    ),
                    {**ids, "actor": ids[actor]},
                )
            assert denied.value.orig.sqlstate == "42501"
        for sql in (
            "UPDATE public.store_memberships SET store_id=:sibling_store WHERE user_id=:staff",
            "UPDATE public.store_memberships SET user_id=:owner WHERE user_id=:staff",
            "UPDATE public.store_memberships SET tenant_id=:other_tenant,store_id=:foreign_store WHERE user_id=:staff",
            "DELETE FROM public.store_memberships WHERE user_id=:staff",
        ):
            assert db.execute(text(sql), ids).rowcount == 0
        assert authorize(db, original, "media.live")
        with pytest.raises(AuthorizationDenied):
            authorize(db, sibling, "media.live")
    # Preserve ordinary OWNER store management: insert, update user/store, delete.
    with protected_actor(engines, ids, "owner") as db:
        assert (
            db.execute(
                text(
                    "INSERT INTO public.store_memberships(tenant_id,user_id,store_id) VALUES(:tenant,:staff,:sibling_store)"
                ),
                ids,
            ).rowcount
            == 1
        )
        assert (
            db.execute(
                text(
                    "UPDATE public.store_memberships SET user_id=:owner WHERE store_id=:sibling_store AND user_id=:staff"
                ),
                ids,
            ).rowcount
            == 1
        )
        assert (
            db.execute(
                text(
                    "UPDATE public.store_memberships SET store_id=:store WHERE user_id=:owner"
                ),
                ids,
            ).rowcount
            == 1
        )
        assert (
            db.execute(
                text("DELETE FROM public.store_memberships WHERE user_id=:owner"), ids
            ).rowcount
            == 1
        )
        assert (
            db.execute(
                text("DELETE FROM public.store_memberships WHERE user_id=:staff"), ids
            ).rowcount
            == 1
        )
    with protected_actor(engines, ids) as db:
        with pytest.raises(AuthorizationDenied):
            authorize(db, original, "media.live")
        with pytest.raises(DBAPIError) as denied, db.begin_nested():
            db.execute(
                text(
                    "INSERT INTO public.store_memberships(tenant_id,user_id,store_id) VALUES(:tenant,:staff,:store)"
                ),
                ids,
            )
        assert denied.value.orig.sqlstate == "42501"
    with protected_actor(engines, ids, "owner") as db:
        db.execute(
            text(
                "INSERT INTO public.store_memberships(tenant_id,user_id,store_id) VALUES(:tenant,:staff,:store)"
            ),
            ids,
        )
    with protected_actor(engines, ids) as db:
        assert authorize(db, original, "media.live")


def test_lifecycle_timestamps_maintained(disposable_domain_db):
    """Every operational table stamps inserts and preserves creation on update."""
    engines, config = disposable_domain_db
    admin = engines["ADMIN"]
    ids = seed_foundation(admin)
    command.upgrade(config, "0004_tvt_domain")
    with admin.connect() as db:
        started = db.execute(text("SELECT clock_timestamp()")).scalar_one()
    seed_domain(admin, ids)
    with admin.begin() as db:
        columns = db.execute(
            text(
                "SELECT table_name,column_name,data_type,column_default,is_nullable FROM information_schema.columns WHERE table_schema='wso_private' AND table_name=ANY(:tables) AND column_name IN ('created_at','updated_at')"
            ),
            {"tables": list(TABLES)},
        ).all()
        assert len(columns) == 24, (
            "all twelve operational tables need both lifecycle columns"
        )
        assert all(
            row.data_type == "timestamp with time zone"
            and row.column_default is not None
            and row.is_nullable == "NO"
            for row in columns
        )
        for table in TABLES:
            rows = db.execute(
                text(f"SELECT id,created_at,updated_at FROM wso_private.{table}")
            ).all()
            assert rows
            assert all(
                row.created_at.tzinfo is not None
                and started <= row.created_at == row.updated_at
                for row in rows
            )
            for row in rows:
                changed = db.execute(
                    text(
                        f"UPDATE wso_private.{table} SET created_at='2000-01-01 UTC',updated_at='2000-01-01 UTC' WHERE id=:id RETURNING created_at,updated_at"
                    ),
                    {"id": row.id},
                ).one()
                assert changed.created_at == row.created_at
                assert changed.updated_at > row.updated_at
    command.downgrade(config, "0003a_assets")
    command.upgrade(config, "0004_tvt_domain")
    seed_domain(admin, ids)
    with admin.connect() as db:
        for table in TABLES:
            assert (
                db.execute(
                    text(
                        f"SELECT count(*) FROM wso_private.{table} WHERE created_at=updated_at AND created_at IS NOT NULL"
                    )
                ).scalar_one()
                > 0
            )
            assert (
                db.execute(
                    text(
                        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid=CAST(:t AS regclass)"
                    ),
                    {"t": "wso_private." + table},
                ).scalar_one()
                == "wso_domain_owner"
            )
