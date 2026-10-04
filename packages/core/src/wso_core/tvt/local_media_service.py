"""Credential-free original-session ownership with fresh media authority."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, RLock, Thread
from typing import Protocol
from uuid import UUID

from wso_contracts.tvt.local_media import LocalLiveResponse
from wso_contracts.tvt.media import MediaLease

from .local_credentials import LocalDeviceCredentials
from .local_live import PrivateLiveFrame
from .local_service import LocalDeviceFailure, LocalVerifyBudget

# Preserve the established fixed public error vocabulary for API/RPC callers.
LocalMediaFailure = LocalDeviceFailure


@dataclass(frozen=True, slots=True, repr=False)
class LocalMediaChannel:
    guid: bytes
    raw_index: int
    window_index: int
    ordinal: int
    kind: str
    stream: str = "main"


@dataclass(frozen=True, slots=True)
class LocalLiveProof:
    login_accepted: bool
    same_original_session: bool
    serial_matched: bool
    channel_matched: bool
    live_permission: bool
    codec_supported: bool = False
    framing_verified: bool = False
    timing_verified: bool = False
    codec: str | None = None

    def validate(self, *, delivery: bool = False) -> None:
        flags = (
            self.login_accepted,
            self.same_original_session,
            self.serial_matched,
            self.channel_matched,
            self.live_permission,
            self.codec_supported,
            self.framing_verified,
            self.timing_verified,
        )
        if any(type(flag) is not bool for flag in flags) or not all(flags[:5]):
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        if self.codec is not None and self.codec not in {"h264", "hevc"}:
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        if delivery and (not all(flags) or self.codec is None):
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)


class OwnedLocalLiveSession(Protocol):
    proof: LocalLiveProof

    def current(
        self, *, deadline_monotonic: float, current: Callable[[], bool]
    ) -> bool: ...

    def read_frames(
        self,
        *,
        max_frames: int,
        max_bytes: int,
        deadline_monotonic: float,
        current: Callable[[], bool],
    ) -> tuple[PrivateLiveFrame, ...]: ...
    def close(self) -> bool: ...


class LocalLiveProvider(Protocol):
    def open_session(
        self,
        credentials: LocalDeviceCredentials,
        selection: LocalMediaChannel,
        *,
        deadline_monotonic: float,
        current: Callable[[], bool],
        cancel: Event,
    ) -> OwnedLocalLiveSession: ...


class LocalMediaAdmissionPort(Protocol):
    def redeem(self, ticket: str, *, budget: LocalVerifyBudget) -> object: ...
    def open(
        self,
        lease: object,
        callback: Callable[
            [LocalDeviceCredentials, LocalMediaChannel, Callable[[], bool]],
            OwnedLocalLiveSession,
        ],
        *,
        budget: LocalVerifyBudget,
    ) -> OwnedLocalLiveSession: ...
    def activate(
        self, lease: object, proof: LocalLiveProof, *, budget: LocalVerifyBudget
    ) -> MediaLease: ...
    def current(self, lease: object) -> bool: ...
    def view(self, lease: object) -> MediaLease: ...
    def playing(self, lease: object, proof: LocalLiveProof) -> MediaLease: ...
    def close(self, lease: object, *, cleanup_confirmed: bool) -> None: ...
    def redeem_control(
        self, ticket: str, purpose: str, *, budget: LocalVerifyBudget
    ) -> UUID: ...
    def retry_cleanup(self) -> bool: ...


@dataclass(slots=True)
class _Owned:
    lease: object
    session: OwnedLocalLiveSession
    view: MediaLease
    stopping: bool = False
    retirement_check: Callable[[], bool] | None = None
    lock: RLock = field(default_factory=RLock)


class LocalMediaExecutor:
    """Each lease owns one original native session; no reuse or pooling.

    monitor_interval=0 permits an external scheduler to call sweep explicitly.
    Production default is a one-second revocation monitor. A failed SQL check
    closes resources; uncertain native cleanup leaves SQL state STOPPING.
    """

    def __init__(
        self,
        admission: LocalMediaAdmissionPort,
        provider: LocalLiveProvider | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        monitor_interval: float = 1.0,
    ) -> None:
        if not 0 <= monitor_interval <= 1:
            raise ValueError("invalid local media monitor interval")
        self.admission, self.provider, self._clock = admission, provider, clock
        self._owned: dict[UUID, _Owned] = {}
        self._closed: dict[UUID, MediaLease] = {}
        self._retiring: list[tuple[object, OwnedLocalLiveSession | None]] = []
        self._retiring_inflight: dict[
            object, tuple[object, OwnedLocalLiveSession | None]
        ] = {}
        self._starting = 0
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        if monitor_interval:

            def monitor() -> None:
                while not self._stop.wait(monitor_interval):
                    self.sweep()

            self._thread = Thread(
                target=monitor, daemon=True, name="local-media-authority"
            )
            self._thread.start()

    @staticmethod
    def _input(ticket: str, correlation_id: str) -> None:
        if (
            type(ticket) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", ticket)
            or type(correlation_id) is not str
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", correlation_id)
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)

    def start(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: Event | None = None,
    ) -> LocalLiveResponse:
        self._input(ticket, correlation_id)
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock, cancel=cancel)
        budget.remaining_ms()
        if self.provider is None or self._stop.is_set():
            raise LocalDeviceFailure()
        with self._lock:
            if self._stop.is_set():
                raise LocalDeviceFailure()
            self._starting += 1
        lease: object | None = None
        session: OwnedLocalLiveSession | None = None
        try:
            lease = self.admission.redeem(ticket, budget=budget)

            def opened(
                credentials: LocalDeviceCredentials,
                channel: LocalMediaChannel,
                current: Callable[[], bool],
            ) -> OwnedLocalLiveSession:
                nonlocal session

                def allowed() -> bool:
                    budget.remaining_ms()
                    return current()

                if not allowed():
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                assert self.provider is not None
                session = self.provider.open_session(
                    credentials,
                    channel,
                    deadline_monotonic=budget.deadline_monotonic,
                    current=allowed,
                    cancel=budget.cancel,
                )
                if not allowed():
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                if type(session.proof) is not LocalLiveProof:
                    raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
                session.proof.validate()
                return session

            session = self.admission.open(lease, opened, budget=budget)
            view = self.admission.activate(lease, session.proof, budget=budget)
            budget.remaining_ms()
            if view.state != "NEGOTIATING" or not self.admission.current(lease):
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            with self._lock:
                if self._stop.is_set() or view.id in self._owned:
                    raise LocalDeviceFailure()
                self._owned[view.id] = _Owned(lease, session, view)
            budget.remaining_ms()
            return LocalLiveResponse(lease=view, request_id=correlation_id)
        except BaseException as exc:
            if lease is not None:
                with self._lock:
                    registered = next(
                        (
                            key
                            for key, value in self._owned.items()
                            if value.lease is lease
                        ),
                        None,
                    )
                if registered is not None:
                    # Even a late start failure must respect any registered
                    # original media-resource barrier before SQL retirement.
                    self.close(registered)
                elif not self._retire(lease, session):
                    with self._lock:
                        self._retiring.append((lease, session))
            if isinstance(exc, LocalDeviceFailure):
                raise LocalDeviceFailure(exc.code, exc.status) from None
            if not isinstance(exc, Exception):
                raise
            raise LocalDeviceFailure() from None
        finally:
            with self._lock:
                self._starting -= 1

    def _retire(
        self,
        lease: object,
        session: OwnedLocalLiveSession | None,
        check: Callable[[], bool] | None = None,
    ) -> bool:
        confirmed = session is None
        if session is not None:
            try:
                confirmed = session.close() is True
            except Exception:  # noqa: BLE001 -- uncertain native cleanup stays pending.
                confirmed = False
        external_confirmed = check is None
        if check is not None:
            try:
                # Always trigger original media cleanup, even when native
                # close is uncertain. The callback only schedules/checks;
                # it must never block or authorize additional work.
                external_confirmed = check() is True
            except Exception:  # noqa: BLE001 -- unsettled media owner stays STOPPING.
                external_confirmed = False
        confirmed = confirmed and external_confirmed
        try:
            self.admission.close(lease, cleanup_confirmed=confirmed)
        except Exception:  # noqa: BLE001 -- failed SQL cleanup cannot establish closure.
            return False
        return confirmed

    def current(self, lease_id: UUID) -> bool:
        with self._lock:
            owned = self._owned.get(lease_id)
        if owned is None or owned.stopping or self._stop.is_set():
            return False
        try:
            accepted = self.admission.current(owned.lease) is True
            with self._lock:
                return (
                    accepted
                    and self._owned.get(lease_id) is owned
                    and not owned.stopping
                    and not self._stop.is_set()
                )
        except Exception:  # noqa: BLE001 -- fresh authority failure denies delivery.
            return False

    def _get(self, lease_id: UUID) -> _Owned:
        with self._lock:
            owned = self._owned.get(lease_id)
        if owned is None or not self.current(lease_id):
            self.close(lease_id)
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return owned

    def lease(self, lease_id: UUID) -> MediaLease:
        return self.admission.view(self._get(lease_id).lease)

    def proof(self, lease_id: UUID) -> LocalLiveProof:
        proof = self._get(lease_id).session.proof
        if type(proof) is not LocalLiveProof:
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        proof.validate()
        self._get(lease_id)
        return proof

    def attach_retirement(self, lease_id: UUID, check: Callable[[], bool]) -> None:
        if type(lease_id) is not UUID or not callable(check):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        with self._lock:
            owned = self._owned.get(lease_id)
        if owned is None:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        with owned.lock:
            with self._lock:
                if (
                    self._owned.get(lease_id) is not owned
                    or owned.stopping
                    or self._stop.is_set()
                ):
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                if owned.retirement_check is not None:
                    raise LocalDeviceFailure("LOCAL_DEVICE_GENERATION_CONFLICT", 409)
            if not self.current(lease_id):
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            with self._lock:
                if (
                    self._owned.get(lease_id) is not owned
                    or owned.stopping
                    or self._stop.is_set()
                ):
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                owned.retirement_check = check

    def read_frames(
        self, lease_id: UUID, *, max_frames: int, max_bytes: int, deadline_ms: int
    ) -> tuple[PrivateLiveFrame, ...]:
        if (
            type(max_frames) is not int
            or not 1 <= max_frames <= 16
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= 8 * 1024 * 1024
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock)
        owned = self._get(lease_id)

        def allowed() -> bool:
            budget.remaining_ms()
            return self.current(lease_id)

        try:
            frames = owned.session.read_frames(
                max_frames=max_frames,
                max_bytes=max_bytes,
                deadline_monotonic=budget.deadline_monotonic,
                current=allowed,
            )
            if not allowed():
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            if (
                type(frames) is not tuple
                or len(frames) > max_frames
                or any(type(frame) is not PrivateLiveFrame for frame in frames)
                or sum(len(frame.private_bytes()) for frame in frames) > max_bytes
            ):
                raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
            return frames
        except BaseException as exc:
            self.close(lease_id)
            if isinstance(exc, LocalDeviceFailure):
                raise LocalDeviceFailure(exc.code, exc.status) from None
            if not isinstance(exc, Exception):
                raise
            raise LocalDeviceFailure() from None

    def authorize_control(
        self,
        ticket: str,
        purpose: str,
        *,
        deadline_ms: int,
        cancel: Event | None = None,
    ) -> UUID:
        self._input(ticket, "control")
        if purpose not in {"offer", "stop", "playing"}:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock, cancel=cancel)
        lease_id = self.admission.redeem_control(ticket, purpose, budget=budget)
        if purpose in {"offer", "playing"}:
            self._get(lease_id)
        budget.remaining_ms()
        return lease_id

    def playing(self, lease_id: UUID, proof: LocalLiveProof) -> MediaLease:
        proof.validate(delivery=True)
        return self.admission.playing(self._get(lease_id).lease, proof)

    def stop(
        self,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: Event | None = None,
    ) -> LocalLiveResponse:
        self._input(ticket, correlation_id)
        budget = LocalVerifyBudget(deadline_ms, clock=self._clock, cancel=cancel)
        lease_id = self.authorize_control(
            ticket, "stop", deadline_ms=budget.remaining_ms(), cancel=cancel
        )
        response = self.finish_stop(lease_id, correlation_id=correlation_id)
        budget.remaining_ms()
        return response

    def finish_stop(self, lease_id: UUID, *, correlation_id: str) -> LocalLiveResponse:
        """Private completion port; caller derives this ID from its stop ticket."""
        if (
            type(lease_id) is not UUID
            or type(correlation_id) is not str
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", correlation_id)
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        with self._lock:
            owned = self._owned.get(lease_id)
            closed = self._closed.get(lease_id)
        if owned is None:
            if closed is not None:
                return LocalLiveResponse(lease=closed, request_id=correlation_id)
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        if not self.close(lease_id):
            raise LocalDeviceFailure()
        view = owned.view.model_copy(update={"state": "CLOSED"})
        return LocalLiveResponse(lease=view, request_id=correlation_id)

    def close(self, lease_id: UUID) -> bool:
        with self._lock:
            owned = self._owned.get(lease_id)
        if owned is None:
            return True
        with owned.lock:
            with self._lock:
                if self._owned.get(lease_id) is not owned:
                    return True
                owned.stopping = True
            confirmed = self._retire(owned.lease, owned.session, owned.retirement_check)
            if confirmed:
                with self._lock:
                    self._owned.pop(lease_id, None)
                    self._closed[lease_id] = owned.view.model_copy(
                        update={"state": "CLOSED"}
                    )
                    while len(self._closed) > 32:
                        self._closed.pop(next(iter(self._closed)))
            return confirmed

    def _retry_retiring(self) -> bool:
        with self._lock:
            retiring, self._retiring = self._retiring, []
            batch = [(object(), pair) for pair in retiring]
            self._retiring_inflight.update(batch)
        try:
            for key, (lease, session) in batch:
                settled = False
                try:
                    # Native/SQL work runs outside the ownership lock, while
                    # the exact binding remains globally visible to shutdown.
                    settled = self._retire(lease, session)
                finally:
                    with self._lock:
                        owner = self._retiring_inflight.pop(key)
                        if not settled:
                            self._retiring.append(owner)
        finally:
            # An interruption must retain unprocessed original owners too.
            with self._lock:
                for key, _ in batch:
                    unprocessed_owner = self._retiring_inflight.pop(key, None)
                    if unprocessed_owner is not None:
                        self._retiring.append(unprocessed_owner)
        with self._lock:
            return not self._retiring and not self._retiring_inflight

    def sweep(self) -> None:
        self._retry_retiring()
        with self._lock:
            keys = tuple(self._owned)
        for key in keys:
            if not self.current(key):
                self.close(key)
                continue
            with self._lock:
                owned = self._owned.get(key)
            if owned is None:
                continue
            media_binding = owned.lease

            def media_current(binding: object = media_binding) -> bool:
                return self.admission.current(binding)

            try:
                # Renewal checks fresh SQL and only extends an unexpired native
                # owner. This callback is independent of the startup transaction.
                accepted = owned.session.current(
                    deadline_monotonic=self._clock() + 30,
                    current=media_current,
                )
            except Exception:  # noqa: BLE001 -- unavailable native owner denies media.
                accepted = False
            if accepted is not True:
                self.close(key)
        self.admission.retry_cleanup()

    def shutdown(self) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        with self._lock:
            keys = tuple(self._owned)
        for key in keys:
            self.close(key)
        self._retry_retiring()
        admission_settled = self.admission.retry_cleanup()
        with self._lock:
            return (
                admission_settled
                and not self._owned
                and not self._retiring
                and not self._retiring_inflight
                and self._starting == 0
                and (self._thread is None or not self._thread.is_alive())
            )
