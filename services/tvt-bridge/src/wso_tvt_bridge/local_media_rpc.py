"""Purpose-bound media RPC; no device or credential selectors on the wire."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from threading import Event
from typing import Any, cast

import grpc
from wso_contracts.tvt.local_media import (
    LocalLiveOfferRequest,
    LocalLiveOfferResponse,
    LocalLiveResponse,
    LocalLiveStartedRequest,
)
from wso_contracts.tvt.media import LocalMediaOwnerRef
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget

from .generated import tvt_bridge_pb2 as generated_pb
from .generated import tvt_bridge_pb2_grpc as rpc
from .local_rpc import local_failure
from .selected import PROTOCOL_VERSION, directory_json, reject_unknown, validate_request

pb: Any = generated_pb
MAX_MEDIA_JSON = 262144


def checked_media_json(
    raw: bytes, action: str, correlation: str
) -> LocalLiveResponse | LocalLiveOfferResponse:
    try:
        if not 0 < len(raw) <= MAX_MEDIA_JSON:
            raise ValueError
        data = directory_json(raw)
        result = (
            LocalLiveOfferResponse if action == "offer" else LocalLiveResponse
        ).model_validate(data)
        if result.request_id != correlation:
            raise ValueError
        if (
            isinstance(result, LocalLiveResponse)
            and type(result.lease.owner) is not LocalMediaOwnerRef
        ):
            raise ValueError
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise local_failure("LOCAL_DEVICE_PROTOCOL_INVALID") from None


def validate_media_request(
    request: Any, action: str
) -> LocalLiveOfferRequest | LocalLiveStartedRequest | None:
    try:
        reject_unknown(request)
        validate_request(pb.LocalDeviceVerifyRequest(context=request.context))
        if (
            len(request.context.correlation_id) > 64
            or request.ByteSize() > MAX_MEDIA_JSON
        ):
            raise ValueError
        if action == "offer":
            return LocalLiveOfferRequest.model_validate(
                directory_json(request.offer_json)
            )
        if action == "playing" and request.ByteSize() <= 1024:
            return LocalLiveStartedRequest.model_validate(
                directory_json(request.started_json)
            )
        if action not in {"start", "stop"} or request.ByteSize() > 1024:
            raise ValueError
        return None
    except (ValueError, TypeError, AccountFailure):
        raise local_failure("LOCAL_DEVICE_INPUT_INVALID") from None


def call_media(
    stub: Any,
    registry: Any,
    action: str,
    ticket: str,
    *,
    deadline_ms: int,
    correlation_id: str,
    cancel: Event | None = None,
    offer: LocalLiveOfferRequest | None = None,
    started: LocalLiveStartedRequest | None = None,
) -> Any:
    budget = LocalVerifyBudget(deadline_ms, cancel=cancel)
    cls = {
        "start": pb.LocalMediaStartRequest,
        "offer": pb.LocalMediaOfferRequest,
        "stop": pb.LocalMediaStopRequest,
        "playing": pb.LocalMediaPlayingRequest,
    }.get(action)
    if cls is None:
        raise local_failure("LOCAL_DEVICE_INPUT_INVALID")
    request = cls(
        context=pb.RpcContext(
            protocol_version=PROTOCOL_VERSION,
            ticket=ticket,
            deadline_ms=budget.remaining_ms(),
            correlation_id=correlation_id,
        )
    )
    if action == "offer":
        if type(offer) is not LocalLiveOfferRequest:
            raise local_failure("LOCAL_DEVICE_INPUT_INVALID")
        request.offer_json = offer.model_dump_json().encode()
    if action == "playing":
        if type(started) is not LocalLiveStartedRequest:
            raise local_failure("LOCAL_DEVICE_INPUT_INVALID")
        request.started_json = started.model_dump_json().encode()
    validate_media_request(request, action)
    slot = None
    try:
        slot = registry.admit(correlation_id)
        pending = getattr(stub, action.title()).future(
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
        return checked_media_json(reply.public_json, action, correlation_id)
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


class LocalMediaRpcService(rpc.LocalMediaBridgeV1Servicer):
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
            offer = validate_media_request(request, action)
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
            kwargs = {
                "deadline_ms": remaining,
                "correlation_id": request.context.correlation_id,
                "cancel": cancel,
            }
            if offer is not None:
                kwargs["started" if action == "playing" else "offer"] = offer
            result = getattr(self.worker, action)(request.context.ticket, **kwargs)
            if time.monotonic() >= end or cancel.is_set() or not context.is_active():
                raise local_failure("LOCAL_DEVICE_CANCELLED")
            clean = checked_media_json(
                result.model_dump_json(exclude_none=True).encode(),
                action,
                request.context.correlation_id,
            )
            reply = pb.LocalMediaReply(
                public_json=clean.model_dump_json(exclude_none=True).encode()
            )
        except LocalDeviceFailure as exc:
            reply = pb.LocalMediaReply(failure_code=local_failure(exc.code).code)
        except Exception:  # noqa: BLE001 -- fixed private RPC failure boundary
            reply = pb.LocalMediaReply(failure_code="LOCAL_DEVICE_UNAVAILABLE")
        finally:
            if slot is not None and not self.pool.settle(slot):
                reply = pb.LocalMediaReply(failure_code="LOCAL_DEVICE_CANCELLED")
        return reply

    def Start(self, request: Any, context: Any) -> Any:
        return self._invoke("start", request, context)

    def Offer(self, request: Any, context: Any) -> Any:
        return self._invoke("offer", request, context)

    def Stop(self, request: Any, context: Any) -> Any:
        return self._invoke("stop", request, context)

    def Playing(self, request: Any, context: Any) -> Any:
        return self._invoke("playing", request, context)
