"""Store selection intersects verified tenant membership and store assignments."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from wso_core.db import StoreRepository, tenant_session
from wso_core.db_budget import AuthorizationDbControls, DbUnavailable

from wso_api.auth import AuthFailure, AuthService, Service, WebSession


@dataclass(frozen=True)
class TenantScope:
    tenant_id: UUID
    user_id: UUID
    role: str
    session: Session


@dataclass(frozen=True)
class StoreScope:
    tenant: TenantScope
    store: StoreView


class StoreView(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    timezone: str
    active: bool

    model_config = {"from_attributes": True}


class StoreList(BaseModel):
    items: list[StoreView]
    selected_tenant_id: UUID


@contextmanager
def require_tenant(
    action: str,
    tenant_id: UUID,
    *,
    service: AuthService,
    principal: WebSession,
    db_controls: AuthorizationDbControls | None = None,
) -> Iterator[TenantScope]:
    if action not in {
        "stores:read",
        "connections:read",
        "connections:write",
        "jobs:read",
        "jobs:cancel",
        "assets:read",
        "assets:write",
    }:
        raise HTTPException(status_code=403)
    try:
        identity = (
            service.identity(principal)
            if db_controls is None
            else service.identity(principal, db_controls=db_controls)
        )
        with identity as lookup:
            if lookup.user_id() != principal.user_id:
                raise AuthFailure()
            choice = lookup.authorize_tenant(tenant_id)
        # Commit issuance before the application role consumes the one-use grant.
        if choice.role not in {"OWNER", "MANAGER", "STAFF"}:
            raise PermissionError("unsupported role")
        if action.startswith(("connections:", "assets:")) and choice.role != "OWNER":
            raise HTTPException(status_code=403)
        with tenant_session(
            tenant_id,
            authorization=choice,
            session_factory=service.tenant_factory if db_controls is None else None,
            db_controls=db_controls,
        ) as db:
            yield TenantScope(tenant_id, choice.user_id, choice.role, db)
    except DbUnavailable as exc:
        raise AuthFailure(503, "auth_unavailable") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=404) from exc


def require_store(action: str, store_id: UUID, *, tenant: TenantScope) -> StoreScope:
    if action not in {"stores:read", "jobs:read", "jobs:cancel"}:
        raise HTTPException(status_code=403)
    for store in StoreRepository(tenant.session).list_visible(tenant.user_id):
        if store.id == store_id:
            return StoreScope(tenant, StoreView.model_validate(store))
    raise HTTPException(status_code=404)


router = APIRouter(prefix="/api/v1/stores", tags=["stores"])


@router.get("", response_model=StoreList)
def stores(
    tenant_id: UUID, request: Request, response: Response, service: Service
) -> StoreList:
    principal = service.authenticate(request)
    with require_tenant(
        "stores:read", tenant_id, service=service, principal=principal
    ) as scope:
        items = [
            StoreView.model_validate(store)
            for store in StoreRepository(scope.session).list_visible(scope.user_id)
        ]
    response.headers["Cache-Control"] = "no-store"
    return StoreList(items=items, selected_tenant_id=tenant_id)


@router.get("/{store_id}", response_model=StoreView)
def store(
    store_id: UUID,
    tenant_id: UUID,
    request: Request,
    response: Response,
    service: Service,
) -> StoreView:
    principal = service.authenticate(request)
    with require_tenant(
        "stores:read", tenant_id, service=service, principal=principal
    ) as scope:
        selected = require_store("stores:read", store_id, tenant=scope).store
    response.headers["Cache-Control"] = "no-store"
    return selected
