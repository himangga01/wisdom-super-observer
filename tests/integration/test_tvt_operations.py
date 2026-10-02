"""Opt-in uniquely owned PostgreSQL operation diagnostics, never vendor acceptance."""

import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from wso_core.db import tenant_session
from wso_core.jobs import JobFailure, JobService
from wso_core.tenancy import identity_session
from wso_core.tvt.domain_jobs import OPERATION_REGISTRY
from wso_core.tvt.operations import OperationService

from tests.integration.test_tvt_domain_scope import seed_domain, seed_foundation
from tests.integration.test_tvt_startup import baseline
from tests.support.job_handlers import verify_fixture_database

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    ROOT
    / ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W02-operation-fix1-evidence"
)


def diagnostic(context):
    # Optional evidence must never replace SQLAlchemy's original DBAPI error.
    try:
        error = context.original_exception
        sqlstate = getattr(error, "sqlstate", None)
        if type(sqlstate) is not str or sqlstate not in {
            "42702",
            "42703",
            "42601",
            "42501",
        }:
            return
        error_class = type(error).__name__
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", error_class):
            error_class = "DBAPIError"
        record = f"{sqlstate}: {error_class}\n"
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        with (EVIDENCE / "sql-diagnostics.txt").open("a", encoding="utf-8") as out:
            out.write(record)
    except Exception:  # noqa: BLE001 - optional diagnostics cannot own SQL errors
        # Metadata, formatting and filesystem failures are diagnostic failures;
        # returning None keeps the original SQLAlchemy exception propagation.
        return


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
            db.execute(
                text(
                    f"SELECT to_jsonb(t)::text FROM {name} t"
                    + (
                        " WHERE kind NOT IN ('TVT_ACCOUNT_OPERATION','TVT_DEVICE_OPERATION','TYCO_OPERATION')"
                        if table == "job_kinds"
                        else ""
                    )
                    + " ORDER BY 1"
                )
            )
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
def operation_db():
    if os.getenv("WSO_TEST_W02_OPERATION_DIAGNOSTIC") != "1":
        pytest.skip(
            "requires explicit owned W02 operation PostgreSQL development activation"
        )
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
    name = "w02_operation_" + uuid4().hex
    marker = "owned-w02-operation-" + uuid4().hex
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
            assert re.fullmatch(r"w02_operation_[0-9a-f]{32}", name)
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
            role: create_engine(
                url.set(database=name), hide_parameters=True, connect_args=bounds
            )
            for role, url in urls.items()
        }
        for engine in engines.values():
            event.listen(engine, "handle_error", diagnostic)
        config = Config(str(ROOT / "infra/alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            urls["ADMIN"]
            .set(database=name)
            .render_as_string(hide_password=False)
            .replace("%", "%%"),
        )
        command.upgrade(config, "0007_tvt_account_sessions")
        ids = seed_foundation(engines["ADMIN"])
        seed_domain(engines["ADMIN"], ids)
        with engines["ADMIN"].connect() as db:
            before = baseline(db)
            before_rows = foundation_contents(db)
            before_owners = function_owners(db)
            constraints = db.execute(
                text(
                    "SELECT conrelid::regclass::text,conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace IN ('public'::regnamespace,'wso_private'::regnamespace) ORDER BY 1,2"
                )
            ).all()
        command.upgrade(config, "0008_tvt_operation_engine")
        with engines["ADMIN"].connect() as db:
            assert foundation_contents(db, before_rows) == before_rows
            assert set(before_owners).issubset(set(function_owners(db)))
        command.downgrade(config, "0007_tvt_account_sessions")
        with engines["ADMIN"].connect() as db:
            assert baseline(db) == before
            assert foundation_contents(db) == before_rows
            assert function_owners(db) == before_owners
            assert (
                db.execute(
                    text(
                        "SELECT conrelid::regclass::text,conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace IN ('public'::regnamespace,'wso_private'::regnamespace) ORDER BY 1,2"
                    )
                ).all()
                == constraints
            )
        command.upgrade(config, "0008_tvt_operation_engine")
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
def actor_db(operation_db, actor="staff", tenant="tenant"):
    engines, ids = operation_db
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


def firmware(ids, version="v1"):
    return {
        "kind": "firmware",
        "domain": "TVT",
        "identity_id": str(ids["identity"]),
        "device_id": str(ids["device"]),
        "store_id": str(ids["store"]),
        "target_version": version,
    }


def seed_write(operation_db):
    engines, ids = operation_db
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO public.store_memberships(tenant_id,user_id,store_id) VALUES(:t,:a,:s) ON CONFLICT DO NOTHING"
            ),
            {"t": ids["tenant"], "a": ids["owner"], "s": ids["store"]},
        )
        for actor in ("owner", "staff"):
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_identity_grants(id,tenant_id,identity_id,actor_id,action,link_id,revision,expires_at) VALUES(:id,:t,:i,:a,'device.firmware',:l,1,clock_timestamp()+interval '1 hour') ON CONFLICT DO NOTHING"
                ),
                {
                    "id": uuid4(),
                    "t": ids["tenant"],
                    "i": ids["identity"],
                    "a": ids[actor],
                    "l": ids["null_link"],
                },
            )
        for table in ("tvt_upstream_grants", "tvt_capability_snapshots"):
            db.execute(
                text(
                    f"INSERT INTO wso_private.{table}(id,tenant_id,identity_id,device_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(:id,:t,:i,:d,'device.firmware',true,1,1,clock_timestamp(),clock_timestamp()+interval '1 hour') ON CONFLICT DO NOTHING"
                ),
                {
                    "id": uuid4(),
                    "t": ids["tenant"],
                    "i": ids["identity"],
                    "d": ids["device"],
                },
            )


def observe(operation_db, payload):
    """Synthetic trusted observations only; no upstream authorization claim."""
    with operation_db[0]["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.operation_target_observations(tenant_id,intent_key,connection_generation,revision,upstream_verified,capability_verified,observed_at,expires_at) VALUES(:t,decode(wso_private.wso_operation_canonical(CAST(:p AS jsonb))->>'key','hex'),1,1,true,true,clock_timestamp(),clock_timestamp()+interval '1 hour') ON CONFLICT DO NOTHING"
            ),
            {"t": operation_db[1]["tenant"], "p": json.dumps(payload)},
        )


def test_cross_actor_exclusive_hold_and_actor_idempotency(operation_db):
    seed_write(operation_db)
    _, ids = operation_db
    observe(operation_db, firmware(ids))
    observe(operation_db, firmware(ids, "v2"))

    def prepare(actor):
        try:
            with actor_db(operation_db, actor) as db:
                return OperationService(db).prepare(firmware(ids), "race-" + actor)
        except JobFailure as error:
            return error.status

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(prepare, ("owner", "staff")))
    assert sum(result == 409 for result in results) == 1
    winner = next(result for result in results if result != 409)
    actor = "owner" if results[0] != 409 else "staff"
    with actor_db(operation_db, actor) as db:
        replay = OperationService(db).prepare(firmware(ids), "race-" + actor)
        assert replay.operation_id == winner.operation_id
        assert replay.confirmation is None
    with pytest.raises(JobFailure) as error, actor_db(operation_db, actor) as db:
        OperationService(db).prepare(firmware(ids, "v2"), "race-" + actor)
    assert error.value.status == 409
    with actor_db(operation_db, actor) as db:
        OperationService(db).cancel(winner.operation_id)


def test_submit_atomic_outbox_cancel_retains_unknown_hold(operation_db):
    seed_write(operation_db)
    engines, ids = operation_db
    payload = firmware(ids, "v-submit")
    observe(operation_db, payload)
    with actor_db(operation_db) as db:
        prepared = OperationService(db).prepare(payload, "submit-key")
    with actor_db(operation_db) as db:
        result = OperationService(db).submit(
            prepared.operation_id, prepared.confirmation, payload, "submit-key"
        )
        assert result["state"] == "SUBMITTED"
    with engines["ADMIN"].connect() as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM public.outbox WHERE job_id=:id"),
                {"id": result["job_id"]},
            ).scalar_one()
            == 1
        )
    with actor_db(operation_db) as db:
        assert (
            OperationService(db).cancel(prepared.operation_id)["state"]
            == "UNKNOWN_OUTCOME"
        )
    with pytest.raises(JobFailure) as error, actor_db(operation_db, "owner") as db:
        OperationService(db).prepare(payload, "new-key")
    assert error.value.status == 409


def test_generic_enqueue_cannot_mint_operation_job(operation_db):
    from wso_contracts.models import StoreScope

    _, ids = operation_db
    with pytest.raises(JobFailure) as error, actor_db(operation_db, "owner") as db:
        JobService(db, OPERATION_REGISTRY).enqueue(
            StoreScope(tenant_id=ids["tenant"], store_id=ids["store"]),
            "TVT_DEVICE_OPERATION",
            {"schema_version": 1, "operation_id": str(uuid4())},
            "bypass",
        )
    assert error.value.status == 403


def test_unobserved_exact_firmware_target_is_denied(operation_db):
    seed_write(operation_db)
    with pytest.raises(JobFailure) as error, actor_db(operation_db) as db:
        OperationService(db).prepare(
            firmware(operation_db[1], "unobserved"), "unobserved"
        )
    assert error.value.status == 403


def test_direct_sql_uuid_spelling_cannot_evade_hold(operation_db):
    seed_write(operation_db)
    payload = firmware(operation_db[1], "canonical")
    observe(operation_db, payload)
    with actor_db(operation_db) as db:
        OperationService(db).prepare(payload, "canonical")
    upper = {
        key: value.upper() if key.endswith("_id") else value
        for key, value in payload.items()
    }
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError) as error, actor_db(operation_db, "owner") as db:
        db.execute(
            text(
                "SELECT * FROM public.wso_operation_prepare(CAST(:p AS jsonb),'canonical-other')"
            ),
            {"p": json.dumps(upper)},
        )
    assert error.value.orig.sqlstate == "40001"


def submit_fixture(operation_db, version):
    seed_write(operation_db)
    payload = firmware(operation_db[1], version)
    observe(operation_db, payload)
    with actor_db(operation_db) as db:
        prepared = OperationService(db).prepare(payload, version)
        result = OperationService(db).submit(
            prepared.operation_id, prepared.confirmation, payload, version
        )
    return prepared, result, payload


@contextmanager
def executing(operation_db, job_id):
    from wso_core.dispatch import Dispatcher
    from wso_core.worker import JobWorker

    engines, _ = operation_db
    dispatch = Dispatcher(
        engines["DISPATCH"].url.render_as_string(hide_password=False),
        lambda *_: None,
        registry=OPERATION_REGISTRY,
    )
    worker = JobWorker(
        engines["JOB"].url.render_as_string(hide_password=False), OPERATION_REGISTRY
    )
    try:
        references = dispatch.claim_dispatch_batch()
        reference = next(ref for ref in references if ref.job_id == job_id)
        assert len(reference.model_dump()) == 6
        lease = worker.claim(job_id, reference=reference)
        assert lease is not None
        yield worker, lease, reference
    finally:
        worker.engine.dispose()
        dispatch.engine.dispose()


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "FAILED"])
def test_unknown_readback_is_fenced_and_only_definitive_evidence_releases_hold(
    operation_db,
    outcome,
):
    from dataclasses import replace

    from wso_core.tvt.domain_jobs import AuthoritativeReadback

    prepared, result, payload = submit_fixture(operation_db, "readback-" + outcome)
    with executing(operation_db, result["job_id"]) as (worker, lease, _reference):
        assert not lease.reconcile
        worker.fail(lease.job_id, lease.token, "UPSTREAM_TIMEOUT")
        with actor_db(operation_db) as db:
            assert (
                OperationService(db).get(prepared.operation_id)["state"]
                == "UNKNOWN_OUTCOME"
            )
            OperationService(db).reconcile(prepared.operation_id)
        with executing(operation_db, result["job_id"]) as (recovery, current, _):
            assert current.reconcile and current.generation > lease.generation
            with pytest.raises(JobFailure):
                recovery.publish_operation_readback(
                    replace(current, generation=lease.generation),
                    AuthoritativeReadback(
                        outcome=outcome, reference="backend-readback-1"
                    ),
                )
            recovery.publish_operation_readback(
                current,
                AuthoritativeReadback(outcome=outcome, reference="backend-readback-1"),
            )
        with actor_db(operation_db) as db:
            assert OperationService(db).get(prepared.operation_id)["state"] == outcome
            assert (
                OperationService(db).prepare(payload, "readback-next-" + outcome).state
                == "CONFIRMING"
            )

        with operation_db[0]["ADMIN"].connect() as db:
            assert (
                db.execute(
                    text("SELECT state FROM public.jobs WHERE id=:id"),
                    {"id": result["job_id"]},
                ).scalar_one()
                == outcome
            )


def test_expired_confirmation_releases_only_its_hold(operation_db):
    seed_write(operation_db)
    engines, ids = operation_db
    payload = firmware(ids, "expiry")
    observe(operation_db, payload)
    with actor_db(operation_db) as db:
        first = OperationService(db).prepare(payload, "expiry-1")
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.operations SET expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"
            ),
            {"id": first.operation_id},
        )
    with actor_db(operation_db) as db:
        assert OperationService(db).get(first.operation_id)["state"] == "FAILED"
    with actor_db(operation_db, "owner") as db:
        second = OperationService(db).prepare(payload, "expiry-2")
    with actor_db(operation_db) as db:
        OperationService(db).cancel(first.operation_id)
    with engines["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.operation_holds WHERE operation_id=:id"
                ),
                {"id": second.operation_id},
            ).scalar_one()
            == 1
        )
    with pytest.raises(JobFailure), actor_db(operation_db) as db:
        OperationService(db).submit(
            first.operation_id, first.confirmation, payload, "expiry-1"
        )


def test_revocation_denies_generic_read_cancel_claim_and_step(operation_db):
    prepared, result, _ = submit_fixture(operation_db, "revoked")
    engines, ids = operation_db
    with executing(operation_db, result["job_id"]) as (worker, lease, reference):
        with actor_db(operation_db, "owner") as db, pytest.raises(JobFailure):
            JobService(db).get(lease.job_id)
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_identity_grants SET revision=revision+1 WHERE tenant_id=:t AND actor_id=:a AND action='device.firmware'"
                ),
                {"t": ids["tenant"], "a": ids["staff"]},
            )
        with pytest.raises(JobFailure), worker.step(lease):
            pytest.fail("revoked step admitted")
        with pytest.raises(JobFailure), actor_db(operation_db) as db:
            JobService(db).cancel(lease.job_id)
        assert worker.claim(lease.job_id, reference=reference) is None
    with engines["ADMIN"].connect() as db:
        assert (
            db.execute(
                text("SELECT state FROM wso_private.operations WHERE id=:id"),
                {"id": prepared.operation_id},
            ).scalar_one()
            == "UNKNOWN_OUTCOME"
        )


def test_credential_single_use_current_scope_generation_and_publication(operation_db):
    from wso_core.secrets import SecretCipher, SecretRejected
    from wso_core.tvt.operation_credentials import (
        OperationCredentialStore,
        issue_operation_ticket,
    )

    class Key:
        def encryption_key(self):
            return bytes(range(32))

    engines, ids = operation_db
    version = uuid4()
    sealed = SecretCipher(Key()).seal(
        ids["tenant"], ids["connection"], version, b"owned-synthetic"
    )
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.connection_secrets(connection_id,tenant_id,version_id,nonce,ciphertext) VALUES(:c,:t,:v,:n,:b)"
            ),
            {
                "c": ids["connection"],
                "t": ids["tenant"],
                "v": version,
                "n": sealed.nonce,
                "b": sealed.ciphertext,
            },
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_account_sessions(identity_id,tenant_id,actor_id,state) VALUES(:i,:t,:a,'READY')"
            ),
            {"i": ids["identity"], "t": ids["tenant"], "a": ids["staff"]},
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_account_storage(connection_id,tenant_id,kind) VALUES(:c,:t,'USER')"
            ),
            {"c": ids["connection"], "t": ids["tenant"]},
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_account_tokens(id,tenant_id,identity_id,kind,connection_id,version_id,generation) VALUES(:id,:t,:i,'USER',:c,:v,1)"
            ),
            {
                "id": uuid4(),
                "t": ids["tenant"],
                "i": ids["identity"],
                "c": ids["connection"],
                "v": version,
            },
        )
    _, result, _ = submit_fixture(operation_db, "credential")
    with executing(operation_db, result["job_id"]) as (worker, lease, _):
        with pytest.raises(JobFailure):
            worker.issue_connection_handle(lease, ids["connection"])
        store = OperationCredentialStore(
            engines["WORKER"].url.render_as_string(hide_password=False), Key()
        )
        try:
            ticket = issue_operation_ticket(worker, lease)
            secret = store.redeem(ticket)
            with pytest.raises(SecretRejected):
                store.redeem(ticket)

            def use(value):
                assert value == b"owned-synthetic"

            store.use(secret, use)

            def revoke(value):
                with engines["ADMIN"].begin() as db:
                    db.execute(
                        text(
                            "UPDATE wso_private.tvt_capability_snapshots SET revision=revision+1 WHERE action='device.firmware'"
                        )
                    )

            with pytest.raises(SecretRejected):
                store.use(secret, revoke)
            with engines["ADMIN"].connect() as db:
                assert (
                    db.execute(
                        text(
                            "SELECT state FROM wso_private.operations WHERE job_id=:id"
                        ),
                        {"id": lease.job_id},
                    ).scalar_one()
                    == "UNKNOWN_OUTCOME"
                )
            with pytest.raises(SecretRejected):
                store.use(secret, lambda _: pytest.fail("revoked credential used"))
        finally:
            store.close()
    _, result, _ = submit_fixture(operation_db, "credential-output")
    with executing(operation_db, result["job_id"]) as (worker, lease, _):
        store = OperationCredentialStore(
            engines["WORKER"].url.render_as_string(hide_password=False), Key()
        )
        try:
            secret = store.redeem(issue_operation_ticket(worker, lease))
            with pytest.raises(SecretRejected):
                store.use(secret, lambda value: value)
        finally:
            store.close()


def test_payment_channel_scope_and_tyco_exact_target(operation_db):
    engines, ids = operation_db
    payment = {
        "kind": "payment",
        "domain": "TVT",
        "identity_id": str(ids["identity"]),
        "device_id": str(ids["device"]),
        "channel_id": str(ids["channel"]),
        "store_id": str(ids["store"]),
        "product": "cloud",
        "term": "P1Y",
        "quoted_price_version": "quote-1",
    }
    tyco = {
        "kind": "tyco",
        "domain": "TYCO",
        "identity_id": str(ids["tyco_identity"]),
        "panel_id": str(ids["panel"]),
        "action": "relay",
        "target": "relay-1",
        "requested_state": "open",
    }
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_identity_grants(id,tenant_id,identity_id,actor_id,action,link_id,revision,expires_at) VALUES(:id,:tenant,:identity,:staff,'device.purchase',:link,1,clock_timestamp()+interval '1 hour')"
            ),
            {**ids, "id": uuid4()},
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tyco_identity_grants(id,tenant_id,identity_id,actor_id,action,panel_id,revision,expires_at) VALUES(:id,:tenant,:tyco_identity,:staff,'panel.relay',:panel,1,clock_timestamp()+interval '1 hour')"
            ),
            {**ids, "id": uuid4()},
        )
        for table in ("upstream_grants", "capability_snapshots"):
            db.execute(
                text(
                    f"INSERT INTO wso_private.tvt_{table}(id,tenant_id,identity_id,device_id,channel_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(:id,:tenant,:identity,:device,:channel,'device.purchase',true,1,1,clock_timestamp(),clock_timestamp()+interval '1 hour')"
                ),
                {**ids, "id": uuid4()},
            )
            db.execute(
                text(
                    f"INSERT INTO wso_private.tyco_{table}(id,tenant_id,identity_id,panel_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(:id,:tenant,:tyco_identity,:panel,'panel.relay',true,1,1,clock_timestamp(),clock_timestamp()+interval '1 hour')"
                ),
                {**ids, "id": uuid4()},
            )
    observe(operation_db, payment)
    observe(operation_db, tyco)
    with actor_db(operation_db) as db:
        p = OperationService(db).prepare(payment, "payment")
        t = OperationService(db).prepare(tyco, "tyco")
        result = OperationService(db).submit(
            t.operation_id, t.confirmation, tyco, "tyco"
        )
    with engines["ADMIN"].connect() as db:
        assert db.execute(
            text("SELECT kind,scope_kind,store_id FROM public.jobs WHERE id=:id"),
            {"id": result["job_id"]},
        ).one() == ("TYCO_OPERATION", "TENANT", None)
    for invalid in (
        {**payment, "channel_id": str(ids["sibling_channel"])},
        {**payment, "quoted_price_version": "unobserved"},
        {**tyco, "target": "relay-2"},
        {**tyco, "requested_state": "closed"},
    ):
        with pytest.raises(JobFailure) as error, actor_db(operation_db) as db:
            OperationService(db).prepare(invalid, "wrong-target")
        assert error.value.status == 403
    with actor_db(operation_db) as db:
        OperationService(db).cancel(p.operation_id)


def test_lost_worker_lease_retains_unknown_and_never_retries_write(operation_db):
    prepared, result, payload = submit_fixture(operation_db, "crash")
    with executing(operation_db, result["job_id"]) as (worker, lease, reference):
        worker._call(
            "SELECT public.wso_mark_job_submitted(:id,:token)",
            lease.job_id,
            lease.token,
        )
        with operation_db[0]["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE public.jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:id"
                ),
                {"id": lease.job_id},
            )
        assert worker.claim(lease.job_id, reference=reference) is None
        with pytest.raises(JobFailure):
            worker.complete(lease.job_id, lease.token, {})
    with actor_db(operation_db) as db:
        assert (
            OperationService(db).get(prepared.operation_id)["state"]
            == "UNKNOWN_OUTCOME"
        )
    with pytest.raises(JobFailure) as error, actor_db(operation_db, "owner") as db:
        OperationService(db).prepare(payload, "crash-new")
    assert error.value.status == 409


def test_sql_routes_ignore_guc_claims_and_deny_generic_write_authority(operation_db):
    from sqlalchemy.exc import DBAPIError

    engines, ids = operation_db
    with pytest.raises(DBAPIError) as error, engines["APP"].begin() as db:
        db.execute(
            text(
                "SELECT set_config('app.tenant_id',:t,true),set_config('app.user_id',:a,true),set_config('app.role','OWNER',true)"
            ),
            {"t": str(ids["tenant"]), "a": str(ids["owner"])},
        )
        db.execute(
            text("SELECT * FROM public.wso_operation_prepare(CAST(:p AS jsonb),'guc')"),
            {"p": json.dumps(firmware(ids))},
        )
    assert error.value.orig.sqlstate == "42501"
    with pytest.raises(DBAPIError) as error, actor_db(operation_db, "owner") as db:
        db.execute(
            text(
                "SELECT public.wso_enqueue_job(:t,'STORE',:s,'TVT_DEVICE_OPERATION',1,CAST(:p AS jsonb),'generic-sql')"
            ),
            {
                "t": ids["tenant"],
                "s": ids["store"],
                "p": json.dumps({"schema_version": 1, "operation_id": str(uuid4())}),
            },
        )
    assert error.value.orig.sqlstate == "42501"
    for sql in (
        "SELECT public.wso_operation_readback(:id,'invented',1,'SUCCEEDED','invented')",
        "SELECT public.wso_operation_secret('invented')",
    ):
        with pytest.raises(DBAPIError) as error, actor_db(operation_db) as db:
            db.execute(text(sql), {"id": uuid4()})
        assert error.value.orig.sqlstate == "42501"


class OperationFixtureKey:
    def encryption_key(self):
        return bytes(range(32))


def seed_fixture_secret(operation_db, connection="connection"):
    from wso_core.secrets import SecretCipher

    engines, ids = operation_db
    version = uuid4()
    envelope = SecretCipher(OperationFixtureKey()).seal(
        ids["tenant"], ids[connection], version, b"owned-fix1-synthetic"
    )
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.connection_secrets(connection_id,tenant_id,version_id,nonce,ciphertext) VALUES(:c,:t,:v,:n,:b) ON CONFLICT(connection_id) DO UPDATE SET version_id=EXCLUDED.version_id,nonce=EXCLUDED.nonce,ciphertext=EXCLUDED.ciphertext"
            ),
            {
                "c": ids[connection],
                "t": ids["tenant"],
                "v": version,
                "n": envelope.nonce,
                "b": envelope.ciphertext,
            },
        )
    return version


def seed_managed_session(operation_db):
    engines, ids = operation_db
    seed_write(operation_db)
    version = seed_fixture_secret(operation_db)
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_account_sessions(identity_id,tenant_id,actor_id,state) VALUES(:identity,:tenant,:staff,'READY') ON CONFLICT(identity_id) DO UPDATE SET actor_id=EXCLUDED.actor_id,state='READY'"
            ),
            ids,
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_account_storage(connection_id,tenant_id,kind) VALUES(:connection,:tenant,'USER') ON CONFLICT(connection_id) DO NOTHING"
            ),
            ids,
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_account_tokens(id,tenant_id,identity_id,kind,connection_id,version_id,generation) VALUES(:id,:tenant,:identity,'USER',:connection,:v,1) ON CONFLICT(tenant_id,identity_id,kind) DO UPDATE SET version_id=EXCLUDED.version_id,generation=1,renewal_state='IDLE'"
            ),
            {**ids, "id": uuid4(), "v": version},
        )


def change_managed_session(operation_db, change):
    engines, ids = operation_db
    with engines["ADMIN"].begin() as db:
        if change == "actor":
            db.execute(
                text(
                    "UPDATE wso_private.tvt_account_sessions SET actor_id=:owner WHERE identity_id=:identity"
                ),
                ids,
            )
        elif change == "closed":
            db.execute(
                text(
                    "UPDATE wso_private.tvt_account_sessions SET state='CLOSED' WHERE identity_id=:identity"
                ),
                ids,
            )
        elif change == "recreated_actor":
            token = dict(
                db.execute(
                    text(
                        "SELECT id,tenant_id,identity_id,kind,connection_id,version_id,generation FROM wso_private.tvt_account_tokens WHERE identity_id=:identity AND kind='USER'"
                    ),
                    ids,
                )
                .mappings()
                .one()
            )
            db.execute(
                text(
                    "DELETE FROM wso_private.tvt_account_sessions WHERE identity_id=:identity"
                ),
                ids,
            )
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_account_sessions(identity_id,tenant_id,actor_id,state) VALUES(:identity,:tenant,:owner,'READY')"
                ),
                ids,
            )
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_account_tokens(id,tenant_id,identity_id,kind,connection_id,version_id,generation) VALUES(:id,:tenant_id,:identity_id,:kind,:connection_id,:version_id,:generation)"
                ),
                token,
            )
        else:
            raise AssertionError("unknown fixture mutation")


@contextmanager
def operation_secret_store(operation_db):
    from wso_core.tvt.operation_credentials import OperationCredentialStore

    store = OperationCredentialStore(
        operation_db[0]["WORKER"].url.render_as_string(hide_password=False),
        OperationFixtureKey(),
    )
    try:
        yield store
    finally:
        store.close()


def test_managed_session_other_actor_with_all_grants_cannot_prepare(operation_db):
    from wso_core.tvt.operation_credentials import issue_operation_ticket

    seed_managed_session(operation_db)
    engines, ids = operation_db
    payload = firmware(ids, "fix1-other-actor")
    observe(operation_db, payload)
    with engines["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_identity_grants WHERE identity_id=:identity AND actor_id IN (:staff,:owner) AND action='device.firmware'"
                ),
                ids,
            ).scalar_one()
            == 2
        )
    with pytest.raises(JobFailure) as error, actor_db(operation_db, "owner") as db:
        OperationService(db).prepare(payload, "fix1-other-actor")
    assert error.value.status == 403
    with actor_db(operation_db) as db:
        prepared = OperationService(db).prepare(payload, "fix1-own-actor")
        result = OperationService(db).submit(
            prepared.operation_id, prepared.confirmation, payload, "fix1-own-actor"
        )
    with (
        executing(operation_db, result["job_id"]) as (worker, lease, _),
        operation_secret_store(operation_db) as store,
    ):
        credential = store.redeem(issue_operation_ticket(worker, lease))
        observed = []
        store.use(
            credential, lambda value: observed.append(value == b"owned-fix1-synthetic")
        )
        assert observed == [True]


@pytest.mark.parametrize("missing", ["session", "token"])
def test_missing_managed_session_cannot_become_nonmanaged_delegation(
    operation_db, missing
):
    seed_managed_session(operation_db)
    engines, ids = operation_db
    payload = firmware(ids, "fix1-missing-" + missing)
    observe(operation_db, payload)
    with engines["ADMIN"].begin() as db:
        table = "tvt_account_sessions" if missing == "session" else "tvt_account_tokens"
        db.execute(
            text(f"DELETE FROM wso_private.{table} WHERE identity_id=:identity"), ids
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_account_storage WHERE connection_id=:connection"
                ),
                ids,
            ).scalar_one()
            == 1
        )
    for actor in ("staff", "owner"):
        with pytest.raises(JobFailure) as error, actor_db(operation_db, actor) as db:
            OperationService(db).prepare(
                payload, "fix1-missing-" + missing + "-" + actor
            )
        assert error.value.status == 403


def test_managed_actor_change_fences_existing_operation_routes(operation_db):
    from wso_core.secrets import SecretRejected
    from wso_core.tvt.domain_jobs import AuthoritativeReadback
    from wso_core.tvt.operation_credentials import issue_operation_ticket

    seed_managed_session(operation_db)
    engines, ids = operation_db
    payload = firmware(ids, "fix1-unsubmitted")
    observe(operation_db, payload)
    with actor_db(operation_db) as db:
        draft = OperationService(db).prepare(payload, "fix1-unsubmitted")
    submitted, result, _ = submit_fixture(operation_db, "fix1-route-fences")
    with executing(operation_db, result["job_id"]) as (worker, lease, reference):
        change_managed_session(operation_db, "actor")
        with pytest.raises(JobFailure), actor_db(operation_db) as db:
            OperationService(db).submit(
                draft.operation_id, draft.confirmation, payload, "fix1-unsubmitted"
            )
        for method in ("get", "cancel", "reconcile"):
            with pytest.raises(JobFailure), actor_db(operation_db) as db:
                getattr(OperationService(db), method)(submitted.operation_id)
        with pytest.raises(JobFailure), actor_db(operation_db) as db:
            JobService(db).get(lease.job_id)
        with pytest.raises(JobFailure), actor_db(operation_db) as db:
            JobService(db).cancel(lease.job_id)
        with pytest.raises(JobFailure), worker.step(lease):
            pytest.fail("old managed actor entered a job step")
        with pytest.raises(SecretRejected):
            issue_operation_ticket(worker, lease)
        with pytest.raises(JobFailure):
            worker.publish_operation_readback(
                lease,
                AuthoritativeReadback(outcome="SUCCEEDED", reference="fix1-readback"),
            )
        assert worker.claim(lease.job_id, reference=reference) is None
    with engines["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT o.state,count(h.operation_id) FROM wso_private.operations o JOIN wso_private.operation_holds h ON h.operation_id=o.id WHERE o.id=:id GROUP BY o.state"
            ),
            {"id": submitted.operation_id},
        ).one() == ("UNKNOWN_OUTCOME", 1)


@pytest.mark.parametrize("stage", ["redeem", "before_use", "inside_callback"])
@pytest.mark.parametrize("change", ["actor", "closed", "recreated_actor"])
def test_managed_session_change_invalidates_tickets_and_leases(
    operation_db, stage, change
):
    from wso_core.secrets import SecretRejected
    from wso_core.tvt.operation_credentials import issue_operation_ticket

    seed_managed_session(operation_db)
    submitted, result, _ = submit_fixture(operation_db, "fix1-" + stage + "-" + change)
    observed = []
    with (
        executing(operation_db, result["job_id"]) as (worker, lease, reference),
        operation_secret_store(operation_db) as store,
    ):
        ticket = issue_operation_ticket(worker, lease)
        if stage == "redeem":
            change_managed_session(operation_db, change)
            with pytest.raises(SecretRejected):
                store.redeem(ticket)
            assert worker.claim(lease.job_id, reference=reference) is None
        else:
            credential = store.redeem(ticket)
            if stage == "before_use":
                change_managed_session(operation_db, change)

            def callback(value):
                observed.append(value == b"owned-fix1-synthetic")
                if stage == "inside_callback":
                    change_managed_session(operation_db, change)

            with pytest.raises(SecretRejected):
                store.use(credential, callback)
            assert observed == ([True] if stage == "inside_callback" else [])
            with pytest.raises(SecretRejected):
                store.use(
                    credential,
                    lambda _: pytest.fail("stale managed lease invoked callback"),
                )
    with operation_db[0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT o.state,count(h.operation_id) FROM wso_private.operations o JOIN wso_private.operation_holds h ON h.operation_id=o.id WHERE o.id=:id GROUP BY o.state"
            ),
            {"id": submitted.operation_id},
        ).one() == ("UNKNOWN_OUTCOME", 1)


@pytest.mark.parametrize("domain", ["TVT", "TYCO"])
def test_nonmanaged_delegated_operation_credentials_remain_usable(operation_db, domain):
    from wso_core.tvt.operation_credentials import issue_operation_ticket

    engines, _ = operation_db
    ids = seed_foundation(engines["ADMIN"])
    seed_domain(engines["ADMIN"], ids)
    isolated = (engines, ids)
    seed_write(isolated)
    seed_fixture_secret(
        isolated, "connection" if domain == "TVT" else "tyco_connection"
    )
    if domain == "TVT":
        payload = firmware(ids, "fix1-nonmanaged")
    else:
        payload = {
            "kind": "tyco",
            "domain": "TYCO",
            "identity_id": str(ids["tyco_identity"]),
            "panel_id": str(ids["panel"]),
            "action": "relay",
            "target": "relay-1",
            "requested_state": "open",
        }
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "INSERT INTO wso_private.tyco_identity_grants(id,tenant_id,identity_id,actor_id,action,panel_id,revision,expires_at) VALUES(:id,:tenant,:tyco_identity,:owner,'panel.relay',:panel,1,clock_timestamp()+interval '1 hour')"
                ),
                {**ids, "id": uuid4()},
            )
            for table in ("upstream_grants", "capability_snapshots"):
                db.execute(
                    text(
                        f"INSERT INTO wso_private.tyco_{table}(id,tenant_id,identity_id,panel_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(:id,:tenant,:tyco_identity,:panel,'panel.relay',true,1,1,clock_timestamp(),clock_timestamp()+interval '1 hour')"
                    ),
                    {**ids, "id": uuid4()},
                )
    observe(isolated, payload)
    with actor_db(isolated, "owner") as db:
        prepared = OperationService(db).prepare(payload, "fix1-delegated")
        result = OperationService(db).submit(
            prepared.operation_id, prepared.confirmation, payload, "fix1-delegated"
        )
    with (
        executing(isolated, result["job_id"]) as (worker, lease, _),
        operation_secret_store(isolated) as store,
    ):
        credential = store.redeem(issue_operation_ticket(worker, lease))
        observed = []
        store.use(
            credential, lambda value: observed.append(value == b"owned-fix1-synthetic")
        )
        assert observed == [True]
