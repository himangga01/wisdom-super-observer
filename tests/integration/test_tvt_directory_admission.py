"""W07 guarded PostgreSQL authority acceptance, never live TVT execution."""

import hashlib
import importlib.util
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from wso_core.tvt.account_projection import AccountFailure

from tests.integration.test_tvt_account_flow_admission import (
    flow_source_expectations as directory_source_expectations,
)
from tests.integration.test_tvt_account_flow_admission import (
    flow_source_snapshot as directory_source_snapshot,
)
from tests.integration.test_tvt_domain_scope import seed_foundation
from tests.integration.test_tvt_sessions import foundation_contents, function_owners

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT
    / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W07-protected-directory-service-evidence"
)
TABLES = ("tvt_directory_tickets",)


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


def test_directory_revision_has_a_separate_protected_authority_boundary():
    path = ROOT / "infra/migrations/versions/0011_tvt_directory_read_tickets.py"
    assert path.exists(), (
        "A separate protected directory admission revision is required"
    )
    spec = importlib.util.spec_from_file_location("flow_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0010_tvt_account_flows"


def directory_parent_sha256():
    activation = os.environ.get("WSO_TEST_W07_DIRECTORY_ACCEPTANCE")
    if activation is None:
        pytest.skip(
            "requires reviewed parent and explicit owned W07 database activation"
        )
    assert activation == "1"
    expected = os.environ.get("WSO_TEST_W07_PARENT_SHA256")
    assert (
        expected == "a8c39baf215e3b8fea4b92e5df96c21bf1701b9edbb7d61f62e27860af2e5958"
    )
    assert (
        hashlib.sha256(
            (ROOT / "infra/migrations/versions/0010_tvt_account_flows.py").read_bytes()
        ).hexdigest()
        == expected
    )
    return expected


@pytest.fixture(scope="module")
def directory_database():
    expected = directory_parent_sha256()
    source_name = directory_source_expectations()[0]
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
    before_source = directory_source_snapshot(source)
    control = create_engine(
        urls["ADMIN"].set(database="postgres"), isolation_level="AUTOCOMMIT", **options
    )
    name, marker = "w07_directory_" + uuid4().hex, "owned-w07-directory-" + uuid4().hex
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
            assert re.fullmatch(r"w07_directory_[0-9a-f]{32}", name)
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
        for engine in engines.values():

            @event.listens_for(engine, "handle_error")
            def diagnostic(context):
                error = context.original_exception
                code = getattr(error, "sqlstate", None)
                if code in {"42702", "42703", "42601", "42501"}:
                    EVIDENCE.mkdir(parents=True, exist_ok=True)
                    with (EVIDENCE / "sql-diagnostic.txt").open(
                        "a", encoding="utf-8"
                    ) as out:
                        out.write(
                            str(code)
                            + ": "
                            + str(
                                getattr(
                                    getattr(error, "diag", None), "message_primary", ""
                                )
                            )
                            + "\n"
                        )

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
                        ROOT / "infra/migrations/versions/0010_tvt_account_flows.py"
                    ).read_bytes()
                ).hexdigest()
                == expected
            )
            getattr(command, direction)(config, revision)

        migrate("upgrade", "0010_tvt_account_flows")
        seed_foundation(engines["ADMIN"])
        with engines["ADMIN"].connect() as db:
            rows, owners = foundation_contents(db), function_owners(db)
            before_authority = authority_definitions(db)
        migrate("upgrade", "0011_tvt_directory_read_tickets")
        migrate("downgrade", "0010_tvt_account_flows")
        with engines["ADMIN"].connect() as db:
            assert foundation_contents(db) == rows and function_owners(db) == owners
            assert authority_definitions(db) == before_authority
        migrate("upgrade", "0011_tvt_directory_read_tickets")
        with engines["ADMIN"].connect() as db:
            assert foundation_contents(db, rows) == rows
            after_tables = foundation_contents(db)
            assert set(after_tables) - set(rows) == {
                ("wso_private", "tvt_directory_tickets")
            }
            assert set(rows) - set(after_tables) == set()
            receipt["owned_parent_table_count_including_alembic"] = len(rows) + 1
            receipt["owned_directory_table_count_including_alembic"] = (
                len(after_tables) + 1
            )
        receipt["roundtrip_preserved_parent_rows_owners"] = True
        receipt["roundtrip_preserved_parent_function_bodies_acls_policies"] = True
        yield engines
    finally:
        for engine in engines.values():
            engine.dispose()
        after_source = directory_source_snapshot(source)
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
def seeded_directory(directory_database):
    from tests.integration.test_tvt_sessions import publish

    engines = directory_database
    ids = seed_foundation(engines["ADMIN"])
    ids["session"] = uuid4().hex * 2
    ids["identity"] = publish((engines, ids))
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_flow_policies(region,brand,profile_id,consent_version,key_commitment,enabled) VALUES('test','SuperLivePlus','profile','v1',decode(:k,'hex'),true) ON CONFLICT(region,brand) DO UPDATE SET enabled=true,revision=1,consent_version='v1'"
            ),
            {"k": "0" * 64},
        )
        db.execute(
            text(
                "INSERT INTO public.web_sessions(session_digest,csrf_digest,exchange_digest,issuer,subject,user_id,expires_at) VALUES(:s,:c,:e,'https://w02.test',:sub,:u,clock_timestamp()+interval '1 hour')"
            ),
            {
                "s": ids["session"],
                "c": uuid4().hex * 2,
                "e": uuid4().hex * 2,
                "sub": str(ids["staff"]),
                "u": ids["staff"],
            },
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_user_consents(tenant_id,user_id,profile_id,version,status) VALUES(:t,:u,'profile','v1','accepted')"
            ),
            {"t": ids["tenant"], "u": ids["staff"]},
        )
    yield engines, ids
    with engines["ADMIN"].begin() as db:
        db.execute(
            text("DELETE FROM wso_private.tvt_directory_tickets WHERE tenant_id=:t"),
            {"t": ids["tenant"]},
        )


def body_for(fixture, **changes):
    from wso_contracts.tvt.directory import DeviceListRequest

    return DeviceListRequest(
        **(
            {
                "identity_id": fixture[1]["identity"],
                "region": "test",
                "brand": "SuperLivePlus",
            }
            | changes
        )
    )


def directory_issue(fixture, body=None, session=None, actor="staff"):
    from wso_core.tvt.directory_admission import DirectoryTicketIssuer

    from tests.integration.test_tvt_sessions import actor_db

    with actor_db(fixture, actor) as db:
        return DirectoryTicketIssuer(db, lambda: 10000).issue(
            session or fixture[1]["session"], "device_list", body or body_for(fixture)
        )


@contextmanager
def directory_worker(fixture, version="v1"):
    from wso_core.tvt.directory_admission import DirectoryAdmission, DirectoryPolicy

    from tests.integration.test_tvt_sessions import TestKey

    try:
        worker = DirectoryAdmission(
            fixture[0]["WORKER"].url.render_as_string(hide_password=False),
            (DirectoryPolicy("test", "SuperLivePlus", "profile", version),),
            TestKey(),
        )
    except TypeError:
        pytest.fail("bounded directory admission must own the snapshot cipher")
    try:
        yield worker
    finally:
        worker.close()


def test_actual_sql_one_use_exact_body_and_vault_snapshot(seeded_directory):
    from tests.integration.test_tvt_sessions import vault_for

    f = seeded_directory
    body = body_for(f)
    ticket = directory_issue(f, body)
    with directory_worker(f) as worker, vault_for(f) as vault:
        with pytest.raises(AccountFailure):
            worker.redeem(
                ticket, "device_list", body.model_copy(update={"page_size": 1})
            )
        lease = worker.redeem(ticket, "device_list", body)
        with pytest.raises(AccountFailure):
            worker.redeem(ticket, "device_list", body)
        account = worker.claim(lease)
        with pytest.raises(AccountFailure):
            worker.claim(lease)
        assert worker.snapshot(lease).value == "synthetic-user-token"
        assert vault.use(account, lambda secret: secret == b"synthetic-user-token")
        worker.check(lease)
        worker.publish(lease)
        with pytest.raises(AccountFailure):
            worker.publish(lease)
        worker.dispose(lease)
        with pytest.raises(AccountFailure):
            vault.use(account, lambda _: pytest.fail("disposed bytes"))


@pytest.mark.parametrize(
    "change", ["session", "foreign_session", "identity", "region", "brand", "owner"]
)
def test_actual_issuer_denies_forged_or_foreign_selection(seeded_directory, change):
    f = seeded_directory
    args = {}
    if change in {"session", "foreign_session"}:
        args["session"] = uuid4().hex * 2
    elif change == "owner":
        args["actor"] = "owner"
    else:
        args["body"] = body_for(
            f,
            **{
                change if change != "identity" else "identity_id": uuid4()
                if change == "identity"
                else "foreign"
            },
        )
    with pytest.raises(AccountFailure):
        directory_issue(f, **args)


CHANGES = {
    "session_revoke": "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s",
    "session_expiry": "UPDATE public.web_sessions SET created_at=clock_timestamp()-interval '1 hour',expires_at=clock_timestamp()-interval '1 second' WHERE session_digest=:s",
    "membership": "UPDATE public.memberships SET role='MANAGER' WHERE tenant_id=:t AND user_id=:u",
    "consent": "UPDATE wso_private.tvt_user_consents SET status='declined',decided_at=clock_timestamp() WHERE tenant_id=:t AND user_id=:u",
    "consent_time": "UPDATE wso_private.tvt_user_consents SET decided_at=clock_timestamp()+interval '1 second' WHERE tenant_id=:t AND user_id=:u",
    "policy": "UPDATE wso_private.tvt_flow_policies SET revision=revision+1 WHERE region='test' AND brand='SuperLivePlus'",
    "generation": "UPDATE wso_private.tvt_account_tokens SET generation=generation+1 WHERE identity_id=:i AND kind='USER'",
    "renewal": "UPDATE wso_private.tvt_account_tokens SET renewal_state='INFLIGHT' WHERE identity_id=:i AND kind='USER'",
    "sequence": "UPDATE wso_private.tvt_account_tokens SET renewal_sequence=renewal_sequence+1 WHERE identity_id=:i AND kind='USER'",
    "managed_owner": "UPDATE wso_private.tvt_account_sessions SET actor_id=:owner WHERE identity_id=:i",
    "closed": "UPDATE wso_private.tvt_account_sessions SET state='CLOSED' WHERE identity_id=:i",
    "grant": "UPDATE wso_private.tvt_identity_grants SET expires_at=clock_timestamp()-interval '1 second' WHERE identity_id=:i",
    "ticket_expiry": "UPDATE wso_private.tvt_directory_tickets SET expires_at=clock_timestamp()-interval '1 second' WHERE identity_id=:i",
}


@pytest.mark.parametrize("stage", ["redeem", "claim", "publish"])
@pytest.mark.parametrize("change", list(CHANGES))
def test_actual_current_authority_changes_deny_at_each_boundary(
    seeded_directory, stage, change
):
    f = seeded_directory
    ticket = directory_issue(f)
    with directory_worker(f) as worker:
        lease = None
        if stage != "redeem":
            lease = worker.redeem(ticket, "device_list", body_for(f))
        if stage == "publish":
            worker.claim(lease)
        with f[0]["ADMIN"].begin() as db:
            db.execute(
                text(CHANGES[change]),
                {
                    "s": f[1]["session"],
                    "t": f[1]["tenant"],
                    "u": f[1]["staff"],
                    "i": f[1]["identity"],
                    "owner": f[1]["owner"],
                },
            )
        with pytest.raises(AccountFailure):
            if stage == "redeem":
                worker.redeem(ticket, "device_list", body_for(f))
            elif stage == "claim":
                worker.claim(lease)
            else:
                worker.publish(lease)
        if lease is not None:
            worker.dispose(lease)


@pytest.mark.parametrize(
    "role",
    ["APP", "IDENTITY", "SESSION", "WORKER", "DISPATCH", "JOB", "ASSET_MAINTENANCE"],
)
def test_actual_runtime_roles_cannot_read_private_directory_or_secret_tables(
    seeded_directory, role
):
    for table in (
        "wso_private.tvt_directory_tickets",
        "wso_private.tvt_account_tokens",
        "wso_private.connection_secrets",
    ):
        with seeded_directory[0][role].begin() as db, pytest.raises(DBAPIError):
            db.execute(text("SELECT * FROM " + table))


def test_actual_forged_gucs_no_tenant_context_and_standalone_profile_ticket_deny(
    seeded_directory,
):
    from wso_contracts.tvt.directory import canonical_request

    from tests.integration.test_tvt_sessions import issue

    f = seeded_directory
    with f[0]["APP"].begin() as db:
        db.execute(
            text(
                "SELECT set_config('app.tenant_id',:t,true),set_config('app.user_id',:u,true),set_config('app.role','OWNER',true)"
            ),
            {"t": str(f[1]["tenant"]), "u": str(f[1]["staff"])},
        )
        assert (
            db.execute(
                text(
                    "SELECT public.wso_tvt_directory_issue(:s,'device_list',CAST(:q AS jsonb))"
                ),
                {
                    "s": f[1]["session"],
                    "q": canonical_request("device_list", body_for(f)),
                },
            ).scalar_one()
            is None
        )
    profile = issue(f, "profile", f[1]["identity"], 1)
    with directory_worker(f) as worker, pytest.raises(AccountFailure):
        worker.redeem(profile, "device_list", body_for(f))


def test_actual_wrong_worker_profile_denied_without_decryption(seeded_directory):
    ticket = directory_issue(seeded_directory)
    with (
        directory_worker(seeded_directory, "v2") as worker,
        pytest.raises(AccountFailure),
    ):
        worker.redeem(ticket, "device_list", body_for(seeded_directory))


@pytest.mark.parametrize("kind", ["P2P", "DEVICE"])
def test_actual_nonuser_kind_never_admits_directory(seeded_directory, kind):
    f = seeded_directory
    with f[0]["ADMIN"].begin() as db:
        db.execute(
            text(
                "DELETE FROM wso_private.tvt_account_tokens WHERE identity_id=:i AND kind='P2P'"
            ),
            {"i": f[1]["identity"]},
        )
        db.execute(
            text(
                "UPDATE wso_private.tvt_account_tokens SET kind=:k WHERE identity_id=:i AND kind='USER'"
            ),
            {"i": f[1]["identity"], "k": kind},
        )
    with pytest.raises(AccountFailure):
        directory_issue(f)


def test_actual_actor_with_account_grant_cannot_use_other_actors_managed_session(
    seeded_directory,
):
    f = seeded_directory
    owner_session = uuid4().hex * 2
    with f[0]["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_identity_grants(id,tenant_id,identity_id,actor_id,action,revision,expires_at) VALUES(:g,:t,:i,:u,'account.read',1,clock_timestamp()+interval '5 minutes')"
            ),
            {
                "g": uuid4(),
                "t": f[1]["tenant"],
                "i": f[1]["identity"],
                "u": f[1]["owner"],
            },
        )
        db.execute(
            text(
                "INSERT INTO public.web_sessions(session_digest,csrf_digest,exchange_digest,issuer,subject,user_id,expires_at) VALUES(:s,:c,:e,'https://w02.test',:sub,:u,clock_timestamp()+interval '1 hour')"
            ),
            {
                "s": owner_session,
                "c": uuid4().hex * 2,
                "e": uuid4().hex * 2,
                "sub": str(f[1]["owner"]),
                "u": f[1]["owner"],
            },
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_user_consents(tenant_id,user_id,profile_id,version,status) VALUES(:t,:u,'profile','v1','accepted')"
            ),
            {"t": f[1]["tenant"], "u": f[1]["owner"]},
        )
    with pytest.raises(AccountFailure):
        directory_issue(f, session=owner_session, actor="owner")


@pytest.mark.parametrize(
    "change",
    [
        {"method": "logout"},
        {"origin": "https://foreign.invalid"},
        {"token": "synthetic-private"},
        {"page_num": True},
        {"page_size": 1001},
    ],
)
def test_actual_sql_query_schema_cannot_be_bypassed_by_direct_function(
    seeded_directory, change
):
    from tests.integration.test_tvt_sessions import actor_db

    f = seeded_directory
    body = body_for(f).model_dump(mode="json") | change
    with actor_db(f) as db:
        assert (
            db.execute(
                text(
                    "SELECT public.wso_tvt_directory_issue(:s,'device_list',CAST(:q AS jsonb))"
                ),
                {"s": f[1]["session"], "q": json.dumps(body)},
            ).scalar_one()
            is None
        )


def test_actual_actor_capacity_and_expired_delegates_are_bounded(seeded_directory):
    f = seeded_directory
    for _ in range(4):
        directory_issue(f)
    with pytest.raises(AccountFailure):
        directory_issue(f)
    with f[0]["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.tvt_directory_tickets SET expires_at=clock_timestamp()-interval '1 second' WHERE tenant_id=:t"
            ),
            {"t": f[1]["tenant"]},
        )
    directory_issue(f)
    with f[0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_directory_tickets WHERE tenant_id=:t"
                ),
                {"t": f[1]["tenant"]},
            ).scalar_one()
            == 1
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_account_tickets WHERE tenant_id=:t AND purpose='profile'"
                ),
                {"t": f[1]["tenant"]},
            ).scalar_one()
            == 1
        )


def test_actual_function_acl_and_forced_rls_are_narrow(seeded_directory):
    with seeded_directory[0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='wso_private.tvt_directory_tickets'::regclass"
            )
        ).one() == ("wso_account_owner", True, True)
        for role in (
            "wso_app",
            "wso_identity_bootstrap",
            "wso_web_session",
            "wso_connection_worker",
            "wso_dispatcher",
            "wso_job_worker",
            "wso_asset_maintenance",
        ):
            rows = db.execute(
                text(
                    "SELECT p.proname,has_function_privilege(:r,p.oid,'EXECUTE') FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.proname LIKE 'wso_tvt_directory_%'"
                ),
                {"r": role},
            ).all()
            allowed = {name for name, yes in rows if yes}
            if role == "wso_app":
                assert allowed == {"wso_tvt_directory_issue"}
            elif role == "wso_connection_worker":
                assert allowed == {
                    "wso_tvt_directory_redeem",
                    "wso_tvt_directory_context",
                    "wso_tvt_directory_claim",
                    "wso_tvt_directory_publish",
                    "wso_tvt_directory_dispose",
                    "wso_tvt_directory_secret",
                }
            else:
                assert allowed == set()


@pytest.mark.parametrize(
    "name,extra,payload",
    [
        ("DeviceListRequest", {}, {"total": "0", "records": []}),
        (
            "ChannelListRequest",
            {"sn_list": ["SN"]},
            [{"sn": "SN", "chls": [{"chlIndex": 7}]}],
        ),
        (
            "DeviceDetailRequest",
            {"sn": "SN", "return_chl": True},
            {"devInfo": {"sn": "SN"}},
        ),
        (
            "ChannelDetailRequest",
            {"sn": "SN", "chl_index": 7},
            {"sn": "SN", "chlIndex": 7},
        ),
        ("SentSharesRequest", {"resource_types": []}, {"total": 0, "records": []}),
        (
            "ReceivedSharesRequest",
            {"resource_types": [99]},
            {"total": 0, "records": []},
        ),
    ],
)
@pytest.mark.parametrize("revoke", [False, True])
def test_actual_worker_sql_and_vault_transactions_end_before_controlled_https_boundary(
    seeded_directory, monkeypatch, name, extra, payload, revoke
):
    import wso_contracts.tvt.directory as contracts
    import wso_core.tvt.account_client as account
    from wso_api.tvt.device_service import DirectoryWorkerExecutor
    from wso_api.tvt.session_service import AccountEndpoint
    from wso_core.tvt.account_protocol import parse_response
    from wso_core.tvt.directory_admission import DirectoryTicketIssuer

    from tests.integration.test_tvt_sessions import actor_db

    f = seeded_directory
    body = getattr(contracts, name)(
        identity_id=f[1]["identity"], region="test", brand="SuperLivePlus", **extra
    )
    with actor_db(f) as db:
        ticket = DirectoryTicketIssuer(db, lambda: 10000).issue(
            f[1]["session"], body.method, body
        )
    requests = []

    class Boundary:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, request):
            with f[0]["ADMIN"].begin() as db:
                assert (
                    db.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND usename='wso_connection_worker' AND state LIKE 'idle in transaction%'"
                        )
                    ).scalar_one()
                    == 0
                )
                if revoke:
                    db.execute(
                        text(
                            "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                        ),
                        {"s": f[1]["session"]},
                    )
            requests.append(request.path)
            return parse_response(
                200, json.dumps({"basic": {"msgcode": 200}, "data": payload}).encode()
            )

        def close(self):
            pass

    monkeypatch.setattr(account, "ProcessAccountTransport", Boundary)
    with directory_worker(f) as admission:
        worker = DirectoryWorkerExecutor(
            admission,
            (
                AccountEndpoint(
                    "test",
                    "SuperLivePlus",
                    "https://directory.example.invalid",
                    "en",
                    "US",
                    "1",
                ),
            ),
        )
        try:
            if revoke:
                with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
                    worker.execute(
                        body.method,
                        ticket,
                        body,
                        deadline_ms=10000,
                        correlation_id="sql-worker",
                    )
            else:
                view = worker.execute(
                    body.method,
                    ticket,
                    body,
                    deadline_ms=10000,
                    correlation_id="sql-worker",
                )
                assert (
                    view.method == body.method
                    and view.identity_id == f[1]["identity"]
                    and view.complete is None
                )
        finally:
            worker.close()
    assert len(requests) == 1
    with f[0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_directory_tickets WHERE tenant_id=:t"
                ),
                {"t": f[1]["tenant"]},
            ).scalar_one()
            == 0
        )


def test_actual_current_tenant_context_and_fixed_method_are_independent_authority(
    seeded_directory,
):
    from wso_contracts.tvt.directory import SentSharesRequest
    from wso_core.tvt.directory_admission import DirectoryTicketIssuer

    from tests.integration.test_tvt_sessions import actor_db

    f = seeded_directory
    with actor_db(f, tenant="other_tenant") as db, pytest.raises(AccountFailure):
        DirectoryTicketIssuer(db, lambda: 10000).issue(
            f[1]["session"], "device_list", body_for(f)
        )
    ticket = directory_issue(f)
    other = SentSharesRequest(
        identity_id=f[1]["identity"], region="test", brand="SuperLivePlus"
    )
    with directory_worker(f) as worker, pytest.raises(AccountFailure):
        worker.redeem(ticket, "sent_shares", other)


@pytest.mark.parametrize(
    "change", ["session_revoke", "consent", "generation", "renewal", "membership"]
)
def test_actual_bounded_snapshot_rechecks_current_authority_before_decrypt(
    seeded_directory, change
):
    f = seeded_directory

    class KeyProbe:
        calls = 0

        def encryption_key(self):
            self.calls += 1
            return bytes(range(32))

    with directory_worker(f) as worker:
        lease = worker.redeem(directory_issue(f), "device_list", body_for(f))
        worker.claim(lease)
        probe = KeyProbe()
        worker._cipher._provider = probe
        with f[0]["ADMIN"].begin() as db:
            db.execute(
                text(CHANGES[change]),
                {
                    "s": f[1]["session"],
                    "t": f[1]["tenant"],
                    "u": f[1]["staff"],
                    "i": f[1]["identity"],
                    "owner": f[1]["owner"],
                },
            )
        with pytest.raises(AccountFailure):
            worker.snapshot(lease)
        assert probe.calls == 0
        worker.dispose(lease)


@pytest.mark.parametrize("expired_after", ["secret", "publish"])
def test_actual_late_sql_return_never_dispatches_or_publishes_to_caller(
    seeded_directory, monkeypatch, expired_after
):
    import wso_core.tvt.account_client as account
    from wso_api.tvt.device_service import DirectoryWorkerExecutor
    from wso_api.tvt.session_service import AccountEndpoint
    from wso_core.tvt.account_protocol import parse_response
    from wso_core.tvt.token_vault import token_budget

    f = seeded_directory
    expired = False
    requests = []

    class Boundary:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, request):
            requests.append(request.path)
            return parse_response(
                200, b'{"basic":{"msgcode":200},"data":{"total":"0","records":[]}}'
            )

        def close(self):
            pass

    monkeypatch.setattr(account, "ProcessAccountTransport", Boundary)
    with directory_worker(f) as admission:
        assert admission._engine.pool.__class__.__name__ == "NullPool"

        class Probe:
            calls = 0

            def encryption_key(self):
                self.calls += 1
                return bytes(range(32))

        probe = Probe()
        admission._cipher._provider = probe

        @event.listens_for(admission._engine, "after_cursor_execute")
        def late_return(conn, cursor, statement, parameters, context, executemany):
            nonlocal expired
            if "public.wso_tvt_directory_" + expired_after + "(" in statement:
                expired = True

        ticket = directory_issue(f)
        worker = DirectoryWorkerExecutor(
            admission,
            (
                AccountEndpoint(
                    "test",
                    "SuperLivePlus",
                    "https://directory.example.invalid",
                    "en",
                    "US",
                    "1",
                ),
            ),
        )
        with (
            token_budget(lambda: 0 if expired else 10000),
            pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"),
        ):
            worker.execute(
                "device_list",
                ticket,
                body_for(f),
                deadline_ms=10000,
                correlation_id="late-sql",
            )
        assert expired and len(requests) == (0 if expired_after == "secret" else 1)
        assert probe.calls == (0 if expired_after == "secret" else 1)
        with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
            worker.close(deadline_ms=20)


def test_actual_snapshot_commit_return_rechecks_original_deadline(seeded_directory):
    from wso_core.tvt.token_vault import token_budget

    f = seeded_directory
    expired = False
    with directory_worker(f) as admission:
        lease = admission.redeem(directory_issue(f), "device_list", body_for(f))
        admission.claim(lease)

        @event.listens_for(admission._engine, "commit")
        def expire_at_commit(conn):
            nonlocal expired
            expired = True

        with (
            token_budget(lambda: 0 if expired else 10000),
            pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"),
        ):
            admission.snapshot(lease)
        assert expired


@pytest.mark.parametrize("change", ["session_revoke", "consent"])
@pytest.mark.parametrize("stage", ["check", "publish"])
def test_actual_session_revocation_during_credential_lock_wait_denies_publication(
    seeded_directory, change, stage
):
    import threading
    import time

    f = seeded_directory
    outcomes = []
    with directory_worker(f) as admission:
        lease = admission.redeem(directory_issue(f), "device_list", body_for(f))
        admission.claim(lease)

        def publish():
            try:
                getattr(admission, stage)(lease)
                outcomes.append("accepted")
            except AccountFailure as failure:
                outcomes.append(failure.code)

        with f[0]["ADMIN"].begin() as blocker:
            blocker.execute(
                text(
                    "SELECT id FROM wso_private.tvt_account_tokens WHERE identity_id=:i AND kind='USER' FOR UPDATE"
                ),
                {"i": f[1]["identity"]},
            )
            thread = threading.Thread(target=publish)
            thread.start()
            reached = False
            deadline = time.monotonic() + 2
            try:
                while time.monotonic() < deadline:
                    with f[0]["ADMIN"].connect() as db:
                        reached = db.execute(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND usename='wso_connection_worker' AND wait_event_type='Lock')"
                            )
                        ).scalar_one()
                    if reached:
                        break
                    time.sleep(0.01)
                assert reached, "publication must be inside its credential lock wait"
                with f[0]["ADMIN"].begin() as db:
                    db.execute(
                        text(CHANGES[change]),
                        {"s": f[1]["session"], "t": f[1]["tenant"], "u": f[1]["staff"]},
                    )
            finally:
                # Rollback releases only this unique fixture's synthetic lock.
                blocker.rollback()
                thread.join(2)
        assert not thread.is_alive() and outcomes == ["ACCOUNT_DENIED"]
        admission.dispose(lease)
