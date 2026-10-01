"""Opt-in W05 PostgreSQL17 diagnostics; never APK/runtime acceptance."""

import hashlib
import json
import multiprocessing
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from wso_api.tvt.identity_service import IdentityService
from wso_contracts.tvt.account import AccountSelection
from wso_core.db import tenant_session
from wso_core.tenancy import identity_session
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.token_vault import TokenVault

from tests.integration.test_tvt_domain_scope import seed_domain, seed_foundation
from tests.integration.test_tvt_startup import baseline
from tests.support.job_handlers import verify_fixture_database


def _diagnostic(context):
    error = context.original_exception
    diag = getattr(error, "diag", None)
    code = getattr(error, "sqlstate", None)
    # Diagnostic text is permitted only for these SQL compiler errors; values
    # and constraint messages are never recorded.
    if code in {"42702", "42703", "42601"} and EVIDENCE.exists():
        with (EVIDENCE / "sql-compiler-diagnostics.txt").open(
            "a", encoding="utf-8"
        ) as out:
            out.write(
                str(code) + ": " + str(getattr(diag, "message_primary", "")) + "\n"
            )


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT
    / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W05-account-evidence"
)


class TestKey:
    __test__ = False

    def encryption_key(self):
        return bytes(range(32))


def foundation_contents(db, tables=None):
    if tables is None:
        tables = db.execute(
            text(
                "SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname IN ('public','wso_private') AND c.relkind='r' AND c.relname<>'alembic_version' ORDER BY 1,2"
            )
        ).all()
    result = {}
    for schema, table in tables:
        assert re.fullmatch(r"[a-z0-9_]+", schema + table)
        name = f'"{schema}"."{table}"'
        rows = (
            db.execute(text(f"SELECT to_jsonb(t)::text FROM {name} t ORDER BY 1"))
            .scalars()
            .all()
        )
        owner = db.execute(
            text(
                "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid=to_regclass(:name)"
            ),
            {"name": name},
        ).scalar_one()
        # Private row values stay in this process; only an aggregate digest is compared.
        result[(schema, table)] = (
            owner,
            hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
        )
    return result


def function_owners(db):
    return db.execute(
        text(
            "SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname IN ('public','wso_private') ORDER BY 1"
        )
    ).all()


@pytest.fixture(scope="module")
def account_db():
    if os.getenv("WSO_TEST_W05_ACCOUNT_DIAGNOSTIC") != "1":
        pytest.skip("requires explicit owned W05 PostgreSQL development activation")
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
    assert all(os.getenv(f"WSO_TEST_{role}_DATABASE_URL") for role in roles)
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
    identity = None
    name = "w05_account_" + uuid4().hex
    marker = "owned-w05-account-" + uuid4().hex
    receipt = {"name": name, "marker": marker, "cleanup": False}
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
            assert re.fullmatch(r"w05_account_[0-9a-f]{32}", name)
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
        event.listen(
            __import__("sqlalchemy").engine.Engine, "handle_error", _diagnostic
        )
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
        command.upgrade(config, "0006_tvt_startup")
        ids = seed_foundation(engines["ADMIN"])
        seed_domain(engines["ADMIN"], ids)
        with engines["ADMIN"].connect() as db:
            before = baseline(db)
            before_rows = foundation_contents(db)
            before_owners = function_owners(db)
        command.upgrade(config, "0007_tvt_account_sessions")
        with engines["ADMIN"].connect() as db:
            assert foundation_contents(db, before_rows) == before_rows
            assert set(before_owners).issubset(set(function_owners(db)))
        command.downgrade(config, "0006_tvt_startup")
        with engines["ADMIN"].connect() as db:
            assert baseline(db) == before
            assert foundation_contents(db) == before_rows
            assert function_owners(db) == before_owners
        command.upgrade(config, "0007_tvt_account_sessions")
        with engines["ADMIN"].connect() as db:
            assert foundation_contents(db, before_rows) == before_rows
            assert set(before_owners).issubset(set(function_owners(db)))
        receipt["up_down_reup_preserves_definitions_acls"] = True
        receipt["up_down_reup_preserves_existing_rows_and_owners"] = True
        yield engines, ids
    finally:
        for engine in engines.values():
            engine.dispose()
        if control is not None:
            try:
                if identity is not None:
                    verify_fixture_database(source, domain_only=sys.platform == "win32")
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
                                text(
                                    "SELECT count(*) FROM pg_database WHERE datname=:n"
                                ),
                                {"n": name},
                            ).scalar_one()
                            == 0
                        )
                        receipt["cleanup"] = True
            finally:
                control.dispose()
        source.dispose()
        if EVIDENCE.exists():
            (EVIDENCE / f"database-{name}.json").write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )


@contextmanager
def actor_db(account_db, actor="staff", tenant="tenant"):
    engines, ids = account_db
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


@contextmanager
def vault_for(account_db):
    vault = TokenVault(
        account_db[0]["WORKER"].url.render_as_string(hide_password=False), TestKey()
    )
    try:
        yield vault
    finally:
        vault.close()


def issue(account_db, purpose, identity=None, generation=0, actor="staff"):
    with actor_db(account_db, actor) as db:
        return IdentityService(db).issue(
            purpose,
            AccountSelection(region="test", brand="SuperLivePlus"),
            identity_id=identity,
            generation=generation,
        )


def publish(account_db):
    with vault_for(account_db) as vault:
        lease = vault.redeem(issue(account_db, "login"), "login")
        identity = vault.publish(lease, "synthetic-user-token", "synthetic-p2p-token")
    return identity


def test_staff_login_publication_separates_secret_kinds_and_denies_generic_handles(
    account_db,
):
    identity = publish(account_db)
    engines, _ids = account_db
    with engines["ADMIN"].connect() as db:
        rows = db.execute(
            text(
                "SELECT t.kind,t.connection_id,t.version_id,t.generation,s.ciphertext FROM wso_private.tvt_account_tokens t JOIN wso_private.connection_secrets s USING(connection_id) WHERE t.identity_id=:i ORDER BY kind"
            ),
            {"i": identity},
        ).all()
        assert [r.kind for r in rows] == ["P2P", "USER"]
        assert len({r.connection_id for r in rows}) == 2
        assert all(b"synthetic" not in r.ciphertext for r in rows)
        assert (
            db.execute(
                text("SELECT count(*) FROM wso_private.tvt_identities WHERE id=:i"),
                {"i": identity},
            ).scalar_one()
            == 1
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_upstream_grants WHERE identity_id=:i AND action<>'account.read'"
                ),
                {"i": identity},
            ).scalar_one()
            == 0
        )
    with actor_db(account_db, "owner") as db:
        for row in rows:
            assert (
                db.execute(
                    text("SELECT public.wso_issue_connection_handle(:id,1)"),
                    {"id": row.connection_id},
                ).scalar_one()
                is None
            )
        assert (
            rows[0].connection_id
            not in db.execute(text("SELECT id FROM public.connections")).scalars().all()
        )
    with vault_for(account_db) as vault:
        lease = vault.redeem(issue(account_db, "profile", identity, 1), "profile")
        assert (
            vault.use(lease, lambda secret: secret == b"synthetic-user-token") is True
        )
    with pytest.raises(AccountFailure):
        issue(account_db, "profile", identity, 1, actor="owner")


def test_ticket_cannot_replay_or_outlive_membership_and_grants(account_db):
    identity = publish(account_db)
    ticket = issue(account_db, "profile", identity, 1)
    with vault_for(account_db) as vault:
        lease = vault.redeem(ticket, "profile")
        with pytest.raises(AccountFailure):
            vault.redeem(ticket, "profile")
        with account_db[0]["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_identity_grants SET expires_at=clock_timestamp()-interval '1 second' WHERE identity_id=:i"
                ),
                {"i": identity},
            )
        with pytest.raises(AccountFailure):
            vault.use(lease, lambda _: pytest.fail("revoked bytes reached callback"))
    with pytest.raises(AccountFailure):
        issue(account_db, "profile", identity, 1)


def test_challenges_are_actor_bound_expiring_and_consumed_once(account_db):
    with vault_for(account_db) as vault:
        lease = vault.redeem(issue(account_db, "image"), "image")
        challenge = vault.save_challenge(lease, "synthetic-private-image-id")
        foreign = vault.redeem(issue(account_db, "check", actor="owner"), "check")
        with pytest.raises(AccountFailure):
            vault.consume_challenge(foreign, challenge)
        own = vault.redeem(issue(account_db, "check"), "check")
        assert vault.consume_challenge(own, challenge) == "synthetic-private-image-id"
        with pytest.raises(AccountFailure):
            vault.consume_challenge(own, challenge)


def _renew_process(url, ticket, queue, gate, crash=False):
    with_token = TokenVault(url, TestKey())
    try:
        lease = with_token.redeem(ticket, "renew")
        gate.wait(10)

        def callback(value):
            queue.put(("called", os.getpid()))
            if crash:
                # Let the witness reach the parent before terminating this owned process.
                queue.close()
                queue.join_thread()
                os._exit(17)
            return "synthetic-new-user-token"

        generation = with_token.renew(lease, callback)
        queue.put(("generation", generation))
    except AccountFailure as error:
        queue.put(("error", error.code))
    finally:
        with_token.close()


def test_two_process_singleflight_and_crashed_owner_fence(account_db):
    identity = publish(account_db)
    tickets = [issue(account_db, "renew", identity, 1) for _ in range(2)]
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    gate = context.Event()
    url = account_db[0]["WORKER"].url.render_as_string(hide_password=False)
    children = [
        context.Process(target=_renew_process, args=(url, t, queue, gate))
        for t in tickets
    ]
    for child in children:
        child.start()
    gate.set()
    for child in children:
        child.join(20)
        assert not child.is_alive() and child.exitcode == 0
    results = [queue.get(timeout=5) for _ in range(3)]
    assert sum(r[0] == "called" for r in results) == 1
    assert [r[1] for r in results if r[0] == "generation"] == [2, 2]
    queue.close()
    queue.join_thread()
    crash_ticket = issue(account_db, "renew", identity, 2)
    queue = context.Queue()
    gate = context.Event()
    gate.set()
    child = context.Process(
        target=_renew_process, args=(url, crash_ticket, queue, gate, True)
    )
    child.start()
    child.join(20)
    assert not child.is_alive() and child.exitcode == 17
    assert queue.get(timeout=5)[0] == "called"
    queue.close()
    queue.join_thread()
    with vault_for(account_db) as vault:
        lease = vault.redeem(issue(account_db, "renew", identity, 2), "renew")
        with pytest.raises(AccountFailure, match="RENEWAL_OUTCOME_UNKNOWN"):
            vault.renew(lease, lambda _: pytest.fail("crashed attempt was replayed"))
    with account_db[0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT generation FROM wso_private.tvt_account_tokens WHERE identity_id=:i AND kind='USER'"
                ),
                {"i": identity},
            ).scalar_one()
            == 2
        )
        assert (
            db.execute(
                text(
                    "SELECT generation FROM wso_private.tvt_account_tokens WHERE identity_id=:i AND kind='P2P'"
                ),
                {"i": identity},
            ).scalar_one()
            == 1
        )


def test_logout_revokes_local_tokens_without_changing_web_identity(account_db):
    identity = publish(account_db)
    with vault_for(account_db) as vault:
        lease = vault.redeem(issue(account_db, "logout", identity, 1), "logout")
        vault.revoke(lease)
    with account_db[0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.connection_secrets s JOIN wso_private.tvt_account_tokens t USING(connection_id) WHERE t.identity_id=:i"
                ),
                {"i": identity},
            ).scalar_one()
            == 0
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM public.memberships WHERE tenant_id=:t AND user_id=:a"
                ),
                {"t": account_db[1]["tenant"], "a": account_db[1]["staff"]},
            ).scalar_one()
            == 1
        )
    with pytest.raises(AccountFailure):
        issue(account_db, "profile", identity, 1)


def test_app_and_job_cannot_execute_worker_or_read_private_tables(account_db):
    for role in ("APP", "JOB", "WORKER"):
        for table in (
            "tvt_account_sessions",
            "tvt_account_tokens",
            "tvt_account_tickets",
            "connection_secrets",
        ):
            with account_db[0][role].connect() as db, pytest.raises(DBAPIError):
                db.execute(text(f"SELECT * FROM wso_private.{table}"))
    for role in ("APP", "JOB"):
        with account_db[0][role].connect() as db, pytest.raises(DBAPIError):
            db.execute(
                text(
                    "SELECT public.wso_tvt_account_redeem(repeat('0',64),repeat('1',64))"
                )
            )


def test_success_without_replacement_deduplicates_without_inventing_rotation(
    account_db,
):
    identity = publish(account_db)
    storage_query = text(
        "SELECT t.kind,t.connection_id,t.version_id,t.generation,c.generation,md5(to_jsonb(s)::text) "
        "FROM wso_private.tvt_account_tokens t JOIN public.connections c ON c.id=t.connection_id "
        "JOIN wso_private.connection_secrets s ON s.connection_id=t.connection_id "
        "WHERE t.identity_id=:i ORDER BY t.kind"
    )
    with account_db[0]["ADMIN"].begin() as db:
        original_storage = db.execute(storage_query, {"i": identity}).all()
        cutoff = db.execute(
            text("SELECT clock_timestamp()+interval '2 seconds'")
        ).scalar_one()
        db.execute(
            text(
                "UPDATE wso_private.tvt_identity_grants SET expires_at=:cutoff WHERE identity_id=:i"
            ),
            {"i": identity, "cutoff": cutoff},
        )
        for table in ("tvt_upstream_grants", "tvt_capability_snapshots"):
            db.execute(
                text(
                    f"UPDATE wso_private.{table} SET observed_at=CAST(:cutoff AS timestamptz)-interval '5 minutes',expires_at=:cutoff WHERE identity_id=:i"
                ),
                {"i": identity, "cutoff": cutoff},
            )
    tickets = [issue(account_db, "renew", identity, 1) for _ in range(2)]
    observed = []
    with vault_for(account_db) as vault:
        leases = [vault.redeem(ticket, "renew") for ticket in tickets]
        old_profile = vault.redeem(issue(account_db, "profile", identity, 1), "profile")

        def no_replacement(value):
            observed.append(True)

        assert vault.renew(leases[0], no_replacement) == 1
        assert vault.renew(leases[1], no_replacement) == 1
        # Cross the actual old cutoff; never replace the authority clock or
        # change new observations after publication to make admission pass.
        with account_db[0]["ADMIN"].connect() as db:
            db.execute(
                text(
                    "SELECT pg_sleep(greatest(0,extract(epoch FROM (CAST(:cutoff AS timestamptz)-clock_timestamp())))+0.02)"
                ),
                {"cutoff": cutoff},
            )
            assert db.execute(
                text("SELECT clock_timestamp()>:cutoff"), {"cutoff": cutoff}
            ).scalar_one()
        fresh_profile = vault.redeem(
            issue(account_db, "profile", identity, 1), "profile"
        )
        assert vault.use(fresh_profile, lambda value: value == b"synthetic-user-token")
        assert issue(account_db, "renew", identity, 1)
        with pytest.raises(AccountFailure):
            vault.use(
                old_profile, lambda _: pytest.fail("old revision used saved bytes")
            )
    assert observed == [True]
    with account_db[0]["ADMIN"].connect() as db:
        row = db.execute(
            text(
                "SELECT generation,renewal_sequence FROM wso_private.tvt_account_tokens WHERE identity_id=:i AND kind='USER'"
            ),
            {"i": identity},
        ).one()
        assert tuple(row) == (1, 1)
        assert db.execute(storage_query, {"i": identity}).all() == original_storage
        authority = db.execute(
            text(
                "SELECT g.revision,u.revision,c.revision,u.connection_generation,c.connection_generation,"
                "g.expires_at,u.expires_at,c.expires_at,u.observed_at,c.observed_at,clock_timestamp() AS now "
                "FROM wso_private.tvt_identity_grants g JOIN wso_private.tvt_upstream_grants u USING(tenant_id,identity_id,action) "
                "JOIN wso_private.tvt_capability_snapshots c USING(tenant_id,identity_id,action) "
                "WHERE g.identity_id=:i AND g.action='account.read'"
            ),
            {"i": identity},
        ).one()
        assert tuple(authority[:5]) == (2, 2, 2, 1, 1)
        assert authority[5] == authority[6] == authority[7]
        assert authority[5] > authority[10] > cutoff
        for observation in authority[8:10]:
            assert cutoff > observation
            assert 299 < (authority[5] - observation).total_seconds() <= 300
        for table in (
            "tvt_identity_grants",
            "tvt_upstream_grants",
            "tvt_capability_snapshots",
        ):
            assert (
                db.execute(
                    text(
                        f"SELECT count(*) FROM wso_private.{table} WHERE identity_id=:i AND action<>'account.read'"
                    ),
                    {"i": identity},
                ).scalar_one()
                == 0
            )


def test_raw_guc_unknown_kind_region_and_generation_cannot_issue(account_db):
    identity = publish(account_db)
    with account_db[0]["APP"].begin() as db:
        db.execute(
            text(
                "SELECT set_config('wso.tenant_id',:t,true),set_config('wso.user_id',:u,true),set_config('wso.role','OWNER',true)"
            ),
            {"t": str(account_db[1]["tenant"]), "u": str(account_db[1]["owner"])},
        )
        assert (
            db.execute(
                text(
                    "SELECT public.wso_tvt_account_issue('login','test','SuperLivePlus',NULL,'USER',0)"
                )
            ).scalar_one()
            is None
        )
    with actor_db(account_db) as db:
        for region, kind, generation in [
            ("wrong", "USER", 1),
            ("test", "P2P", 1),
            ("test", "DEVICE", 1),
            ("test", "USER", 2),
            ("test", "UNKNOWN", 1),
        ]:
            assert (
                db.execute(
                    text(
                        "SELECT public.wso_tvt_account_issue('profile',:region,'SuperLivePlus',:identity,:kind,:generation)"
                    ),
                    {
                        "region": region,
                        "identity": identity,
                        "kind": kind,
                        "generation": generation,
                    },
                ).scalar_one()
                is None
            )


def test_missing_kind_and_stale_publisher_cannot_obtain_or_replace_saved_bytes(
    account_db,
):
    identity = publish(account_db)
    with vault_for(account_db) as vault:
        lease = vault.redeem(issue(account_db, "renew", identity, 1), "renew")
        witness = uuid4()
        with vault.transaction() as db:
            assert (
                db.execute(
                    text("SELECT public.wso_tvt_account_renew_claim(:lease,:attempt)"),
                    {"lease": lease.value, "attempt": witness},
                ).scalar_one()
                == "CLAIMED"
            )
        with vault.transaction() as db:
            assert (
                db.execute(
                    text(
                        "SELECT public.wso_tvt_account_renew_publish(:lease,:attempt,NULL,NULL,NULL)"
                    ),
                    {"lease": lease.value, "attempt": uuid4()},
                ).scalar_one()
                is None
            )
        with account_db[0]["ADMIN"].begin() as db:
            db.execute(
                text(
                    "DELETE FROM wso_private.tvt_account_tokens WHERE identity_id=:i AND kind='USER'"
                ),
                {"i": identity},
            )
        with pytest.raises(AccountFailure):
            vault.use(lease, lambda _: pytest.fail("missing kind reached callback"))


def test_local_close_is_current_actor_bound_idempotent_without_worker(account_db):
    identity = publish(account_db)
    with actor_db(account_db, "owner") as db, pytest.raises(AccountFailure):
        IdentityService(db).close(identity)
    with actor_db(account_db) as db:
        IdentityService(db).close(identity)
    with actor_db(account_db) as db:
        IdentityService(db).close(identity)
    with pytest.raises(AccountFailure):
        issue(account_db, "profile", identity, 1)


def test_worker_logout_attempts_real_account_path_then_revokes_on_uncertainty(
    account_db, monkeypatch
):
    from wso_api.tvt.session_service import AccountEndpoint, AccountWorkerExecutor
    from wso_core.tvt import account_client
    from wso_core.tvt.account_protocol import AccountResponse

    paths = []

    class Boundary:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, request):
            paths.append(request.path)
            assert json.loads(request.body)["basic"]["token"] == "synthetic-user-token"
            return AccountResponse(503, 503, b'{"basic":{"msgcode":503}}')

        def close(self):
            pass

    monkeypatch.setattr(account_client, "ProcessAccountTransport", Boundary)
    identity = publish(account_db)
    with vault_for(account_db) as vault:
        worker = AccountWorkerExecutor(
            vault,
            (
                AccountEndpoint(
                    "test",
                    "SuperLivePlus",
                    "https://upstream.test",
                    "en",
                    "US",
                    "1.18.1",
                ),
            ),
        )
        result = worker.logout(
            issue(account_db, "logout", identity, 1),
            deadline_ms=10000,
            correlation_id="synthetic-logout",
        )
        assert result.state == "CLOSED" and result.upstream_outcome == "unknown"
    assert paths == ["/user/logout"]
    with pytest.raises(AccountFailure):
        issue(account_db, "profile", identity, 1)


def test_old_domain_and_legacy_controls_then_adoption_fences_every_generic_use(
    account_db,
):
    from datetime import UTC, datetime, timedelta

    from wso_core.secrets import SecretCipher, SecretRejected, WorkerSecretStore
    from wso_core.tvt.authorization import DomainTarget, authorize
    from wso_core.tvt.credentials import CredentialProvider

    engines, ids = account_db
    legacy = uuid4()
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO public.connections(id,tenant_id,kind,alias,site,status,generation) VALUES(:id,:tenant,'TVT_ACCOUNT','Legacy','Fixture','NOT_VERIFIED',1)"
            ),
            {"id": legacy, "tenant": ids["tenant"]},
        )
        for connection in (legacy, ids["connection"], ids["tyco_connection"]):
            version = uuid4()
            envelope = SecretCipher(TestKey()).seal(
                ids["tenant"], connection, version, b"synthetic-old-secret"
            )
            db.execute(
                text(
                    "INSERT INTO wso_private.connection_secrets VALUES(:id,:tenant,:version,:nonce,:cipher)"
                ),
                {
                    "id": connection,
                    "tenant": ids["tenant"],
                    "version": version,
                    "nonce": envelope.nonce,
                    "cipher": envelope.ciphertext,
                },
            )
    worker = WorkerSecretStore(
        engines["WORKER"].url.render_as_string(hide_password=False), TestKey()
    )
    target = DomainTarget(
        "TVT", ids["identity"], ids["device"], ids["channel"], ids["store"]
    )
    try:
        handles = []
        with actor_db(account_db) as db:
            for _ in range(2):
                handles.append(
                    CredentialProvider(db).with_handle(
                        authorize(db, target, "media.live"),
                        "media.live",
                        datetime.now(UTC) + timedelta(seconds=25),
                    )
                )
        lease = worker.with_secret(handles[0])
        assert lease.use(lambda data: data == b"synthetic-old-secret")
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_account_storage(connection_id,tenant_id,kind) VALUES(:connection,:tenant,'USER')"
                ),
                ids,
            )
        with pytest.raises(SecretRejected):
            lease.use(lambda _: pytest.fail("old lease survived adoption"))
        with pytest.raises(SecretRejected):
            worker.with_secret(handles[1])
        with actor_db(account_db) as db, pytest.raises(SecretRejected):
            CredentialProvider(db).with_handle(
                authorize(db, target, "media.live"),
                "media.live",
                datetime.now(UTC) + timedelta(seconds=25),
            )
        # Unrelated existing domain and never-mapped owner paths remain valid.
        with actor_db(account_db) as db:
            panel = DomainTarget("TYCO", ids["tyco_identity"], panel_id=ids["panel"])
            handle = CredentialProvider(db).with_handle(
                authorize(db, panel, "panel.read"),
                "panel.read",
                datetime.now(UTC) + timedelta(seconds=25),
            )
        assert worker.with_secret(handle).use(len) == 20
        with actor_db(account_db, "owner") as db:
            handle = db.execute(
                text("SELECT public.wso_issue_connection_handle(:id,1)"), {"id": legacy}
            ).scalar_one()
        assert worker.with_secret(handle).use(len) == 20
    finally:
        worker._factory.kw["bind"].dispose()


def test_w05_metadata_deletion_never_reopens_untyped_domain_path(account_db):
    from datetime import UTC, datetime, timedelta

    from wso_core.secrets import SecretRejected
    from wso_core.tvt.authorization import DomainTarget, authorize
    from wso_core.tvt.credentials import CredentialProvider

    identity = publish(account_db)
    with actor_db(account_db) as db:
        scope = authorize(db, DomainTarget("TVT", identity), "account.read")
        with pytest.raises(SecretRejected):
            CredentialProvider(db).with_handle(
                scope, "account.read", datetime.now(UTC) + timedelta(seconds=25)
            )
    with account_db[0]["ADMIN"].begin() as db:
        db.execute(
            text("DELETE FROM wso_private.tvt_account_sessions WHERE identity_id=:id"),
            {"id": identity},
        )
    with actor_db(account_db) as db:
        scope = authorize(db, DomainTarget("TVT", identity), "account.read")
        with pytest.raises(SecretRejected):
            CredentialProvider(db).with_handle(
                scope, "account.read", datetime.now(UTC) + timedelta(seconds=25)
            )
    with pytest.raises(AccountFailure):
        issue(account_db, "profile", identity, 1)


@pytest.fixture
def account_api(account_db):
    from datetime import UTC, datetime, timedelta

    from fastapi.testclient import TestClient
    from wso_api.auth import (
        AuthService,
        AuthSettings,
        OIDCVerifier,
        PostgresSessionStore,
        WebSession,
        token_digest,
    )
    from wso_api.main import create_app

    engines, ids = account_db
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
    app = create_app()
    app.state.auth_service = AuthService(
        settings,
        OIDCVerifier(settings),
        sessions,
        identity_factory=sessionmaker(engines["IDENTITY"]),
        tenant_factory=sessionmaker(engines["APP"]),
    )
    with TestClient(app, base_url="https://app.test") as client:
        token = uuid4().hex
        assert sessions.create(
            token_digest(token),
            WebSession(
                "https://w02.test",
                str(ids["staff"]),
                ids["staff"],
                token_digest("csrf"),
                datetime.now(UTC) + timedelta(minutes=10),
            ),
            token_digest(uuid4().hex),
        )
        client.cookies.set("__Host-wso-session", token)
        yield client


def test_real_t03_api_redaction_csrf_before_json_and_local_logout(
    account_db, account_api
):
    api = account_api
    params = {"tenant_id": str(account_db[1]["tenant"])}
    headers = {"Origin": "https://app.test", "X-CSRF-Token": "csrf"}
    r = api.post(
        "/api/v1/tvt/identities/login",
        params=params,
        content="{bad",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 403
    body = {
        "mode": "email",
        "account": "person@example.test",
        "secret": "synthetic-private-secret",
        "region": "test",
        "brand": "SuperLivePlus",
    }
    r = api.post(
        "/api/v1/tvt/identities/login", params=params, headers=headers, json=body
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "ACCOUNT_UNAVAILABLE"
    r = api.post(
        "/api/v1/tvt/identities/login",
        params=params,
        headers=headers,
        json=body | {"mode": "invalid"},
    )
    assert r.status_code == 422 and "synthetic-private-secret" not in r.text
    identity = publish(account_db)
    r = api.post(
        f"/api/v1/tvt/identities/{identity}/logout", params=params, headers=headers
    )
    assert (
        r.status_code == 200
        and r.json()["state"] == "CLOSED"
        and r.json()["upstream_outcome"] == "not_attempted"
    )
    assert api.get("/api/v1/me").status_code == 200
    assert r.headers["cache-control"] == "no-store" and "Cookie" in r.headers["vary"]
    assert r.json()["request_id"] == r.headers["x-request-id"]


def test_real_client_login_profile_projection_and_configured_origin_selection(
    account_db, monkeypatch
):
    from wso_api.tvt.session_service import AccountEndpoint, AccountWorkerExecutor
    from wso_contracts.tvt.account import AccountLogin
    from wso_core.tvt import account_client
    from wso_core.tvt.account_protocol import AccountResponse

    paths = []

    class Boundary:
        def __init__(self, *args, **kwargs):
            assert kwargs["origin"] == "https://upstream.test"

        def send(self, request):
            paths.append(request.path)
            if request.path == "/user/login":
                data = json.loads(request.body)["data"]
                assert data["type"] == 1 and data["userName"] == "person@example.test"
                assert (
                    len(data["password"]) == 128
                    and data["password"] != "synthetic-password"
                )
                return AccountResponse(
                    200,
                    200,
                    b'{"basic":{"msgcode":200},"data":{"token":"synthetic-client-user","p2pId":"synthetic-client-p2p"}}',
                )
            assert request.path == "/user/info/get"
            return AccountResponse(
                200,
                200,
                b'{"basic":{"msgcode":200},"data":{"userId":"PRIVATE-ID","type":4,"nickName":"Example","image":"/private.jpg"}}',
            )

        def close(self):
            pass

    monkeypatch.setattr(account_client, "ProcessAccountTransport", Boundary)
    statuses = []
    with vault_for(account_db) as vault:
        worker = AccountWorkerExecutor(
            vault,
            (
                AccountEndpoint(
                    "test",
                    "SuperLivePlus",
                    "https://upstream.test",
                    "en",
                    "US",
                    "1.18.1",
                ),
            ),
            statuses.append,
        )
        login = worker.login(
            issue(account_db, "login"),
            AccountLogin(
                region="test",
                brand="SuperLivePlus",
                mode="email",
                account="person@example.test",
                secret="synthetic-password",
            ),
            deadline_ms=10000,
            correlation_id="synthetic-login",
        )
        profile = worker.profile(
            issue(account_db, "profile", login.identity_id, 1),
            deadline_ms=10000,
            correlation_id="synthetic-profile",
        )
        assert (
            profile.profile.account_type == 4 and profile.profile.nickname == "Example"
        )
        assert (
            "PRIVATE" not in profile.model_dump_json()
            and "/private" not in profile.model_dump_json()
        )
    assert paths == ["/user/login", "/user/info/get"]
    assert [(s.http_status, s.native_msgcode) for s in statuses] == [
        (200, 200),
        (200, 200),
    ]


def test_current_membership_change_after_upstream_prevents_publication(account_db):
    with vault_for(account_db) as vault:
        lease = vault.redeem(issue(account_db, "login"), "login")
        try:
            with account_db[0]["ADMIN"].begin() as db:
                db.execute(
                    text(
                        "UPDATE public.memberships SET role='MANAGER' WHERE tenant_id=:tenant AND user_id=:staff"
                    ),
                    account_db[1],
                )
            with pytest.raises(AccountFailure):
                vault.publish(lease, "synthetic-user", "")
        finally:
            with account_db[0]["ADMIN"].begin() as db:
                db.execute(
                    text(
                        "UPDATE public.memberships SET role='STAFF' WHERE tenant_id=:tenant AND user_id=:staff"
                    ),
                    account_db[1],
                )


def test_remaining_deadline_prevents_late_publication_and_keeps_renewal_witness(
    account_db,
):
    from wso_core.tvt.token_vault import token_budget

    identity = publish(account_db)
    with vault_for(account_db) as vault:
        lease = vault.redeem(issue(account_db, "renew", identity, 1), "renew")
        live = [True]

        def remaining():
            if not live[0]:
                raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
            return 1000

        def callback(value):
            live[0] = False
            return "late-synthetic-token"

        with (
            token_budget(remaining),
            pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"),
        ):
            vault.renew(lease, callback)
    with account_db[0]["ADMIN"].connect() as db:
        row = db.execute(
            text(
                "SELECT generation,renewal_state FROM wso_private.tvt_account_tokens WHERE identity_id=:i AND kind='USER'"
            ),
            {"i": identity},
        ).one()
        assert tuple(row) == (1, "INFLIGHT")


def test_outer_cancellation_inside_worker_denies_publication_and_commit(account_db):
    from wso_api.tvt.session_service import worker_budget
    from wso_core.tvt.token_vault import token_budget

    identity = publish(account_db)
    live = [True]

    def remaining():
        if not live[0]:
            raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
        return 1000

    with vault_for(account_db) as vault:
        lease = vault.redeem(issue(account_db, "renew", identity, 1), "renew")

        def callback(value):
            live[0] = False
            return "cancelled-synthetic-token"

        @worker_budget
        def operation(*, deadline_ms):
            vault.renew(lease, callback)

        with (
            token_budget(remaining),
            pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"),
        ):
            operation(deadline_ms=2000)

        # Cancellation after successful SQL must also abort the transaction.
        live[0] = True

        @worker_budget
        def write(*, deadline_ms):
            with vault.transaction() as db:
                db.execute(text("CREATE TEMP TABLE w05_cancel_commit (value int)"))
                live[0] = False

        with (
            token_budget(remaining),
            pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"),
        ):
            write(deadline_ms=2000)
        with vault.transaction() as db:
            assert (
                db.execute(
                    text("SELECT to_regclass('pg_temp.w05_cancel_commit')")
                ).scalar_one()
                is None
            )

    with account_db[0]["ADMIN"].connect() as db:
        row = db.execute(
            text(
                "SELECT generation,renewal_state FROM wso_private.tvt_account_tokens WHERE identity_id=:i AND kind='USER'"
            ),
            {"i": identity},
        ).one()
        assert tuple(row) == (1, "INFLIGHT")


def test_metadata_rls_nologin_owner_and_no_public_function_execute(account_db):
    with account_db[0]["ADMIN"].connect() as db:
        rows = db.execute(
            text(
                "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wso_private' AND c.relkind='r' AND c.relname LIKE 'tvt_account_%'"
            )
        ).all()
        assert len(rows) == 5 and all(
            tuple(r[1:]) == (True, True, "wso_account_owner") for r in rows
        )
        assert not any(
            db.execute(
                text(
                    "SELECT rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='wso_account_owner'"
                )
            ).one()
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM pg_auth_members WHERE member='wso_account_owner'::regrole OR roleid='wso_account_owner'::regrole"
                )
            ).scalar_one()
            == 0
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a WHERE p.proowner='wso_account_owner'::regrole AND a.grantee=0 AND a.privilege_type='EXECUTE'"
                )
            ).scalar_one()
            == 0
        )


def test_expired_challenge_and_auxiliary_generic_mutation_are_denied(account_db):
    with vault_for(account_db) as vault:
        image = vault.redeem(issue(account_db, "image"), "image")
        challenge = vault.save_challenge(image, "synthetic-expiring-image-id")
        with account_db[0]["ADMIN"].begin() as db:
            connection = db.execute(
                text(
                    "UPDATE wso_private.tvt_account_challenges SET expires_at=clock_timestamp()-interval '1 second' WHERE id=:id RETURNING connection_id"
                ),
                {"id": challenge},
            ).scalar_one()
        check = vault.redeem(issue(account_db, "check"), "check")
        with pytest.raises(AccountFailure, match="CHALLENGE_EXPIRED"):
            vault.consume_challenge(check, challenge)
    with actor_db(account_db, "owner") as db, pytest.raises(DBAPIError) as denied:
        db.execute(
            text(
                "SELECT public.wso_mutate_connection(:connection,1,'delete','{}'::jsonb,NULL,NULL,NULL,'synthetic')"
            ),
            {"connection": connection},
        )
    assert denied.value.orig.sqlstate == "42501"
