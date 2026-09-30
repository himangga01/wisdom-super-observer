from collections.abc import Callable, Mapping
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from wso_api.auth import configure_auth
from wso_api.auth import router as auth_router
from wso_api.stores.router import router as stores_router


def _error_response(
    request: Request, status_code: int, code: str, message: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "request_id": request.state.request_id,
        },
    )


def create_app(
    readiness_checks: Mapping[str, Callable[[], bool]] | None = None,
) -> FastAPI:
    app = FastAPI()
    checks = dict(readiness_checks or {})
    configure_auth(app)
    app.include_router(auth_router)
    app.include_router(stores_router)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - remove internal details from public errors
            response = _error_response(
                request, 500, "internal_error", "Internal server error"
            )
        response.headers["X-Request-ID"] = request.state.request_id
        path = request.url.path
        if path in {"/api/v1/me", "/api/v1/stores"} or path.startswith(
            ("/api/v1/auth/", "/api/v1/stores/")
        ):
            response.headers["Cache-Control"] = "no-store"
            vary = response.headers.get("Vary", "")
            if "cookie" not in {value.strip().lower() for value in vary.split(",")}:
                response.headers["Vary"] = f"{vary}, Cookie" if vary else "Cookie"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error_response(request, 404, "not_found", "Not found")
        return _error_response(request, exc.status_code, "http_error", "Request failed")

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(request, 422, "validation_error", "Invalid request")

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        dependencies: dict[str, str] = {}
        for name, check in checks.items():
            try:
                dependencies[name] = "ready" if check() else "unavailable"
            except Exception:  # noqa: BLE001 - unavailable means any check failure
                dependencies[name] = "unavailable"
        healthy = bool(checks) and all(
            state == "ready" for state in dependencies.values()
        )
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ready" if healthy else "unavailable",
                "dependencies": dependencies,
            },
        )

    return app
