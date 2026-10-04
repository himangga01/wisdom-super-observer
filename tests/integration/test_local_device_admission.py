"""Purpose-bound local SQL acceptance; activated guarded owned DB only."""

import importlib.util
import os
import re
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from wso_contracts.tvt.local_device import LocalVerifyRequest
from wso_core.connections import ConnectionService
from wso_core.tvt.local_credentials import LocalDeviceCredentials
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget

from tests.integration.test_tvt_domain_scope import seed_foundation
from tests.integration.test_tvt_sessions import actor_db as app_scope

ROOT = Path(__file__).resolve().parents[2]
pytest_plugins = ["tests.integration.test_tvt_directory_admission"]


def test_local_revision_exists_as_a_separate_scope():
    path = ROOT / "infra/migrations/versions/0012_tvt_local_devices.py"
    assert path.exists(), "local admission migration missing"
    spec = importlib.util.spec_from_file_location("local_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0011_tvt_directory_read_tickets"


@pytest.fixture(scope="module")
def local_database(request):
    if os.getenv("WSO_TEST_W08_LOCAL_ACCEPTANCE") != "1":
        pytest.skip("Root must activate the guarded owned local SQL fixture")
    # Reuse the existing create/identity-check/snapshot/drop owner. Its URLs
    # initially name the source DB; only this fixture's fresh DB is migrated.
    engines = request.getfixturevalue("directory_database")
    owned = engines["ADMIN"].url.database
    assert re.fullmatch(r"w07_directory_[0-9a-f]{32}", owned)
    with engines["ADMIN"].connect() as db:
        assert db.execute(text("SELECT current_database()")).scalar_one() == owned
        assert (
            db.execute(
                text(
                    "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"
                )
            )
            .scalar_one()
            .startswith("owned-w07-directory-")
        )
    cfg = Config(str(ROOT / "infra/alembic.ini"))
    cfg.set_main_option(
        "sqlalchemy.url",
        engines["ADMIN"].url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    command.upgrade(cfg, "0012_tvt_local_devices")
    yield engines
    command.downgrade(cfg, "0011_tvt_directory_read_tickets")


class Key:
    def encryption_key(self):
        return bytes(range(32))


@pytest.fixture
def local_case(local_database):
    engines = local_database
    ids = seed_foundation(engines["ADMIN"])
    ids["session"] = uuid4().hex * 2
    with engines["ADMIN"].begin() as db:
        db.execute(
            text(
                "INSERT INTO public.web_sessions(session_digest,csrf_digest,exchange_digest,issuer,subject,user_id,expires_at) VALUES(:s,:s,:e,'https://w02.test',:sub,:u,clock_timestamp()+interval '1 hour')"
            ),
            {
                "s": ids["session"],
                "e": uuid4().hex * 2,
                "sub": str(ids["owner"]),
                "u": ids["owner"],
            },
        )
    with app_scope((engines, ids), "owner") as db:
        connection = ConnectionService(db, Key()).mutate(
            "create",
            {
                "kind": "TVT_DEVICE",
                "alias": "Device",
                "site": "Human place",
                "store_ids": [str(ids["store"])],
            },
            credentials=LocalDeviceCredentials(
                serial="TEST123", username="private-user", password="private-password"
            ).to_encrypt_bytes(),
        )
    ids["local"] = connection.id
    return engines, ids


def issuer(case, **changes):
    from wso_core.tvt.local_admission import LocalDeviceTicketIssuer

    _engines, ids = case
    with app_scope(case, changes.pop("actor", "owner")) as db:
        return LocalDeviceTicketIssuer(db, lambda: 20000).issue(
            changes.pop("session", ids["session"]),
            changes.pop("connection", ids["local"]),
            LocalVerifyRequest(
                store_id=changes.pop("store", ids["store"]),
                expected_generation=changes.pop("generation", 1),
            ),
        )


def admission(case):
    from wso_core.tvt.local_admission import LocalDeviceAdmission

    return LocalDeviceAdmission(
        case[0]["WORKER"].url.render_as_string(hide_password=False), Key()
    )


def test_sql_replay_foreign_scope_and_private_table_denial(local_case):
    worker, budget = admission(local_case), LocalVerifyBudget(20000)
    ticket = issuer(local_case)
    lease = worker.redeem(ticket, budget=budget)
    with pytest.raises(LocalDeviceFailure):
        worker.redeem(ticket, budget=budget)
    worker.close(lease, budget=budget)
    for changes in (
        {"actor": "staff"},
        {"connection": local_case[1]["connection"]},
        {"store": local_case[1]["foreign_store"]},
        {"generation": 2},
        {"session": "f" * 64},
    ):
        with pytest.raises(LocalDeviceFailure):
            issuer(local_case, **changes)
    for role in ("APP", "WORKER", "JOB", "DISPATCH"):
        with pytest.raises(DBAPIError), local_case[0][role].begin() as db:
            db.execute(text("SELECT * FROM wso_private.tvt_local_device_tickets"))
    worker.shutdown()


def test_sql_cancelled_native_result_cannot_persist_inventory(local_case):
    from wso_core.tvt.local_service import LocalVerificationExecutor

    from tests.tvt_parity.test_local_device_service import Provider

    engines, ids = local_case
    worker, cancel = admission(local_case), Event()
    with pytest.raises(LocalDeviceFailure) as caught:
        LocalVerificationExecutor(worker, Provider(cancel.set)).verify(
            issuer(local_case),
            deadline_ms=20000,
            correlation_id="cancel-test",
            cancel=cancel,
        )
    assert caught.value.code == "LOCAL_DEVICE_CANCELLED"
    with engines["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_local_devices WHERE connection_id=:c"
                ),
                {"c": ids["local"]},
            ).scalar_one()
            == 0
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_local_device_tickets WHERE connection_id=:c"
                ),
                {"c": ids["local"]},
            ).scalar_one()
            == 0
        )
    worker.shutdown()


@pytest.mark.parametrize(
    "change",
    [
        "expiry",
        "epoch",
        "session",
        "membership_readd",
        "link_readd",
        "generation",
        "inactive_readd",
    ],
)
def test_sql_lifecycle_change_never_revives_ticket(local_case, change):
    engines, ids = local_case
    worker, budget = admission(local_case), LocalVerifyBudget(20000)
    lease = worker.redeem(issuer(local_case), budget=budget)
    with engines["ADMIN"].begin() as db:
        params = {
            "t": ids["tenant"],
            "c": ids["local"],
            "u": ids["owner"],
            "s": ids["store"],
            "web": ids["session"],
        }
        sql = {
            "expiry": "UPDATE wso_private.tvt_local_device_tickets SET issued_at=statement_timestamp()-interval '30 seconds',expires_at=statement_timestamp()-interval '1 second' WHERE tenant_id=:t",
            "epoch": "UPDATE public.tenants SET job_generation=job_generation+1 WHERE id=:t",
            "session": "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:web",
            "membership_readd": "UPDATE public.memberships SET role='STAFF' WHERE tenant_id=:t AND user_id=:u; UPDATE public.memberships SET role='OWNER' WHERE tenant_id=:t AND user_id=:u",
            "link_readd": "DELETE FROM public.store_connections WHERE connection_id=:c; INSERT INTO public.store_connections VALUES(:t,:c,:s)",
            "generation": "UPDATE public.connections SET generation=2 WHERE id=:c",
            "inactive_readd": "UPDATE public.stores SET active=false WHERE id=:s; UPDATE public.stores SET active=true WHERE id=:s",
        }[change]
        for statement in sql.split(";"):
            db.execute(text(statement), params)
        if change == "expiry":
            assert db.execute(
                text(
                    "SELECT issued_at<expires_at,expires_at<=issued_at+interval '30 seconds',expires_at<statement_timestamp() FROM wso_private.tvt_local_device_tickets WHERE connection_id=:c"
                ),
                params,
            ).one() == (True, True, True)
    with pytest.raises(LocalDeviceFailure):
        worker.run(
            lease, lambda *_: pytest.fail("revoked secret callback ran"), budget=budget
        )
    worker.close(lease, budget=budget)
    worker.shutdown()


def test_sql_real_encrypted_roundtrip_and_safe_channel_projection(local_case):
    from wso_core.tvt.local_service import LocalVerificationExecutor

    from tests.tvt_parity.test_local_device_service import Provider

    engines, ids = local_case
    worker = admission(local_case)
    view = LocalVerificationExecutor(worker, Provider()).verify(
        issuer(local_case), deadline_ms=20000, correlation_id="sql-test"
    )
    assert view.inventory_state == "AVAILABLE" and len(view.channels) == 1
    assert view.channels[0].label == "Channel 1"
    assert view.connection_id == ids["local"]
    assert view.request_id == "sql-test"
    with engines["ADMIN"].connect() as db:
        row = db.execute(
            text(
                "SELECT raw_index,window_index FROM wso_private.tvt_local_channels WHERE device_id=:d"
            ),
            {"d": view.device_id},
        ).one()
        assert row == (42, 7)
        assert (
            db.execute(
                text("SELECT status FROM public.connections WHERE id=:c"),
                {"c": ids["local"]},
            ).scalar_one()
            == "NOT_VERIFIED"
        )
        audit = str(
            db.execute(
                text("SELECT * FROM audit_events WHERE entity_id=:c"),
                {"c": ids["local"]},
            ).all()
        )
    for marker in ("TEST123", "private-user", "private-password", "raw_index", "guid"):
        assert marker not in view.model_dump_json() + audit
    with app_scope(local_case, "owner") as db:
        read = worker.inventory(db, ids["local"], ids["store"], correlation_id="read")
        assert read.channels == view.channels
    worker.shutdown()


@pytest.mark.parametrize("change", ["membership_readd", "link_readd", "inactive_readd"])
def test_sql_published_inventory_tombstone_survives_restore(local_case, change):
    from wso_core.tvt.local_admission import LocalDeviceInventoryReader
    from wso_core.tvt.local_service import LocalVerificationExecutor

    from tests.tvt_parity.test_local_device_service import Provider

    engines, ids = local_case
    worker = admission(local_case)
    original = LocalVerificationExecutor(worker, Provider()).verify(
        issuer(local_case), deadline_ms=20000, correlation_id="publish-test"
    )
    with engines["ADMIN"].begin() as db:
        params = {
            "t": ids["tenant"],
            "u": ids["owner"],
            "c": ids["local"],
            "s": ids["store"],
        }
        statements = {
            "membership_readd": [
                "UPDATE public.memberships SET role='STAFF' WHERE tenant_id=:t AND user_id=:u",
                "UPDATE public.memberships SET role='OWNER' WHERE tenant_id=:t AND user_id=:u",
            ],
            "link_readd": [
                "DELETE FROM public.store_connections WHERE connection_id=:c",
                "INSERT INTO public.store_connections VALUES(:t,:c,:s)",
            ],
            "inactive_readd": [
                "UPDATE public.stores SET active=false WHERE id=:s",
                "UPDATE public.stores SET active=true WHERE id=:s",
            ],
        }[change]
        for statement in statements:
            db.execute(text(statement), params)
    with app_scope(local_case, "owner") as db:
        stale = LocalDeviceInventoryReader(db).get(
            ids["local"], ids["store"], correlation_id="read-stale"
        )
    assert stale.inventory_state == "STALE" and stale.channels == ()
    assert stale.device_id == original.device_id
    assert stale.inventory_revision == original.inventory_revision
    worker.shutdown()
