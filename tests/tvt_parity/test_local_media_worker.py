import asyncio
import concurrent.futures
import threading
import time
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from wso_contracts.tvt.local_media import (
    LocalLiveOfferRequest,
    LocalLiveResponse,
    LocalLiveStartedRequest,
)
from wso_core.tvt.local_service import LocalDeviceFailure
from wso_core.tvt.windows_decode import DecodeBinding
from wso_tvt_media import worker as module
from wso_tvt_media.codec import MediaDenied

from tests.tvt_parity.test_local_media_rpc_api import public_view


class Core:
    def __init__(self):
        self.active = True
        self.closes = 0
        self.plays = 0
        self.barrier = None
        self.view = LocalLiveResponse.model_validate(public_view()).lease
        self.view.expires_at = datetime.now(UTC) + timedelta(seconds=29)
        self.id = self.view.id
        self.live_proof = object()

    def start(self, *args, **kwargs):
        return SimpleNamespace(lease=self.view, request_id="test")

    def authorize_control(self, ticket, purpose, **kwargs):
        if purpose == "stop":
            self.active = False
            self.view.state = "STOPPING"
        return self.id

    def attach_retirement(self, lease_id, check):
        assert lease_id == self.id and self.barrier is None
        self.barrier = check

    def proof(self, lease_id):
        assert lease_id == self.id
        return self.live_proof

    def finish_stop(self, lease_id, *, correlation_id):
        assert lease_id == self.id and self.view.state == "CLOSED"
        return LocalLiveResponse(lease=self.view, request_id=correlation_id)

    def lease(self, *args):
        return self.view

    def current(self, *args):
        return self.active

    def playing(self, *args):
        self.plays += 1
        self.view.state = "PLAYING"
        return self.view

    def close(self, *args):
        self.active = False
        if self.barrier and not self.barrier():
            self.view.state = "STOPPING"
            return False
        if self.view.state != "CLOSED":
            self.closes += 1
        self.view.state = "CLOSED"
        return True

    def stop(self, *args, **kwargs):
        self.close()
        return SimpleNamespace(lease=self.view, request_id="test")

    def shutdown(self):
        return True


def test_start_diagnostic_preparation_failure_precedes_cleanup(monkeypatch):
    events = []
    core = Core()

    def fail_proof(lease):
        raise ValueError("private-secret")

    core.proof = fail_proof
    owner = module.LocalMediaWorker(
        core,
        decoder_executable=Path(__file__).resolve(),
        observation_factory=lambda: (
            lambda stage, reason: events.append((stage, reason))
        ),
    )
    try:
        with pytest.raises(LocalDeviceFailure):
            owner.start("ticket", deadline_ms=1000, correlation_id="test")
        assert events[0] == ("proof_read", "failure")
        assert core.closes == 1
    finally:
        settle(owner)


def test_observer_factory_failure_does_not_change_start_cleanup(monkeypatch):
    core = Core()

    def broken():
        raise RuntimeError("private-secret")

    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    owner = module.LocalMediaWorker(
        core, decoder_executable=Path(__file__).resolve(), observation_factory=broken
    )
    try:
        assert (
            owner.start("ticket", deadline_ms=1000, correlation_id="test").lease.id
            == core.id
        )
    finally:
        settle(owner)
    assert core.closes == 1


class Source:
    def __init__(self, *args, proof=None):
        self.closed = False
        self.proof = proof
        self.adapter = SimpleNamespace(proof=proof)
        self.produced_frames = 1

    def start(self):
        pass

    def current(self):
        return not self.closed

    def alive(self):
        return not self.closed

    def transport_current(self):
        return not self.closed

    async def binding(self):
        return DecodeBinding(
            generation=1, owner=b"o" * 16, channel=b"c" * 16, task=b"t" * 16
        )

    async def close(self):
        self.closed = True


class Peer:
    original_close_failed = False

    def __init__(self, **kwargs):
        self.source = kwargs["source"]
        self.current = kwargs["current"]
        self.permitted = kwargs.get("permitted")
        self.peer = self
        self.closed = False
        self.connectionState = "new"

    async def answer(self, *args):
        return SimpleNamespace(sdp="v=0\r\n")

    async def close(self):
        await self.source.close()
        self.closed = True

    async def wait_closed(self):
        pass

    def renew(self, *args):
        pass


def settle(owner):
    end = time.monotonic() + 3
    while not owner.shutdown():
        assert time.monotonic() < end
        time.sleep(0.01)


def test_rpc_facade_preserves_original_sources_until_stop_settles(monkeypatch):
    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Core()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    try:
        result = owner.start("ticket", deadline_ms=20000, correlation_id="test")
        source = owner._sources[result.lease.id]
        peer = owner._peers[result.lease.id]
        response = owner.offer(
            "ticket",
            offer=LocalLiveOfferRequest(sdp="v=0\r\n", offer_id=uuid4()),
            deadline_ms=20000,
            correlation_id="test",
        )
        assert response.type == "answer"
        owner.stop("ticket", deadline_ms=20000, correlation_id="test")
        assert source.closed and peer.closed and core.closes == 1
        assert not owner._sources and not owner._peers
    finally:
        settle(owner)
    assert not owner._thread.is_alive()


def test_cancelled_start_retains_pending_source_cleanup_until_confirmed(monkeypatch):
    entered = threading.Event()
    closing = threading.Event()
    gate = threading.Event()

    class Pending(Source):
        async def binding(self):
            entered.set()
            await asyncio.Future()

        async def close(self):
            closing.set()
            while not gate.is_set():
                await asyncio.sleep(0.01)
            self.closed = True

    monkeypatch.setattr(module, "NativeDecodedSource", Pending)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    owner = module.LocalMediaWorker(Core(), decoder_executable=Path(__file__).resolve())
    cancel = threading.Event()
    failures = []

    def start():
        try:
            owner.start(
                "ticket", deadline_ms=20000, correlation_id="test", cancel=cancel
            )
        except LocalDeviceFailure:
            failures.append(True)

    caller = threading.Thread(target=start)
    caller.start()
    try:
        assert entered.wait(2)
        cancel.set()
        caller.join(2)
        assert failures and closing.wait(2)
        assert not owner.shutdown()
        assert owner._sources
    finally:
        gate.set()
        caller.join(2)
        settle(owner)
    assert not owner._sources and not owner._thread.is_alive()


def test_playing_needs_browser_receipt_connected_peer_and_real_decoded_source(
    monkeypatch,
):
    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Core()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        assert core.plays == 0
        with pytest.raises(LocalDeviceFailure):
            owner.playing(
                "ticket",
                started=LocalLiveStartedRequest(decoded_frames=1),
                deadline_ms=20000,
                correlation_id="test",
            )
        peer = owner._peers[core.id]
        source = owner._sources[core.id]
        peer.connectionState = "connected"
        source.produced_frames = 0
        with pytest.raises(LocalDeviceFailure):
            owner.playing(
                "ticket",
                started=LocalLiveStartedRequest(decoded_frames=1),
                deadline_ms=20000,
                correlation_id="test",
            )
        source.produced_frames = 1
        assert (
            owner.playing(
                "ticket",
                started=LocalLiveStartedRequest(decoded_frames=1),
                deadline_ms=20000,
                correlation_id="test",
            ).lease.state
            == "PLAYING"
        )
        assert core.plays == 1
    finally:
        settle(owner)


def test_sql_closed_waits_for_decoder_and_peer_retirement(monkeypatch):
    entered = threading.Event()
    gate = threading.Event()

    class Slow(Source):
        async def close(self):
            entered.set()
            while not gate.is_set():
                await asyncio.sleep(0.01)
            self.closed = True

    monkeypatch.setattr(module, "NativeDecodedSource", Slow)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Core()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    results = []
    owner.start("ticket", deadline_ms=20000, correlation_id="test")
    caller = threading.Thread(
        target=lambda: results.append(
            owner.stop("ticket", deadline_ms=20000, correlation_id="test")
        )
    )
    caller.start()
    try:
        assert entered.wait(2)
        assert core.view.state == "STOPPING" and core.closes == 0 and caller.is_alive()
        gate.set()
        caller.join(2)
        assert results[0].lease.state == "CLOSED" and core.closes == 1
    finally:
        gate.set()
        caller.join(2)
        settle(owner)


def on_loop(owner, function):
    done: concurrent.futures.Future = concurrent.futures.Future()

    def run():
        try:
            done.set_result(function())
        except BaseException as error:  # noqa: BLE001 -- surface to the test thread.
            done.set_exception(error)

    owner._loop.call_soon_threadsafe(run)
    return done.result(2)


def cancel_on_loop(owner, task):
    async def cancel():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run_coroutine_threadsafe(cancel(), owner._loop).result(2)


def request_playing(owner):
    return owner.playing(
        "ticket",
        started=LocalLiveStartedRequest(decoded_frames=1),
        deadline_ms=20000,
        correlation_id="test",
    )


def test_peer_receives_sql_free_transport_permit(monkeypatch):
    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Core()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        peer, source = owner._peers[core.id], owner._sources[core.id]
        # Lock-only liveness fences; the emission permit only withholds.
        assert peer.current == source.alive
        assert peer.permitted == source.transport_current
        assert peer.current != source.current
    finally:
        settle(owner)


def test_prepare_fetches_proof_and_attaches_retirement_off_loop(monkeypatch):
    seen: list[tuple[str, int]] = []

    class Recording(Core):
        def attach_retirement(self, lease_id, check):
            seen.append(("attach", threading.get_ident()))
            super().attach_retirement(lease_id, check)

        def proof(self, lease_id):
            seen.append(("proof", threading.get_ident()))
            return super().proof(lease_id)

    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Recording()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        assert [name for name, _ in seen] == ["attach", "proof"]
        assert owner._thread.ident not in [ident for _, ident in seen]
        assert owner._sources[core.id].proof is core.live_proof
    finally:
        settle(owner)


@pytest.mark.parametrize("change", ["retired", "capped"])
def test_prepare_refuses_source_when_entry_changes_while_proof_pending(
    monkeypatch, change
):
    entered = threading.Event()
    gate = threading.Event()
    created = []

    class Held(Core):
        def proof(self, lease_id):
            entered.set()
            gate.wait(3)
            return super().proof(lease_id)

    class Counted(Source):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(module, "NativeDecodedSource", Counted)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Held()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    failures = []

    def start():
        try:
            owner.start("ticket", deadline_ms=20000, correlation_id="test")
        except LocalDeviceFailure as error:
            failures.append(error)

    caller = threading.Thread(target=start)
    caller.start()
    others = tuple(uuid4() for _ in range(16))
    try:
        assert entered.wait(3)
        if change == "retired":
            owner.stop("ticket", deadline_ms=20000, correlation_id="test")
        else:
            # Sixteen other sources registered while this start's SQL was pending.
            on_loop(owner, lambda: owner._sources.update(dict.fromkeys(others)))
        gate.set()
        caller.join(5)
        assert failures and not created
        assert core.id not in owner._sources and not owner._peers
    finally:
        gate.set()
        caller.join(5)
        on_loop(owner, lambda: [owner._sources.pop(key, None) for key in others])
        settle(owner)


def test_watch_sql_runs_off_loop_without_stalling_it(monkeypatch):
    idents: dict[str, list[int]] = {"current": [], "lease": []}

    blocked: list[tuple[float, float]] = []

    class Blocking(Source):
        def current(self):
            idents["current"].append(threading.get_ident())
            started = time.monotonic()
            time.sleep(0.3)
            blocked.append((started, time.monotonic()))
            return not self.closed

    class Recording(Core):
        def lease(self, *args):
            idents["lease"].append(threading.get_ident())
            return super().lease(*args)

    monkeypatch.setattr(module, "NativeDecodedSource", Blocking)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Recording()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    ticks: list[float] = []

    async def heartbeat():
        while True:
            ticks.append(time.monotonic())
            await asyncio.sleep(0.02)

    task = None
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        idents["lease"].clear()
        task = on_loop(owner, lambda: owner._loop.create_task(heartbeat()))
        end = time.monotonic() + 3
        while not idents["lease"] and time.monotonic() < end:
            time.sleep(0.01)
        assert idents["current"] and idents["lease"]
        assert owner._thread.ident not in idents["current"] + idents["lease"]
        gaps = [b - a for a, b in pairwise(ticks)]
        assert gaps and max(gaps) < 0.2
        # The loop kept ticking during the blocking SQL interval itself.
        assert any(
            sum(start < tick < end for tick in ticks) >= 5 for start, end in blocked
        )
    finally:
        if task is not None:
            cancel_on_loop(owner, task)
        settle(owner)


def test_watch_skips_entry_retired_during_pending_authority_call(monkeypatch):
    entered = threading.Event()
    gate = threading.Event()
    resumed = threading.Event()
    retired = threading.Event()
    after: list[str] = []

    class Held(Source):
        def current(self):
            entered.set()
            gate.wait(2)
            resumed.set()
            return True

    class Recording(Core):
        def lease(self, *args):
            if retired.is_set():
                after.append("lease")
            return super().lease(*args)

    class Renewing(Peer):
        def renew(self, *args):
            if retired.is_set():
                after.append("renew")

    monkeypatch.setattr(module, "NativeDecodedSource", Held)
    monkeypatch.setattr(module, "LocalWebRtcSession", Renewing)
    core = Recording()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        assert entered.wait(3)
        owner.stop("ticket", deadline_ms=20000, correlation_id="test")
        retired.set()
        gate.set()
        assert resumed.wait(2)
        time.sleep(0.3)
        # The resumed authority call must not lease or renew a retired entry.
        assert after == [] and not owner._monitor.done()
    finally:
        gate.set()
        settle(owner)


def test_browser_received_sql_runs_off_loop_and_uses_fresh_proof(monkeypatch):
    seen: dict[str, list] = {"current": [], "playing": [], "proof": [], "fresh": []}

    class Recorded(Source):
        def current(self):
            seen["current"].append(threading.get_ident())
            # A proof read before this fresh check would be the older object.
            self.adapter.proof = object()
            seen["fresh"].append(self.adapter.proof)
            return not self.closed

    class Recording(Core):
        def playing(self, lease_id, given):
            seen["playing"].append(threading.get_ident())
            seen["proof"].append(given)
            return super().playing(lease_id, given)

    monkeypatch.setattr(module, "NativeDecodedSource", Recorded)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Recording()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        owner._peers[core.id].connectionState = "connected"
        seen["current"].clear()
        assert request_playing(owner).lease.state == "PLAYING"
        assert seen["playing"] and owner._thread.ident not in seen["playing"]
        assert seen["current"] and owner._thread.ident not in seen["current"]
        assert seen["proof"] == [seen["fresh"][-1]]
    finally:
        settle(owner)


def test_browser_received_denies_when_current_false_before_playing(monkeypatch):
    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Core()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        owner._peers[core.id].connectionState = "connected"
        owner._sources[core.id].closed = True
        with pytest.raises(LocalDeviceFailure) as failure:
            request_playing(owner)
        assert failure.value.status == 404 and core.plays == 0
    finally:
        settle(owner)


@pytest.mark.parametrize(
    "change", ["replace_peer", "replace_source", "remove", "drop", "closing"]
)
def test_browser_received_denies_when_entry_changes_during_pending_call(
    monkeypatch, change
):
    entered = threading.Event()
    gate = threading.Event()

    class Held(Source):
        def current(self):
            if self.closed:
                return False
            entered.set()
            gate.wait(3)
            return True

    monkeypatch.setattr(module, "NativeDecodedSource", Held)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Core()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    errors: list[LocalDeviceFailure] = []
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        owner._peers[core.id].connectionState = "connected"

        def call():
            try:
                request_playing(owner)
            except LocalDeviceFailure as error:
                errors.append(error)

        caller = threading.Thread(target=call)
        caller.start()
        assert entered.wait(3)
        original_peer, original_source = owner._peers[core.id], owner._sources[core.id]

        def mutate():
            if change == "replace_peer":
                replacement = Peer(source=original_source, current=None)
                replacement.connectionState = "connected"
                owner._peers[core.id] = replacement
            elif change == "replace_source":
                owner._sources[core.id] = Held()
            elif change == "remove":
                owner._peers.pop(core.id)
            elif change == "closing":
                owner._closing[core.id] = owner._loop.create_task(asyncio.sleep(30))
            else:
                original_peer.connectionState = "closed"

        on_loop(owner, mutate)
        gate.set()
        caller.join(5)
        assert errors and errors[0].status == 404 and core.plays == 0

        def restore():
            owner._peers[core.id] = original_peer
            owner._sources[core.id] = original_source
            retiring = owner._closing.pop(core.id, None)
            if retiring is not None:
                retiring.cancel()

        on_loop(owner, restore)
    finally:
        gate.set()
        settle(owner)


def test_browser_received_denies_entry_already_retiring(monkeypatch):
    checked = []

    class Recorded(Source):
        def current(self):
            checked.append(True)
            return True

    monkeypatch.setattr(module, "NativeDecodedSource", Recorded)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Core()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        owner._peers[core.id].connectionState = "connected"
        retiring = on_loop(
            owner,
            lambda: owner._closing.setdefault(
                core.id, owner._loop.create_task(asyncio.sleep(30))
            ),
        )
        with pytest.raises(LocalDeviceFailure) as failure:
            request_playing(owner)
        assert failure.value.status == 404 and core.plays == 0 and not checked
        on_loop(owner, lambda: owner._closing.pop(core.id))
        cancel_on_loop(owner, retiring)
    finally:
        settle(owner)


def test_browser_received_denies_when_entry_changes_after_playing(monkeypatch):
    entered = threading.Event()
    gate = threading.Event()

    class Held(Core):
        def playing(self, *args):
            value = super().playing(*args)
            entered.set()
            gate.wait(3)
            return value

    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Held()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    errors: list[LocalDeviceFailure] = []
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        peer = owner._peers[core.id]
        peer.connectionState = "connected"

        def call():
            try:
                request_playing(owner)
            except LocalDeviceFailure as error:
                errors.append(error)

        caller = threading.Thread(target=call)
        caller.start()
        assert entered.wait(3)

        def drop():
            peer.connectionState = "closed"

        on_loop(owner, drop)
        gate.set()
        caller.join(5)
        # SQL PLAYING was written, but the response still fails closed.
        assert errors and errors[0].status == 404 and core.plays == 1
    finally:
        gate.set()
        settle(owner)


def uncertain_close_worker(monkeypatch, *, failed):
    """The bounded close reports uncertainty; settlement reports the outcome."""
    events: list[str] = []

    class Settled(Peer):
        settled = False

        async def close(self):
            events.append("peer.close")
            raise MediaDenied()

        async def wait_closed(self):
            events.append("wait_closed")
            self.settled = True
            raise MediaDenied()

        @property
        def original_close_failed(self):
            assert self.settled  # Read only after the settlement barrier.
            events.append("outcome")
            return failed

    class Tracked(Source):
        def current(self):
            events.append("source.current")
            return super().current()

        async def close(self):
            events.append("source.close")
            self.closed = True

    class Recording(Core):
        def lease(self, *args):
            events.append("sql.lease")
            return super().lease(*args)

        def close(self, lease_id, *args):
            if lease_id != self.id:
                return True
            events.append("sql.close")
            return super().close(lease_id)

        def finish_stop(self, lease_id, *, correlation_id):
            # LocalMediaExecutor.finish_stop: an unconfirmed close fails stop.
            if not Core.close(self, lease_id):
                raise LocalDeviceFailure()
            return super().finish_stop(lease_id, correlation_id=correlation_id)

    monkeypatch.setattr(module, "NativeDecodedSource", Tracked)
    monkeypatch.setattr(module, "LocalWebRtcSession", Settled)
    core = Recording()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    owner.start("ticket", deadline_ms=20000, correlation_id="test")
    events.clear()
    return owner, core, events


def abandon(owner):
    """Quarantine keeps shutdown() False by design; then stop the test loop."""
    end = time.monotonic() + 3
    try:
        while owner._shutdown_future is None or not owner._shutdown_future.done():
            assert owner.shutdown() is False
            assert time.monotonic() < end
            time.sleep(0.01)
        assert owner.shutdown() is False
        return owner._shutdown_future.result()
    finally:
        if owner._thread.is_alive():
            owner._loop.call_soon_threadsafe(owner._loop.stop)
            owner._thread.join(2)


def test_uncertain_close_with_clean_settlement_confirms_without_second_close(
    monkeypatch,
):
    owner, core, events = uncertain_close_worker(monkeypatch, failed=False)
    try:
        owner.stop("ticket", deadline_ms=20000, correlation_id="test")
        # Source before peer; the original close is awaited, never re-called;
        # a timeout that later settled cleanly still confirms closure.
        assert events == [
            "peer.close",
            "source.close",
            "wait_closed",
            "outcome",
            "sql.close",
        ]
        assert not owner._sources and not owner._peers and core.closes == 1
        assert core.id not in owner._quarantined
    finally:
        settle(owner)


def test_original_close_failure_quarantines_lease_and_keeps_custody(monkeypatch):
    owner, core, events = uncertain_close_worker(monkeypatch, failed=True)
    try:
        with pytest.raises(LocalDeviceFailure):
            owner.stop("ticket", deadline_ms=20000, correlation_id="test")
        # No runtime-closed signal and no confirming SQL close from the worker.
        assert events == ["peer.close", "source.close", "wait_closed", "outcome"]
        assert core.closes == 0 and core.view.state != "CLOSED"
        assert core.id in owner._quarantined
        assert not owner._runtime_closed[core.id].is_set()
        assert core.id in owner._sources and core.id in owner._peers
        # Retained custody still counts toward the sixteen-source cap.
        others = tuple(uuid4() for _ in range(15))
        on_loop(owner, lambda: owner._sources.update({key: Source() for key in others}))
        with pytest.raises(MediaDenied):
            asyncio.run_coroutine_threadsafe(
                owner._prepare(uuid4()), owner._loop
            ).result(2)
        on_loop(owner, lambda: [owner._sources.pop(key) for key in others])
    finally:
        assert abandon(owner) is False
    assert core.closes == 0 and not owner._thread.is_alive()


def test_quarantined_lease_is_not_retried_by_watch_or_close_entry(monkeypatch):
    owner, core, events = uncertain_close_worker(monkeypatch, failed=True)
    probed = threading.Event()

    class Probe(Source):
        def current(self):
            probed.set()
            return True

    other = uuid4()
    try:
        with pytest.raises(LocalDeviceFailure):
            owner.stop("ticket", deadline_ms=20000, correlation_id="test")
        assert core.id in owner._quarantined
        events.clear()
        on_loop(owner, lambda: owner._sources.setdefault(other, Probe()))
        probed.clear()
        assert probed.wait(3)  # A watch pass ran over every registered entry.
        asyncio.run_coroutine_threadsafe(
            owner._close_entry(core.id), owner._loop
        ).result(2)
        assert events == [] and core.closes == 0
        on_loop(owner, lambda: owner._sources.pop(other))
    finally:
        assert abandon(owner) is False


def test_watch_survives_close_entry_failure_and_keeps_renewing(monkeypatch):
    failing = uuid4()
    failures: list[float] = []
    renewals: list[float] = []

    class Failing(Core):
        def close(self, lease_id, *args):
            if lease_id == failing:
                failures.append(time.monotonic())
                raise RuntimeError("unexpected close failure")
            return super().close(lease_id, *args)

    class Revoked(Source):
        def current(self):
            return False

    class Renewing(Peer):
        def renew(self, *args):
            renewals.append(time.monotonic())

    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Renewing)
    owner = module.LocalMediaWorker(
        Failing(), decoder_executable=Path(__file__).resolve()
    )
    try:
        # Registered first, so each pass meets the failing close before the
        # healthy lease: _close_entry raises inside _watch on every pass.
        on_loop(owner, lambda: owner._sources.setdefault(failing, Revoked()))
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        end = time.monotonic() + 6
        while time.monotonic() < end and (
            len(failures) < 2 or sum(t > failures[0] for t in renewals) < 2
        ):
            time.sleep(0.02)
        # Custody kept (still registered, retried next pass) and the other
        # lease kept being renewed after the failure.
        assert len(failures) >= 2 and failing in owner._sources
        assert sum(t > failures[0] for t in renewals) >= 2
        assert not owner._monitor.done()
    finally:
        on_loop(owner, lambda: owner._sources.pop(failing, None))
        settle(owner)


def test_unconfirmed_sql_close_backs_off_to_one_second(monkeypatch):
    real_sleep = asyncio.sleep
    delays: list[float] = []
    attempts: list[bool] = []

    class Unconfirmed(Core):
        def close(self, *args):
            attempts.append(True)
            if len(attempts) <= 7:
                return False  # SQL closure not confirmed yet.
            return super().close(*args)

    class Clock:
        """Worker-module asyncio that records retry sleeps (not the 1 s watch)."""

        def __getattr__(self, name):
            return getattr(asyncio, name)

        async def sleep(self, delay, result=None):
            if asyncio.current_task() is not owner._monitor:
                delays.append(delay)
                delay = 0
            return await real_sleep(delay, result)

    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Unconfirmed()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    monkeypatch.setattr(module, "asyncio", Clock())
    try:
        owner.start("ticket", deadline_ms=20000, correlation_id="test")
        owner.stop("ticket", deadline_ms=20000, correlation_id="test")
        assert delays == [0.05, 0.1, 0.2, 0.4, 0.8, 1.0, 1.0]
        assert len(attempts) == 8 and core.closes == 1
    finally:
        settle(owner)


@pytest.mark.parametrize("pending_cleanup", [False, True])
def test_worker_maps_no_signal_to_504_code_and_releases_source(
    monkeypatch, pending_cleanup
):
    from wso_tvt_media import native_source

    held = threading.Event()
    entered = threading.Event()
    originals = []
    errors = []

    class NoFrames(Source):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            originals.append(self)

        async def binding(self):
            no_signal = getattr(native_source, "MediaNoSignal", MediaDenied)
            raise no_signal()

        async def close(self):
            entered.set()
            if pending_cleanup:
                while not held.is_set():
                    await asyncio.sleep(0.001)
            await super().close()

    monkeypatch.setattr(module, "NativeDecodedSource", NoFrames)
    core = Core()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())

    def start():
        try:
            owner.start("ticket", deadline_ms=20000, correlation_id="test")
        except LocalDeviceFailure as failure:
            errors.append(failure)

    caller = threading.Thread(target=start)
    try:
        caller.start()
        assert entered.wait(2)
        if pending_cleanup:
            assert caller.is_alive() and core.closes == 0
            assert owner._sources[core.id] is originals[0]
            assert not owner._runtime_closed[core.id].is_set()
        held.set()
        caller.join(3)
        assert not caller.is_alive() and len(errors) == 1
        assert (errors[0].code, errors[0].status) == ("LOCAL_DEVICE_NO_SIGNAL", 504)
        assert originals[0].closed and core.closes == 1
        assert not owner._sources and not owner._peers and not owner._runtime_closed
        assert core.view.state == "CLOSED"
    finally:
        held.set()
        caller.join(3)
        settle(owner)


@pytest.mark.parametrize(
    "code,status",
    [
        ("LOCAL_DEVICE_BUSY", 429),
        ("LOCAL_DEVICE_UPSTREAM_REJECTED", 502),
        ("LOCAL_DEVICE_DENIED", 404),
        ("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504),
    ],
)
def test_worker_keeps_known_start_refusals_distinct_from_no_signal(
    monkeypatch, code, status
):
    class Refused(Core):
        def start(self, *args, **kwargs):
            raise LocalDeviceFailure(code, status)

    owner = module.LocalMediaWorker(
        Refused(), decoder_executable=Path(__file__).resolve()
    )
    try:
        with pytest.raises(LocalDeviceFailure) as failure:
            owner.start("ticket", deadline_ms=20000, correlation_id="test")
        assert (failure.value.code, failure.value.status) == (code, status)
        assert not owner._sources and not owner._peers
    finally:
        settle(owner)


@pytest.mark.parametrize("occupied, allowed", [(2, True), (15, True), (16, False)])
def test_prepare_sixteen_source_capacity(monkeypatch, occupied, allowed):
    monkeypatch.setattr(module, "NativeDecodedSource", Source)
    monkeypatch.setattr(module, "LocalWebRtcSession", Peer)
    core = Core()
    owner = module.LocalMediaWorker(core, decoder_executable=Path(__file__).resolve())
    others = tuple(uuid4() for _ in range(occupied))
    try:
        on_loop(owner, lambda: owner._sources.update({key: Source() for key in others}))
        if allowed:
            owner.start("ticket", deadline_ms=20000, correlation_id="test")
            assert core.id in owner._sources and core.id in owner._peers
        else:
            with pytest.raises(LocalDeviceFailure):
                owner.start("ticket", deadline_ms=20000, correlation_id="test")
            assert core.id not in owner._sources
    finally:
        on_loop(owner, lambda: [owner._sources.pop(key, None) for key in others])
        settle(owner)
