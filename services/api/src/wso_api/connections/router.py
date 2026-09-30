"""Owner connection lifecycle; credential inputs never appear in response DTOs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from wso_core.connections import ConnectionFailure, ConnectionService, ConnectionView
from wso_core.secrets import FileKeyProvider, KeyProvider, SecretRejected

from wso_api.auth import Service, require_csrf
from wso_api.stores.router import require_tenant


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    kind: Literal["TVT_ACCOUNT", "TVT_DEVICE", "TYCO_ACCOUNT"]
    alias: str = Field(min_length=1, max_length=200)
    site: str = Field(min_length=1, max_length=500)
    username: SecretStr = Field(min_length=1, max_length=512, repr=False)
    password: SecretStr = Field(min_length=1, max_length=4096, repr=False)
    store_ids: list[UUID] = Field(default_factory=list, max_length=100)


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    expected_generation: int = Field(ge=1, strict=True)


class ConnectionPatch(GenerationRequest):
    alias: str | None = Field(default=None, min_length=1, max_length=200)
    site: str | None = Field(default=None, min_length=1, max_length=500)
    username: SecretStr | None = Field(
        default=None, min_length=1, max_length=512, repr=False
    )
    password: SecretStr | None = Field(
        default=None, min_length=1, max_length=4096, repr=False
    )
    store_ids: list[UUID] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def complete_replacement(self) -> ConnectionPatch:
        if (self.username is None) != (self.password is None):
            raise ValueError("complete credentials required")
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("explicit null is unsupported")
        return self


class ConnectionList(BaseModel):
    items: list[ConnectionView]
    selected_tenant_id: UUID


def configure_connections(app: FastAPI, provider: KeyProvider | None = None) -> None:
    if provider is None and os.getenv("WSO_CONNECTION_KEY_FILE"):
        provider = FileKeyProvider(Path(os.environ["WSO_CONNECTION_KEY_FILE"]))
    app.state.connection_key_provider = provider


router = APIRouter(prefix="/api/v1/connections", tags=["connections"])


def credential_bytes(body: ConnectionCreate | ConnectionPatch) -> bytes | None:
    if body.username is None or body.password is None:
        return None
    return json.dumps(
        {
            "username": body.username.get_secret_value(),
            "password": body.password.get_secret_value(),
        },
        separators=(",", ":"),
    ).encode()


def mutate(
    action: str,
    tenant_id: UUID,
    request: Request,
    service: Service,
    body: ConnectionCreate | ConnectionPatch | GenerationRequest,
    connection_id: UUID | None = None,
) -> ConnectionView | None:
    principal = service.authenticate(request)
    require_csrf(request, service, principal)
    try:
        with require_tenant(
            "connections:write", tenant_id, service=service, principal=principal
        ) as scope:
            data = body.model_dump(
                mode="json",
                exclude={"username", "password", "expected_generation"},
                exclude_unset=True,
            )
            return ConnectionService(
                scope.session,
                getattr(request.app.state, "connection_key_provider", None),
            ).mutate(
                action,
                data,
                connection_id=connection_id,
                expected_generation=body.expected_generation
                if isinstance(body, GenerationRequest)
                else 0,
                credentials=credential_bytes(body)
                if isinstance(body, (ConnectionCreate, ConnectionPatch))
                else None,
                correlation_id=getattr(request.state, "request_id", None),
            )
    except ConnectionFailure as exc:
        raise HTTPException(exc.status) from None
    except SecretRejected:
        raise HTTPException(503) from None


@router.get("", response_model=ConnectionList)
def list_connections(
    tenant_id: UUID, request: Request, service: Service
) -> ConnectionList:
    principal = service.authenticate(request)
    with require_tenant(
        "connections:read", tenant_id, service=service, principal=principal
    ) as scope:
        return ConnectionList(
            items=ConnectionService(scope.session).list(), selected_tenant_id=tenant_id
        )


@router.get("/{connection_id}", response_model=ConnectionView)
def get_connection(
    connection_id: UUID, tenant_id: UUID, request: Request, service: Service
) -> ConnectionView:
    principal = service.authenticate(request)
    try:
        with require_tenant(
            "connections:read", tenant_id, service=service, principal=principal
        ) as scope:
            return ConnectionService(scope.session).get(connection_id)
    except ConnectionFailure as exc:
        raise HTTPException(exc.status) from None


@router.post("", response_model=ConnectionView, status_code=201)
def create_connection(
    body: ConnectionCreate, tenant_id: UUID, request: Request, service: Service
) -> ConnectionView | None:
    return mutate("create", tenant_id, request, service, body)


@router.patch("/{connection_id}", response_model=ConnectionView)
def update_connection(
    connection_id: UUID,
    body: ConnectionPatch,
    tenant_id: UUID,
    request: Request,
    service: Service,
) -> ConnectionView | None:
    return mutate("update", tenant_id, request, service, body, connection_id)


@router.post("/{connection_id}/disconnect", response_model=ConnectionView)
def disconnect_connection(
    connection_id: UUID,
    body: GenerationRequest,
    tenant_id: UUID,
    request: Request,
    service: Service,
) -> ConnectionView | None:
    return mutate("disconnect", tenant_id, request, service, body, connection_id)


@router.delete("/{connection_id}", status_code=204)
def delete_connection(
    connection_id: UUID,
    body: GenerationRequest,
    tenant_id: UUID,
    request: Request,
    service: Service,
) -> Response:
    mutate("delete", tenant_id, request, service, body, connection_id)
    return Response(status_code=204)
