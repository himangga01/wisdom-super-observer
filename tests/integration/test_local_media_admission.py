"""Guarded future-owned PostgreSQL local media acceptance; no device provider."""

import hashlib
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from wso_contracts.tvt.local_media import LocalLiveRequest
from wso_core.tvt.local_media_admission import (
    LocalMediaAdmission,
    LocalMediaReader,
    LocalMediaTicketIssuer,
)
from wso_core.tvt.local_media_service import LocalMediaExecutor
from wso_core.tvt.local_service import (
    LocalDeviceFailure,
    LocalInventoryChannel,
    LocalVerificationExecutor,
)

from tests.integration.test_local_device_admission import ROOT, Key, admission, issuer
from tests.integration.test_tvt_sessions import actor_db as app_scope
from tests.tvt_parity.test_local_device_service import Provider as InventoryProvider
from tests.tvt_parity.test_local_media_service import Provider, Session

pytest_plugins = ["tests.integration.test_local_device_admission"]


@pytest.fixture(scope="module")
def media_database(local_database):
    if os.getenv("WSO_TEST_W08_LOCAL_MEDIA_ACCEPTANCE") != "1":
        pytest.skip("Root must activate guarded future-owned media SQL acceptance")
    owned = local_database["ADMIN"].url.database
    assert re.fullmatch(r"w07_directory_[0-9a-f]{32}", owned)
    with local_database["ADMIN"].connect() as db:
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
        local_database["ADMIN"]
        .url.render_as_string(hide_password=False)
        .replace("%", "%%"),
    )
    command.upgrade(cfg, "0013_tvt_local_media_leases")
    yield local_database
    command.downgrade(cfg, "0012_tvt_local_devices")


@pytest.fixture
def media_case(media_database, local_case):
    worker = admission(local_case)
    inventory = LocalVerificationExecutor(worker, InventoryProvider()).verify(
        issuer(local_case), deadline_ms=20000, correlation_id="inventory"
    )
    worker.shutdown()
    media = LocalMediaAdmission(
        media_database["WORKER"].url.render_as_string(hide_password=False), Key()
    )
    native = Session()
    executor = LocalMediaExecutor(media, Provider(native), monitor_interval=0)
    yield local_case, inventory, media, executor, native
    executor.shutdown()
    media.shutdown()


def issue(case, **changes):
    local, inventory, _, _, _ = case
    _, ids = local
    with app_scope(local, changes.pop("actor", "owner")) as db:
        body = LocalLiveRequest(
            store_id=changes.pop("store", ids["store"]),
            device_id=changes.pop("device", inventory.device_id),
            channel_id=changes.pop("channel", inventory.channels[0].id),
            expected_generation=changes.pop("generation", 1),
            inventory_revision=changes.pop("revision", inventory.inventory_revision),
        )
        return LocalMediaTicketIssuer(db, lambda: 20000).issue(
            changes.pop("session", ids["session"]),
            changes.pop("connection", ids["local"]),
            body,
        )


def start(case):
    return case[3].start(issue(case), deadline_ms=20000, correlation_id="live").lease


LIFECYCLE = {
    "membership_readd": [
        "UPDATE public.memberships SET role='STAFF' WHERE tenant_id=:t AND user_id=:u",
        "UPDATE public.memberships SET role='OWNER' WHERE tenant_id=:t AND user_id=:u",
    ],
    "link_readd": [
        "DELETE FROM public.store_connections WHERE connection_id=:c",
        "INSERT INTO public.store_connections VALUES(:t,:c,:s)",
    ],
    "store_readd": [
        "UPDATE public.stores SET active=false WHERE id=:s",
        "UPDATE public.stores SET active=true WHERE id=:s",
    ],
    "epoch": ["UPDATE public.tenants SET job_generation=job_generation+1 WHERE id=:t"],
    "generation": ["UPDATE public.connections SET generation=generation+1 WHERE id=:c"],
    "session": [
        "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:web"
    ],
    "inventory": [
        "UPDATE wso_private.tvt_local_devices SET revision=revision+1 WHERE connection_id=:c"
    ],
    "secret": [
        "UPDATE wso_private.connection_secrets SET version_id=gen_random_uuid() WHERE connection_id=:c"
    ],
}
TWO_CHANNELS = (
    LocalInventoryChannel(
        guid=UUID("10000000-0000-0000-0000-000000000001").bytes_le,
        raw_index=42,
        window_index=7,
        ordinal=1,
        kind="digital",
    ),
    LocalInventoryChannel(
        guid=UUID("10000000-0000-0000-0000-000000000002").bytes_le,
        raw_index=43,
        window_index=8,
        ordinal=2,
        kind="digital",
    ),
)
# (invalidated, state, cleanup_confirmed, never redeemed: worker_epoch IS NULL)
UNREDEEMED_CLOSED = (True, "CLOSED", True, True)
WORKER_STOPPING = (True, "STOPPING", False, False)
WORKER_CLOSED = (True, "CLOSED", True, False)


def reverify(case, **changes):
    """Publish a new two-channel revision through the real inventory path."""
    worker = admission(case[0])
    try:
        return LocalVerificationExecutor(
            worker, InventoryProvider(channels=TWO_CHANNELS)
        ).verify(
            issuer(case[0], **changes), deadline_ms=20000, correlation_id="inventory"
        )
    finally:
        worker.shutdown()


def lease_of(case, ticket):
    with case[0][0]["ADMIN"].connect() as db:
        return db.execute(
            text(
                "SELECT id FROM wso_private.tvt_local_media_leases WHERE ticket_digest=:d"
            ),
            {"d": hashlib.sha256(ticket.encode()).digest()},
        ).scalar_one()


def lease_row(case, lease_id):
    with case[0][0]["ADMIN"].connect() as db:
        return tuple(
            db.execute(
                text(
                    "SELECT invalidated,state,cleanup_confirmed,worker_epoch IS NULL FROM wso_private.tvt_local_media_leases WHERE id=:id"
                ),
                {"id": lease_id},
            ).one()
        )


def expire(case, *lease_ids):
    with case[0][0]["ADMIN"].begin() as db:
        for lease_id in lease_ids:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_leases SET heartbeat_at=statement_timestamp()-interval '31 seconds',expires_at=statement_timestamp()-interval '1 second' WHERE id=:id"
                ),
                {"id": lease_id},
            )


def change_lifecycle(case, change):
    engines, ids = case[0]
    with engines["ADMIN"].begin() as db:
        for statement in LIFECYCLE[change]:
            db.execute(
                text(statement),
                {
                    "t": ids["tenant"],
                    "u": ids["owner"],
                    "c": ids["local"],
                    "s": ids["store"],
                    "web": ids["session"],
                },
            )


def restored_issue(case, change, inventory):
    """Restore what a lifecycle change removed; return issue() arguments."""
    engines, ids = case[0]
    changes = {}
    if change == "session":
        changes["session"] = uuid4().hex * 2
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "INSERT INTO public.web_sessions(session_digest,csrf_digest,exchange_digest,issuer,subject,user_id,expires_at) VALUES(:s,:s,:e,'https://w02.test',:sub,:u,clock_timestamp()+interval '1 hour')"
                ),
                {
                    "s": changes["session"],
                    "e": uuid4().hex * 2,
                    "sub": str(ids["owner"]),
                    "u": ids["owner"],
                },
            )
    elif change == "generation":
        changes["generation"] = 2
    if change != "secret":
        # A secret rotation leaves the inventory current; all others invalidate it.
        inventory = reverify(case, **changes)
    return changes | {
        "channel": inventory.channels[0].id,
        "revision": inventory.inventory_revision,
    }


@contextmanager
def paused_owner_call(case, lock, params, call):
    """Run call(db) on an OWNER session parked behind an ADMIN-held lock.

    The body runs while the call waits at that lock, after its earlier
    statements; leaving the block releases the lock and joins the call.
    """
    engines = case[0][0]
    outcome = {}
    ready = threading.Event()

    def run():
        try:
            with app_scope(case[0], "owner") as db:
                outcome["pid"] = db.execute(
                    text("SELECT pg_backend_pid()")
                ).scalar_one()
                ready.set()
                outcome["value"] = call(db)
        except Exception as error:  # noqa: BLE001 -- surfaced to the test thread
            outcome["error"] = error
        finally:
            ready.set()

    holder = engines["ADMIN"].connect()
    caller = threading.Thread(target=run, name="paused-owner-call")
    try:
        holder.execute(text(lock), params)  # Held until the rollback below.
        caller.start()
        assert ready.wait(10) and "pid" in outcome, outcome
        end = time.monotonic() + 10
        while True:
            assert caller.is_alive(), f"call finished before pausing: {outcome}"
            with engines["ADMIN"].connect() as db:
                if db.execute(
                    text("SELECT cardinality(pg_blocking_pids(:p))>0"),
                    {"p": outcome["pid"]},
                ).scalar_one():
                    break
            assert time.monotonic() < end, "call never waited on the held lock"
            time.sleep(0.01)
        yield outcome
    finally:
        holder.rollback()
        holder.close()
        caller.join(15)
    assert not caller.is_alive()


def row_versions(case):
    """xmin changes exactly when an UPDATE writes a new row version."""
    engines, ids = case[0]
    with engines["ADMIN"].connect() as db:
        grants = {
            lease: (version, invalidated)
            for lease, version, invalidated in db.execute(
                text(
                    "SELECT lease_id,xmin::text,invalidated FROM wso_private.tvt_local_media_grants"
                )
            )
        }
        leases = dict(
            db.execute(
                text(
                    "SELECT id,xmin::text FROM wso_private.tvt_local_media_leases WHERE connection_id=:c"
                ),
                {"c": ids["local"]},
            ).all()
        )
    return grants, leases


def test_media_sql_scope_replay_and_table_privileges(media_case):
    local, _, worker, executor, _ = media_case
    ticket = issue(media_case)
    executor.start(ticket, deadline_ms=20000, correlation_id="live")
    with pytest.raises(LocalDeviceFailure):
        executor.start(ticket, deadline_ms=20000, correlation_id="replay")
    for changes in (
        {"actor": "staff"},
        {"store": local[1]["foreign_store"]},
        {"session": "f" * 64},
        {"channel": uuid4()},
        {"device": uuid4()},
        {"generation": 2},
        {"revision": 2},
    ):
        with pytest.raises(LocalDeviceFailure):
            issue(media_case, **changes)
    for role in ("APP", "WORKER", "JOB", "DISPATCH"):
        with pytest.raises(DBAPIError), local[0][role].begin() as db:
            db.execute(text("SELECT * FROM wso_private.tvt_local_media_leases"))
    assert worker.worker_epoch is not None


def test_media_sql_permission_proof_not_inventory_authority(media_case):
    media_case[4].proof = replace(media_case[4].proof, live_permission=False)
    with pytest.raises(LocalDeviceFailure):
        start(media_case)
    with media_case[0][0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_local_media_grants g JOIN wso_private.tvt_local_media_leases l ON l.id=g.lease_id WHERE l.tenant_id=:t AND l.connection_id=:c AND l.session_digest=:s"
                ),
                {
                    "t": media_case[0][1]["tenant"],
                    "c": media_case[0][1]["local"],
                    "s": media_case[0][1]["session"],
                },
            ).scalar_one()
            == 0
        )


def test_media_sql_heartbeat_exact_session_and_expiry_cannot_revive(media_case):
    local, _, _, executor, _ = media_case
    view = start(media_case)
    with app_scope(local, "owner") as db:
        refreshed = LocalMediaReader(db).heartbeat(local[1]["session"], view.id)
    assert refreshed.state == "NEGOTIATING"
    with app_scope(local, "owner") as db, pytest.raises(LocalDeviceFailure):
        LocalMediaReader(db).heartbeat("f" * 64, view.id)
    with local[0]["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_leases SET heartbeat_at=statement_timestamp()-interval '31 seconds',expires_at=statement_timestamp()-interval '1 second' WHERE id=:id"
            ),
            {"id": view.id},
        )
    with app_scope(local, "owner") as db, pytest.raises(LocalDeviceFailure):
        LocalMediaReader(db).heartbeat(local[1]["session"], view.id)
    assert not executor.current(view.id)
    executor.sweep()
    assert media_case[4].closed == 1


@pytest.mark.parametrize(
    "change",
    [
        "membership_readd",
        "link_readd",
        "store_readd",
        "epoch",
        "generation",
        "session",
        "inventory",
        "secret",
    ],
)
def test_media_sql_lifecycle_tombstones_never_revive(media_case, change):
    local, _, _, executor, _ = media_case
    engines, ids = local
    view = start(media_case)
    statements = LIFECYCLE[change]
    with engines["ADMIN"].begin() as db:
        for statement in statements:
            db.execute(
                text(statement),
                {
                    "t": ids["tenant"],
                    "u": ids["owner"],
                    "c": ids["local"],
                    "s": ids["store"],
                    "web": ids["session"],
                },
            )
        row = db.execute(
            text(
                "SELECT invalidated,state FROM wso_private.tvt_local_media_leases WHERE id=:id"
            ),
            {"id": view.id},
        ).one()
        assert row == (True, "STOPPING")
    assert not executor.current(view.id)
    executor.sweep()
    assert media_case[4].closed == 1


def test_media_sql_control_purpose_replay_and_confirmed_stop(media_case):
    local, _, worker, executor, native = media_case
    view = start(media_case)
    with app_scope(local, "owner") as db:
        offer = LocalMediaTicketIssuer(db, lambda: 20000).issue_control(
            local[1]["session"], view.id, "offer"
        )
    from wso_core.tvt.local_service import LocalVerifyBudget

    with pytest.raises(LocalDeviceFailure):
        worker.redeem_control(offer, "stop", budget=LocalVerifyBudget(20000))
    assert executor.authorize_control(offer, "offer", deadline_ms=20000) == view.id
    with pytest.raises(LocalDeviceFailure):
        executor.authorize_control(offer, "offer", deadline_ms=20000)
    with app_scope(local, "owner") as db:
        stop = LocalMediaTicketIssuer(db, lambda: 20000).issue_control(
            local[1]["session"], view.id, "stop"
        )
    executor.sweep()  # Prove the stop/watchdog race also returns a final receipt.
    final = executor.stop(stop, deadline_ms=20000, correlation_id="stop")
    assert final.lease.state == "CLOSED" and native.closed == 1


def test_media_sql_playing_requires_independent_delivery_proof(media_case):
    view = start(media_case)
    with pytest.raises(LocalDeviceFailure):
        media_case[3].playing(view.id, media_case[4].proof)
    proof = replace(
        media_case[4].proof,
        codec_supported=True,
        framing_verified=True,
        timing_verified=True,
        codec="h264",
    )
    assert media_case[3].playing(view.id, proof).state == "PLAYING"


def test_media_sql_external_cleanup_barrier_holds_stopping_until_all_originals_close(
    media_case,
):
    local, _, _, executor, native = media_case
    view = start(media_case)
    done = [False]
    executor.attach_retirement(view.id, lambda: done[0])
    assert executor.close(view.id) is False
    assert native.closed == 1
    with app_scope(local, "owner") as db:
        assert (
            LocalMediaReader(db).get(local[1]["session"], view.id).state == "STOPPING"
        )
    done[0] = True
    assert executor.finish_stop(view.id, correlation_id="stop").lease.state == "CLOSED"
    with app_scope(local, "owner") as db:
        assert LocalMediaReader(db).get(local[1]["session"], view.id).state == "CLOSED"


def test_media_sql_playing_ticket_purpose_replay_and_stop_cannot_grant_late_playing(
    media_case,
):
    local, _, worker, executor, _ = media_case
    from wso_core.tvt.local_service import LocalVerifyBudget

    view = start(media_case)
    with app_scope(local, "owner") as db:
        playing = LocalMediaTicketIssuer(db, lambda: 20000).issue_control(
            local[1]["session"], view.id, "playing"
        )
    for wrong in ("offer", "stop"):
        with pytest.raises(LocalDeviceFailure):
            worker.redeem_control(playing, wrong, budget=LocalVerifyBudget(20000))
    assert executor.authorize_control(playing, "playing", deadline_ms=20000) == view.id
    with pytest.raises(LocalDeviceFailure):
        executor.authorize_control(playing, "playing", deadline_ms=20000)
    with app_scope(local, "owner") as db:
        late = LocalMediaTicketIssuer(db, lambda: 20000).issue_control(
            local[1]["session"], view.id, "playing"
        )
        LocalMediaTicketIssuer(db, lambda: 20000).issue_control(
            local[1]["session"], view.id, "stop"
        )
    with pytest.raises(LocalDeviceFailure):
        executor.authorize_control(late, "playing", deadline_ms=20000)


@pytest.mark.parametrize("change", list(LIFECYCLE))
def test_media_sql_unredeemed_revocation_closes_and_frees_the_channel(
    media_case, change
):
    executor, native = media_case[3], media_case[4]
    inventory = reverify(media_case)
    first, second = (channel.id for channel in inventory.channels)
    revision = inventory.inventory_revision
    ticket = issue(media_case, channel=first, revision=revision)
    unredeemed = lease_of(media_case, ticket)
    redeemed = executor.start(
        issue(media_case, channel=second, revision=revision),
        deadline_ms=20000,
        correlation_id="live",
    ).lease.id
    change_lifecycle(media_case, change)
    # No worker ever owned it, so nothing external remains: CLOSED, not stranded.
    assert lease_row(media_case, unredeemed) == UNREDEEMED_CLOSED
    # A redeemed lease still waits for its own worker's confirmed cleanup.
    assert lease_row(media_case, redeemed) == WORKER_STOPPING
    with pytest.raises(LocalDeviceFailure):
        executor.start(ticket, deadline_ms=20000, correlation_id="replay")
    executor.sweep()
    assert lease_row(media_case, redeemed)[1] == "CLOSED" and native.closed == 1
    retry = restored_issue(media_case, change, inventory)
    # A generation change re-creates channel rows; every other change keeps the id.
    assert retry["channel"] == first or change == "generation"
    assert issue(media_case, **retry)


def test_media_sql_api_read_closes_unredeemed_lease_but_keeps_worker_stopping(
    media_case,
):
    local, _, _, executor, native = media_case
    engines, ids = local
    unredeemed = lease_of(media_case, issue(media_case))
    with engines["ADMIN"].begin() as db:
        # Login window over, TTL not expired: the expiry sweep cannot see it.
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_leases SET issued_at=statement_timestamp()-interval '25 seconds',login_expires_at=statement_timestamp()-interval '5 seconds' WHERE id=:id"
            ),
            {"id": unredeemed},
        )
    with app_scope(local, "owner") as db:
        assert LocalMediaReader(db).get(ids["session"], unredeemed).state == "CLOSED"
    assert lease_row(media_case, unredeemed) == UNREDEEMED_CLOSED
    view = start(media_case)  # The same connection+channel is issuable again.
    expire(media_case, view.id)
    with app_scope(local, "owner") as db:
        assert LocalMediaReader(db).get(ids["session"], view.id).state == "STOPPING"
    assert lease_row(media_case, view.id) == WORKER_STOPPING
    executor.sweep()
    assert lease_row(media_case, view.id)[1] == "CLOSED" and native.closed == 1


def test_media_sql_expiry_sweep_closes_stranded_unredeemed_tombstone(media_case):
    executor, native = media_case[3], media_case[4]
    inventory = reverify(media_case)
    first, second = (channel.id for channel in inventory.channels)
    revision = inventory.inventory_revision
    stranded = lease_of(media_case, issue(media_case, channel=first, revision=revision))
    owned = executor.start(
        issue(media_case, channel=second, revision=revision),
        deadline_ms=20000,
        correlation_id="live",
    ).lease.id
    with media_case[0][0]["ADMIN"].begin() as db:
        # The shape earlier revoke/API paths left: never redeemed, yet STOPPING.
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_leases SET invalidated=true,state='STOPPING' WHERE id=:id"
            ),
            {"id": stranded},
        )
    expire(media_case, stranded, owned)
    # The next issue's expiry sweep retires the tombstone and frees its channel.
    assert issue(media_case, channel=first, revision=revision)
    assert lease_row(media_case, stranded) == UNREDEEMED_CLOSED
    # The same sweep hands an expired redeemed lease to its worker unchanged.
    assert lease_row(media_case, owned) == WORKER_STOPPING
    executor.sweep()
    assert lease_row(media_case, owned)[1] == "CLOSED" and native.closed == 1


def test_media_sql_revocation_rewrites_only_the_rows_it_revokes(media_case):
    executor = media_case[3]
    _, ids = media_case[0]
    inventory = reverify(media_case)
    first, second = (channel.id for channel in inventory.channels)

    def begin(channel):
        return executor.start(
            issue(media_case, channel=channel, revision=inventory.inventory_revision),
            deadline_ms=20000,
            correlation_id="live",
        ).lease.id

    for _ in range(3):  # Finished history: CLOSED leases with invalidated grants.
        assert executor.close(begin(first))
    settled = [False]
    tombstone = begin(second)  # Invalidated STOPPING while its cleanup is pending.
    executor.attach_retirement(tombstone, lambda: settled[0])
    assert executor.close(tombstone) is False
    fresh = begin(first)
    grants, leases = row_versions(media_case)
    assert len(grants) >= 5 and not grants[fresh][1]
    assert all(grants[lease][1] for lease in leases if lease != fresh)
    with media_case[0][0]["ADMIN"].begin() as db:
        db.execute(
            text("UPDATE public.connections SET generation=generation+1 WHERE id=:c"),
            {"c": ids["local"]},
        )
    later_grants, later_leases = row_versions(media_case)
    # Only the lease this event revoked and its own grant get new row versions.
    assert {key for key, value in later_grants.items() if grants[key] != value} == {
        fresh
    }
    assert {key for key, value in later_leases.items() if leases[key] != value} == {
        fresh
    }
    assert later_grants[fresh][1] is True
    assert lease_row(media_case, fresh) == WORKER_STOPPING
    assert lease_row(media_case, tombstone) == WORKER_STOPPING
    settled[0] = True
    assert executor.close(tombstone)


def test_media_sql_open_leases_have_a_partial_revocation_index(media_database):
    with media_database["ADMIN"].connect() as db:
        definition = db.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname='wso_private' AND indexname='local_media_open'"
            )
        ).scalar_one_or_none()
    assert definition is not None
    assert definition.endswith(
        "tvt_local_media_leases USING btree (tenant_id) WHERE (state <> 'CLOSED'::text)"
    )


def test_media_sql_api_read_racing_worker_close_cannot_revive_it(media_case):
    local, _, _, executor, _ = media_case
    _, ids = local
    view = start(media_case)

    def read(db):
        return LocalMediaReader(db, lambda: 20000).get(ids["session"], view.id)

    # Race order, made deterministic: the read loads the live row, waits at a
    # held store lock while the worker's CLOSE commits, then decides and writes.
    with paused_owner_call(
        media_case,
        "SELECT 1 FROM public.stores WHERE id=:s FOR UPDATE",
        {"s": ids["store"]},
        read,
    ) as outcome:
        assert executor.close(view.id)
        assert lease_row(media_case, view.id) == WORKER_CLOSED
    assert "error" not in outcome and outcome["value"].state == "CLOSED"
    assert lease_row(media_case, view.id) == WORKER_CLOSED
    # Plain order (close, then read) and the freed channel.
    with app_scope(local, "owner") as db:
        assert LocalMediaReader(db).get(ids["session"], view.id).state == "CLOSED"
    assert lease_row(media_case, view.id) == WORKER_CLOSED
    assert issue(media_case)


def test_media_sql_stop_control_racing_close_cannot_revive_it(media_case):
    local, _, _, executor, _ = media_case
    engines, ids = local
    view = start(media_case)

    def stop(db):
        return LocalMediaTicketIssuer(db, lambda: 20000).issue_control(
            ids["session"], view.id, "stop"
        )

    # The stop control passes live(), then waits at its advisory lock.
    with paused_owner_call(
        media_case, "SELECT pg_advisory_xact_lock(711300002)", {}, stop
    ) as outcome:
        # live() share-locked the grant, so the worker CLOSE (which must
        # invalidate that grant) cannot commit inside this window.
        with engines["ADMIN"].connect() as db, pytest.raises(DBAPIError) as held:
            db.execute(
                text(
                    "SELECT 1 FROM wso_private.tvt_local_media_grants WHERE lease_id=:id FOR NO KEY UPDATE NOWAIT"
                ),
                {"id": view.id},
            )
        assert held.value.orig.sqlstate == "55P03"
        # Any other path leaving the row CLOSED meanwhile must still win.
        with engines["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_leases SET invalidated=true,state='CLOSED',cleanup_confirmed=true WHERE id=:id"
                ),
                {"id": view.id},
            )
    assert "error" not in outcome  # The stop receipt is still issued.
    assert lease_row(media_case, view.id) == WORKER_CLOSED
    assert executor.close(view.id)  # The worker settles its own custody too.
    # Plain order on a fresh lease: the worker CLOSE commits, then a stop.
    fresh = start(media_case)
    assert executor.close(fresh.id)
    with app_scope(local, "owner") as db, pytest.raises(LocalDeviceFailure):
        LocalMediaTicketIssuer(db, lambda: 20000).issue_control(
            ids["session"], fresh.id, "stop"
        )
    assert lease_row(media_case, fresh.id) == WORKER_CLOSED
    assert issue(media_case)
