"""Opt-in W03 development diagnostic; not foundation/full14/live acceptance."""

import hashlib
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
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from wso_api.auth import (
    AuthService,
    AuthSettings,
    OIDCVerifier,
    PostgresSessionStore,
    WebSession,
    token_digest,
)
from wso_api.main import create_app
from wso_core.db import tenant_session
from wso_core.tenancy import identity_session

from tests.integration.test_tvt_domain_scope import seed_domain, seed_foundation
from tests.support.job_handlers import verify_fixture_database

ROOT = Path(__file__).resolve().parents[2]
ROLES = (
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


def profile_data():
    return {
        "profile_id": "superliveplus-en",
        "source_apk_sha256": "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281",
        "brand": "SuperLivePlus",
        "region": "test",
        "consent_version": "test-v1",
        "default_locale": "en",
        "default_timezone": "UTC",
        "supported_locales": ["en", "ko"],
        "terms": {
            "source_reference": "agreement/ServiceTerms_en.html",
            "url": "https://app.test/policies/terms",
        },
        "privacy": {
            "source_reference": "agreement/PrivacyStatement_en.html",
            "url": "https://app.test/policies/privacy",
        },
        "local_routes": ["/tvt/settings"],
    }


def baseline(db):
    return (
        db.execute(
            text(
                "SELECT n.nspname,p.proname,p.oid::regprocedure::text,pg_get_functiondef(p.oid),p.proacl::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('public','wso_private') ORDER BY 1,2,3"
            )
        ).all(),
        db.execute(
            text(
                "SELECT n.nspname,c.relname,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity,a.attname,a.attacl::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 WHERE n.nspname IN ('public','wso_private') AND c.relkind='r' ORDER BY 1,2,6"
            )
        ).all(),
        db.execute(
            text(
                "SELECT n.nspname,c.relname,p.polname,p.polcmd,p.polroles::text,pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wso_private') ORDER BY 1,2,3"
            )
        ).all(),
    )


def foundation_rows(db):
    tables = db.execute(
        text(
            "SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wso_private') AND c.relkind='r' AND c.relname NOT IN ('alembic_version','tvt_user_preferences','tvt_user_consents') ORDER BY 1,2"
        )
    ).all()
    return {
        f"{schema}.{table}": hashlib.sha256(
            str(
                db.execute(
                    text(
                        f'SELECT row_to_json(t)::text FROM "{schema}"."{table}" t ORDER BY row_to_json(t)::text'
                    )
                ).all()
            ).encode()
        ).hexdigest()
        for schema, table in tables
    }


@pytest.fixture(scope="module")
def startup_db():
    if os.getenv("WSO_TEST_W03_STARTUP_DIAGNOSTIC") != "1":
        pytest.skip("requires explicit W03 development diagnostic activation")
    assert all(os.getenv(f"WSO_TEST_{role}_DATABASE_URL") for role in ROLES), (
        "all nine role URLs required"
    )
    urls = {
        role: make_url(os.environ[f"WSO_TEST_{role}_DATABASE_URL"]) for role in ROLES
    }
    bounds = {
        "connect_timeout": 5,
        "options": "-c statement_timeout=10000 -c lock_timeout=3000",
    }
    source = create_engine(urls["ADMIN"], hide_parameters=True, connect_args=bounds)
    control = None
    engines = {}
    identity = None
    name = "w03_startup_" + uuid4().hex
    marker = "owned-w03-startup-" + uuid4().hex
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
            assert re.fullmatch(r"w03_startup_[0-9a-f]{32}", name)
            assert (
                db.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname=:n"),
                    {"n": name},
                ).scalar_one()
                == 0
            )
            db.execute(
                text(f'CREATE DATABASE "{name}" OWNER wso_migrator TEMPLATE template0')
            )
            db.execute(text(f"COMMENT ON DATABASE \"{name}\" IS '{marker}'"))
            identity = db.execute(
                text(
                    "SELECT oid,datdba,pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:n"
                ),
                {"n": name},
            ).one()
            assert identity[2:] == ("wso_migrator", marker)
        engines = {
            role: create_engine(
                url.set(database=name), hide_parameters=True, connect_args=bounds
            )
            for role, url in urls.items()
        }
        config = Config(str(ROOT / "infra/alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            urls["ADMIN"]
            .set(database=name)
            .render_as_string(hide_password=False)
            .replace("%", "%%"),
        )
        command.upgrade(config, "0005_tvt_credentials")
        ids = seed_foundation(engines["ADMIN"])
        seed_domain(engines["ADMIN"], ids)
        with engines["ADMIN"].connect() as db:
            before = baseline(db)
            rows = foundation_rows(db)
        command.upgrade(config, "0006_tvt_startup")
        with engines["ADMIN"].connect() as db:
            after = baseline(db)
            assert all(
                set(old).issubset(set(new))
                for old, new in zip(before, after, strict=True)
            )
            assert foundation_rows(db) == rows
        yield engines, config, ids
        with engines["ADMIN"].connect() as db:
            rows = foundation_rows(db)
        command.downgrade(config, "0005_tvt_credentials")
        with engines["ADMIN"].connect() as db:
            assert baseline(db) == before
            assert foundation_rows(db) == rows
        command.upgrade(config, "0006_tvt_startup")
        with engines["ADMIN"].connect() as db:
            assert foundation_rows(db) == rows
        command.downgrade(config, "0005_tvt_credentials")
        with engines["ADMIN"].connect() as db:
            assert baseline(db) == before
    finally:
        for engine in engines.values():
            engine.dispose()
        if control is not None:
            try:
                if identity is not None:
                    verify_fixture_database(source, domain_only=sys.platform == "win32")
                    assert re.fullmatch(r"w03_startup_[0-9a-f]{32}", name)
                    with control.connect() as db:
                        current = db.execute(
                            text(
                                "SELECT oid,datdba,pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:n"
                            ),
                            {"n": name},
                        ).one()
                        assert current == identity
                        db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            finally:
                control.dispose()
        source.dispose()


@contextmanager
def actor_db(startup_db, actor="staff", tenant="tenant"):
    engines, _, ids = startup_db
    with identity_session(
        "https://w02.test",
        str(ids[actor]),
        session_factory=sessionmaker(engines["IDENTITY"]),
    ) as lookup:
        choice = lookup.authorize_tenant(ids[tenant])
    with tenant_session(
        ids[tenant], authorization=choice, session_factory=sessionmaker(engines["APP"])
    ) as db:
        yield db


@pytest.fixture
def startup_client(startup_db):
    from wso_core.tvt.startup import StartupProfile

    engines, _, ids = startup_db
    settings = AuthSettings(
        issuer="https://w02.test",
        audience="wso-web",
        jwks_url="https://w02.test/keys",
        exchange_key="x" * 48,
        public_origin="https://app.test",
        session_database_url="postgresql+psycopg://wso_web_session@localhost/test",
    )
    sessions = PostgresSessionStore(
        settings.session_database_url, session_factory=sessionmaker(engines["SESSION"])
    )
    service = AuthService(
        settings,
        OIDCVerifier(settings),
        sessions,
        identity_factory=sessionmaker(engines["IDENTITY"]),
        tenant_factory=sessionmaker(engines["APP"]),
    )
    app = create_app()
    app.state.auth_service = service
    app.state.tvt_startup_profile = StartupProfile.model_validate(profile_data())
    with TestClient(app, base_url="https://app.test") as client:

        def login(actor="staff"):
            token = uuid4().hex
            assert sessions.create(
                token_digest(token),
                WebSession(
                    "https://w02.test",
                    str(ids[actor]),
                    ids[actor],
                    token_digest("csrf"),
                    datetime.now(UTC) + timedelta(minutes=10),
                ),
                token_digest(uuid4().hex),
            )
            client.cookies.set("__Host-wso-session", token)

        login()
        yield client, ids, login


def test_real_api_versioned_choices_and_user_tenant_isolation(startup_client):
    from wso_core.tvt.startup import StartupProfile

    api, ids, login = startup_client
    q = {"tenant_id": str(ids["tenant"])}
    headers = {"Origin": "https://app.test", "X-CSRF-Token": "csrf"}
    r = api.get("/api/v1/tvt/bootstrap", params=q)
    assert r.status_code == 200, r.text
    initial = r.json()
    assert initial["consent"]["status"] == "pending"
    assert initial["identity"] == {"state": "unlinked", "accounts": []}
    assert initial["menu"] == [
        {"id": "local-settings", "label": "Settings", "path": "/tvt/settings"}
    ]
    r = api.post(
        "/api/v1/tvt/consent",
        params=q,
        headers=headers,
        json={"version": "test-v1", "decision": "accepted"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted" and r.json()["decided_at"]
    r = api.put(
        "/api/v1/tvt/preferences",
        params=q,
        headers=headers,
        json={"locale": "ko", "timezone": "Asia/Seoul"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"locale": "ko", "timezone": "Asia/Seoul"}
    assert api.get("/api/v1/tvt/bootstrap", params=q).json()["locale"] == "ko"
    login("owner")
    other = api.get("/api/v1/tvt/bootstrap", params=q).json()
    assert other["consent"]["status"] == "pending" and other["locale"] == "en"
    login()
    other = api.get(
        "/api/v1/tvt/bootstrap", params={"tenant_id": str(ids["other_tenant"])}
    ).json()
    assert other["consent"]["status"] == "pending" and other["locale"] == "en"
    api.app.state.tvt_startup_profile = StartupProfile.model_validate(
        {**profile_data(), "consent_version": "test-v2"}
    )
    assert (
        api.get("/api/v1/tvt/bootstrap", params=q).json()["consent"]["status"]
        == "pending"
    )
    r = api.post(
        "/api/v1/tvt/consent",
        params=q,
        headers=headers,
        json={"version": "test-v1", "decision": "accepted"},
    )
    assert r.status_code == 409
    r = api.post(
        "/api/v1/tvt/consent",
        params=q,
        headers=headers,
        json={"version": "test-v2", "decision": "declined"},
    )
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert (
        api.get("/api/v1/tvt/bootstrap", params=q).json()["consent"]["status"]
        == "declined"
    )
    r = api.put(
        "/api/v1/tvt/preferences",
        params=q,
        headers=headers,
        json={"locale": "fr", "timezone": "UTC"},
    )
    assert r.status_code == 422
    assert api.get("/api/v1/tvt/bootstrap", params=q).json()["locale"] == "ko"
    assert (
        api.get("/api/v1/tvt/bootstrap", params={"tenant_id": str(uuid4())}).status_code
        == 404
    )


def test_raw_guc_cannot_read_or_write_and_runtime_has_no_table_access(startup_db):
    engines, _, ids = startup_db
    for sql in (
        "SELECT * FROM public.wso_tvt_startup_read('p','v')",
        "SELECT * FROM public.wso_tvt_preferences_write('p','en','UTC')",
        "SELECT * FROM public.wso_tvt_consent_write('p','v','accepted')",
        "SELECT * FROM public.wso_tvt_startup_accounts()",
    ):
        with engines["APP"].begin() as db:
            db.execute(
                text(
                    "SELECT set_config('app.tenant_id',:t,true),set_config('app.user_id',:u,true),set_config('app.role','OWNER',true)"
                ),
                {"t": str(ids["tenant"]), "u": str(ids["owner"])},
            )
            assert db.execute(text(sql)).all() == []
    for role in ROLES[1:]:
        if role == "MIGRATOR":
            continue
        for table in ("tvt_user_preferences", "tvt_user_consents"):
            with engines[role].begin() as db, pytest.raises(DBAPIError):
                db.execute(text(f"SELECT * FROM wso_private.{table}"))
    with engines["ADMIN"].connect() as db:
        rows = db.execute(
            text(
                "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) FROM pg_class c WHERE c.relname IN ('tvt_user_preferences','tvt_user_consents') ORDER BY 1"
            )
        ).all()
        assert rows == [
            ("tvt_user_consents", True, True, "wso_domain_owner"),
            ("tvt_user_preferences", True, True, "wso_domain_owner"),
        ]


def test_account_metadata_requires_explicit_current_account_read_intersection(
    startup_db, startup_client
):
    engines, _, ids = startup_db
    api, _, login = startup_client
    q = {"tenant_id": str(ids["tenant"])}
    assert (
        api.get("/api/v1/tvt/bootstrap", params=q).json()["identity"]["accounts"] == []
    )
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_identity_grants(id,tenant_id,identity_id,actor_id,action,revision,expires_at) VALUES(:g,:tenant,:identity,:staff,'account.read',1,clock_timestamp()+interval '1 hour')"
            ),
            {**ids, "g": uuid4()},
        )
        for name in ("tvt_upstream_grants", "tvt_capability_snapshots"):
            db.execute(
                text(
                    f"INSERT INTO wso_private.{name}(id,tenant_id,identity_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(:g,:tenant,:identity,'account.read',true,1,1,clock_timestamp(),clock_timestamp()+interval '1 hour')"
                ),
                {**ids, "g": uuid4()},
            )
    result = api.get("/api/v1/tvt/bootstrap", params=q).json()["identity"]
    assert result == {
        "state": "linked",
        "accounts": [{"id": str(ids["identity"]), "brand": "test", "region": "test"}],
    }
    login("owner")
    assert (
        api.get("/api/v1/tvt/bootstrap", params=q).json()["identity"]["accounts"] == []
    )
    login()
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.tvt_capability_snapshots SET verified=false WHERE identity_id=:identity AND action='account.read'"
            ),
            ids,
        )
    assert (
        api.get("/api/v1/tvt/bootstrap", params=q).json()["identity"]["accounts"] == []
    )


def test_choices_fail_closed_after_membership_change_and_transaction_end(startup_db):
    engines, _, ids = startup_db
    with actor_db(startup_db) as db:
        assert (
            db.execute(
                text("SELECT * FROM public.wso_tvt_startup_read('p','v')")
            ).first()
            is not None
        )
    with engines["APP"].begin() as db:
        assert (
            db.execute(text("SELECT * FROM public.wso_tvt_startup_read('p','v')")).all()
            == []
        )
    with identity_session(
        "https://w02.test",
        str(ids["staff"]),
        session_factory=sessionmaker(engines["IDENTITY"]),
    ) as lookup:
        stale = lookup.authorize_tenant(ids["tenant"])
    with engines["ADMIN"].begin() as admin:
        admin.execute(
            text(
                "UPDATE public.memberships SET role='MANAGER' WHERE tenant_id=:tenant AND user_id=:staff"
            ),
            ids,
        )
    try:
        with (
            pytest.raises(PermissionError),
            tenant_session(
                ids["tenant"],
                authorization=stale,
                session_factory=sessionmaker(engines["APP"]),
            ) as db,
        ):
            db.execute(text("SELECT * FROM public.wso_tvt_startup_read('p','v')"))
    finally:
        with engines["ADMIN"].begin() as admin:
            admin.execute(
                text(
                    "UPDATE public.memberships SET role='STAFF' WHERE tenant_id=:tenant AND user_id=:staff"
                ),
                ids,
            )
    for role in ROLES:
        if role in {"ADMIN", "APP", "MIGRATOR"}:
            continue
        with engines[role].begin() as db, pytest.raises(DBAPIError):
            db.execute(text("SELECT * FROM public.wso_tvt_startup_read('p','v')"))
