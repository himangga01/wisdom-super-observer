"""Mux admission unit boundaries plus explicitly guarded owned SQL acceptance."""

import importlib
import importlib.util
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from tests.integration.test_local_media_admission import (
    InventoryProvider,
    Key,
    LocalVerificationExecutor,
    admission,
    app_scope,
    issuer,
)

pytest_plugins = ["tests.integration.test_local_media_admission"]
ROOT = Path(__file__).resolve().parents[2]


def facade():
    name = "wso_core.tvt.local_media_mux_admission"
    assert importlib.util.find_spec(name), "purpose-specific admission is missing"
    return importlib.import_module(name)


def test_copied_or_foreign_grant_never_reaches_sql():
    module = facade()
    from wso_core.tvt.local_media_mux_types import (
        _GRANT_SEAL,
        MuxScopeKey,
        TransportGrant,
    )

    scope = MuxScopeKey(
        uuid4(),
        1,
        uuid4(),
        bytes(32),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        uuid4(),
        1,
        uuid4(),
    )
    gate = module.SqlMuxAdmission(
        "postgresql+psycopg://unused", Key(), clock=lambda: 1.0
    )
    foreign = TransportGrant(
        scope=scope,
        expires_monotonic=10,
        native_generation=uuid4(),
        _authority=object(),
        _seal=_GRANT_SEAL,
    )
    assert gate.current_transport(foreign) is False
    assert gate.current_transport(replace(foreign, _seal=_GRANT_SEAL)) is False
    assert gate.dispose() is True


def test_viewer_receipt_cannot_close_epoch():
    module = facade()
    gate = module.SqlMuxAdmission("postgresql+psycopg://unused", Key())
    from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL, ViewerCleanupReceipt

    receipt = ViewerCleanupReceipt(
        lease_id=uuid4(),
        registration_id=uuid4(),
        decoder_settled=True,
        peer_settled=True,
        media_cleared=True,
        _authority=object(),
        _seal=_CUSTODY_SEAL,
    )
    from wso_core.tvt.local_service import LocalDeviceFailure

    with pytest.raises(LocalDeviceFailure):
        gate.finish_epoch(object(), receipt)
    assert gate.dispose() is True


def historical(db):
    return db.execute(
        text(
            "SELECT n.nspname,p.proname,pg_get_functiondef(p.oid),p.proacl::text,pg_get_userbyid(p.proowner) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.proname LIKE 'wso_tvt_local_media_%' ORDER BY n.nspname,p.proname,p.oid"
        )
    ).all()


@pytest.fixture(scope="module")
def mux_database(media_database):
    assert os.environ.get("WSO_TEST_W08_LOCAL_MEDIA_MUX_ACCEPTANCE") == "1", (
        "Root guarded mux wrapper is required"
    )
    owned = media_database["ADMIN"].url.database
    assert re.fullmatch(r"w07_directory_[0-9a-f]{32}", owned)
    with media_database["ADMIN"].connect() as db:
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
        before = historical(db)
    cfg = Config(str(ROOT / "infra/alembic.ini"))
    cfg.set_main_option(
        "sqlalchemy.url",
        media_database["ADMIN"]
        .url.render_as_string(hide_password=False)
        .replace("%", "%%"),
    )
    command.upgrade(cfg, "0017_tvt_main_return_retention")
    try:
        with media_database["ADMIN"].connect() as db:
            after = historical(db)
            assert all(row in after for row in before)
        yield media_database
    finally:
        command.downgrade(cfg, "0015_tvt_local_media_capacity")
        with media_database["ADMIN"].connect() as db:
            assert historical(db) == before


@pytest.fixture
def mux_case(mux_database, local_case):
    worker = admission(local_case)
    from tests.integration.test_local_media_admission import TWO_CHANNELS

    inventory = LocalVerificationExecutor(
        worker, InventoryProvider(channels=TWO_CHANNELS)
    ).verify(issuer(local_case), deadline_ms=20000, correlation_id="mux-inventory")
    worker.shutdown()
    gate = facade().SqlMuxAdmission(
        mux_database["WORKER"].url.render_as_string(hide_password=False), Key()
    )
    yield local_case, inventory, gate
    gate.shutdown()
    # No runtime/native owner was constructed by these SQL tests. Explicitly
    # release this fixture's pool, separately from product cleanup acceptance.
    gate._engine.dispose()
    # This synthetic fixture never creates native/decoder originals. Test-owned
    # SQL rows are explicitly retired without claiming a physical receipt.
    with mux_database["ADMIN"].begin() as db:
        params = {"c": local_case[1]["local"]}
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_leases SET mux_viewer_settled=true,mux_native_settled=true,state='CLOSED',invalidated=true,cleanup_confirmed=true WHERE connection_id=:c"
            ),
            params,
        )
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_slots SET state='CLOSED' WHERE master_id IN (SELECT id FROM wso_private.tvt_local_media_masters WHERE connection_id=:c)"
            ),
            params,
        )
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_masters SET state='CLOSED',cleanup_confirmed=true WHERE connection_id=:c"
            ),
            params,
        )
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_focus_refs SET state='CANCELLED' WHERE master_id IN (SELECT id FROM wso_private.tvt_local_media_masters WHERE connection_id=:c)"
            ),
            params,
        )
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_walls SET state='CLOSED' WHERE id IN (SELECT mux_wall_id FROM wso_private.tvt_local_media_leases WHERE connection_id=:c)"
            ),
            params,
        )


def test_new_rls_execute_and_caps(mux_database):
    with mux_database["ADMIN"].connect() as db:
        rows = db.execute(
            text(
                "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wso_private' AND c.relname IN ('tvt_local_media_walls','tvt_local_media_masters','tvt_local_media_slots','tvt_local_media_focus_refs','tvt_local_media_mux_controls')"
            )
        ).all()
        assert len(rows) == 5
        assert all(row[1:] == (True, True, "wso_tvt_local_owner") for row in rows)
        for table, *_ in rows:
            for role in ("wso_app", "wso_connection_worker", "wso_job_worker"):
                assert (
                    db.execute(
                        text(
                            "SELECT has_table_privilege(:r,:t,'SELECT,INSERT,UPDATE,DELETE')"
                        ),
                        {"r": role, "t": "wso_private." + table},
                    ).scalar_one()
                    is False
                )
        assert (
            db.execute(
                text(
                    "SELECT has_function_privilege('wso_app','public.wso_tvt_local_media_master_login(text,uuid,uuid)','EXECUTE')"
                )
            ).scalar_one()
            is False
        )
        assert (
            db.execute(
                text(
                    "SELECT has_function_privilege('wso_connection_worker','public.wso_tvt_local_media_wall_issue(text,integer)','EXECUTE')"
                )
            ).scalar_one()
            is False
        )


def wall(case):
    local, _, _ = case
    with app_scope(local, "owner") as db:
        value = db.execute(
            text("SELECT public.wso_tvt_local_media_wall_issue(:s,30)"),
            {"s": local[1]["session"]},
        ).scalar_one()
    assert value
    return value["id"]


def shared_ticket(case, wall_id, channel=None):
    local, inv, _ = case
    with app_scope(local, "owner") as db:
        return db.execute(
            text(
                "SELECT public.wso_tvt_local_media_shared_issue(:s,:c,:store,:dev,:ch,1,:rev,'sub',30,:wall)"
            ),
            {
                "s": local[1]["session"],
                "c": local[1]["local"],
                "store": local[1]["store"],
                "dev": inv.device_id,
                "ch": channel or inv.channels[0].id,
                "rev": inv.inventory_revision,
                "wall": wall_id,
            },
        ).scalar_one()


def test_stopping_viewer_blocks_shared_issue(mux_case):
    from sqlalchemy.exc import DBAPIError
    from wso_core.tvt.local_service import LocalVerifyBudget

    w = wall(mux_case)
    ticket = shared_ticket(mux_case, w)
    gate = mux_case[2]
    lease = gate.redeem(ticket, budget=LocalVerifyBudget(20000))
    gate.close(lease, cleanup_confirmed=False)
    with pytest.raises(DBAPIError) as caught:
        shared_ticket(mux_case, w)
    assert caught.value.orig.sqlstate == "53300"


def test_legacy_pending_cleanup_not_reclassified(mux_case):
    from wso_core.tvt.local_service import LocalVerifyBudget

    from tests.integration.test_local_media_admission import issue

    local, inv, gate = mux_case
    ticket = issue((local, inv, gate, None, None))
    lease = gate.redeem(ticket, budget=LocalVerifyBudget(20000))
    gate.close(lease, cleanup_confirmed=False)
    with local[0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT state,cleanup_confirmed,mux_cleanup_scope,mux_wall_id FROM wso_private.tvt_local_media_leases WHERE id=:id"
            ),
            {"id": lease.id},
        ).one() == ("STOPPING", False, None, None)
    gate.close(lease, cleanup_confirmed=True)


def budget():
    from wso_core.tvt.local_service import LocalVerifyBudget

    return LocalVerifyBudget(20000)


def reserve(case):
    w = wall(case)
    lease = case[2].redeem(shared_ticket(case, w), budget=budget())
    reservation = case[2].reserve_master(lease, budget=budget())
    return w, lease, reservation


class SyntheticOriginal:
    """Controlled fixture issuer; no OS or recorder custody is claimed."""

    def __init__(self, reservation):
        from wso_core.tvt.local_media_mux_types import (
            MasterLoginProof,
            MuxEpochIdentity,
        )

        self.reservation = reservation
        self.epoch = MuxEpochIdentity(417, uuid4().bytes_le)
        self.proof = MasterLoginProof(True, True, True, True, True, 16)
        self.authority = object()
        self.bindings = {}
        self.receipt = None

    def binding_for(self, channel):
        from wso_core.tvt.local_media_mux_types import (
            _NATIVE_BINDING_SEAL,
            OriginalMuxBinding,
        )

        if channel not in self.bindings:
            self.bindings[channel] = OriginalMuxBinding(
                scope=self.reservation.scope,
                master_id=self.reservation.master_id,
                native_generation=self.reservation.transport.native_generation,
                epoch=self.epoch,
                channel=channel,
                proof=self.proof,
                _authority=self.authority,
                _seal=_NATIVE_BINDING_SEAL,
            )
        return self.bindings[channel]

    def issued_receipt(self):
        return self.receipt


def setup_slot(case):
    from tests.integration.test_local_media_admission import TWO_CHANNELS

    w, lease, reservation = reserve(case)
    gate = case[2]
    gate.prepare_login(reservation, budget=budget())
    original = SyntheticOriginal(reservation)
    gate.register_original(reservation, original, original)
    gate.activate_master(reservation, original.proof, budget=budget())
    slot = gate.reserve_slot(
        lease,
        reservation,
        binding=original.binding_for(TWO_CHANNELS[0].guid),
        budget=budget(),
    )
    viewer = gate.admit_viewer(lease, slot, registration=uuid4(), budget=budget())
    return w, lease, reservation, original, slot, viewer


def test_reserved_master_login_runs_after_transaction_release(mux_case):
    gate = mux_case[2]
    _, _, reservation = reserve(mux_case)
    credentials, grant = gate.prepare_login(reservation, budget=budget())
    assert credentials is not None
    assert gate._engine.pool.checkedout() == 0
    assert grant is reservation.transport
    from wso_core.tvt.local_service import LocalDeviceFailure

    with pytest.raises(LocalDeviceFailure):
        gate.prepare_login(reservation, budget=budget())


def test_same_device_other_actor_or_secret_revision_never_joins(mux_case):
    from wso_core.tvt.local_service import LocalDeviceFailure

    w, _, reservation = reserve(mux_case)
    lease = mux_case[2].redeem(
        shared_ticket(mux_case, w, mux_case[1].channels[1].id), budget=budget()
    )
    follower = mux_case[2].reserve_master(lease, budget=budget())
    assert follower is not reservation and follower.creator is False
    assert (
        follower.master_id == reservation.master_id
        and follower.scope == reservation.scope
    )
    assert follower.transport is reservation.transport
    with pytest.raises(LocalDeviceFailure):
        mux_case[2].prepare_login(follower, budget=budget())
    with pytest.raises(LocalDeviceFailure):
        mux_case[2].register_original(
            follower, SyntheticOriginal(follower), SyntheticOriginal(follower)
        )
    with mux_case[0][0]["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.connection_secrets SET version_id=gen_random_uuid() WHERE connection_id=:c"
            ),
            {"c": mux_case[0][1]["local"]},
        )
    assert mux_case[2].current_transport(reservation.transport) is False
    with pytest.raises(LocalDeviceFailure):
        mux_case[2].reserve_master(lease, budget=budget())


def test_each_retained_slot_revocation_stops_master(mux_case):
    _, _, reservation, _, slot, _ = setup_slot(mux_case)
    with mux_case[0][0]["ADMIN"].begin() as db:
        db.execute(
            text("UPDATE wso_private.tvt_local_channels SET active=false WHERE id=:id"),
            {"id": mux_case[1].channels[0].id},
        )
    assert mux_case[2].current_slot(slot) is False
    assert mux_case[2].current_transport(reservation.transport) is False
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT state,cleanup_confirmed FROM wso_private.tvt_local_media_masters WHERE id=:id"
            ),
            {"id": reservation.master_id},
        ).one() == ("STOPPING", False)


def test_legacy_cleanup_cannot_close_shared_viewer(mux_case):
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, lease, _, _, _, _ = setup_slot(mux_case)
    with pytest.raises(LocalDeviceFailure):
        mux_case[2].close(lease, cleanup_confirmed=True)


def unit_transport(clock=lambda: 1.0):
    from wso_core.tvt.local_media_mux_types import (
        _GRANT_SEAL,
        MasterReservation,
        MuxScopeKey,
        TransportGrant,
    )

    gate = facade().SqlMuxAdmission("postgresql+psycopg://unused", Key(), clock=clock)
    scope = MuxScopeKey(
        uuid4(),
        1,
        uuid4(),
        bytes(32),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        uuid4(),
        1,
        gate.worker_epoch,
    )
    master, native = uuid4(), uuid4()
    grant = gate._remember(
        TransportGrant(
            scope=scope,
            expires_monotonic=30,
            native_generation=native,
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "a" * 64,
        master,
        native,
    )
    reservation = MasterReservation(
        scope=scope,
        master_id=master,
        creator=True,
        transport=grant,
        deadline_monotonic=20,
        _seal=_GRANT_SEAL,
    )
    gate._masters[master] = reservation
    return gate, reservation


def test_slow_success_has_expired_cache_and_denial_stays(monkeypatch):
    from datetime import UTC, datetime, timedelta

    now = [1.0]
    gate, reservation = unit_transport(lambda: now[0])
    calls = []

    def slow(record):
        calls.append(record)
        now[0] += 0.2
        return {"expires_at": datetime.now(UTC) + timedelta(seconds=20)}

    monkeypatch.setattr(gate, "_observe", slow)
    assert gate.current_transport(reservation.transport)
    assert gate.current_transport(reservation.transport)
    assert len(calls) == 2
    monkeypatch.setattr(gate, "_observe", lambda record: None)
    assert gate.current_transport(reservation.transport) is False
    monkeypatch.setattr(gate, "_observe", slow)
    assert gate.current_transport(reservation.transport) is False
    assert len(calls) == 2
    gate._engine.dispose()


def test_expired_startup_reservation_does_not_decrypt_or_activate(monkeypatch):
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate, reservation = unit_transport(lambda: 21.0)
    calls = []
    monkeypatch.setattr(gate, "_sql", lambda *a, **kw: calls.append(a))
    with pytest.raises(LocalDeviceFailure):
        gate.prepare_login(reservation, budget=budget())
    assert calls == []
    gate._engine.dispose()


def test_shutdown_does_not_dispose_an_unconfirmed_mux_original():
    gate, _ = unit_transport()
    assert gate.shutdown() is False
    assert gate._mux_closed is False
    gate._engine.dispose()


def test_original_binding_copies_and_post_callback_replacement_fail(monkeypatch):
    from wso_core.tvt.local_media_mux_types import _NATIVE_BINDING_SEAL
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate, reservation = unit_transport()
    original = SyntheticOriginal(reservation)
    gate.register_original(reservation, original, original)
    binding = original.binding_for(uuid4().bytes_le)
    assert gate._binding(reservation, binding).issuer is original
    with pytest.raises(LocalDeviceFailure):
        gate._binding(reservation, replace(binding, _seal=_NATIVE_BINDING_SEAL))
    monkeypatch.setattr(original, "binding_for", lambda channel: binding)
    with pytest.raises(LocalDeviceFailure):
        gate._binding(reservation, binding)
    gate._engine.dispose()


class SyntheticViewerCustody:
    def __init__(self, lease_id, registration):
        from wso_core.tvt.local_media_mux_types import (
            _CUSTODY_SEAL,
            ViewerCleanupReceipt,
        )

        self.receipt = ViewerCleanupReceipt(
            lease_id=lease_id,
            registration_id=registration,
            decoder_settled=True,
            peer_settled=True,
            media_cleared=True,
            _authority=object(),
            _seal=_CUSTODY_SEAL,
        )

    def issued_receipt(self):
        return self.receipt


def delivery_proof():
    from wso_core.tvt.local_media_service import LocalLiveProof

    return LocalLiveProof(True, True, True, True, True, True, True, True, "h264")


def focus_ticket(case, lease_id, direction):
    with app_scope(case[0], "owner") as db:
        ticket = db.execute(
            text(
                "SELECT public.wso_tvt_local_media_focus_issue(:s,:id,:direction,clock_timestamp()+interval '20 seconds')"
            ),
            {"s": case[0][1]["session"], "id": lease_id, "direction": direction},
        ).scalar_one()
    assert ticket
    return ticket


def focus_setup(case, *, claim_main=True):
    from wso_core.tvt.local_media_mux_types import CleanupScope

    from tests.tvt_parity.test_local_media_service import Session

    w, _, reservation, _, _, viewer = setup_slot(case)
    gate = case[2]
    gate.activate_viewer(viewer, delivery_proof(), budget=budget())
    focus = gate.redeem_focus(
        focus_ticket(case, viewer.lease_id, "FORWARD"), budget=budget()
    )
    ref_id = gate._records[id(focus)].focus_id
    viewer_custody = SyntheticViewerCustody(viewer.lease_id, viewer.registration)
    gate.register_viewer_custodian(viewer, viewer_custody)
    gate.finish_viewer(viewer, viewer_custody.receipt, scope=CleanupScope.VIEWER)
    local, inv, _ = case
    with app_scope(local, "owner") as db:
        ticket = db.execute(
            text(
                "SELECT public.wso_tvt_local_media_shared_issue(:s,:c,:store,:dev,:ch,1,:rev,'main',30,:wall,:focus)"
            ),
            {
                "s": local[1]["session"],
                "c": local[1]["local"],
                "store": local[1]["store"],
                "dev": inv.device_id,
                "ch": inv.channels[0].id,
                "rev": inv.inventory_revision,
                "wall": w,
                "focus": ref_id,
            },
        ).scalar_one()
    assert ticket
    main = gate.redeem(ticket, budget=budget())
    registration = uuid4()
    local_custody = SyntheticViewerCustody(main.id, registration)
    main_custody = SyntheticOriginal(reservation)
    gate.register_dedicated(
        main, main_custody, local_custody, registration=registration, budget=budget()
    )
    if claim_main:
        native = Session()
        gate.open(main, lambda credentials, channel, current: native, budget=budget())
        gate.activate(main, native.proof, budget=budget())
    return w, reservation, focus, main, registration, local_custody, main_custody


def test_main_retention_accepts_committed_return_before_worker_redeem(mux_case):
    _, _, focus, main, _, _, _ = focus_setup(mux_case)
    gate = mux_case[2]
    ack = gate.settle_focus(focus, "ATTACHED", viewer=main.id)
    assert gate.current_main_retention(main, focus, ack)
    ticket = focus_ticket(mux_case, main.id, "RETURN")
    assert ticket
    assert gate.current_main_retention(main, focus, ack), (
        "committed exact pending RETURN must bridge original MAIN retention"
    )
    assert gate._focus_settlements[id(focus)] is ack


def test_main_retention_observer_migration_and_worker_only_acl(mux_database):
    signature = "public.wso_tvt_local_media_main_retention_observe(text,uuid,uuid)"
    with mux_database["ADMIN"].connect() as db:
        assert (
            db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0017_tvt_main_return_retention"
        )
        row = db.execute(
            text(
                "SELECT pg_get_userbyid(proowner),prosecdef,proconfig FROM pg_proc "
                "WHERE oid=to_regprocedure(:signature)"
            ),
            {"signature": signature},
        ).one()
        assert row[0] == "wso_tvt_local_owner" and row[1]
        assert "search_path=pg_catalog" in row[2] and "lock_timeout=3s" in row[2]
        for role in [
            "wso_app",
            "wso_web_session",
            "wso_job_worker",
            "wso_connection_worker",
        ]:
            assert db.execute(
                text("SELECT has_function_privilege(:role,:signature,'EXECUTE')"),
                {"role": role, "signature": signature},
            ).scalar_one() is (role == "wso_connection_worker")
        assert not db.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) x "
                "WHERE p.oid=to_regprocedure(:signature) AND x.grantee=0 AND x.privilege_type='EXECUTE')"
            ),
            {"signature": signature},
        ).scalar_one()


@pytest.mark.parametrize(
    "fault",
    [
        "CANCELLED",
        "FAILED",
        "EXPIRED",
        "ATTACHED",
        "CONSUMED",
        "deadline",
        "wrong_main",
        "wrong_channel",
        "foreign_worker",
        "revoke_main",
        "foreign_master_epoch",
        "foreign_main_epoch",
        "unredeemed_authority",
    ],
)
def test_main_retention_rejects_noncurrent_or_foreign_return(mux_case, fault):
    _, _, focus, main, _, _, _ = focus_setup(mux_case)
    gate = mux_case[2]
    ack = gate.settle_focus(focus, "ATTACHED", viewer=main.id)
    focus_ticket(mux_case, main.id, "RETURN")
    with mux_case[0][0]["ADMIN"].begin() as db:
        params = {
            "main": main.id,
            "source": focus.lease_id,
            "channel": mux_case[1].channels[1].id,
            "foreign": uuid4(),
        }
        if fault in {"CANCELLED", "FAILED", "EXPIRED", "ATTACHED", "CONSUMED"}:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_focus_refs SET state=:state WHERE source_lease=:main AND direction='RETURN'"
                ),
                params | {"state": fault},
            )
        elif fault == "deadline":
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_focus_refs SET issued_at=clock_timestamp()-interval '30 seconds',expires_at=clock_timestamp()-interval '11 seconds' WHERE source_lease=:main AND direction='RETURN'"
                ),
                params,
            )
        elif fault == "wrong_main":
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_focus_refs SET source_lease=:source WHERE source_lease=:main AND direction='RETURN'"
                ),
                params,
            )
        elif fault == "wrong_channel":
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_focus_refs SET channel_id=:channel WHERE source_lease=:main AND direction='RETURN'"
                ),
                params,
            )
        elif fault == "foreign_worker":
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_focus_refs SET worker_epoch=:foreign,authority_digest=sha256(convert_to(CAST(:foreign AS text),'UTF8')) WHERE source_lease=:main AND direction='RETURN'"
                ),
                params,
            )
        elif fault == "foreign_master_epoch":
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_masters SET native_generation=:foreign WHERE id=:master"
                ),
                params | {"master": gate._records[id(focus)].master_id},
            )
        elif fault == "foreign_main_epoch":
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_leases SET native_generation=:foreign WHERE id=:main"
                ),
                params,
            )
        elif fault == "unredeemed_authority":
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_focus_refs SET authority_digest=sha256(convert_to(CAST(:foreign AS text),'UTF8')) WHERE source_lease=:main AND direction='RETURN'"
                ),
                params,
            )
        else:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_leases SET invalidated=true,state='STOPPING' WHERE id=:main"
                ),
                params,
            )
    assert not gate.current_main_retention(main, focus, ack)


def test_main_return_retention_uses_pending_deadline_not_consumed_active_deadline(
    mux_case,
):
    _, _, focus, main, _, _, _ = focus_setup(mux_case)
    gate = mux_case[2]
    ack = gate.settle_focus(focus, "ATTACHED", viewer=main.id)
    focus_ticket(mux_case, main.id, "RETURN")
    with mux_case[0][0]["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_focus_refs SET active_expires_at=clock_timestamp()-interval '1 second' WHERE id=:focus"
            ),
            {"focus": gate._records[id(focus)].focus_id},
        )
    assert gate.current_main_retention(main, focus, ack)


def test_main_retention_preserves_original_settlement_until_strict_publication_check(
    mux_case,
):
    from wso_core.tvt.local_media_mux_types import _GRANT_SEAL

    _, _, focus, main, _, _, _ = focus_setup(mux_case)
    gate = mux_case[2]
    ack = gate.settle_focus(focus, "ATTACHED", viewer=main.id)
    ticket = focus_ticket(mux_case, main.id, "RETURN")
    assert gate.current_main_retention(main, focus, ack)
    returned = gate.redeem_focus(ticket, budget=budget())
    assert gate.current_main_retention(main, focus, ack)
    assert not gate.current_main_retention(main, replace(focus, _seal=_GRANT_SEAL), ack)
    assert not gate.current_main_retention(main, focus, replace(ack))
    assert gate.current_focus(returned)
    assert gate._focus_settlements[id(focus)] is ack
    # A retention result does not make the old active ACK publishable again.
    assert not gate.focus_settlement_current(focus, ack, "ATTACHED", viewer=main.id)


@pytest.mark.parametrize("change", ["return", "stop"])
def test_main_retention_rechecks_committed_change_during_sql_observation(
    mux_case, change
):
    _, _, focus, main, _, _, _ = focus_setup(mux_case)
    gate = mux_case[2]
    ack = gate.settle_focus(focus, "ATTACHED", viewer=main.id)
    if change == "stop":
        focus_ticket(mux_case, main.id, "RETURN")
    admin = mux_case[0][0]["ADMIN"]
    key = uuid4().int % 0x7FFFFFFF
    signature = "public.wso_tvt_local_media_main_retention_observe(text,uuid,uuid)"
    with admin.connect() as db:
        original = db.execute(
            text("SELECT pg_get_functiondef(to_regprocedure(:s))"), {"s": signature}
        ).scalar_one()
    marker = "   IF NOT wso_private.wso_tvt_local_media_master_current(m)\n   OR NOT wso_private.wso_tvt_local_media_live_read(l) THEN RETURN NULL; END IF;"
    reload_marker = "   -- Reload original MAIN/master before final validation;"
    if reload_marker in original:
        marker = reload_marker
    assert original.count(marker) == 1
    changed = original.replace(
        marker, f"   PERFORM pg_advisory_xact_lock({key});\n" + marker
    )
    with admin.begin() as db:
        db.execute(text(changed))
    locker = admin.connect()
    transaction = locker.begin()
    locker.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(gate.current_main_retention, main, focus, ack)
    try:
        until = time.monotonic() + 3
        waiting = False
        while time.monotonic() < until:
            with admin.connect() as db:
                waiting = db.execute(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM pg_locks x WHERE x.locktype='advisory' "
                        "AND NOT x.granted AND x.objid=:key AND x.pid IN "
                        "(SELECT pid FROM pg_stat_activity WHERE datname=current_database()))"
                    ),
                    {"key": key},
                ).scalar_one()
            if waiting:
                break
            time.sleep(0.005)
        assert waiting, "actual worker observation must reach its final SQL barrier"
        if change == "return":
            focus_ticket(mux_case, main.id, "RETURN")
        else:
            with app_scope(mux_case[0], "owner") as db:
                ticket = db.execute(
                    text(
                        "SELECT public.wso_tvt_local_media_control_issue(:s,:main,'stop')"
                    ),
                    {"s": mux_case[0][1]["session"], "main": main.id},
                ).scalar_one()
                assert ticket
        transaction.commit()
        assert future.result(timeout=5) is (change == "return"), (
            "fresh bounded RETURN is valid; committed original MAIN Stop is denial"
        )
    finally:
        if transaction.is_active:
            transaction.rollback()
        locker.close()
        pool.shutdown(wait=True)
        with admin.begin() as db:
            db.execute(text(original))


def test_focus_pending_twenty_seconds_not_renewable(mux_case):
    from wso_core.tvt.local_service import LocalDeviceFailure

    w, _, focus, _, _, _, _ = focus_setup(mux_case)
    gate = mux_case[2]
    with pytest.raises(LocalDeviceFailure):
        gate.refresh_grant(focus)
    with mux_case[0][0]["ADMIN"].connect() as db:
        before = db.execute(
            text(
                "SELECT issued_at,expires_at FROM wso_private.tvt_local_media_focus_refs WHERE id=:id"
            ),
            {"id": gate._records[id(focus)].focus_id},
        ).one()
    with app_scope(mux_case[0], "owner") as db:
        assert db.execute(
            text("SELECT public.wso_tvt_local_media_wall_read(:s,:w,true)"),
            {"s": mux_case[0][1]["session"], "w": w},
        ).scalar_one()
    with mux_case[0][0]["ADMIN"].connect() as db:
        after = db.execute(
            text(
                "SELECT issued_at,expires_at FROM wso_private.tvt_local_media_focus_refs WHERE id=:id"
            ),
            {"id": gate._records[id(focus)].focus_id},
        ).one()
    assert before == after
    assert 0 < (after[1] - after[0]).total_seconds() <= 20


@pytest.mark.parametrize("reuse_fault", [None, "foreign_channel", "revoked_channel"])
def test_main_active_return_consumed_atomically(mux_case, reuse_fault):
    from sqlalchemy.exc import DBAPIError
    from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL, EpochCleanupReceipt
    from wso_core.tvt.local_service import LocalDeviceFailure

    w, reservation, focus, main, _, local_custody, main_custody = focus_setup(mux_case)
    gate = mux_case[2]
    ref_id = gate._records[id(focus)].focus_id
    gate.settle_focus(focus, "ATTACHED", viewer=main.id)
    with mux_case[0][0]["ADMIN"].connect() as db:
        row = db.execute(
            text(
                "SELECT state,active_expires_at>clock_timestamp(),active_expires_at<=clock_timestamp()+interval '30 seconds' FROM wso_private.tvt_local_media_focus_refs WHERE id=:id"
            ),
            {"id": ref_id},
        ).one()
        assert row == ("MAIN_ACTIVE", True, True)
    returned = gate.redeem_focus(
        focus_ticket(mux_case, main.id, "RETURN"), budget=budget()
    )
    assert returned.direction == "RETURN"
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT state FROM wso_private.tvt_local_media_focus_refs WHERE id=:id"
                ),
                {"id": ref_id},
            ).scalar_one()
            == "CONSUMED"
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_local_media_focus_refs WHERE wall_id=:w AND state='MAIN_ACTIVE'"
                ),
                {"w": w},
            ).scalar_one()
            == 0
        )
    gate.finish_dedicated_viewer(main, local_custody.receipt)
    local, inv, _ = mux_case

    def return_ticket():
        with app_scope(local, "owner") as db:
            return db.execute(
                text(
                    "SELECT public.wso_tvt_local_media_shared_issue(:s,:c,:store,:dev,:ch,1,:rev,'sub',30,:wall,:focus)"
                ),
                {
                    "s": local[1]["session"],
                    "c": local[1]["local"],
                    "store": local[1]["store"],
                    "dev": inv.device_id,
                    "ch": inv.channels[0].id,
                    "rev": inv.inventory_revision,
                    "wall": w,
                    "focus": gate._records[id(returned)].focus_id,
                },
            ).scalar_one()

    with pytest.raises(DBAPIError) as caught:
        return_ticket()
    assert caught.value.orig.sqlstate == "53300"
    main_custody.receipt = EpochCleanupReceipt(
        master_id=main.id,
        worker_epoch=main.worker_epoch,
        native_generation=main.native_generation,
        original_state="REAPED",
        callback_settled=True,
        ipc_settled=True,
        job_settled=True,
        _authority=object(),
        _seal=_CUSTODY_SEAL,
    )
    gate.finish_dedicated(main, main_custody.receipt)
    ticket = return_ticket()
    assert ticket
    next_lease = gate.redeem(ticket, budget=budget())
    follower = gate.reserve_master(next_lease, budget=budget())
    assert follower.creator is False and follower.master_id == reservation.master_id

    # Exercise the product's retained-slot branch, then all remaining SQL ports.
    # Unlike the inert coordinator fake, SQL requires each fresh lease's slot ID.
    from threading import RLock
    from types import SimpleNamespace

    from wso_core.tvt.local_media_mux_service import DeviceEpochCoordinator, SlotRecord
    from wso_core.tvt.local_media_mux_types import SlotRetentionGrant

    selection = gate.prepare_viewer(next_lease, budget=budget())
    retained = next(
        row.grant
        for row in gate._records.values()
        if type(row.grant) is SlotRetentionGrant and not row.closed
    )
    original = gate._originals[reservation.master_id].issuer
    before_identity = retained.slot
    record = SimpleNamespace(
        slots={selection.guid: SlotRecord(selection, retained, retained.slot)},
        opening=False,
        prepared=original,
        reservation=reservation,
    )
    coordinator = object.__new__(DeviceEpochCoordinator)
    coordinator.admission, coordinator._lock = gate, RLock()
    coordinator._active = lambda item: item is record
    coordinator._fence = lambda item: None
    if reuse_fault == "foreign_channel":
        from tests.integration.test_local_media_admission import TWO_CHANNELS

        record.prepared = SimpleNamespace(
            binding_for=lambda channel: original.binding_for(TWO_CHANNELS[1].guid)
        )
    elif reuse_fault == "revoked_channel":
        with mux_case[0][0]["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_channels SET active=false WHERE id=:id"
                ),
                {"id": inv.channels[0].id},
            )
    if reuse_fault is not None:
        with pytest.raises(LocalDeviceFailure):
            coordinator._slot(next_lease, selection, record, budget())
        return
    reused = coordinator._slot(next_lease, selection, record, budget())
    assert reused.grant is retained and reused.identity is before_identity
    admitted = gate.admit_viewer(
        next_lease, reused.grant, registration=uuid4(), budget=budget()
    )
    gate.activate_viewer(admitted, delivery_proof(), budget=budget())
    ack = gate.settle_focus(returned, "ATTACHED", viewer=next_lease.id)
    assert ack is not None
    assert gate.focus_settlement_current(
        returned, ack, "ATTACHED", viewer=next_lease.id
    )


def test_uncertain_master_commit_retains_charge_and_authority(mux_case, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from wso_core.tvt.local_service import LocalDeviceFailure

    w = wall(mux_case)
    gate = mux_case[2]
    lease = gate.redeem(shared_ticket(mux_case, w), budget=budget())
    execute = gate._sql

    def uncertain(function, *args, **kwargs):
        value = execute(function, *args, **kwargs)
        if function == "master_reserve":
            raise SQLAlchemyError("synthetic lost commit response")
        return value

    monkeypatch.setattr(gate, "_sql", uncertain)
    with pytest.raises(LocalDeviceFailure):
        gate.reserve_master(lease, budget=budget())
    assert len(gate._pending_reservations) == 1
    assert gate.dispose() is False
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_local_media_masters WHERE wall_id=:w AND state='STARTING' AND NOT cleanup_confirmed"
                ),
                {"w": w},
            ).scalar_one()
            == 1
        )
    monkeypatch.setattr(gate, "_sql", execute)
    with pytest.raises(LocalDeviceFailure):
        gate.reserve_master(lease, budget=budget())
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_local_media_masters WHERE wall_id=:w"
                ),
                {"w": w},
            ).scalar_one()
            == 1
        )


def test_dedicated_both_receipts_and_base_receipt_mismatch(mux_case):
    from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL, EpochCleanupReceipt
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, reservation, _, main, _, local_custody, main_custody = focus_setup(mux_case)
    gate = mux_case[2]
    gate.finish_dedicated_viewer(main, local_custody.receipt)

    def state():
        with mux_case[0][0]["ADMIN"].connect() as db:
            return db.execute(
                text(
                    "SELECT state,cleanup_confirmed FROM wso_private.tvt_local_media_leases WHERE id=:id"
                ),
                {"id": main.id},
            ).one()

    assert state() == ("STOPPING", False)
    receipt = EpochCleanupReceipt(
        master_id=reservation.master_id,
        worker_epoch=main.worker_epoch,
        native_generation=reservation.transport.native_generation,
        original_state="REAPED",
        callback_settled=True,
        ipc_settled=True,
        job_settled=True,
        _authority=object(),
        _seal=_CUSTODY_SEAL,
    )
    main_custody.receipt = receipt
    with pytest.raises(LocalDeviceFailure):
        gate.finish_dedicated(main, receipt)
    assert state() == ("STOPPING", False)
    main_custody.receipt = replace(
        receipt,
        master_id=main.id,
        native_generation=main.native_generation,
        _seal=_CUSTODY_SEAL,
    )
    gate.finish_dedicated(main, main_custody.receipt)
    assert state() == ("CLOSED", True)


def test_refresh_replaces_grant_without_reviving_old_or_wrong_purpose(mux_case):
    from wso_core.tvt.local_service import LocalDeviceFailure

    w, _, reservation, _, slot, viewer = setup_slot(mux_case)
    gate = mux_case[2]
    gate.activate_viewer(viewer, delivery_proof(), budget=budget())
    with app_scope(mux_case[0], "owner") as db:
        assert db.execute(
            text("SELECT public.wso_tvt_local_media_read(:s,:id,true)"),
            {"s": mux_case[0][1]["session"], "id": viewer.lease_id},
        ).scalar_one()
        assert db.execute(
            text("SELECT public.wso_tvt_local_media_wall_read(:s,:w,true)"),
            {"s": mux_case[0][1]["session"], "w": w},
        ).scalar_one()
    for grant, current in (
        (reservation.transport, gate.current_transport),
        (slot, gate.current_slot),
        (viewer, gate.current_viewer),
    ):
        fresh = gate.refresh_grant(grant)
        assert (
            fresh is not grant
            and type(fresh) is type(grant)
            and fresh.scope == grant.scope
        )
        assert current(grant) is False
        assert current(fresh) is True
        with pytest.raises(LocalDeviceFailure):
            gate.refresh_grant(grant)
    assert gate.current_slot(reservation.transport) is False


def test_observed_slot_denial_overrides_cached_master(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from wso_core.tvt.local_media_mux_types import (
        _GRANT_SEAL,
        MuxEpochIdentity,
        MuxSlotIdentity,
        SlotRetentionGrant,
    )

    gate, reservation = unit_transport()
    slot = gate._remember(
        SlotRetentionGrant(
            scope=reservation.scope,
            slot=MuxSlotIdentity(
                MuxEpochIdentity(1, uuid4().bytes_le),
                uuid4().bytes_le,
                uuid4().bytes_le,
                2,
            ),
            expires_monotonic=20,
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "b" * 64,
        reservation.master_id,
        reservation.transport.native_generation,
    )
    monkeypatch.setattr(
        gate,
        "_observe",
        lambda r: (
            {"expires_at": datetime.now(UTC) + timedelta(seconds=20)}
            if r.grant is reservation.transport
            else None
        ),
    )
    assert gate.current_transport(reservation.transport)
    assert gate.current_slot(slot) is False
    assert gate.current_transport(reservation.transport) is False
    gate._engine.dispose()


@pytest.mark.parametrize("native_first", [False, True])
def test_last_viewer_requires_both_original_and_local_receipts(mux_case, native_first):
    from wso_core.tvt.local_media_mux_types import (
        _CUSTODY_SEAL,
        CleanupScope,
        EpochCleanupReceipt,
    )

    _, _, reservation, original, _, viewer = setup_slot(mux_case)
    gate = mux_case[2]
    custody = SyntheticViewerCustody(viewer.lease_id, viewer.registration)
    gate.register_viewer_custodian(viewer, custody)
    original.receipt = EpochCleanupReceipt(
        master_id=reservation.master_id,
        worker_epoch=reservation.scope.worker_epoch,
        native_generation=reservation.transport.native_generation,
        original_state="REAPED",
        callback_settled=True,
        ipc_settled=True,
        job_settled=True,
        _authority=object(),
        _seal=_CUSTODY_SEAL,
    )

    def native():
        gate.finish_epoch(reservation.transport, original.receipt)

    def local():
        gate.finish_viewer(
            viewer, custody.receipt, scope=CleanupScope.LAST_VIEWER_AND_DEVICE_EPOCH
        )

    def state():
        with mux_case[0][0]["ADMIN"].connect() as db:
            return db.execute(
                text(
                    "SELECT state,cleanup_confirmed FROM wso_private.tvt_local_media_leases WHERE id=:id"
                ),
                {"id": viewer.lease_id},
            ).one()

    first, second = (native, local) if native_first else (local, native)
    first()
    assert state() == ("STOPPING", False)
    second()
    assert state() == ("CLOSED", True)


def test_mutation_waiting_on_actor_revoke_never_admits(mux_case):
    import threading
    import time

    from sqlalchemy import event
    from wso_core.tvt.local_service import LocalDeviceFailure

    from tests.integration.test_local_media_admission import TWO_CHANNELS

    w, _, reservation, original, _, _ = setup_slot(mux_case)
    gate = mux_case[2]
    second = gate.redeem(
        shared_ticket(mux_case, w, mux_case[1].channels[1].id), budget=budget()
    )
    checked = threading.Event()
    pids = []
    outcome = []

    def checkout(connection, record, proxy):
        pids.append(connection.info.backend_pid)
        checked.set()

    def reserve_other():
        try:
            gate.reserve_slot(
                second,
                reservation,
                binding=original.binding_for(TWO_CHANNELS[1].guid),
                budget=budget(),
            )
            outcome.append("admitted")
        except LocalDeviceFailure:
            outcome.append("denied")

    event.listen(gate._engine, "checkout", checkout)
    thread = threading.Thread(target=reserve_other)
    try:
        with mux_case[0][0]["ADMIN"].begin() as db:
            params = {
                "t": reservation.scope.tenant_id,
                "u": reservation.scope.actor_user_id,
            }
            db.execute(
                text(
                    "SELECT 1 FROM public.memberships WHERE tenant_id=:t AND user_id=:u FOR UPDATE"
                ),
                params,
            )
            thread.start()
            assert checked.wait(2)
            deadline = time.monotonic() + 2
            blocked = False
            while time.monotonic() < deadline:
                blocked = db.execute(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)"
                    ),
                    {"pid": pids[-1]},
                ).scalar_one()
                if blocked:
                    break
                time.sleep(0.01)
            assert blocked
            db.execute(
                text(
                    "UPDATE public.memberships SET role='STAFF' WHERE tenant_id=:t AND user_id=:u"
                ),
                params,
            )
        thread.join(5)
        assert not thread.is_alive()
        assert outcome == ["denied"]
    finally:
        if thread.ident is not None:
            thread.join(5)
        event.remove(gate._engine, "checkout", checkout)


def test_two_base_master_cap_counts_stopping_originals(mux_case):
    from wso_core.tvt.local_service import LocalDeviceFailure

    from tests.integration.test_local_media_admission import capacity_case

    database = mux_case[0][0]
    gate = mux_case[2]
    cases = []
    try:
        for _ in range(3):
            created = capacity_case(database)
            cases.append((created[0], created[1], gate))
        first = reserve(cases[0])[2]
        reserve(cases[1])
        w = wall(cases[2])
        lease = gate.redeem(shared_ticket(cases[2], w), budget=budget())
        with pytest.raises(LocalDeviceFailure) as caught:
            gate.reserve_master(lease, budget=budget())
        assert caught.value.code == "LOCAL_DEVICE_BUSY"
        with database["ADMIN"].begin() as db:
            db.execute(
                text("SELECT wso_private.wso_tvt_local_media_stop_master(:id)"),
                {"id": first.master_id},
            )
        with pytest.raises(LocalDeviceFailure) as caught:
            gate.reserve_master(lease, budget=budget())
        assert caught.value.code == "LOCAL_DEVICE_DENIED"
        # The original attempt cannot dispatch twice. A new channel lease reaches
        # SQL again and proves that the STOPPING original still consumes capacity.
        fresh = gate.redeem(
            shared_ticket(cases[2], w, cases[2][1].channels[1].id), budget=budget()
        )
        with pytest.raises(LocalDeviceFailure) as caught:
            gate.reserve_master(fresh, budget=budget())
        assert caught.value.code == "LOCAL_DEVICE_BUSY"
        with database["ADMIN"].connect() as db:
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM wso_private.tvt_local_media_masters WHERE state<>'CLOSED' AND NOT cleanup_confirmed"
                    )
                ).scalar_one()
                == 2
            )
    finally:
        for case in cases:
            with database["ADMIN"].begin() as db:
                params = {"c": case[0][1]["local"]}
                db.execute(
                    text(
                        "UPDATE wso_private.tvt_local_media_leases SET mux_viewer_settled=true,mux_native_settled=true,state='CLOSED',invalidated=true,cleanup_confirmed=true WHERE connection_id=:c"
                    ),
                    params,
                )
                db.execute(
                    text(
                        "UPDATE wso_private.tvt_local_media_masters SET state='CLOSED',cleanup_confirmed=true WHERE connection_id=:c"
                    ),
                    params,
                )
                db.execute(
                    text(
                        "UPDATE wso_private.tvt_local_media_walls SET state='CLOSED' WHERE id IN (SELECT mux_wall_id FROM wso_private.tvt_local_media_leases WHERE connection_id=:c)"
                    ),
                    params,
                )


def test_sixteen_retained_slots_stay_charged_after_viewer_close(mux_case):
    from uuid import UUID

    from wso_core.tvt.local_media_mux_types import CleanupScope
    from wso_core.tvt.local_service import LocalDeviceFailure

    from tests.integration.test_local_media_admission import capacity_inventory

    expanded = capacity_inventory(
        (mux_case[0], mux_case[1], mux_case[2], None, None), 17
    )
    case = (expanded[0], expanded[1], mux_case[2])
    gate = case[2]
    w, lease, reservation = reserve(case)
    gate.prepare_login(reservation, budget=budget())
    original = SyntheticOriginal(reservation)
    gate.register_original(reservation, original, original)
    gate.activate_master(reservation, original.proof, budget=budget())
    for index in range(17):
        if index:
            lease = gate.redeem(
                shared_ticket(case, w, case[1].channels[index].id), budget=budget()
            )
            follower = gate.reserve_master(lease, budget=budget())
            assert follower.creator is False
        binding = original.binding_for(UUID(int=index + 1).bytes_le)
        if index == 16:
            with pytest.raises(LocalDeviceFailure) as caught:
                gate.reserve_slot(lease, reservation, binding=binding, budget=budget())
            assert caught.value.code == "LOCAL_DEVICE_BUSY"
            break
        slot = gate.reserve_slot(lease, reservation, binding=binding, budget=budget())
        viewer = gate.admit_viewer(lease, slot, registration=uuid4(), budget=budget())
        gate.activate_viewer(viewer, delivery_proof(), budget=budget())
        if index:
            custody = SyntheticViewerCustody(viewer.lease_id, viewer.registration)
            gate.register_viewer_custodian(viewer, custody)
            gate.finish_viewer(viewer, custody.receipt, scope=CleanupScope.VIEWER)
    with case[0][0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT count(*),count(*) FILTER(WHERE state='PARKED') FROM wso_private.tvt_local_media_slots WHERE master_id=:id AND state<>'CLOSED'"
            ),
            {"id": reservation.master_id},
        ).one() == (16, 15)


@pytest.mark.parametrize(
    "failure", ["none", "exception", "expired_entry", "expired_during"]
)
def test_refresh_failure_fences_exact_master_and_siblings(monkeypatch, failure):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.exc import SQLAlchemyError
    from wso_core.tvt.local_media_mux_types import (
        _GRANT_SEAL,
        MuxEpochIdentity,
        MuxSlotIdentity,
        SlotRetentionGrant,
        TransportGrant,
        ViewerGrant,
    )
    from wso_core.tvt.local_service import LocalDeviceFailure

    clock = [1.0]
    gate, reservation = unit_transport(lambda: clock[0])
    identity = MuxSlotIdentity(
        MuxEpochIdentity(1, uuid4().bytes_le), uuid4().bytes_le, uuid4().bytes_le, 2
    )
    slot = gate._remember(
        SlotRetentionGrant(
            scope=reservation.scope,
            slot=identity,
            expires_monotonic=20,
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "b" * 64,
        reservation.master_id,
        reservation.transport.native_generation,
    )
    viewer = gate._remember(
        ViewerGrant(
            scope=reservation.scope,
            slot=identity,
            lease_id=uuid4(),
            registration=uuid4(),
            expires_monotonic=30,
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "c" * 64,
        reservation.master_id,
        reservation.transport.native_generation,
    )
    other = gate._remember(
        TransportGrant(
            scope=replace(reservation.scope, device_id=uuid4(), connection_id=uuid4()),
            expires_monotonic=30,
            native_generation=uuid4(),
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "d" * 64,
        uuid4(),
        uuid4(),
    )
    good = lambda: {"expires_at": datetime.now(UTC) + timedelta(seconds=20)}
    monkeypatch.setattr(gate, "_observe", lambda r: good())
    assert gate.current_transport(reservation.transport)
    assert gate.current_viewer(viewer)
    assert gate.current_transport(other)

    def failing(record):
        if record.grant is not slot:
            return good()
        if failure == "exception":
            raise SQLAlchemyError("synthetic observation failure")
        if failure == "expired_during":
            clock[0] = 21.0
            return good()
        return None

    monkeypatch.setattr(gate, "_observe", failing)
    if failure == "expired_entry":
        clock[0] = 21.0
    with pytest.raises(LocalDeviceFailure):
        gate.refresh_grant(slot)
    assert gate.current_transport(reservation.transport) is False
    assert gate.current_viewer(viewer) is False
    assert gate.current_transport(other) is True
    monkeypatch.setattr(gate, "_observe", lambda r: good())
    with pytest.raises(LocalDeviceFailure):
        gate.refresh_grant(slot)
    gate._engine.dispose()


def stop_wall(case, wall_id):
    with app_scope(case[0], "owner") as db:
        ticket = db.execute(
            text("SELECT public.wso_tvt_local_media_wall_stop_issue(:s,:w)"),
            {"s": case[0][1]["session"], "w": wall_id},
        ).scalar_one()
    assert ticket


def wall_state(case, wall_id):
    with case[0][0]["ADMIN"].connect() as db:
        return db.execute(
            text("SELECT state FROM wso_private.tvt_local_media_walls WHERE id=:id"),
            {"id": wall_id},
        ).scalar_one()


def original_receipt(master_id, worker_epoch, native):
    from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL, EpochCleanupReceipt

    return EpochCleanupReceipt(
        master_id=master_id,
        worker_epoch=worker_epoch,
        native_generation=native,
        original_state="REAPED",
        callback_settled=True,
        ipc_settled=True,
        job_settled=True,
        _authority=object(),
        _seal=_CUSTODY_SEAL,
    )


@pytest.mark.parametrize("native_first", [False, True])
def test_stop_wall_finalizes_after_both_receipt_orders(mux_case, native_first):
    from sqlalchemy.exc import DBAPIError
    from wso_core.tvt.local_media_mux_types import CleanupScope

    w, _, reservation, original, _, viewer = setup_slot(mux_case)
    gate = mux_case[2]
    custody = SyntheticViewerCustody(viewer.lease_id, viewer.registration)
    gate.register_viewer_custodian(viewer, custody)
    original.receipt = original_receipt(
        reservation.master_id,
        reservation.scope.worker_epoch,
        reservation.transport.native_generation,
    )
    stop_wall(mux_case, w)

    def native():
        gate.finish_epoch(reservation.transport, original.receipt)

    def local():
        gate.finish_viewer(
            viewer, custody.receipt, scope=CleanupScope.LAST_VIEWER_AND_DEVICE_EPOCH
        )

    first, second = (native, local) if native_first else (local, native)
    first()
    assert wall_state(mux_case, w) == "STOPPING"
    with pytest.raises(DBAPIError):
        wall(mux_case)
    second()
    assert wall_state(mux_case, w) == "CLOSED"
    # Repeating the exact receipt is idempotent and cannot reopen the wall.
    native()
    assert wall_state(mux_case, w) == "CLOSED"
    assert wall(mux_case) != w


def test_stop_wall_waits_for_dedicated_last_receipt(mux_case):
    from sqlalchemy.exc import DBAPIError

    w, reservation, _, main, _, local_custody, main_custody = focus_setup(mux_case)
    gate = mux_case[2]
    original = gate._original(reservation).issuer
    original.receipt = original_receipt(
        reservation.master_id,
        reservation.scope.worker_epoch,
        reservation.transport.native_generation,
    )
    main_custody.receipt = original_receipt(
        main.id, main.worker_epoch, main.native_generation
    )
    stop_wall(mux_case, w)
    gate.finish_epoch(reservation.transport, original.receipt)
    gate.finish_dedicated_viewer(main, local_custody.receipt)
    assert wall_state(mux_case, w) == "STOPPING"
    with pytest.raises(DBAPIError):
        wall(mux_case)
    gate.finish_dedicated(main, main_custody.receipt)
    assert wall_state(mux_case, w) == "CLOSED"
    assert wall(mux_case) != w


@pytest.mark.parametrize("retired", [False, True])
def test_stop_empty_or_already_retired_wall_allows_new_wall(mux_case, retired):
    from wso_core.tvt.local_media_mux_types import CleanupScope

    if retired:
        w, _, reservation, original, _, viewer = setup_slot(mux_case)
        gate = mux_case[2]
        custody = SyntheticViewerCustody(viewer.lease_id, viewer.registration)
        gate.register_viewer_custodian(viewer, custody)
        original.receipt = original_receipt(
            reservation.master_id,
            reservation.scope.worker_epoch,
            reservation.transport.native_generation,
        )
        gate.finish_viewer(
            viewer, custody.receipt, scope=CleanupScope.LAST_VIEWER_AND_DEVICE_EPOCH
        )
        gate.finish_epoch(reservation.transport, original.receipt)
    else:
        w = wall(mux_case)
    stop_wall(mux_case, w)
    assert wall_state(mux_case, w) == "CLOSED"
    assert wall(mux_case) != w


def test_ports_viewer_selection_preserves_login_and_admission(mux_case, monkeypatch):
    from tests.integration.test_local_media_admission import TWO_CHANNELS

    gate = mux_case[2]
    assert callable(getattr(gate, "prepare_viewer", None)), (
        "short selection port missing"
    )
    w = wall(mux_case)
    lease = gate.redeem(shared_ticket(mux_case, w), budget=budget())

    def no_decrypt(*args):
        pytest.fail("credential-free viewer selection decrypted credentials")

    with monkeypatch.context() as patch:
        patch.setattr(gate._cipher, "open", no_decrypt)
        selected = gate.prepare_viewer(lease, budget=budget())
        assert selected.stream == "sub" and selected.guid == TWO_CHANNELS[0].guid
        assert gate.prepare_viewer(lease, budget=budget()) == selected
    assert gate._engine.pool.checkedout() == 0
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT state FROM wso_private.tvt_local_media_leases WHERE id=:id"
                ),
                {"id": lease.id},
            ).scalar_one()
            == "LOGIN"
        )
    reservation = gate.reserve_master(lease, budget=budget())
    gate.prepare_login(reservation, budget=budget())
    original = SyntheticOriginal(reservation)
    gate.register_original(reservation, original, original)
    gate.activate_master(reservation, original.proof, budget=budget())
    slot = gate.reserve_slot(
        lease, reservation, binding=original.binding_for(selected.guid), budget=budget()
    )
    viewer = gate.admit_viewer(lease, slot, registration=uuid4(), budget=budget())
    assert viewer.lease_id == lease.id


def test_ports_selection_rejects_copy_and_known_denial_before_sql(
    mux_case, monkeypatch
):
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    assert callable(getattr(gate, "prepare_viewer", None)), (
        "short selection port missing"
    )
    lease = gate.redeem(shared_ticket(mux_case, wall(mux_case)), budget=budget())

    def no_checkout(*args, **kwargs):
        pytest.fail("foreign or known-denied lease reached SQL")

    with monkeypatch.context() as patch:
        patch.setattr(gate._engine, "begin", no_checkout)
        with pytest.raises(LocalDeviceFailure):
            gate.prepare_viewer(replace(lease), budget=budget())
        gate._retire_authority(lease.token)
        with pytest.raises(LocalDeviceFailure):
            gate.prepare_viewer(lease, budget=budget())


def test_ports_dedicated_decrypts_after_checkout_and_claims_once(mux_case, monkeypatch):
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    assert callable(getattr(gate, "prepare_dedicated", None)), (
        "short dedicated port missing"
    )
    _, _, _, main, _, _, _ = focus_setup(mux_case, claim_main=False)
    selected = gate.prepare_viewer(main, budget=budget())
    assert selected.stream == "main"
    decrypt = gate._cipher.open
    calls = []

    def outside(*args):
        assert gate._engine.pool.checkedout() == 0
        calls.append(1)
        return decrypt(*args)

    monkeypatch.setattr(gate._cipher, "open", outside)
    credentials, channel = gate.prepare_dedicated(main, budget=budget())
    assert credentials is not None and channel == selected and calls == [1]
    assert gate._engine.pool.checkedout() == 0
    with pytest.raises(LocalDeviceFailure):
        gate.prepare_dedicated(main, budget=budget())
    assert calls == [1]


@pytest.mark.parametrize("denial", ["cancel", "local", "sql"])
def test_ports_dedicated_rechecks_after_decrypt(mux_case, monkeypatch, denial):
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    assert callable(getattr(gate, "prepare_dedicated", None)), (
        "short dedicated port missing"
    )
    _, _, _, main, _, _, _ = focus_setup(mux_case, claim_main=False)
    request = budget()
    decrypt = gate._cipher.open

    def deny_after(*args):
        assert gate._engine.pool.checkedout() == 0
        raw = decrypt(*args)
        if denial == "cancel":
            request.cancel.set()
        elif denial == "local":
            gate._retire_authority(main.token)
        else:
            with mux_case[0][0]["ADMIN"].begin() as db:
                db.execute(
                    text(
                        "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                    ),
                    {"s": mux_case[0][1]["session"]},
                )
        return raw

    monkeypatch.setattr(gate._cipher, "open", deny_after)
    with pytest.raises(LocalDeviceFailure):
        gate.prepare_dedicated(main, budget=request)
    assert gate._engine.pool.checkedout() == 0


def test_dedicated_startup_authority_claimed_then_real_activation(mux_case):
    gate = mux_case[2]
    _, _, _, main, registration, local_custody, _ = focus_setup(
        mux_case, claim_main=False
    )
    # This historical fixture stores its future cleanup receipt eagerly. Startup
    # instead requires a still-unsettled issuer, as the actual prepared owner does.
    local_custody.receipt = None
    selected = gate.prepare_viewer(main, budget=budget())
    credentials, channel = gate.prepare_dedicated(main, budget=budget())
    assert credentials is not None and channel == selected
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT state FROM wso_private.tvt_local_media_leases WHERE id=:id"
                ),
                {"id": main.id},
            ).scalar_one()
            == "CLAIMED"
        )
    assert (
        gate.current_dedicated_startup(main, registration, selected, budget=budget())
        is True
    )
    assert gate._engine.pool.checkedout() == 0
    assert main.token not in gate._authorities
    # Actual activation, not the startup predicate, grants live observer authority.
    assert gate.activate(main, delivery_proof(), budget=budget()).state == "NEGOTIATING"
    assert gate.current(main) is True
    assert gate._engine.pool.checkedout() == 0


@pytest.mark.parametrize(
    "denial",
    [
        "focus_cancelled",
        "focus_expired",
        "revoked",
        "channel",
        "foreign",
        "registration",
        "selection",
    ],
)
def test_dedicated_startup_authority_rejects_changed_binding_or_sql_scope(
    mux_case, denial
):
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    _, _, focus, main, registration, local_custody, _ = focus_setup(
        mux_case, claim_main=False
    )
    local_custody.receipt = None
    selected = gate.prepare_viewer(main, budget=budget())
    gate.prepare_dedicated(main, budget=budget())
    if denial == "focus_cancelled":
        assert gate.settle_focus(focus, "CANCELLED").state == "CANCELLED"
    elif denial == "focus_expired":
        with mux_case[0][0]["ADMIN"].begin() as db:
            # Separate clock samples need margin under the 20-second span check.
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_focus_refs SET issued_at=clock_timestamp()-interval '30 seconds',expires_at=clock_timestamp()-interval '15 seconds' WHERE id=:id"
                ),
                {"id": gate.focus_identity(focus)[0]},
            )
    elif denial == "revoked":
        with mux_case[0][0]["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                ),
                {"s": mux_case[0][1]["session"]},
            )
    elif denial == "channel":
        with mux_case[0][0]["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_channels SET active=false WHERE id=:id"
                ),
                {"id": mux_case[1].channels[0].id},
            )
    elif denial == "foreign":
        main = replace(main)
    elif denial == "registration":
        registration = uuid4()
    else:
        selected = replace(selected, ordinal=selected.ordinal + 1)
    with pytest.raises(LocalDeviceFailure):
        gate.current_dedicated_startup(main, registration, selected, budget=budget())
    assert gate._engine.pool.checkedout() == 0


def test_ports_wall_control_purposes_are_noninterchangeable(mux_case):
    from uuid import UUID

    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    assert callable(getattr(gate, "redeem_wall_stop", None)), (
        "wall stop redemption missing"
    )
    assert callable(getattr(gate, "redeem_wall_heartbeat", None)), (
        "wall heartbeat redemption missing"
    )
    w, _, _, _, _, _ = setup_slot(mux_case)
    with app_scope(mux_case[0], "owner") as db:
        heartbeat = db.execute(
            text(
                "SELECT public.wso_tvt_local_media_wall_control_issue(:s,:w,'WALL_HEARTBEAT')"
            ),
            {"s": mux_case[0][1]["session"], "w": w},
        ).scalar_one()
    assert heartbeat
    with pytest.raises(LocalDeviceFailure):
        gate.redeem_wall_stop(heartbeat, budget=budget())
    assert gate.redeem_wall_heartbeat(heartbeat, budget=budget()) == UUID(w)
    with pytest.raises(LocalDeviceFailure):
        gate.redeem_wall_heartbeat(heartbeat, budget=budget())
    with app_scope(mux_case[0], "owner") as db:
        stop = db.execute(
            text("SELECT public.wso_tvt_local_media_wall_stop_issue(:s,:w)"),
            {"s": mux_case[0][1]["session"], "w": w},
        ).scalar_one()
    with pytest.raises(LocalDeviceFailure):
        gate.redeem_wall_heartbeat(stop, budget=budget())
    assert gate.redeem_wall_stop(stop, budget=budget()) == UUID(w)


def test_ports_heartbeat_does_not_revive_expired_wall(mux_case):
    gate = mux_case[2]
    assert callable(getattr(gate, "redeem_wall_heartbeat", None)), (
        "wall heartbeat redemption missing"
    )
    w = wall(mux_case)
    with mux_case[0][0]["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_walls SET heartbeat_at=clock_timestamp()-interval '40 seconds',expires_at=clock_timestamp()-interval '20 seconds' WHERE id=:w"
            ),
            {"w": w},
        )
    with app_scope(mux_case[0], "owner") as db:
        assert (
            db.execute(
                text(
                    "SELECT public.wso_tvt_local_media_wall_control_issue(:s,:w,'WALL_HEARTBEAT')"
                ),
                {"s": mux_case[0][1]["session"], "w": w},
            ).scalar_one()
            is None
        )


def test_ports_focus_settle_ticket_and_scoped_readback(mux_case):
    from uuid import UUID

    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    assert callable(getattr(gate, "redeem_focus_settle", None)), (
        "focus settlement redemption missing"
    )
    w, _, focus, _, _, _, _ = focus_setup(mux_case)
    identifier = gate._records[id(focus)].focus_id
    with app_scope(mux_case[0], "owner") as db:
        ticket = db.execute(
            text(
                "SELECT public.wso_tvt_local_media_focus_settle_issue(:s,:id,'CANCELLED')"
            ),
            {"s": mux_case[0][1]["session"], "id": identifier},
        ).scalar_one()
        denied = db.execute(
            text(
                "SELECT public.wso_tvt_local_media_focus_settle_issue(:s,:id,'ATTACHED')"
            ),
            {"s": mux_case[0][1]["session"], "id": identifier},
        ).scalar_one()
    assert denied is None
    assert gate.redeem_focus_settle(ticket, budget=budget()) == (
        identifier,
        UUID(w),
        "CANCELLED",
    )
    gate.settle_focus(focus, "CANCELLED")
    with pytest.raises(LocalDeviceFailure):
        gate.redeem_focus_settle(ticket, budget=budget())
    with app_scope(mux_case[0], "owner") as db:
        view = db.execute(
            text("SELECT public.wso_tvt_local_media_focus_read(:s,:id)"),
            {"s": mux_case[0][1]["session"], "id": identifier},
        ).scalar_one()
        hidden = db.execute(
            text("SELECT public.wso_tvt_local_media_focus_read(:s,:id)"),
            {"s": "0" * 64, "id": identifier},
        ).scalar_one()
    assert hidden is None and view["state"] == "CANCELLED" and view["wall_id"] == w
    assert set(view) == {
        "id",
        "wall_id",
        "lease_id",
        "direction",
        "state",
        "expires_at",
    }


def test_ports_focus_identity_is_retained_cleanup_identity():
    from wso_core.tvt.local_media_mux_types import _GRANT_SEAL, FocusGrant
    from wso_core.tvt.local_service import LocalDeviceFailure

    now = [1.0]
    gate, reservation = unit_transport(lambda: now[0])
    assert callable(getattr(gate, "focus_identity", None)), (
        "focus identity port missing"
    )
    identifier = uuid4()
    grant = gate._remember(
        FocusGrant(
            scope=reservation.scope,
            lease_id=uuid4(),
            direction="FORWARD",
            admitted_monotonic=1.0,
            expires_monotonic=10.0,
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "f" * 64,
        reservation.master_id,
        reservation.transport.native_generation,
        focus_id=identifier,
    )
    assert gate.focus_identity(grant) == (identifier, reservation.scope.wall_id)
    now[0] = 20.0
    assert gate.focus_identity(grant) == (identifier, reservation.scope.wall_id)
    assert grant.expires_monotonic == 10.0 and gate.current_focus(grant) is False
    with pytest.raises(LocalDeviceFailure):
        gate.focus_identity(replace(grant, _seal=_GRANT_SEAL))
    gate._engine.dispose()


def test_ports_new_sql_functions_have_exact_runtime_roles(mux_database):
    assert callable(getattr(facade().SqlMuxAdmission, "prepare_viewer", None)), (
        "short selection port missing"
    )
    with mux_database["ADMIN"].connect() as db:
        for signature, role in (
            (
                "public.wso_tvt_local_media_viewer_selection(text,uuid,uuid)",
                "wso_connection_worker",
            ),
            (
                "public.wso_tvt_local_media_wall_heartbeat_redeem(text,uuid)",
                "wso_connection_worker",
            ),
            ("public.wso_tvt_local_media_focus_read(text,uuid)", "wso_app"),
        ):
            for other in ("wso_app", "wso_connection_worker", "wso_job_worker"):
                assert db.execute(
                    text("SELECT has_function_privilege(:role,:fn,'EXECUTE')"),
                    {"role": other, "fn": signature},
                ).scalar_one() is (other == role)


@pytest.mark.parametrize("reason", ["expired", "wrong_target"])
def test_settlement_declined_attach_is_not_success(mux_case, reason):
    from wso_core.tvt.local_service import LocalDeviceFailure

    _, _, focus, main, _, _, _ = focus_setup(mux_case)
    gate = mux_case[2]
    if reason == "expired":
        with mux_case[0][0]["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE wso_private.tvt_local_media_focus_refs SET issued_at=statement_timestamp()-interval '30 seconds',expires_at=statement_timestamp()-interval '10 seconds' WHERE id=:id"
                ),
                {"id": gate.focus_identity(focus)[0]},
            )
    with pytest.raises(LocalDeviceFailure):
        gate.settle_focus(
            focus, "ATTACHED", viewer=uuid4() if reason == "wrong_target" else main.id
        )
    assert not gate._records[id(focus)].closed
    cleanup = gate.settle_focus(
        focus, "EXPIRED" if reason == "expired" else "CANCELLED"
    )
    assert cleanup.state == ("EXPIRED" if reason == "expired" else "CANCELLED")


@pytest.mark.parametrize("change", ["return", "stop"])
def test_settlement_ack_requires_current_exact_sql_state(mux_case, change):
    w, _, focus, main, _, _, _ = focus_setup(mux_case)
    gate = mux_case[2]
    ack = gate.settle_focus(focus, "ATTACHED", viewer=main.id)
    assert type(ack).__name__ == "FocusSettlement", (
        "void return is not settlement proof"
    )
    assert (
        ack.focus_id == gate.focus_identity(focus)[0]
        and ack.state == "MAIN_ACTIVE"
        and ack.attached_viewer == main.id
    )
    assert gate.focus_settlement_current(focus, ack, "ATTACHED", viewer=main.id) is True
    with mux_case[0][0]["WORKER"].begin() as db:
        observed = db.execute(
            text("SELECT public.wso_tvt_local_media_focus_settlement_observe(:a,:w)"),
            {"a": gate._records[id(focus)].authority, "w": gate.worker_epoch},
        ).scalar_one()
        assert observed["state"] == "MAIN_ACTIVE"
        assert (
            db.execute(text("SELECT pg_current_xact_id_if_assigned()")).scalar_one()
            is None
        )
        assert not db.execute(
            text(
                "SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='tuple'"
            )
        ).all()
    assert (
        gate.focus_settlement_current(focus, replace(ack), "ATTACHED", viewer=main.id)
        is False
    )
    if change == "return":
        gate.redeem_focus(focus_ticket(mux_case, main.id, "RETURN"), budget=budget())
    else:
        stop_wall(mux_case, w)
    assert (
        gate.focus_settlement_current(focus, ack, "ATTACHED", viewer=main.id) is False
    )


def test_settlement_terminal_cleanup_retries_after_expiry(mux_case, monkeypatch):
    _, _, focus, _, _, _, _ = focus_setup(mux_case)
    gate = mux_case[2]
    monkeypatch.setattr(gate, "_clock", lambda: focus.expires_monotonic + 1)
    ack = gate.settle_focus(focus, "CANCELLED")
    assert type(ack).__name__ == "FocusSettlement"
    assert ack.state == "CANCELLED"
    again = gate.settle_focus(focus, "CANCELLED")
    assert again.state == "CANCELLED" and again.focus_id == ack.focus_id
    assert gate.focus_settlement_current(focus, again, "CANCELLED") is True
    assert gate.current_focus(focus) is False


def test_settlement_late_ack_can_cancel_without_fake_native_cleanup(
    mux_case, monkeypatch
):
    _, _, focus, main, _, viewer_custody, native_custody = focus_setup(mux_case)
    gate = mux_case[2]
    attached = gate.settle_focus(focus, "ATTACHED", viewer=main.id)
    assert type(attached).__name__ == "FocusSettlement"
    monkeypatch.setattr(gate, "_clock", lambda: focus.expires_monotonic + 1)
    cancelled = gate.settle_focus(focus, "CANCELLED", viewer=main.id)
    assert cancelled.state == "CANCELLED" and cancelled.attached_viewer == main.id
    assert (
        gate.focus_settlement_current(focus, attached, "ATTACHED", viewer=main.id)
        is False
    )
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT state,cleanup_confirmed,mux_native_settled FROM wso_private.tvt_local_media_leases WHERE id=:id"
            ),
            {"id": main.id},
        ).one() == ("STOPPING", False, False)
    gate.finish_dedicated_viewer(main, viewer_custody.receipt)
    native_custody.receipt = original_receipt(
        main.id, main.worker_epoch, main.native_generation
    )
    gate.finish_dedicated(main, native_custody.receipt)
    again = gate.settle_focus(focus, "CANCELLED", viewer=main.id)
    assert again.state == "CANCELLED"
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT state,cleanup_confirmed FROM wso_private.tvt_local_media_leases WHERE id=:id"
            ),
            {"id": main.id},
        ).one() == ("CLOSED", True)


def recovery_reserve(case, *, channel=None):
    gate = case[2]
    assert callable(getattr(gate, "begin_master_attempt", None)), (
        "R176 attempt port missing"
    )
    w = wall(case)
    lease = gate.redeem(shared_ticket(case, w, channel), budget=budget())
    attempt = gate.begin_master_attempt(lease)
    reservation = gate.reserve_master(lease, budget=budget(), attempt=attempt)
    return w, lease, attempt, reservation


def not_created_receipt(reservation):
    from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL

    return replace(
        original_receipt(
            reservation.master_id,
            reservation.scope.worker_epoch,
            reservation.transport.native_generation,
        ),
        original_state="NOT_CREATED",
        _seal=_CUSTODY_SEAL,
    )


def test_recovery_attempt_is_local_exact_and_inflight_is_unresolved(monkeypatch):
    from wso_core.tvt.local_media_admission import _SEAL, LocalMediaLease
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate, _ = unit_transport()
    lease = LocalMediaLease("a" * 64, gate.worker_epoch, uuid4(), uuid4(), _SEAL)
    gate._issued_leases[id(lease)] = lease
    monkeypatch.setattr(
        gate,
        "_sql",
        lambda *a, **kw: pytest.fail("local/inflight operation reached SQL"),
    )
    attempt = gate.begin_master_attempt(lease)
    with pytest.raises(LocalDeviceFailure):
        gate.reserve_master(lease, budget=budget(), attempt=replace(attempt))
    with pytest.raises(LocalDeviceFailure):
        gate.begin_master_attempt(replace(lease))
    gate._attempts[id(attempt)].phase = "RUNNING"
    assert gate.resolve_master_attempt(attempt, budget=budget()) is None
    assert gate.dispose() is False
    gate._engine.dispose()


def test_recovery_unstarted_stop_requires_exact_original_receipt(mux_case, monkeypatch):
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    w, lease, _, reservation = recovery_reserve(mux_case)
    stop_wall(mux_case, w)
    claim = gate.claim_unstarted_master(reservation)
    original = SyntheticOriginal(reservation)
    gate.register_unstarted_original(claim, original, original)
    with pytest.raises(LocalDeviceFailure):
        gate.finish_unstarted_master(
            claim, not_created_receipt(reservation), budget=budget()
        )
    assert wall_state(mux_case, w) == "STOPPING"
    original.receipt = not_created_receipt(reservation)
    monkeypatch.setattr(
        gate._cipher,
        "open",
        lambda *args: pytest.fail("empty cleanup decrypted credentials"),
    )
    closure = gate.finish_unstarted_master(claim, original.receipt, budget=budget())
    assert closure.master_id == reservation.master_id and lease.id in closure.lease_ids
    assert gate.unstarted_master_closed(claim, closure) is True
    assert gate.unstarted_master_closed(replace(claim), closure) is False
    assert gate.unstarted_master_closed(claim, replace(closure)) is False
    assert wall_state(mux_case, w) == "CLOSED"
    assert (
        gate.finish_unstarted_master(claim, original.receipt, budget=budget())
        is closure
    )


@pytest.mark.parametrize("acquisition", ["login", "registered"])
def test_recovery_unstarted_rejects_prior_acquisition(mux_case, acquisition):
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    _, _, _, reservation = recovery_reserve(mux_case)
    if acquisition == "login":
        gate.prepare_login(reservation, budget=budget())
    else:
        original = SyntheticOriginal(reservation)
        gate.register_original(reservation, original, original)
    with pytest.raises(LocalDeviceFailure):
        gate.claim_unstarted_master(reservation)


def test_recovery_lost_commit_returns_same_creator_and_followers(mux_case, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    assert callable(getattr(gate, "begin_master_attempt", None)), (
        "R176 attempt port missing"
    )
    w = wall(mux_case)
    lease = gate.redeem(shared_ticket(mux_case, w), budget=budget())
    attempt = gate.begin_master_attempt(lease)
    execute = gate._sql

    def lost(function, *args, **kwargs):
        value = execute(function, *args, **kwargs)
        if function == "master_reserve":
            raise SQLAlchemyError("synthetic lost result after commit")
        return value

    monkeypatch.setattr(gate, "_sql", lost)
    with pytest.raises(LocalDeviceFailure):
        gate.reserve_master(lease, budget=budget(), attempt=attempt)
    monkeypatch.setattr(gate, "_sql", execute)
    resolved = gate.resolve_master_attempt(attempt, budget=budget())
    assert resolved.outcome == "RESERVED" and resolved.reservation.creator is True
    assert gate.master_resolution_current(attempt, resolved) is True
    assert gate.master_resolution_current(replace(attempt), resolved) is False
    assert gate.master_resolution_current(attempt, replace(resolved)) is False
    assert gate.resolve_master_attempt(attempt, budget=budget()) is resolved
    other = gate.redeem(
        shared_ticket(mux_case, w, mux_case[1].channels[1].id), budget=budget()
    )
    follower_attempt = gate.begin_master_attempt(other)
    monkeypatch.setattr(gate, "_sql", lost)
    with pytest.raises(LocalDeviceFailure):
        gate.reserve_master(other, budget=budget(), attempt=follower_attempt)
    monkeypatch.setattr(gate, "_sql", execute)
    follower = gate.resolve_master_attempt(follower_attempt, budget=budget())
    assert follower.reservation.creator is False
    assert follower.reservation.master_id == resolved.reservation.master_id
    assert follower.reservation.transport is resolved.reservation.transport


def test_recovery_absent_tombstone_blocks_late_reserve_and_closes_only_lease(
    mux_case, monkeypatch
):
    from sqlalchemy.exc import DBAPIError, SQLAlchemyError
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    assert callable(getattr(gate, "begin_master_attempt", None)), (
        "R176 attempt port missing"
    )
    w = wall(mux_case)
    lease = gate.redeem(shared_ticket(mux_case, w), budget=budget())
    attempt = gate.begin_master_attempt(lease)
    execute = gate._sql
    late = []

    def delayed(function, *args, **kwargs):
        if function == "master_reserve":
            late.append((function, args, kwargs))
            raise SQLAlchemyError("synthetic delayed original request")
        return execute(function, *args, **kwargs)

    monkeypatch.setattr(gate, "_sql", delayed)
    with pytest.raises(LocalDeviceFailure):
        gate.reserve_master(lease, budget=budget(), attempt=attempt)
    monkeypatch.setattr(gate, "_sql", execute)
    stop_wall(mux_case, w)
    resolved = gate.resolve_master_attempt(attempt, budget=budget())
    assert resolved.outcome == "ABSENT" and resolved.reservation is None
    function, args, kwargs = late[0]
    assert execute(function, *args, **kwargs) is None
    with pytest.raises(DBAPIError):
        wall(mux_case)
    closure = gate.finish_absent_attempt(attempt, resolved, budget=budget())
    assert closure.lease_id == lease.id and closure.master_id is None
    assert gate.absent_attempt_closed(attempt, resolved, closure) is True
    assert gate.absent_attempt_closed(attempt, replace(resolved), closure) is False
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT state,cleanup_confirmed,mux_native_settled FROM wso_private.tvt_local_media_leases WHERE id=:id"
            ),
            {"id": lease.id},
        ).one() == ("CLOSED", True, False)
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.tvt_local_media_masters WHERE wall_id=:id"
                ),
                {"id": w},
            ).scalar_one()
            == 0
        )
    assert wall_state(mux_case, w) == "CLOSED"


def test_recovery_unknown_lookup_retains_charge(mux_case, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    assert callable(getattr(gate, "begin_master_attempt", None)), (
        "R176 attempt port missing"
    )
    lease = gate.redeem(shared_ticket(mux_case, wall(mux_case)), budget=budget())
    attempt = gate.begin_master_attempt(lease)
    monkeypatch.setattr(
        gate,
        "_sql",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            SQLAlchemyError("synthetic unavailable lookup")
        ),
    )
    with pytest.raises(LocalDeviceFailure):
        gate.reserve_master(lease, budget=budget(), attempt=attempt)
    assert gate.resolve_master_attempt(attempt, budget=budget()) is None
    assert gate.dispose() is False


def test_recovery_unadopted_follower_preserves_live_creator(mux_case):
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    assert callable(getattr(gate, "begin_master_attempt", None)), (
        "R176 attempt port missing"
    )
    w, _, creator, _, _, viewer = setup_slot(mux_case)
    gate.activate_viewer(viewer, delivery_proof(), budget=budget())
    other = gate.redeem(
        shared_ticket(mux_case, w, mux_case[1].channels[1].id), budget=budget()
    )
    attempt = gate.begin_master_attempt(other)
    follower = gate.reserve_master(other, budget=budget(), attempt=attempt)
    closure = gate.finish_unadopted_follower(other, follower, budget=budget())
    assert gate.unadopted_viewer_closed(other, follower, closure) is True
    assert gate.unadopted_viewer_closed(replace(other), follower, closure) is False
    assert gate.current_transport(creator.transport) is True
    with pytest.raises(LocalDeviceFailure):
        gate.claim_unstarted_master(follower)
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT state,cleanup_confirmed,mux_native_settled FROM wso_private.tvt_local_media_leases WHERE id=:id"
            ),
            {"id": other.id},
        ).one() == ("CLOSED", True, False)
        assert db.execute(
            text(
                "SELECT state,cleanup_confirmed FROM wso_private.tvt_local_media_masters WHERE id=:id"
            ),
            {"id": creator.master_id},
        ).one() == ("ACTIVE", False)


@pytest.mark.parametrize("crossed", [0, 1])
def test_recovery_r1_crossed_followers_deny_before_fencing(monkeypatch, crossed):
    import json
    from datetime import UTC, datetime, timedelta

    from wso_core.tvt.local_media_admission import _SEAL, LocalMediaLease
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate, creator = unit_transport()
    original = SyntheticOriginal(creator)
    gate.register_original(creator, original, original)
    scope = json.loads(gate._scope_json(creator.scope))
    leases = [
        LocalMediaLease(
            ("b" if i == 0 else "c") * 64, gate.worker_epoch, uuid4(), uuid4(), _SEAL
        )
        for i in range(2)
    ]
    for lease in leases:
        gate._issued_leases[id(lease)] = lease
    calls = []

    def sql(function, args, parameters, budget=None):
        lease = next(v for v in leases if v.token == args.get("a"))
        if function == "master_attempt_scope":
            return scope
        if function == "master_reserve":
            return {
                **scope,
                "master_id": str(creator.master_id),
                "native_generation": str(creator.transport.native_generation),
                "operation_native": str(args["mn"]),
                "lease_id": str(lease.id),
                "outcome": "RESERVED",
                "creator": False,
                "expires_at": datetime.now(UTC) + timedelta(seconds=20),
            }
        assert function == "unadopted_follower_close"
        calls.append(lease.id)
        return {
            **scope,
            "master_id": str(creator.master_id),
            "lease_id": str(lease.id),
            "closed": True,
        }

    monkeypatch.setattr(gate, "_sql", sql)
    followers = [
        gate.reserve_master(v, budget=budget(), attempt=gate.begin_master_attempt(v))
        for v in leases
    ]
    with pytest.raises(LocalDeviceFailure):
        gate.finish_unadopted_follower(
            leases[crossed], followers[1 - crossed], budget=budget()
        )
    assert calls == []
    assert all(id(v) not in gate._lease_cleanup for v in leases)
    for lease, follower in zip(leases, followers, strict=True):
        closure = gate.finish_unadopted_follower(lease, follower, budget=budget())
        assert gate.unadopted_viewer_closed(lease, follower, closure)
        assert (
            gate.finish_unadopted_follower(lease, follower, budget=budget()) is closure
        )
    assert len(calls) == 2
    gate._engine.dispose()


def recovery_claim_legacy(case, lease):
    with case[0][0]["WORKER"].begin() as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM public.wso_tvt_local_media_use(:a,:w,:n)"),
                case[2]._args(lease),
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize("mode", ["absent", "follower", "unstarted"])
@pytest.mark.parametrize("stop", ["close", "revoke"])
def test_recovery_r1_legacy_claim_history_survives_stop(mux_case, mode, stop):
    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    if mode == "follower":
        w, _, _, _, _, _ = setup_slot(mux_case)
        lease = gate.redeem(
            shared_ticket(mux_case, w, mux_case[1].channels[1].id), budget=budget()
        )
        attempt = gate.begin_master_attempt(lease)
        reservation = gate.reserve_master(lease, budget=budget(), attempt=attempt)
    else:
        w = wall(mux_case)
        lease = gate.redeem(shared_ticket(mux_case, w), budget=budget())
        attempt = gate.begin_master_attempt(lease)
        if mode == "unstarted":
            reservation = gate.reserve_master(lease, budget=budget(), attempt=attempt)
        else:
            resolved = gate.resolve_master_attempt(attempt, budget=budget())
            assert resolved.outcome == "ABSENT"
    recovery_claim_legacy(mux_case, lease)
    if stop == "close":
        gate.close(lease, cleanup_confirmed=False)
    else:
        with mux_case[0][0]["ADMIN"].begin() as db:
            db.execute(
                text(
                    "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                ),
                {"s": mux_case[0][1]["session"]},
            )
    with pytest.raises(LocalDeviceFailure):
        if mode == "absent":
            gate.finish_absent_attempt(attempt, resolved, budget=budget())
        elif mode == "follower":
            gate.finish_unadopted_follower(lease, reservation, budget=budget())
        else:
            claim = gate.claim_unstarted_master(reservation)
            original = SyntheticOriginal(reservation)
            gate.register_unstarted_original(claim, original, original)
            original.receipt = not_created_receipt(reservation)
            gate.finish_unstarted_master(claim, original.receipt, budget=budget())
    with mux_case[0][0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT state,cleanup_confirmed,mux_viewer_settled,mux_native_settled FROM wso_private.tvt_local_media_leases WHERE id=:id"
            ),
            {"id": lease.id},
        ).one() == ("STOPPING", False, False, False)


def test_recovery_r1_inherited_open_marks_before_callback(mux_case):
    from wso_core.tvt.local_service import LocalDeviceFailure

    from tests.tvt_parity.test_local_media_service import Session

    gate = mux_case[2]
    _, lease, _, reservation = recovery_reserve(mux_case)

    def starter(credentials, channel, current):
        with pytest.raises(LocalDeviceFailure):
            gate.claim_unstarted_master(reservation)
        return Session()

    gate.open(lease, starter, budget=budget())
    gate.close(lease, cleanup_confirmed=False)
    with pytest.raises(LocalDeviceFailure):
        gate.claim_unstarted_master(reservation)


def test_recovery_r1_claim_overlaps_absent_close(mux_case):
    import threading

    from wso_core.tvt.local_service import LocalDeviceFailure

    gate = mux_case[2]
    lease = gate.redeem(shared_ticket(mux_case, wall(mux_case)), budget=budget())
    attempt = gate.begin_master_attempt(lease)
    resolved = gate.resolve_master_attempt(attempt, budget=budget())
    entered = threading.Event()
    results = []

    def close():
        entered.set()
        try:
            gate.finish_absent_attempt(attempt, resolved, budget=budget())
            results.append("closed")
        except LocalDeviceFailure:
            results.append("denied")

    thread = threading.Thread(target=close)
    try:
        with mux_case[0][0]["WORKER"].begin() as db:
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM public.wso_tvt_local_media_use(:a,:w,:n)"
                    ),
                    gate._args(lease),
                ).scalar_one()
                == 1
            )
            db.execute(
                text("SELECT public.wso_tvt_local_media_close(:a,:w,:n,false)"),
                gate._args(lease),
            )
            thread.start()
            assert entered.wait(2)
        thread.join(5)
        assert not thread.is_alive()
        assert results == ["denied"]
    finally:
        if thread.ident is not None:
            thread.join(5)


def test_recovery_r1_legacy_nongroup_open_still_completes(mux_case):
    from tests.integration.test_local_media_admission import issue
    from tests.tvt_parity.test_local_media_service import Session

    local, inventory, gate = mux_case
    lease = gate.redeem(issue((local, inventory, gate, None, None)), budget=budget())
    native = Session()
    opened = gate.open(
        lease, lambda credentials, channel, current: native, budget=budget()
    )
    assert opened is native
    assert gate.activate(lease, native.proof, budget=budget()).state == "NEGOTIATING"
    assert native.close() is True
    gate.close(lease, cleanup_confirmed=True)
    with local[0]["ADMIN"].connect() as db:
        assert db.execute(
            text(
                "SELECT state,cleanup_confirmed,mux_wall_id,mux_acquisition_started FROM wso_private.tvt_local_media_leases WHERE id=:id"
            ),
            {"id": lease.id},
        ).one() == ("CLOSED", True, None, False)


@pytest.mark.parametrize("boundary", ["facade", "sql"])
def test_r186_initial_binding_enters_negotiating_without_delivery(mux_case, boundary):
    import json
    from dataclasses import asdict

    from tests.tvt_parity.test_local_media_service import Session

    _, lease, _, _, _, viewer = setup_slot(mux_case)
    gate = mux_case[2]
    initial = Session().proof
    assert (
        initial.codec is None
        and not initial.codec_supported
        and not initial.framing_verified
        and not initial.timing_verified
    )
    custody = SyntheticViewerCustody(viewer.lease_id, viewer.registration)
    gate.register_viewer_custodian(viewer, custody)
    if boundary == "facade":
        result = gate.activate_viewer(viewer, initial, budget=budget())
        assert result.state == "NEGOTIATING"
    else:
        with mux_case[0][0]["WORKER"].begin() as db:
            result = db.execute(
                text(
                    "SELECT public.wso_tvt_local_media_viewer_activate(:a,:w,:n,:r,CAST(:p AS jsonb))"
                ),
                {
                    **gate._args(lease),
                    "r": viewer.registration,
                    "p": json.dumps(asdict(initial)),
                },
            ).scalar_one()
        assert result is not None and result["state"] == "NEGOTIATING"
    with mux_case[0][0]["ADMIN"].connect() as db:
        stored = db.execute(
            text(
                "SELECT permission_proof FROM wso_private.tvt_local_media_grants WHERE lease_id=:id"
            ),
            {"id": viewer.lease_id},
        ).scalar_one()
    assert stored == asdict(initial)


@pytest.mark.parametrize(
    "flag",
    [
        "login_accepted",
        "same_original_session",
        "serial_matched",
        "channel_matched",
        "live_permission",
    ],
)
def test_r186_missing_initial_binding_still_denies(mux_case, flag):
    from wso_core.tvt.local_service import LocalDeviceFailure

    from tests.tvt_parity.test_local_media_service import Session

    _, _, _, _, _, viewer = setup_slot(mux_case)
    with pytest.raises(LocalDeviceFailure):
        mux_case[2].activate_viewer(
            viewer, replace(Session().proof, **{flag: False}), budget=budget()
        )


def test_r186_playing_still_requires_complete_delivery(mux_case):
    import json
    from dataclasses import asdict

    from sqlalchemy.exc import DBAPIError
    from wso_core.tvt.local_service import LocalDeviceFailure

    from tests.tvt_parity.test_local_media_service import Session

    _, lease, _, _, _, viewer = setup_slot(mux_case)
    gate = mux_case[2]
    gate.activate_viewer(viewer, delivery_proof(), budget=budget())
    initial = Session().proof
    with pytest.raises(LocalDeviceFailure) as denied:
        gate.playing(lease, initial)
    assert denied.value.code == "LOCAL_DEVICE_PROTOCOL_INVALID"
    with (
        pytest.raises(DBAPIError) as sql_denied,
        mux_case[0][0]["WORKER"].begin() as db,
    ):
        db.execute(
            text(
                "SELECT public.wso_tvt_local_media_playing(:a,:w,:n,CAST(:p AS jsonb))"
            ),
            {**gate._args(lease), "p": json.dumps(asdict(initial))},
        ).scalar_one()
    assert sql_denied.value.orig.sqlstate == "22023"
    assert gate.playing(lease, delivery_proof()).state == "PLAYING"


@pytest.mark.parametrize("denial", ["expiry", "revocation", "copied_grant"])
def test_r186_initial_proof_cannot_override_scope_denial(mux_case, denial):
    from wso_core.tvt.local_media_mux_types import _GRANT_SEAL
    from wso_core.tvt.local_service import LocalDeviceFailure

    from tests.tvt_parity.test_local_media_service import Session

    _, _, _, _, _, viewer = setup_slot(mux_case)
    if denial == "copied_grant":
        viewer = replace(viewer, _seal=_GRANT_SEAL)
    else:
        with mux_case[0][0]["ADMIN"].begin() as db:
            if denial == "expiry":
                db.execute(
                    text(
                        "UPDATE wso_private.tvt_local_media_leases SET heartbeat_at=statement_timestamp()-interval '31 seconds',expires_at=statement_timestamp()-interval '1 second' WHERE id=:id"
                    ),
                    {"id": viewer.lease_id},
                )
            else:
                db.execute(
                    text(
                        "UPDATE public.web_sessions SET revoked_at=clock_timestamp() WHERE session_digest=:s"
                    ),
                    {"s": mux_case[0][1]["session"]},
                )
    with pytest.raises(LocalDeviceFailure):
        mux_case[2].activate_viewer(viewer, Session().proof, budget=budget())


def test_r186_initial_binding_reaches_sql_without_upgrading(monkeypatch):
    import json
    from dataclasses import asdict

    from wso_core.tvt.local_media_admission import _SEAL, LocalMediaLease
    from wso_core.tvt.local_media_mux_types import (
        _GRANT_SEAL,
        MuxEpochIdentity,
        MuxSlotIdentity,
        ViewerGrant,
    )

    from tests.tvt_parity.test_local_media_service import Session

    gate, creator = unit_transport()
    lease = LocalMediaLease("b" * 64, gate.worker_epoch, uuid4(), uuid4(), _SEAL)
    slot = MuxSlotIdentity(
        MuxEpochIdentity(1, uuid4().bytes_le), uuid4().bytes_le, uuid4().bytes_le, 2
    )
    viewer = gate._remember(
        ViewerGrant(
            scope=creator.scope,
            slot=slot,
            lease_id=lease.id,
            registration=uuid4(),
            expires_monotonic=20,
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        lease.token,
        creator.master_id,
        lease.native_generation,
        lease=lease,
    )
    initial = Session().proof

    class ReachedInitialSQL(Exception):
        pass

    def query(function, args, *positional):
        assert function == "viewer_activate" and json.loads(args["p"]) == asdict(
            initial
        )
        raise ReachedInitialSQL

    monkeypatch.setattr(gate, "_sql", query)
    with pytest.raises(ReachedInitialSQL):
        gate.activate_viewer(viewer, initial, budget=budget())
    gate._engine.dispose()


def test_observers_are_read_only_without_xid_or_row_locks(mux_case):
    _, _, reservation, _, _, _ = setup_slot(mux_case)
    gate = mux_case[2]
    record = gate._reservation(reservation)
    with mux_case[0][0]["WORKER"].begin() as db:
        assert db.execute(
            text("SELECT public.wso_tvt_local_media_master_observe(:ma,:w,:mn)"),
            gate._master_args(record),
        ).scalar_one()
        assert (
            db.execute(text("SELECT pg_current_xact_id_if_assigned()")).scalar_one()
            is None
        )
        assert not db.execute(
            text(
                "SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='tuple'"
            )
        ).all()


def _api9_wall_view_port(case):
    with case[0][0]["ADMIN"].connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT to_regprocedure('public.wso_tvt_local_media_wall_view(text,uuid)')"
                )
            ).scalar_one()
            is not None
        ), "scoped terminal wall readback is missing"


@pytest.mark.parametrize("state", ["ACTIVE", "STOPPING", "CLOSED"])
def test_api9_wall_view_terminal_scoped_readonly(mux_case, state):
    _api9_wall_view_port(mux_case)
    w = wall(mux_case)
    with mux_case[0][0]["ADMIN"].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.tvt_local_media_walls SET state=:state WHERE id=:wall"
            ),
            {"state": state, "wall": w},
        )
    with app_scope(mux_case[0], "owner") as db:
        xid_before = db.execute(
            text("SELECT pg_current_xact_id_if_assigned()")
        ).scalar_one()
        view = db.execute(
            text("SELECT public.wso_tvt_local_media_wall_view(:s,:wall)"),
            {"s": mux_case[0][1]["session"], "wall": w},
        ).scalar_one()
        assert view["id"] == w and view["state"] == state
        assert set(view) == {"id", "state", "expires_at"}
        assert (
            db.execute(text("SELECT pg_current_xact_id_if_assigned()")).scalar_one()
            == xid_before
        )
        assert not db.execute(
            text(
                "SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='tuple'"
            )
        ).all()
        hidden = db.execute(
            text("SELECT public.wso_tvt_local_media_wall_view(:s,:wall)"),
            {"s": "0" * 64, "wall": w},
        ).scalar_one()
        assert hidden is None
    with app_scope(mux_case[0], "staff") as db:
        assert (
            db.execute(
                text("SELECT public.wso_tvt_local_media_wall_view(:s,:wall)"),
                {"s": mux_case[0][1]["session"], "wall": w},
            ).scalar_one()
            is None
        )


@pytest.mark.parametrize("revocation", ["session", "tenant"])
def test_api9_wall_view_requires_current_session_epoch(mux_case, revocation):
    _api9_wall_view_port(mux_case)
    w = wall(mux_case)
    with mux_case[0][0]["ADMIN"].begin() as db:
        if revocation == "session":
            db.execute(
                text(
                    "UPDATE public.web_sessions SET created_at=statement_timestamp()-interval '1 minute',expires_at=statement_timestamp()-interval '1 second' WHERE session_digest=:s"
                ),
                {"s": mux_case[0][1]["session"]},
            )
        else:
            db.execute(
                text(
                    "UPDATE public.tenants SET job_generation=job_generation+1 WHERE id=:t"
                ),
                {"t": mux_case[0][1]["tenant"]},
            )
    with app_scope(mux_case[0], "owner") as db:
        assert (
            db.execute(
                text("SELECT public.wso_tvt_local_media_wall_view(:s,:wall)"),
                {"s": mux_case[0][1]["session"], "wall": w},
            ).scalar_one()
            is None
        )


@pytest.mark.parametrize("heartbeat", [False, True])
def test_api9_wall_expiry_clipped_to_authoritative_session(mux_case, heartbeat):
    from datetime import datetime

    w = wall(mux_case) if heartbeat else None
    with mux_case[0][0]["ADMIN"].begin() as db:
        expiry = db.execute(
            text(
                "UPDATE public.web_sessions SET expires_at=statement_timestamp()+interval '15 seconds' WHERE session_digest=:s RETURNING expires_at"
            ),
            {"s": mux_case[0][1]["session"]},
        ).scalar_one()
    with app_scope(mux_case[0], "owner") as db:
        view = db.execute(
            text(
                "SELECT public.wso_tvt_local_media_wall_read(:s,:wall,true)"
                if heartbeat
                else "SELECT public.wso_tvt_local_media_wall_issue(:s,30)"
            ),
            {"s": mux_case[0][1]["session"], "wall": w},
        ).scalar_one()
    assert view is not None
    assert datetime.fromisoformat(view["expires_at"]) <= expiry


def test_api9_wall_view_app_only_acl(mux_database):
    with mux_database["ADMIN"].connect() as db:
        signature = "public.wso_tvt_local_media_wall_view(text,uuid)"
        assert (
            db.execute(
                text("SELECT to_regprocedure(:fn)"), {"fn": signature}
            ).scalar_one()
            is not None
        ), "terminal wall readback missing"
        for role in ("wso_app", "wso_connection_worker", "wso_job_worker"):
            assert db.execute(
                text("SELECT has_function_privilege(:role,:fn,'EXECUTE')"),
                {"role": role, "fn": signature},
            ).scalar_one() is (role == "wso_app")
