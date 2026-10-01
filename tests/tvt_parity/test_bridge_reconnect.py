"""Ownership and retirement after dispatch; no simulated native callbacks."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from wso_core.tvt.account_projection import AccountFailure


def test_abandoned_call_keeps_capacity_until_settlement():
    from wso_tvt_bridge.callback_registry import CallbackRegistry

    registry = CallbackRegistry(capacity=1, history_limit=4)
    first = registry.admit("call-a")
    registry.abandon(first)
    with pytest.raises(AccountFailure, match="SESSION_BUSY"):
        registry.admit("call-b")
    assert registry.settle(first) is False
    second = registry.admit("call-b")
    assert registry.settle(second) is True
    assert registry.settle(second) is False
    with pytest.raises(AccountFailure, match="ACCOUNT_INPUT_INVALID"):
        registry.admit("call-b")


def test_close_is_concurrent_idempotent_and_epochs_do_not_cross():
    from wso_tvt_bridge.callback_registry import CallbackRegistry

    first = CallbackRegistry(capacity=2, history_limit=4)
    old = first.admit("same")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: first.close(), range(16)))
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
        first.admit("late")
    fresh = CallbackRegistry(capacity=2, history_limit=4)
    new = fresh.admit("same")
    assert not fresh.settle(old)
    assert fresh.settle(new)
    assert not first.settle(old)
    assert first.active_count == 0


def test_bounded_history_never_forgets_one_terminal_result():
    from wso_tvt_bridge.callback_registry import CallbackRegistry

    registry = CallbackRegistry(capacity=1, history_limit=2)
    for value in ("a", "b"):
        assert registry.settle(registry.admit(value))
    with pytest.raises(AccountFailure, match="SESSION_BUSY"):
        registry.admit("c")


def test_close_defers_resource_disposal_until_real_call_settles():
    from wso_tvt_bridge.session_pool import SessionPool

    disposed = []
    pool = SessionPool(capacity=1, dispose=lambda: disposed.append("disposed"))
    slot = pool.registry.admit("owned")
    assert not pool.close(grace=0)
    assert disposed == []
    assert not pool.settle(slot)
    assert disposed == ["disposed"]
    assert pool.close(grace=0)
    assert disposed == ["disposed"]


def test_worker_budget_preserves_transport_cancellation_before_publication():
    from wso_api.tvt.session_service import worker_budget
    from wso_core.tvt.token_vault import remaining_budget, token_budget

    active = True
    published = []

    def transport_remaining():
        if not active:
            raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
        return 1000

    @worker_budget
    def operation(*, deadline_ms, correlation_id):
        nonlocal active
        assert remaining_budget() > 0
        active = False
        remaining_budget()
        published.append("incorrect-publication")

    with (
        token_budget(transport_remaining),
        pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"),
    ):
        operation(deadline_ms=1000, correlation_id="cancel")
    assert published == []
