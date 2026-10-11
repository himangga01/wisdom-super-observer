"""Two original MAIN-to-RETURN current-observation schedules."""

from dataclasses import replace

import pytest
from test_local_media_mux_service import main_setup
from wso_core.tvt.local_media_mux_types import _GRANT_SEAL, FocusGrant
from wso_core.tvt.local_service import LocalVerifyBudget


def returning(admission, main):
    grant = FocusGrant(
        scope=admission.scope,
        lease_id=main.id,
        direction="RETURN",
        admitted_monotonic=2.0,
        expires_monotonic=22.0,
        _authority=object(),
        _seal=_GRANT_SEAL,
    )
    admission.tickets["return"] = grant
    return grant


def test_sql_return_commit_before_local_publication_preserves_exact_main():
    coordinator, admission, provider, _, _, main, _ = main_setup()
    active, ack = coordinator._main_acks[main.id]
    returning(admission, main)
    del admission.focus_acknowledgements[id(active)]  # SQL consumes MAIN_ACTIVE.
    calls = []

    def retention(lease, given, receipt):
        calls.append((lease, given, receipt))
        return lease is main and given is active and receipt is ack

    admission.current_main_retention = retention
    assert coordinator.current(main.id), "valid SQL RETURN precedes local publication"
    assert calls == [(main, active, ack)] and not provider.prepared.closing
    coordinator.reserve_focus("return", budget=LocalVerifyBudget(2000))
    assert coordinator.current(main.id)


def test_inflight_main_current_retries_exact_local_return_swap():
    coordinator, admission, _, _, _, main, _ = main_setup()
    active, ack = coordinator._main_acks[main.id]
    grant = returning(admission, main)
    calls = []

    def observe(given, receipt, transition=None, *, viewer=None):
        calls.append((given, receipt))
        if len(calls) == 1:
            del admission.focus_acknowledgements[id(active)]
            coordinator.reserve_focus("return", budget=LocalVerifyBudget(2000))
            return False
        return True

    admission.focus_settlement_current = observe
    admission.current_main_retention = lambda lease, given, receipt: observe(
        given, receipt
    )
    assert coordinator.current(main.id), "in-flight old ACK cannot deny new RETURN"
    assert coordinator._focus[id(grant)] is grant and calls == [(active, ack)]


@pytest.mark.parametrize("fault", ["revoke", "expire", "stop", "foreign"])
def test_return_retry_does_not_override_real_authority_or_original_retirement(fault):
    coordinator, admission, _provider, _, _, main, now = main_setup()
    grant = returning(admission, main)
    coordinator.reserve_focus("return", budget=LocalVerifyBudget(2000))
    if fault == "revoke":
        admission.denied = True
    elif fault == "expire":
        now[0] = grant.expires_monotonic
    elif fault == "stop":
        coordinator._dedicated[main.id].stopping = True
    else:
        copied = replace(grant, _seal=_GRANT_SEAL)
        coordinator._focus[id(grant)] = copied
    assert not coordinator.current(main.id)
