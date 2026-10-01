"""Offline lifetime and ownership contracts; actual full14 remains mandatory."""

import math
from dataclasses import replace

import pytest


def test_validation_loop_refreshes_only_after_previous_scenario_settles(monkeypatch):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from uuid import UUID

    from tests.integration.test_private_assets import (
        test_upload_validation_rejects_truncation_checksum_and_type as run_validation,
    )
    from tests.support import asset_harness
    from tests.support.asset_harness import AssetHarness, BrowserActor

    now = [datetime.now(UTC)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0]

    monkeypatch.setattr(asset_harness, "datetime", Clock)
    h = object.__new__(AssetHarness)
    h.phase, h.callers = "test", []
    h.deadlines = SimpleNamespace(check=lambda phase: None)
    issued = []

    def new_actor(*, tenant_id=None, user_id=None):
        actor = BrowserActor(
            tenant_id or UUID(int=1),
            user_id or UUID(int=2),
            str(len(issued)),
            "csrf",
            now[0] + timedelta(seconds=600),
        )
        issued.append(actor)
        h.actors.append(actor)
        return actor

    h.actors = []
    new_actor()
    new_actor(user_id=UUID(int=3))
    h.new_actor = new_actor
    pending, completed = [], []
    h.image = lambda **kw: b"synthetic image" * 8

    def begin(*args, **kw):
        assert not pending
        assert h.actors[0].expires_at > now[0], "expired session reached next BEGIN"
        pending.append(h.actors[0])
        return {"asset_id": "synthetic"}

    h.require_begin = begin

    def response(*args, **kw):
        assert h.actors[0] is pending[0], "session rotated inside upload"
        return SimpleNamespace(status_code=204)

    h.put = h.raw_put = h.complete = response
    h.chunks = lambda body: (body,)
    h.row = lambda _: {"failure_code": "DECODE"}
    h.assert_error = h.assert_parser_disconnect = h.assert_never_ready = lambda *args: (
        None
    )

    def recover(*args):
        assert h.actors[0] is pending.pop()
        completed.append(True)
        now[0] += timedelta(seconds=600)

    h.recover_rejected = recover
    run_validation(h)
    assert len(completed) == 7 and not pending
    assert len(issued) == 14  # Both default actors refresh at six later boundaries.


@pytest.mark.parametrize(
    "remaining,required,refresh",
    [
        (700, 190, False),
        (301, 190, False),
        (300, 190, True),
        (-1, 190, True),
        (504, 505, True),
        (506, 505, False),
    ],
)
def test_settled_scenario_creates_protected_session_without_mutating_old_or_negative_actors(
    monkeypatch, remaining, required, refresh
):
    from contextlib import contextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from uuid import UUID

    from sqlalchemy import orm
    from starlette.requests import Request
    from wso_api.auth import (
        SESSION_COOKIE,
        AuthFailure,
        AuthService,
        PostgresSessionStore,
        token_digest,
    )

    from tests.support import asset_harness
    from tests.support.asset_harness import AssetHarness, BrowserActor

    now = datetime.now(UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(asset_harness, "datetime", Clock)
    actors = [
        BrowserActor(
            UUID(int=1),
            UUID(int=index + 2),
            f"token-{index}",
            f"csrf-{index}",
            now + timedelta(seconds=seconds),
        )
        for index, seconds in enumerate((remaining, 700, -5, 700))
    ]
    rows = {
        token_digest(a.token): SimpleNamespace(
            issuer="https://issuer.test",
            subject=str(a.user_id),
            user_id=a.user_id,
            csrf_digest=token_digest(a.csrf),
            expires_at=a.expires_at,
        )
        for a in actors
    }
    revoked = {token_digest(actors[3].token)}
    protected_creates, statements, disposed = [], [], []

    class Database:
        def execute(self, sql, parameters=None):
            statement = str(sql)
            statements.append(statement)
            if statement == "SELECT current_user":
                return SimpleNamespace(scalar_one=lambda: "wso_web_session")
            if statement.startswith("SELECT public.wso_create_web_session("):
                assert parameters["digest"] not in rows
                protected_creates.append(dict(parameters))
                rows[parameters["digest"]] = SimpleNamespace(
                    issuer=parameters["issuer"],
                    subject=parameters["subject"],
                    user_id=parameters["user_id"],
                    csrf_digest=parameters["csrf"],
                    expires_at=parameters["expires_at"],
                )
                return SimpleNamespace(scalar_one=lambda: True)
            assert statement == "SELECT * FROM public.wso_get_web_session(:digest)"
            return SimpleNamespace(
                first=lambda: (
                    None
                    if parameters["digest"] in revoked
                    else rows.get(parameters["digest"])
                )
            )

    class Factory:
        @contextmanager
        def begin(self):
            yield Database()

    factory = Factory()
    monkeypatch.setattr(orm, "sessionmaker", lambda engine: factory)
    monkeypatch.setattr(
        asset_harness,
        "create_engine",
        lambda *args, **kw: SimpleNamespace(dispose=lambda: disposed.append(True)),
    )
    monkeypatch.setenv(
        "WSO_TEST_SESSION_DATABASE_URL",
        "postgresql+psycopg://synthetic.invalid/fixture",
    )
    store = PostgresSessionStore(
        "postgresql+psycopg://synthetic.invalid/fixture", session_factory=factory
    )
    service = object.__new__(AuthService)
    service.sessions = store

    def authenticate(actor):
        return service.authenticate(
            Request(
                {
                    "type": "http",
                    "headers": [
                        (b"cookie", f"{SESSION_COOKIE}={actor.token}".encode())
                    ],
                }
            )
        )

    h = object.__new__(AssetHarness)
    h.actors, h.callers, h.phase = list(actors), [], "test"
    h.deadlines = SimpleNamespace(check=lambda phase: None)
    h.admin = None  # Same-user refresh must never create/restore membership.
    original_expiry = actors[0].expires_at
    if remaining < 0:
        with pytest.raises(AuthFailure):
            authenticate(actors[0])
    # An in-flight caller prevents a boundary, including credential rotation.
    h.callers = [object()]
    from tests.support.asset_faults import FixtureContractError

    with pytest.raises(FixtureContractError):
        h.prepare_scenario(required_seconds=required)
    assert not protected_creates and h.actors[0] is actors[0]
    h.callers.clear()
    h.prepare_scenario(required_seconds=required)
    current = h.actors[0]
    assert authenticate(current).user_id == actors[0].user_id
    assert current.tenant_id == actors[0].tenant_id
    assert actors[0].expires_at == original_expiry
    assert rows[token_digest(actors[0].token)].expires_at == original_expiry
    if refresh:
        assert current.token != actors[0].token and current.csrf != actors[0].csrf
        assert current.expires_at == now + timedelta(seconds=600)
        assert len(protected_creates) == 1 and disposed == [True]
    else:
        assert current is actors[0] and protected_creates == []
    assert h.actors[1:4] == actors[1:4]
    for actor in actors[2:4]:
        with pytest.raises(AuthFailure):
            authenticate(actor)
    assert all(s.startswith("SELECT ") for s in statements)


@pytest.mark.parametrize("resumed", [False, True])
@pytest.mark.parametrize("sizes", [(6, 5), (201, 101)])
def test_transient_recovery_traverses_unequal_streams_and_inherited_tail(
    monkeypatch, capsys, resumed, sizes
):
    import json
    from types import SimpleNamespace

    from tests.support import asset_faults, asset_process
    from tests.support.asset_harness import AssetHarness
    from tests.support.asset_process import ProcessMode

    cursors = {
        "object_cursor": 4 if resumed else None,
        "multipart_cursor": 3 if resumed else None,
    }
    populations = {
        "object_cursor": list(range(sizes[0])),
        "multipart_cursor": list(range(sizes[1])),
    }
    seen = {key: set() for key in cursors}
    limits, records, cleanup = [], [], []
    journals = []

    def reconcile_once(*, limit):
        limits.append(limit)
        for name, items in populations.items():
            start = cursors[name] or 0
            page = items[start : start + limit]
            seen[name].update(page)
            cursors[name] = (
                start + len(page) if start + len(page) < len(items) else None
            )
            journals[-1]["pages"].append(
                [
                    name,
                    {"cursor": start, "limit": limit},
                    {"items": page, "next_cursor": cursors[name]},
                ]
            )
        return 0

    service = SimpleNamespace(
        reconcile_once=reconcile_once,
        objects=SimpleNamespace(local_cleanup_complete=lambda: True),
    )
    monkeypatch.setattr(asset_process.sys, "platform", "linux")
    for key, value in {
        "CI": "true",
        "WSO_CI_DISPOSABLE_POSTGRES": "1",
        "WSO_ASSET_FIXTURE_CONTROL": ".",
        "WSO_ASSET_FIXTURE_OWNER": "synthetic",
    }.items():
        monkeypatch.setenv(key, value)
    from pathlib import Path

    monkeypatch.setattr(
        asset_process,
        "BarrierControl",
        lambda *args: SimpleNamespace(directory=Path("."), owner="synthetic"),
    )

    def create_service(env, observer, control):
        journals.append(observer)
        return service

    monkeypatch.setattr(asset_process, "create_fixture_maintenance", create_service)
    helper = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(
        asset_process,
        "HelperObserver",
        lambda *args: SimpleNamespace(start=lambda: helper),
    )
    monkeypatch.setattr(
        asset_faults, "snapshot_json", lambda path, value: records.append(value)
    )
    h = object.__new__(AssetHarness)
    h.row = lambda _: {"state": "DELETED", "lease_expires_at": None}
    h.phase = "test"
    h.deadlines = SimpleNamespace(
        allowance=lambda cap, phase: cap, check=lambda phase: None
    )
    h.cursor_state = lambda: dict(cursors)

    def run_mode(mode, *, limit=1, **kwargs):
        assert mode is ProcessMode.RECONCILE
        monkeypatch.setattr(
            asset_process.sys, "argv", ["fixture", mode.value, str(limit)]
        )
        asset_process.main()
        return records[-2]

    h.run_mode = run_mode
    h.drain_cleanup = lambda ids, cutoff: cleanup.append((ids, cutoff))
    h._recover_rejected({"asset_id": "synthetic"})
    assert seen == {
        "object_cursor": set(range(sizes[0])),
        "multipart_cursor": set(range(sizes[1])),
    }
    expected_calls = (2 if resumed else 1) if sizes == (6, 5) else (5 if resumed else 3)
    assert limits == [100] * expected_calls
    diagnostic = json.loads(capsys.readouterr().out.split("=", 1)[1])
    assert diagnostic["provider_pages"] == 2 * expected_calls
    assert set(diagnostic) == {
        "schema",
        "reconcile_calls",
        "provider_pages",
        "page_limit",
        "wait_ms",
        "traversal_ms",
        "cleanup_ms",
    }
    assert all(
        type(value) is int and 0 <= value <= 600000 for value in diagnostic.values()
    )
    assert len(cleanup) == 1 and cleanup[0][0] == ["synthetic"]
    assert len(records) == 2 * len(limits)
    # Fixed-epoch callers retain their default one-item page/restart witness.
    cursors.update(object_cursor=None, multipart_cursor=None)
    run_mode(ProcessMode.RECONCILE)
    assert limits[-1] == 1 and cursors == {"object_cursor": 1, "multipart_cursor": 1}


def test_transient_recovery_keeps_sixty_four_call_ceiling_and_original_phase(
    monkeypatch,
):
    from types import SimpleNamespace

    from tests.support.asset_harness import AssetHarness

    h = object.__new__(AssetHarness)
    h.row = lambda _: {"state": "DELETED", "lease_expires_at": None}
    calls, checks = [], []
    h.phase = "original"
    h.deadlines = SimpleNamespace(
        allowance=lambda cap, phase: cap, check=lambda phase: checks.append(phase)
    )
    h.cursor_state = lambda: {"object_cursor": "stuck", "multipart_cursor": None}

    def run_mode(mode, **kw):
        calls.append(kw)
        return {"pages": [[], []]}

    h.run_mode = run_mode
    h.drain_cleanup = lambda *args: pytest.fail(
        "incomplete traversal cannot earn cleanup"
    )
    with pytest.raises(RuntimeError, match="transient reconciliation bound"):
        h._recover_rejected({"asset_id": "synthetic"})
    assert len(calls) == 64
    assert checks and set(checks) == {"original"}


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
