"""Identity bootstrap and explicit authorization for tenant transactions."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from wso_core.db_budget import AuthorizationDbControls

_ISSUER_KEY = object()


@dataclass(frozen=True)
class TenantAuthorization:
    """A tenant choice returned by a verified-principal bootstrap lookup."""

    tenant_id: UUID
    user_id: UUID
    role: str
    _issuer_key: object = field(repr=False, compare=False)
    _grant_token: str | None = field(default=None, repr=False, compare=False)

    def _valid_for(self, tenant_id: UUID) -> bool:
        return (
            self._issuer_key is _ISSUER_KEY
            and self.tenant_id == tenant_id
            and self._grant_token is not None
        )


@lru_cache(maxsize=1)
def _identity_factory() -> sessionmaker[Session]:
    url = os.environ["WSO_IDENTITY_DATABASE_URL"]
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("identity database must use postgresql+psycopg")
    return sessionmaker(create_engine(url, pool_pre_ping=True, hide_parameters=True))


class IdentityLookup:
    def __init__(self, session: Session) -> None:
        self._session = session

    def user_id(self) -> UUID | None:
        """Return the verified principal's provisioned ID, including without tenants."""
        return self._session.execute(
            text(
                "SELECT id FROM users "
                "WHERE oidc_issuer = current_setting('app.oidc_issuer', true) "
                "AND oidc_subject = current_setting('app.oidc_subject', true)"
            )
        ).scalar_one_or_none()

    def authorize_tenant(self, tenant_id: UUID) -> TenantAuthorization:
        """Issue a one-use grant; exit the identity context before consuming it.

        ``list_tenants`` is display metadata. Each tenant transaction needs a
        fresh grant, even when retrying work that previously rolled back.
        """
        if not isinstance(tenant_id, UUID):
            raise PermissionError("tenant selection is not authorized")
        row = self._session.execute(
            text("SELECT * FROM public.wso_issue_tenant_grant(:tenant_id)"),
            {"tenant_id": tenant_id},
        ).one_or_none()
        if row is None:
            raise PermissionError("tenant selection is not authorized")
        return TenantAuthorization(
            tenant_id, row.user_id, row.role, _ISSUER_KEY, row.grant_token
        )

    def list_tenants(self) -> list[TenantAuthorization]:
        rows = self._session.execute(
            text(
                "SELECT m.tenant_id, m.user_id, m.role "
                "FROM memberships AS m JOIN users AS u ON u.id = m.user_id "
                "WHERE u.oidc_issuer = current_setting('app.oidc_issuer', true) "
                "AND u.oidc_subject = current_setting('app.oidc_subject', true) "
                "ORDER BY m.tenant_id"
            )
        )
        return [
            TenantAuthorization(row.tenant_id, row.user_id, row.role, _ISSUER_KEY)
            for row in rows
        ]


@contextmanager
def identity_session(
    verified_issuer: str,
    verified_subject: str,
    *,
    session_factory: sessionmaker[Session] | None = None,
    db_controls: AuthorizationDbControls | None = None,
) -> Iterator[IdentityLookup]:
    """Look up memberships after the caller has verified an OIDC token.

    The backend must never pass unverified request fields as these arguments.
    PostgreSQL settings alone do not authenticate a principal.
    """
    if not verified_issuer or not verified_subject:
        raise ValueError("verified issuer and subject are required")
    if db_controls is not None:
        if session_factory is not None:
            raise ValueError(
                "bounded identity provider and legacy factory are ambiguous"
            )
        db_controls.deadline.remaining_ms()
        transaction = db_controls.factories.identity(deadline=db_controls.deadline)
    else:
        factory = session_factory or _identity_factory()
        transaction = factory.begin()
    with transaction as session:
        role: str = session.execute(text("SELECT current_user")).scalar_one()
        if role != "wso_identity_bootstrap":
            raise PermissionError("identity connection must use bootstrap role")
        session.execute(
            text("SELECT set_config('app.oidc_issuer', :issuer, true)"),
            {"issuer": verified_issuer},
        )
        session.execute(
            text("SELECT set_config('app.oidc_subject', :subject, true)"),
            {"subject": verified_subject},
        )
        yield IdentityLookup(session)
