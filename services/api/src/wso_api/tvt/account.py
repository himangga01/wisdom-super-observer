"""Typed account routes under T03 auth/CSRF; no saved-token decrypt in API."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from wso_contracts.tvt.account import (
    AccountErrorEnvelope,
    AccountIdentity,
    AccountLogin,
    AccountLogoutView,
    AccountProfileView,
    AccountRefresh,
    AccountSelection,
    ImageChallengeView,
    ImageCheckRequest,
    ImageCheckView,
)
from wso_core.tvt.account_projection import AccountFailure
from wso_core.tvt.authorization import AuthorizationDenied
from wso_core.tvt.ports import AccountClientError
from wso_core.tvt.token_vault import require_user_kind

from wso_api.auth import (
    SESSION_COOKIE,
    AuthFailure,
    AuthService,
    WebSession,
    auth_service,
    require_csrf,
)
from wso_api.stores.router import require_tenant
from wso_api.tvt.identity_service import IdentityService
from wso_api.tvt.session_service import AccountWorker, Budget


def _authenticate(request: Request) -> tuple[AuthService, WebSession]:
    if not request.cookies.get(SESSION_COOKIE):
        raise AuthFailure()
    service = auth_service(request)
    principal = service.authenticate(request)
    if request.method == "POST":
        require_csrf(request, service, principal)
    return service, principal


class AccountRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def secured(request: Request) -> Response:
            request.state._tvt_account_budget = Budget(10000)
            request.state._tvt_account_authenticated = await run_in_threadpool(
                _authenticate, request
            )
            return await handler(request)

        return secured


def authenticated(request: Request) -> tuple[AuthService, WebSession]:
    return cast(
        tuple[AuthService, WebSession], request.state._tvt_account_authenticated
    )


Current = Annotated[tuple[AuthService, WebSession], Depends(authenticated)]
router = APIRouter(
    prefix="/api/v1/tvt/identities",
    tags=["tvt-account"],
    route_class=AccountRoute,
    responses={
        status: {"model": AccountErrorEnvelope}
        for status in (401, 403, 404, 409, 422, 500, 502, 503, 504)
    },
)


def configure_account(app: FastAPI, worker: AccountWorker | None = None) -> None:
    app.state.tvt_account_worker = worker

    @app.exception_handler(AccountFailure)
    async def failure(request: Request, error: AccountFailure) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={
                "error": {
                    "code": error.code,
                    "message": "Account unavailable"
                    if error.status == 503
                    else "Account request failed",
                },
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(AccountClientError)
    async def client_failure(
        request: Request, error: AccountClientError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": error.code.value,
                    "message": "Account request failed",
                },
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(AuthorizationDenied)
    async def denied(request: Request, error: AuthorizationDenied) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "ACCOUNT_DENIED",
                    "message": "Account request failed",
                },
                "request_id": request.state.request_id,
            },
        )


def worker_for(request: Request) -> AccountWorker:
    worker = getattr(request.app.state, "tvt_account_worker", None)
    if worker is None:
        raise AccountFailure()
    return cast(AccountWorker, worker)


def ticket_for(
    request: Request,
    tenant_id: UUID,
    current: tuple[AuthService, WebSession],
    purpose: str,
    *,
    selection: AccountSelection | None = None,
    identity_id: UUID | None = None,
    refresh: AccountRefresh | None = None,
) -> str:
    service, principal = current
    with require_tenant(
        "stores:read", tenant_id, service=service, principal=principal
    ) as scope:
        identities = IdentityService(
            scope.session, request.state._tvt_account_budget.remaining
        )
        generation = 0
        if identity_id is not None:
            local = identities.describe(identity_id)
            selection = AccountSelection(region=local.region, brand=local.brand)
            generation = local.generation
        if selection is None:
            raise AccountFailure()
        if refresh:
            require_user_kind(refresh.kind)
            generation = refresh.expected_generation
        ticket = identities.issue(
            purpose, selection, identity_id=identity_id, generation=generation
        )
    # require_tenant commits one-use issuance before worker redemption.
    return ticket


@router.post("/login", response_model=AccountIdentity, operation_id="tvtAccountLogin")
def login(
    body: AccountLogin, tenant_id: UUID, request: Request, current: Current
) -> AccountIdentity:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "login", selection=body)
    return worker.login(
        ticket,
        body,
        deadline_ms=request.state._tvt_account_budget.remaining(),
        correlation_id=request.state.request_id,
    )


@router.post(
    "/challenges/image",
    response_model=ImageChallengeView,
    operation_id="tvtAccountImageChallenge",
)
def image_challenge(
    body: AccountSelection, tenant_id: UUID, request: Request, current: Current
) -> ImageChallengeView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "image", selection=body)
    return worker.image_challenge(
        ticket,
        deadline_ms=request.state._tvt_account_budget.remaining(),
        correlation_id=request.state.request_id,
    )


@router.post(
    "/challenges/image/check",
    response_model=ImageCheckView,
    operation_id="tvtAccountImageCheck",
)
def check_image(
    body: ImageCheckRequest, tenant_id: UUID, request: Request, current: Current
) -> ImageCheckView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "check", selection=body)
    return worker.check_image(
        ticket,
        body,
        deadline_ms=request.state._tvt_account_budget.remaining(),
        correlation_id=request.state.request_id,
    )


@router.get(
    "/{identity_id}/me",
    response_model=AccountProfileView,
    operation_id="tvtAccountProfile",
)
def profile(
    identity_id: UUID, tenant_id: UUID, request: Request, current: Current
) -> AccountProfileView:
    worker = worker_for(request)
    ticket = ticket_for(request, tenant_id, current, "profile", identity_id=identity_id)
    return worker.profile(
        ticket,
        deadline_ms=request.state._tvt_account_budget.remaining(),
        correlation_id=request.state.request_id,
    )


@router.post(
    "/{identity_id}/refresh",
    response_model=AccountIdentity,
    operation_id="tvtAccountRefresh",
)
def refresh(
    body: AccountRefresh,
    identity_id: UUID,
    tenant_id: UUID,
    request: Request,
    current: Current,
) -> AccountIdentity:
    worker = worker_for(request)
    ticket = ticket_for(
        request, tenant_id, current, "renew", identity_id=identity_id, refresh=body
    )
    return worker.renew(
        ticket,
        body,
        deadline_ms=request.state._tvt_account_budget.remaining(),
        correlation_id=request.state.request_id,
    )


@router.post(
    "/{identity_id}/logout",
    response_model=AccountLogoutView,
    operation_id="tvtAccountLogout",
)
def logout(
    identity_id: UUID, tenant_id: UUID, request: Request, current: Current
) -> AccountLogoutView:
    worker = getattr(request.app.state, "tvt_account_worker", None)
    outcome: Literal["confirmed", "unknown", "not_attempted"] = "not_attempted"
    try:
        if worker is not None:
            ticket = ticket_for(
                request, tenant_id, current, "logout", identity_id=identity_id
            )
            outcome = worker.logout(
                ticket,
                deadline_ms=request.state._tvt_account_budget.remaining(),
                correlation_id=request.state.request_id,
            ).upstream_outcome
    except Exception:  # noqa: BLE001 -- uncertain remote outcome, local close is mandatory
        outcome = "unknown"
    finally:
        service, principal = current
        with require_tenant(
            "stores:read", tenant_id, service=service, principal=principal
        ) as scope:
            IdentityService(scope.session).close(identity_id)
    return AccountLogoutView(
        identity_id=identity_id,
        upstream_outcome=outcome,
        request_id=request.state.request_id,
    )
