"""R120 media authority gate: per-lease cache, one in-flight check, sticky denial.

A fake clock and a stubbed ``LocalMediaAdmission._query`` stand in for SQL; no
database, device or network is contacted. Leases and views are synthetic.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from wso_contracts.tvt.media import MediaLease
from wso_core.tvt import local_media_admission as module
from wso_core.tvt.local_media_admission import LocalMediaAdmission, LocalMediaLease
from wso_core.tvt.local_service import LocalDeviceFailure

from tests.tvt_parity.test_local_media_contracts import local_values

URL = "postgresql+psycopg://worker:unused@127.0.0.1:1/unused"
# R120 freshness window (AUTHORITY_FRESHNESS_SECONDS, pinned below).
F = 0.1


class Key:
    def encryption_key(self):
        return bytes(range(32))


class Clock:
    """Fake gate clock: only explicit test steps (or simulated SQL) move it."""

    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class Engine:
    """Fake worker engine for the SQL that still runs per call (close)."""

    def __init__(self):
        self.statements = []
        self.role = "wso_connection_worker"
        self.observe = None
        self.begin_error = None
        self.on_begin = None

    @contextmanager
    def begin(self):
        if self.on_begin is not None:
            self.on_begin()
        if self.begin_error is not None:
            raise self.begin_error
        yield self

    def execute(self, statement, parameters=None):
        query = str(statement)
        self.statements.append(query)
        if query == "SELECT current_user":
            return Result(self.role)
        if "wso_tvt_local_media_observe" in query:
            return Result(self.observe())
        return Result(None)

    def dispose(self):
        pass


class SQL:
    """Stub for ``LocalMediaAdmission._query``; answers ``observe`` per lease.

    The authority decision is taken when a check enters (its statement
    snapshot): a revoke recorded before entry is seen, a later one is not.
    """

    def __init__(self, clock=None):
        self.clock = clock
        self.calls = []
        self.views = {}
        self.revoked = set()
        self.holds = {}
        self.entered = threading.Event()
        self.latency = 0.0
        self.sleep = 0.0
        self.during = None

    def grant(self, view=None):
        given = LocalMediaLease(uuid4().hex * 2, uuid4(), uuid4(), None, module._SEAL)
        self.views[given.token] = view or MediaLease(**local_values())
        return given

    def revoke(self, given):
        self.revoked.add(given.token)

    def restore(self, given):
        self.revoked.discard(given.token)

    def count(self, function="observe"):
        return sum(1 for name, _, _ in self.calls if name == function)

    def __call__(self, lease, function, **kwargs):
        token = lease.token
        self.calls.append((function, token, threading.current_thread().name))
        live = function == "observe" and token not in self.revoked
        hold = self.holds.pop(token, None)
        self.entered.set()
        if self.during is not None:
            self.during()
        if hold is not None:
            assert hold.wait(10)
        if self.sleep:
            time.sleep(self.sleep)
        if self.latency:
            self.clock.now += self.latency
        if not live:
            return None
        view = self.views[token]
        return (view() if callable(view) else view).model_dump(mode="json")


def gated_admission(clock=time.perf_counter):
    """A real gate whose observe SQL is stubbed and whose close SQL is inert."""
    admission = LocalMediaAdmission(URL, Key(), clock=clock)
    admission._engine.dispose()
    admission._engine = Engine()
    sql = SQL(clock)
    admission._query = sql
    return admission, sql


def startable(admission, sql):
    """Stub only the startup ports (redeem/open/activate); the gate stays real."""

    def redeem(ticket, *, budget):
        return sql.grant()

    def opened(lease, callback, *, budget):
        return callback(None, None, lambda: True)

    def activate(lease, proof, *, budget):
        return sql.views[lease.token]

    admission.redeem, admission.open, admission.activate = redeem, opened, activate
    return admission


def gated_executor(provider, *, clock=time.perf_counter):
    from wso_core.tvt.local_media_service import LocalMediaExecutor

    admission, sql = gated_admission(clock)
    startable(admission, sql)
    executor = LocalMediaExecutor(admission, provider, monitor_interval=0)
    return executor, admission, sql


def run(target, name):
    outcome = []
    thread = threading.Thread(target=lambda: outcome.append(target()), name=name)
    thread.start()
    return thread, outcome


def simulate(packets):
    """3 s at 10 fps of the media hot path's gate calls on one lease.

    Per frame: 10 ingress-side checks and the decoder's two checks at frame
    completion, then publication (executor.lease: current + view); per packet
    two parent pump checks spread through the frame; a 50 ms authority
    heartbeat (current + view); a 1 Hz executor sweep (two checks) and
    worker watch (current + view). Frame starts advance by exactly the frame
    period, the same float step the gate adds to a check's start.
    """
    clock = Clock(0.0)
    admission, sql = gated_admission(clock)
    given = sql.grant()
    events = []
    start = 0.0
    for index in range(30):
        events += [(start, 0, "current")] * 12
        events += [(start, 1, "current"), (start, 1, "view")]
        for half in (0.0, 0.05):
            events += [(start + half, 2, "current"), (start + half, 2, "view")]
        for packet in range(packets):
            arrival = start + 0.09 * (packet + 1) / packets
            events += [(arrival, 3, "current")] * 2
        if index % 10 == 0:
            events += [(start + 0.025, 4, "current")] * 3 + [(start + 0.025, 4, "view")]
        start += 0.1
    gate_calls = 0
    for moment, _, kind in sorted(events, key=lambda event: event[:2]):
        clock.now = moment
        if kind == "current":
            assert admission.current(given) is True
        else:
            assert admission.view(given).id == sql.views[given.token].id
        gate_calls += 1
    return sql, gate_calls


@pytest.mark.parametrize("packets", [1, 8, 32])
def test_sql_budget_per_simulated_second(packets):
    sql, gate_calls = simulate(packets)
    baseline, _ = simulate(1)
    observe = sql.count()
    assert gate_calls >= 30 * (2 * packets + 18)
    # At most one check per F of simulated time, whatever the packet rate.
    assert observe <= 31
    assert abs(observe - baseline.count()) <= 1
    assert sql.count("current") == sql.count("worker_view") == 0
    assert {name for name, _, _ in sql.calls} == {"observe"}


def test_cache_requires_start_within_freshness():
    assert module.AUTHORITY_FRESHNESS_SECONDS == F
    clock = Clock()
    admission, sql = gated_admission(clock)
    given = sql.grant()
    sql.latency = 0.03  # The check itself takes 30 ms of gate time.
    start = clock.now
    assert admission.current(given) is True and sql.count() == 1
    # Freshness is anchored at the check's start, not at its 30 ms later end.
    clock.now = start + 0.0999
    assert admission.current(given) is True and sql.count() == 1
    clock.now = start + F
    assert admission.current(given) is True and sql.count() == 2


def test_first_call_runs_sql_and_leases_isolated():
    clock = Clock()
    admission, sql = gated_admission(clock)
    first, second = sql.grant(), sql.grant()
    assert admission.current(first) is True and sql.count() == 1
    # A second lease's first call never reuses another lease's answer.
    assert admission.view(second).id == sql.views[second.token].id
    assert sql.count() == 2
    assert admission.view(first).id == sql.views[first.token].id
    assert sql.count() == 2
    sql.revoke(first)
    clock.now += F
    assert admission.current(first) is False
    assert admission.current(second) is True and sql.count() == 4
    clock.now += F
    assert admission.current(second) is True and sql.count() == 5
    assert admission.current(first) is False and sql.count() == 5


def test_denial_sticky_without_sql():
    clock = Clock()
    admission, sql = gated_admission(clock)
    given = sql.grant()
    assert admission.current(given) is True
    sql.revoke(given)
    clock.now += F
    assert admission.current(given) is False and sql.count() == 2
    # Restoring SQL authority never revives the lease, and costs no SQL.
    sql.restore(given)
    for _ in range(5):
        clock.now += F
        assert admission.current(given) is False
        with pytest.raises(LocalDeviceFailure) as denied:
            admission.view(given)
        assert (denied.value.code, denied.value.status) == ("LOCAL_DEVICE_DENIED", 404)
    assert sql.count() == 2


class Cancelled(Exception):
    sqlstate = "57014"


@pytest.mark.parametrize(
    "failure", ["pool_timeout", "statement_timeout", "role_mismatch", "invalid_view"]
)
def test_sql_error_denies_sticky(failure):
    # The real _query runs here; only the engine under it is fake.
    clock = Clock()
    admission = LocalMediaAdmission(URL, Key(), clock=clock)
    admission._engine.dispose()
    engine = admission._engine = Engine()
    view = MediaLease(**local_values())
    engine.observe = lambda: view.model_dump(mode="json")
    if failure == "pool_timeout":
        engine.begin_error = PoolTimeout("QueuePool limit reached", None, None)
    elif failure == "statement_timeout":

        def cancelled():
            raise DBAPIError("observe", {}, Cancelled())

        engine.observe = cancelled
    elif failure == "role_mismatch":
        engine.role = "wso_app"
    else:
        engine.observe = lambda: {**view.model_dump(mode="json"), "state": "BOGUS"}
    given = LocalMediaLease(uuid4().hex * 2, uuid4(), uuid4(), None, module._SEAL)
    # The caller that ran the failing check keeps the fixed 503 mapping.
    with pytest.raises(LocalDeviceFailure) as caught:
        admission.current(given)
    assert (caught.value.code, caught.value.status) == ("LOCAL_DEVICE_UNAVAILABLE", 503)
    # SQL recovers and time passes; the lease stays denied and never re-asks.
    engine.begin_error, engine.role = None, "wso_connection_worker"
    engine.observe = lambda: view.model_dump(mode="json")
    issued = len(engine.statements)
    clock.now += 10 * F
    assert admission.current(given) is False
    with pytest.raises(LocalDeviceFailure) as denied:
        admission.view(given)
    assert (denied.value.code, denied.value.status) == ("LOCAL_DEVICE_DENIED", 404)
    assert len(engine.statements) == issued
    # The failure belongs to that lease only.
    other = LocalMediaLease(uuid4().hex * 2, uuid4(), uuid4(), None, module._SEAL)
    assert admission.current(other) is True
    assert any("wso_tvt_local_media_observe" in s for s in engine.statements[issued:])


def test_concurrent_callers_share_one_in_flight_check():
    clock = Clock()
    admission, sql = gated_admission(clock)
    given = sql.grant()
    release = sql.holds[given.token] = threading.Event()
    names = ["pump", "pump", "ingress", "ingress", "decoder", "heartbeat", "sweep"]
    names.append("watch")
    barrier = threading.Barrier(len(names))
    results = {}

    def call(index):
        barrier.wait(5)
        results[index] = admission.view(given)

    threads = [
        threading.Thread(target=call, args=(index,), name=f"{name}-{index}")
        for index, name in enumerate(names)
    ]
    for thread in threads:
        thread.start()
    try:
        assert sql.entered.wait(5)
        time.sleep(0.2)
        # Nobody can answer without the one check, so all eight are inside it.
        assert all(thread.is_alive() for thread in threads)
        assert sql.count() == 1
    finally:
        release.set()
        for thread in threads:
            thread.join(5)
    assert not any(thread.is_alive() for thread in threads)
    assert sql.count() == 1 and len(results) == 8
    first = results[0]
    assert all(result == first for result in results.values())
    assert len({id(result) for result in results.values()}) == 8
    assert first.id == sql.views[given.token].id


def test_waiter_rejects_check_started_before_call_minus_F():
    clock = Clock()
    admission, sql = gated_admission(clock)
    given = sql.grant()
    release = sql.holds[given.token] = threading.Event()
    early, early_outcome = run(lambda: admission.current(given), "early")
    try:
        assert sql.entered.wait(5)  # Check A began at s and is still running.
        clock.now += 1.5 * F  # A later call begins after s + F.
        late, late_outcome = run(lambda: admission.current(given), "late")
        time.sleep(0.1)
        # It waits for A rather than starting a second concurrent check...
        assert late.is_alive() and sql.count() == 1
    finally:
        release.set()
        early.join(5)
    late.join(5)
    # ...then rejects A's answer as too old for it and runs its own check.
    assert early_outcome == [True] and late_outcome == [True]
    assert [name for _, _, name in sql.calls] == ["early", "late"]


def test_slow_success_honored():
    clock = Clock()
    admission, sql = gated_admission(clock)
    given = sql.grant()
    release = sql.holds[given.token] = threading.Event()
    start = clock.now
    runner, runner_outcome = run(lambda: admission.current(given), "ingress")
    try:
        assert sql.entered.wait(5)
        clock.now = start + F / 2  # Begins within F of the check's start.
        waiter, waiter_outcome = run(lambda: admission.current(given), "decoder")
        time.sleep(0.2)
        clock.now = start + 20 * F  # The check finishes far beyond F.
    finally:
        release.set()
        runner.join(5)
    waiter.join(5)
    # A slow but successful check is no denial, for its runner and its waiter.
    assert runner_outcome == [True] and waiter_outcome == [True]
    assert sql.count() == 1
    # Its answer is too old to reuse: the next call checks again, and passes.
    assert admission.current(given) is True and sql.count() == 2


def test_waiter_timeout_and_reentrancy_deny(monkeypatch):
    assert module.AUTHORITY_WAIT_SECONDS == 5.0
    monkeypatch.setattr(module, "AUTHORITY_WAIT_SECONDS", 0.2)
    clock = Clock()
    admission, sql = gated_admission(clock)
    given = sql.grant()
    release = sql.holds[given.token] = threading.Event()
    runner, outcome = run(lambda: admission.current(given), "stuck")
    try:
        assert sql.entered.wait(5)
        began = time.perf_counter()
        assert admission.current(given) is False
        assert 0.15 <= time.perf_counter() - began < 2
    finally:
        release.set()
        runner.join(5)
    # The timeout was a sticky denial: the stuck check's late True is discarded.
    assert outcome == [False]
    clock.now += 10 * F
    assert admission.current(given) is False and sql.count() == 1
    # Re-entry from the checking thread is denied at once, never self-waited.
    monkeypatch.setattr(module, "AUTHORITY_WAIT_SECONDS", 5.0)
    other = sql.grant()
    inner = []
    sql.during = lambda: inner.append(admission.current(other))
    began = time.perf_counter()
    assert admission.current(other) is True
    assert time.perf_counter() - began < 1
    assert inner == [False] and sql.count() == 2


def test_close_during_flight_discards_true():
    assert module.AUTHORITY_TOMBSTONES == 64
    clock = Clock()
    admission, sql = gated_admission(clock)
    given = sql.grant()
    release = sql.holds[given.token] = threading.Event()
    runner, outcome = run(lambda: admission.current(given), "ingress")
    order = []
    try:
        assert sql.entered.wait(5)
        waiter, waiter_outcome = run(lambda: admission.current(given), "decoder")
        time.sleep(0.05)
        # close() denies and tombstones before its own SQL begins.
        admission._engine.on_begin = lambda: order.append(admission.current(given))
        admission.close(given, cleanup_confirmed=True)
        sql.revoke(given)  # What the committed close makes observe report.
        waiter.join(5)
        assert not waiter.is_alive() and waiter_outcome == [False]
        assert runner.is_alive()
    finally:
        release.set()
        runner.join(5)
    assert outcome == [False] and order == [False]
    assert any("wso_tvt_local_media_close" in s for s in admission._engine.statements)
    clock.now += 10 * F
    assert admission.current(given) is False and sql.count() == 1
    # Tombstones keep the 64 most recent tokens; an evicted one asks SQL again.
    admission._engine.on_begin = None
    closed = [sql.grant() for _ in range(64)]
    for lease in closed:
        sql.revoke(lease)
        admission.close(lease, cleanup_confirmed=True)
    assert admission.current(closed[0]) is False and sql.count() == 1
    assert admission.current(given) is False and sql.count() == 2


def test_cache_clipped_to_lease_expiry():
    clock = Clock()
    admission, sql = gated_admission(clock)
    values = local_values()

    def expiring(seconds):
        def view():
            now = datetime.now(UTC)
            return MediaLease(
                **{
                    **values,
                    "heartbeat_at": now - timedelta(seconds=1),
                    "expires_at": now + timedelta(seconds=seconds),
                }
            )

        return view

    given = sql.grant()
    sql.views[given.token] = expiring(0.05)
    start = clock.now
    assert admission.current(given) is True and sql.count() == 1
    clock.now = start + 0.03
    assert admission.current(given) is True and sql.count() == 1
    # The lease expires 50 ms after the check: a cached True never outlives it.
    clock.now = start + 0.07
    assert admission.current(given) is True and sql.count() == 2
    # A successful answer can cross expiry during SQL response latency, or
    # appear expired through clock skew. Approved slow-success semantics return
    # it to eligible callers once; ordinary reuse/transport permits stay clipped.
    sql.views[given.token] = expiring(-0.5)
    clock.now += F
    assert admission.current(given) is True and sql.count() == 3
    assert admission.current(given) is True and sql.count() == 4


def test_one_slow_lease_never_denies_another():
    clock = Clock()
    admission, sql = gated_admission(clock)
    slow, fast = sql.grant(), sql.grant()
    release = sql.holds[slow.token] = threading.Event()
    runner, runner_outcome = run(lambda: admission.current(slow), "slow-ingress")
    try:
        assert sql.entered.wait(5)
        waiter, waiter_outcome = run(lambda: admission.current(slow), "slow-decoder")
        began = time.perf_counter()
        for _ in range(20):
            clock.now += F
            assert admission.current(fast) is True
        assert time.perf_counter() - began < 1
        assert runner.is_alive() and waiter.is_alive()
    finally:
        release.set()
        runner.join(5)
    waiter.join(5)
    # The slow lease's callers are answered when its own check ends, not denied.
    assert runner_outcome == [True] and waiter_outcome == [True]
    assert sum(1 for _, token, _ in sql.calls if token == fast.token) == 20


def test_parent_pump_with_gate_bounds_sql_and_latches_denial():
    from wso_tvt_bridge.local_inventory_ipc import AuthorityError
    from wso_tvt_bridge.local_live_ipc import LiveParentAuthority, LiveRemoteAuthority

    clock = Clock()
    admission, sql = gated_admission(clock)
    given = sql.grant()
    parent = LiveParentAuthority(time.monotonic() + 20, threading.Event())
    parent.bind("a" * 32)
    remote = LiveRemoteAuthority(parent.worker_connection, "a" * 32, parent.deadline)
    answered, failed, seen = [], [], []

    def child():
        try:
            while True:
                remote.require("frame")
                answered.append(True)
        except AuthorityError:
            failed.append(True)

    def current():
        clock.now += 0.002  # Each parent check is 2 ms of pipeline time.
        began = clock.now
        allowed = admission.current(given)
        seen.append((began, allowed))
        return allowed

    worker = threading.Thread(target=child, name="native-child")
    start = clock.now
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while len(answered) < 400:
            assert parent.pump(current) is True
            assert time.monotonic() < deadline
            time.sleep(0)
        steady = clock.now - start
        assert all(allowed for _, allowed in seen)
        assert sql.count() <= steady / F + 1
        revoked = clock.now
        sql.revoke(given)
        while parent.pump(current):
            assert time.monotonic() < deadline
            time.sleep(0)
        assert parent.failure == "denied"
        assert all(not allowed for began, allowed in seen if began >= revoked + F)
        settled, checks = sql.count(), len(seen)
        # Latched: no further check reaches the gate, and the gate is sticky.
        sql.restore(given)
        clock.now += 10 * F
        assert parent.pump(current) is False and len(seen) == checks
        assert admission.current(given) is False and sql.count() == settled
    finally:
        # As the watchdog's stop does to a native child: its pipe peer closes.
        parent.connection.close()
        worker.join(5)
        parent.close()
        remote.close()
    assert not worker.is_alive() and failed == [True]


def test_public_view_mutation_cannot_change_cached_authority_or_scope():
    admission, sql = gated_admission(Clock())
    given = sql.grant()
    first = admission.view(given)
    expected = first.model_dump()
    first.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    first.owner.tenant_id = uuid4()
    first.device.store_id = uuid4()
    again = admission.view(given)
    assert again.model_dump() == expected
    assert (
        again is not first
        and again.owner is not first.owner
        and again.device is not first.device
    )
    assert admission.current(given) is True and sql.count() == 1


@pytest.mark.parametrize("selector", ["current", "worker_view"])
def test_unused_query_selectors_are_rejected_before_sql(selector):
    admission, sql = gated_admission(Clock())
    with pytest.raises(LocalDeviceFailure):
        LocalMediaAdmission._query(admission, sql.grant(), selector)
    assert not admission._engine.statements
