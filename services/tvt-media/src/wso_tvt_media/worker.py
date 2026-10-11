"""Owned synchronous RPC facade over the private native/decoder/WebRTC pipeline."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from wso_contracts.tvt.local_media import (
    LocalLiveOfferRequest,
    LocalLiveOfferResponse,
    LocalLiveResponse,
    LocalLiveStartedRequest,
)
from wso_core.tvt.local_media_mux_service import MuxMediaExecutor
from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL, ViewerCleanupReceipt
from wso_core.tvt.local_media_service import LocalMediaExecutor
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget

from .codec import MediaDenied
from .live import LocalWebRtcSession
from .mux_source import MuxSourceFactory
from .native_source import (
    FailureObserver,
    MediaNoSignal,
    NativeDecodedSource,
    failure_reason,
    observe_failure,
)
from .signaling import SignalingDenied

MAX_MEDIA_SOURCES = 16


class _LocalStartup:
    """One pre-start local owner; pending preparation never means empty media."""

    def __init__(self, registration: UUID) -> None:
        self.registration = registration
        self.prepared = threading.Event()
        self.requested = threading.Event()
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.receipt: ViewerCleanupReceipt | None = None
        self.authority = object()


class LocalMediaWorker:
    def __init__(
        self,
        executor: LocalMediaExecutor | MuxMediaExecutor,
        *,
        decoder_executable: Path,
        observation_factory: Callable[[], FailureObserver] | None = None,
        source_factory: MuxSourceFactory | None = None,
        retain_owner: Callable[[LocalMediaWorker], None] | None = None,
    ) -> None:
        if not decoder_executable.is_absolute() or not decoder_executable.is_file():
            raise LocalDeviceFailure()
        self.executor, self.decoder_executable = executor, decoder_executable
        if (source_factory is None and isinstance(executor, MuxMediaExecutor)) or (
            source_factory is not None and source_factory.executor is not executor
        ):
            raise LocalDeviceFailure()
        self._source_factory = source_factory
        self._max_sources = 12 if source_factory is not None else MAX_MEDIA_SOURCES
        self._observation_factory = observation_factory
        self._loop = asyncio.new_event_loop()
        self._sources: dict[UUID, NativeDecodedSource] = {}
        self._peers: dict[UUID, LocalWebRtcSession] = {}
        self._closing: dict[UUID, asyncio.Task[None]] = {}
        self._runtime_closed: dict[UUID, threading.Event] = {}
        self._startups: dict[UUID, _LocalStartup] = {}
        # An original close owner failed: custody is kept and never confirmed.
        self._quarantined: set[UUID] = set()
        self._stopping = threading.Event()
        self._ready = threading.Event()
        self._guard = threading.Lock()
        self._inflight = 0
        self._shutdown_future: concurrent.futures.Future[bool] | None = None
        self._construction_done = threading.Event()
        self._thread_entered = threading.Event()
        self._thread_exited = threading.Event()
        self._loop_closed = threading.Event()
        self._start_attempted = False
        self._runtime_ready = False
        self._executor_closed = False
        self._monitor: asyncio.Task[None] | None = None
        self._original_loop = self._loop
        self._original_thread: threading.Thread | None = None

        def run() -> None:
            self._thread_entered.set()
            try:
                if self._stopping.is_set():
                    return
                asyncio.set_event_loop(self._original_loop)
                self._monitor = self._original_loop.create_task(self._watch())
                self._runtime_ready = True
                self._ready.set()
                self._original_loop.run_forever()
            except BaseException:  # noqa: BLE001 -- retain original runtime, never publish private errors.
                self._stopping.set()
            finally:
                self._close_original_loop()
                self._thread_exited.set()
                self._ready.set()

        try:
            self._thread = threading.Thread(
                target=run, name="local-media-loop-owner", daemon=False
            )
            self._original_thread = self._thread
            if retain_owner is not None:
                retain_owner(self)
            if self._stopping.is_set():
                raise LocalDeviceFailure()
            self._start_attempted = True
            self._original_thread.start()
            if (
                not self._ready.wait(5)
                or not self._runtime_ready
                or self._thread_exited.is_set()
            ):
                raise LocalDeviceFailure()
        except BaseException:
            self._stopping.set()
            if not self._start_attempted:
                self._close_original_loop()
            raise
        finally:
            self._construction_done.set()

    def _close_original_loop(self) -> bool:
        if self._loop_closed.is_set():
            return True
        try:
            self._original_loop.close()
            if self._original_loop.is_closed():
                self._loop_closed.set()
        except BaseException:  # noqa: BLE001 -- uncertain original loop closure stays pending.
            return False
        return self._loop_closed.is_set()

    def _close_executor(self) -> bool:
        if not self._executor_closed:
            self._executor_closed = self.executor.shutdown() is True
        return self._executor_closed

    def _await(
        self, operation: Any, budget: LocalVerifyBudget, *, cancel_future: bool = True
    ) -> Any:
        future = asyncio.run_coroutine_threadsafe(operation, self._loop)
        try:
            while True:
                budget.remaining_ms()
                try:
                    return future.result(timeout=0.025)
                except concurrent.futures.TimeoutError:
                    continue
        except BaseException:
            if cancel_future:
                future.cancel()
            raise

    def _retain_local(
        self, lease_id: UUID, registration: UUID
    ) -> Callable[[], ViewerCleanupReceipt | None]:
        startup = _LocalStartup(registration)
        with self._guard:
            if lease_id in self._runtime_closed:
                raise MediaDenied()
            self._startups[lease_id] = startup
            self._runtime_closed[lease_id] = startup.closed

        def retirement() -> ViewerCleanupReceipt | None:
            with startup.lock:
                if startup.closed.is_set() and startup.prepared.is_set():
                    if startup.receipt is None:
                        startup.receipt = ViewerCleanupReceipt(
                            lease_id=lease_id,
                            registration_id=registration,
                            decoder_settled=True,
                            peer_settled=True,
                            media_cleared=True,
                            _authority=startup.authority,
                            _seal=_CUSTODY_SEAL,
                        )
                    return startup.receipt
                if not startup.requested.is_set():
                    startup.requested.set()
                    self._loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self._close_entry(lease_id))
                    )
                return None

        return retirement

    def start(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: threading.Event | None = None,
    ) -> LocalLiveResponse:
        budget = LocalVerifyBudget(deadline_ms, cancel=cancel)
        with self._guard:
            if self._stopping.is_set() or not self._construction_done.is_set():
                raise LocalDeviceFailure()
            self._inflight += 1
        result = None
        observe = None
        if self._observation_factory is not None:
            try:
                observe = self._observation_factory()
            except BaseException:  # noqa: BLE001, S110 -- optional diagnostic only, never log.
                pass
        stage = "executor_start"
        retained: list[tuple[UUID, _LocalStartup]] = []
        dispatched = False

        def retain_local(
            lease_id: UUID, registration: UUID
        ) -> Callable[[], ViewerCleanupReceipt | None]:
            callback = self._retain_local(lease_id, registration)
            retained.append((lease_id, self._startups[lease_id]))
            return callback

        try:
            options: dict[str, Any] = {}
            if self._source_factory is not None:
                options["retain_local"] = retain_local
            result = self.executor.start(
                ticket,
                deadline_ms=budget.remaining_ms(),
                correlation_id=correlation_id,
                cancel=budget.cancel,
                **options,
            )
            stage = "worker_start"
            dispatched = True
            self._await(
                self._prepare(result.lease.id, observe=observe),
                budget,
                cancel_future=self._source_factory is None,
            )
            budget.remaining_ms()
            return result
        except Exception as error:  # noqa: BLE001 -- normalize private startup failures
            observe_failure(observe, stage, failure_reason(error))
            if result is not None:
                self.executor.close(result.lease.id)
            if isinstance(error, MediaNoSignal):
                raise LocalDeviceFailure("LOCAL_DEVICE_NO_SIGNAL", 504) from None
            if isinstance(error, LocalDeviceFailure):
                raise LocalDeviceFailure(error.code, error.status) from None
            raise LocalDeviceFailure() from None
        finally:
            for lease_id, startup in retained:
                if not dispatched:
                    startup.prepared.set()  # No local preparation was scheduled.
                if (
                    result is None
                    or startup.requested.is_set()
                    or self._stopping.is_set()
                ):

                    def close_retained(ident: UUID = lease_id) -> None:
                        asyncio.create_task(self._close_entry(ident))

                    self._loop.call_soon_threadsafe(close_retained)
            with self._guard:
                self._inflight -= 1

    async def _prepare(
        self, lease_id: UUID, *, observe: FailureObserver | None = None
    ) -> None:
        startup = self._startups.get(lease_id)
        if startup is None:
            await self._prepare_media(lease_id, observe=observe)
            return
        try:
            try:
                await self._prepare_media(lease_id, observe=observe)
            finally:
                startup.prepared.set()
        except BaseException:
            await asyncio.shield(self._close_entry(lease_id))
            raise

    async def _prepare_media(
        self, lease_id: UUID, *, observe: FailureObserver | None = None
    ) -> None:
        startup = self._startups.get(lease_id)
        if (
            self._stopping.is_set()
            or (startup is not None and startup.requested.is_set())
            or lease_id in self._sources
            or len(self._sources) >= self._max_sources
        ):
            observe_failure(observe, "worker_prepare", "denied")
            raise MediaDenied()
        closed = startup.closed if startup is not None else threading.Event()
        requested = threading.Event()
        gate = threading.Lock()
        self._runtime_closed[lease_id] = closed
        registration = None if startup is None else startup.registration
        receipt = None
        authority = object()

        def retirement_check() -> bool | ViewerCleanupReceipt | None:
            nonlocal receipt
            if closed.is_set():
                if self._source_factory is not None:
                    if registration is None:
                        return None
                    if receipt is None:
                        receipt = ViewerCleanupReceipt(
                            lease_id=lease_id,
                            registration_id=registration,
                            decoder_settled=True,
                            peer_settled=True,
                            media_cleared=True,
                            _authority=authority,
                            _seal=_CUSTODY_SEAL,
                        )
                    return receipt
                return True
            with gate:
                if not requested.is_set():
                    requested.set()
                    self._loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self._close_entry(lease_id))
                    )
            return None if self._source_factory is not None else False

        def mux_retirement() -> ViewerCleanupReceipt | None:
            result = retirement_check()
            return result if type(result) is ViewerCleanupReceipt else None

        stage = "retirement_attach"
        try:
            if self._source_factory is not None:
                if startup is None:
                    registration = await asyncio.to_thread(
                        self._source_factory.executor.registration, lease_id
                    )
                    await asyncio.to_thread(
                        self._source_factory.executor.attach_retirement,
                        lease_id,
                        mux_retirement,
                    )
            else:
                if isinstance(self.executor, MuxMediaExecutor):
                    raise MediaDenied()
                await asyncio.to_thread(
                    self.executor.attach_retirement,
                    lease_id,
                    lambda: retirement_check() is True,
                )
            stage = "proof_read"
            if self._source_factory is not None:
                proof = await asyncio.to_thread(
                    self._source_factory.executor.binding_proof, lease_id
                )
            else:
                proof = await asyncio.to_thread(self.executor.proof, lease_id)
            if (
                self._stopping.is_set()
                or lease_id in self._closing
                or self._runtime_closed.get(lease_id) is not closed
                or lease_id in self._sources
                or len(self._sources) >= self._max_sources
            ):
                # Retired or capped while those calls were pending: never
                # start a source; registration below is not interleaved.
                observe_failure(observe, "worker_prepare", "denied")
                raise MediaDenied()
            stage = "source_create"
            if self._source_factory is not None:
                source = await self._source_factory(
                    lease_id, self.decoder_executable, proof=proof, observe=observe
                )
                if (
                    self._stopping.is_set()
                    or closed.is_set()
                    or lease_id in self._closing
                    or self._runtime_closed.get(lease_id) is not closed
                    or lease_id in self._sources
                    or len(self._sources) >= self._max_sources
                ):
                    await source.close()
                    raise MediaDenied()
            else:
                options: dict[str, Any] = (
                    {"observe": observe} if observe is not None else {}
                )
                source = NativeDecodedSource(
                    self.executor,
                    lease_id,
                    self.decoder_executable,
                    proof=proof,
                    **options,
                )
            self._sources[lease_id] = source
            stage = "source_start"
            source.start()
            stage = "binding"
            binding = await source.binding()
            stage = "prepare_lease"
            lease = await asyncio.to_thread(self.executor.lease, lease_id)
            remaining = (lease.expires_at - datetime.now(UTC)).total_seconds()
            stage = "peer_create"
            self._peers[lease_id] = LocalWebRtcSession(
                binding=binding,
                source=source,
                current=source.alive,
                permitted=source.transport_current,
                expires_at=time.monotonic() + min(remaining, 29.9),
                observe=observe,
                media_credit=self._source_factory.credit
                if self._source_factory is not None
                else None,
                registration=registration,
            )
            observe_failure(observe, "milestone", "peer_created")
        except BaseException as error:
            observe_failure(observe, stage, failure_reason(error))
            if startup is None:
                await asyncio.shield(self._close_entry(lease_id))
            raise

    def offer(
        self,
        ticket: str,
        *,
        offer: LocalLiveOfferRequest,
        deadline_ms: int,
        correlation_id: str,
        cancel: threading.Event | None = None,
    ) -> LocalLiveOfferResponse:
        budget = LocalVerifyBudget(deadline_ms, cancel=cancel)
        lease_id = self.executor.authorize_control(
            ticket, "offer", deadline_ms=budget.remaining_ms(), cancel=budget.cancel
        )
        try:
            result = self._await(self._offer(lease_id, offer), budget)
            budget.remaining_ms()
            return LocalLiveOfferResponse(
                type="answer", sdp=result.sdp, request_id=correlation_id
            )
        except Exception as error:  # noqa: BLE001 -- fixed media signaling boundary
            asyncio.run_coroutine_threadsafe(self._close_entry(lease_id), self._loop)
            if isinstance(error, LocalDeviceFailure):
                raise LocalDeviceFailure(error.code, error.status) from None
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502) from None

    async def _offer(self, lease_id: UUID, offer: LocalLiveOfferRequest) -> Any:
        peer = self._peers.get(lease_id)
        if peer is None or self._stopping.is_set():
            raise SignalingDenied()
        return await peer.answer(offer.sdp, str(offer.offer_id))

    def stop(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: threading.Event | None = None,
    ) -> LocalLiveResponse:
        budget = LocalVerifyBudget(deadline_ms, cancel=cancel)
        lease_id = self.executor.authorize_control(
            ticket,
            "stop",
            deadline_ms=budget.remaining_ms(),
            cancel=budget.cancel,
        )
        self._await(self._close_entry(lease_id), budget)
        budget.remaining_ms()
        return self.executor.finish_stop(lease_id, correlation_id=correlation_id)

    def playing(
        self,
        ticket: str,
        *,
        started: LocalLiveStartedRequest,
        deadline_ms: int,
        correlation_id: str,
        cancel: threading.Event | None = None,
    ) -> LocalLiveResponse:
        budget = LocalVerifyBudget(deadline_ms, cancel=cancel)
        lease_id = self.executor.authorize_control(
            ticket, "playing", deadline_ms=budget.remaining_ms(), cancel=budget.cancel
        )
        value = self._await(self._browser_received(lease_id, started), budget)
        budget.remaining_ms()
        return LocalLiveResponse(lease=value, request_id=correlation_id)

    async def _browser_received(
        self, lease_id: UUID, started: LocalLiveStartedRequest
    ) -> Any:
        peer, source = self._peers.get(lease_id), self._sources.get(lease_id)
        if (
            type(started) is not LocalLiveStartedRequest
            or peer is None
            or source is None
            or lease_id in self._closing
            or peer.peer.connectionState != "connected"
            or source.produced_frames < 1
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)

        def same() -> bool:
            return (
                lease_id not in self._closing
                and self._peers.get(lease_id) is peer
                and self._sources.get(lease_id) is source
                and peer.peer.connectionState == "connected"
            )

        if not await asyncio.to_thread(source.current) or not same():
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        value = await asyncio.to_thread(
            self.executor.playing, lease_id, source.adapter.proof
        )
        if not same():
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return value

    async def _close_entry(self, lease_id: UUID) -> None:
        if lease_id in self._quarantined:
            return
        if lease_id in self._closing:
            await asyncio.shield(self._closing[lease_id])
            return
        startup = self._startups.get(lease_id)
        if startup is not None:
            startup.requested.set()
        source = self._sources.get(lease_id)
        peer = self._peers.get(lease_id)
        closed = self._runtime_closed.get(lease_id)
        if source is None and peer is None and closed is None:
            return

        async def retire() -> None:
            try:
                if startup is not None:
                    while not startup.prepared.is_set():
                        await asyncio.sleep(0.01)
                # Preparation may have retained an original after close began.
                source = self._sources.get(lease_id)
                peer = self._peers.get(lease_id)
                if peer is not None:
                    try:
                        await peer.close()
                        if self._source_factory is not None:
                            await peer.wait_closed()
                    except MediaDenied:
                        # Settle the same original objects after a reported
                        # timeout; never recreate or re-close an owner.
                        # wait_closed fires only after both original tasks.
                        if source is not None:
                            await source.close()
                        with suppress(MediaDenied):
                            await peer.wait_closed()
                        if peer.original_close_failed:
                            # Settled, but an original owner failed to close:
                            # keep custody (and the cap), never confirm it.
                            self._quarantined.add(lease_id)
                            return
                elif source is not None:
                    await source.close()
                if closed is not None:
                    closed.set()
                # Unconfirmed SQL closure: back off 50 ms doubling to 1 s; the
                # executor's own sweep also retries, so never spin at 20 Hz.
                delay = 0.05
                while not await asyncio.to_thread(self.executor.close, lease_id):
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 1.0)
                self._peers.pop(lease_id, None)
                self._sources.pop(lease_id, None)
                self._runtime_closed.pop(lease_id, None)
                self._startups.pop(lease_id, None)
            finally:
                self._closing.pop(lease_id, None)

        task = asyncio.create_task(retire())
        self._closing[lease_id] = task
        await asyncio.shield(task)

    async def _watch(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(1)
            for lease_id in tuple(self._sources):
                if lease_id in self._quarantined:
                    continue
                observe = None
                stage = "worker_watch"
                try:
                    source = self._sources.get(lease_id)
                    if source is None:
                        continue
                    observe = getattr(source, "_observe", None)
                    if not await asyncio.to_thread(source.current):
                        observe_failure(observe, stage, "current_false")
                        raise MediaDenied()
                    if self._peers.get(lease_id) is not None:
                        stage = "worker_lease"
                        lease = await asyncio.to_thread(self.executor.lease, lease_id)
                        peer = self._peers.get(lease_id)
                        if peer is not None:
                            left = (
                                lease.expires_at - datetime.now(UTC)
                            ).total_seconds()
                            stage = "worker_renew"
                            peer.renew(time.monotonic() + min(left, 29.9))
                except Exception as error:  # noqa: BLE001 -- authority failure closes original media
                    observe_failure(observe, stage, failure_reason(error))
                    try:
                        await self._close_entry(lease_id)
                    except Exception:  # noqa: BLE001, S112 -- custody kept; next pass retries
                        continue

    async def _shutdown(self) -> bool:
        if self._monitor is not None:
            self._monitor.cancel()
            await asyncio.gather(self._monitor, return_exceptions=True)
        for lease_id in tuple(self._runtime_closed):
            await self._close_entry(lease_id)
        return (
            not self._quarantined
            and not self._sources
            and not self._closing
            and not self._runtime_closed
        )

    def shutdown(self) -> bool:
        self._stopping.set()
        with self._guard:
            if self._inflight:
                return False
        if not self._construction_done.is_set():
            return False
        if (
            self._loop is not self._original_loop
            or self._thread is not self._original_thread
        ):
            return False
        if not self._start_attempted:
            return self._close_original_loop() and self._close_executor()
        if self._thread_exited.is_set():
            if self._runtime_ready:
                if self._shutdown_future is None or not self._shutdown_future.done():
                    return False
                try:
                    if self._shutdown_future.result() is not True:
                        return False
                except BaseException:  # noqa: BLE001 -- a dead loop cannot certify unfinished async disposal.
                    return False
            if (
                self._sources
                or self._peers
                or self._closing
                or self._runtime_closed
                or self._quarantined
            ):
                return False
            if not self._close_original_loop():
                return False
            self._thread.join(timeout=2)
            return not self._thread.is_alive() and self._close_executor()
        # Interrupted start can still enter later. Neither ident absence nor
        # is_alive(False) establishes that no original thread was acquired.
        if not self._thread_entered.is_set() or not self._runtime_ready:
            return False
        if self._shutdown_future is None:
            self._shutdown_future = asyncio.run_coroutine_threadsafe(
                self._shutdown(), self._loop
            )
        if not self._shutdown_future.done():
            return False
        try:
            closed = self._shutdown_future.result()
        except Exception:  # noqa: BLE001 -- retain uncertain cleanup for another attempt
            self._shutdown_future = None
            return False
        if not closed or not self._close_executor():
            return False
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
        return (
            not self._thread.is_alive()
            and self._thread_exited.is_set()
            and self._loop_closed.is_set()
        )
