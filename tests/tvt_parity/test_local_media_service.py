"""Executor lifetime failures must retire the original native session."""

from contextlib import contextmanager
from dataclasses import replace
from threading import Event
from uuid import uuid4

import pytest
from wso_contracts.tvt.media import MediaLease
from wso_core.tvt.local_service import LocalDeviceFailure

from tests.tvt_parity.test_local_media_admission_pool import URL, Key
from tests.tvt_parity.test_local_media_contracts import local_values


class Session:
    def __init__(self):
        from wso_core.tvt.local_media_service import LocalLiveProof

        self.proof = LocalLiveProof(True, True, True, True, True)
        self.closed = 0
        self.frames = (b"frame",)
        self.after_read = lambda: None

    def close(self):
        self.closed += 1
        return True

    def read_frames(self, **kwargs):
        self.after_read()
        return self.frames

    def current(self, *, deadline_monotonic, current):
        return current()


class Provider:
    def __init__(self, session):
        self.session = session

    def open_session(self, credentials, selection, **kwargs):
        return self.session


class Admission:
    def __init__(self):
        self.view = MediaLease(**local_values())
        self.allowed = True
        self.closed = 0
        self.cleanup_confirmations = []

    def redeem(self, ticket, *, budget):
        return self.view.id

    def open(self, lease, callback, *, budget):
        return callback(None, None, lambda: self.allowed)

    def activate(self, lease, proof, *, budget):
        return self.view

    def current(self, lease):
        return self.allowed

    def view(self, lease):
        return self.view

    def close(self, lease, *, cleanup_confirmed):
        self.closed += 1
        self.cleanup_confirmations.append(cleanup_confirmed)

    def redeem_control(self, ticket, purpose, *, budget):
        return self.view.id

    def retry_cleanup(self):
        return True


def executor(admission, provider, **kwargs):
    from wso_core.tvt.local_media_service import LocalMediaExecutor

    return LocalMediaExecutor(admission, provider, monitor_interval=0, **kwargs)


def test_unproved_permission_cannot_return_live_lease():
    admission, session = Admission(), Session()
    session.proof = replace(session.proof, live_permission=False)
    worker = executor(admission, Provider(session))
    with pytest.raises(LocalDeviceFailure):
        worker.start("a" * 64, deadline_ms=20000, correlation_id="test")
    assert session.closed == 1
    assert admission.closed == 1
    assert not worker.current(admission.view.id)


def test_revocation_during_frame_read_discards_result_and_closes_original():
    admission, session = Admission(), Session()
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="test")
    session.after_read = lambda: setattr(admission, "allowed", False)
    with pytest.raises(LocalDeviceFailure):
        worker.read_frames(
            admission.view.id, max_frames=4, max_bytes=1024, deadline_ms=1000
        )
    assert session.closed == 1
    assert admission.closed == 1


def test_expiry_after_committed_start_cannot_return_success():
    admission, session = Admission(), Session()
    now = [0.0]

    def activate(lease, proof, *, budget):
        now[0] = 21.0
        return admission.view

    admission.activate = activate
    worker = executor(admission, Provider(session), clock=lambda: now[0])
    with pytest.raises(LocalDeviceFailure) as caught:
        worker.start("a" * 64, deadline_ms=20000, correlation_id="test")
    assert caught.value.code == "LOCAL_DEVICE_DEADLINE_EXCEEDED"
    assert session.closed == 1
    assert admission.closed == 1


def test_cancelled_start_and_stop_are_bounded_and_idempotent():
    admission, session = Admission(), Session()
    worker = executor(admission, Provider(session))
    cancel = Event()
    cancel.set()
    with pytest.raises(LocalDeviceFailure):
        worker.start("a" * 64, deadline_ms=20000, correlation_id="test", cancel=cancel)
    assert session.closed == 0
    result = worker.start("a" * 64, deadline_ms=20000, correlation_id="test")
    assert result.lease.state == "NEGOTIATING"
    worker.stop("b" * 64, deadline_ms=1000, correlation_id="stop")
    worker.shutdown()
    assert session.closed == 1
    assert not worker.current(uuid4())


def test_uncertain_native_cleanup_keeps_retry_owner_and_never_reports_closed():
    admission, session = Admission(), Session()
    confirmed = [False]

    def close():
        session.closed += 1
        return confirmed[0]

    session.close = close
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="test")
    assert not worker.close(admission.view.id)
    confirmed[0] = True
    assert worker.close(admission.view.id)
    assert session.closed == 2


def test_stop_after_watchdog_close_returns_confirmed_closed_tombstone():
    admission, session = Admission(), Session()
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="test")
    admission.allowed = False
    worker.sweep()
    assert session.closed == 1
    result = worker.stop("b" * 64, deadline_ms=1000, correlation_id="stop")
    assert result.lease.state == "CLOSED"


def test_provider_cannot_deliver_more_bytes_than_admitted_read_bound():
    from wso_core.tvt.local_live import PrivateLiveFrame

    admission, session = Admission(), Session()
    session.frames = (PrivateLiveFrame(b"x" * 1025),)
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    with pytest.raises(LocalDeviceFailure):
        worker.read_frames(
            admission.view.id, max_frames=1, max_bytes=1024, deadline_ms=1000
        )
    assert session.closed == 1


def test_stop_cleanup_past_original_deadline_cannot_return_success():
    admission, session = Admission(), Session()
    ticks = [0.0]
    worker = executor(admission, Provider(session), clock=lambda: ticks[0])
    worker.start("a" * 64, deadline_ms=20000, correlation_id="start")

    def close():
        session.closed += 1
        ticks[0] = 2.0
        return True

    session.close = close
    with pytest.raises(LocalDeviceFailure) as caught:
        worker.stop("b" * 64, deadline_ms=1000, correlation_id="stop")
    assert caught.value.code == "LOCAL_DEVICE_DEADLINE_EXCEEDED"
    assert session.closed == 1


@pytest.mark.parametrize("failure", ["expiry", "cancel", "uncertain_commit"])
def test_real_media_redemption_retains_cleanup_owner_on_commit_failure(failure):
    from wso_core.tvt.local_media_admission import LocalMediaAdmission

    ticks, cancel = [0.0], Event()
    state = {"phase": "REQUESTED", "close": 0}

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class DB:
        def execute(self, sql, parameters=None):
            query = str(sql)
            if query == "SELECT current_user":
                return Result("wso_connection_worker")
            if "wso_tvt_local_media_redeem" in query:
                state["phase"] = "LOGIN"
                return Result(uuid4())
            if "wso_tvt_local_media_close" in query:
                state["phase"] = "CLOSED"
                state["close"] += 1
            return Result(None)

    class Engine:
        @contextmanager
        def begin(self):
            yield DB()
            if state["phase"] == "LOGIN":
                if failure == "expiry":
                    ticks[0] = 21.0
                elif failure == "cancel":
                    cancel.set()
                else:
                    raise RuntimeError("uncertain transport completion")

    # Constructed normally: close() also retires the lease's authority gate
    # state (R120). Only the engine under the real SQL ports is inert.
    admission = LocalMediaAdmission(URL, Key())
    admission._engine.dispose()
    admission._engine = Engine()
    worker = executor(admission, Provider(Session()), clock=lambda: ticks[0])
    with pytest.raises(LocalDeviceFailure):
        worker.start(
            "a" * 64, deadline_ms=20000, correlation_id="commit", cancel=cancel
        )
    assert state == {"phase": "CLOSED", "close": 1}


def test_shutdown_retries_failed_start_original_and_reports_uncertainty():
    admission, session = Admission(), Session()
    session.proof = replace(session.proof, live_permission=False)
    settled = [False]

    def close():
        session.closed += 1
        return settled[0]

    session.close = close
    worker = executor(admission, Provider(session))
    with pytest.raises(LocalDeviceFailure):
        worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    assert session.closed == 1
    assert worker.shutdown() is False
    assert session.closed == 2
    settled[0] = True
    assert worker.shutdown() is True
    assert session.closed == 3


def test_uncertain_committed_redemption_retries_exact_binding_after_close_recovers():
    from sqlalchemy.exc import SQLAlchemyError
    from wso_core.tvt.local_media_admission import LocalMediaAdmission

    state = {
        "phase": "REQUESTED",
        "close": 0,
        "authority": None,
        "retire_authority": None,
    }
    recovery = [False]

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class DB:
        def execute(self, sql, parameters=None):
            query = str(sql)
            if query == "SELECT current_user":
                return Result("wso_connection_worker")
            if "wso_tvt_local_media_redeem" in query:
                state["phase"] = "LOGIN"
                state["authority"] = (parameters["a"], parameters["w"], parameters["n"])
                return Result(uuid4())
            if "wso_tvt_local_media_close" in query:
                state["close"] += 1
                state["retire_authority"] = (
                    parameters["a"],
                    parameters["w"],
                    parameters["n"],
                )
                if not recovery[0]:
                    raise SQLAlchemyError("inert SQL retirement unavailable")
                state["phase"] = "CLOSED"
            return Result(None)

    class Engine:
        @contextmanager
        def begin(self):
            yield DB()
            if state["phase"] == "LOGIN":
                raise RuntimeError("uncertain commit")

    # Constructed normally: close() also retires the lease's authority gate
    # state (R120). Only the engine under the real SQL ports is inert.
    admission = LocalMediaAdmission(URL, Key())
    admission._engine.dispose()
    admission._engine = Engine()
    worker = executor(admission, Provider(Session()))
    with pytest.raises(LocalDeviceFailure):
        worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    assert state["phase"] == "LOGIN"
    recovery[0] = True
    worker.sweep()
    assert state["phase"] == "CLOSED"
    assert state["retire_authority"] == state["authority"]
    assert state["close"] == 2
    assert worker.shutdown() is True


def test_private_proof_port_returns_original_session_proof_only_while_current():
    admission, session = Admission(), Session()
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    assert worker.proof(admission.view.id) is session.proof
    admission.allowed = False
    with pytest.raises(LocalDeviceFailure):
        worker.proof(admission.view.id)
    assert session.closed == 1


def test_shutdown_cannot_report_settled_while_external_retirement_is_inflight():
    from threading import Thread

    admission, session = Admission(), Session()
    session.proof = replace(session.proof, live_permission=False)
    entered, release = Event(), Event()

    def close():
        session.closed += 1
        if session.closed == 2:
            entered.set()
            assert release.wait(2)
        return session.closed >= 3

    session.close = close
    worker = executor(admission, Provider(session))
    with pytest.raises(LocalDeviceFailure):
        worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    sweep = Thread(target=worker.sweep)
    sweep.start()
    try:
        assert entered.wait(1)
        assert sweep.is_alive()
        assert worker.shutdown() is False
    finally:
        release.set()
        sweep.join(2)
    assert not sweep.is_alive()
    assert worker.shutdown() is True
    assert session.closed == 3


def test_external_retirement_barrier_keeps_native_reaped_lease_unsettled():
    admission, session = Admission(), Session()
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    done = [False]
    calls = []

    def check():
        calls.append(True)
        return done[0]

    worker.attach_retirement(admission.view.id, check)
    assert worker.close(admission.view.id) is False
    assert admission.cleanup_confirmations == [False]
    assert not worker.current(admission.view.id)
    with pytest.raises(LocalDeviceFailure):
        worker.finish_stop(admission.view.id, correlation_id="stop")
    done[0] = True
    assert (
        worker.finish_stop(admission.view.id, correlation_id="stop").lease.state
        == "CLOSED"
    )
    assert admission.cleanup_confirmations == [False, False, True]
    assert len(calls) == 3


def test_retirement_callback_always_runs_even_native_cleanup_fails():
    admission, session = Admission(), Session()
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    called = []
    worker.attach_retirement(admission.view.id, lambda: called.append(True) or True)
    session.close = lambda: False
    assert worker.close(admission.view.id) is False
    assert called == [True] and admission.cleanup_confirmations == [False]


def test_attach_exactly_once_and_after_original_closing_is_denied():
    from threading import Thread

    admission, session = Admission(), Session()
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    worker.attach_retirement(admission.view.id, lambda: True)
    with pytest.raises(LocalDeviceFailure):
        worker.attach_retirement(admission.view.id, lambda: True)
    entered, release = Event(), Event()

    def close():
        entered.set()
        assert release.wait(2)
        return True

    session.close = close
    closer = Thread(target=lambda: worker.close(admission.view.id))
    closer.start()
    try:
        assert entered.wait(1)
        result = []

        def attach():
            try:
                worker.attach_retirement(admission.view.id, lambda: True)
            except LocalDeviceFailure:
                result.append("denied")

        attaching = Thread(target=attach)
        attaching.start()
        release.set()
        closer.join(2)
        attaching.join(2)
        assert not closer.is_alive() and not attaching.is_alive()
        assert result == ["denied"]
    finally:
        release.set()
        closer.join(2)


def test_finish_stop_uses_already_authorized_id_without_second_redemption():
    admission, session = Admission(), Session()
    redeemed = []

    def redeem(ticket, purpose, *, budget):
        redeemed.append(purpose)
        return admission.view.id

    admission.redeem_control = redeem
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    authorized = worker.authorize_control("b" * 64, "stop", deadline_ms=1000)
    assert worker.finish_stop(authorized, correlation_id="stop").lease.state == "CLOSED"
    assert redeemed == ["stop"]


def test_playing_control_requires_current_original_permission_and_delivery_proof():
    admission, session = Admission(), Session()
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="start")
    assert (
        worker.authorize_control("c" * 64, "playing", deadline_ms=1000)
        == admission.view.id
    )
    with pytest.raises(LocalDeviceFailure):
        worker.playing(admission.view.id, session.proof)
    admission.allowed = False
    with pytest.raises(LocalDeviceFailure):
        worker.authorize_control("d" * 64, "playing", deadline_ms=1000)


def test_real_api_issuer_accepts_only_three_closed_control_purposes():
    from wso_core.tvt.local_media_admission import LocalMediaTicketIssuer

    class Result:
        def scalar_one(self):
            return "a" * 64

    class DB:
        def execute(self, sql, parameters=None):
            return Result()

    issuer = LocalMediaTicketIssuer(DB(), lambda: 1000)
    assert issuer.issue_control("b" * 64, uuid4(), "playing") == "a" * 64
    with pytest.raises(LocalDeviceFailure):
        issuer.issue_control("b" * 64, uuid4(), "decode")


def test_executor_fences_immediately_despite_fresh_gate():
    from threading import Thread

    from tests.tvt_parity.test_local_media_authority_gate import Clock, gated_executor

    # A frozen gate clock: every gate answer stays fresh for the whole test.
    first_session, second_session = Session(), Session()
    sessions = iter((first_session, second_session))
    entered, release = Event(), Event()

    def slow_close():
        entered.set()
        assert release.wait(2)
        first_session.closed += 1
        return True

    first_session.close = slow_close

    class Sessions:
        def open_session(self, credentials, selection, **kwargs):
            return next(sessions)

    worker, admission, sql = gated_executor(Sessions(), clock=Clock())
    first = worker.start("a" * 64, deadline_ms=20000, correlation_id="first").lease
    second = worker.start("b" * 64, deadline_ms=20000, correlation_id="second").lease
    leases = {view.id: worker._owned[view.id].lease for view in (first, second)}
    assert worker.current(first.id) and worker.current(second.id)
    assert sql.count() == 2
    closer = Thread(target=lambda: worker.close(first.id), name="executor-close")
    closer.start()
    try:
        assert entered.wait(2)
        # The executor fences before native or SQL retirement, while the gate
        # still holds a fresh True for the same lease.
        assert not worker.current(first.id)
        assert admission.current(leases[first.id]) is True
    finally:
        release.set()
        closer.join(2)
    assert not closer.is_alive() and first_session.closed == 1
    assert admission.current(leases[first.id]) is False
    assert worker.current(second.id) and sql.count() == 2
    # Shutdown fences the remaining lease the same way, without new SQL.
    assert worker.shutdown() is True
    assert not worker.current(second.id) and second_session.closed == 1
    assert admission.current(leases[second.id]) is False
    assert sql.count() == 2 and {name for name, _, _ in sql.calls} == {"observe"}


def test_attach_denies_shutdown_that_crosses_its_current_check():
    admission, session = Admission(), Session()
    worker = executor(admission, Provider(session))
    worker.start("a" * 64, deadline_ms=20000, correlation_id="start")

    def current(lease):
        worker._stop.set()
        return True

    admission.current = current
    with pytest.raises(LocalDeviceFailure):
        worker.attach_retirement(admission.view.id, lambda: True)
    assert not worker.current(admission.view.id)
    assert worker.shutdown() is True
