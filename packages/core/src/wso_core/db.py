"""Tenant-scoped SQLAlchemy models and transaction boundaries."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    create_engine,
    exists,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.sql import func

from wso_core.tenancy import TenantAuthorization


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_users_oidc_principal"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    oidc_issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    oidc_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (Index("ix_memberships_user_id", "user_id"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_stores_tenant_id_id"),
        Index("ix_stores_tenant_active", "tenant_id", "active"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Seoul"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StoreMembership(Base):
    __tablename__ = "store_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "store_id"],
            ["stores.tenant_id", "stores.id"],
            name="fk_store_memberships_tenant_store",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_store_memberships_tenant_user",
        ),
        Index("ix_store_memberships_tenant_user", "tenant_id", "user_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            name="fk_audit_events_tenant_actor",
        ),
        Index("ix_audit_events_tenant_occurred", "tenant_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


@lru_cache(maxsize=1)
def _app_factory() -> sessionmaker[Session]:
    url = os.environ["WSO_APP_DATABASE_URL"]
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("application database must use postgresql+psycopg")
    return sessionmaker(create_engine(url, pool_pre_ping=True))


@contextmanager
def tenant_session(
    tenant_id: UUID,
    *,
    authorization: TenantAuthorization | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> Iterator[Session]:
    """Open a tenant transaction for a bootstrap-authorized tenant choice.

    This helper requires a trusted app process. The custom PostgreSQL tenant
    setting is not an unforgeable claim for arbitrary SQL under ``wso_app``.
    """
    if (
        not isinstance(tenant_id, UUID)
        or not isinstance(authorization, TenantAuthorization)
        or not authorization._valid_for(tenant_id)
    ):
        raise PermissionError("tenant selection is not authorized")
    factory = session_factory or _app_factory()
    with factory.begin() as session:
        role: str = session.execute(text("SELECT current_user")).scalar_one()
        if role != "wso_app":
            raise PermissionError("tenant connection must use application role")
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        authorized: bool = session.execute(
            text(
                "SELECT public.wso_validate_tenant_authorization("
                ":tenant_id, :user_id, :role)"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": authorization.user_id,
                "role": authorization.role,
            },
        ).scalar_one()
        if not authorized:
            raise PermissionError("tenant membership was revoked or changed")
        session.info["authorized_user_id"] = authorization.user_id
        yield session


class StoreRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_visible(self, user_id: UUID) -> list[Store]:
        """Owners see tenant stores; managers and staff see assigned stores."""
        if self._session.info.get("authorized_user_id") != user_id:
            raise PermissionError("repository user does not match tenant authorization")
        owner = exists(
            select(Membership.user_id).where(
                Membership.tenant_id == Store.tenant_id,
                Membership.user_id == user_id,
                Membership.role == "OWNER",
            )
        )
        assigned = exists(
            select(StoreMembership.user_id).where(
                StoreMembership.tenant_id == Store.tenant_id,
                StoreMembership.store_id == Store.id,
                StoreMembership.user_id == user_id,
            )
        )
        query = (
            select(Store)
            .where(Store.active.is_(True), owner | assigned)
            .order_by(Store.name, Store.id)
        )
        return list(self._session.scalars(query))
