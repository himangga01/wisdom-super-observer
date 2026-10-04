"""Owned synchronous RPC facade over the private native/decoder/WebRTC pipeline."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
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
from wso_core.tvt.local_media_service import LocalMediaExecutor
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget

from .codec import MediaDenied
from .live import LocalWebRtcSession
from .native_source import NativeDecodedSource
from .signaling import SignalingDenied


class LocalMediaWorker:
    def __init__(
        self, executor: LocalMediaExecutor, *, decoder_executable: Path
    ) -> None:
        if not decoder_executable.is_absolute() or not decoder_executable.is_file():
            raise LocalDeviceFailure()
        self.executor, self.decoder_executable = executor, decoder_executable
        self._loop = asyncio.new_event_loop()
        self._sources: dict[UUID, NativeDecodedSource] = {}
        self._peers: dict[UUID, LocalWebRtcSession] = {}
        self._closing: dict[UUID, asyncio.Task[None]] = {}
        self._runtime_closed: dict[UUID, threading.Event] = {}
        # An original close owner failed: custody is kept and never confirmed.
        self._quarantined: set[UUID] = set()
        self._stopping = threading.Event()
        self._ready = threading.Event()
        self._guard = threading.Lock()
        self._inflight = 0
        self._shutdown_future: concurrent.futures.Future[bool] | None = None

        def run() -> None:
            asyncio.set_event_loop(self._loop)
            self._monitor = self._loop.create_task(self._watch())
            self._ready.set()
            self._loop.run_forever()
            self._loop.close()

        self._thread = threading.Thread(
            target=run, name="local-media-loop-owner", daemon=False
        )
        self._thread.start()
        if not self._ready.wait(5):
            raise LocalDeviceFailure()

    def _await(self, operation: Any, budget: LocalVerifyBudget) -> Any:
        future = asyncio.run_coroutine_threadsafe(operation, self._loop)
        try:
            while True:
                budget.remaining_ms()
                try:
                    return future.result(timeout=0.025)
                except concurrent.futures.TimeoutError:
                    continue
        except BaseException:
            future.cancel()
            raise

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
            if self._stopping.is_set():
                raise LocalDeviceFailure()
            self._inflight += 1
        result = None
        try:
            result = self.executor.start(
                ticket,
                deadline_ms=budget.remaining_ms(),
                correlation_id=correlation_id,
                cancel=budget.cancel,
            )
            self._await(self._prepare(result.lease.id), budget)
            budget.remaining_ms()
            return result
        except Exception as error:  # noqa: BLE001 -- normalize private startup failures
            if result is not None:
                self.executor.close(result.lease.id)
            if isinstance(error, LocalDeviceFailure):
                raise LocalDeviceFailure(error.code, error.status) from None
            raise LocalDeviceFailure() from None
        finally:
            with self._guard:
                self._inflight -= 1

    async def _prepare(self, lease_id: UUID) -> None:
        if (
            self._stopping.is_set()
            or lease_id in self._sources
            or len(self._sources) >= 2
        ):
            raise MediaDenied()
        closed = threading.Event()
        requested = threading.Event()
        gate = threading.Lock()
        self._runtime_closed[lease_id] = closed

        def retirement_check() -> bool:
            if closed.is_set():
                return True
            with gate:
                if not requested.is_set():
                    requested.set()
                    self._loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self._close_entry(lease_id))
                    )
            return False

        try:
            # SQL/native authority work never runs on the media event loop.
            await asyncio.to_thread(
                self.executor.attach_retirement, lease_id, retirement_check
            )
            proof = await asyncio.to_thread(self.executor.proof, lease_id)
            if (
                self._stopping.is_set()
                or lease_id in self._closing
                or self._runtime_closed.get(lease_id) is not closed
                or lease_id in self._sources
                or len(self._sources) >= 2
            ):
                # Retired or capped while those calls were pending: never
                # start a source; registration below is not interleaved.
                raise MediaDenied()
            source = NativeDecodedSource(
                self.executor, lease_id, self.decoder_executable, proof=proof
            )
            self._sources[lease_id] = source
            source.start()
            binding = await source.binding()
            lease = await asyncio.to_thread(self.executor.lease, lease_id)
            remaining = (lease.expires_at - datetime.now(UTC)).total_seconds()
            self._peers[lease_id] = LocalWebRtcSession(
                binding=binding,
                source=source,
                current=source.alive,
                permitted=source.transport_current,
                expires_at=time.monotonic() + min(remaining, 29.9),
            )
        except BaseException:
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
        source = self._sources.get(lease_id)
        peer = self._peers.get(lease_id)
        closed = self._runtime_closed.get(lease_id)
        if source is None and peer is None and closed is None:
            return

        async def retire() -> None:
            try:
                if peer is not None:
                    try:
                        await peer.close()
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
                try:
                    source = self._sources.get(lease_id)
                    if source is None:
                        continue
                    if not await asyncio.to_thread(source.current):
                        raise MediaDenied()
                    if self._peers.get(lease_id) is not None:
                        lease = await asyncio.to_thread(self.executor.lease, lease_id)
                        peer = self._peers.get(lease_id)
                        if peer is not None:
                            left = (
                                lease.expires_at - datetime.now(UTC)
                            ).total_seconds()
                            peer.renew(time.monotonic() + min(left, 29.9))
                except Exception:  # noqa: BLE001 -- authority failure closes original media
                    try:
                        await self._close_entry(lease_id)
                    except Exception:  # noqa: BLE001, S112 -- custody kept; next pass retries
                        continue

    async def _shutdown(self) -> bool:
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
        if not self._thread.is_alive():
            return True
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
        if not closed or not self.executor.shutdown():
            return False
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
        return not self._thread.is_alive()
