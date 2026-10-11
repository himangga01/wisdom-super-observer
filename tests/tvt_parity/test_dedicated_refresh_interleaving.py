"""Preserved unsafe single-observation controls for the repaired barrier."""

from tests.tvt_parity.test_local_media_mux_service import main_setup


def test_direct_dedicated_refresh_change_can_return_false_with_live_rights():
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    original = admission.current_main_retention

    def crossed(*args):
        result = original(*args)
        owned.master.refresh_version += 1
        owned.master.refreshing = True
        return result

    admission.current_main_retention = crossed
    assert coordinator._current_dedicated_once(owned) is False
    assert not owned.stopping and not admission.denied
    admission.current_main_retention = original
    owned.master.refreshing = False
    assert coordinator._current_dedicated(owned) is True
    admission.current = lambda lease: False
    assert coordinator._current_dedicated(owned) is False


def test_sweep_can_close_main_after_crossed_refresh_observation():
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    original = admission.current_main_retention

    def crossed(*args):
        result = original(*args)
        owned.master.refresh_version += 1
        owned.master.refreshing = True
        return result

    admission.current_main_retention = crossed
    coordinator._current_dedicated = coordinator._current_dedicated_once
    closing_states = []
    original_close = coordinator._close_dedicated

    def closing(record):
        closing_states.append(record.master.state.value)
        return original_close(record)

    coordinator._close_dedicated = closing
    coordinator.sweep()
    assert owned.stopping and not admission.denied
    assert closing_states[0] == "ACTIVE"


def test_native_current_supplier_can_receive_transient_refresh_false():
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    observed = []

    class NativeProbe:
        def current(self, *, deadline_monotonic, current):
            owned.master.refresh_version += 1
            owned.master.refreshing = True
            observed.append(current())
            return observed[-1]

    owned.session = NativeProbe()
    coordinator._current_dedicated = coordinator._current_dedicated_once
    coordinator.sweep()
    assert observed == [False] and owned.stopping and not admission.denied


def test_real_revocation_still_closes_dedicated_main():
    coordinator, admission, _provider, _budget, _first, main, _now = main_setup()
    owned = coordinator._dedicated[main.id]
    admission.current = lambda lease: False
    coordinator.sweep()
    assert owned.stopping
