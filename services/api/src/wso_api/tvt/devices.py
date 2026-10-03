"""Authenticated readonly directory: committed SQL tickets before shared RPC."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from wso_contracts.tvt.account import AccountErrorEnvelope
from wso_contracts.tvt.directory import (
    ChannelDetailRequest,
    ChannelListRequest,
    DeviceDetailRequest,
    DeviceListRequest,
    DirectoryRequest,
    DirectoryView,
    ObservationField,
    ObservationObject,
    ReceivedSharesRequest,
    SentSharesRequest,
)
from wso_core.tvt import directory_projection as projection
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.directory_admission import DirectoryTicketIssuer
from wso_tvt_bridge.client import AccountRpcClient
from wso_tvt_bridge.selected import (
    DIRECTORY_FAILURES,
    checked_directory_view,
    directory_json,
    encode_directory_input,
)

from wso_api.auth import SESSION_COOKIE, AuthService, WebSession, token_digest
from wso_api.stores.router import require_tenant
from wso_api.tvt.account import AccountRoute, Current, _authenticate
from wso_api.tvt.session_service import Budget


class DirectoryRoute(AccountRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = APIRoute.get_route_handler(self)

        async def secured(request: Request) -> Response:
            request.state._tvt_account_budget = Budget(10000)
            request.state._tvt_account_authenticated = await run_in_threadpool(
                _authenticate, request
            )
            budget = request.state._tvt_account_budget
            query = request.query_params.multi_items()
            if len(query) != 1 or query[0][0] != "tenant_id":
                raise AccountFailure("ACCOUNT_INPUT_INVALID", 422)
            if (
                not request.headers.get("content-type", "")
                .lower()
                .split(";")[0]
                .strip()
                == "application/json"
            ):
                raise AccountFailure("ACCOUNT_INPUT_INVALID", 422)

            async def bounded() -> bytes:
                chunks = []
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 65536:
                        raise ValueError
                    chunks.append(chunk)
                return b"".join(chunks)

            try:
                payload = await asyncio.wait_for(
                    bounded(), timeout=budget.remaining() / 1000
                )
                directory_json(payload)
                request._body = payload
            except TimeoutError:
                raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504) from None
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise AccountFailure("ACCOUNT_INPUT_INVALID", 422) from None
            budget.remaining()
            return await handler(request)

        return secured


router = APIRouter(
    prefix="/api/v1/tvt/directory",
    tags=["tvt-directory"],
    route_class=DirectoryRoute,
    responses={
        status: {"model": AccountErrorEnvelope}
        for status in (401, 403, 404, 409, 422, 429, 500, 502, 503, 504)
    },
)

# Reuse the decoded source whitelist, including nested field types and defaults.
_SCHEMAS = {
    "device_list": projection._DEVICE_RECORD,
    "channel_list": projection._CHANNEL_DEVICE,
    "device_detail": projection._DEVICE_DETAIL,
    "channel_detail": projection._CHANNEL_DETAIL,
    "sent_shares": projection._SENT_SHARE,
    "received_shares": projection._RECEIVED_SHARE,
}


def configure_directory(app: FastAPI) -> None:
    app.state.tvt_directory_worker = None
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = original_openapi()
        component = schema["components"]["schemas"]["ObservationValue"]
        if any(
            "items" in branch
            and branch["items"].get("$ref", "").endswith("/ObservationValue")
            for branch in component.get("anyOf", [])
        ):
            scalars = [
                branch for branch in component["anyOf"] if branch.get("type") != "array"
            ]
            bounded: dict[str, Any] = {"anyOf": scalars}
            for _ in range(12):
                bounded = {
                    "anyOf": scalars
                    + [{"type": "array", "maxItems": 1000, "items": bounded}]
                }
            # Finite array recursion documents the runtime public depth ceiling;
            # named object recursion remains typed through ObservationObject.
            schema["components"]["schemas"]["ObservationValue"] = bounded
        return schema

    app.openapi = openapi  # type: ignore[method-assign]  # documented FastAPI hook
    previous = cast(
        Callable[[Request, AccountFailure], Awaitable[JSONResponse]],
        app.exception_handlers[AccountFailure],
    )

    @app.exception_handler(AccountFailure)
    async def failure(request: Request, error: AccountFailure) -> JSONResponse:
        if not request.url.path.startswith("/api/v1/tvt/directory/"):
            return await previous(request, error)
        status = DIRECTORY_FAILURES.get(error.code)
        code = error.code
        if status is None or status != error.status:
            code, status = "ACCOUNT_UNAVAILABLE", 503
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": "Directory unavailable"
                    if status == 503
                    else "Directory request failed",
                },
                "request_id": request.state.request_id,
            },
        )


def _shape(item: object, schema: projection._Schema) -> None:
    if schema.kind == "object":
        if type(item) is not ObservationObject or schema.members is None:
            raise ValueError
        fields: dict[str, ObservationField] = {
            field.name: field for field in item.fields
        }
        if len(fields) != len(item.fields) or fields.keys() != schema.members.keys():
            raise ValueError
        for name, member in schema.members.items():
            field = fields[name]
            if field.source_default != member.source_default or type(
                field.source_default
            ) is not type(member.source_default):
                raise ValueError
            if field.opaque_kind is not None:
                if (
                    member.kind != "scalar"
                    or field.state != "value"
                    or field.value is not None
                ):
                    raise ValueError
            elif field.state == "value":
                _shape(field.value, member)
            elif field.value is not None:
                raise ValueError
    elif schema.kind == "list":
        if type(item) is not tuple or len(item) > 1000 or schema.element is None:
            raise ValueError
        for value in item:
            _shape(value, schema.element)
    elif (
        schema.kind == "text"
        and type(item) is str
        or schema.kind == "int"
        and type(item) is int
        and -(2**31) <= item < 2**31
        or schema.kind == "bool"
        and type(item) is bool
    ):
        pass
    elif schema.kind == "scalar" and type(item) in (str, bool, int, float):
        if type(item) is int and not -(2**53 - 1) <= item <= 2**53 - 1:
            raise ValueError
    else:
        raise ValueError
    if type(item) is str and (
        "\0" in item
        or any(0xD800 <= ord(c) <= 0xDFFF for c in item)
        or len(item.encode("utf-8")) > 4096
    ):
        raise ValueError


def checked(
    request: Request, body: DirectoryRequest, view: DirectoryView
) -> DirectoryView:
    request.state._tvt_account_budget.remaining()
    clean = checked_directory_view(view, body, request.state.request_id)
    try:
        if clean.generation > 2**53 - 1:
            raise ValueError
        if body.method == "device_list":
            if type(clean.total) is not str:
                raise ValueError
            _shape(clean.total, projection._TEXT)
        elif body.method in ("sent_shares", "received_shares"):
            if type(clean.total) is not int or not 0 <= clean.total < 2**31:
                raise ValueError
        elif clean.total is not None:
            raise ValueError
        if (
            body.method in ("device_detail", "channel_detail")
            and len(clean.records) != 1
        ):
            raise ValueError
        for record in clean.records:
            _shape(record, _SCHEMAS[body.method])
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502) from None
    request.state._tvt_account_budget.remaining()
    return clean


def execute(
    request: Request,
    tenant_id: UUID,
    current: tuple[AuthService, WebSession],
    body: DirectoryRequest,
) -> DirectoryView:
    worker = getattr(request.app.state, "tvt_directory_worker", None)
    if worker is None:
        raise AccountFailure()
    encode_directory_input(body.method, body)
    service, principal = current
    with require_tenant(
        "stores:read", tenant_id, service=service, principal=principal
    ) as scope:
        ticket = DirectoryTicketIssuer(
            scope.session, request.state._tvt_account_budget.remaining
        ).issue(token_digest(request.cookies[SESSION_COOKIE]), body.method, body)
    # Context exit commits ticket issuance before the network call.
    client = cast(AccountRpcClient, worker)
    method = getattr(client, "directory_" + body.method)
    view = method(
        ticket,
        body,
        deadline_ms=request.state._tvt_account_budget.remaining(),
        correlation_id=request.state.request_id,
    )
    return checked(request, body, view)


@router.post(
    "/device-list", response_model=DirectoryView, operation_id="tvtDirectoryDeviceList"
)
def device_list(
    body: DeviceListRequest, tenant_id: UUID, request: Request, current: Current
) -> DirectoryView:
    return execute(request, tenant_id, current, body)


@router.post(
    "/channel-list",
    response_model=DirectoryView,
    operation_id="tvtDirectoryChannelList",
)
def channel_list(
    body: ChannelListRequest, tenant_id: UUID, request: Request, current: Current
) -> DirectoryView:
    return execute(request, tenant_id, current, body)


@router.post(
    "/device-detail",
    response_model=DirectoryView,
    operation_id="tvtDirectoryDeviceDetail",
)
def device_detail(
    body: DeviceDetailRequest, tenant_id: UUID, request: Request, current: Current
) -> DirectoryView:
    return execute(request, tenant_id, current, body)


@router.post(
    "/channel-detail",
    response_model=DirectoryView,
    operation_id="tvtDirectoryChannelDetail",
)
def channel_detail(
    body: ChannelDetailRequest, tenant_id: UUID, request: Request, current: Current
) -> DirectoryView:
    return execute(request, tenant_id, current, body)


@router.post(
    "/sent-shares", response_model=DirectoryView, operation_id="tvtDirectorySentShares"
)
def sent_shares(
    body: SentSharesRequest, tenant_id: UUID, request: Request, current: Current
) -> DirectoryView:
    return execute(request, tenant_id, current, body)


@router.post(
    "/received-shares",
    response_model=DirectoryView,
    operation_id="tvtDirectoryReceivedShares",
)
def received_shares(
    body: ReceivedSharesRequest, tenant_id: UUID, request: Request, current: Current
) -> DirectoryView:
    return execute(request, tenant_id, current, body)
