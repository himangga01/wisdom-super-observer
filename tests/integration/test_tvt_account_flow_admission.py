"""W06 guarded PostgreSQL authority acceptance, never live TVT execution."""

import hashlib
import importlib.util
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from wso_contracts.tvt.account_flows import AccountFlowReference, AccountFlowStart
from wso_core.db import tenant_session
from wso_core.tenancy import identity_session
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.flow_admission import FlowAdmission, FlowTicketIssuer

from tests.integration.test_tvt_domain_scope import seed_foundation
from tests.integration.test_tvt_sessions import foundation_contents, function_owners
from tests.support.job_handlers import verify_fixture_database

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT
    / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W06-flow-fixture-portability-evidence"
)
TABLES = ("tvt_flows", "tvt_flow_tickets", "tvt_flow_intents", "tvt_flow_policies")


def authority_definitions(db):
    return (
        db.execute(
            text(
                "SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid),p.proacl::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('public','wso_private') ORDER BY 1"
            )
        ).all(),
        db.execute(
            text(
                "SELECT n.nspname,c.relname,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wso_private') AND c.relkind='r' ORDER BY 1,2"
            )
        ).all(),
        db.execute(
            text(
                "SELECT n.nspname,c.relname,p.polname,p.polroles::text,p.polcmd,p.polpermissive,pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wso_private') ORDER BY 1,2,3"
            )
        ).all(),
    )


def test_flow_revision_has_a_separate_protected_authority_boundary():
    path = ROOT / "infra/migrations/versions/0010_tvt_account_flows.py"
    assert path.exists(), "A separate protected flow admission revision is required"
    spec = importlib.util.spec_from_file_location("flow_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0009_asset_read_denial"


def flow_linux_table_roster():
    # Head0011 adds only wso_private.tvt_directory_tickets: canonical66.
    # Root e216 offline0010 inventory: 65 canonical public/private tables.
    # SQL (strict LF) SHA256: 5b0b4e165056d76d3e488164bdfe84a76fac09a17ec35ce315cbbd22f72cd19e
    # Source0010 SHA256: a8c39baf215e3b8fea4b92e5df96c21bf1701b9edbb7d61f62e27860af2e5958
    return frozenset(
        {
            ("public", "alembic_version"),
            ("public", "assets"),
            ("public", "audit_events"),
            ("public", "connections"),
            ("public", "inbox_dedup"),
            ("public", "job_assets"),
            ("public", "job_connections"),
            ("public", "job_items"),
            ("public", "jobs"),
            ("public", "memberships"),
            ("public", "outbox"),
            ("public", "store_connections"),
            ("public", "store_memberships"),
            ("public", "stores"),
            ("public", "tenants"),
            ("public", "users"),
            ("public", "web_sessions"),
            ("wso_private", "asset_audit_outbox"),
            ("wso_private", "asset_cleanup"),
            ("wso_private", "asset_job_kinds"),
            ("wso_private", "asset_read_leases"),
            ("wso_private", "asset_reconciliation"),
            ("wso_private", "asset_settings"),
            ("wso_private", "asset_tickets"),
            ("wso_private", "asset_uploads"),
            ("wso_private", "connection_handles"),
            ("wso_private", "connection_leases"),
            ("wso_private", "connection_revocations"),
            ("wso_private", "connection_secrets"),
            ("wso_private", "dispatch_ready"),
            ("wso_private", "domain_credential_capabilities"),
            ("wso_private", "domain_credential_connections"),
            ("wso_private", "job_contexts"),
            ("wso_private", "job_kinds"),
            ("wso_private", "job_settings"),
            ("wso_private", "operation_constraint_backup"),
            ("wso_private", "operation_holds"),
            ("wso_private", "operation_target_observations"),
            ("wso_private", "operation_tickets"),
            ("wso_private", "operations"),
            ("wso_private", "tenant_contexts"),
            ("wso_private", "tenant_grants"),
            ("wso_private", "tvt_account_challenges"),
            ("wso_private", "tvt_account_sessions"),
            ("wso_private", "tvt_account_storage"),
            ("wso_private", "tvt_account_tickets"),
            ("wso_private", "tvt_account_tokens"),
            ("wso_private", "tvt_capability_snapshots"),
            ("wso_private", "tvt_channels"),
            ("wso_private", "tvt_device_links"),
            ("wso_private", "tvt_device_store_links"),
            ("wso_private", "tvt_directory_tickets"),
            ("wso_private", "tvt_flow_intents"),
            ("wso_private", "tvt_flow_policies"),
            ("wso_private", "tvt_flow_tickets"),
            ("wso_private", "tvt_flows"),
            ("wso_private", "tvt_identities"),
            ("wso_private", "tvt_identity_grants"),
            ("wso_private", "tvt_upstream_grants"),
            ("wso_private", "tvt_user_consents"),
            ("wso_private", "tvt_user_preferences"),
            ("wso_private", "tyco_capability_snapshots"),
            ("wso_private", "tyco_identities"),
            ("wso_private", "tyco_identity_grants"),
            ("wso_private", "tyco_panels"),
            ("wso_private", "tyco_upstream_grants"),
        }
    )


def verify_flow_recovery_fixture(db):
    """Read-only validation of the optional trusted job recovery fixture."""
    identity = db.execute(
        text("""
            SELECT pg_get_userbyid(c.relowner) AS recovery_owner,
                   c.relrowsecurity,c.relforcerowsecurity,c.relkind::text,
                   c.relpersistence::text,c.relispartition,
                   ARRAY(SELECT ROW(a.grantor,a.grantee,a.privilege_type,a.is_grantable)::text
                         FROM aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
                         WHERE a.grantee=c.relowner ORDER BY 1)
                   = ARRAY(SELECT ROW(a.grantor,a.grantee,a.privilege_type,a.is_grantable)::text
                           FROM aclexplode(acldefault('r',c.relowner)) a ORDER BY 1),
                   NOT c.relhasrules
                   AND NOT EXISTS(SELECT 1 FROM pg_trigger t
                                  WHERE t.tgrelid=c.oid AND NOT t.tgisinternal)
                   AND NOT EXISTS(SELECT 1 FROM pg_inherits i
                                  WHERE i.inhrelid=c.oid OR i.inhparent=c.oid)
                   AND (SELECT count(*) FROM pg_index i WHERE i.indrelid=c.oid)=1
            FROM pg_class c
            WHERE c.oid='public.job_recovery_effects'::regclass
        """)
    ).one()
    assert tuple(identity) == ("wso_migrator", True, True, "r", "p", False, True, True)
    columns = db.execute(
        text("""
            SELECT a.attname::text,format_type(a.atttypid,a.atttypmod),a.attnotnull,
                   pg_get_expr(d.adbin,d.adrelid),a.attidentity::text,
                   a.attgenerated::text,a.attacl IS NULL
            FROM pg_attribute a LEFT JOIN pg_attrdef d
              ON d.adrelid=a.attrelid AND d.adnum=a.attnum
            WHERE a.attrelid='public.job_recovery_effects'::regclass
              AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum
        """)
    ).all()
    assert [tuple(row) for row in columns] == [
        ("tenant_id", "uuid", True, None, "", "", True),
        ("job_id", "uuid", True, None, "", "", True),
        ("effect_count", "bigint", True, None, "", "", True),
    ]
    constraints = db.execute(
        text("""
            SELECT c.contype::text,
                   ARRAY(SELECT a.attname::text
                         FROM unnest(c.conkey) WITH ORDINALITY k(attnum,ordinal)
                         JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum
                         ORDER BY k.ordinal),n.nspname::text,r.relname::text,
                   ARRAY(SELECT a.attname::text
                         FROM unnest(c.confkey) WITH ORDINALITY k(attnum,ordinal)
                         JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.attnum
                         ORDER BY k.ordinal),
                   CASE WHEN c.contype='f' THEN c.confupdtype::text END,
                   CASE WHEN c.contype='f' THEN c.confdeltype::text END,
                   CASE WHEN c.contype='f' THEN c.confmatchtype::text END,
                   CASE WHEN c.contype='c' THEN c.connoinherit END,
                   c.condeferrable,c.condeferred,c.convalidated,
                   regexp_replace(pg_get_expr(c.conbin,c.conrelid),'[[:space:]()]','','g')
            FROM pg_constraint c LEFT JOIN pg_class r ON r.oid=c.confrelid
            LEFT JOIN pg_namespace n ON n.oid=r.relnamespace
            WHERE c.conrelid='public.job_recovery_effects'::regclass ORDER BY c.contype
        """)
    ).all()
    assert [tuple(row) for row in constraints] == [
        (
            "c",
            ["effect_count"],
            None,
            None,
            [],
            None,
            None,
            None,
            False,
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
            "s",
            None,
            False,
            False,
            True,
            None,
        ),
        (
            "p",
            ["job_id"],
            None,
            None,
            [],
            None,
            None,
            None,
            None,
            False,
            False,
            True,
            None,
        ),
    ]
    policies = db.execute(
        text("""
            SELECT p.polname::text,p.polcmd::text,p.polpermissive,
                   ARRAY(SELECT CASE WHEN role_oid=0 THEN 'PUBLIC' ELSE pg_get_userbyid(role_oid) END
                         FROM unnest(p.polroles) roles(role_oid) ORDER BY 1),
                   pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)
            FROM pg_policy p WHERE p.polrelid='public.job_recovery_effects'::regclass
            ORDER BY p.polname
        """)
    ).all()
    assert len(policies) == 1
    policy = tuple(policies[0])
    assert policy[:4] == ("recovery_worker", "*", True, ["wso_job_worker"])
    assert all(
        expression is not None
        and re.sub(r"[\s()]", "", expression).replace("public.", "")
        == "job_id=wso_current_job_id"
        for expression in policy[4:]
    )
    acls = db.execute(
        text("""
            SELECT pg_get_userbyid(a.grantor),
                   CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
                   a.privilege_type,a.is_grantable
            FROM pg_class c,
                 LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
            WHERE c.oid='public.job_recovery_effects'::regclass AND a.grantee<>c.relowner
            ORDER BY 1,2,3
        """)
    ).all()
    assert [tuple(row) for row in acls] == [
        ("wso_migrator", "wso_job_worker", "INSERT", False),
        ("wso_migrator", "wso_job_worker", "SELECT", False),
        ("wso_migrator", "wso_job_worker", "UPDATE", False),
    ]


def verify_flow_linux_tables(db, tables):
    canonical = flow_linux_table_roster()
    observed = frozenset(tuple(row) for row in tables)
    recovery = ("public", "job_recovery_effects")
    assert len(tables) == len(observed)
    assert observed in (canonical, canonical | {recovery})
    if recovery in observed:
        verify_flow_recovery_fixture(db)


def flow_source_expectations():
    if sys.platform == "win32":
        return "wso_test", 16384, "postgres", "0003a_assets", 36
    if sys.platform == "linux":
        # The container guard proves the fresh CI resource. Its OID is observed
        # and retained in source custody, rather than borrowed from Windows.
        return "wso_ci_test", None, "postgres", "0011_tvt_directory_read_tickets", 66
    raise ValueError("W06 requires the managed Windows or Linux CI source")


def flow_parent_sha256():
    activation = os.environ.get("WSO_TEST_W06_FLOW_ACCEPTANCE")
    if activation is None:
        pytest.skip(
            "requires reviewed parent and explicit owned W06 database activation"
        )
    assert activation == "1"
    expected = os.environ.get("WSO_TEST_W06_PARENT_SHA256")
    assert (
        expected == "3a2fc52bb33a86058d5f13d36f6112986f1ef4117032c64cc268e2e88f61572e"
    )
    assert (
        hashlib.sha256(
            (ROOT / "infra/migrations/versions/0009_asset_read_denial.py").read_bytes()
        ).hexdigest()
        == expected
    )
    return expected


def flow_source_snapshot(source):
    name, oid, owner, revision, count = flow_source_expectations()
    verify_fixture_database(source, domain_only=sys.platform == "win32")
    with source.connect() as db:
        row = db.execute(
            text(
                "SELECT current_database(),oid,pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()"
            )
        ).one()
        observed_revision = db.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one()
        assert row[0] == name and row[2] == owner and observed_revision == revision
        assert type(row[1]) is int and row[1] > 0
        assert oid is None or row[1] == oid
        if sys.platform == "linux":
            table_objects = db.execute(
                text(
                    "SELECT n.nspname,c.relname,c.relkind::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wso_private') AND c.relkind IN ('r','p','f') ORDER BY 1,2"
                )
            ).all()
            # Foreign table data must never be read by foundation_contents.
            assert all(kind == "r" for _, _, kind in table_objects)
            tables = [(schema, table) for schema, table, _ in table_objects]
            verify_flow_linux_tables(db, tables)
        else:
            tables = db.execute(
                text(
                    "SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wso_private') AND c.relkind='r' ORDER BY 1,2"
                )
            ).all()
        contents = foundation_contents(db, tables)
        assert len(contents) == (len(tables) if sys.platform == "linux" else count)
        return tuple(row), observed_revision, contents


@pytest.fixture(scope="module")
def flow_database():
    expected = flow_parent_sha256()
    source_name = flow_source_expectations()[0]
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
    urls = {
        role: make_url(os.environ[f"WSO_TEST_{role}_DATABASE_URL"]) for role in roles
    }
    assert all(
        (u.host, u.port, u.database)
        == (urls["ADMIN"].host, urls["ADMIN"].port, source_name)
        for u in urls.values()
    )
    options = {
        "hide_parameters": True,
        "connect_args": {
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c lock_timeout=3000",
        },
    }
    source = create_engine(urls["ADMIN"], **options)
    before_source = flow_source_snapshot(source)
    control = create_engine(
        urls["ADMIN"].set(database="postgres"), isolation_level="AUTOCOMMIT", **options
    )
    name, marker = "w06_flow_" + uuid4().hex, "owned-w06-flow-" + uuid4().hex
    identity, engines = None, {}
    receipt = {
        "name": name,
        "marker": marker,
        "parent_sha256": expected,
        "cleanup": False,
    }

    receipt["source_identity"] = {
        "name": before_source[0][0],
        "oid": before_source[0][1],
        "owner": before_source[0][2],
        "revision": before_source[1],
        "table_count": len(before_source[2]),
    }
    receipt["source_before"] = [
        {"schema": schema, "table": table, "owner": value[0], "rows_sha256": value[1]}
        for (schema, table), value in before_source[2].items()
    ]
    try:
        with control.connect() as db:
            assert re.fullmatch(r"w06_flow_[0-9a-f]{32}", name)
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
            receipt.update(oid=identity[0], owner_oid=identity[1], owner=identity[2])
        engines = {
            role: create_engine(url.set(database=name), **options)
            for role, url in urls.items()
        }
        assert all(engine.url.database == name for engine in engines.values())
        config = Config(str(ROOT / "infra/alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            urls["ADMIN"]
            .set(database=name)
            .render_as_string(hide_password=False)
            .replace("%", "%%"),
        )

        def migrate(direction, revision):
            assert (
                hashlib.sha256(
                    (
                        ROOT / "infra/migrations/versions/0009_asset_read_denial.py"
                    ).read_bytes()
                ).hexdigest()
                == expected
            )
            getattr(command, direction)(config, revision)

        migrate("upgrade", "0009_asset_read_denial")
        seed_foundation(engines["ADMIN"])
        with engines["ADMIN"].connect() as db:
            rows, owners = foundation_contents(db), function_owners(db)
            before_authority = authority_definitions(db)
        migrate("upgrade", "0010_tvt_account_flows")
        migrate("downgrade", "0009_asset_read_denial")
        with engines["ADMIN"].connect() as db:
            assert foundation_contents(db) == rows and function_owners(db) == owners
            assert authority_definitions(db) == before_authority
        migrate("upgrade", "0010_tvt_account_flows")
        with engines["ADMIN"].connect() as db:
            assert foundation_contents(db, rows) == rows
        receipt["roundtrip_preserved_parent_rows_owners"] = True
        receipt["roundtrip_preserved_parent_function_bodies_acls_policies"] = True
        yield engines
    finally:
        for engine in engines.values():
            engine.dispose()
        after_source = flow_source_snapshot(source)
        assert after_source == before_source
        receipt["source_after"] = [
            {
                "schema": schema,
                "table": table,
                "owner": value[0],
                "rows_sha256": value[1],
            }
            for (schema, table), value in after_source[2].items()
        ]
        receipt["source_unchanged"] = {
            "name": after_source[0][0],
            "oid": after_source[0][1],
            "owner": after_source[0][2],
            "revision": after_source[1],
            "table_count": len(after_source[2]),
            "content_equal": True,
        }
        if identity is not None:
            with control.connect() as db:
                current = db.execute(
                    text(
                        "SELECT oid,datdba,pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:n"
                    ),
                    {"n": name},
                ).one()
                assert current == identity
                db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
                assert (
                    db.execute(
                        text("SELECT count(*) FROM pg_database WHERE datname=:n"),
                        {"n": name},
                    ).scalar_one()
                    == 0
                )
                receipt["cleanup"] = True
        control.dispose()
        source.dispose()
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / f"database-{name}.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )


@pytest.fixture
def seeded_flow(flow_database):
    ids = seed_foundation(flow_database["ADMIN"])
    ids["session"] = uuid4().hex * 2
    ids["owner_session"] = uuid4().hex * 2
    with flow_database["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_flow_policies(region,brand,profile_id,consent_version,key_commitment,enabled) VALUES('test','brand','profile','v1',decode(:k,'hex'),true) ON CONFLICT(region,brand) DO UPDATE SET enabled=true,revision=1,consent_version='v1',key_commitment=EXCLUDED.key_commitment"
            ),
            {"k": hashlib.sha256(bytes(range(32))).hexdigest()},
        )
        for actor, session in (("staff", "session"), ("owner", "owner_session")):
            db.execute(
                text(
                    "INSERT INTO public.web_sessions(session_digest,csrf_digest,exchange_digest,issuer,subject,user_id,expires_at) VALUES(:s,:c,:e,'https://w02.test',:sub,:u,clock_timestamp()+interval '1 hour')"
                ),
                {
                    "s": ids[session],
                    "c": uuid4().hex * 2,
                    "e": uuid4().hex * 2,
                    "sub": str(ids[actor]),
                    "u": ids[actor],
                },
            )
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_user_consents(tenant_id,user_id,profile_id,version,status) VALUES(:t,:u,'profile','v1','accepted')"
                ),
                {"t": ids["tenant"], "u": ids[actor]},
            )
    yield flow_database, ids
    # Only this test's synthetic rows inside the guarded disposable DB. This
    # admin fixture cleanup is not a service release or reconciliation path.
    with flow_database["ADMIN"].begin() as db:
        db.execute(
            text(
                "DELETE FROM wso_private.tvt_flow_tickets WHERE flow_id IN (SELECT id FROM wso_private.tvt_flows WHERE tenant_id=:t)"
            ),
            {"t": ids["tenant"]},
        )
        db.execute(
            text("DELETE FROM wso_private.tvt_flow_intents WHERE tenant_id=:t"),
            {"t": ids["tenant"]},
        )
        db.execute(
            text("DELETE FROM wso_private.tvt_flows WHERE tenant_id=:t"),
            {"t": ids["tenant"]},
        )


@contextmanager
def actor_db(fixture, actor="staff", tenant="tenant"):
    engines, ids = fixture
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


def start_body(purpose="recover"):
    return AccountFlowStart(
        region="test",
        brand="brand",
        purpose=purpose,
        mode="email",
        account="private@example.invalid",
    )


def issue(
    fixture,
    operation="start",
    body=None,
    *,
    actor="staff",
    tenant="tenant",
    session=None,
):
    ids = fixture[1]
    with actor_db(fixture, actor, tenant) as db:
        return FlowTicketIssuer(db, lambda: 5000).issue(
            session or ids["owner_session" if actor == "owner" else "session"],
            operation,
            body or start_body(),
        )


@contextmanager
def admission(fixture):
    worker = FlowAdmission(
        fixture[0]["WORKER"].url.render_as_string(hide_password=False),
        hashlib.sha256(bytes(range(32))).hexdigest(),
    )
    try:
        yield worker
    finally:
        worker.close()


def reference(lease, **changes):
    return AccountFlowReference(
        region=lease.region,
        brand=lease.brand,
        purpose=lease.purpose,
        flow_id=lease.flow_id,
    ).model_copy(update=changes)


def opened(fixture, worker):
    lease = worker.redeem(issue(fixture), "start")
    assert worker.claim(lease) == "CLAIMED"
    worker.publish(lease, "CREATED")
    return lease


def test_policy_key_replacement_denied_while_pending_and_allowed_after_known_settlement(
    seeded_flow,
):
    engines, _ = seeded_flow
    replacement = hashlib.sha256(b"x" * 32).hexdigest()
    with admission(seeded_flow) as worker:
        old = opened(seeded_flow, worker)
        lease = worker.redeem(issue(seeded_flow, "recover", reference(old)), "recover")
        assert worker.claim(lease, uuid4().hex * 2) == "CLAIMED"
        with engines["ADMIN"].begin() as db, pytest.raises(DBAPIError):
            db.execute(
                text(
                    "UPDATE wso_private.tvt_flow_policies SET key_commitment=decode(:k,'hex') WHERE region='test' AND brand='brand'"
                ),
                {"k": replacement},
            )
        with engines["ADMIN"].begin() as db, pytest.raises(DBAPIError):
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_flow_policies(region,brand,profile_id,consent_version,key_commitment,enabled) VALUES('alternate','brand','profile','v1',decode(:k,'hex'),true)"
                ),
                {"k": replacement},
            )
        wrong = FlowAdmission(
            engines["WORKER"].url.render_as_string(hide_password=False), replacement
        )
        try:
            with pytest.raises(AccountFailure):
                wrong.redeem(issue(seeded_flow), "start")
            with pytest.raises(AccountFailure):
                wrong.check(lease)
            with pytest.raises(AccountFailure):
                wrong.claim(lease, uuid4().hex * 2)
            with pytest.raises(AccountFailure):
                wrong.publish(lease, "COMPLETE")
        finally:
            wrong.close()
        worker.publish(lease, "COMPLETE")
        outstanding = worker.redeem(
            issue(seeded_flow, "state", reference(old)), "state"
        )
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_flow_policies SET key_commitment=decode(:k,'hex') WHERE region='test' AND brand='brand'"
                ),
                {"k": replacement},
            )
        with pytest.raises(AccountFailure):
            worker.check(outstanding)
    successor = FlowAdmission(
        engines["WORKER"].url.render_as_string(hide_password=False), replacement
    )
    try:
        fresh = opened(seeded_flow, successor)
        assert fresh.key_commitment == replacement
        final = successor.redeem(
            issue(seeded_flow, "recover", reference(fresh)), "recover"
        )
        assert successor.claim(final, uuid4().hex * 2) == "CLAIMED"
        successor.publish(final, "FAILED")
    finally:
        successor.close()
    with engines["ADMIN"].begin() as db:
        assert (
            db.execute(
                text(
                    "SELECT outcome FROM wso_private.tvt_flow_intents WHERE flow_id=:f"
                ),
                {"f": old.flow_id},
            ).scalar_one()
            == "COMPLETE"
        )
        db.execute(
            text(
                "UPDATE wso_private.tvt_flow_policies SET key_commitment=decode(:k,'hex') WHERE region='test' AND brand='brand'"
            ),
            {"k": hashlib.sha256(bytes(range(32))).hexdigest()},
        )


def test_preexisting_cross_key_selections_race_cannot_create_two_pending_intents(
    seeded_flow,
):
    from concurrent.futures import ThreadPoolExecutor

    engines, _ = seeded_flow
    alternate = hashlib.sha256(b"x" * 32).hexdigest()
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_flow_policies(region,brand,profile_id,consent_version,key_commitment,enabled) VALUES('alternate','brand','profile','v1',decode(:k,'hex'),true)"
            ),
            {"k": alternate},
        )
    other = FlowAdmission(
        engines["WORKER"].url.render_as_string(hide_password=False), alternate
    )
    try:
        with admission(seeded_flow) as worker:
            first = opened(seeded_flow, worker)
            alternate_body = start_body().model_copy(update={"region": "alternate"})
            second = other.redeem(issue(seeded_flow, body=alternate_body), "start")
            assert other.claim(second) == "CLAIMED"
            other.publish(second, "CREATED")
            pairs = [
                (
                    worker,
                    worker.redeem(
                        issue(seeded_flow, "recover", reference(first)), "recover"
                    ),
                ),
                (
                    other,
                    other.redeem(
                        issue(seeded_flow, "recover", reference(second)), "recover"
                    ),
                ),
            ]

            def claim(pair):
                try:
                    return pair[0].claim(pair[1], uuid4().hex * 2)
                except AccountFailure:
                    return "DENIED"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(claim, pairs))
            assert sorted(outcomes) == ["CLAIMED", "DENIED"]
            for pair, result in zip(pairs, outcomes, strict=True):
                if result == "CLAIMED":
                    pair[0].publish(pair[1], "COMPLETE")
    finally:
        other.close()
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "DELETE FROM wso_private.tvt_flow_policies WHERE region='alternate' AND brand='brand'"
                )
            )


def test_actual_ticket_replay_current_authority_and_exact_session(seeded_flow):
    with admission(seeded_flow) as worker:
        ticket = issue(seeded_flow)
        with pytest.raises(AccountFailure):
            worker.redeem(uuid4().hex * 2, "start")
        with pytest.raises(AccountFailure):
            worker.redeem(ticket, "recover")
        lease = worker.redeem(ticket, "start")
        with pytest.raises(AccountFailure):
            worker.redeem(ticket, "start")
        with pytest.raises(AccountFailure):
            issue(seeded_flow, "state", reference(lease), actor="owner")
        with pytest.raises(AccountFailure):
            issue(seeded_flow, "state", reference(lease), tenant="other_tenant")
        with pytest.raises(AccountFailure):
            issue(seeded_flow, "state", reference(lease, purpose="register"))
        with pytest.raises(AccountFailure):
            issue(seeded_flow, "state", reference(lease, brand="other"))
        with pytest.raises(AccountFailure):
            issue(seeded_flow, session=seeded_flow[1]["owner_session"])
        with seeded_flow[0]["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                ),
                {"s": seeded_flow[1]["session"]},
            )
        with pytest.raises(AccountFailure):
            worker.check(lease)
        with pytest.raises(AccountFailure):
            worker.claim(lease)


@pytest.mark.parametrize(
    "revocation",
    [
        "membership",
        "role",
        "consent",
        "policy",
        "version",
        "session_expiry",
        "ticket_expiry",
    ],
)
def test_each_protected_fact_is_rechecked_before_claim(seeded_flow, revocation):
    engines, ids = seeded_flow
    with admission(seeded_flow) as worker:
        lease = worker.redeem(issue(seeded_flow), "start")
        statements = {
            "membership": "DELETE FROM public.memberships WHERE tenant_id=:t AND user_id=:u",
            "role": "UPDATE public.memberships SET role='MANAGER' WHERE tenant_id=:t AND user_id=:u",
            "consent": "UPDATE wso_private.tvt_user_consents SET status='declined' WHERE tenant_id=:t AND user_id=:u",
            "policy": "UPDATE wso_private.tvt_flow_policies SET enabled=false WHERE region='test' AND brand='brand'",
            "version": "UPDATE wso_private.tvt_flow_policies SET consent_version='v2' WHERE region='test' AND brand='brand'",
            "session_expiry": "UPDATE public.web_sessions SET created_at=clock_timestamp()-interval '2 hours',expires_at=clock_timestamp()-interval '1 hour' WHERE session_digest=:s",
            "ticket_expiry": "UPDATE wso_private.tvt_flow_tickets SET expires_at=clock_timestamp()-interval '1 second' WHERE flow_id=:f",
        }
        with engines["ADMIN"].begin() as db:
            if revocation == "membership":
                db.execute(
                    text(
                        "DELETE FROM public.store_memberships WHERE tenant_id=:t AND user_id=:u"
                    ),
                    {"t": ids["tenant"], "u": ids["staff"]},
                )
            db.execute(
                text(statements[revocation]),
                {
                    "t": ids["tenant"],
                    "u": ids["staff"],
                    "s": ids["session"],
                    "f": lease.flow_id,
                },
            )
        with pytest.raises(AccountFailure):
            worker.check(lease)
        with pytest.raises(AccountFailure):
            worker.claim(lease)


def test_final_witness_survives_revocation_restart_and_fresh_actor_flow(seeded_flow):
    engines, ids = seeded_flow
    with admission(seeded_flow) as worker:
        original = opened(seeded_flow, worker)
        lease = worker.redeem(
            issue(seeded_flow, "recover", reference(original)), "recover"
        )
        assert worker.claim(lease, "d" * 64) == "CLAIMED"
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                ),
                {"s": ids["session"]},
            )
        with pytest.raises(AccountFailure):
            worker.publish(lease, "COMPLETE")
    with admission(seeded_flow) as successor:
        other = successor.redeem(issue(seeded_flow, actor="owner"), "start")
        assert successor.claim(other) == "CLAIMED"
        successor.publish(other, "CREATED")
        final = successor.redeem(
            issue(seeded_flow, "recover", reference(other), actor="owner"), "recover"
        )
        assert successor.claim(final, "d" * 64) == "UNKNOWN_OUTCOME"
        successor.publish(final, "UNKNOWN_OUTCOME")
    with engines["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT outcome FROM wso_private.tvt_flow_intents WHERE flow_id=:f"
                ),
                {"f": original.flow_id},
            ).scalar_one()
            == "UNKNOWN_OUTCOME"
        )


def test_policy_empty_denies_and_four_table_acls_are_closed(seeded_flow):
    engines, _ = seeded_flow
    with engines["ADMIN"].connect() as db:
        for name in TABLES:
            row = db.execute(
                text(
                    "SELECT pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:n)"
                ),
                {"n": "wso_private." + name},
            ).one()
            assert tuple(row) == ("wso_account_owner", True, True)
            for role in (
                "wso_app",
                "wso_connection_worker",
                "wso_web_session",
                "wso_identity_bootstrap",
            ):
                assert not db.execute(
                    text(
                        "SELECT has_table_privilege(:r,:n,'SELECT,INSERT,UPDATE,DELETE')"
                    ),
                    {"r": role, "n": "wso_private." + name},
                ).scalar_one()
        functions = db.execute(
            text(
                "SELECT p.proname,pg_get_userbyid(p.proowner),p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.proname LIKE 'wso_tvt_flow_%' ORDER BY 1"
            )
        ).all()
        assert len(functions) == 8
        assert all(
            row[1] == "wso_account_owner"
            and row[2]
            and "search_path=pg_catalog" in row[3]
            for row in functions
        )
    for role in ("APP", "WORKER"):
        with engines[role].begin() as db, pytest.raises(DBAPIError):
            db.execute(text("SELECT * FROM wso_private.tvt_flows"))
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "DELETE FROM wso_private.tvt_flow_policies WHERE region='test' AND brand='brand'"
            )
        )
    with pytest.raises(AccountFailure):
        issue(seeded_flow)


def test_current_session_and_flow_expiry_cap_tickets_and_stale_generations(seeded_flow):
    engines, ids = seeded_flow
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE public.web_sessions SET expires_at=clock_timestamp()+interval '90 seconds' WHERE session_digest=:s"
            ),
            {"s": ids["session"]},
        )
    with admission(seeded_flow) as worker:
        lease = worker.redeem(issue(seeded_flow), "start")
        with engines["ADMIN"].connect() as db:
            bounded = db.execute(
                text(
                    "SELECT f.expires_at<=s.expires_at AND f.expires_at<=f.created_at+interval '300 seconds' AND t.expires_at<=f.expires_at AND t.expires_at<=clock_timestamp()+interval '30 seconds' FROM wso_private.tvt_flows f JOIN public.web_sessions s ON s.session_digest=f.session_digest JOIN wso_private.tvt_flow_tickets t ON t.flow_id=f.id WHERE f.id=:f"
                ),
                {"f": lease.flow_id},
            ).scalar_one()
            assert bounded is True
        assert worker.claim(lease) == "CLAIMED"
        assert worker.publish(lease, "CREATED").generation == 2
        with pytest.raises(AccountFailure):
            worker.claim(lease)
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_flows SET expires_at=clock_timestamp()-interval '1 second' WHERE id=:f"
                ),
                {"f": lease.flow_id},
            )
        with pytest.raises(AccountFailure):
            issue(seeded_flow, "image", reference(lease))
        state = worker.redeem(issue(seeded_flow, "state", reference(lease)), "state")
        assert worker.claim(state) == "CLAIMED"
        worker.publish(state, "EXPIRED")


def test_same_business_intent_races_only_one_durable_final_admission(seeded_flow):
    from concurrent.futures import ThreadPoolExecutor

    with admission(seeded_flow) as worker:
        first = opened(seeded_flow, worker)
        second = opened(seeded_flow, worker)
        leases = [
            worker.redeem(issue(seeded_flow, "recover", reference(item)), "recover")
            for item in (first, second)
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(lambda lease: worker.claim(lease, "e" * 64), leases)
            )
        assert sorted(outcomes) == ["CLAIMED", "UNKNOWN_OUTCOME"]
        for lease in leases:
            worker.publish(lease, "UNKNOWN_OUTCOME")
    with seeded_flow[0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_flow_intents WHERE digest=decode(:d,'hex')"
                ),
                {"d": "e" * 64},
            ).scalar_one()
            == 1
        )


def test_lost_registry_after_read_claim_has_explicit_durable_unknown(seeded_flow):
    with admission(seeded_flow) as worker:
        initial = opened(seeded_flow, worker)
        reading = worker.redeem(
            issue(seeded_flow, "image", reference(initial)), "image"
        )
        assert worker.claim(reading) == "CLAIMED"
    with admission(seeded_flow) as successor:
        state = successor.redeem(
            issue(seeded_flow, "state", reference(initial)), "state"
        )
        assert state.state == "UNKNOWN_OUTCOME"


@pytest.mark.parametrize("outcome", ["COMPLETE", "FAILED"])
def test_known_terminal_settlement_allows_new_intent_but_retains_consumed_witness(
    seeded_flow, outcome
):
    digest = uuid4().hex * 2
    with admission(seeded_flow) as worker:
        old = opened(seeded_flow, worker)
        first = worker.redeem(issue(seeded_flow, "recover", reference(old)), "recover")
        assert worker.claim(first, digest) == "CLAIMED"
        worker.publish(first, outcome)
        fresh = opened(seeded_flow, worker)
        second = worker.redeem(
            issue(seeded_flow, "recover", reference(fresh)), "recover"
        )
        assert worker.claim(second, digest) == "CLAIMED"
        with pytest.raises(AccountFailure):
            worker.claim(first, digest)
    with seeded_flow[0]["ADMIN"].connect() as db:
        assert db.execute(
            text("SELECT final_consumed,state FROM wso_private.tvt_flows WHERE id=:f"),
            {"f": old.flow_id},
        ).one() == (True, outcome)
        assert (
            db.execute(
                text(
                    "SELECT outcome FROM wso_private.tvt_flow_intents WHERE flow_id=:f"
                ),
                {"f": old.flow_id},
            ).scalar_one()
            == outcome
        )


def test_function_execute_acl_no_generic_credential_or_public_grants(seeded_flow):
    with seeded_flow[0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='wso_private'"
                )
            ).scalar_one()
            == "wso_migrator"
        )
        for role in (
            "wso_app",
            "wso_connection_worker",
            "wso_web_session",
            "wso_identity_bootstrap",
        ):
            assert (
                db.execute(
                    text("SELECT has_schema_privilege(:r,'wso_private','CREATE')"),
                    {"r": role},
                ).scalar_one()
                is False
            )
        functions = db.execute(
            text(
                "SELECT n.nspname,p.proname,p.oid::regprocedure::text,p.proacl FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.proname LIKE 'wso_tvt_flow_%'"
            )
        ).all()
        for schema, name, signature, _ in functions:
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid=to_regprocedure(:s) AND a.grantee=0"
                    ),
                    {"s": signature},
                ).scalar_one()
                == 0
            )
            for role in (
                "wso_app",
                "wso_connection_worker",
                "wso_web_session",
                "wso_identity_bootstrap",
            ):
                permitted = db.execute(
                    text("SELECT has_function_privilege(:r,:s,'EXECUTE')"),
                    {"r": role, "s": signature},
                ).scalar_one()
                assert permitted is (
                    schema == "public"
                    and (
                        (name == "wso_tvt_flow_issue" and role == "wso_app")
                        or (
                            name != "wso_tvt_flow_issue"
                            and role == "wso_connection_worker"
                        )
                    )
                )
        for table in ("public.web_sessions", "wso_private.tvt_user_consents"):
            for role in ("wso_app", "wso_connection_worker", "wso_web_session"):
                assert not db.execute(
                    text("SELECT has_table_privilege(:r,:t,'SELECT')"),
                    {"r": role, "t": table},
                ).scalar_one()
        assert (
            db.execute(
                text(
                    "SELECT rolcanlogin OR rolbypassrls OR rolsuper OR rolinherit FROM pg_roles WHERE rolname='wso_account_owner'"
                )
            ).scalar_one()
            is False
        )


def test_real_worker_admission_native_parser_and_durable_settlement(
    seeded_flow, monkeypatch
):
    from wso_contracts.tvt.account_flows import AccountRecoverySubmit

    from tests.tvt_parity.test_account_flow_service import build, ref, response

    with admission(seeded_flow) as authority:
        worker, _, requests = build(
            monkeypatch, [response({}, code=1001), response({})], admission=authority
        )
        views = []
        for expected in ("FAILED", "COMPLETE"):
            body = start_body()
            view = worker.start(
                issue(seeded_flow, body=body),
                body,
                deadline_ms=5000,
                correlation_id="actual-sql",
            )
            submit = ref(
                view,
                AccountRecoverySubmit,
                new_password="private-password",
                dynamic_code="123456",
            )
            result = worker.recover(
                issue(seeded_flow, "recover", submit),
                submit,
                deadline_ms=5000,
                correlation_id="actual-sql",
            )
            assert result.state == expected and result.request_id == "actual-sql"
            views.append(view.flow_id)
        assert len(requests) == 2
        assert all(request.path == "/user/info/password/reset" for request in requests)
    with seeded_flow[0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_flow_intents WHERE flow_id=ANY(:ids)"
                ),
                {"ids": views},
            ).scalar_one()
            == 2
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_flow_intents WHERE flow_id=ANY(:ids) AND outcome='UNKNOWN_OUTCOME'"
                ),
                {"ids": views},
            ).scalar_one()
            == 0
        )


def test_real_worker_revocation_inside_admitted_exchange_cannot_publish(
    seeded_flow, monkeypatch
):
    from wso_contracts.tvt.account_flows import AccountRecoverySubmit

    from tests.tvt_parity.test_account_flow_service import build, ref, response

    engines, ids = seeded_flow

    def revoke(_):
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                ),
                {"s": ids["session"]},
            )
        return response({})

    with admission(seeded_flow) as authority:
        worker, _, requests = build(monkeypatch, [revoke], admission=authority)
        body = start_body()
        view = worker.start(
            issue(seeded_flow, body=body),
            body,
            deadline_ms=5000,
            correlation_id="revoked-sql",
        )
        submit = ref(
            view,
            AccountRecoverySubmit,
            new_password="private-password",
            dynamic_code="123456",
        )
        with pytest.raises(AccountFailure):
            worker.recover(
                issue(seeded_flow, "recover", submit),
                submit,
                deadline_ms=5000,
                correlation_id="revoked-sql",
            )
        assert len(requests) == 1 and not worker._registry
    with engines["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT outcome FROM wso_private.tvt_flow_intents WHERE flow_id=:f"
                ),
                {"f": view.flow_id},
            ).scalar_one()
            == "UNKNOWN_OUTCOME"
        )


def test_shutdown_after_real_final_claim_preserves_unknown_and_blocks_fresh_flow(
    seeded_flow, monkeypatch
):
    import threading

    from wso_contracts.tvt.account_flows import AccountRecoverySubmit

    from tests.tvt_parity.test_account_flow_service import build, ref, response

    entered, release = threading.Event(), threading.Event()

    def pending(_):
        entered.set()
        assert release.wait(2)
        return response({})

    with admission(seeded_flow) as authority:
        worker, _, requests = build(monkeypatch, [pending], admission=authority)
        body = start_body()
        view = worker.start(
            issue(seeded_flow, body=body),
            body,
            deadline_ms=5000,
            correlation_id="shutdown-sql",
        )
        original = worker._registry[view.flow_id].flow.close

        def closing():
            original()
            release.set()

        monkeypatch.setattr(worker._registry[view.flow_id].flow, "close", closing)
        submit = ref(
            view, AccountRecoverySubmit, new_password="password", dynamic_code="123456"
        )
        ticket = issue(seeded_flow, "recover", submit)
        failures = []

        def perform():
            try:
                worker.recover(
                    ticket, submit, deadline_ms=5000, correlation_id="shutdown-sql"
                )
            except AccountFailure as error:
                failures.append(error.code)

        thread = threading.Thread(target=perform)
        thread.start()
        assert entered.wait(2)
        try:
            worker.close(deadline_ms=1000)
        finally:
            release.set()
            thread.join(2)
        assert failures == ["ACCOUNT_CANCELLED"] and len(requests) == 1
        assert not worker._registry and not worker._binding_key
        successor, _, no_requests = build(monkeypatch, admission=authority)
        fresh = successor.start(
            issue(seeded_flow, body=body),
            body,
            deadline_ms=5000,
            correlation_id="shutdown-sql",
        )
        retry = ref(
            fresh, AccountRecoverySubmit, new_password="other", dynamic_code="654321"
        )
        result = successor.recover(
            issue(seeded_flow, "recover", retry),
            retry,
            deadline_ms=5000,
            correlation_id="shutdown-sql",
        )
        assert result.state == "UNKNOWN_OUTCOME" and not no_requests
        successor.close(deadline_ms=1000)
    with seeded_flow[0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT outcome FROM wso_private.tvt_flow_intents WHERE flow_id=:f"
                ),
                {"f": view.flow_id},
            ).scalar_one()
            == "UNKNOWN_OUTCOME"
        )


@pytest.mark.parametrize("operation", ["claim", "publish"])
@pytest.mark.parametrize("crosses_expiry", [True, False], ids=["expired", "valid"])
def test_ticket_expiry_after_flow_lock_is_rechecked_before_mutation(
    seeded_flow, operation, crosses_expiry
):
    """A capability may expire during a successful lock wait, before the budget."""
    import threading
    import time

    from wso_core.tvt.token_vault import token_budget

    engines, _ = seeded_flow
    observation = {"operation": operation, "crosses_expiry": crosses_expiry}
    with admission(seeded_flow) as worker:
        initial = opened(seeded_flow, worker)
        lease = worker.redeem(
            issue(seeded_flow, "recover", reference(initial)), "recover"
        )
        intent = uuid4().hex * 2
        if operation == "publish":
            assert worker.claim(lease, intent) == "CLAIMED"
        outcome = {}
        with engines["ADMIN"].connect() as locking:
            transaction = locking.begin()
            locker_pid = locking.execute(text("SELECT pg_backend_pid()")).scalar_one()
            locking.execute(
                text("SELECT id FROM wso_private.tvt_flows WHERE id=:f FOR UPDATE"),
                {"f": initial.flow_id},
            )
            with engines["ADMIN"].begin() as db:
                db.execute(
                    text(
                        "UPDATE wso_private.tvt_flow_tickets SET expires_at=clock_timestamp()+(:ms * interval '1 millisecond') WHERE flow_id=:f AND operation='recover'"
                    ),
                    {"f": initial.flow_id, "ms": 1200 if crosses_expiry else 2000},
                )
            operation_end = time.monotonic() + 3

            def perform():
                try:
                    with token_budget(
                        lambda: int((operation_end - time.monotonic()) * 1000)
                    ):
                        result = (
                            worker.claim(lease, intent)
                            if operation == "claim"
                            else worker.publish(lease, "COMPLETE")
                        )
                    outcome["result"] = result if operation == "claim" else result.state
                except AccountFailure as error:
                    outcome["result"] = error.code
                except BaseException as error:  # noqa: BLE001 -- capture only helper-thread error type
                    outcome["unexpected_error_type"] = type(error).__name__
                finally:
                    outcome["operation_budget_remaining_ms"] = int(
                        (operation_end - time.monotonic()) * 1000
                    )

            thread = threading.Thread(target=perform)
            thread.start()
            try:
                with (
                    engines["ADMIN"]
                    .connect()
                    .execution_options(isolation_level="AUTOCOMMIT") as monitor
                ):
                    limit = time.monotonic() + 2
                    while time.monotonic() < limit:
                        blocked = monitor.execute(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity a WHERE a.datname=current_database() AND a.usename='wso_connection_worker' AND a.state='active' AND :pid=ANY(pg_blocking_pids(a.pid)))"
                            ),
                            {"pid": locker_pid},
                        ).scalar_one()
                        if blocked:
                            break
                        time.sleep(0.005)
                    assert blocked is True, (
                        "must observe the actual worker waiting on the held flow row"
                    )
                    expiry = text(
                        "SELECT clock_timestamp()>=expires_at FROM wso_private.tvt_flow_tickets WHERE flow_id=:f AND operation='recover'"
                    )
                    assert (
                        monitor.execute(expiry, {"f": initial.flow_id}).scalar_one()
                        is False
                    )
                    observation["blocked_while_ticket_valid"] = True
                    if crosses_expiry:
                        while time.monotonic() < limit:
                            if monitor.execute(
                                expiry, {"f": initial.flow_id}
                            ).scalar_one():
                                break
                            time.sleep(0.005)
                    expired = monitor.execute(
                        expiry, {"f": initial.flow_id}
                    ).scalar_one()
                    assert expired is crosses_expiry
                    observation["expired_at_lock_release"] = expired
                transaction.commit()
            finally:
                if transaction.is_active:
                    transaction.rollback()
                thread.join(4)
            assert not thread.is_alive()
        with engines["ADMIN"].connect() as db:
            state = dict(
                db.execute(
                    text(
                        "SELECT f.state,f.generation,f.final_consumed,f.busy_digest IS NOT NULL AS busy,t.used,(SELECT count(*) FROM wso_private.tvt_flow_intents i WHERE i.flow_id=f.id) AS witnesses,(SELECT i.outcome FROM wso_private.tvt_flow_intents i WHERE i.flow_id=f.id) AS outcome FROM wso_private.tvt_flows f JOIN wso_private.tvt_flow_tickets t ON t.flow_id=f.id AND t.operation='recover' WHERE f.id=:f"
                    ),
                    {"f": initial.flow_id},
                )
                .mappings()
                .one()
            )
        observation.update(outcome)
        observation["durable_after"] = state
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (
            EVIDENCE
            / f"expiry-lock-{operation}-{crosses_expiry}-{engines['ADMIN'].url.database}.json"
        ).write_text(json.dumps(observation, indent=2), encoding="utf-8")
        assert outcome["operation_budget_remaining_ms"] > 0
        assert "unexpected_error_type" not in outcome
        if crosses_expiry:
            assert outcome["result"] == "ACCOUNT_DENIED"
            assert state["generation"] == lease.generation
            if operation == "claim":
                assert state == {
                    "state": "CREATED",
                    "generation": lease.generation,
                    "final_consumed": False,
                    "busy": False,
                    "used": False,
                    "witnesses": 0,
                    "outcome": None,
                }
            else:
                assert state == {
                    "state": "UNKNOWN_OUTCOME",
                    "generation": lease.generation,
                    "final_consumed": True,
                    "busy": True,
                    "used": True,
                    "witnesses": 1,
                    "outcome": "UNKNOWN_OUTCOME",
                }
        else:
            assert outcome["result"] == (
                "CLAIMED" if operation == "claim" else "COMPLETE"
            )
            assert state["final_consumed"] is True and state["used"] is True
            assert state["witnesses"] == 1
            assert state["generation"] == lease.generation + (operation == "publish")
            assert state["outcome"] == (
                "UNKNOWN_OUTCOME" if operation == "claim" else "COMPLETE"
            )


def test_sql_lock_wait_is_bounded_by_original_operation_budget(seeded_flow):
    import time

    from wso_core.tvt.token_vault import token_budget

    with admission(seeded_flow) as worker:
        initial = opened(seeded_flow, worker)
        lease = worker.redeem(
            issue(seeded_flow, "recover", reference(initial)), "recover"
        )
        with seeded_flow[0]["ADMIN"].begin() as locking:
            locking.execute(
                text("SELECT id FROM wso_private.tvt_flows WHERE id=:f FOR UPDATE"),
                {"f": initial.flow_id},
            )
            started = time.monotonic()
            with (
                token_budget(lambda: int((started + 0.15 - time.monotonic()) * 1000)),
                pytest.raises(AccountFailure) as error,
            ):
                worker.claim(lease, uuid4().hex * 2)
            assert time.monotonic() - started < 2
            assert error.value.__context__ is None
    with seeded_flow[0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_flow_intents WHERE flow_id=:f"
                ),
                {"f": initial.flow_id},
            ).scalar_one()
            == 0
        )
