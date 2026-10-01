"""Startup routes reuse T03 sessions, CSRF and consumed tenant authority."""

from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from wso_contracts.tvt.startup import (
    ConsentUpdate,
    PreferenceUpdate,
    StartupBootstrap,
    StartupConsent,
    StartupErrorEnvelope,
)
from wso_core.tvt.startup import (
    StartupFailure,
    StartupProfile,
    StartupRepository,
    load_profile,
)

from wso_api.auth import (
    SESSION_COOKIE,
    AuthFailure,
    AuthService,
    WebSession,
    auth_service,
    require_csrf,
)
from wso_api.stores.router import require_tenant


class StartupRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        if not self.methods or self.methods.isdisjoint({"POST", "PUT"}):
            return handler

        async def authenticated_handler(request: Request) -> Response:
            # FastAPI parses JSON before dependencies. Establish the real T03
            # session first, outside that parser but inside canonical handlers.
            request.state._tvt_startup_authenticated = await run_in_threadpool(
                _authenticate, request
            )
            return await handler(request)

        return authenticated_handler


router = APIRouter(
    prefix="/api/v1/tvt",
    route_class=StartupRoute,
    tags=["tvt-startup"],
    responses={
        status: {"model": StartupErrorEnvelope}
        for status in (401, 403, 404, 409, 422, 500, 503)
    },
)


def configure_startup(app: FastAPI) -> None:
    app.state.tvt_startup_profile = load_profile()

    @app.exception_handler(StartupFailure)
    async def startup_failure(request: Request, exc: StartupFailure) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": "Startup unavailable"
                    if exc.status == 503
                    else "Request failed",
                },
                "request_id": request.state.request_id,
            },
        )


def _authenticate(request: Request) -> tuple[AuthService, WebSession]:
    # Anonymous requests stay signed out even in an unconfigured deployment.
    if not request.cookies.get(SESSION_COOKIE):
        raise AuthFailure()
    service = auth_service(request)
    return service, service.authenticate(request)


def authenticated(request: Request) -> tuple[AuthService, WebSession]:
    # Reuse only the pair established by StartupRoute in this same request.
    # GET has no body parser to precede and authenticates through its dependency.
    established = getattr(request.state, "_tvt_startup_authenticated", None)
    if established is not None:
        return cast(tuple[AuthService, WebSession], established)
    return _authenticate(request)


CurrentSession = Annotated[tuple[AuthService, WebSession], Depends(authenticated)]


@contextmanager
def repository(
    request: Request, tenant_id: UUID, service: AuthService, principal: WebSession
) -> Iterator[StartupRepository]:
    profile = getattr(request.app.state, "tvt_startup_profile", None)
    if not isinstance(profile, StartupProfile):
        raise StartupFailure()
    # This is the existing membership-only operation. Account metadata has its
    # own explicit domain intersection inside the checked SQL projection.
    with require_tenant(
        "stores:read", tenant_id, service=service, principal=principal
    ) as scope:
        yield StartupRepository(scope.session, profile)


@router.get("/bootstrap", response_model=StartupBootstrap, operation_id="tvtBootstrap")
def bootstrap(
    tenant_id: UUID, request: Request, current: CurrentSession
) -> StartupBootstrap:
    service, principal = current
    with repository(request, tenant_id, service, principal) as repo:
        return repo.bootstrap(tenant_id)


@router.post("/consent", response_model=StartupConsent, operation_id="tvtConsent")
def consent(
    body: ConsentUpdate, tenant_id: UUID, request: Request, current: CurrentSession
) -> StartupConsent:
    service, principal = current
    require_csrf(request, service, principal)
    with repository(request, tenant_id, service, principal) as repo:
        return repo.record_consent(body)


@router.put(
    "/preferences", response_model=PreferenceUpdate, operation_id="tvtPreferences"
)
def preferences(
    body: PreferenceUpdate, tenant_id: UUID, request: Request, current: CurrentSession
) -> PreferenceUpdate:
    service, principal = current
    require_csrf(request, service, principal)
    with repository(request, tenant_id, service, principal) as repo:
        return repo.preferences(body)
