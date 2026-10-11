"""Bounded raw-mux probe invoked only by an already admitted owned runtime."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from wso_contracts.tvt.local_media import LocalLiveRequest
from wso_core.tvt.local_media_mux_types import _CUSTODY_SEAL, ViewerCleanupReceipt
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget
from wso_core.tvt.windows_decode import ElementaryPacket


@dataclass(frozen=True, slots=True)
class MuxProbePlan:
    channels: tuple[int, ...]
    max_seconds: int

    def __post_init__(self) -> None:
        if (
            type(self.channels) is not tuple
            or len(self.channels) not in (2, 4)
            or any(
                type(channel) is not int or not 1 <= channel <= 256
                for channel in self.channels
            )
            or len(set(self.channels)) != len(self.channels)
            or type(self.max_seconds) is not int
            or not 1 <= self.max_seconds <= 120
        ):
            raise ValueError("bounded mux probe plan refused")


class ProbeViewerOwner:
    """Raw-only media custody. This profile never constructs a decoder or peer.

    Retain this exact owner before native startup, then bind before reading.
    A controller timeout never clears its in-flight operation, original batches,
    uncertainty or native ownership.
    """

    def __init__(
        self, executor: Any, lease_id: UUID, registration: UUID, handle: Any = None
    ) -> None:
        if type(lease_id) is not UUID or type(registration) is not UUID:
            raise ValueError("probe owner refused")
        self.executor, self.lease_id = executor, lease_id
        self.handle: Any = None
        self.registration = registration
        self._lock = threading.RLock()
        self._reading = self._stopping = self._uncertain = False
        self._read_attempted = False
        self._binding_attempted = False
        self._batches: dict[int, tuple[Any, ...]] = {}
        self._receipt: ViewerCleanupReceipt | None = None
        self._authority = object()
        self.original_retire = self._retire
        if handle is not None:
            self.bind(handle, registration)

    def begin_binding(self) -> None:
        with self._lock:
            if (
                self._binding_attempted
                or self.handle is not None
                or self._stopping
                or self._uncertain
            ):
                self._uncertain = True
                raise ValueError("probe binding preparation refused")
            self._binding_attempted = True

    def bind(self, handle: Any, registration: UUID) -> None:
        with self._lock:
            self._binding_attempted = True
            if (
                self.handle is not None
                or self._stopping
                or self._uncertain
                or type(registration) is not UUID
                or registration != self.registration
                or getattr(handle, "registration", None) != self.registration
            ):
                self._uncertain = True
                raise ValueError("original probe binding required")
            self.handle = handle

    def begin_read(self) -> None:
        with self._lock:
            self._read_attempted = True
            if (
                self.handle is None
                or self._stopping
                or self._reading
                or self._uncertain
                or self.handle.registration != self.registration
            ):
                self._uncertain = True
                raise ValueError("probe read refused")
            self._reading = True

    def returned(self, batch: tuple[Any, ...]) -> None:
        with self._lock:
            if (
                not self._reading
                or type(batch) is not tuple
                or id(batch) in self._batches
            ):
                self._uncertain = True
                raise ValueError("probe read ownership refused")
            if batch:
                self._batches[id(batch)] = batch
            self._reading = False

    def read_failed(self) -> None:
        with self._lock:
            self._reading = False
            self._uncertain = True

    def release(self, batch: tuple[Any, ...]) -> None:
        if not batch:
            return
        with self._lock:
            if self._batches.get(id(batch)) is not batch:
                raise ValueError("original probe batch required")
            try:
                self.executor.release_mux_frames(self.lease_id, batch)
            except BaseException:
                self._uncertain = True
                raise
            del self._batches[id(batch)]

    def _retire(self) -> ViewerCleanupReceipt | None:
        with self._lock:
            self._stopping = True
            if (
                self._reading
                or self._batches
                or self._uncertain
                or (
                    self.handle is None
                    and (self._read_attempted or self._binding_attempted)
                )
                or (
                    self.handle is not None
                    and self.handle.registration != self.registration
                )
            ):
                return None
            if self._receipt is None:
                self._receipt = ViewerCleanupReceipt(
                    lease_id=self.lease_id,
                    registration_id=self.registration,
                    decoder_settled=True,
                    peer_settled=True,
                    media_cleared=True,
                    _authority=self._authority,
                    _seal=_CUSTODY_SEAL,
                )
            return self._receipt


class SqlProbeTickets:
    """Use the reviewed issuer inside caller-owned authenticated transactions.

    The context manager must commit/release the tenant transaction before it
    exits. No transaction or checkout remains held across a native operation.
    This adapter does not read configuration, make grants or execute raw SQL.
    """

    def __init__(
        self,
        transaction: Callable[[], AbstractContextManager[Any]],
        session_digest: str,
        connection_id: UUID,
        tenant_id: UUID,
    ) -> None:
        self._transaction, self._digest = transaction, session_digest
        self._connection, self._tenant = connection_id, tenant_id

    def _call(self, name: str, budget: LocalVerifyBudget, *args: Any) -> Any:
        from wso_api.tvt.local_media_mux import LocalMuxTicketIssuer

        budget.remaining_ms()
        with self._transaction() as session:
            issuer = LocalMuxTicketIssuer(session, budget.remaining_ms)
            result = getattr(issuer, name)(self._digest, *args)
        budget.remaining_ms()
        return result

    def wall(self, budget: LocalVerifyBudget) -> UUID:
        from wso_api.tvt.local_media_mux import public_wall

        return public_wall(self._call("issue_wall", budget), self._tenant).id

    def start(
        self, request: LocalLiveRequest, wall: UUID, budget: LocalVerifyBudget
    ) -> str:
        if (
            type(request) is not LocalLiveRequest
            or request.stream != "sub"
            or request.focus_ref_id is not None
        ):
            raise ValueError("probe substream selector required")
        selected = LocalLiveRequest.model_validate(
            request.model_dump() | {"wall_id": wall}
        )
        return str(self._call("issue_shared", budget, self._connection, selected))

    def control(self, wall: UUID, purpose: str, budget: LocalVerifyBudget) -> str:
        if purpose not in {"heartbeat", "stop"}:
            raise ValueError("probe control refused")
        return str(self._call("issue_wall_control", budget, wall, purpose))

    def state(self, wall: UUID, budget: LocalVerifyBudget) -> str:
        from wso_api.tvt.local_media_mux import public_wall

        return str(
            public_wall(self._call("read_wall", budget, wall), self._tenant, wall).state
        )


class MuxProbeRunner:
    """One admitted raw-only probe. Root owns source/native/profile approvals.

    Keep this runner and its executor alive after FAILED_RETAINED: they retain
    the exact original cleanup callbacks and any uncertain returned batches.
    The observer writer/terminal and runtime shutdown remain the caller's owners.
    """

    def __init__(
        self,
        executor: Any,
        tickets: SqlProbeTickets,
        observer: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
        pause: Callable[[float], None] = time.sleep,
    ) -> None:
        self.executor, self.tickets, self.observer = executor, tickets, observer
        self.clock, self.pause = clock, pause
        self.owners: dict[UUID, ProbeViewerOwner] = {}
        self._ran = False

    def _retain_local(
        self, lease_id: UUID, registration: UUID
    ) -> Callable[[], ViewerCleanupReceipt | None]:
        if lease_id in self.owners:
            raise ValueError("original probe owner already retained")
        owner = ProbeViewerOwner(self.executor, lease_id, registration)
        self.owners[lease_id] = owner
        return owner.original_retire

    def _budget(self, deadline: float, maximum_ms: int = 2000) -> LocalVerifyBudget:
        remaining = int((deadline - self.clock()) * 1000)
        if remaining < 1:
            raise LocalDeviceFailure("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504)
        return LocalVerifyBudget(min(maximum_ms, remaining), clock=self.clock)

    def _wire_ready(self, plan: MuxProbePlan, interval: object) -> bool:
        value = self.observer.mux_probe_snapshot(interval)
        mux = value.get("mux", {})
        slots = mux.get("slots", [])
        masters = mux.get("masters", [])
        return (
            value.get("schema_version") == 3
            and value.get("observation_failures") == 0
            and mux.get("omitted") == 0
            and len(masters) == 1
            and masters[0].get("login_proof") == "VERIFIED_RETURN"
            and {row.get("channel_ordinal") for row in slots} == set(plan.channels)
            and len(slots) == len(plan.channels)
            and all(
                row.get("wire", {}).get("status") == "OBSERVED"
                and row["wire"].get("ack") is not None
                and row["wire"].get("media") is not None
                for row in slots
            )
        )

    def run(
        self,
        plan: MuxProbePlan,
        requests: Mapping[int, LocalLiveRequest],
        *,
        cleanup_seconds: int = 30,
        prior_two_complete: bool = False,
    ) -> dict[str, Any]:

        if (
            type(plan) is not MuxProbePlan
            or self._ran
            or not self.observer.shared
            or type(cleanup_seconds) is not int
            or not 1 <= cleanup_seconds <= 120
            or type(prior_two_complete) is not bool
            or (len(plan.channels) == 4 and not prior_two_complete)
            or set(requests) != set(plan.channels)
            or any(
                type(request) is not LocalLiveRequest or request.stream != "sub"
                for request in requests.values()
            )
            or len({request.channel_id for request in requests.values()})
            != len(plan.channels)
            or len(
                {
                    (
                        request.store_id,
                        request.device_id,
                        request.expected_generation,
                        request.inventory_revision,
                    )
                    for request in requests.values()
                }
            )
            != 1
        ):
            raise ValueError("owned mux probe selection refused")
        interval = self.observer.begin_mux_probe(plan.channels)
        self._ran = True
        try:
            return self._run(plan, requests, cleanup_seconds, interval)
        finally:
            self.observer.end_mux_probe(interval)

    def _run(
        self,
        plan: MuxProbePlan,
        requests: Mapping[int, LocalLiveRequest],
        cleanup_seconds: int,
        interval: object,
    ) -> dict[str, Any]:
        from wso_tvt_bridge.local_live_mux_ipc import media_credit_usage
        from wso_tvt_media.native_source import NativeFrameAdapter, failure_reason

        started = self.clock()
        live_deadline = started + plan.max_seconds
        baseline = media_credit_usage()
        wall = None
        adapters: dict[UUID, NativeFrameAdapter] = {}
        counts: dict[UUID, int] = {}
        cuts: dict[UUID, Any] = {}
        streams: list[dict[str, Any]] = []
        native_slots = []
        packet: ElementaryPacket | None = None
        failure = None
        live_pass = False
        cleanup_confirmed = False
        closed = 0
        try:
            wall = self.tickets.wall(self._budget(live_deadline, 20000))
            for ordinal, channel in enumerate(plan.channels, 1):
                budget = self._budget(live_deadline, 20000)
                ticket = self.tickets.start(requests[channel], wall, budget)
                response = self.executor.start(
                    ticket,
                    deadline_ms=budget.remaining_ms(),
                    correlation_id=f"mux-probe-{ordinal}",
                    retain_local=self._retain_local,
                )
                lease = response.lease.id
                owner = self.owners[lease]
                owner.begin_binding()
                handle, grant = self.executor.mux_binding(lease)
                if grant.lease_id != lease:
                    raise ValueError("original probe lease required")
                owner.bind(handle, grant.registration)
                cuts[lease] = handle.cut
                self.observer.bind_mux_probe(interval, handle, grant.slot, handle.cut)
                native_slots.append(grant.slot)
                counts[lease] = 0
                streams.append(
                    {"ordinal": ordinal, "channel_ordinal": channel, "frames": 0}
                )
            if (
                len(set(native_slots)) != len(plan.channels)
                or len({slot.task for slot in native_slots}) != len(plan.channels)
                or len({slot.epoch for slot in native_slots}) != 1
            ):
                raise ValueError("one original distinct slots required")
            heartbeat = self.clock() + 10
            while not all(count >= 2 for count in counts.values()):
                self._budget(live_deadline)
                if self.clock() >= heartbeat:
                    budget = self._budget(live_deadline)
                    ticket = self.tickets.control(wall, "heartbeat", budget)
                    if (
                        self.executor.coordinator.heartbeat(ticket, budget=budget)
                        != wall
                    ):
                        raise ValueError("wall correlation refused")
                    heartbeat = self.clock() + 10
                for row, (lease, owner) in zip(
                    streams, self.owners.items(), strict=True
                ):
                    if counts[lease] >= 2:
                        continue
                    budget = self._budget(live_deadline)
                    handle, grant = self.executor.mux_binding(lease)
                    if (
                        handle is not owner.handle
                        or handle.cut is not cuts[lease]
                        or grant.registration != owner.registration
                    ):
                        raise ValueError("original viewer binding required")
                    owner.begin_read()
                    try:
                        frames = self.executor.read_mux_frames(
                            lease,
                            max_frames=1,
                            max_bytes=4 << 20,
                            deadline_ms=budget.remaining_ms(),
                        )
                        owner.returned(frames)
                    except BaseException:
                        owner.read_failed()
                        raise
                    try:
                        budget.remaining_ms()
                        for frame in frames:
                            if lease not in adapters:
                                # The raw probe does not bootstrap browser/media
                                # startup: actual proof is read after actual media.
                                adapters[lease] = NativeFrameAdapter(
                                    self.executor.proof(lease),
                                    allow_dimension_changes=True,
                                )
                            packet = adapters[lease].packet_mux(
                                frame, registration=owner.registration, cut=cuts[lease]
                            )
                            if not self.executor.current(lease):
                                raise ValueError("probe authority denied")
                            counts[lease] += 1
                            row.update(
                                frames=counts[lease],
                                codec=packet.codec,
                                width=packet.width,
                                height=packet.height,
                                last_slot_ordinal=frame.slot_ordinal,
                                last_ingress=frame.ingress.last,
                                last_elapsed_ms=max(
                                    0, int((self.clock() - started) * 1000)
                                ),
                            )
                            if counts[lease] == 1:
                                row.update(
                                    first_slot_ordinal=frame.slot_ordinal,
                                    first_ingress=frame.ingress.first,
                                    cut_after_ordinal=cuts[lease].after_ordinal,
                                    post_cut_key_verified=adapters[lease].random_access,
                                )
                    finally:
                        frame, packet = None, None
                        owner.release(frames)
                        frames = ()
                self.observer.sample_mux_credits()
            wire_ready = self._wire_ready(plan, interval)
            if not self.observer.mux_probe_current(interval):
                raise ValueError("current probe interval changed")
            self._budget(live_deadline)
            live_pass = wire_ready
            if not wire_ready:
                failure = "WIRE_EVIDENCE_UNAVAILABLE"
        except Exception as error:  # noqa: BLE001 -- only a closed reason leaves the owned probe.
            live_pass = False
            failure = failure_reason(error)
        finally:
            cleanup_deadline = self.clock() + cleanup_seconds
            if wall is not None:
                try:
                    budget = self._budget(cleanup_deadline)
                    ticket = self.tickets.control(wall, "stop", budget)
                    stopped, cleanup_confirmed = (
                        self.executor.coordinator.stop_wall_result(
                            ticket, budget=budget
                        )
                    )
                    if stopped != wall:
                        raise ValueError("cleanup wall mismatch")
                    while not cleanup_confirmed:
                        self.pause(min(0.05, max(0, cleanup_deadline - self.clock())))
                        cleanup_confirmed = self.executor.coordinator.stop_wall(
                            wall, budget=self._budget(cleanup_deadline)
                        )
                    for lease in self.owners:
                        self._budget(cleanup_deadline)
                        response = self.executor.finish_stop(
                            lease, correlation_id="mux-probe-stop"
                        )
                        closed += int(response.lease.state == "CLOSED")
                    cleanup_confirmed = (
                        closed == len(self.owners)
                        and self.tickets.state(wall, self._budget(cleanup_deadline))
                        == "CLOSED"
                        and media_credit_usage() == baseline
                    )
                except Exception:  # noqa: BLE001 -- timeout/unknown original remains retained.
                    cleanup_confirmed = False
            self.observer.sample_mux_credits()
        final_observation = self.observer.snapshot()
        if (
            final_observation.get("observation_failures") != 0
            or final_observation.get("mux", {}).get("omitted") != 0
            or not self.observer.mux_probe_current(interval)
        ):
            live_pass = False
            failure = "OBSERVATION_FAILED"
        if not cleanup_confirmed and failure is None:
            failure = "CLEANUP_RETAINED"
        return deepcopy(
            {
                "schema_version": 1,
                "status": "RAW_GATE_RETIRED"
                if live_pass and cleanup_confirmed
                else "FAILED"
                if cleanup_confirmed
                else "FAILED_RETAINED",
                "failure": failure,
                "channel_count": len(plan.channels),
                "closed_viewers": closed,
                "frame_counts": list(counts.values()),
                "streams": streams,
                "live_max_seconds": plan.max_seconds,
                "cleanup_max_seconds": cleanup_seconds,
                "elapsed_ms": max(0, int((self.clock() - started) * 1000)),
                "cleanup_scope": "LAST_VIEWER_AND_DEVICE_EPOCH"
                if cleanup_confirmed
                else "RETAINED",
                "observer_terminal_required": True,
            }
        )


if __name__ == "__main__":
    raise SystemExit("Mux probe requires the reviewed owned-runtime controller.")
