"""Closed mux RPC transport; selectors and authority are SQL ticket contents."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from threading import Event
from typing import Any, cast
from uuid import UUID

import grpc
from pydantic import Field
from wso_contracts.models import WireModel
from wso_contracts.tvt.local_media import LocalLiveResponse
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget

from .generated import tvt_bridge_pb2 as generated_pb
from .generated import tvt_bridge_pb2_grpc as rpc
from .local_media_rpc import MAX_MEDIA_JSON, checked_media_json
from .local_rpc import local_failure
from .selected import PROTOCOL_VERSION, directory_json, reject_unknown, validate_request

pb: Any = generated_pb
METHODS = {
    "start_shared": "StartShared",
    "wall_heartbeat": "WallHeartbeat",
    "stop_wall": "StopWall",
    "focus_reserve": "FocusReserve",
    "focus_settle": "FocusSettle",
}


class LocalMuxAck(WireModel):
    """Private opaque operation identity, never authority or cleanup evidence."""

    id: UUID
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


def validate_mux_request(request: Any) -> None:
    try:
        if type(request) is not pb.LocalMediaMuxRequest or request.ByteSize() > 1024:
            raise ValueError
        reject_unknown(request)
        validate_request(pb.LocalDeviceVerifyRequest(context=request.context))
        if len(request.context.correlation_id) > 64:
            raise ValueError
    except (ValueError, TypeError, AccountFailure):
        raise local_failure("LOCAL_DEVICE_INPUT_INVALID") from None


def checked_mux_json(
    raw: bytes, action: str, correlation: str
) -> LocalLiveResponse | LocalMuxAck:
    if action == "start_shared":
        result = checked_media_json(raw, "start", correlation)
        assert isinstance(result, LocalLiveResponse)
        return result
    try:
        if action not in METHODS or not 0 < len(raw) <= MAX_MEDIA_JSON:
            raise ValueError
        ack = LocalMuxAck.model_validate(directory_json(raw))
        if ack.request_id != correlation or not ack.id.int:
            raise ValueError
        return ack
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise local_failure("LOCAL_DEVICE_PROTOCOL_INVALID") from None


def call_mux(
    stub: Any,
    registry: Any,
    action: str,
    ticket: str,
    *,
    deadline_ms: int,
    correlation_id: str,
    cancel: Event | None = None,
) -> LocalLiveResponse | LocalMuxAck:
    if action not in METHODS:
        raise local_failure("LOCAL_DEVICE_INPUT_INVALID")
    budget = LocalVerifyBudget(deadline_ms, cancel=cancel)
    request = pb.LocalMediaMuxRequest(
        context=pb.RpcContext(
            protocol_version=PROTOCOL_VERSION,
            ticket=ticket,
            deadline_ms=budget.remaining_ms(),
            correlation_id=correlation_id,
        )
    )
    validate_mux_request(request)
    slot = None
    try:
        slot = registry.admit(correlation_id)
        pending = getattr(stub, METHODS[action]).future(
            request, timeout=budget.remaining_ms() / 1000, wait_for_ready=False
        )
        registry.attach_cancel(slot, pending.cancel)
        while True:
            try:
                budget.remaining_ms()
                reply = pending.result(timeout=0.025)
                break
            except grpc.FutureTimeoutError:
                continue
            except LocalDeviceFailure:
                pending.cancel()
                raise
        budget.remaining_ms()
        reject_unknown(reply)
        if reply.ByteSize() > MAX_MEDIA_JSON or bool(reply.failure_code) == bool(
            reply.public_json
        ):
            raise local_failure("LOCAL_DEVICE_PROTOCOL_INVALID")
        if reply.failure_code:
            raise local_failure(reply.failure_code)
        return checked_mux_json(reply.public_json, action, correlation_id)
    except grpc.FutureCancelledError:
        raise local_failure("LOCAL_DEVICE_CANCELLED") from None
    except grpc.RpcError as exc:
        raise local_failure(
            {
                grpc.StatusCode.PERMISSION_DENIED: "LOCAL_DEVICE_DENIED",
                grpc.StatusCode.DEADLINE_EXCEEDED: "LOCAL_DEVICE_DEADLINE_EXCEEDED",
                grpc.StatusCode.RESOURCE_EXHAUSTED: "LOCAL_DEVICE_BUSY",
            }.get(exc.code(), "LOCAL_DEVICE_UNAVAILABLE")
        ) from None
    except AccountFailure:
        raise local_failure("LOCAL_DEVICE_BUSY") from None
    except (ValueError, TypeError):
        raise local_failure("LOCAL_DEVICE_PROTOCOL_INVALID") from None
    finally:
        if slot is not None and not registry.settle(slot):
            raise local_failure("LOCAL_DEVICE_CANCELLED") from None


class LocalMuxRpcClient:
    """Borrow the existing authenticated channel and original call registry."""

    def __init__(self, account_client: Any) -> None:
        stub: Any = rpc.LocalMediaMuxBridgeV1Stub
        self._stub = stub(account_client._channel)
        self._registry = account_client._registry

    def start_shared(self, ticket: str, **kwargs: Any) -> Any:
        return call_mux(self._stub, self._registry, "start_shared", ticket, **kwargs)

    def wall_heartbeat(self, ticket: str, **kwargs: Any) -> Any:
        return call_mux(self._stub, self._registry, "wall_heartbeat", ticket, **kwargs)

    def stop_wall(self, ticket: str, **kwargs: Any) -> Any:
        return call_mux(self._stub, self._registry, "stop_wall", ticket, **kwargs)

    def focus_reserve(self, ticket: str, **kwargs: Any) -> Any:
        return call_mux(self._stub, self._registry, "focus_reserve", ticket, **kwargs)

    def focus_settle(self, ticket: str, **kwargs: Any) -> Any:
        return call_mux(self._stub, self._registry, "focus_settle", ticket, **kwargs)


class LocalMuxWorkerAdapter:
    """Redeem exactly once through the reviewed executor/coordinator ports."""

    def __init__(self, media_worker: Any) -> None:
        self.worker = media_worker
        self.executor = media_worker.executor
        self.coordinator = self.executor.coordinator

    def start_shared(self, ticket: str, **kwargs: Any) -> LocalLiveResponse:
        return cast(LocalLiveResponse, self.worker.start(ticket, **kwargs))

    def _control(
        self,
        action: str,
        ticket: str,
        *,
        deadline_ms: int,
        correlation_id: str,
        cancel: Event | None = None,
    ) -> LocalMuxAck:
        budget = LocalVerifyBudget(deadline_ms, cancel=cancel)
        if action == "wall_heartbeat":
            identity = self.coordinator.heartbeat(ticket, budget=budget)
        elif action == "focus_reserve":
            grant = self.coordinator.reserve_focus(ticket, budget=budget)
            identity, _ = self.executor.admission.focus_identity(grant)
        elif action == "focus_settle":
            identity = self.coordinator.settle_focus_control(ticket, budget=budget)
        elif action == "stop_wall":
            identity, _settled = self.coordinator.stop_wall_result(
                ticket, budget=budget
            )
        else:
            raise local_failure("LOCAL_DEVICE_INPUT_INVALID")
        budget.remaining_ms()
        return LocalMuxAck(id=identity, request_id=correlation_id)

    def wall_heartbeat(self, ticket: str, **kwargs: Any) -> LocalMuxAck:
        return self._control("wall_heartbeat", ticket, **kwargs)

    def stop_wall(self, ticket: str, **kwargs: Any) -> LocalMuxAck:
        return self._control("stop_wall", ticket, **kwargs)

    def focus_reserve(self, ticket: str, **kwargs: Any) -> LocalMuxAck:
        return self._control("focus_reserve", ticket, **kwargs)

    def focus_settle(self, ticket: str, **kwargs: Any) -> LocalMuxAck:
        return self._control("focus_settle", ticket, **kwargs)


class SharedLegacyControls:
    """Keep offer/playing/stop ports, fence the independent Start RPC."""

    def __init__(self, worker: Any) -> None:
        self.worker = worker

    def start(self, ticket: str, **kwargs: Any) -> Any:
        raise local_failure("LOCAL_DEVICE_INPUT_INVALID")

    def offer(self, ticket: str, **kwargs: Any) -> Any:
        return self.worker.offer(ticket, **kwargs)

    def playing(self, ticket: str, **kwargs: Any) -> Any:
        return self.worker.playing(ticket, **kwargs)

    def stop(self, ticket: str, **kwargs: Any) -> Any:
        return self.worker.stop(ticket, **kwargs)


class LocalMediaMuxRpcService(rpc.LocalMediaMuxBridgeV1Servicer):
    def __init__(self, worker: Any, config: Any, pool: Any) -> None:
        self.worker, self.config, self.pool = worker, config, pool

    def _invoke(self, action: str, request: Any, context: grpc.ServicerContext) -> Any:
        auth = cast(Mapping[str, Sequence[bytes]], context.auth_context())
        identities = auth.get("x509_subject_alternative_name", ())
        if (
            auth.get("transport_security_type") != [b"ssl"]
            or context.peer_identity_key() != "x509_subject_alternative_name"
            or len(identities) != 1
            or identities[0] not in {x.encode("ascii") for x in self.config.client_sans}
        ):
            context.abort(grpc.StatusCode.PERMISSION_DENIED, "LOCAL_DEVICE_DENIED")
        slot = None
        cancel = Event()
        reply = pb.LocalMediaReply(failure_code="LOCAL_DEVICE_UNAVAILABLE")
        try:
            validate_mux_request(request)
            left = context.time_remaining()
            if left is None or left <= 0:
                raise local_failure("LOCAL_DEVICE_DEADLINE_EXCEEDED")
            end = time.monotonic() + min(left, request.context.deadline_ms / 1000)
            slot = self.pool.registry.admit(request.context.correlation_id)
            self.pool.registry.attach_cancel(slot, cancel.set)
            owned = slot
            if not context.add_callback(lambda: self.pool.registry.abandon(owned)):
                raise local_failure("LOCAL_DEVICE_CANCELLED")
            if self.worker is None:
                raise local_failure("LOCAL_DEVICE_UNAVAILABLE")
            remaining = int((end - time.monotonic()) * 1000)
            if remaining < 1:
                raise local_failure("LOCAL_DEVICE_DEADLINE_EXCEEDED")
            result = getattr(self.worker, action)(
                request.context.ticket,
                deadline_ms=remaining,
                correlation_id=request.context.correlation_id,
                cancel=cancel,
            )
            if time.monotonic() >= end or cancel.is_set() or not context.is_active():
                raise local_failure("LOCAL_DEVICE_CANCELLED")
            clean = checked_mux_json(
                result.model_dump_json(exclude_none=True).encode(),
                action,
                request.context.correlation_id,
            )
            reply = pb.LocalMediaReply(
                public_json=clean.model_dump_json(exclude_none=True).encode()
            )
        except LocalDeviceFailure as exc:
            reply = pb.LocalMediaReply(failure_code=local_failure(exc.code).code)
        except Exception:  # noqa: BLE001 -- fixed private boundary
            reply = pb.LocalMediaReply(failure_code="LOCAL_DEVICE_UNAVAILABLE")
        finally:
            if slot is not None and not self.pool.settle(slot):
                reply = pb.LocalMediaReply(failure_code="LOCAL_DEVICE_CANCELLED")
        return reply

    def StartShared(self, request: Any, context: Any) -> Any:
        return self._invoke("start_shared", request, context)

    def WallHeartbeat(self, request: Any, context: Any) -> Any:
        return self._invoke("wall_heartbeat", request, context)

    def StopWall(self, request: Any, context: Any) -> Any:
        return self._invoke("stop_wall", request, context)

    def FocusReserve(self, request: Any, context: Any) -> Any:
        return self._invoke("focus_reserve", request, context)

    def FocusSettle(self, request: Any, context: Any) -> Any:
        return self._invoke("focus_settle", request, context)
