"""Real admission retirement after refresh precedes Core transport publication.

Only SQL IO and native-original issuance are inert seams. No connection, child,
SDK, private input or browser is acquired by these controls.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from wso_core.tvt.local_media_mux_types import (
    _CUSTODY_SEAL,
    _GRANT_SEAL,
    MuxEpochIdentity,
    MuxSlotIdentity,
    SlotRetentionGrant,
    TransportGrant,
    ViewerGrant,
)
from wso_core.tvt.local_service import LocalDeviceFailure

from tests.integration.test_local_media_mux_admission import (
    SyntheticOriginal,
    original_receipt,
    unit_transport,
)


@pytest.fixture
def retirement(monkeypatch):
    gate, reservation = unit_transport()
    original = SyntheticOriginal(reservation)
    gate.register_original(reservation, original, original)
    monkeypatch.setattr(
        gate,
        "_observe",
        lambda _: {"expires_at": datetime.now(UTC) + timedelta(seconds=20)},
    )

    def sql(function, arguments, parameters, budget=None):
        assert function == "epoch_close"
        assert arguments["ma"] == "a" * 64
        assert arguments["w"] == reservation.scope.worker_epoch
        assert arguments["mn"] == reservation.transport.native_generation

    monkeypatch.setattr(gate, "_sql", sql)
    try:
        yield gate, reservation, original
    finally:
        # Engine construction is lazy; this releases it even in denied controls.
        gate._engine.dispose()


def confirm(reservation, original):
    original.receipt = original_receipt(
        reservation.master_id,
        reservation.scope.worker_epoch,
        reservation.transport.native_generation,
    )
    return original.receipt


@pytest.mark.parametrize("replacement_count", [1, 3])
def test_confirmed_old_epoch_closes_every_refreshed_transport(
    retirement, replacement_count
):
    gate, reservation, original = retirement
    fresh = reservation.transport
    for _ in range(replacement_count):
        fresh = gate.refresh_grant(fresh)
    assert not gate._record(fresh, TransportGrant, expired=True).closed
    assert gate.dispose() is False

    # Core kept the old handle when native replace_grant raised after admission
    # registered fresh. Its exact original receipt still retires the same epoch.
    receipt = confirm(reservation, original)
    gate.finish_epoch(reservation.transport, receipt)
    assert gate._record(fresh, TransportGrant, expired=True).closed
    assert not gate.current_transport(fresh)
    assert gate.dispose() is True


@pytest.mark.parametrize(
    "invalid", ["pending", "copy", "master", "native", "worker", "issuer"]
)
def test_unconfirmed_or_wrong_original_receipt_keeps_replacement_open(
    retirement, invalid
):
    gate, reservation, original = retirement
    fresh = gate.refresh_grant(reservation.transport)
    receipt = confirm(reservation, original)
    if invalid == "pending":
        original.receipt = None
    elif invalid == "copy":
        receipt = replace(receipt, _seal=_CUSTODY_SEAL)
    elif invalid == "issuer":
        original.issued_receipt = lambda: receipt
    else:
        field = {
            "master": "master_id",
            "native": "native_generation",
            "worker": "worker_epoch",
        }[invalid]
        receipt = replace(receipt, **{field: uuid4()}, _seal=_CUSTODY_SEAL)
        original.receipt = receipt

    with pytest.raises(LocalDeviceFailure):
        gate.finish_epoch(reservation.transport, receipt)
    assert not gate._record(fresh, TransportGrant, expired=True).closed
    assert gate.dispose() is False


def test_sql_close_failure_keeps_replacement_unsettled(retirement, monkeypatch):
    gate, reservation, original = retirement
    fresh = gate.refresh_grant(reservation.transport)
    receipt = confirm(reservation, original)
    sql = gate._sql

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("inert epoch close failure")

    monkeypatch.setattr(gate, "_sql", unavailable)
    with pytest.raises(LocalDeviceFailure):
        gate.finish_epoch(reservation.transport, receipt)
    assert not gate._record(fresh, TransportGrant, expired=True).closed
    assert gate.dispose() is False
    monkeypatch.setattr(gate, "_sql", sql)
    gate.finish_epoch(reservation.transport, receipt)
    assert gate.dispose() is True


@pytest.mark.parametrize("difference", ["master", "native", "worker"])
def test_epoch_receipt_cannot_close_another_transport_generation(
    retirement, difference
):
    gate, reservation, original = retirement
    fresh = gate.refresh_grant(reservation.transport)
    master, native, scope = reservation.master_id, fresh.native_generation, fresh.scope
    if difference == "master":
        master = uuid4()
    elif difference == "native":
        native = uuid4()
    else:
        scope = replace(scope, worker_epoch=uuid4())
    other = gate._remember(
        replace(fresh, scope=scope, native_generation=native, _seal=_GRANT_SEAL),
        "b" * 64,
        master,
        native,
    )
    gate.finish_epoch(reservation.transport, confirm(reservation, original))
    assert gate._record(fresh, TransportGrant, expired=True).closed
    other_record = gate._record(other, TransportGrant, expired=True)
    assert not other_record.closed
    assert not other_record.denied
    assert gate.dispose() is False


def test_epoch_transport_retirement_preserves_unsettled_viewer_receipt(retirement):
    gate, reservation, original = retirement
    fresh = gate.refresh_grant(reservation.transport)
    slot = MuxSlotIdentity(
        MuxEpochIdentity(1, uuid4().bytes), uuid4().bytes, uuid4().bytes, 2
    )
    retention = gate._remember(
        SlotRetentionGrant(
            scope=fresh.scope,
            slot=slot,
            expires_monotonic=30,
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "b" * 64,
        reservation.master_id,
        fresh.native_generation,
    )
    viewer = gate._remember(
        ViewerGrant(
            scope=fresh.scope,
            slot=slot,
            expires_monotonic=30,
            lease_id=uuid4(),
            registration=uuid4(),
            _authority=gate._issuer,
            _seal=_GRANT_SEAL,
        ),
        "c" * 64,
        reservation.master_id,
        fresh.native_generation,
    )
    gate.finish_epoch(reservation.transport, confirm(reservation, original))
    assert gate._record(fresh, TransportGrant, expired=True).closed
    assert gate._record(retention, SlotRetentionGrant, expired=True).closed
    assert not gate._record(viewer, ViewerGrant, expired=True).closed
    assert not gate.current_viewer(viewer)
    assert gate.dispose() is False
