"""Owner local verification and saved inventory; API never constructs a worker."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from wso_contracts.tvt.account import AccountErrorEnvelope
from wso_contracts.tvt.local_device import LocalDeviceView, LocalVerifyRequest
from wso_core.tvt.local_service import LocalDeviceFailure, LocalVerifyBudget
from wso_tvt_bridge.local_rpc import LOCAL_FAILURES, checked_local_view
from wso_tvt_bridge.selected import directory_json

from wso_api.auth import SESSION_COOKIE, token_digest
from wso_api.stores.router import require_tenant
from wso_api.tvt.account import Current, _authenticate

from .local_device_service import LocalDeviceWorker


class LocalDeviceRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def secured(request: Request) -> Response:
            budget = LocalVerifyBudget(20000)
            request.state.local_device_budget = budget
            request.state._tvt_account_authenticated = await run_in_threadpool(
                _authenticate, request
            )
            expected = (
                {"tenant_id"} if request.method == "POST" else {"tenant_id", "store_id"}
            )
            query = request.query_params.multi_items()
            if len(query) != len(expected) or {key for key, _ in query} != expected:
                raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
            if request.method == "POST":
                if (
                    request.headers.get("content-type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                    != "application/json"
                ):
                    raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)

                async def bounded() -> bytes:
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 1024:
                            raise ValueError
                        chunks.append(chunk)
                    return b"".join(chunks)

                try:
                    timeout = budget.remaining_ms() / 1000
                    payload = await asyncio.wait_for(bounded(), timeout=timeout)
                    directory_json(payload)
                    request._body = payload
                except TimeoutError:
                    raise LocalDeviceFailure(
                        "LOCAL_DEVICE_DEADLINE_EXCEEDED", 504
                    ) from None
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    raise LocalDeviceFailure(
                        "LOCAL_DEVICE_INPUT_INVALID", 422
                    ) from None
            budget.remaining_ms()
            return await handler(request)

        return secured


router = APIRouter(
    prefix="/api/v1/tvt/local-devices",
    tags=["tvt-local-devices"],
    route_class=LocalDeviceRoute,
    responses={
        s: {"model": AccountErrorEnvelope}
        for s in (401, 403, 404, 409, 422, 429, 500, 502, 503, 504)
    },
)


def configure_local_devices(app: FastAPI) -> None:
    app.state.tvt_local_device_worker = None

    @app.exception_handler(LocalDeviceFailure)
    async def failure(request: Request, error: LocalDeviceFailure) -> JSONResponse:
        code, status = error.code, LOCAL_FAILURES.get(error.code)
        if status is None or status != error.status:
            code, status = "LOCAL_DEVICE_UNAVAILABLE", 503
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": "Local device unavailable"
                    if status == 503
                    else "Local device request failed",
                },
                "request_id": request.state.request_id,
            },
        )


def _verify(
    request: Request,
    tenant_id: UUID,
    connection_id: UUID,
    current: tuple[Any, Any],
    body: LocalVerifyRequest,
) -> LocalDeviceView:
    from wso_core.tvt.local_admission import LocalDeviceTicketIssuer

    worker = cast(
        LocalDeviceWorker | None,
        getattr(request.app.state, "tvt_local_device_worker", None),
    )
    if worker is None:
        raise LocalDeviceFailure()
    budget: LocalVerifyBudget = request.state.local_device_budget
    service, principal = current
    with require_tenant(
        "connections:write", tenant_id, service=service, principal=principal
    ) as scope:
        ticket = LocalDeviceTicketIssuer(scope.session, budget.remaining_ms).issue(
            token_digest(request.cookies[SESSION_COOKIE]), connection_id, body
        )
    budget.remaining_ms()
    view = worker.verify(
        ticket,
        deadline_ms=budget.remaining_ms(),
        correlation_id=request.state.request_id,
        cancel=budget.cancel,
    )
    budget.remaining_ms()
    clean = checked_local_view(view, request.state.request_id)
    if (
        clean.connection_id != connection_id
        or clean.store_id != body.store_id
        or clean.connection_generation != body.expected_generation
        or clean.inventory_state != "AVAILABLE"
    ):
        raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
    return clean


@router.post(
    "/{connection_id}/verify",
    response_model=LocalDeviceView,
    operation_id="tvtLocalDeviceVerify",
)
async def verify(
    connection_id: UUID,
    body: LocalVerifyRequest,
    tenant_id: UUID,
    request: Request,
    current: Current,
) -> LocalDeviceView:
    budget: LocalVerifyBudget = request.state.local_device_budget

    async def disconnected() -> None:
        while True:
            if await request.is_disconnected():
                budget.cancel.set()
                return
            await asyncio.sleep(0.025)

    watcher = asyncio.create_task(disconnected())
    try:
        return await run_in_threadpool(
            _verify, request, tenant_id, connection_id, current, body
        )
    finally:
        watcher.cancel()
        budget.cancel.set()


def _inventory(
    request: Request,
    tenant_id: UUID,
    store_id: UUID,
    current: tuple[Any, Any],
    connection_id: UUID | None = None,
) -> list[LocalDeviceView]:
    from wso_core.tvt.local_admission import LocalDeviceInventoryReader

    budget: LocalVerifyBudget = request.state.local_device_budget
    service, principal = current
    with require_tenant(
        "connections:read", tenant_id, service=service, principal=principal
    ) as scope:
        reader = LocalDeviceInventoryReader(scope.session)
        views = (
            (
                reader.get(
                    connection_id, store_id, correlation_id=request.state.request_id
                ),
            )
            if connection_id is not None
            else reader.list(store_id, correlation_id=request.state.request_id)
        )
    budget.remaining_ms()
    clean = [checked_local_view(view, request.state.request_id) for view in views]
    if any(
        view.store_id != store_id
        or (connection_id is not None and view.connection_id != connection_id)
        for view in clean
    ):
        raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
    if connection_id is not None and len(clean) != 1:
        raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
    return clean


@router.get("", response_model=list[LocalDeviceView], operation_id="tvtLocalDeviceList")
def device_list(
    tenant_id: UUID, store_id: UUID, request: Request, current: Current
) -> list[LocalDeviceView]:
    return _inventory(request, tenant_id, store_id, current)


@router.get(
    "/{connection_id}/channels",
    response_model=LocalDeviceView,
    operation_id="tvtLocalDeviceChannels",
)
def channels(
    connection_id: UUID,
    tenant_id: UUID,
    store_id: UUID,
    request: Request,
    current: Current,
) -> LocalDeviceView:
    return _inventory(request, tenant_id, store_id, current, connection_id)[0]
