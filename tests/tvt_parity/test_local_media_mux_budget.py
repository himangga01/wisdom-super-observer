"""One retained IPC/media host budget, with sealed single ownership."""

import importlib
import importlib.util
from dataclasses import replace
from uuid import uuid4

import pytest
from test_local_live_mux import setup
from wso_tvt_media.codec import MediaDenied


def ledger():
    name = "wso_tvt_media.mux_budget"
    assert importlib.util.find_spec(name), "common media credit ledger missing"
    return importlib.import_module(name).MediaCreditLedger()


def test_shared_credit_counts_every_stage_once():
    budget = ledger()
    _, (slot,) = setup()
    credit = budget.reserve_encoded(slot, frames=16, bytes=4 << 20)
    assert credit is not None
    assert budget.reserve_encoded(slot, frames=1, bytes=1) is None
    for stage in ("parent", "source", "decode"):
        old = credit
        credit = budget.transfer(credit, stage)
        assert credit.id == old.id
        with pytest.raises(MediaDenied):
            budget.release(old)
        assert budget.reserve_encoded(slot, frames=1, bytes=1) is None
    budget.release(credit)
    again = budget.reserve_encoded(slot, frames=16, bytes=4 << 20)
    assert again is not None
    budget.release(again)


def test_rgb_is_one_latest_and_inflight_conversion_is_separately_retained():
    budget = ledger()
    registration = uuid4()
    latest = budget.reserve_rgb(registration, bytes=16 << 20)
    assert latest is not None
    assert budget.reserve_rgb(registration, bytes=1) is None
    conversion = budget.reserve_conversion(registration, bytes=48 << 20)
    assert conversion is not None
    budget.release(latest)
    replacement = budget.reserve_rgb(registration, bytes=16 << 20)
    assert replacement is not None
    budget.release(replacement)
    budget.release(conversion)


def test_forged_or_foreign_credit_never_refunds_original_charge():
    budget = ledger()
    _, (slot,) = setup()
    credit = budget.reserve_encoded(slot, frames=1, bytes=4 << 20)
    assert credit is not None
    foreign = ledger()
    with pytest.raises(MediaDenied):
        foreign.release(credit)
    with pytest.raises((MediaDenied, TypeError, ValueError)):
        forged = replace(credit)
        budget.release(forged)
    assert budget.reserve_encoded(slot, frames=1, bytes=1) is None
    budget.release(credit)


def test_common_ipc_raw_and_rgb_cannot_exceed_host_ceiling():
    budget = ledger()
    from wso_tvt_bridge.local_live_mux_ipc import (
        release_media_credit,
        reserve_media_credit,
    )

    raw = reserve_media_credit(
        slot=None,
        registration=uuid4(),
        frames=0,
        bytes=(1 << 30) - (16 << 20),
        stage="raw",
    )
    assert raw is not None
    rgb = None
    try:
        rgb = budget.reserve_rgb(uuid4(), bytes=16 << 20)
        assert rgb is not None
        assert budget.reserve_conversion(uuid4(), bytes=1) is None
    finally:
        if rgb is not None:
            budget.release(rgb)
        release_media_credit(raw)


def test_encoded_aggregate_is_shared_across_ledgers_and_slots():
    from wso_core.tvt.local_media_mux_types import MuxSlotIdentity

    budget, other = ledger(), ledger()
    _, (original,) = setup()
    held = []
    try:
        for index in range(1, 17):
            slot = MuxSlotIdentity(
                original.epoch, bytes([index]) * 16, original.task, 2
            )
            credit = budget.reserve_encoded(slot, frames=1, bytes=4 << 20)
            assert credit is not None
            held.append(credit)
        extra = MuxSlotIdentity(original.epoch, b"z" * 16, original.task, 2)
        assert other.reserve_encoded(extra, frames=1, bytes=1) is None
        budget.release(held.pop())
        replacement = other.reserve_encoded(extra, frames=16, bytes=4 << 20)
        assert replacement is not None
        other.release(replacement)
    finally:
        for credit in held:
            budget.release(credit)
