"""Authenticated private image routes; no storage identifiers enter the wire."""

from __future__ import annotations

import hmac
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from wso_contracts.assets import Asset, BeginUpload, DownloadTicket, UploadSession
from wso_core.assets import (
    AssetAction,
    AssetActor,
    AssetFailure,
    AssetStore,
    AuthorizedTransactions,
    VerifiedDownload,
)
from wso_core.db_budget import DbDeadline, DbUnavailable
from wso_core.storage import IOBudget

from wso_api.assets.bootstrap import asset_runtime
from wso_api.auth import (
    SESSION_COOKIE,
    AuthFailure,
    AuthService,
    Service,
    require_csrf,
    token_digest,
)
from wso_api.stores.router import require_tenant

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])


def _authority(
    request: Request,
    service: AuthService,
    tenant_id: UUID,
    *,
    mutation: bool,
    budget: IOBudget,
) -> tuple[AssetActor, AuthorizedTransactions]:
    authorization = asset_runtime(request).authorization
    try:
        controls = authorization.for_deadline(
            DbDeadline(min(budget.deadline_monotonic, time.monotonic() + 5))
        )
        principal = service.authenticate(request, db_controls=controls)
    except DbUnavailable:
        raise AssetFailure(503, "ASSET_AUTHORIZATION_TIMEOUT") from None
    if mutation:
        require_csrf(request, service, principal)
    digest = token_digest(request.cookies[SESSION_COOKIE])
    actor = AssetActor(
        tenant_id,
        principal.user_id,
        digest,
        principal.expires_at,
        request.state.request_id,
    )

    @contextmanager
    def transactions(
        action: AssetAction, *, deadline_monotonic: float
    ) -> Iterator[Session]:
        try:
            # One shared cap covers cookie, identity, grant, redemption and asset SQL.
            controls = authorization.for_deadline(
                DbDeadline(
                    min(
                        deadline_monotonic,
                        budget.deadline_monotonic,
                        time.monotonic() + 5,
                    )
                )
            )
            current = service.authenticate(request, db_controls=controls)
            if current.user_id != actor.user_id or not hmac.compare_digest(
                token_digest(request.cookies[SESSION_COOKIE]), actor.session_digest
            ):
                raise AssetFailure(401, "ASSET_AUTHENTICATION_REQUIRED")
            if action == "assets:write":
                require_csrf(request, service, current)
            with require_tenant(
                action,
                tenant_id,
                service=service,
                principal=current,
                db_controls=controls,
            ) as scope:
                controls.deadline.remaining_ms()
                yield scope.session
                controls.deadline.remaining_ms()
            controls.deadline.remaining_ms()
        except DbUnavailable:
            raise AssetFailure(503, "ASSET_AUTHORIZATION_TIMEOUT") from None
        except AuthFailure as error:
            raise AssetFailure(
                error.status,
                "ASSET_AUTHORIZATION_TIMEOUT"
                if error.status == 503
                else "ASSET_AUTHENTICATION_REQUIRED",
            ) from None
        except HTTPException as error:
            if error.status_code not in (401, 403, 404, 503):
                raise
            raise AssetFailure(
                error.status_code,
                "ASSET_DENIED"
                if error.status_code == 403
                else "ASSET_NOT_FOUND"
                if error.status_code == 404
                else "ASSET_UNAVAILABLE",
            ) from None

    return actor, transactions


def _store(
    request: Request,
    service: AuthService,
    tenant_id: UUID,
    *,
    mutation: bool,
    verification: bool = False,
) -> AssetStore:
    runtime = asset_runtime(request)
    budget = IOBudget(
        time.monotonic()
        + (runtime.configuration.policy.verification_seconds if verification else 5)
    )
    actor, transactions = _authority(
        request, service, tenant_id, mutation=mutation, budget=budget
    )
    return runtime.store_for(actor=actor, transactions=transactions, budget=budget)


@router.post("", response_model=UploadSession, status_code=201)
def begin_upload(
    body: BeginUpload, request: Request, response: Response, service: Service
) -> UploadSession:
    store = _store(request, service, body.scope.tenant_id, mutation=True)
    result = store.begin_upload(
        body.scope,
        body.purpose,
        body.content_type,
        body.byte_size,
        body.checksum,
        parent_asset_id=body.parent_asset_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.put(
    "/{asset_id}/content",
    status_code=204,
    openapi_extra={
        "parameters": [
            {
                "name": "X-Upload-Session",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        ],
        "requestBody": {
            "required": True,
            "content": {
                "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                "image/png": {"schema": {"type": "string", "format": "binary"}},
            },
        },
    },
)
async def put_content(
    asset_id: UUID, tenant_id: UUID, request: Request, service: Service
) -> Response:
    runtime = asset_runtime(request)
    budget = IOBudget(time.monotonic() + runtime.configuration.policy.upload_seconds)
    actor, transactions = await anyio.to_thread.run_sync(
        lambda: _authority(request, service, tenant_id, mutation=True, budget=budget)
    )
    try:
        session_id = UUID(request.headers.get("X-Upload-Session", ""))
        length = request.headers.get("Content-Length")
        if length is not None and (
            not length.isascii() or not length.isdecimal() or len(length) > 10
        ):
            raise ValueError("invalid length")
        content_length = int(length) if length is not None else None
    except ValueError:
        raise AssetFailure(422, "ASSET_INVALID") from None
    gateway = runtime.gateway_for(actor=actor, transactions=transactions, budget=budget)
    await gateway.put_content(
        asset_id,
        session_id,
        request.stream(),
        content_type=request.headers.get("Content-Type", ""),
        content_length=content_length,
        content_encoding=request.headers.get("Content-Encoding"),
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/{asset_id}/complete", response_model=Asset)
def complete_upload(
    asset_id: UUID,
    tenant_id: UUID,
    request: Request,
    response: Response,
    service: Service,
) -> Asset:
    result = _store(
        request, service, tenant_id, mutation=True, verification=True
    ).complete_upload(asset_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/{asset_id}", response_model=Asset)
def get_asset(
    asset_id: UUID,
    tenant_id: UUID,
    request: Request,
    response: Response,
    service: Service,
) -> Asset:
    result = _store(request, service, tenant_id, mutation=False).get(asset_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.delete("/{asset_id}", response_model=Asset, status_code=202)
def delete_asset(
    asset_id: UUID,
    tenant_id: UUID,
    request: Request,
    response: Response,
    service: Service,
) -> Asset:
    result = _store(request, service, tenant_id, mutation=True).delete_asset(asset_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post(
    "/{asset_id}/download-tickets", response_model=DownloadTicket, status_code=201
)
def issue_ticket(
    asset_id: UUID,
    tenant_id: UUID,
    request: Request,
    response: Response,
    service: Service,
) -> DownloadTicket:
    store = _store(request, service, tenant_id, mutation=True)
    result = store.authorize_download(store.actor.user_id, asset_id)
    response.headers["Cache-Control"] = "no-store"
    return result


class _DownloadResponse(StreamingResponse):
    def __init__(self, download: VerifiedDownload) -> None:
        self._download = download
        extension = "png" if download.content_type == "image/png" else "jpg"
        super().__init__(
            download.iter_bytes(),
            media_type=download.content_type,
            headers={
                "Content-Length": str(download.byte_size),
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="asset.{extension}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            with anyio.fail_after(
                max(0, self._download.deadline_monotonic - time.monotonic())
            ):
                await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(
                    self._download.close, abandon_on_cancel=False
                )


@router.get(
    "/{asset_id}/content",
    response_class=Response,
    responses={
        200: {
            "description": "Verified private image bytes",
            "content": {
                "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                "image/png": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
    openapi_extra={
        "parameters": [
            {
                "name": "X-Asset-Ticket",
                "in": "header",
                "required": True,
                "schema": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                    "minLength": 64,
                    "maxLength": 64,
                },
            }
        ]
    },
)
def get_content(
    asset_id: UUID, tenant_id: UUID, request: Request, service: Service
) -> Response:
    runtime = asset_runtime(request)
    budget = IOBudget(time.monotonic() + runtime.configuration.policy.download_seconds)
    actor, transactions = _authority(
        request, service, tenant_id, mutation=False, budget=budget
    )
    if "Range" in request.headers:
        raise HTTPException(416)
    download = (
        asset_runtime(request)
        .gateway_for(actor=actor, transactions=transactions, budget=budget)
        .open_download(asset_id, request.headers.get("X-Asset-Ticket", ""))
    )
    request.scope["wso_asset_download_deadline"] = download.deadline_monotonic
    return _DownloadResponse(download)


class AssetDeadlineMiddleware:
    """Root registers this outermost so the deadline includes the real ASGI send."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def bounded_send(message: Message) -> None:
            deadline: Any = scope.get("wso_asset_download_deadline")
            if deadline is None:
                await send(message)
            else:
                with anyio.fail_after(max(0, float(deadline) - time.monotonic())):
                    await send(message)

        await self.app(scope, receive, bounded_send)
