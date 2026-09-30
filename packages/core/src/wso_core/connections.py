"""Owner-authorized connection metadata and encrypt-only credential writes."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from wso_core.secrets import KeyProvider, SecretCipher, SecretRejected


class ConnectionFailure(Exception):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__("connection request failed")


class ConnectionView(BaseModel):
    id: UUID
    tenant_id: UUID
    kind: Literal["TVT_ACCOUNT", "TVT_DEVICE", "TYCO_ACCOUNT"]
    alias: str
    site: str
    status: Literal["NOT_VERIFIED", "DISCONNECTED"]
    last_success: datetime | None
    generation: int
    store_ids: list[UUID]


class SecretStore:
    """The API write path has no saved-secret read method or worker DB URL."""

    def __init__(self, provider: KeyProvider) -> None:
        self._cipher = SecretCipher(provider)

    def prepare(
        self, tenant_id: UUID, connection_id: UUID, plaintext: bytes
    ) -> dict[str, Any]:
        version = uuid4()
        envelope = self._cipher.seal(tenant_id, connection_id, version, plaintext)
        return {
            "version": version,
            "nonce": envelope.nonce,
            "cipher": envelope.ciphertext,
        }


class ConnectionService:
    def __init__(self, session: Session, provider: KeyProvider | None = None) -> None:
        self._session, self._provider = session, provider

    def list(self) -> list[ConnectionView]:
        rows = self._session.execute(
            text(
                "SELECT c.*, ARRAY(SELECT sc.store_id FROM store_connections sc WHERE sc.connection_id=c.id ORDER BY sc.store_id) AS store_ids FROM connections c ORDER BY c.alias,c.id"
            )
        ).mappings()
        return [ConnectionView.model_validate(dict(row)) for row in rows]

    def get(self, connection_id: UUID | str) -> ConnectionView:
        for row in self.list():
            if str(row.id) == str(connection_id):
                return row
        raise ConnectionFailure(404)

    def mutate(
        self,
        action: str,
        data: dict[str, Any],
        *,
        connection_id: UUID | None = None,
        expected_generation: int = 0,
        credentials: bytes | None = None,
        correlation_id: str | None = None,
    ) -> ConnectionView | None:
        connection_id = connection_id or uuid4()
        # Read protected scope from DB, never trust a caller-supplied tenant ID.
        tenant: UUID = self._session.execute(
            text("SELECT public.wso_current_tenant_id()")
        ).scalar_one()
        encrypted = {"version": None, "nonce": None, "cipher": None}
        if credentials is not None:
            if self._provider is None:
                raise SecretRejected()
            encrypted = SecretStore(self._provider).prepare(
                tenant, connection_id, credentials
            )
        try:
            self._session.execute(
                text(
                    "SELECT public.wso_mutate_connection(:id,:expected,:action,CAST(:data AS jsonb),:version,:nonce,:cipher,:correlation)"
                ),
                {
                    "id": connection_id,
                    "expected": expected_generation,
                    "action": action,
                    "data": json.dumps(data),
                    "correlation": correlation_id,
                    **encrypted,
                },
            )
        except DBAPIError as exc:
            state = getattr(exc.orig, "sqlstate", None)
            statuses = {
                "P0002": 404,
                "42501": 403,
                "40001": 409,
                "22023": 422,
                "23514": 422,
                "23502": 422,
            }
            if state in statuses:
                raise ConnectionFailure(statuses[state]) from None
            raise
        return None if action == "delete" else self.get(connection_id)

    def disconnect(
        self, connection_id: UUID, expected_generation: int
    ) -> ConnectionView | None:
        return self.mutate(
            "disconnect",
            {},
            connection_id=connection_id,
            expected_generation=expected_generation,
        )

    def authorize_worker(self, connection_id: UUID | str, generation: int) -> str:
        token: str | None = self._session.execute(
            text("SELECT public.wso_issue_connection_handle(:id,:generation)"),
            {"id": connection_id, "generation": generation},
        ).scalar_one()
        if token is None:
            raise SecretRejected()
        return str(token)
