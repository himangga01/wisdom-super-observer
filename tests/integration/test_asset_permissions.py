"""Asset authority gates against the explicitly owned PostgreSQL server."""

import json
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.support.job_handlers import verify_fixture_database

pytest_plugins = ["tests.auth_support"]


@pytest.fixture(scope="module")
def auth_db(asset_database):
    engines = [asset_database] + [
        create_engine(os.environ[f"WSO_TEST_{role}_DATABASE_URL"], hide_parameters=True)
        for role in ("APP", "IDENTITY", "SESSION")
    ]
    try:
        yield engines
    finally:
        for engine in engines[1:]:
            engine.dispose()


@pytest.fixture
def asset_authorization(asset_database):
    from wso_core.db_budget import AuthorizationDbFactories, create_budgeted_provider

    providers = [
        create_budgeted_provider(
            os.environ[f"WSO_TEST_{role}_DATABASE_URL"],
            null_pool=index == 3,
            pool_size=1,
        )
        for index, role in enumerate(("SESSION", "IDENTITY", "APP", "APP"))
    ]
    try:
        yield AuthorizationDbFactories(*providers)
    finally:
        for provider in providers:
            provider.dispose()


@pytest.fixture
def asset_case(auth_case, signing_key):
    from wso_api.auth import token_digest

    from tests.auth_support import login

    data = login(auth_case[0], signing_key, auth_case[1], "owner")
    digest = token_digest(data["session_id"])
    with auth_case[3].begin() as db:
        present = db.execute(
            text("SELECT to_regclass('public.assets') IS NOT NULL")
        ).scalar_one()
        if present:
            row = (
                db.execute(
                    text("SELECT * FROM public.wso_asset_runtime_configuration()")
                )
                .mappings()
                .one()
            )
            if row["installation_id"] is None:
                db.execute(
                    text(
                        "SELECT public.wso_install_asset_runtime_configuration(:i,'wso-owned-assets-test')"
                    ),
                    {"i": UUID("8aef7c82-258d-4f72-8012-21bc64a1abb1")},
                )
    try:
        yield auth_case, digest
    finally:
        if present:
            with auth_case[3].begin() as db:
                ids = [auth_case[1]["a"], auth_case[1]["b"]]
                for table in (
                    "asset_audit_outbox",
                    "asset_cleanup",
                    "asset_read_leases",
                    "asset_tickets",
                    "asset_uploads",
                ):
                    db.execute(
                        text(
                            f"DELETE FROM wso_private.{table} WHERE tenant_id=ANY(:ids)"
                        ),
                        {"ids": ids},
                    )
                db.execute(
                    text("DELETE FROM public.job_assets WHERE tenant_id=ANY(:ids)"),
                    {"ids": ids},
                )
                db.execute(
                    text("DELETE FROM public.jobs WHERE tenant_id=ANY(:ids)"),
                    {"ids": ids},
                )
                db.execute(
                    text("DELETE FROM public.assets WHERE tenant_id=ANY(:ids)"),
                    {"ids": ids},
                )
                db.execute(
                    text("DELETE FROM public.audit_events WHERE tenant_id=ANY(:ids)"),
                    {"ids": ids},
                )


@contextmanager
def asset_scope(case, actor="owner", tenant="a"):
    from wso_api.auth import WebSession
    from wso_api.stores.router import require_tenant

    fixture, _ = case
    principal = WebSession(
        "https://issuer.test",
        str(fixture[1][actor]),
        fixture[1][actor],
        "",
        datetime.now(UTC) + timedelta(minutes=5),
    )
    with require_tenant(
        "stores:read", fixture[1][tenant], service=fixture[2], principal=principal
    ) as scope:
        yield scope.session


def upload_request(case, **changes):
    return {
        "scope": {"scope_kind": "TENANT", "tenant_id": str(case[0][1]["a"])},
        "purpose": "IMPORT_PHOTO",
        "content_type": "image/png",
        "byte_size": 9,
        "checksum": {"algorithm": "SHA256", "value": "a" * 64},
        "parent_asset_id": None,
        **changes,
    }


def begin(case, **changes):
    with asset_scope(case) as db:
        try:
            return dict(
                db.execute(
                    text(
                        "SELECT * FROM public.wso_begin_asset_upload(CAST(:r AS jsonb),:s)"
                    ),
                    {"r": json.dumps(upload_request(case, **changes)), "s": case[1]},
                )
                .mappings()
                .one()
            )
        except DBAPIError as error:
            if error.orig.sqlstate == "42883":
                pytest.fail(
                    "authenticated asset allocation control is missing", pytrace=False
                )
            raise


def test_owner_allocates_photo_without_store_and_private_manifest_is_hidden(asset_case):
    result = begin(asset_case)
    assert result["max_bytes"] == 9
    assert result["upload_path"].startswith("/api/v1/assets/")
    with asset_scope(asset_case) as db:
        row = db.execute(
            text("SELECT state,store_id FROM public.assets WHERE id=:id"),
            {"id": result["asset_id"]},
        ).one()
        assert row.state == "PENDING" and row.store_id is None
        with pytest.raises(DBAPIError) as rejected:
            db.execute(text("SELECT * FROM wso_private.asset_uploads"))
        assert rejected.value.orig.sqlstate == "42501"


def test_unknown_session_cannot_allocate(asset_case):
    with asset_scope(asset_case) as db:
        with pytest.raises(DBAPIError) as rejected:
            db.execute(
                text(
                    "SELECT * FROM public.wso_begin_asset_upload(CAST(:r AS jsonb),:s)"
                ),
                {"r": json.dumps(upload_request(asset_case)), "s": "f" * 64},
            )
        assert rejected.value.orig.sqlstate == "42501"


def test_evidence_capability_denies_before_allocation(asset_case):
    with asset_scope(asset_case) as db:
        with pytest.raises(DBAPIError) as rejected:
            db.execute(
                text(
                    "SELECT * FROM public.wso_begin_asset_upload(CAST(:r AS jsonb),:s)"
                ),
                {
                    "r": json.dumps(
                        upload_request(
                            asset_case,
                            purpose="EVIDENCE",
                            scope={
                                "scope_kind": "STORE",
                                "tenant_id": str(asset_case[0][1]["a"]),
                                "store_id": str(asset_case[0][1]["assigned"]),
                            },
                        )
                    ),
                    "s": asset_case[1],
                },
            )
        assert rejected.value.orig.sqlstate == "0A000"


def test_pending_asset_cannot_issue_ticket_or_finalize_without_lease(asset_case):
    result = begin(asset_case)
    for statement, expected in (
        ("SELECT * FROM public.wso_issue_asset_ticket(:id,:s)", "55000"),
        (
            "SELECT * FROM public.wso_finish_asset_validation(:id,1,:token,'{}'::jsonb,:s)",
            "55000",
        ),
    ):
        with asset_scope(asset_case) as db:
            with pytest.raises(DBAPIError) as rejected:
                db.execute(
                    text(statement),
                    {"id": result["asset_id"], "s": asset_case[1], "token": "a" * 64},
                )
            assert rejected.value.orig.sqlstate == expected


def test_tombstone_is_idempotent_and_blocks_new_write(asset_case):
    result = begin(asset_case)
    for _ in range(2):
        with asset_scope(asset_case) as db:
            row = (
                db.execute(
                    text("SELECT * FROM public.wso_tombstone_asset(:id,:s)"),
                    {"id": result["asset_id"], "s": asset_case[1]},
                )
                .mappings()
                .one()
            )
            assert row["state"] == "DELETING"
    with asset_scope(asset_case) as db:
        with pytest.raises(DBAPIError) as rejected:
            db.execute(
                text("SELECT * FROM public.wso_prepare_asset_write(:id,:session,:s)"),
                {"id": result["asset_id"], "session": result["id"], "s": asset_case[1]},
            )
        assert rejected.value.orig.sqlstate == "55000"


def test_parent_must_be_owned_ready_photo(asset_case):
    with pytest.raises(DBAPIError) as rejected:
        begin(asset_case, purpose="IMPORT_CROP", parent_asset_id=str(uuid4()))
    assert rejected.value.orig.sqlstate == "P0002"


ENVELOPE = {
    "key_id": "test",
    "wrapped_dek": "a" * 96,
    "wrap_nonce": "b" * 24,
    "object_nonce": "c" * 24,
}


def control(case, name, arguments, values):
    with asset_scope(case) as db:
        return dict(
            db.execute(
                text(f"SELECT * FROM public.{name}({arguments})"),
                {"s": case[1], **values},
            )
            .mappings()
            .one()
        )


def ready(case):
    upload = begin(case)
    identifier = upload["asset_id"]
    manifest = control(
        case,
        "wso_begin_asset_write",
        ":id,:upload,:s,CAST(:envelope AS jsonb)",
        {"id": identifier, "upload": upload["id"], "envelope": json.dumps(ENVELOPE)},
    )
    values = {
        "id": identifier,
        "generation": manifest["lease_generation"],
        "token": manifest["lease_token"],
    }
    control(
        case,
        "wso_record_asset_multipart",
        ":id,:generation,:token,:multipart,:s",
        {**values, "multipart": "ready-fixture-upload"},
    )
    control(case, "wso_begin_asset_completion", ":id,:generation,:token,:s", values)
    control(
        case,
        "wso_seal_asset_upload",
        ":id,:generation,:token,:s",
        {
            "id": identifier,
            "generation": manifest["lease_generation"],
            "token": manifest["lease_token"],
        },
    )
    validation = control(
        case, "wso_begin_asset_validation", ":id,:s", {"id": identifier}
    )
    receipt = {
        "policy_version": validation["policy_version"],
        "byte_size": 9,
        "checksum_sha256": "a" * 64,
        "content_type": "image/png",
        "width": 1,
        "height": 1,
        "oriented_width": 1,
        "oriented_height": 1,
        "frame_count": 1,
    }
    result = control(
        case,
        "wso_finish_asset_validation",
        ":id,:generation,:token,CAST(:receipt AS jsonb),:s",
        {
            "id": identifier,
            "generation": validation["lease_generation"],
            "token": validation["lease_token"],
            "receipt": json.dumps(receipt),
        },
    )
    assert result["state"] == "READY"
    return identifier


def test_checked_write_validation_and_one_use_ticket(asset_case):
    identifier = ready(asset_case)
    ticket = control(asset_case, "wso_issue_asset_ticket", ":id,:s", {"id": identifier})
    manifest = control(
        asset_case,
        "wso_redeem_asset_ticket",
        ":id,:token,:s",
        {"id": identifier, "token": ticket["token"]},
    )
    assert manifest["read_use"] == "DOWNLOAD" and manifest["lease_token"] is None
    with pytest.raises(DBAPIError) as rejected:
        control(
            asset_case,
            "wso_redeem_asset_ticket",
            ":id,:token,:s",
            {"id": identifier, "token": ticket["token"]},
        )
    assert rejected.value.orig.sqlstate == "P0002"


def test_single_write_attempt_and_foreign_finish_token_are_denied(asset_case):
    upload = begin(asset_case)
    values = {
        "id": upload["asset_id"],
        "upload": upload["id"],
        "envelope": json.dumps(ENVELOPE),
    }
    manifest = control(
        asset_case,
        "wso_begin_asset_write",
        ":id,:upload,:s,CAST(:envelope AS jsonb)",
        values,
    )
    with pytest.raises(DBAPIError) as rejected:
        control(
            asset_case,
            "wso_begin_asset_write",
            ":id,:upload,:s,CAST(:envelope AS jsonb)",
            values,
        )
    assert rejected.value.orig.sqlstate == "55000"
    with pytest.raises(DBAPIError) as rejected:
        control(
            asset_case,
            "wso_seal_asset_upload",
            ":id,:generation,:token,:s",
            {
                "id": upload["asset_id"],
                "generation": manifest["lease_generation"],
                "token": "f" * 64,
            },
        )
    assert rejected.value.orig.sqlstate == "55000"


def test_parent_tombstone_invalidates_child_and_issued_ticket(asset_case):
    parent = ready(asset_case)
    child = begin(asset_case, purpose="IMPORT_CROP", parent_asset_id=str(parent))
    ticket = control(asset_case, "wso_issue_asset_ticket", ":id,:s", {"id": parent})
    control(asset_case, "wso_tombstone_asset", ":id,:s", {"id": parent})
    with asset_scope(asset_case) as db:
        states = (
            db.execute(
                text("SELECT state FROM public.assets WHERE id=ANY(:ids)"),
                {"ids": [parent, child["asset_id"]]},
            )
            .scalars()
            .all()
        )
        assert states == ["DELETING", "DELETING"]
    with pytest.raises(DBAPIError):
        control(
            asset_case,
            "wso_redeem_asset_ticket",
            ":id,:token,:s",
            {"id": parent, "token": ticket["token"]},
        )


def test_maintenance_can_finish_known_unwritten_attempt_without_read_authority(
    asset_case,
):
    identifier = begin(asset_case)["asset_id"]
    control(asset_case, "wso_tombstone_asset", ":id,:s", {"id": identifier})
    with asset_case[0][3].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.asset_cleanup SET due_at=clock_timestamp()-interval '1 second' WHERE asset_id=:id"
            ),
            {"id": identifier},
        )
    with asset_case[0][3].begin() as db:
        db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
        work = (
            db.execute(
                text(
                    "SELECT * FROM public.wso_claim_asset_cleanup(1,'permissions-test')"
                )
            )
            .mappings()
            .one()
        )
        assert work["asset_id"] == identifier
        assert "wrapped_dek" not in work and "session_digest" not in work
    with asset_case[0][3].begin() as db:
        db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
        assert db.execute(
            text("SELECT public.wso_finish_asset_cleanup(:id,:gen,:token,true)"),
            {
                "id": work["work_id"],
                "gen": work["lease_generation"],
                "token": work["lease_token"],
            },
        ).scalar_one()
    with asset_scope(asset_case) as db:
        assert (
            db.execute(
                text("SELECT state FROM public.assets WHERE id=:id"), {"id": identifier}
            ).scalar_one()
            == "DELETED"
        )


def test_uncertain_remote_write_cannot_be_deleted_from_absence_alone(asset_case):
    upload = begin(asset_case)
    manifest = control(
        asset_case,
        "wso_begin_asset_write",
        ":id,:upload,:s,CAST(:envelope AS jsonb)",
        {
            "id": upload["asset_id"],
            "upload": upload["id"],
            "envelope": json.dumps(ENVELOPE),
        },
    )
    values = {
        "id": upload["asset_id"],
        "generation": manifest["lease_generation"],
        "token": manifest["lease_token"],
    }
    control(
        asset_case,
        "wso_record_asset_multipart",
        ":id,:generation,:token,:multipart,:s",
        {**values, "multipart": "uncertain-completion"},
    )
    control(
        asset_case, "wso_begin_asset_completion", ":id,:generation,:token,:s", values
    )
    control(asset_case, "wso_tombstone_asset", ":id,:s", {"id": upload["asset_id"]})
    with asset_case[0][3].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.asset_uploads SET lease_expires_at=clock_timestamp()-interval '1 minute' WHERE asset_id=:id"
            ),
            {"id": upload["asset_id"]},
        )
        db.execute(
            text(
                "UPDATE wso_private.asset_cleanup SET due_at=clock_timestamp()-interval '1 second' WHERE asset_id=:id"
            ),
            {"id": upload["asset_id"]},
        )
    with asset_case[0][3].begin() as db:
        db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
        work = (
            db.execute(
                text(
                    "SELECT * FROM public.wso_claim_asset_cleanup(1,'permissions-test')"
                )
            )
            .mappings()
            .one()
        )
    with asset_case[0][3].begin() as db:
        db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
        assert not db.execute(
            text("SELECT public.wso_finish_asset_cleanup(:id,:gen,:token,true)"),
            {
                "id": work["work_id"],
                "gen": work["lease_generation"],
                "token": work["lease_token"],
            },
        ).scalar_one()


def test_job_read_requires_real_job_context_and_empty_allowlist_denies(asset_database):
    with asset_database.begin() as db:
        db.execute(text("SET LOCAL ROLE wso_job_worker"))
        with pytest.raises(DBAPIError) as rejected:
            db.execute(
                text("SELECT * FROM public.wso_begin_job_asset_read(:id)"),
                {"id": uuid4()},
            )
        assert rejected.value.orig.sqlstate == "42501"


def test_maintenance_worker_id_matches_frozen_128_character_opaque_contract(
    asset_database,
):
    with asset_database.begin() as db:
        db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
        assert (
            db.execute(
                text("SELECT * FROM public.wso_claim_asset_cleanup(1,:worker)"),
                {"worker": "worker " + "x" * 121},
            )
            .mappings()
            .all()
            == []
        )


def test_reconciliation_cursor_survives_worker_replacement_and_rejects_stale_cas(
    asset_database,
):
    with asset_database.connect() as db:
        transaction = db.begin()
        try:
            db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
            try:
                state = (
                    db.execute(
                        text("SELECT * FROM public.wso_asset_reconciliation_state()")
                    )
                    .mappings()
                    .one()
                )
            except DBAPIError:
                pytest.fail(
                    "durable reconciliation cursor control is missing", pytrace=False
                )
            assert db.execute(
                text(
                    "SELECT public.wso_checkpoint_asset_reconciliation('OBJECTS',:expected,'test-cursor')"
                ),
                {"expected": state["object_cursor"]},
            ).scalar_one()
            assert not db.execute(
                text(
                    "SELECT public.wso_checkpoint_asset_reconciliation('OBJECTS','stale-cursor','next-cursor')"
                )
            ).scalar_one()
            assert (
                db.execute(
                    text("SELECT * FROM public.wso_asset_reconciliation_state()")
                )
                .mappings()
                .one()["object_cursor"]
                == "test-cursor"
            )
        finally:
            transaction.rollback()


def test_http_controls_bind_actual_cookie_and_require_csrf(
    asset_case, signing_key, asset_authorization
):
    from types import SimpleNamespace

    from sqlalchemy.orm import Session
    from wso_api.assets.bootstrap import AssetRuntime, configure_assets
    from wso_core.assets import (
        AssetAdmissionController,
        read_asset_runtime_configuration,
    )

    from tests.auth_support import login

    try:
        from wso_api.assets.router import router
    except ModuleNotFoundError:
        pytest.fail("authenticated asset router is missing", pytrace=False)
    case, digest = asset_case
    client, ids, _service, admin = case
    if "/api/v1/assets" not in client.app.openapi()["paths"]:
        client.app.include_router(router)
    with Session(admin) as db:
        configuration = read_asset_runtime_configuration(db)
    unavailable = SimpleNamespace(namespace=configuration.namespace)
    configure_assets(
        client.app,
        runtime=AssetRuntime(
            configuration,
            unavailable,
            unavailable,
            unavailable,
            AssetAdmissionController(upload_slots=2, read_slots=2),
            None,
            authorization=asset_authorization,
        ),
    )
    request = upload_request(asset_case)
    assert client.post("/api/v1/assets", json=request).status_code == 403
    credentials = login(client, signing_key, ids, "owner")
    response = client.post(
        "/api/v1/assets",
        json=request,
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": credentials["csrf_token"],
        },
    )
    assert response.status_code == 201, response.text
    assert response.headers["Cache-Control"] == "no-store"
    identifier = response.json()["asset_id"]
    from wso_api.auth import token_digest

    with admin.connect() as db:
        stored = db.execute(
            text(
                "SELECT session_digest FROM wso_private.asset_uploads WHERE asset_id=:id"
            ),
            {"id": identifier},
        ).scalar_one()
    assert stored == token_digest(credentials["session_id"]) and stored != digest
    result = client.get(f"/api/v1/assets/{identifier}", params={"tenant_id": ids["a"]})
    assert result.status_code == 200 and result.json()["state"] == "PENDING"


@pytest.fixture(scope="module")
def asset_database():
    url = os.getenv("WSO_TEST_ADMIN_DATABASE_URL")
    if not url:
        pytest.skip("requires explicit owned PostgreSQL role URLs")
    engine = create_engine(url, hide_parameters=True)
    verify_fixture_database(engine, domain_only=sys.platform == "win32")
    try:
        yield engine
    finally:
        engine.dispose()


def test_runtime_policy_is_readable_without_tenant_or_byte_authority(asset_database):
    with asset_database.begin() as db:
        db.execute(text("SET LOCAL ROLE wso_app"))
        try:
            row = db.execute(
                text("SELECT * FROM public.wso_asset_runtime_configuration()")
            )
        except DBAPIError:
            pytest.fail(
                "protected asset policy getter is not implemented", pytrace=False
            )
        assert row.mappings().one()["max_bytes"] == 20_971_520


def test_runtime_cannot_install_namespace(asset_database):
    with asset_database.begin() as db:
        assert db.execute(
            text(
                "SELECT to_regprocedure('public.wso_install_asset_runtime_configuration(uuid,text)') IS NOT NULL"
            )
        ).scalar_one(), "namespace installer missing"
        for role in ("wso_app", "wso_job_worker", "wso_asset_maintenance"):
            assert not db.execute(
                text(
                    "SELECT has_function_privilege(:r,'public.wso_install_asset_runtime_configuration(uuid,text)','EXECUTE')"
                ),
                {"r": role},
            ).scalar_one()


def test_asset_private_rows_and_schema_are_not_runtime_authority(asset_database):
    with asset_database.begin() as db:
        assert db.execute(
            text("SELECT to_regclass('wso_private.asset_settings') IS NOT NULL")
        ).scalar_one(), "protected asset settings missing"
        for role in ("wso_app", "wso_job_worker", "wso_asset_maintenance"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not db.execute(
                    text(
                        "SELECT has_table_privilege(:r,'wso_private.asset_settings',:p)"
                    ),
                    {"r": role, "p": privilege},
                ).scalar_one()
            assert not db.execute(
                text("SELECT has_schema_privilege(:r,'public','CREATE')"), {"r": role}
            ).scalar_one()


def test_namespace_install_is_one_time_and_idempotent(asset_database):
    # Roll back an installer exercise; never rebind the managed installation.
    with asset_database.connect() as db:
        transaction = db.begin()
        try:
            exists = db.execute(
                text(
                    "SELECT to_regprocedure('public.wso_asset_runtime_configuration()') IS NOT NULL"
                )
            ).scalar_one()
            assert exists, "runtime configuration missing"
            row = (
                db.execute(
                    text("SELECT * FROM public.wso_asset_runtime_configuration()")
                )
                .mappings()
                .one()
            )
            installation = row["installation_id"] or UUID(
                "8aef7c82-258d-4f72-8012-21bc64a1abb1"
            )
            bucket = row["bucket"] or "wso-owned-assets-test"
            db.execute(text("SET LOCAL ROLE wso_migrator"))
            for _ in range(2):
                db.execute(
                    text(
                        "SELECT public.wso_install_asset_runtime_configuration(:i,:b)"
                    ),
                    {"i": installation, "b": bucket},
                )
            with pytest.raises(DBAPIError) as rejected:
                db.execute(
                    text(
                        "SELECT public.wso_install_asset_runtime_configuration(:i,'different-owned-bucket')"
                    ),
                    {"i": installation},
                )
            assert rejected.value.orig.sqlstate == "40001"
        finally:
            transaction.rollback()


def test_policy_change_requires_new_version_even_for_migrator(asset_database):
    with asset_database.connect() as db:
        transaction = db.begin()
        try:
            assert db.execute(
                text("SELECT to_regclass('wso_private.asset_settings') IS NOT NULL")
            ).scalar_one(), "settings missing"
            db.execute(text("SET LOCAL ROLE wso_migrator"))
            with pytest.raises(DBAPIError) as rejected:
                db.execute(
                    text(
                        "UPDATE wso_private.asset_settings SET upload_seconds=upload_seconds-1"
                    )
                )
            assert rejected.value.orig.sqlstate == "22023"
        finally:
            transaction.rollback()


def test_policy_getter_fences_concurrent_policy_change_for_control_transaction(
    asset_database,
):
    with asset_database.connect() as control_db, asset_database.connect() as editor:
        transaction = control_db.begin()
        edit = editor.begin()
        try:
            control_db.execute(text("SET LOCAL ROLE wso_app"))
            control_db.execute(
                text("SELECT * FROM public.wso_asset_runtime_configuration()")
            ).all()
            editor.execute(text("SET LOCAL lock_timeout='100ms'"))
            with pytest.raises(DBAPIError) as rejected:
                editor.execute(
                    text("UPDATE wso_private.asset_settings SET version=version+1")
                )
            assert rejected.value.orig.sqlstate == "55P03"
        finally:
            edit.rollback()
            transaction.rollback()


def test_session_expiry_while_waiting_asset_lock_denies_final_transition(asset_case):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue

    identifier = begin(asset_case)["asset_id"]
    pids = Queue()

    def waiting_delete():
        with asset_scope(asset_case) as db:
            db.execute(text("SET LOCAL statement_timeout='3s'"))
            pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            with pytest.raises(DBAPIError) as rejected:
                db.execute(
                    text("SELECT * FROM public.wso_tombstone_asset(:id,:s)"),
                    {"id": identifier, "s": asset_case[1]},
                )
            return rejected.value.orig.sqlstate

    with asset_case[0][3].connect() as blocker:
        transaction = blocker.begin()
        blocker.execute(
            text("SELECT id FROM public.assets WHERE id=:id FOR UPDATE"),
            {"id": identifier},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(waiting_delete)
            pid = pids.get(timeout=3)
            deadline = time.monotonic() + 2
            while True:
                with asset_case[0][3].connect() as monitor:
                    waiting = monitor.execute(
                        text(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"
                        ),
                        {"pid": pid},
                    ).scalar_one()
                if waiting == "Lock":
                    break
                assert time.monotonic() < deadline, "control never reached asset lock"
                time.sleep(0.01)
            with asset_case[0][3].begin() as editor:
                editor.execute(
                    text(
                        "UPDATE public.web_sessions SET expires_at=created_at+interval '1 microsecond' WHERE session_digest=:digest"
                    ),
                    {"digest": asset_case[1]},
                )
            transaction.rollback()
            assert future.result(timeout=3) == "42501"
    with asset_case[0][3].connect() as db:
        assert (
            db.execute(
                text("SELECT state FROM public.assets WHERE id=:id"), {"id": identifier}
            ).scalar_one()
            == "PENDING"
        )


def test_tenant_quota_serializes_concurrent_allocations(asset_case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    for _ in range(19):
        begin(asset_case)
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=3)
        try:
            begin(asset_case)
            return "created"
        except DBAPIError as error:
            return error.orig.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(attempt), pool.submit(attempt)
        assert sorted([first.result(timeout=5), second.result(timeout=5)]) == [
            "54000",
            "created",
        ]
    with asset_scope(asset_case) as db:
        assert db.execute(text("SELECT count(*) FROM public.assets")).scalar_one() == 20


def test_job_attachment_and_worker_read_require_current_reference(asset_case):
    from wso_contracts.jobs import ImportJobPayload
    from wso_contracts.models import TenantScope
    from wso_core.dispatch import Dispatcher
    from wso_core.jobs import JobFailure, JobKind, JobRegistry, JobService
    from wso_core.worker import JobWorker

    kind = "ASSET_PERMISSIONS_READ"
    registry = JobRegistry(
        (JobKind(kind, ImportJobPayload, "TENANT", effect_mode="READ"),)
    )
    identifier = ready(asset_case)
    with asset_case[0][3].begin() as db:
        db.execute(
            text(
                "INSERT INTO wso_private.job_kinds(kind,payload_version,scope_kind,permission,queue,effect_mode,max_attempts,credential_use) VALUES(:kind,1,'TENANT','OWNER','wso.default','READ',3,false)"
            ),
            {"kind": kind},
        )
        db.execute(
            text(
                "INSERT INTO wso_private.asset_job_kinds VALUES(:kind,'IMPORT_PHOTO','READ')"
            ),
            {"kind": kind},
        )
    dispatcher = None
    worker = None
    try:
        with asset_scope(asset_case) as db:
            job = JobService(db, registry=registry).enqueue(
                TenantScope(tenant_id=asset_case[0][1]["a"]),
                kind,
                ImportJobPayload(import_id=uuid4()),
                "asset-test",
            )
            db.execute(
                text("SELECT public.wso_attach_job_asset(:job,:asset)"),
                {"job": job.id, "asset": identifier},
            )
        dispatcher = Dispatcher(
            os.environ["WSO_TEST_DISPATCH_DATABASE_URL"], lambda *_: None
        )
        worker = JobWorker(os.environ["WSO_TEST_JOB_DATABASE_URL"], registry=registry)
        reference = next(
            item for item in dispatcher.claim_dispatch_batch() if item.job_id == job.id
        )
        lease = worker.claim(job.id, reference=reference)
        assert lease is not None
        with worker.step(lease) as step:
            manifest = (
                step.session.execute(
                    text("SELECT * FROM public.wso_begin_job_asset_read(:id)"),
                    {"id": identifier},
                )
                .mappings()
                .one()
            )
            assert (
                manifest["read_use"] == "JOB"
                and manifest["lease_remaining_ms"] <= 10000
            )
            assert step.session.execute(
                text("SELECT public.wso_revalidate_asset_read(:id,:lease)"),
                {"id": identifier, "lease": manifest["lease_id"]},
            ).scalar_one()
            step.session.execute(
                text("SELECT public.wso_close_asset_read(:id,:lease)"),
                {"id": identifier, "lease": manifest["lease_id"]},
            )
        worker.engine.dispose()
        worker = JobWorker(os.environ["WSO_TEST_JOB_DATABASE_URL"], registry=registry)
        with worker.step(lease) as step:
            assert (
                step.session.execute(
                    text("SELECT asset_id FROM public.wso_begin_job_asset_read(:id)"),
                    {"id": identifier},
                ).scalar_one()
                == identifier
            )
        control(asset_case, "wso_tombstone_asset", ":id,:s", {"id": identifier})
        with pytest.raises(JobFailure), worker.step(lease) as step:
            step.session.execute(
                text("SELECT * FROM public.wso_begin_job_asset_read(:id)"),
                {"id": identifier},
            ).all()
    finally:
        if worker:
            worker.engine.dispose()
        if dispatcher:
            dispatcher.engine.dispose()
        with asset_case[0][3].begin() as db:
            db.execute(
                text("DELETE FROM wso_private.asset_job_kinds WHERE kind=:kind"),
                {"kind": kind},
            )
            db.execute(
                text("DELETE FROM wso_private.job_kinds WHERE kind=:kind"),
                {"kind": kind},
            )


def test_asset_immutable_scope_metadata_and_terminal_states_are_database_constraints(
    asset_case,
):
    identifier = begin(asset_case)["asset_id"]
    for assignment in (
        "byte_size=10",
        "purpose='EVIDENCE'",
        "checksum_sha256=repeat('b',64)",
    ):
        with asset_case[0][3].begin() as db:
            db.execute(text("SET LOCAL ROLE wso_migrator"))
            with pytest.raises(DBAPIError) as rejected:
                db.execute(
                    text(f"UPDATE public.assets SET {assignment} WHERE id=:id"),
                    {"id": identifier},
                )
            assert rejected.value.orig.sqlstate == "22023"


def test_asset_audit_records_only_bounded_request_identity(asset_case):
    with asset_scope(asset_case) as db:
        db.execute(
            text(
                "SELECT set_config('wso.asset_request_id','asset-permission-request',true)"
            )
        )
        row = (
            db.execute(
                text(
                    "SELECT * FROM public.wso_begin_asset_upload(CAST(:request AS jsonb),:s)"
                ),
                {"request": json.dumps(upload_request(asset_case)), "s": asset_case[1]},
            )
            .mappings()
            .one()
        )
    with asset_case[0][3].connect() as db:
        audit = (
            db.execute(
                text(
                    "SELECT action,correlation_id,result FROM public.audit_events WHERE entity_id=:id"
                ),
                {"id": row["asset_id"]},
            )
            .mappings()
            .one()
        )
        assert dict(audit) == {
            "action": "ASSET_UPLOAD_BEGIN",
            "correlation_id": "asset-permission-request",
            "result": "OK",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain_fence", [False, True])
async def test_coordinator_sql_conversion_and_transaction_boundaries_with_memory_transport(
    asset_case,
    uncertain_fence,
):
    """Adapter double pins coordinator order only; this is not real S3 acceptance."""
    import hashlib
    import time
    from io import BytesIO

    from PIL import Image
    from sqlalchemy.orm import Session
    from wso_contracts.assets import Checksum
    from wso_contracts.models import TenantScope
    from wso_core.asset_crypto import AssetCipher
    from wso_core.asset_images import ImageValidator
    from wso_core.assets import (
        AssetActor,
        AssetAdmissionController,
        AssetGateway,
        AssetStore,
        read_asset_runtime_configuration,
    )
    from wso_core.storage import IOBudget, UploadedPart

    from tests.contract.test_asset_storage_primitives import MemoryKeys

    buffer = BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format="PNG")
    data = buffer.getvalue()
    active = False
    events = []

    @contextmanager
    def transactions(action, *, deadline_monotonic):
        nonlocal active
        with asset_scope(asset_case) as db:
            assert not active
            active = True
            try:
                yield db
            finally:
                active = False

    with Session(asset_case[0][3]) as db:
        configuration = read_asset_runtime_configuration(db)

    class Transport:
        namespace = configuration.namespace

        def __init__(self):
            self.parts = {}
            self.stored = b""

        def local_cleanup_complete(self):
            return True

        def create_multipart(self, locator, *, budget):
            assert not active
            events.append("create")
            return "test-multipart"

        def upload_part(self, locator, upload_id, part_number, ciphertext, *, budget):
            assert not active
            events.append("part")
            self.parts[part_number] = ciphertext
            return UploadedPart(part_number, "test-etag")

        def complete_multipart(self, locator, upload_id, parts, *, budget):
            assert not active
            with asset_case[0][3].connect() as observer:
                assert (
                    observer.execute(
                        text(
                            "SELECT completion_dispatched FROM wso_private.asset_uploads WHERE asset_id=:id"
                        ),
                        {"id": locator.asset_id},
                    ).scalar_one()
                    is True
                )
            events.append("complete")
            self.stored = b"".join(self.parts[p.part_number] for p in parts)

        def get(self, locator, *, max_bytes, budget):
            assert not active
            events.append("get")
            assert len(self.stored) <= max_bytes
            return BytesIO(self.stored)

    objects = Transport()
    actor = AssetActor(
        asset_case[0][1]["a"],
        asset_case[0][1]["owner"],
        asset_case[1],
        datetime.now(UTC) + timedelta(minutes=1),
        "coordinator-test",
    )
    store = AssetStore(
        actor=actor,
        transactions=transactions,
        budget=IOBudget(time.monotonic() + 120),
        objects=objects,
        cipher=AssetCipher(MemoryKeys()),
        images=ImageValidator(policy=configuration.policy),
        policy=configuration.policy,
        admission=AssetAdmissionController(upload_slots=2, read_slots=2),
        on_event=lambda event: events.append(event.name),
    )
    upload = store.begin_upload(
        TenantScope(tenant_id=actor.tenant_id),
        "IMPORT_PHOTO",
        "image/png",
        len(data),
        Checksum(algorithm="SHA256", value=hashlib.sha256(data).hexdigest()),
    )
    from wso_core.assets import _AssetRepository

    with asset_scope(asset_case) as db:
        assert (
            _AssetRepository(db, actor)
            .prepare_write(upload.asset_id, upload.id)
            .session_id
            == upload.id
        )

    async def body():
        yield data[:4]
        yield data[4:]

    if uncertain_fence:
        from wso_core.assets import AssetFailure

        original_control = store._control

        def lost_fence_ack(action, method, *args, **kwargs):
            result = original_control(action, method, *args, **kwargs)
            if method == "begin_completion":
                raise AssetFailure(503, "ASSET_UNAVAILABLE")
            return result

        store._control = lost_fence_ack
        with pytest.raises(AssetFailure):
            await AssetGateway(store=store).put_content(
                upload.asset_id,
                upload.id,
                body(),
                content_type="image/png",
                content_length=None,
                content_encoding=None,
            )
        assert (
            "complete" not in events
            and not objects.stored
            and store.admission.active_count == 0
        )
        with asset_case[0][3].connect() as observer:
            assert (
                observer.execute(
                    text(
                        "SELECT completion_dispatched FROM wso_private.asset_uploads WHERE asset_id=:id"
                    ),
                    {"id": upload.asset_id},
                ).scalar_one()
                is True
            )
        return

    await AssetGateway(store=store).put_content(
        upload.asset_id,
        upload.id,
        body(),
        content_type="image/png",
        content_length=None,
        content_encoding=None,
    )
    assert data not in objects.stored
    assert store.complete_upload(upload.asset_id).state == "READY"
    ticket = store.authorize_download(actor.user_id, upload.asset_id)
    with AssetGateway(store=store).open_download(
        upload.asset_id, ticket.token
    ) as download:
        assert b"".join(download.iter_bytes()) == data
    assert store.admission.active_count == 0
    assert (
        events.index("UPLOAD_INTENT_COMMITTED")
        < events.index("create")
        < events.index("MULTIPART_CREATED_BEFORE_RECORD")
        < events.index("part")
        < events.index("complete")
        < events.index("OBJECT_COMPLETED_BEFORE_SEAL")
        < events.index("get")
        < events.index("VALIDATED_BEFORE_FINALIZE")
    )


def test_cleanup_retry_has_bounded_jitter_and_attention_after_ten_attempts(asset_case):
    identifier = begin(asset_case)["asset_id"]
    control(asset_case, "wso_tombstone_asset", ":id,:s", {"id": identifier})
    with asset_case[0][3].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.asset_cleanup SET attempts=9,due_at=clock_timestamp()-interval '2 hours' WHERE asset_id=:id"
            ),
            {"id": identifier},
        )
    with asset_case[0][3].begin() as db:
        db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
        work = (
            db.execute(
                text("SELECT * FROM public.wso_claim_asset_cleanup(1,'attention-test')")
            )
            .mappings()
            .one()
        )
        db.execute(
            text(
                "SELECT public.wso_retry_asset_cleanup(:id,:gen,:token,'UNAVAILABLE')"
            ),
            {
                "id": work["work_id"],
                "gen": work["lease_generation"],
                "token": work["lease_token"],
            },
        )
    with asset_case[0][3].connect() as db:
        row = (
            db.execute(
                text(
                    "SELECT status,extract(epoch from due_at-clock_timestamp()) AS delay FROM wso_private.asset_cleanup WHERE asset_id=:id"
                ),
                {"id": identifier},
            )
            .mappings()
            .one()
        )
        assert row["status"] == "READY" and 299 < row["delay"] <= 305
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.asset_audit_outbox WHERE asset_id=:id AND action='ASSET_CLEANUP_ATTENTION'"
                ),
                {"id": identifier},
            ).scalar_one()
            >= 1
        )


def test_unknown_multipart_ids_get_distinct_durable_cleanup_actions(asset_case):
    upload = begin(asset_case)
    control(asset_case, "wso_tombstone_asset", ":id,:s", {"id": upload["asset_id"]})
    locator = {
        "installation_id": "8aef7c82-258d-4f72-8012-21bc64a1abb1",
        "tenant_id": str(asset_case[0][1]["a"]),
        "asset_id": str(upload["asset_id"]),
        "attempt_id": str(upload["id"]),
    }
    with asset_case[0][3].begin() as db:
        db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
        for multipart in ("provider-upload-one", "provider-upload-two"):
            assert db.execute(
                text(
                    "SELECT public.wso_reconcile_asset_candidate(CAST(:locator AS jsonb),clock_timestamp()-interval '1 hour')"
                ),
                {"locator": json.dumps({**locator, "multipart_id": multipart})},
            ).scalar_one()
    with asset_case[0][3].connect() as db:
        ids = (
            db.execute(
                text(
                    "SELECT multipart_id FROM wso_private.asset_cleanup WHERE asset_id=:id AND operation='ABORT_MULTIPART' ORDER BY multipart_id"
                ),
                {"id": upload["asset_id"]},
            )
            .scalars()
            .all()
        )
        assert ids == ["provider-upload-one", "provider-upload-two"]


def test_maintenance_finish_does_not_wait_for_business_tenant_lock(asset_case):
    from concurrent.futures import ThreadPoolExecutor

    identifier = begin(asset_case)["asset_id"]
    control(asset_case, "wso_tombstone_asset", ":id,:s", {"id": identifier})
    with asset_case[0][3].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.asset_cleanup SET due_at=clock_timestamp()-interval '1 second' WHERE asset_id=:id"
            ),
            {"id": identifier},
        )
    with asset_case[0][3].begin() as db:
        db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
        work = (
            db.execute(
                text(
                    "SELECT * FROM public.wso_claim_asset_cleanup(1,'lock-order-test')"
                )
            )
            .mappings()
            .one()
        )

    def finish():
        try:
            with asset_case[0][3].begin() as db:
                db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
                db.execute(text("SET LOCAL lock_timeout='150ms'"))
                return db.execute(
                    text(
                        "SELECT public.wso_finish_asset_cleanup(:id,:gen,:token,true)"
                    ),
                    {
                        "id": work["work_id"],
                        "gen": work["lease_generation"],
                        "token": work["lease_token"],
                    },
                ).scalar_one()
        except DBAPIError as error:
            return error.orig.sqlstate

    with asset_case[0][3].connect() as holder:
        held = holder.begin()
        try:
            holder.execute(
                text("SELECT id FROM public.tenants WHERE id=:id FOR UPDATE"),
                {"id": asset_case[0][1]["a"]},
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(finish).result(timeout=3) is True
        finally:
            held.rollback()


def test_maintenance_audit_projection_is_idempotent_and_preserves_missing_tenant(
    asset_case,
):
    tenant, identifier = asset_case[0][1]["a"], uuid4()
    missing = UUID(int=0)
    with asset_case[0][3].connect() as db:
        transaction = db.begin()
        try:
            db.execute(
                text(
                    "INSERT INTO wso_private.asset_audit_outbox(tenant_id,asset_id,action) VALUES(:tenant,:asset,'ASSET_CLEANUP_SUCCESS'),(:missing,:asset,'ASSET_CLEANUP_SUCCESS')"
                ),
                {"tenant": tenant, "asset": identifier, "missing": missing},
            )
            db.execute(text("SET LOCAL ROLE wso_asset_maintenance"))
            assert (
                db.execute(text("SELECT public.wso_flush_asset_audits(1)")).scalar_one()
                == 1
            )
            assert (
                db.execute(
                    text("SELECT public.wso_flush_asset_audits(100)")
                ).scalar_one()
                == 0
            )
            db.execute(text("RESET ROLE"))
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM public.audit_events WHERE entity_id=:asset AND action='ASSET_CLEANUP_SUCCESS'"
                    ),
                    {"asset": identifier},
                ).scalar_one()
                == 1
            )
            assert (
                db.execute(
                    text(
                        "SELECT tenant_id FROM wso_private.asset_audit_outbox WHERE asset_id=:asset"
                    ),
                    {"asset": identifier},
                ).scalar_one()
                == missing
            )
        finally:
            transaction.rollback()


@pytest.mark.parametrize("role", ["wso_app", "wso_job_worker", "wso_asset_maintenance"])
@pytest.mark.parametrize(
    "table", ["asset_uploads", "asset_reconciliation", "asset_audit_outbox"]
)
def test_runtime_cannot_read_private_asset_control_rows(asset_database, role, table):
    with asset_database.connect() as db:
        transaction = db.begin()
        try:
            db.execute(text(f"SET LOCAL ROLE {role}"))
            with pytest.raises(DBAPIError) as denied:
                db.execute(text(f"SELECT * FROM wso_private.{table}")).all()
            assert denied.value.orig.sqlstate == "42501"
        finally:
            transaction.rollback()


def writing_attempt(case):
    upload = begin(case)
    manifest = control(
        case,
        "wso_begin_asset_write",
        ":id,:upload,:s,CAST(:envelope AS jsonb)",
        {
            "id": upload["asset_id"],
            "upload": upload["id"],
            "envelope": json.dumps(ENVELOPE),
        },
    )
    values = {
        "id": upload["asset_id"],
        "generation": manifest["lease_generation"],
        "token": manifest["lease_token"],
    }
    return upload, values


def test_completion_dispatch_fence_is_required_and_monotonic(asset_case):
    upload, values = writing_attempt(asset_case)
    control(
        asset_case,
        "wso_record_asset_multipart",
        ":id,:generation,:token,:multipart,:s",
        {**values, "multipart": "known-upload"},
    )
    with pytest.raises(DBAPIError) as denied:
        control(
            asset_case, "wso_seal_asset_upload", ":id,:generation,:token,:s", values
        )
    assert denied.value.orig.sqlstate == "55000"
    control(
        asset_case, "wso_begin_asset_completion", ":id,:generation,:token,:s", values
    )
    with asset_case[0][3].connect() as restarted:
        assert (
            restarted.execute(
                text(
                    "SELECT completion_dispatched FROM wso_private.asset_uploads WHERE asset_id=:id"
                ),
                {"id": upload["asset_id"]},
            ).scalar_one()
            is True
        )
    with asset_case[0][3].begin() as db, pytest.raises(DBAPIError) as immutable:
        db.execute(
            text(
                "UPDATE wso_private.asset_uploads SET completion_dispatched=false WHERE asset_id=:id"
            ),
            {"id": upload["asset_id"]},
        )
    assert immutable.value.orig.sqlstate == "22023"
    control(asset_case, "wso_tombstone_asset", ":id,:s", {"id": upload["asset_id"]})
    with pytest.raises(DBAPIError) as late:
        control(
            asset_case,
            "wso_begin_asset_completion",
            ":id,:generation,:token,:s",
            values,
        )
    assert late.value.orig.sqlstate == "55000"


@pytest.mark.parametrize("recorded", [False, True])
def test_incomplete_attempt_without_completion_recovers_after_abort_and_restart(
    asset_case, recorded
):
    """Real SQL/restricted maintenance; transport double is not provider crash acceptance."""
    from sqlalchemy.orm import Session
    from wso_core.assets import read_asset_runtime_configuration
    from wso_core.retention import AssetMaintenance
    from wso_core.storage import (
        MultipartEntry,
        MultipartPage,
        ObjectLocator,
        ObjectPage,
    )

    upload, values = writing_attempt(asset_case)
    if recorded:
        control(
            asset_case,
            "wso_record_asset_multipart",
            ":id,:generation,:token,:multipart,:s",
            {**values, "multipart": "known-upload"},
        )
    control(asset_case, "wso_tombstone_asset", ":id,:s", {"id": upload["asset_id"]})
    with asset_case[0][3].begin() as db:
        # Exercise SQL phase predicates without representing a real process crash.
        db.execute(
            text(
                "UPDATE wso_private.asset_uploads SET lease_expires_at=clock_timestamp()-interval '1 minute' WHERE asset_id=:id"
            ),
            {"id": upload["asset_id"]},
        )
    with Session(asset_case[0][3]) as db:
        configuration = read_asset_runtime_configuration(db)
    locator = ObjectLocator(
        configuration.namespace.installation_id,
        asset_case[0][1]["a"],
        upload["asset_id"],
        upload["id"],
    )

    class Transport:
        namespace = configuration.namespace

        def __init__(self):
            self.pending = {"known-upload", "create-gap-upload"}
            self.aborted = []

        def list_objects(self, **kwargs):
            return ObjectPage((), None)

        def list_multipart(self, **kwargs):
            names = sorted(self.pending)
            if kwargs.get("cursor") == "page-two":
                names = names[1:]
            page = names[:1]
            return MultipartPage(
                tuple(
                    MultipartEntry(
                        locator, name, datetime.now(UTC) - timedelta(hours=2)
                    )
                    for name in page
                ),
                "page-two" if len(names) > 1 else None,
            )

        def delete(self, *args, **kwargs):
            pass

        def abort_multipart(self, target, upload_id, **kwargs):
            assert target == locator
            self.aborted.append(upload_id)
            self.pending.discard(upload_id)

        def local_cleanup_complete(self):
            return True

    objects = Transport()
    engine = create_engine(
        os.environ["WSO_TEST_ASSET_MAINTENANCE_DATABASE_URL"], hide_parameters=True
    )

    @contextmanager
    def transactions():
        with Session(engine) as db, db.begin():
            yield db

    try:
        for _ in range(4):
            with asset_case[0][3].begin() as db:
                db.execute(
                    text(
                        "UPDATE wso_private.asset_cleanup SET due_at=clock_timestamp()-interval '1 second' WHERE asset_id=:id"
                    ),
                    {"id": upload["asset_id"]},
                )
            AssetMaintenance(
                transactions=transactions,
                objects=objects,
                worker_id="restart-test",
                on_event=None,
            ).run_once(limit=10)
        assert (
            sorted(set(objects.aborted)) == ["create-gap-upload", "known-upload"]
            and not objects.pending
        )
        with asset_case[0][3].connect() as db:
            state = (
                db.execute(
                    text(
                        "SELECT a.state,u.wrapped_dek,u.remote_uncertain FROM public.assets a JOIN wso_private.asset_uploads u ON u.asset_id=a.id WHERE a.id=:id"
                    ),
                    {"id": upload["asset_id"]},
                )
                .mappings()
                .one()
            )
            assert dict(state) == {
                "state": "DELETED",
                "wrapped_dek": None,
                "remote_uncertain": False,
            }
        # A delayed Create/UploadPart is still an orphan after logical deletion;
        # periodic namespace reconciliation must discover and abort it separately.
        objects.pending.add("late-create-upload")
        restarted = AssetMaintenance(
            transactions=transactions,
            objects=objects,
            worker_id="later-reconciliation",
            on_event=None,
        )
        restarted.reconcile_once()
        restarted.run_once(limit=10)
        assert not objects.pending and "late-create-upload" in objects.aborted
        with pytest.raises(DBAPIError):
            control(
                asset_case,
                "wso_begin_asset_completion",
                ":id,:generation,:token,:s",
                values,
            )
    finally:
        engine.dispose()
