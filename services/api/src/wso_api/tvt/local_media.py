"""Local live HTTP control; API only issues tickets and reads public leases."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from wso_contracts.tvt.local_media import (
    LocalLiveOfferRequest,
    LocalLiveOfferResponse,
    LocalLiveRequest,
    LocalLiveResponse,
    LocalLiveStartedRequest,
)
from wso_contracts.tvt.media import LocalMediaOwnerRef
from wso_core.tvt.local_media_admission import LocalMediaReader, LocalMediaTicketIssuer
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget
from wso_tvt_bridge.local_media_rpc import checked_media_json
from wso_tvt_bridge.selected import directory_json

from wso_api.auth import SESSION_COOKIE, token_digest
from wso_api.stores.router import require_tenant
from wso_api.tvt.account import Current, _authenticate
from wso_api.tvt.local_media_diagnostics import MediaDiagnostic, diagnostic


class LocalMediaRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def secured_inner(request: Request) -> Response:
            budget = LocalVerifyBudget(20000)
            request.state.local_media_budget = budget
            trace = diagnostic(request)
            trace.phase("auth")
            request.state._tvt_account_authenticated = await run_in_threadpool(
                _authenticate, request
            )
            trace.complete()
            trace.phase("query")
            start = request.url.path == "/api/v1/tvt/live-sessions"
            expected = {"tenant_id", "connection_id"} if start else {"tenant_id"}
            query = request.query_params.multi_items()
            if len(query) != len(expected) or {key for key, _ in query} != expected:
                raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
            trace.complete()
            trace.phase("body")
            if request.method == "POST":
                if (
                    request.headers.get("content-type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                    != "application/json"
                ):
                    raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
                maximum = 262144 if request.url.path.endswith("/webrtc-offer") else 4096

                async def bounded() -> bytes:
                    raw = bytearray()
                    async for chunk in request.stream():
                        if len(raw) + len(chunk) > maximum:
                            raise ValueError
                        raw.extend(chunk)
                    return bytes(raw)

                try:
                    raw = await asyncio.wait_for(
                        bounded(), timeout=budget.remaining_ms() / 1000
                    )
                    value = directory_json(raw)
                    if (
                        not start
                        and not request.url.path.endswith("/webrtc-offer")
                        and not request.url.path.endswith("/playing")
                        and not request.url.path.endswith("/focus-reservations")
                        and not request.url.path.endswith("/settle")
                        and value != {}
                    ):
                        raise ValueError
                    request._body = raw
                except TimeoutError:
                    raise LocalDeviceFailure(
                        "LOCAL_DEVICE_DEADLINE_EXCEEDED", 504
                    ) from None
                except (ValueError, UnicodeError, TypeError, RecursionError):
                    raise LocalDeviceFailure(
                        "LOCAL_DEVICE_INPUT_INVALID", 422
                    ) from None
            trace.complete()
            trace.phase("handler")
            budget.remaining_ms()
            response = await handler(request)
            trace.complete()
            trace.phase("response")
            trace.complete()
            return response

        async def secured(request: Request) -> Response:
            trace = MediaDiagnostic(request, self.path)
            request.state.local_media_diagnostic = trace
            try:
                response = await secured_inner(request)
            except BaseException as error:
                trace.finish(error=error)
                raise
            trace.finish(response.status_code)
            return response

        return secured


router = APIRouter(
    prefix="/api/v1/tvt/live-sessions",
    tags=["tvt-local-live"],
    route_class=LocalMediaRoute,
)


def configure_local_media(app: FastAPI, *, shared_enabled: bool = False) -> None:
    if type(shared_enabled) is not bool:
        raise ValueError("invalid shared media mode")
    app.state.tvt_local_media_worker = None
    app.state.tvt_local_media_mux_worker = None
    app.state.tvt_local_media_shared_enabled = shared_enabled
    app.state.tvt_local_media_diagnostics_sink = None


def checked_view(
    result: LocalLiveResponse,
    tenant_id: UUID,
    actor_id: UUID,
    lease_id: UUID | None = None,
) -> LocalLiveResponse:
    lease = result.lease
    if (
        type(lease.owner) is not LocalMediaOwnerRef
        or lease.owner.tenant_id != tenant_id
        or lease.owner.actor_user_id != actor_id
        or (lease_id is not None and lease.id != lease_id)
    ):
        raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
    return result


def dispatch(
    request: Request,
    tenant_id: UUID,
    current: tuple[Any, Any],
    action: str,
    connection_id: UUID | None = None,
    lease_id: UUID | None = None,
    body: Any = None,
) -> LocalLiveResponse | LocalLiveOfferResponse:
    budget = request.state.local_media_budget
    service, principal = current
    shared = request.app.state.tvt_local_media_shared_enabled
    trace = diagnostic(request)
    if action == "start":
        from .local_media_mux import validate_mode_request

        trace.mode(body)
        validate_mode_request(shared, body)
        trace.complete()
    trace.phase("worker")
    worker = getattr(
        request.app.state,
        "tvt_local_media_mux_worker"
        if shared and action == "start"
        else "tvt_local_media_worker",
        None,
    )
    if worker is None:
        raise LocalDeviceFailure()
    trace.complete()
    trace.phase("tenant")
    digest = token_digest(request.cookies[SESSION_COOKIE])
    with require_tenant(
        "connections:write", tenant_id, service=service, principal=principal
    ) as scope:
        trace.complete()
        trace.phase("ticket")
        if (action == "start" and connection_id is None) or (
            action != "start" and lease_id is None
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        if shared and action == "start":
            from .local_media_mux import LocalMuxTicketIssuer

            ticket = LocalMuxTicketIssuer(
                scope.session, budget.remaining_ms
            ).issue_shared(digest, cast(UUID, connection_id), body)
        else:
            issuer = LocalMediaTicketIssuer(scope.session, budget.remaining_ms)
            ticket = (
                issuer.issue(digest, cast(UUID, connection_id), body)
                if action == "start"
                else issuer.issue_control(digest, cast(UUID, lease_id), action)
            )
    trace.complete()
    budget.remaining_ms()
    kwargs = {
        "deadline_ms": budget.remaining_ms(),
        "correlation_id": request.state.request_id,
        "cancel": budget.cancel,
    }
    if action == "offer":
        kwargs["offer"] = body
    if action == "playing":
        kwargs["started"] = body
    trace.phase("rpc")
    value = getattr(
        worker, "start_shared" if shared and action == "start" else "live_" + action
    )(ticket, **kwargs)
    trace.complete()
    trace.phase("response")
    budget.remaining_ms()
    result = checked_media_json(
        value.model_dump_json(exclude_none=True).encode(),
        action,
        request.state.request_id,
    )
    if action == "offer":
        return result
    assert isinstance(result, LocalLiveResponse)
    checked_view(result, tenant_id, principal.user_id, lease_id)
    if action == "start":
        lease = result.lease
        assert isinstance(lease.owner, LocalMediaOwnerRef)
        if (
            lease.owner.connection_id != connection_id
            or lease.owner.store_id != body.store_id
            or lease.device.device_id != body.device_id
            or lease.channel != body.channel_id
            or lease.connection_generation != body.expected_generation
            or lease.inventory_revision != body.inventory_revision
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
    return result


async def call_owned(
    request: Request, *, dispatch_fn: Callable[..., Any] = dispatch, **kwargs: Any
) -> Any:
    budget = request.state.local_media_budget

    async def watch() -> None:
        while True:
            if await request.is_disconnected():
                budget.cancel.set()
                return
            await asyncio.sleep(0.025)

    watcher = asyncio.create_task(watch())
    success = False
    try:
        value = await run_in_threadpool(dispatch_fn, request, **kwargs)
        success = True
        return value
    finally:
        watcher.cancel()
        if not success:
            budget.cancel.set()


@router.post("", response_model=LocalLiveResponse, response_model_exclude_none=True)
async def start(
    request: Request,
    tenant_id: UUID,
    connection_id: UUID,
    body: LocalLiveRequest,
    current: Current,
) -> Any:
    return await call_owned(
        request,
        tenant_id=tenant_id,
        connection_id=connection_id,
        body=body,
        current=current,
        action="start",
    )


@router.post("/{lease_id}/webrtc-offer", response_model=LocalLiveOfferResponse)
async def offer(
    request: Request,
    tenant_id: UUID,
    lease_id: UUID,
    body: LocalLiveOfferRequest,
    current: Current,
) -> Any:
    return await call_owned(
        request,
        tenant_id=tenant_id,
        lease_id=lease_id,
        body=body,
        current=current,
        action="offer",
    )


@router.post(
    "/{lease_id}/stop",
    response_model=LocalLiveResponse,
    response_model_exclude_none=True,
)
async def stop(
    request: Request, tenant_id: UUID, lease_id: UUID, current: Current
) -> Any:
    return await call_owned(
        request, tenant_id=tenant_id, lease_id=lease_id, current=current, action="stop"
    )


@router.post(
    "/{lease_id}/playing",
    response_model=LocalLiveResponse,
    response_model_exclude_none=True,
)
async def playing(
    request: Request,
    tenant_id: UUID,
    lease_id: UUID,
    body: LocalLiveStartedRequest,
    current: Current,
) -> Any:
    return await call_owned(
        request,
        tenant_id=tenant_id,
        lease_id=lease_id,
        body=body,
        current=current,
        action="playing",
    )


def read_lease(
    request: Request,
    tenant_id: UUID,
    lease_id: UUID,
    current: tuple[Any, Any],
    heartbeat: bool,
) -> LocalLiveResponse:
    budget = request.state.local_media_budget
    service, principal = current
    with require_tenant(
        "connections:write", tenant_id, service=service, principal=principal
    ) as scope:
        reader = LocalMediaReader(scope.session, budget.remaining_ms)
        view = (reader.heartbeat if heartbeat else reader.get)(
            token_digest(request.cookies[SESSION_COOKIE]), lease_id
        )
    return checked_view(
        LocalLiveResponse(lease=view, request_id=request.state.request_id),
        tenant_id,
        principal.user_id,
        lease_id,
    )


@router.get(
    "/{lease_id}", response_model=LocalLiveResponse, response_model_exclude_none=True
)
def state(
    request: Request, tenant_id: UUID, lease_id: UUID, current: Current
) -> LocalLiveResponse:
    return read_lease(request, tenant_id, lease_id, current, False)


@router.post(
    "/{lease_id}/heartbeat",
    response_model=LocalLiveResponse,
    response_model_exclude_none=True,
)
def heartbeat(
    request: Request, tenant_id: UUID, lease_id: UUID, current: Current
) -> LocalLiveResponse:
    return read_lease(request, tenant_id, lease_id, current, True)
