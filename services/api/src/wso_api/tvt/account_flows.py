"""Closed flow routes: T03 admission, committed SQL ticket, then owned RPC."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from wso_contracts.tvt.account import AccountErrorEnvelope
from wso_contracts.tvt.account_flows import (
    AccountDynamicCodeRequest,
    AccountFlowCancel,
    AccountFlowReference,
    AccountFlowStart,
    AccountFlowView,
    AccountRecoverySubmit,
    AccountRegistrationSubmit,
)
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.flow_admission import FlowTicketIssuer
from wso_tvt_bridge.client import AccountRpcClient
from wso_tvt_bridge.selected import FLOW_FAILURES

from wso_api.auth import SESSION_COOKIE, AuthService, WebSession, token_digest
from wso_api.stores.router import require_tenant
from wso_api.tvt.account import AccountRoute, Current

router = APIRouter(
    prefix="/api/v1/tvt/account-flows",
    tags=["tvt-account-flows"],
    route_class=AccountRoute,
    responses={
        status: {"model": AccountErrorEnvelope}
        for status in (401, 403, 404, 409, 422, 429, 500, 502, 503, 504)
    },
)


def configure_account_flows(app: FastAPI) -> None:
    app.state.tvt_account_flow_worker = None
    account_failure = cast(
        Callable[[Request, AccountFailure], Awaitable[JSONResponse]],
        app.exception_handlers[AccountFailure],
    )

    @app.exception_handler(AccountFailure)
    async def failure(request: Request, error: AccountFailure) -> JSONResponse:
        if not request.url.path.startswith("/api/v1/tvt/account-flows/"):
            return await account_failure(request, error)
        code = error.code
        status = FLOW_FAILURES.get(code)
        if status is None or status != error.status:
            code, status = "ACCOUNT_UNAVAILABLE", 503
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": "Account unavailable"
                    if status == 503
                    else "Account request failed",
                },
                "request_id": request.state.request_id,
            },
        )


def worker_for(request: Request) -> AccountRpcClient:
    worker = getattr(request.app.state, "tvt_account_flow_worker", None)
    if worker is None:
        raise AccountFailure()
    return cast(AccountRpcClient, worker)


def ticket_for(
    request: Request,
    tenant_id: UUID,
    current: tuple[AuthService, WebSession],
    operation: str,
    body: AccountFlowStart | AccountFlowReference,
) -> str:
    service, principal = current
    with require_tenant(
        "stores:read", tenant_id, service=service, principal=principal
    ) as scope:
        ticket = FlowTicketIssuer(
            scope.session, request.state._tvt_account_budget.remaining
        ).issue(token_digest(request.cookies[SESSION_COOKIE]), operation, body)
    # The tenant context commits issuance BEFORE the network redemption.
    return ticket


def checked(
    request: Request,
    body: AccountFlowStart | AccountFlowReference,
    view: AccountFlowView,
) -> AccountFlowView:
    # Keep the public shape closed even when a port implementation is substituted.
    request.state._tvt_account_budget.remaining()
    try:
        result = AccountFlowView.model_validate(view.model_dump())
    except (ValidationError, TypeError, AttributeError):
        raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502) from None
    if (
        result.request_id != request.state.request_id
        or (result.region, result.brand, result.purpose)
        != (body.region, body.brand, body.purpose)
        or isinstance(body, AccountFlowReference)
        and result.flow_id != body.flow_id
    ):
        raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
    return result


@router.post(
    "/start", response_model=AccountFlowView, operation_id="tvtAccountFlowStart"
)
def start(
    body: AccountFlowStart, tenant_id: UUID, request: Request, current: Current
) -> AccountFlowView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "start", body)
    return checked(
        request,
        body,
        worker.start(
            ticket,
            body,
            deadline_ms=request.state._tvt_account_budget.remaining(),
            correlation_id=request.state.request_id,
        ),
    )


@router.post(
    "/state", response_model=AccountFlowView, operation_id="tvtAccountFlowState"
)
def state(
    body: AccountFlowReference, tenant_id: UUID, request: Request, current: Current
) -> AccountFlowView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "state", body)
    return checked(
        request,
        body,
        worker.state(
            ticket,
            body,
            deadline_ms=request.state._tvt_account_budget.remaining(),
            correlation_id=request.state.request_id,
        ),
    )


@router.post(
    "/existence", response_model=AccountFlowView, operation_id="tvtAccountFlowExistence"
)
def existence(
    body: AccountFlowReference, tenant_id: UUID, request: Request, current: Current
) -> AccountFlowView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "existence", body)
    return checked(
        request,
        body,
        worker.existence(
            ticket,
            body,
            deadline_ms=request.state._tvt_account_budget.remaining(),
            correlation_id=request.state.request_id,
        ),
    )


@router.post(
    "/image", response_model=AccountFlowView, operation_id="tvtAccountFlowImage"
)
def image(
    body: AccountFlowReference, tenant_id: UUID, request: Request, current: Current
) -> AccountFlowView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "image", body)
    return checked(
        request,
        body,
        worker.image(
            ticket,
            body,
            deadline_ms=request.state._tvt_account_budget.remaining(),
            correlation_id=request.state.request_id,
        ),
    )


@router.post(
    "/issue-code",
    response_model=AccountFlowView,
    operation_id="tvtAccountFlowIssueCode",
)
def issue_code(
    body: AccountDynamicCodeRequest, tenant_id: UUID, request: Request, current: Current
) -> AccountFlowView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "issue_code", body)
    return checked(
        request,
        body,
        worker.issue_code(
            ticket,
            body,
            deadline_ms=request.state._tvt_account_budget.remaining(),
            correlation_id=request.state.request_id,
        ),
    )


@router.post(
    "/register", response_model=AccountFlowView, operation_id="tvtAccountFlowRegister"
)
def register(
    body: AccountRegistrationSubmit, tenant_id: UUID, request: Request, current: Current
) -> AccountFlowView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "register", body)
    return checked(
        request,
        body,
        worker.register(
            ticket,
            body,
            deadline_ms=request.state._tvt_account_budget.remaining(),
            correlation_id=request.state.request_id,
        ),
    )


@router.post(
    "/recover", response_model=AccountFlowView, operation_id="tvtAccountFlowRecover"
)
def recover(
    body: AccountRecoverySubmit, tenant_id: UUID, request: Request, current: Current
) -> AccountFlowView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "recover", body)
    return checked(
        request,
        body,
        worker.recover(
            ticket,
            body,
            deadline_ms=request.state._tvt_account_budget.remaining(),
            correlation_id=request.state.request_id,
        ),
    )


@router.post(
    "/cancel", response_model=AccountFlowView, operation_id="tvtAccountFlowCancel"
)
def cancel(
    body: AccountFlowCancel, tenant_id: UUID, request: Request, current: Current
) -> AccountFlowView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "cancel", body)
    return checked(
        request,
        body,
        worker.cancel(
            ticket,
            body,
            deadline_ms=request.state._tvt_account_budget.remaining(),
            correlation_id=request.state.request_id,
        ),
    )
