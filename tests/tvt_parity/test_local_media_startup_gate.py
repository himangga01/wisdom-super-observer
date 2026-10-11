"""R132 bounds long startup transactions before checkout; no database or device."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from wso_core.tvt import local_media_admission as module
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget

from tests.tvt_parity.test_local_media_authority_gate import Clock, gated_admission


class WaitingSlot:
    def __init__(self, clock, *, cancel=None, available_after=None):
        self.clock = clock
        self.cancel = cancel
        self.available_after = available_after
        self.waits = []
        self.releases = 0

    def acquire(self, *, timeout):
        assert 0 < timeout <= 0.05
        self.waits.append(timeout)
        self.clock.now += timeout
        if self.cancel is not None and sum(self.waits) >= 0.10:
            self.cancel.set()
        return (
            self.available_after is not None and sum(self.waits) >= self.available_after
        )

    def release(self):
        self.releases += 1


@pytest.mark.parametrize(
    "milliseconds,cancel,want,elapsed",
    [
        (20000, False, "LOCAL_DEVICE_BUSY", 10.0),
        (120, False, "LOCAL_DEVICE_DEADLINE_EXCEEDED", 0.12),
        (20000, True, "LOCAL_DEVICE_CANCELLED", 0.10),
    ],
)
def test_startup_wait_is_bounded_and_keeps_caller_failure(
    monkeypatch, milliseconds, cancel, want, elapsed
):
    admission, sql = gated_admission()
    admission._engine.begin_error = LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
    clock = Clock(0.0)
    budget = LocalVerifyBudget(milliseconds, clock=clock)
    slot = WaitingSlot(clock, cancel=budget.cancel if cancel else None)
    admission._startup_slots = slot
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=clock))
    with pytest.raises(LocalDeviceFailure) as caught:
        admission.open(sql.grant(), lambda *args: None, budget=budget)
    assert caught.value.code == want
    assert elapsed - 0.002 <= clock.now <= elapsed + 0.001
    assert slot.releases == 0 and not admission._engine.statements


@pytest.mark.parametrize("fail_at", ["checkout", "settlement"])
def test_startup_slot_released_only_after_transaction_settles(fail_at):
    admission, sql = gated_admission()
    # Seven unrelated startup owners leave exactly one permit.
    slots = admission._startup_slots
    for _ in range(7):
        assert slots.acquire(blocking=False)
    seen = []

    @contextmanager
    def begin():
        assert not slots.acquire(blocking=False)
        seen.append("checkout")
        try:
            if fail_at == "checkout":
                raise LocalDeviceFailure()
            yield admission._engine
        finally:
            assert not slots.acquire(blocking=False)
            seen.append("settlement")
            raise LocalDeviceFailure()

    admission._engine.begin = begin
    with pytest.raises(LocalDeviceFailure):
        admission.open(sql.grant(), lambda *args: None, budget=LocalVerifyBudget(1000))
    assert seen == ["checkout", "settlement"]
    assert slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    for _ in range(8):
        slots.release()


def test_cancel_after_startup_acquire_releases_without_checkout(monkeypatch):
    admission, sql = gated_admission()
    admission._engine.begin_error = LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
    clock = Clock(0.0)
    budget = LocalVerifyBudget(20000, clock=clock)
    slot = WaitingSlot(clock, cancel=budget.cancel, available_after=0.10)
    admission._startup_slots = slot
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=clock))
    with pytest.raises(LocalDeviceFailure) as caught:
        admission.open(sql.grant(), lambda *args: None, budget=budget)
    assert caught.value.code == "LOCAL_DEVICE_CANCELLED"
    assert slot.releases == 1 and not admission._engine.statements
