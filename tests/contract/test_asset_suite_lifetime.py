"""Offline lifetime and ownership contracts; actual full14 remains mandatory."""

import math
from dataclasses import replace

import pytest


def test_setup_allowance_clips_to_original_phase_and_expires_exactly():
    from tests.support.asset_harness import (
        FixtureDeadlineError,
        FixtureDeadlines,
        FixturePhase,
    )

    now = [719.0]
    deadlines = FixtureDeadlines(0.0, clock=lambda: now[0])
    assert deadlines.allowance(5.0, FixturePhase.SETUP) == 1.0
    now[0] = 720.0
    with pytest.raises(FixtureDeadlineError, match="^fixture deadline expired$"):
        deadlines.check(FixturePhase.SETUP)
    with pytest.raises(FixtureDeadlineError):
        deadlines.allowance(5.0, FixturePhase.SETUP)


def test_new_phase_allowances_do_not_renew_setup_or_immutable_work_cutoff():
    from tests.support.asset_harness import (
        FixtureDeadlineError,
        FixtureDeadlines,
        FixturePhase,
    )

    now = [600.0]
    deadlines = FixtureDeadlines(0.0, clock=lambda: now[0])
    deadlines.finish_age_seed()
    now[0] = 1200.0
    with pytest.raises(FixtureDeadlineError):
        deadlines.check(FixturePhase.SETUP)
    assert deadlines.allowance(5.0, FixturePhase.PRE_AGE) == 5.0
    now[0] = 3299.0
    assert deadlines.allowance(20.0, FixturePhase.PRE_AGE) == 1.0
    now[0] = 3300.0
    with pytest.raises(FixtureDeadlineError):
        deadlines.check(FixturePhase.PRE_AGE)
    now[0] = 4319.0
    with pytest.raises(FixtureDeadlineError):
        deadlines.begin_post_age()
    now[0] = 4320.0
    deadlines.begin_post_age()
    assert deadlines.allowance(1000.0, FixturePhase.POST_AGE) == 720.0
    now[0] = 5039.0
    assert deadlines.allowance(5.0, FixturePhase.POST_AGE) == 1.0
    now[0] = 5040.0
    with pytest.raises(FixtureDeadlineError):
        deadlines.check(FixturePhase.POST_AGE)


def test_late_post_age_is_clipped_by_work_and_teardown_by_outer_lifetime():
    from tests.support.asset_harness import (
        FixtureDeadlineError,
        FixtureDeadlines,
        FixturePhase,
    )

    now = [600.0]
    deadlines = FixtureDeadlines(0.0, clock=lambda: now[0])
    deadlines.finish_age_seed()
    now[0] = 5000.0
    deadlines.begin_post_age()
    assert deadlines.allowance(720.0, FixturePhase.POST_AGE) == 160.0
    now[0] = 5159.0
    assert deadlines.allowance(5.0, FixturePhase.POST_AGE) == 1.0
    now[0] = 5160.0
    with pytest.raises(FixtureDeadlineError):
        deadlines.check(FixturePhase.POST_AGE)
    deadlines.begin_teardown()
    assert deadlines.allowance(1000.0, FixturePhase.TEARDOWN) == 480.0
    now[0] = 5640.0
    with pytest.raises(FixtureDeadlineError):
        deadlines.check(FixturePhase.TEARDOWN)


def test_aging_has_no_network_allowance_and_phase_anchors_are_single_use():
    from tests.support.asset_faults import FixtureContractError
    from tests.support.asset_harness import (
        FixtureDeadlineError,
        FixtureDeadlines,
        FixturePhase,
    )

    now = [600.0]
    deadlines = FixtureDeadlines(0.0, clock=lambda: now[0])
    deadlines.finish_age_seed()
    with pytest.raises(FixtureContractError):
        deadlines.finish_age_seed()
    with pytest.raises((FixtureContractError, FixtureDeadlineError)):
        deadlines.allowance(1.0, FixturePhase.AGING)
    now[0] = 4320.0
    deadlines.begin_post_age()
    with pytest.raises(FixtureContractError):
        deadlines.begin_post_age()
    deadlines.begin_teardown()
    with pytest.raises(FixtureContractError):
        deadlines.begin_teardown()


@pytest.mark.parametrize("start", [True, 0, "0", math.inf, math.nan])
def test_deadline_start_requires_finite_native_float(start):
    from tests.support.asset_faults import FixtureContractError
    from tests.support.asset_harness import FixtureDeadlines

    with pytest.raises(FixtureContractError):
        FixtureDeadlines(start, clock=lambda: 1.0)


@pytest.mark.parametrize("cap", [True, 1, "1", 0.0, -1.0, math.inf, math.nan])
def test_allowance_requires_positive_finite_native_float(cap):
    from tests.support.asset_faults import FixtureContractError
    from tests.support.asset_harness import FixtureDeadlines, FixturePhase

    with pytest.raises(FixtureContractError):
        FixtureDeadlines(0.0, clock=lambda: 1.0).allowance(cap, FixturePhase.SETUP)


def epochs():
    from tests.support.asset_faults import EpochTracker, TraversalStream

    return EpochTracker(
        {
            TraversalStream.OBJECTS: frozenset({"a", "b"}),
            TraversalStream.MULTIPART: frozenset({("m", "u")}),
        }
    )


def record(tracker, stream, before, after, identities, *, committed=True):
    from tests.support.asset_faults import TraversalStream

    tracker.record_page(
        TraversalStream(stream),
        cursor_before=before,
        cursor_after=after,
        identities=identities,
        committed=committed,
    )


def test_independent_streams_require_full_epochs_and_simultaneous_committed_null():
    from tests.support.asset_faults import FixtureContractError, ObjectPageCursor

    tracker = epochs()
    first = ObjectPageCursor("object-page-one")
    tracker.begin_iteration()
    record(tracker, "OBJECTS", None, first, ("a",))
    record(tracker, "MULTIPART", None, None, (("m", "u"),))
    summary = tracker.summary()
    assert (
        summary.iterations,
        summary.objects_full,
        summary.multipart_full,
        summary.simultaneous_null,
    ) == (1, False, True, False)
    with pytest.raises(FixtureContractError):
        tracker.assert_complete()
    tracker.begin_iteration()
    record(tracker, "OBJECTS", first, None, ("b",))
    record(tracker, "MULTIPART", None, None, (("m", "u"),))
    summary = tracker.summary()
    assert (
        summary.iterations,
        summary.objects_full,
        summary.multipart_full,
        summary.simultaneous_null,
    ) == (2, True, True, True)
    assert tracker.assert_complete() is None


def test_inherited_tail_does_not_earn_full_inventory_and_null_resets_only_its_stream():
    from tests.support.asset_faults import ObjectPageCursor

    tracker = epochs()
    tracker.begin_iteration()
    record(tracker, "OBJECTS", ObjectPageCursor("retained-tail"), None, ("b",))
    record(tracker, "MULTIPART", None, None, (("m", "u"),))
    assert tracker.summary().objects_full is False
    assert tracker.summary().multipart_full is True
    tracker.begin_iteration()
    record(tracker, "OBJECTS", None, None, ("a", "b"))
    record(tracker, "MULTIPART", None, None, (("m", "u"),))
    assert tracker.assert_complete() is None


def test_empty_malformed_page_can_advance_cursor_without_substituting_inventory():
    from tests.support.asset_faults import ObjectPageCursor

    tracker = epochs()
    cursor = ObjectPageCursor("after-malformed-object")
    tracker.begin_iteration()
    record(tracker, "OBJECTS", None, cursor, ())
    record(tracker, "MULTIPART", None, None, (("m", "u"),))
    assert tracker.summary().objects_full is False
    tracker.begin_iteration()
    record(tracker, "OBJECTS", cursor, None, ("a", "b"))
    record(tracker, "MULTIPART", None, None, (("m", "u"),))
    assert tracker.assert_complete() is None


@pytest.mark.parametrize("identities", [("a", "a"), ("foreign",)])
def test_duplicate_or_unexpected_inventory_refuses_false_witness(identities):
    from tests.support.asset_faults import FixtureContractError

    tracker = epochs()
    tracker.begin_iteration()
    with pytest.raises(FixtureContractError):
        record(tracker, "OBJECTS", None, None, identities)
    assert tracker.summary().objects_full is False


@pytest.mark.parametrize(
    "failure", ["duplicate", "cursor-jump", "noncommit", "wrong-cursor-kind"]
)
def test_epoch_continuity_and_actual_commit_are_required(failure):
    from tests.support.asset_faults import (
        FixtureContractError,
        MultipartPageCursor,
        ObjectPageCursor,
    )

    tracker = epochs()
    first = ObjectPageCursor("first")
    tracker.begin_iteration()
    record(tracker, "OBJECTS", None, first, ("a",))
    record(tracker, "MULTIPART", None, None, (("m", "u"),))
    tracker.begin_iteration()
    before = ObjectPageCursor("unobserved") if failure == "cursor-jump" else first
    after = MultipartPageCursor("key", "u") if failure == "wrong-cursor-kind" else None
    items = ("a",) if failure == "duplicate" else ("b",)
    with pytest.raises(FixtureContractError):
        record(
            tracker, "OBJECTS", before, after, items, committed=failure != "noncommit"
        )
    assert tracker.summary().objects_full is False


def test_iteration_budget_refuses_sixty_fifth_call():
    from tests.support.asset_faults import FixtureContractError

    tracker = epochs()
    for _ in range(64):
        tracker.begin_iteration()
        record(tracker, "OBJECTS", None, None, ("a", "b"))
        record(tracker, "MULTIPART", None, None, (("m", "u"),))
    assert tracker.summary().iterations == 64
    with pytest.raises(FixtureContractError):
        tracker.begin_iteration()
    assert tracker.summary().iterations == 64


def identity():
    from tests.support.asset_faults import ProcessIdentity

    return ProcessIdentity(
        owner="synthetic-owner",
        pid=101,
        uid=1000,
        ppid=100,
        pgid=101,
        start_ticks=500,
        command=("python", "-m", "tests.support.asset_process"),
    )


def test_process_identity_accepts_only_exact_retained_owner():
    from tests.support.asset_faults import validate_process_identity

    assert validate_process_identity(identity(), identity()) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", "other-owner"),
        ("pid", 102),
        ("uid", 1001),
        ("ppid", 99),
        ("pgid", 102),
        ("start_ticks", 501),
        ("command", ("python", "-m", "foreign_process")),
    ],
)
def test_process_identity_refuses_each_changed_ownership_field(field, value):
    from tests.support.asset_faults import (
        FixtureContractError,
        validate_process_identity,
    )

    expected = identity()
    observed = replace(expected, **{field: value})
    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        validate_process_identity(expected, observed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("pid", True),
        ("pid", 0),
        ("uid", -1),
        ("ppid", -1),
        ("pgid", 0),
        ("start_ticks", "500"),
        ("command", ["python"]),
        ("owner", "owner\n"),
    ],
)
def test_process_identity_rejects_coercion_and_invalid_native_fields(field, value):
    from tests.support.asset_faults import FixtureContractError

    with pytest.raises(FixtureContractError):
        replace(identity(), **{field: value})


def idle():
    from tests.support.asset_faults import IdleSnapshot

    return IdleSnapshot(
        healthy=True,
        connections=0,
        sockets=1,
        workers=1,
        only_listener=True,
        only_pinned_acceptor=True,
        acceptor_alive=True,
        commands_settled=True,
    )


def test_idle_accepts_owned_handle_thread_and_command_facts():
    from tests.support.asset_faults import validate_idle_snapshot

    assert validate_idle_snapshot(idle()) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("healthy", False),
        ("connections", 1),
        ("sockets", 2),
        ("workers", 2),
        ("only_listener", False),
        ("only_pinned_acceptor", False),
        ("acceptor_alive", False),
        ("commands_settled", False),
        ("connections", True),
        ("healthy", 1),
    ],
)
def test_idle_counts_never_replace_missing_ownership_or_settlement(field, value):
    from tests.support.asset_faults import FixtureContractError, validate_idle_snapshot

    with pytest.raises(FixtureContractError, match="^invalid fixture contract$"):
        validate_idle_snapshot(replace(idle(), **{field: value}))


def test_positive_allowance_uses_one_validated_clock_observation():
    from tests.support.asset_harness import FixtureDeadlines, FixturePhase

    observations = []
    instant = [0.0]
    increment = [0.0]

    def advancing_clock():
        observed = instant[0]
        observations.append(observed)
        instant[0] += increment[0]
        return observed

    deadlines = FixtureDeadlines(0.0, clock=advancing_clock)
    observations.clear()
    instant[0] = 719.0
    increment[0] = 1.0
    assert deadlines.allowance(5.0, FixturePhase.SETUP) == 1.0
    assert observations == [719.0]
