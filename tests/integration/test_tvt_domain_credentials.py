"""Opt-in PG17 development diagnostics; no live/provider acceptance."""

import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from wso_core.connections import ConnectionService
from wso_core.db import tenant_session
from wso_core.secrets import (
    FileKeyProvider,
    SecretCipher,
    SecretRejected,
    WorkerSecretStore,
)
from wso_core.tenancy import identity_session
from wso_core.tvt.authorization import DomainTarget, authorize

from tests.integration.test_tvt_domain_scope import (
    seed_domain,
    seed_foundation,
)

pytest_plugins = ["tests.integration.test_tvt_domain_scope"]


@pytest.fixture(autouse=True)
def bounded_migration_connections(monkeypatch):
    # Keep the verified saved URL identity intact. Libpq applies these bounds
    # to Alembic's own engines as well as the fixture's bounded role engines.
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "5")
    monkeypatch.setenv(
        "PGOPTIONS",
        os.environ.get("PGOPTIONS", "")
        + " -c statement_timeout=10000 -c lock_timeout=3000",
    )


@pytest.fixture
def credential_case(disposable_domain_db, tmp_path):
    engines, config = disposable_domain_db
    command.upgrade(config, "0005_tvt_credentials")
    ids = seed_foundation(engines["ADMIN"])
    seed_domain(engines["ADMIN"], ids)
    key = tmp_path / "test-key"
    key.write_bytes(bytes(range(32)))
    provider = FileKeyProvider(key)
    from uuid import uuid4

    ids["legacy_connection"] = uuid4()
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO public.connections(id,tenant_id,kind,alias,site,status,generation) VALUES(:legacy_connection,:tenant,'TVT_ACCOUNT','Legacy fixture','Fixture','NOT_VERIFIED',1)"
            ),
            ids,
        )
        for name in ("connection", "tyco_connection", "legacy_connection"):
            version = uuid4()
            envelope = SecretCipher(provider).seal(
                ids["tenant"], ids[name], version, b"synthetic-credential"
            )
            db.execute(
                text(
                    "INSERT INTO wso_private.connection_secrets VALUES(:c,:t,:v,:n,:s)"
                ),
                {
                    "c": ids[name],
                    "t": ids["tenant"],
                    "v": version,
                    "n": envelope.nonce,
                    "s": envelope.ciphertext,
                },
            )
    worker_url = make_url(os.environ["WSO_TEST_WORKER_DATABASE_URL"]).set(
        database=engines["ADMIN"].url.database
    )
    worker = WorkerSecretStore(
        worker_url.render_as_string(hide_password=False), provider
    )
    # Production worker API is unchanged; bound the diagnostic connection pool.
    worker._factory.kw["bind"].dispose()
    worker._factory = sessionmaker(
        create_engine(
            worker_url,
            hide_parameters=True,
            connect_args={
                "connect_timeout": 5,
                "options": "-c statement_timeout=10000 -c lock_timeout=3000",
            },
        )
    )

    @contextmanager
    def actor(name="staff", tenant="tenant"):
        with identity_session(
            "https://w02.test",
            str(ids[name]),
            session_factory=sessionmaker(engines["IDENTITY"]),
        ) as lookup:
            choice = lookup.authorize_tenant(ids[tenant])
        with tenant_session(
            ids[tenant],
            authorization=choice,
            session_factory=sessionmaker(engines["APP"]),
        ) as db:
            yield db

    try:
        yield engines, config, ids, actor, worker
    finally:
        worker._factory.kw["bind"].dispose()


def test_mapped_identity_refuses_generic_owner_handle(credential_case):
    _, _, ids, actor, _ = credential_case
    with actor("owner") as db, pytest.raises(SecretRejected):
        ConnectionService(db).authorize_worker(ids["connection"], 1)


def test_delegated_handle_commits_single_use_redeem_and_rechecks_revocation(
    credential_case,
):
    from wso_core.tvt.credentials import CredentialProvider

    engines, _, ids, actor, worker = credential_case
    target = DomainTarget(
        "TVT", ids["identity"], ids["device"], ids["channel"], ids["store"]
    )
    with actor() as db:
        scope = authorize(db, target, "media.live")
        handle = CredentialProvider(db).with_handle(
            scope, "media.live", datetime.now(UTC) + timedelta(seconds=25)
        )
    lease = worker.with_secret(handle)
    assert lease.use(lambda secret: len(secret)) == 20
    with pytest.raises(SecretRejected):
        worker.with_secret(handle)
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.tvt_identity_grants SET revision=revision+1 WHERE id=:id"
            ),
            {"id": ids["grant"]},
        )
    with pytest.raises(SecretRejected):
        lease.use(lambda secret: pytest.fail("revoked callback executed"))


def issue(case, domain="TVT", purpose="media.live", seconds=25, name="staff"):
    from wso_core.tvt.credentials import CredentialProvider

    _, _, ids, actor, _ = case
    target = (
        DomainTarget(
            "TVT", ids["identity"], ids["device"], ids["channel"], ids["store"]
        )
        if domain == "TVT"
        else DomainTarget("TYCO", ids["tyco_identity"], panel_id=ids["panel"])
    )
    with actor(name) as db:
        return CredentialProvider(db).with_handle(
            authorize(db, target, purpose),
            purpose,
            datetime.now(UTC) + timedelta(seconds=seconds),
        )


def test_tyco_has_distinct_authority_and_owner_requires_explicit_grant(credential_case):
    engines, _, ids, _actor, worker = credential_case
    handle = issue(credential_case, "TYCO", "panel.read")
    assert worker.with_secret(handle).use(len) == 20
    from wso_core.tvt.authorization import AuthorizationDenied

    with pytest.raises(AuthorizationDenied):
        issue(credential_case, name="owner")
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO public.store_memberships(tenant_id,user_id,store_id) VALUES(:tenant,:owner,:store)"
            ),
            ids,
        )
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_identity_grants(id,tenant_id,identity_id,actor_id,action,link_id,revision,expires_at) SELECT gen_random_uuid(),tenant_id,identity_id,:owner,action,link_id,revision,expires_at FROM wso_private.tvt_identity_grants WHERE id=:grant"
            ),
            ids,
        )
    assert worker.with_secret(issue(credential_case, name="owner")).use(len) == 20


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM public.store_memberships WHERE user_id=:staff",
        "UPDATE public.memberships SET role='MANAGER' WHERE user_id=:staff",
        "UPDATE public.stores SET active=false WHERE id=:store",
        "UPDATE wso_private.tvt_identities SET active=false WHERE id=:identity",
        "UPDATE wso_private.tvt_device_links SET active=false WHERE id=:device",
        "UPDATE wso_private.tvt_channels SET active=false WHERE id=:channel",
        "UPDATE wso_private.tvt_device_store_links SET revision=revision+1 WHERE id=:link",
        "UPDATE wso_private.tvt_upstream_grants SET verified=false WHERE identity_id=:identity",
        "UPDATE wso_private.tvt_capability_snapshots SET revision=revision+1 WHERE identity_id=:identity",
        "UPDATE public.connections SET generation=generation+1 WHERE id=:connection",
        "UPDATE public.connections SET status='DISCONNECTED' WHERE id=:connection",
        "UPDATE wso_private.connection_secrets SET version_id=gen_random_uuid() WHERE connection_id=:connection",
    ],
)
def test_every_current_authority_fence_denies_redeem_and_use(credential_case, mutation):
    engines, _, ids, _, worker = credential_case
    pending = issue(credential_case)
    lease = worker.with_secret(issue(credential_case))
    with engines["ADMIN"].begin() as db:
        db.execute(text(mutation), ids)
    with pytest.raises(SecretRejected):
        worker.with_secret(pending)
    with pytest.raises(SecretRejected):
        lease.use(lambda secret: pytest.fail("invalidated callback executed"))


def test_scope_forgery_wrong_purpose_and_foreign_actor_denied(credential_case):
    import json
    from dataclasses import asdict, replace

    from wso_core.tvt.credentials import CredentialProvider

    _, _, ids, actor, _ = credential_case
    target = DomainTarget(
        "TVT", ids["identity"], ids["device"], ids["channel"], ids["store"]
    )
    with actor() as db:
        scope = authorize(db, target, "media.live")
        for purpose in ("account.login", "panel.read", "device.write", ""):
            with pytest.raises(SecretRejected):
                CredentialProvider(db).with_handle(
                    scope, purpose, datetime.now(UTC) + timedelta(seconds=25)
                )
        expected = asdict(scope._facts)
        expected.update(expected.pop("target"))
        for change in (
            {"channel_id": ids["sibling_channel"]},
            {"channel_id": None},
            {"store_id": ids["sibling_store"]},
            {"store_id": ids["foreign_store"]},
            {"identity_id": ids["foreign_identity"]},
            {"actor_id": ids["owner"]},
            {"grant_revision": 999},
            {"domain": "TYCO"},
        ):
            assert (
                db.execute(
                    text(
                        "SELECT public.wso_issue_domain_connection_handle(CAST(:e AS jsonb),'media.live',clock_timestamp()+interval '25 seconds')"
                    ),
                    {
                        "e": json.dumps(
                            {**expected, **change},
                            default=lambda x: (
                                x.isoformat() if isinstance(x, datetime) else str(x)
                            ),
                        )
                    },
                ).scalar_one()
                is None
            )
        with pytest.raises(SecretRejected):
            CredentialProvider(db).with_handle(
                replace(scope, actor_id=ids["owner"]),
                "media.live",
                datetime.now(UTC) + timedelta(seconds=25),
            )
    with actor("owner") as db, pytest.raises(SecretRejected):
        CredentialProvider(db).with_handle(
            scope, "media.live", datetime.now(UTC) + timedelta(seconds=25)
        )


def test_deadline_fact_expiry_rollback_and_parallel_replay(credential_case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from wso_core.tvt.credentials import CredentialProvider

    engines, _, ids, actor, worker = credential_case
    h = issue(credential_case, seconds=100)
    with engines["ADMIN"].connect() as db:
        seconds = db.execute(
            text(
                "SELECT extract(epoch FROM expires_at-clock_timestamp()) FROM wso_private.connection_handles WHERE digest=sha256(convert_to(:h,'UTF8'))"
            ),
            {"h": h},
        ).scalar_one()
        assert 0 < seconds <= 30
    barrier = Barrier(2)

    def redeem():
        barrier.wait(timeout=5)
        try:
            return worker.with_secret(h)
        except SecretRejected:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _: redeem(), range(2)))
    assert sum(x is not None for x in leases) == 1
    lease = next(x for x in leases if x is not None)

    def fail_callback(secret):
        raise ValueError("synthetic callback failure")

    with pytest.raises(ValueError):
        lease.use(fail_callback)
    with pytest.raises(SecretRejected):
        worker.with_secret(h)
    assert lease.use(len) == 20
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.tvt_identity_grants SET expires_at=clock_timestamp()+interval '5 seconds' WHERE id=:grant"
            ),
            ids,
        )
    clipped = issue(credential_case)
    with engines["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT h.expires_at=g.expires_at FROM wso_private.connection_handles h JOIN wso_private.tvt_identity_grants g ON g.id=:grant WHERE digest=sha256(convert_to(:h,'UTF8'))"
            ),
            {**ids, "h": clipped},
        ).scalar_one()
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.connection_handles SET expires_at=clock_timestamp()-interval '1 second' WHERE digest=sha256(convert_to(:h,'UTF8'))"
            ),
            {"h": clipped},
        )
    with pytest.raises(SecretRejected):
        worker.with_secret(clipped)
    target = DomainTarget(
        "TVT", ids["identity"], ids["device"], ids["channel"], ids["store"]
    )
    with actor() as db:
        for deadline in (
            datetime.now(UTC) - timedelta(seconds=1),
            datetime.now(UTC).replace(tzinfo=None),
        ):
            with pytest.raises(SecretRejected):
                CredentialProvider(db).with_handle(
                    authorize(db, target, "media.live"), "media.live", deadline
                )


def test_revocation_waits_for_authorized_callback_then_denies(credential_case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    engines, _, ids, _, worker = credential_case
    lease = worker.with_secret(issue(credential_case))
    entered, release, started, finished = Event(), Event(), Event(), Event()

    def callback(secret):
        entered.set()
        assert release.wait(3)
        return len(secret)

    def revoke():
        started.set()
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_identity_grants SET revision=revision+1 WHERE id=:grant"
                ),
                ids,
            )
        finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        use = pool.submit(lease.use, callback)
        assert entered.wait(3)
        revoke_future = pool.submit(revoke)
        assert started.wait(3)
        try:
            assert database_has_blocked_lock(engines["ADMIN"])
            assert not finished.is_set()
        finally:
            release.set()
        assert use.result(timeout=4) == 20
        revoke_future.result(timeout=4)
    with pytest.raises(SecretRejected):
        lease.use(lambda secret: pytest.fail("revoked callback"))


def test_legacy_unmapped_owner_survives_and_mapping_invalidates_old_handles(
    credential_case,
):
    engines, _, ids, actor, worker = credential_case
    from uuid import uuid4

    ids = {**ids, "connection": ids["legacy_connection"], "identity": uuid4()}
    with actor("owner") as db:
        h = ConnectionService(db).authorize_worker(ids["connection"], 1)
        pending = ConnectionService(db).authorize_worker(ids["connection"], 1)
    lease = worker.with_secret(h)
    assert lease.use(len) == 20
    with actor() as db, pytest.raises(SecretRejected):
        ConnectionService(db).authorize_worker(ids["connection"], 1)
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.tvt_identities(id,tenant_id,connection_id,region,brand) VALUES(:identity,:tenant,:connection,'test','test')"
            ),
            ids,
        )
    with pytest.raises(SecretRejected):
        worker.with_secret(pending)
    with pytest.raises(SecretRejected):
        lease.use(lambda secret: pytest.fail("legacy mapped callback"))


def test_mapping_insertion_waits_for_legacy_callback(credential_case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    engines, _, ids, actor, worker = credential_case
    from uuid import uuid4

    ids = {**ids, "connection": ids["legacy_connection"], "identity": uuid4()}
    with actor("owner") as db:
        h = ConnectionService(db).authorize_worker(ids["connection"], 1)
    lease = worker.with_secret(h)
    entered, release, started, finished = Event(), Event(), Event(), Event()

    def callback(secret):
        entered.set()
        assert release.wait(3)
        return len(secret)

    def mapping():
        started.set()
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "INSERT INTO wso_private.tvt_identities(id,tenant_id,connection_id,region,brand) VALUES(:identity,:tenant,:connection,'test','test')"
                ),
                ids,
            )
        finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        use = pool.submit(lease.use, callback)
        assert entered.wait(3)
        mapped = pool.submit(mapping)
        assert started.wait(3)
        try:
            assert database_has_blocked_lock(engines["ADMIN"])
            assert not finished.is_set()
        finally:
            release.set()
        assert use.result(timeout=4) == 20
        mapped.result(timeout=4)
    with pytest.raises(SecretRejected):
        lease.use(lambda secret: pytest.fail("mapped callback"))


def test_migration_roundtrip_preserves_foundation_rows_functions_and_acls(
    disposable_domain_db,
):
    from tests.integration.test_tvt_domain_scope import foundation_contract

    engines, config = disposable_domain_db
    ids = seed_foundation(engines["ADMIN"])
    command.upgrade(config, "0004_tvt_domain")
    seed_domain(engines["ADMIN"], ids)
    with engines["ADMIN"].connect() as db:
        baseline = foundation_contract(db)
        rows = db.execute(text("SELECT * FROM public.connections ORDER BY id")).all()
    command.upgrade(config, "0005_tvt_credentials")
    command.downgrade(config, "0004_tvt_domain")
    with engines["ADMIN"].connect() as db:
        after = foundation_contract(db)
        # PostgreSQL retains tombstone attributes after DROP COLUMN; compare
        # all surviving ACLs, not those storage-only catalog tombstones.
        dropped = set(
            db.execute(
                text("SELECT attname FROM pg_attribute WHERE attisdropped")
            ).scalars()
        )
        assert after[0] == baseline[0] and after[2] == baseline[2]
        assert [row for row in after[1] if row[3] not in dropped] == baseline[1]
        assert (
            db.execute(text("SELECT * FROM public.connections ORDER BY id")).all()
            == rows
        )
        assert (
            db.execute(
                text("SELECT count(*) FROM wso_private.tvt_identities")
            ).scalar_one()
            == 2
        )
    command.upgrade(config, "0005_tvt_credentials")
    with engines["ADMIN"].connect() as db:
        assert (
            db.execute(text("SELECT * FROM public.connections ORDER BY id")).all()
            == rows
        )
        assert db.execute(
            text(
                "SELECT c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wso_private' AND c.relname='domain_credential_capabilities'"
            )
        ).one() == (True, True, "wso_domain_owner")


def test_raw_roles_cannot_mint_context_read_caps_secrets_or_bypass_validator(
    credential_case,
):
    import json

    from sqlalchemy.exc import DBAPIError

    engines, _, ids, actor, worker = credential_case
    for factory in (sessionmaker(engines["APP"]), worker._factory):
        for sql in (
            "SELECT * FROM wso_private.domain_credential_capabilities",
            "SELECT * FROM wso_private.connection_secrets",
            "SELECT wso_private.wso_validate_domain_credential(NULL,NULL,NULL,NULL,NULL,NULL)",
            "SELECT wso_private.credential_original_wso_use_connection_lease('x')",
            "SET ROLE wso_domain_owner",
        ):
            with factory.begin() as db, pytest.raises(DBAPIError) as error:
                db.execute(text(sql))
            assert error.value.orig.sqlstate == "42501"
    with actor() as db:
        expected = db.execute(
            text(
                "SELECT to_jsonb(f) FROM public.wso_authorize_domain('TVT',:identity,:device,:channel,:store,NULL,'media.live') f"
            ),
            ids,
        ).scalar_one()
        assert expected["actor_id"] == str(ids["staff"])
        parameters = {"expected": json.dumps(expected)}
        # Control: the exact facts and payload succeed with consumed context.
        assert db.execute(
            text(
                "SELECT public.wso_issue_domain_connection_handle(CAST(:expected AS jsonb),'media.live',clock_timestamp()+interval '30 seconds') IS NOT NULL"
            ),
            parameters,
        ).scalar_one()
    with sessionmaker(engines["APP"]).begin() as db:
        for key, value in (
            ("app.tenant_id", ids["tenant"]),
            ("app.user_id", ids["staff"]),
            ("app.role", "STAFF"),
        ):
            db.execute(
                text("SELECT set_config(:k,:v,true)"), {"k": key, "v": str(value)}
            )
        assert (
            db.execute(
                text(
                    "SELECT public.wso_issue_domain_connection_handle(CAST(:expected AS jsonb),'media.live',clock_timestamp()+interval '30 seconds')"
                ),
                parameters,
            ).scalar_one()
            is None
        )


def test_job_step_exclusion_and_domain_metadata_cannot_fall_back(credential_case):
    from wso_core.tvt.credentials import CredentialProvider
    from wso_core.worker import JOB_STEP_ACTIVE

    engines, _, ids, actor, worker = credential_case
    h = issue(credential_case)
    lease = worker.with_secret(issue(credential_case))
    token = JOB_STEP_ACTIVE.set(True)
    try:
        with pytest.raises(SecretRejected):
            worker.with_secret(h)
        with pytest.raises(SecretRejected):
            lease.use(lambda secret: pytest.fail("job-step callback"))
        with actor() as db:
            scope = authorize(
                db,
                DomainTarget(
                    "TVT", ids["identity"], ids["device"], ids["channel"], ids["store"]
                ),
                "media.live",
            )
            with pytest.raises(SecretRejected):
                CredentialProvider(db).with_handle(
                    scope, "media.live", datetime.now(UTC) + timedelta(seconds=25)
                )
    finally:
        JOB_STEP_ACTIVE.reset(token)
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.domain_credential_capabilities SET facts=facts-'grant_revision'"
            )
        )
    with pytest.raises(SecretRejected):
        worker.with_secret(h)
    with pytest.raises(SecretRejected):
        lease.use(lambda secret: pytest.fail("malformed cap callback"))


@pytest.mark.parametrize(
    "purpose,domain",
    [("device.read", "TVT"), ("account.read", "TVT"), ("account.read", "TYCO")],
)
def test_read_purposes_use_exact_post_login_scope(credential_case, purpose, domain):
    from wso_core.tvt.credentials import CredentialProvider

    engines, _, ids, actor, worker = credential_case
    identity = ids["identity"] if domain == "TVT" else ids["tyco_identity"]
    if purpose == "account.read":
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    f"INSERT INTO wso_private.{domain.lower()}_identity_grants(id,tenant_id,identity_id,actor_id,action,revision,expires_at) VALUES(gen_random_uuid(),:tenant,:identity,:staff,'account.read',1,clock_timestamp()+interval '1 hour')"
                ),
                {**ids, "identity": identity},
            )
            for suffix in ("upstream_grants", "capability_snapshots"):
                db.execute(
                    text(
                        f"INSERT INTO wso_private.{domain.lower()}_{suffix}(id,tenant_id,identity_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(gen_random_uuid(),:tenant,:identity,'account.read',true,1,1,clock_timestamp(),clock_timestamp()+interval '1 hour')"
                    ),
                    {**ids, "identity": identity},
                )
        target = DomainTarget(domain, identity)
    else:
        target = DomainTarget("TVT", identity, ids["device"], store_id=ids["store"])
    with actor() as db:
        h = CredentialProvider(db).with_handle(
            authorize(db, target, purpose),
            purpose,
            datetime.now(UTC) + timedelta(seconds=25),
        )
    assert worker.with_secret(h).use(len) == 20


def test_expiry_is_rechecked_after_membership_lock_wait(credential_case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    engines, _, ids, _, worker = credential_case
    lease = worker.with_secret(issue(credential_case, seconds=1))
    started = Event()

    def use():
        started.set()
        with pytest.raises(SecretRejected):
            lease.use(lambda secret: pytest.fail("expired waiting callback"))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "SELECT 1 FROM public.memberships WHERE tenant_id=:tenant AND user_id=:staff FOR UPDATE"
                ),
                ids,
            )
            future = pool.submit(use)
            assert started.wait(3)
            assert database_has_blocked_lock(engines["ADMIN"])
            # Actual server clock crosses the deadline while the worker waits.
            db.execute(text("SELECT pg_sleep(1.1)"))
        future.result(timeout=4)


def test_generic_job_issuance_refuses_mapped_and_preserves_unmapped_generation_fence(
    credential_case,
):
    from uuid import uuid4

    engines, _, ids, actor, worker = credential_case
    with actor("owner") as db:
        job = db.execute(
            text(
                "SELECT public.wso_enqueue_job(:tenant,'TENANT',NULL,'IMPORT',1,jsonb_build_object('schema_version',1,'import_id',CAST(:import_id AS text),'connection_id',CAST(:connection AS text)),'credential-diagnostic')"
            ),
            {**ids, "import_id": uuid4()},
        ).scalar_one()
    synthetic_job_token = "a" * 64
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE public.jobs SET state='RUNNING',lease_generation=1,lease_digest=sha256(convert_to(:token,'UTF8')),lease_expires_at=clock_timestamp()+interval '30 seconds' WHERE id=:job"
            ),
            {"token": synthetic_job_token, "job": job},
        )
    job_engine = create_engine(
        make_url(os.environ["WSO_TEST_JOB_DATABASE_URL"]).set(
            database=engines["ADMIN"].url.database
        ),
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c lock_timeout=3000",
        },
    )

    def job_handle():
        with job_engine.begin() as db:
            return db.execute(
                text(
                    "SELECT public.wso_issue_job_connection_handle(:job,:token,:connection)"
                ),
                {
                    "job": job,
                    "token": synthetic_job_token,
                    "connection": ids["connection"],
                },
            ).scalar_one()

    try:
        assert job_handle() is None
        with engines["ADMIN"].begin() as db:
            # Controlled fixture switches the job connection before issuing any
            # credential; the genuine legacy connection has no mapping history.
            db.execute(
                text(
                    "UPDATE public.job_connections SET connection_id=:legacy_connection WHERE job_id=:job"
                ),
                {**ids, "job": job},
            )
        ids = {**ids, "connection": ids["legacy_connection"]}
        lease = worker.with_secret(job_handle())
        pending = job_handle()
        assert lease.use(len) == 20
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE public.jobs SET lease_generation=lease_generation+1 WHERE id=:job"
                ),
                {"job": job},
            )
        with pytest.raises(SecretRejected):
            worker.with_secret(pending)
        with pytest.raises(SecretRejected):
            lease.use(lambda secret: pytest.fail("stale job callback"))
    finally:
        job_engine.dispose()


@pytest.mark.parametrize(
    "patch",
    [
        "'{\"member\":false}'",
        "'{\"connection_generation\":999}'",
        "'{\"linked\":false}'",
        "'{\"unexpected\":true}'",
    ],
)
def test_malformed_capability_claims_cannot_authorize(credential_case, patch):
    engines, _, _, _, worker = credential_case
    pending = issue(credential_case)
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.domain_credential_capabilities SET facts=facts || CAST(:patch AS jsonb)"
            ),
            {"patch": patch[1:-1]},
        )
    with pytest.raises(SecretRejected):
        worker.with_secret(pending)


def database_has_blocked_lock(admin):
    """Observe actual PostgreSQL waiting, not merely thread scheduling."""
    import time

    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        with admin.connect() as db:
            if db.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND wait_event_type='Lock')"
                )
            ).scalar_one():
                return True
        time.sleep(0.01)
    return False


def test_removed_identity_cannot_reopen_generic_owner_or_job_credentials(
    credential_case,
):
    engines, _, ids, actor, _ = credential_case
    with engines["ADMIN"].begin() as db:
        db.execute(
            text("DELETE FROM wso_private.tvt_identities WHERE id=:identity"), ids
        )
    with actor("owner") as db, pytest.raises(SecretRejected):
        ConnectionService(db).authorize_worker(ids["connection"], 1)


def test_missing_mapping_record_cannot_hide_existing_identity(credential_case):
    engines, _, ids, actor, _ = credential_case
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "DELETE FROM wso_private.domain_credential_connections WHERE connection_id=:connection"
            ),
            ids,
        )
    with actor("owner") as db, pytest.raises(SecretRejected):
        ConnectionService(db).authorize_worker(ids["connection"], 1)


@pytest.mark.parametrize("path", ["pending_handle", "existing_lease"])
def test_repeatable_snapshot_cannot_miss_independently_committed_mapping(
    credential_case, path
):
    from uuid import uuid4

    engines, _, ids, actor, worker = credential_case
    with actor("owner") as db:
        handle = ConnectionService(db).authorize_worker(ids["legacy_connection"], 1)
    lease_token = "b" * 64
    if path == "existing_lease":
        with worker._factory.begin() as db:
            assert db.execute(
                text("SELECT public.wso_redeem_connection_handle(:handle,:lease)"),
                {"handle": handle, "lease": lease_token},
            ).scalar_one()
    # Connection one establishes the older snapshot before connection two maps.
    with worker._factory.begin() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        assert (
            db.execute(
                text("SELECT current_setting('transaction_isolation')")
            ).scalar_one()
            == "repeatable read"
        )
        db.execute(text("SELECT txid_current_snapshot()"))
        with engines["ADMIN"].begin() as mapper:
            mapper.execute(
                text(
                    "INSERT INTO wso_private.tvt_identities(id,tenant_id,connection_id,region,brand) VALUES(:identity,:tenant,:connection,'test','test')"
                ),
                {
                    "identity": uuid4(),
                    "tenant": ids["tenant"],
                    "connection": ids["legacy_connection"],
                },
            )
        # Never materialize or print ciphertext even during the expected RED.
        if path == "pending_handle":
            denied = not db.execute(
                text("SELECT public.wso_redeem_connection_handle(:handle,:lease)"),
                {"handle": handle, "lease": lease_token},
            ).scalar_one()
        else:
            denied = not db.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM public.wso_use_connection_lease(:lease))"
                ),
                {"lease": lease_token},
            ).scalar_one()
        assert denied, (
            "stale snapshot admitted credential authority after mapping committed"
        )


@pytest.mark.parametrize(
    "isolation", ["REPEATABLE READ", "SERIALIZABLE", "READ UNCOMMITTED"]
)
def test_generic_entrypoints_fail_closed_before_authority_in_unsupported_isolation(
    credential_case, isolation
):
    from uuid import uuid4

    engines, _, ids, actor, worker = credential_case
    with actor("owner") as db:
        pending = ConnectionService(db).authorize_worker(ids["legacy_connection"], 1)
        for_lease = ConnectionService(db).authorize_worker(ids["legacy_connection"], 1)
    lease_token = "c" * 64
    with worker._factory.begin() as db:
        assert db.execute(
            text("SELECT public.wso_redeem_connection_handle(:handle,:lease)"),
            {"handle": for_lease, "lease": lease_token},
        ).scalar_one()
    with worker._factory.begin() as db:
        db.connection(execution_options={"isolation_level": isolation})
        redeemed = db.execute(
            text("SELECT public.wso_redeem_connection_handle(:handle,:lease)"),
            {"handle": pending, "lease": "d" * 64},
        ).scalar_one()
        assert redeemed is False
        assert (
            db.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM public.wso_use_connection_lease(:lease))"
                ),
                {"lease": lease_token},
            ).scalar_one()
            is False
        )
    with engines["APP"].connect().execution_options(isolation_level=isolation) as db:
        assert db.execute(
            text("SELECT public.wso_issue_connection_handle(:connection,1) IS NULL"),
            {"connection": ids["legacy_connection"]},
        ).scalar_one()
    job_engine = create_engine(
        make_url(os.environ["WSO_TEST_JOB_DATABASE_URL"]).set(
            database=engines["ADMIN"].url.database
        ),
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c lock_timeout=3000",
        },
    )
    try:
        with job_engine.connect().execution_options(isolation_level=isolation) as db:
            # Unsupported isolation is denied before job admission is attempted.
            assert db.execute(
                text(
                    "SELECT public.wso_issue_job_connection_handle(:job,'invalid',:connection) IS NULL"
                ),
                {"job": uuid4(), "connection": ids["legacy_connection"]},
            ).scalar_one()
    finally:
        job_engine.dispose()
