"""Closed local inventory transport; no credentials or selectors cross RPC."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from threading import Event
from typing import Any, cast
from uuid import UUID

import grpc
from pydantic import BaseModel
from wso_contracts.tvt.local_device import LocalChannelView, LocalDeviceView
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.local_service import (
    LOCAL_DEVICE_FAILURES,
    LocalDeviceFailure,
    LocalVerifyBudget,
)

from .generated import tvt_bridge_pb2 as pb
from .generated import tvt_bridge_pb2_grpc as rpc
from .selected import PROTOCOL_VERSION, directory_json, reject_unknown, validate_request

LOCAL_FAILURES = LOCAL_DEVICE_FAILURES
MAX_LOCAL_BYTES = 65536


def local_failure(code: str) -> LocalDeviceFailure:
    safe = code if code in LOCAL_FAILURES else "LOCAL_DEVICE_UNAVAILABLE"
    return LocalDeviceFailure(safe, LOCAL_FAILURES[safe])


def checked_local_view(view: object, correlation_id: str) -> LocalDeviceView:
    clean = None
    try:

        def raw(item: object) -> Any:
            if type(item) in (LocalDeviceView, LocalChannelView):
                model = cast(BaseModel, item)
                if (
                    set(vars(model)) != set(type(model).model_fields)
                    or model.model_extra
                ):
                    raise ValueError
                return {key: raw(value) for key, value in vars(model).items()}
            if type(item) is tuple:
                return [raw(child) for child in item]
            if type(item) is UUID:
                return str(item)
            if type(item) is datetime:
                return item.isoformat()
            if item is None or type(item) in (str, int):
                return item
            raise ValueError

        if type(view) is not LocalDeviceView:
            raise ValueError
        clean = LocalDeviceView.model_validate(raw(view))
        if (
            clean.request_id != correlation_id
            or len(clean.model_dump_json().encode()) > MAX_LOCAL_BYTES
        ):
            raise ValueError
    except (ValueError, TypeError, UnicodeError, RecursionError):
        clean = None
    if clean is None:
        raise local_failure("LOCAL_DEVICE_PROTOCOL_INVALID") from None
    return clean


def call_local(
    stub: Any,
    registry: Any,
    ticket: str,
    *,
    deadline_ms: int,
    correlation_id: str,
    cancel: Event | None = None,
) -> LocalDeviceView:
    budget = LocalVerifyBudget(deadline_ms, cancel=cancel)
    if type(ticket) is not str or type(correlation_id) is not str:
        raise local_failure("LOCAL_DEVICE_INPUT_INVALID")
    request = pb.LocalDeviceVerifyRequest(
        context=pb.RpcContext(
            protocol_version=PROTOCOL_VERSION,
            ticket=ticket,
            deadline_ms=budget.remaining_ms(),
            correlation_id=correlation_id,
        )
    )
    slot = None
    answer = None
    code: str | None = None
    try:
        validate_request(request)
        if len(correlation_id) > 64:
            raise local_failure("LOCAL_DEVICE_INPUT_INVALID")
        slot = registry.admit(correlation_id)
        request.context.deadline_ms = budget.remaining_ms()
        pending = stub.Verify.future(
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
        if reply.ByteSize() > MAX_LOCAL_BYTES or bool(reply.failure_code) == bool(
            reply.public_json
        ):
            raise local_failure("LOCAL_DEVICE_PROTOCOL_INVALID")
        if reply.failure_code:
            raise local_failure(reply.failure_code)
        answer = checked_local_view(
            LocalDeviceView.model_validate(directory_json(reply.public_json)),
            correlation_id,
        )
        budget.remaining_ms()
    except LocalDeviceFailure as exc:
        code = local_failure(exc.code).code
    except AccountFailure as exc:
        code = {
            "ACCOUNT_INPUT_INVALID": "LOCAL_DEVICE_INPUT_INVALID",
            "ACCOUNT_PROTOCOL_INVALID": "LOCAL_DEVICE_PROTOCOL_INVALID",
            "SESSION_BUSY": "LOCAL_DEVICE_BUSY",
        }.get(exc.code, "LOCAL_DEVICE_UNAVAILABLE")
    except grpc.RpcError as exc:
        code = {
            grpc.StatusCode.PERMISSION_DENIED: "LOCAL_DEVICE_DENIED",
            grpc.StatusCode.RESOURCE_EXHAUSTED: "LOCAL_DEVICE_BUSY",
            grpc.StatusCode.DEADLINE_EXCEEDED: "LOCAL_DEVICE_DEADLINE_EXCEEDED",
        }.get(exc.code(), "LOCAL_DEVICE_UNAVAILABLE")
    except grpc.FutureCancelledError:
        code = "LOCAL_DEVICE_CANCELLED"
    except (ValueError, TypeError, UnicodeError, RecursionError):
        code = "LOCAL_DEVICE_PROTOCOL_INVALID"
    finally:
        if slot is not None and not registry.settle(slot):
            answer, code = None, "LOCAL_DEVICE_CANCELLED"
    if answer is None or code is not None:
        raise local_failure(code or "LOCAL_DEVICE_UNAVAILABLE") from None
    return answer


class LocalDeviceRpcService(rpc.LocalDeviceBridgeV1Servicer):
    def __init__(self, worker: Any, config: Any, pool: Any) -> None:
        self.worker, self.config, self.pool = worker, config, pool

    def Verify(self, request: Any, context: grpc.ServicerContext) -> Any:
        auth = cast(Mapping[str, Sequence[bytes]], context.auth_context())
        identities = auth.get("x509_subject_alternative_name", ())
        if (
            auth.get("transport_security_type") != [b"ssl"]
            or context.peer_identity_key() != "x509_subject_alternative_name"
            or len(identities) != 1
            or identities[0]
            not in {value.encode("ascii") for value in self.config.client_sans}
        ):
            context.abort(grpc.StatusCode.PERMISSION_DENIED, "LOCAL_DEVICE_DENIED")
        slot = None
        cancel = Event()
        reply = pb.LocalDeviceReply(failure_code="LOCAL_DEVICE_UNAVAILABLE")
        try:
            started = time.monotonic()
            validate_request(request)
            if request.ByteSize() > 1024 or len(request.context.correlation_id) > 64:
                raise local_failure("LOCAL_DEVICE_INPUT_INVALID")
            rpc_left = context.time_remaining()
            if rpc_left is None or rpc_left <= 0:
                raise local_failure("LOCAL_DEVICE_DEADLINE_EXCEEDED")
            end = min(
                started + request.context.deadline_ms / 1000,
                time.monotonic() + rpc_left,
            )

            def remaining() -> int:
                left = int((end - time.monotonic()) * 1000)
                if left < 1:
                    cancel.set()
                    raise local_failure("LOCAL_DEVICE_DEADLINE_EXCEEDED")
                if cancel.is_set() or not context.is_active():
                    cancel.set()
                    raise local_failure("LOCAL_DEVICE_CANCELLED")
                return left

            remaining()
            slot = self.pool.registry.admit(request.context.correlation_id)
            self.pool.registry.attach_cancel(slot, cancel.set)
            owned = slot
            if not context.add_callback(lambda: self.pool.registry.abandon(owned)):
                self.pool.registry.abandon(slot)
                raise local_failure("LOCAL_DEVICE_CANCELLED")
            if self.worker is None:
                raise local_failure("LOCAL_DEVICE_UNAVAILABLE")
            result = self.worker.verify(
                request.context.ticket,
                deadline_ms=remaining(),
                correlation_id=request.context.correlation_id,
                cancel=cancel,
            )
            remaining()
            clean = checked_local_view(result, request.context.correlation_id)
            reply = pb.LocalDeviceReply(public_json=clean.model_dump_json().encode())
            if reply.ByteSize() > MAX_LOCAL_BYTES:
                raise local_failure("LOCAL_DEVICE_PROTOCOL_INVALID")
            remaining()
        except LocalDeviceFailure as exc:
            reply = pb.LocalDeviceReply(failure_code=local_failure(exc.code).code)
        except AccountFailure as exc:
            code = {
                "ACCOUNT_INPUT_INVALID": "LOCAL_DEVICE_INPUT_INVALID",
                "ACCOUNT_PROTOCOL_INVALID": "LOCAL_DEVICE_PROTOCOL_INVALID",
                "SESSION_BUSY": "LOCAL_DEVICE_BUSY",
            }.get(exc.code, "LOCAL_DEVICE_UNAVAILABLE")
            reply = pb.LocalDeviceReply(failure_code=code)
        except Exception:  # noqa: BLE001 -- worker failures never leave the boundary
            reply = pb.LocalDeviceReply(failure_code="LOCAL_DEVICE_UNAVAILABLE")
        finally:
            if slot is not None and not self.pool.settle(slot):
                reply = pb.LocalDeviceReply(failure_code="LOCAL_DEVICE_CANCELLED")
        return reply
