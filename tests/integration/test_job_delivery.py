"""Atomic queueing and fenced delivery using actual PostgreSQL."""

import importlib.util
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from wso_api.auth import WebSession
from wso_api.stores.router import require_tenant
from wso_contracts.jobs import ImportJobPayload, RegistrationJobPayload
from wso_contracts.models import TenantScope

pytest_plugins = ["tests.auth_support", "tests.integration.test_connection_secrets"]


@pytest.fixture
def job_case(auth_case):
    if not all(
        os.getenv(f"WSO_TEST_{role}_DATABASE_URL")
        for role in ("WORKER", "DISPATCH", "JOB")
    ):
        pytest.skip("requires explicit PostgreSQL worker and dispatcher role URLs")
    try:
        yield auth_case
    finally:
        with auth_case[3].begin() as db:
            db.execute(
                text("DELETE FROM jobs WHERE tenant_id=ANY(:ids)"),
                {"ids": [auth_case[1]["a"], auth_case[1]["b"]]},
            )


@contextmanager
def scope(case, tenant="a", actor="owner"):
    ids = case[1]
    principal = WebSession(
        "https://issuer.test",
        str(ids[actor]),
        ids[actor],
        "",
        datetime.now(UTC) + timedelta(minutes=5),
    )
    with require_tenant(
        "stores:read", ids[tenant], service=case[2], principal=principal
    ) as authorized:
        yield authorized


def enqueue(case, key="request", payload=None, kind="IMPORT", registry=None):
    from wso_core.jobs import JobService

    with scope(case) as authorized:
        service = JobService(
            authorized.session, **({"registry": registry} if registry else {})
        )
        return service.enqueue(
            TenantScope(tenant_id=case[1]["a"]),
            kind,
            payload or ImportJobPayload(import_id=uuid4()),
            key,
        )


def test_job_service_exists():
    assert importlib.util.find_spec("wso_core.jobs") is not None


def test_tenant_import_without_store_is_queueable(job_case):
    from wso_core.jobs import JobService

    with job_case[3].begin() as db:
        db.execute(
            text("DELETE FROM store_memberships WHERE tenant_id=:t"),
            {"t": job_case[1]["a"]},
        )
        db.execute(
            text("DELETE FROM stores WHERE tenant_id=:t"), {"t": job_case[1]["a"]}
        )
    job = enqueue(job_case)
    assert job.scope.scope_kind == "TENANT" and job.state == "QUEUED"
    with job_case[3].connect() as db:
        for table in ["jobs", "outbox", "wso_private.dispatch_ready"]:
            column = "id" if table == "jobs" else "job_id"
            assert (
                db.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {column}=:j"),
                    {"j": job.id},
                ).scalar_one()
                == 1
            )
    with scope(job_case) as authorized:
        assert JobService(authorized.session).get(job.id) == job


def test_registration_rejects_tenant_only_scope(job_case):
    from wso_core.jobs import JobFailure

    with pytest.raises(JobFailure) as rejected:
        enqueue(
            job_case,
            kind="REGISTRATION",
            payload=RegistrationJobPayload(
                registration_id=uuid4(), connection_id=uuid4()
            ),
        )
    assert rejected.value.status == 422


def test_idempotency_same_payload_returns_original_changed_payload_conflicts(job_case):
    from wso_core.jobs import JobFailure

    payload = ImportJobPayload(import_id=uuid4())
    job = enqueue(job_case, payload=payload)
    assert enqueue(job_case, payload=payload).id == job.id
    with pytest.raises(JobFailure) as rejected:
        enqueue(job_case)
    assert rejected.value.status == 409


def test_unknown_kind_and_payload_are_rejected(job_case):
    from wso_core.jobs import JobFailure

    with pytest.raises(JobFailure):
        enqueue(job_case, kind="EXECUTE")
    with pytest.raises(JobFailure):
        enqueue(job_case, payload={"schema_version": 1, "password": "never-store"})


def test_application_transaction_rollback_removes_all_delivery_rows(job_case):
    from wso_core.jobs import JobService

    with pytest.raises(RuntimeError), scope(job_case) as authorized:
        job = JobService(authorized.session).enqueue(
            TenantScope(tenant_id=job_case[1]["a"]),
            "IMPORT",
            ImportJobPayload(import_id=uuid4()),
            "rollback",
        )
        raise RuntimeError("controlled rollback")
    with job_case[3].connect() as db:
        for table in ["jobs", "outbox", "wso_private.dispatch_ready"]:
            column = "id" if table == "jobs" else "job_id"
            assert (
                db.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {column}=:j"),
                    {"j": job.id},
                ).scalar_one()
                == 0
            )


def test_worker_claim_interface_exists():
    assert importlib.util.find_spec("wso_core.worker") is not None


def test_unavailable_import_handler_fails_honestly(job_case):
    from wso_core.dispatch import Dispatcher
    from wso_core.worker import JobWorker

    job = enqueue(job_case)
    dispatcher = Dispatcher(
        os.environ["WSO_TEST_DISPATCH_DATABASE_URL"], lambda *_: None
    )
    worker = JobWorker(os.environ["WSO_TEST_JOB_DATABASE_URL"])
    reference = next(r for r in dispatcher.claim_dispatch_batch() if r.job_id == job.id)
    worker.execute(reference)
    with job_case[3].connect() as db:
        row = db.execute(
            text("SELECT state,failure_code FROM jobs WHERE id=:j"), {"j": job.id}
        ).one()
        assert row.state == "FAILED" and row.failure_code == "HANDLER_UNAVAILABLE"
    worker.execute(reference)
    worker.engine.dispose()
    dispatcher.engine.dispose()


@pytest.fixture
def delivery(job_case):
    from wso_core.dispatch import Dispatcher
    from wso_core.worker import JobWorker

    dispatcher = Dispatcher(
        os.environ["WSO_TEST_DISPATCH_DATABASE_URL"], lambda *_: None
    )
    worker = JobWorker(os.environ["WSO_TEST_JOB_DATABASE_URL"])
    try:
        yield dispatcher, worker
    finally:
        dispatcher.engine.dispose()
        worker.engine.dispose()


def reference_for(delivery, job):
    return next(r for r in delivery[0].claim_dispatch_batch() if r.job_id == job.id)


@pytest.mark.parametrize(
    "changed", ["tenant_id", "kind", "outbox_id", "lease_generation"]
)
def test_forged_reference_cannot_change_legitimate_job(job_case, delivery, changed):
    from wso_core.jobs import JobFailure

    job = enqueue(job_case)
    reference = reference_for(delivery, job)
    forged = reference.model_copy(
        update={
            changed: "FORGED"
            if changed == "kind"
            else 999999
            if changed == "lease_generation"
            else uuid4()
        }
    )
    with pytest.raises(JobFailure):
        delivery[1].claim(job.id, reference=forged)
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT state FROM jobs WHERE id=:j"), {"j": job.id}
            ).scalar_one()
            == "QUEUED"
        )
    assert delivery[1].claim(job.id, reference=reference) is not None


def test_active_duplicate_claim_is_noop_and_cancel_prevents_next_step(
    job_case, delivery
):
    from wso_core.jobs import JobFailure, JobService

    job = enqueue(job_case)
    reference = reference_for(delivery, job)
    worker = delivery[1]
    lease = worker.claim(job.id, reference=reference)
    assert lease is not None
    assert worker.claim(job.id, reference=reference) is None
    with worker.step(lease) as step:
        assert step.session.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 1
    with scope(job_case) as authorized:
        assert JobService(authorized.session).cancel(job.id).state == "CANCELLED"
    with pytest.raises(JobFailure), worker.step(lease):
        pytest.fail("cancelled step entered")
    with pytest.raises(JobFailure):
        worker.complete(job.id, lease.token, {})


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE memberships SET role='STAFF' WHERE tenant_id=:t AND user_id=:u",
        "UPDATE tenants SET job_generation=job_generation+1 WHERE id=:t",
    ],
)
def test_authority_revocation_between_steps_invalidates_original_lease(
    job_case, delivery, mutation
):
    from wso_core.jobs import JobFailure

    job = enqueue(job_case)
    reference = reference_for(delivery, job)
    worker = delivery[1]
    lease = worker.claim(job.id, reference=reference)
    with worker.step(lease):
        pass
    with job_case[3].begin() as db:
        db.execute(text(mutation), {"t": job_case[1]["a"], "u": job_case[1]["owner"]})
        db.execute(
            text(
                "UPDATE memberships SET role='OWNER' WHERE tenant_id=:t AND user_id=:u"
            ),
            {"t": job_case[1]["a"], "u": job_case[1]["owner"]},
        )
    with pytest.raises(JobFailure), worker.step(lease):
        pytest.fail("revoked authority restored")
    assert worker.claim(job.id, reference=reference) is None
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT state FROM jobs WHERE id=:j"), {"j": job.id}
            ).scalar_one()
            == "CANCELLED"
        )


def test_published_reference_remains_rediscoverable_after_broker_loss(
    job_case, delivery
):
    job = enqueue(job_case)
    reference = reference_for(delivery, job)
    dispatcher = delivery[0]
    dispatcher.ack(reference.outbox_id, reference.lease_generation)
    with job_case[3].begin() as db:
        row = db.execute(
            text(
                "SELECT state,last_published_at FROM wso_private.dispatch_ready WHERE job_id=:j"
            ),
            {"j": job.id},
        ).one()
        assert row.state == "WAITING" and row.last_published_at is not None
        assert (
            db.execute(
                text("SELECT completed_at FROM outbox WHERE job_id=:j"), {"j": job.id}
            ).scalar_one()
            is None
        )
        db.execute(
            text(
                "UPDATE wso_private.dispatch_ready SET due_at=clock_timestamp()-interval '1 second' WHERE job_id=:j"
            ),
            {"j": job.id},
        )
    newer = reference_for(delivery, job)
    assert newer.lease_generation > reference.lease_generation
    dispatcher.ack(reference.outbox_id, reference.lease_generation)
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT state FROM wso_private.dispatch_ready WHERE job_id=:j"),
                {"j": job.id},
            ).scalar_one()
            == "LEASED"
        )


def test_dispatcher_discovers_two_tenants_without_payload_access(job_case, delivery):
    from wso_core.jobs import JobService

    a = enqueue(job_case)
    with job_case[3].begin() as db:
        db.execute(
            text(
                "UPDATE memberships SET role='OWNER' WHERE tenant_id=:t AND user_id=:u"
            ),
            {"t": job_case[1]["b"], "u": job_case[1]["foreign_user"]},
        )
    with scope(job_case, "b", "foreign_user") as authorized:
        b = JobService(authorized.session).enqueue(
            TenantScope(tenant_id=job_case[1]["b"]),
            "IMPORT",
            ImportJobPayload(import_id=uuid4()),
            "request",
        )
    refs = delivery[0].claim_dispatch_batch()
    selected = [r for r in refs if r.job_id in {a.id, b.id}]
    assert {r.tenant_id for r in selected} == {job_case[1]["a"], job_case[1]["b"]}
    assert all(
        set(r.model_dump())
        == {
            "schema_version",
            "job_id",
            "outbox_id",
            "tenant_id",
            "kind",
            "lease_generation",
        }
        for r in selected
    )
    for r in selected:
        lease = delivery[1].claim(r.job_id, reference=r)
        with delivery[1].step(lease) as step:
            rows = step.session.execute(text("SELECT id,tenant_id FROM jobs")).all()
            assert (
                len(rows) == 1
                and rows[0].id == r.job_id
                and rows[0].tenant_id == r.tenant_id
            )
            step.complete({})


def test_cross_tenant_connection_id_is_not_found_without_partial_writes(job_case):
    from wso_core.jobs import JobFailure

    connection = uuid4()
    with job_case[3].begin() as db:
        db.execute(
            text(
                "INSERT INTO connections(id,tenant_id,kind,alias,site,status,generation) VALUES(:c,:t,'TVT_ACCOUNT','fixture','fixture','NOT_VERIFIED',1)"
            ),
            {"c": connection, "t": job_case[1]["b"]},
        )
    try:
        with pytest.raises(JobFailure) as denied:
            enqueue(
                job_case,
                payload=ImportJobPayload(import_id=uuid4(), connection_id=connection),
            )
        assert denied.value.status == 404
        with job_case[3].connect() as db:
            assert (
                db.execute(
                    text("SELECT count(*) FROM jobs WHERE tenant_id=:t"),
                    {"t": job_case[1]["a"]},
                ).scalar_one()
                == 0
            )
    finally:
        with job_case[3].begin() as db:
            db.execute(text("DELETE FROM connections WHERE id=:c"), {"c": connection})


def test_results_reject_secret_fields():
    from wso_core.jobs import JobFailure, bounded_json

    with pytest.raises(JobFailure):
        bounded_json({"nested": {"password": "never-display"}})


from tests.integration.test_connection_secrets import create_connection


@pytest.mark.parametrize("mutation", ["cancel", "role", "generation", "delete"])
def test_job_secret_capability_revalidates_every_use(
    job_case, connection_case, delivery, mutation
):
    from wso_core.jobs import JobService
    from wso_core.secrets import SecretRejected, WorkerSecretStore

    item = create_connection(connection_case).json()
    job = enqueue(
        job_case, payload=ImportJobPayload(import_id=uuid4(), connection_id=item["id"])
    )
    lease = delivery[1].claim(job.id, reference=reference_for(delivery, job))
    secretstore = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    handle = delivery[1].issue_connection_handle(lease, item["id"])
    secretlease = secretstore.with_secret(handle)
    assert secretlease.use(lambda data: b"password-canary-84726" in data)
    pending = delivery[1].issue_connection_handle(lease, item["id"])
    if mutation == "cancel":
        with scope(job_case) as authorized:
            JobService(authorized.session).cancel(job.id)
    else:
        with job_case[3].begin() as db:
            if mutation == "role":
                db.execute(
                    text(
                        "UPDATE memberships SET role='STAFF' WHERE tenant_id=:t AND user_id=:u"
                    ),
                    {"t": job_case[1]["a"], "u": job_case[1]["owner"]},
                )
            elif mutation == "generation":
                db.execute(
                    text("UPDATE connections SET generation=generation+1 WHERE id=:c"),
                    {"c": item["id"]},
                )
            else:
                db.execute(
                    text("DELETE FROM connections WHERE id=:c"), {"c": item["id"]}
                )
    with pytest.raises(SecretRejected):
        secretlease.use(lambda _: pytest.fail("revoked secret used"))
    with pytest.raises(SecretRejected):
        secretstore.with_secret(pending)


def test_wrong_connection_cannot_receive_job_handle(
    job_case, connection_case, delivery
):
    from wso_core.jobs import JobFailure

    first = create_connection(connection_case).json()
    second = create_connection(connection_case).json()
    job = enqueue(
        job_case, payload=ImportJobPayload(import_id=uuid4(), connection_id=first["id"])
    )
    lease = delivery[1].claim(job.id, reference=reference_for(delivery, job))
    with pytest.raises(JobFailure):
        delivery[1].issue_connection_handle(lease, second["id"])


def test_job_status_cancel_and_paginated_items_api(job_case, signing_key):
    from tests.auth_support import login

    job = enqueue(job_case)
    auth = login(job_case[0], signing_key, job_case[1], "owner")
    path = f"/api/v1/jobs/{job.id}"
    query = f"?tenant_id={job_case[1]['a']}"
    response = job_case[0].get(path + query)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "payload" not in response.json() and "lease" not in response.text
    with job_case[3].begin() as db:
        for key in ["001", "002", "003"]:
            db.execute(
                text(
                    "INSERT INTO job_items(tenant_id,job_id,item_key,state,attempt,lease_generation,result) VALUES(:t,:j,:key,'SUCCEEDED',1,1,'{}'::jsonb)"
                ),
                {"t": job_case[1]["a"], "j": job.id, "key": key},
            )
    page = job_case[0].get(path + "/items" + query + "&limit=2").json()
    assert [i["item_key"] for i in page["items"]] == ["001", "002"]
    last = (
        job_case[0]
        .get(path + "/items" + query + "&limit=2&cursor=" + page["next_cursor"])
        .json()
    )
    assert [i["item_key"] for i in last["items"]] == ["003"] and last[
        "next_cursor"
    ] is None
    assert (
        job_case[0].get(path + "/items" + query + "&cursor=forged").status_code == 422
    )
    assert job_case[0].get(path + "/items" + query + "&limit=101").status_code == 422
    assert job_case[0].post(path + "/cancel" + query).status_code == 403
    result = job_case[0].post(
        path + "/cancel" + query,
        headers={"Origin": "https://app.test", "X-CSRF-Token": auth["csrf_token"]},
    )
    assert result.status_code == 200 and result.json()["state"] == "CANCELLED"
    assert job_case[0].post("/api/v1/jobs" + query, json={}).status_code in {404, 405}


def test_raw_sql_cannot_persist_secret_payload_or_result(job_case, delivery):
    from sqlalchemy.exc import DBAPIError

    with scope(job_case) as authorized:
        with pytest.raises(DBAPIError) as rejected:
            authorized.session.execute(
                text(
                    "SELECT public.wso_enqueue_job(:t,'TENANT',NULL,'IMPORT',1,CAST(:payload AS jsonb),'raw-secret')"
                ),
                {
                    "t": job_case[1]["a"],
                    "payload": '{"schema_version":1,"import_id":null}',
                },
            )
        assert rejected.value.orig.sqlstate == "22023"
    job = enqueue(job_case)
    lease = delivery[1].claim(job.id, reference=reference_for(delivery, job))
    with pytest.raises(Exception) as rejected:
        delivery[1]._call(
            "SELECT public.wso_complete_job(:id,:token,'{\"password\":\"no-persist\"}'::jsonb,'SUCCEEDED',NULL)",
            job.id,
            lease.token,
        )
    assert getattr(rejected.value, "status", None) == 422


def test_item_updates_have_execution_fence(job_case, delivery):
    from wso_core.jobs import JobFailure

    job = enqueue(job_case)
    lease = delivery[1].claim(job.id, reference=reference_for(delivery, job))
    with delivery[1].step(lease) as step:
        assert hasattr(step, "record_item"), "worker must expose fenced item results"
        step.record_item("one", "SUCCEEDED", {"count": 1})
        step.complete({"count": 1})
    with pytest.raises(JobFailure), delivery[1].step(lease) as step:
        step.record_item("two", "SUCCEEDED", {})


def test_secret_issuance_cannot_wait_on_callers_active_job_step(
    job_case, connection_case, delivery
):
    from sqlalchemy import event
    from wso_core.jobs import JobFailure

    item = create_connection(connection_case).json()
    job = enqueue(
        job_case, payload=ImportJobPayload(import_id=uuid4(), connection_id=item["id"])
    )
    worker = delivery[1]
    lease = worker.claim(job.id, reference=reference_for(delivery, job))

    @event.listens_for(worker.engine, "connect")
    def timeout(dbapi_connection, _):
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET statement_timeout='500ms'")

    with worker.step(lease):
        with pytest.raises(JobFailure) as denied:
            worker.issue_connection_handle(lease, item["id"])
        assert denied.value.status == 403, (
            "nested credential issuance must reject before any second-connection lock wait"
        )


def test_delayed_job_issues_fresh_secret_after_original_handle_expires(
    job_case, connection_case, delivery
):
    from time import monotonic, sleep

    from wso_core.secrets import SecretRejected, WorkerSecretStore

    from tests.integration.test_connection_secrets import issue

    item = create_connection(connection_case).json()
    old = issue(connection_case, item)
    job = enqueue(
        job_case, payload=ImportJobPayload(import_id=uuid4(), connection_id=item["id"])
    )
    # Actual expiry: queueing never persists or renews a 30-second secret handle.
    deadline = monotonic() + 31
    while monotonic() < deadline:
        sleep(min(0.25, deadline - monotonic()))
    store = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    with pytest.raises(SecretRejected):
        store.with_secret(old)
    lease = delivery[1].claim(job.id, reference=reference_for(delivery, job))
    fresh = delivery[1].issue_connection_handle(lease, item["id"])
    assert fresh != old
    assert store.with_secret(fresh).use(lambda data: b"password-canary-84726" in data)


@pytest.fixture
def fast_timing(job_case):
    with job_case[3].begin() as db:
        previous = dict(
            db.execute(text("SELECT * FROM wso_private.job_settings")).mappings().one()
        )
        db.execute(
            text(
                "UPDATE wso_private.job_settings SET lease_seconds=2,step_seconds=1,dispatch_seconds=1,watchdog_seconds=1,retry_seconds=1"
            )
        )
    try:
        yield
    finally:
        with job_case[3].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.job_settings SET lease_seconds=:lease_seconds,step_seconds=:step_seconds,dispatch_seconds=:dispatch_seconds,watchdog_seconds=:watchdog_seconds,retry_seconds=:retry_seconds"
                ),
                previous,
            )


def test_expired_lease_cannot_heartbeat_complete_or_write_items(
    job_case, delivery, fast_timing
):
    from time import sleep

    from wso_core.jobs import JobFailure

    job = enqueue(job_case)
    reference = reference_for(delivery, job)
    worker = delivery[1]
    first = worker.claim(job.id, reference=reference)
    sleep(2.05)
    assert worker.claim(job.id, reference=reference) is None
    assert worker.claim(job.id, reference=reference) is None  # DB backoff enforced.
    sleep(1.05)
    second = worker.claim(job.id, reference=reference)
    assert second.generation > first.generation
    for operation in [
        lambda: worker.heartbeat(job.id, first.token),
        lambda: worker.complete(job.id, first.token, {}),
    ]:
        with pytest.raises(JobFailure):
            operation()
    with pytest.raises(JobFailure), worker.step(first) as step:
        step.record_item("stale", "SUCCEEDED", {})
    with worker.step(second) as step:
        step.record_item("actual", "SUCCEEDED", {})
        step.complete({"done": True})
    assert worker.claim(job.id, reference=reference) is None


def test_step_deadline_cannot_be_reset_by_completion(job_case, delivery, fast_timing):
    from time import sleep

    from wso_core.jobs import JobFailure

    job = enqueue(job_case)
    lease = delivery[1].claim(job.id, reference=reference_for(delivery, job))
    with pytest.raises(JobFailure), delivery[1].step(lease) as step:
        sleep(1.05)
        step.complete({"too_late": True})
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT state FROM jobs WHERE id=:j"), {"j": job.id}
            ).scalar_one()
            == "RUNNING"
        )


def test_concurrent_same_request_enqueues_one_durable_identity(job_case):
    from concurrent.futures import ThreadPoolExecutor

    payload = ImportJobPayload(import_id=uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(lambda _: enqueue(job_case, payload=payload), range(2)))
    assert jobs[0].id == jobs[1].id
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM outbox WHERE job_id=:j"), {"j": jobs[0].id}
            ).scalar_one()
            == 1
        )


@pytest.fixture
def counter_delivery(job_case):
    import sys

    from wso_core.dispatch import Dispatcher
    from wso_core.worker import JobWorker

    from tests.support.job_handlers import REGISTRY, install_fixture_schema

    install_fixture_schema(job_case[3], domain_only=sys.platform == "win32")
    dispatcher = Dispatcher(
        os.environ["WSO_TEST_DISPATCH_DATABASE_URL"], lambda *_: None, registry=REGISTRY
    )
    worker = JobWorker(os.environ["WSO_TEST_JOB_DATABASE_URL"], REGISTRY)
    try:
        yield dispatcher, worker
    finally:
        dispatcher.engine.dispose()
        worker.engine.dispose()


def counter_job(case, kind="RECOVERY_COUNTER"):
    from tests.support.job_handlers import REGISTRY, CounterPayload

    return enqueue(
        case, kind=kind, payload=CounterPayload(operation_id=uuid4()), registry=REGISTRY
    )


def test_duplicate_delivery_has_one_domain_effect(job_case, counter_delivery):
    job = counter_job(job_case)
    reference = reference_for(counter_delivery, job)
    counter_delivery[1].execute(reference)
    counter_delivery[1].execute(reference)
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT effect_count FROM job_recovery_effects WHERE job_id=:j"),
                {"j": job.id},
            ).scalar_one()
            == 1
        )
        assert (
            db.execute(
                text("SELECT state FROM inbox_dedup WHERE job_id=:j"), {"j": job.id}
            ).scalar_one()
            == "COMPLETED"
        )
        assert (
            db.execute(
                text("SELECT state FROM jobs WHERE id=:j"), {"j": job.id}
            ).scalar_one()
            == "SUCCEEDED"
        )


def test_rollback_after_inbox_processing_reclaims_without_losing_effect(
    job_case, counter_delivery, fast_timing
):
    from time import sleep

    from tests.support.job_handlers import counter

    job = counter_job(job_case)
    reference = reference_for(counter_delivery, job)
    worker = counter_delivery[1]
    lease = worker.claim(job.id, reference=reference)
    with pytest.raises(RuntimeError), worker.step(lease) as step:
        counter(step)
        raise RuntimeError("injected rollback")
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM job_recovery_effects WHERE job_id=:j"),
                {"j": job.id},
            ).scalar_one()
            == 0
        )
        assert (
            db.execute(
                text("SELECT state FROM inbox_dedup WHERE job_id=:j"), {"j": job.id}
            ).scalar_one()
            == "PROCESSING"
        )
    sleep(2.05)
    assert worker.claim(job.id, reference=reference) is None
    sleep(1.05)
    worker.execute(reference)
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT effect_count FROM job_recovery_effects WHERE job_id=:j"),
                {"j": job.id},
            ).scalar_one()
            == 1
        )
        assert (
            db.execute(
                text("SELECT lease_generation FROM jobs WHERE id=:j"), {"j": job.id}
            ).scalar_one()
            == 2
        )


@pytest.mark.parametrize("mutation", ["assignment", "assignment_update", "inactive"])
def test_removed_and_readded_assignment_cannot_revive_job(
    job_case, counter_delivery, mutation
):
    from wso_contracts.models import StoreScope
    from wso_core.jobs import JobFailure, JobService

    from tests.support.job_handlers import REGISTRY, CounterPayload

    ids = job_case[1]
    with scope(job_case, actor="staff") as authorized:
        job = JobService(authorized.session, REGISTRY).enqueue(
            StoreScope(tenant_id=ids["a"], store_id=ids["assigned"]),
            "RECOVERY_STORE",
            CounterPayload(operation_id=uuid4()),
            "store-job",
        )
    worker = counter_delivery[1]
    lease = worker.claim(job.id, reference=reference_for(counter_delivery, job))
    with worker.step(lease):
        pass
    with job_case[3].begin() as db:
        if mutation == "assignment":
            db.execute(
                text(
                    "DELETE FROM store_memberships WHERE tenant_id=:t AND store_id=:s AND user_id=:u"
                ),
                {"t": ids["a"], "s": ids["assigned"], "u": ids["staff"]},
            )
            db.execute(
                text(
                    "INSERT INTO store_memberships(tenant_id,store_id,user_id) VALUES(:t,:s,:u)"
                ),
                {"t": ids["a"], "s": ids["assigned"], "u": ids["staff"]},
            )
        elif mutation == "assignment_update":
            db.execute(
                text(
                    "UPDATE store_memberships SET user_id=:owner WHERE tenant_id=:t AND store_id=:s AND user_id=:staff"
                ),
                {
                    "owner": ids["owner"],
                    "staff": ids["staff"],
                    "t": ids["a"],
                    "s": ids["assigned"],
                },
            )
            db.execute(
                text(
                    "UPDATE store_memberships SET user_id=:staff WHERE tenant_id=:t AND store_id=:s AND user_id=:owner"
                ),
                {
                    "owner": ids["owner"],
                    "staff": ids["staff"],
                    "t": ids["a"],
                    "s": ids["assigned"],
                },
            )
        else:
            db.execute(
                text("UPDATE stores SET active=false WHERE id=:s"),
                {"s": ids["assigned"]},
            )
            db.execute(
                text("UPDATE stores SET active=true WHERE id=:s"),
                {"s": ids["assigned"]},
            )
    with pytest.raises(JobFailure), worker.step(lease):
        pytest.fail("removed grant revived")
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT state FROM jobs WHERE id=:j"), {"j": job.id}
            ).scalar_one()
            == "CANCELLED"
        )


def test_cancel_waits_for_authorized_step_then_prevents_later_step(job_case, delivery):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    from wso_core.jobs import JobFailure, JobService

    job = enqueue(job_case)
    worker = delivery[1]
    lease = worker.claim(job.id, reference=reference_for(delivery, job))
    entered, release, cancel_started = Event(), Event(), Event()
    pids = []

    def active_step():
        with worker.step(lease) as step:
            entered.set()
            assert release.wait(5)
            step.record_item("bounded-step", "SUCCEEDED", {})

    def cancel():
        with scope(job_case) as authorized:
            pids.append(
                authorized.session.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            cancel_started.set()
            return JobService(authorized.session).cancel(job.id).state

    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(active_step)
        assert entered.wait(5)
        cancellation = pool.submit(cancel)
        assert cancel_started.wait(5)
        try:
            deadline = monotonic() + 3
            while True:
                assert not cancellation.done()
                with job_case[3].connect() as db:
                    waiting = db.execute(
                        text(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"
                        ),
                        {"pid": pids[0]},
                    ).scalar_one()
                if waiting == "Lock":
                    break
                assert monotonic() < deadline
                sleep(0.01)
        finally:
            release.set()
        active.result(timeout=5)
        assert cancellation.result(timeout=5) == "CANCELLED"
    with pytest.raises(JobFailure), worker.step(lease):
        pytest.fail("later effect authorized")


def test_generic_credential_handler_requires_separate_authorized_workflow(
    job_case, delivery
):
    from dataclasses import replace

    from wso_core.jobs import DEFAULT_REGISTRY, JobRegistry
    from wso_core.worker import JobWorker

    called = []
    registry = JobRegistry(
        (
            replace(
                DEFAULT_REGISTRY.get("IMPORT"),
                handler=lambda step: called.append(True) or {},
            ),
        )
    )
    worker = JobWorker(os.environ["WSO_TEST_JOB_DATABASE_URL"], registry)
    try:
        job = enqueue(job_case)
        worker.execute(reference_for(delivery, job))
        assert not called
        with job_case[3].connect() as db:
            row = db.execute(
                text("SELECT state,failure_code,submitted_at FROM jobs WHERE id=:j"),
                {"j": job.id},
            ).one()
            assert (
                row.state == "FAILED"
                and row.failure_code == "CAPABILITY_UNSUPPORTED"
                and row.submitted_at is None
            )
    finally:
        worker.engine.dispose()


@pytest.mark.parametrize("target", ["jobs", "outbox", "wso_private.dispatch_ready"])
def test_fault_after_each_durable_write_rolls_back_entire_enqueue(job_case, target):
    from wso_core.jobs import JobFailure

    suffix = uuid4().hex
    function = f"job_fault_{suffix}"
    # Fixture-only trigger is scoped to this synthetic tenant and removed in finally.
    with job_case[3].begin() as db:
        db.execute(
            text(
                f"CREATE FUNCTION public.{function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.tenant_id='{job_case[1]['a']}'::uuid THEN RAISE EXCEPTION 'fixture write rollback'; END IF; RETURN NEW; END $$"
            )
        )
        db.execute(
            text(
                f"CREATE TRIGGER {function} AFTER INSERT ON {target} FOR EACH ROW EXECUTE FUNCTION public.{function}()"
            )
        )
    try:
        with pytest.raises(JobFailure):
            enqueue(job_case)
        with job_case[3].connect() as db:
            for table in ["jobs", "outbox", "wso_private.dispatch_ready"]:
                assert (
                    db.execute(
                        text(f"SELECT count(*) FROM {table} WHERE tenant_id=:t"),
                        {"t": job_case[1]["a"]},
                    ).scalar_one()
                    == 0
                )
    finally:
        with job_case[3].begin() as db:
            db.execute(text(f"DROP TRIGGER {function} ON {target}"))
            db.execute(text(f"DROP FUNCTION public.{function}()"))


def test_separate_secret_workflow_completes_and_nested_redemption_use_fail_fast(
    job_case, connection_case, delivery
):
    from wso_core.secrets import SecretRejected, WorkerSecretStore

    item = create_connection(connection_case).json()
    job = enqueue(
        job_case, payload=ImportJobPayload(import_id=uuid4(), connection_id=item["id"])
    )
    worker = delivery[1]
    lease = worker.claim(job.id, reference=reference_for(delivery, job))
    handle = worker.issue_connection_handle(lease, item["id"])
    store = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    secretlease = store.with_secret(handle)
    pending = worker.issue_connection_handle(lease, item["id"])
    with worker.step(lease):
        with pytest.raises(SecretRejected):
            store.with_secret(pending)
        with pytest.raises(SecretRejected):
            secretlease.use(lambda _: pytest.fail("nested secret callback ran"))
    assert secretlease.use(lambda data: b"password-canary-84726" in data)
    worker.complete(job.id, lease.token, {"verified_fixture": True})
    with pytest.raises(SecretRejected):
        secretlease.use(lambda _: pytest.fail("completed job secret used"))
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT state FROM jobs WHERE id=:j"), {"j": job.id}
            ).scalar_one()
            == "SUCCEEDED"
        )


def test_external_submitted_uncertainty_survives_cancellation(
    job_case, counter_delivery
):
    from wso_core.jobs import JobService

    from tests.support.job_handlers import REGISTRY, ExternalPayload

    job = enqueue(
        job_case,
        kind="RECOVERY_EXTERNAL",
        payload=ExternalPayload(operation_id=uuid4()),
        registry=REGISTRY,
    )
    worker = counter_delivery[1]
    lease = worker.claim(job.id, reference=reference_for(counter_delivery, job))
    with worker.step(lease) as step:
        step.mark_submitted()
    with scope(job_case) as authorized:
        outcome = JobService(authorized.session).cancel(job.id)
    assert (
        outcome.state == "NEEDS_USER_INPUT"
        and outcome.failure_code == "UNKNOWN_REMOTE_STATE"
    )
    with job_case[3].connect() as db:
        row = db.execute(
            text(
                "SELECT cancel_requested_at,submitted_at,lease_digest FROM jobs WHERE id=:j"
            ),
            {"j": job.id},
        ).one()
        assert row.cancel_requested_at and row.submitted_at and row.lease_digest is None


def test_connection_lifecycle_revocation_atomically_closes_job_projection(
    job_case, connection_case, delivery
):
    from wso_core.connections import ConnectionService

    item = create_connection(connection_case).json()
    job = enqueue(
        job_case, payload=ImportJobPayload(import_id=uuid4(), connection_id=item["id"])
    )
    assert delivery[1].claim(job.id, reference=reference_for(delivery, job)) is not None
    with scope(job_case) as authorized:
        ConnectionService(authorized.session).disconnect(item["id"], 1)
    with job_case[3].connect() as db:
        row = db.execute(
            text(
                "SELECT j.state,d.state AS dispatch,o.completed_at FROM jobs j JOIN outbox o ON o.job_id=j.id JOIN wso_private.dispatch_ready d ON d.job_id=j.id WHERE j.id=:j"
            ),
            {"j": job.id},
        ).one()
        assert (
            row.state == "CANCELLED"
            and row.dispatch == "DONE"
            and row.completed_at is not None
        )


def test_membership_delete_readd_does_not_restore_queued_authority(job_case, delivery):
    job = enqueue(job_case)
    reference = reference_for(delivery, job)
    with job_case[3].begin() as db:
        db.execute(
            text("DELETE FROM memberships WHERE tenant_id=:t AND user_id=:u"),
            {"t": job_case[1]["a"], "u": job_case[1]["owner"]},
        )
        db.execute(
            text(
                "INSERT INTO memberships(tenant_id,user_id,role) VALUES(:t,:u,'OWNER')"
            ),
            {"t": job_case[1]["a"], "u": job_case[1]["owner"]},
        )
    assert delivery[1].claim(job.id, reference=reference) is None
    with job_case[3].connect() as db:
        assert (
            db.execute(
                text("SELECT state FROM jobs WHERE id=:j"), {"j": job.id}
            ).scalar_one()
            == "CANCELLED"
        )


def test_read_local_attempts_are_bounded(job_case, counter_delivery):
    from dataclasses import replace

    from wso_core.jobs import JobRegistry
    from wso_core.worker import JobWorker

    from tests.support.job_handlers import REGISTRY

    def failure(_):
        raise RuntimeError("fixture transient read failure")

    worker = JobWorker(
        os.environ["WSO_TEST_JOB_DATABASE_URL"],
        JobRegistry((replace(REGISTRY.get("RECOVERY_COUNTER"), handler=failure),)),
    )
    job = counter_job(job_case)
    reference = reference_for(counter_delivery, job)
    try:
        for attempt in range(3):
            worker.execute(reference)
            with job_case[3].begin() as db:
                db.execute(
                    text(
                        "UPDATE jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:j"
                    ),
                    {"j": job.id},
                )
            assert worker.claim(job.id, reference=reference) is None
            with job_case[3].begin() as db:
                db.execute(
                    text(
                        "UPDATE jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE id=:j"
                    ),
                    {"j": job.id},
                )
        with job_case[3].connect() as db:
            row = db.execute(
                text("SELECT state,failure_code,attempts FROM jobs WHERE id=:j"),
                {"j": job.id},
            ).one()
            assert (
                row.state == "FAILED"
                and row.failure_code == "RETRY_EXHAUSTED"
                and row.attempts == 3
            )
            assert (
                db.execute(
                    text("SELECT count(*) FROM job_recovery_effects WHERE job_id=:j"),
                    {"j": job.id},
                ).scalar_one()
                == 0
            )
    finally:
        worker.engine.dispose()


def test_job_secret_lease_does_not_survive_execution_fence(
    job_case, connection_case, delivery, fast_timing
):
    from time import sleep

    from wso_core.secrets import SecretRejected, WorkerSecretStore

    item = create_connection(connection_case).json()
    job = enqueue(
        job_case, payload=ImportJobPayload(import_id=uuid4(), connection_id=item["id"])
    )
    worker = delivery[1]
    reference = reference_for(delivery, job)
    first = worker.claim(job.id, reference=reference)
    store = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    capability = store.with_secret(worker.issue_connection_handle(first, item["id"]))
    sleep(2.05)
    assert worker.claim(job.id, reference=reference) is None
    sleep(1.05)
    second = worker.claim(job.id, reference=reference)
    assert second.generation > first.generation
    with pytest.raises(SecretRejected):
        capability.use(lambda _: pytest.fail("old generation used secret"))
    assert store.with_secret(worker.issue_connection_handle(second, item["id"])).use(
        lambda data: b"password-canary-84726" in data
    )


@pytest.mark.parametrize(
    ("operation", "expire_while_waiting", "expiry_kind"),
    [
        ("redeem", False, "job"),
        ("use", False, "job"),
        ("redeem", True, "job"),
        ("use", True, "job"),
        ("use", True, "capability"),
    ],
)
def test_job_secret_rechecks_authority_after_observed_job_lock_wait(
    job_case,
    connection_case,
    delivery,
    fast_timing,
    operation,
    expire_while_waiting,
    expiry_kind,
):
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic, sleep

    from wso_core.secrets import SecretRejected, WorkerSecretStore

    if expiry_kind == "capability":
        with job_case[3].begin() as db:
            db.execute(text("UPDATE wso_private.job_settings SET lease_seconds=60"))

    item = create_connection(connection_case).json()
    job = enqueue(
        job_case, payload=ImportJobPayload(import_id=uuid4(), connection_id=item["id"])
    )
    worker = delivery[1]
    lease = worker.claim(job.id, reference=reference_for(delivery, job))
    handle = worker.issue_connection_handle(lease, item["id"])
    store = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    capability = store.with_secret(handle) if operation == "use" else None
    calls = []

    def attempt():
        if operation == "redeem":
            store.with_secret(handle)
            return True
        return capability.use(lambda _: calls.append(True) or True)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with job_case[3].connect() as blocker:
            transaction = blocker.begin()
            blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
            blocker.execute(
                text("SELECT id FROM jobs WHERE id=:j FOR UPDATE"), {"j": job.id}
            )
            pending = pool.submit(attempt)
            try:
                deadline = monotonic() + 3
                while True:
                    assert not pending.done()
                    with job_case[3].connect() as observer:
                        waiting = observer.execute(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE usename='wso_connection_worker' "
                                "AND wait_event_type='Lock' "
                                "AND :blocker=ANY(pg_blocking_pids(pid)) "
                                "AND query LIKE :function"
                            ),
                            {
                                "blocker": blocker_pid,
                                "function": f"%wso_{'redeem_connection_handle' if operation == 'redeem' else 'use_connection_lease'}(%",
                            },
                        ).scalar_one()
                    if waiting == 1:
                        break
                    assert monotonic() < deadline
                    sleep(0.01)
                started = monotonic()
                if expire_while_waiting:
                    elapsed = 30.1 if expiry_kind == "capability" else 2.1
                    while monotonic() - started < elapsed:
                        sleep(0.01)
                    assert monotonic() - started >= elapsed
                # The blocker never modifies the row, its fence, or any deadline.
                live = blocker.execute(
                    text(
                        "SELECT lease_expires_at>clock_timestamp() FROM jobs WHERE id=:j"
                    ),
                    {"j": job.id},
                ).scalar_one()
                assert live is (expiry_kind == "capability" or not expire_while_waiting)
                if expiry_kind == "capability":
                    assert blocker.execute(
                        text(
                            "SELECT expires_at<=clock_timestamp() "
                            "FROM wso_private.connection_leases WHERE job_id=:j"
                        ),
                        {"j": job.id},
                    ).scalar_one()
            finally:
                transaction.rollback()
        if expire_while_waiting:
            with pytest.raises(SecretRejected):
                pending.result(timeout=5)
            assert calls == []
        else:
            assert pending.result(timeout=5) is True
            assert calls == ([True] if operation == "use" else [])


@pytest.mark.parametrize("already_submitted", [False, True])
def test_external_handler_without_reconciler_never_submits_or_erases_uncertainty(
    job_case, counter_delivery, fast_timing, already_submitted
):
    from dataclasses import replace
    from time import sleep

    from wso_core.jobs import JobRegistry
    from wso_core.worker import JobWorker

    from tests.support.job_handlers import REGISTRY, ExternalPayload

    calls = []
    registry = JobRegistry(
        (
            replace(
                REGISTRY.get("RECOVERY_EXTERNAL"),
                handler=lambda step: calls.append(True) or {},
                reconcile=None,
            ),
        )
    )
    job = enqueue(
        job_case,
        kind="RECOVERY_EXTERNAL",
        payload=ExternalPayload(operation_id=uuid4()),
        registry=registry,
    )
    reference = reference_for(counter_delivery, job)
    if already_submitted:
        original = counter_delivery[1]
        lease = original.claim(job.id, reference=reference)
        with original.step(lease) as step:
            step.mark_submitted()
        sleep(2.05)
        assert original.claim(job.id, reference=reference) is None
        sleep(1.05)
    worker = JobWorker(os.environ["WSO_TEST_JOB_DATABASE_URL"], registry)
    try:
        worker.execute(reference)
        assert calls == []
        with job_case[3].connect() as db:
            row = db.execute(
                text("SELECT state,failure_code,submitted_at FROM jobs WHERE id=:j"),
                {"j": job.id},
            ).one()
        if already_submitted:
            assert row.state == "NEEDS_USER_INPUT"
            assert row.failure_code == "UNKNOWN_REMOTE_STATE"
            assert row.submitted_at is not None
        else:
            assert row.state == "FAILED"
            assert row.failure_code == "HANDLER_UNAVAILABLE"
            assert row.submitted_at is None
    finally:
        worker.engine.dispose()


def test_dispatcher_refuses_registry_queue_drift_before_publication(
    job_case, counter_delivery
):
    from dataclasses import replace

    from wso_core.dispatch import Dispatcher
    from wso_core.jobs import JobRegistry

    from tests.support.job_handlers import REGISTRY

    job = counter_job(job_case)
    published = []
    registry = JobRegistry(
        (replace(REGISTRY.get("RECOVERY_COUNTER"), queue="wso.media"),)
    )
    dispatcher = Dispatcher(
        os.environ["WSO_TEST_DISPATCH_DATABASE_URL"],
        lambda reference, queue: published.append((reference, queue)),
        registry=registry,
    )
    try:
        dispatcher.run_once()
        assert not any(reference.job_id == job.id for reference, queue in published)
        with job_case[3].connect() as db:
            assert (
                db.execute(
                    text(
                        "SELECT error_code FROM wso_private.dispatch_ready WHERE job_id=:j"
                    ),
                    {"j": job.id},
                ).scalar_one()
                == "PUBLISH_FAILED"
            )
    finally:
        dispatcher.engine.dispose()


def test_dispatcher_publishes_exact_reference_to_persisted_queue(
    job_case, counter_delivery
):
    from wso_core.dispatch import Dispatcher

    from tests.support.job_handlers import REGISTRY

    job = counter_job(job_case)
    published = []
    dispatcher = Dispatcher(
        os.environ["WSO_TEST_DISPATCH_DATABASE_URL"],
        lambda reference, queue: published.append((reference, queue)),
        registry=REGISTRY,
    )
    try:
        dispatcher.run_once()
        matching = [
            (reference, queue)
            for reference, queue in published
            if reference.job_id == job.id
        ]
        assert len(matching) == 1 and matching[0][1] == "wso.default"
        assert "queue" not in matching[0][0].model_dump()
    finally:
        dispatcher.engine.dispose()


def test_runtime_factory_is_explicit_and_uses_json_late_ack_configuration(monkeypatch):
    from wso_core.job_runtime import create_app

    monkeypatch.delenv("WSO_BROKER_URL", raising=False)
    monkeypatch.delenv("WSO_JOB_DATABASE_URL", raising=False)
    with pytest.raises(ValueError):
        create_app("amqp://localhost", "postgresql+psycopg://worker@localhost/test")
    app = create_app(
        "redis://127.0.0.1:1/0", "postgresql+psycopg://wso_job_worker@127.0.0.1/unused"
    )
    assert app.conf.accept_content == ["json"] and app.conf.task_serializer == "json"
    assert app.conf.task_acks_late and app.conf.task_reject_on_worker_lost
    assert app.conf.worker_prefetch_multiplier == 1 and app.conf.task_ignore_result
    assert app.conf.result_backend is None
    assert (
        app.conf.broker_transport_options["visibility_timeout"]
        > app.conf.task_time_limit
    )
    assert "wso.execute_job" in app.tasks
    app.close()


def test_uncertain_external_recovery_is_bounded_and_never_becomes_failure(
    job_case, counter_delivery
):
    from tests.support.job_handlers import REGISTRY, ExternalPayload

    job = enqueue(
        job_case,
        kind="RECOVERY_EXTERNAL",
        payload=ExternalPayload(operation_id=uuid4()),
        registry=REGISTRY,
    )
    worker = counter_delivery[1]
    reference = reference_for(counter_delivery, job)
    for attempt in range(3):
        lease = worker.claim(job.id, reference=reference)
        assert lease is not None
        with worker.step(lease) as step:
            step.mark_submitted()
        with job_case[3].begin() as db:
            db.execute(
                text(
                    "UPDATE jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=:j"
                ),
                {"j": job.id},
            )
        assert worker.claim(job.id, reference=reference) is None
        with job_case[3].begin() as db:
            db.execute(
                text(
                    "UPDATE jobs SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE id=:j"
                ),
                {"j": job.id},
            )
    with job_case[3].connect() as db:
        row = db.execute(
            text("SELECT state,failure_code,attempts FROM jobs WHERE id=:j"),
            {"j": job.id},
        ).one()
        assert (
            row.state == "NEEDS_USER_INPUT"
            and row.failure_code == "UNKNOWN_REMOTE_STATE"
            and row.attempts == 3
        )


def test_assigned_store_member_cannot_read_another_actors_job(
    job_case, counter_delivery
):
    from wso_contracts.models import StoreScope
    from wso_core.jobs import JobFailure, JobService

    from tests.support.job_handlers import REGISTRY, CounterPayload

    with scope(job_case) as authorized:
        job = JobService(authorized.session, REGISTRY).enqueue(
            StoreScope(tenant_id=job_case[1]["a"], store_id=job_case[1]["assigned"]),
            "RECOVERY_STORE",
            CounterPayload(operation_id=uuid4()),
            "owner-store",
        )
    with scope(job_case, actor="staff") as authorized:
        with pytest.raises(JobFailure) as denied:
            JobService(authorized.session).get(job.id)
        assert denied.value.status == 404


def test_inactive_store_job_is_inaccessible_even_to_owner(job_case, counter_delivery):
    from wso_contracts.models import StoreScope
    from wso_core.jobs import JobFailure, JobService

    from tests.support.job_handlers import REGISTRY, CounterPayload

    with scope(job_case) as authorized:
        job = JobService(authorized.session, REGISTRY).enqueue(
            StoreScope(tenant_id=job_case[1]["a"], store_id=job_case[1]["assigned"]),
            "RECOVERY_STORE",
            CounterPayload(operation_id=uuid4()),
            "owner-store",
        )
    with job_case[3].begin() as db:
        db.execute(
            text("UPDATE stores SET active=false WHERE id=:s"),
            {"s": job_case[1]["assigned"]},
        )
    with scope(job_case) as authorized:
        with pytest.raises(JobFailure) as denied:
            JobService(authorized.session).get(job.id)
        assert denied.value.status == 404


def test_registry_startup_rejects_security_metadata_drift(job_case, counter_delivery):
    from dataclasses import replace

    from wso_core.jobs import JobFailure, JobRegistry
    from wso_core.worker import JobWorker

    from tests.support.job_handlers import REGISTRY

    drift = JobRegistry(
        (replace(REGISTRY.get("RECOVERY_COUNTER"), permission="STAFF"),)
    )
    with pytest.raises(JobFailure):
        JobWorker(os.environ["WSO_TEST_JOB_DATABASE_URL"], drift)


def test_creator_cancel_requires_current_kind_permission(job_case):
    from wso_core.jobs import JobFailure, JobService

    job = enqueue(job_case)
    with job_case[3].begin() as db:
        db.execute(
            text(
                "UPDATE memberships SET role='STAFF' WHERE tenant_id=:t AND user_id=:u"
            ),
            {"t": job_case[1]["a"], "u": job_case[1]["owner"]},
        )
    with scope(job_case) as authorized:
        assert JobService(authorized.session).get(job.id).state == "CANCELLED"
        with pytest.raises(JobFailure) as denied:
            JobService(authorized.session).cancel(job.id)
        assert denied.value.status == 404
