"""Exact directory SQL authority. No network callback executes in a transaction."""

from __future__ import annotations

import math
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from wso_contracts.tvt.directory import DirectoryRequest, canonical_request
from wso_contracts.tvt.identity import ScopeLabel, TokenKind, TvtIdentityRef

from wso_core.secrets import Envelope, KeyProvider, SecretCipher, SecretRejected

from .account_projection import AccountFailure
from .flow_admission import _bound, _remaining, _sql_boundary
from .ports import PrivateToken
from .token_vault import AccountLease, private_text

_SEAL = object()


@dataclass(frozen=True, slots=True)
class DirectoryPolicy:
    region: str
    brand: str
    profile_id: str
    consent_version: str

    def __post_init__(self) -> None:
        for value in (self.region, self.brand, self.profile_id, self.consent_version):
            TypeAdapter(ScopeLabel).validate_python(value)


@dataclass(frozen=True, slots=True)
class DirectoryLease:
    value: str = field(repr=False)
    method: str
    query: str = field(repr=False)
    profile_id: str
    consent_version: str
    tenant_id: UUID
    actor_id: UUID
    identity_id: UUID
    region: str
    brand: str
    generation: int
    _seal: object = field(repr=False, compare=False)


class DirectoryTicketIssuer:
    """API-side: call within real tenant_session; commit before worker dispatch."""

    def __init__(self, session: Session, remaining: Callable[[], int]) -> None:
        self._session, self._remaining = session, remaining

    @_sql_boundary
    def issue(self, session_digest: str, method: str, body: DirectoryRequest) -> str:
        query = None
        try:
            query = canonical_request(method, body)
        except (ValueError, TypeError):
            pass
        if (
            query is None
            or type(session_digest) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", session_digest)
        ):
            raise AccountFailure("ACCOUNT_DENIED", 404)
        left = min(self._remaining(), _remaining())
        if left < 1:
            raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
        _bound(self._session, left)
        result: str | None = self._session.execute(
            text(
                "SELECT public.wso_tvt_directory_issue(:session,:method,CAST(:query AS jsonb))"
            ),
            {"session": session_digest, "method": method, "query": query},
        ).scalar_one()
        if self._remaining() < 1:
            raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
        if type(result) is not str or not re.fullmatch(r"[0-9a-f]{64}", result):
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return result


class DirectoryAdmission:
    """Worker-only fixed functions; policy is trusted deployment configuration."""

    def __init__(
        self,
        worker_url: str,
        policies: tuple[DirectoryPolicy, ...],
        provider: KeyProvider,
    ) -> None:
        if (
            not worker_url.startswith("postgresql+psycopg://")
            or type(policies) is not tuple
            or not 1 <= len(policies) <= 64
            or any(type(p) is not DirectoryPolicy for p in policies)
            or len({(p.region, p.brand) for p in policies}) != len(policies)
        ):
            raise AccountFailure()
        self._cipher = SecretCipher(provider)
        self.policies = MappingProxyType({(p.region, p.brand): p for p in policies})
        self._engine = create_engine(
            worker_url, hide_parameters=True, poolclass=NullPool
        )

        @event.listens_for(self._engine, "do_connect")
        def bounded_connect(
            dialect: Any, conn_rec: Any, cargs: Any, cparams: Any
        ) -> None:
            cparams["connect_timeout"] = max(1, math.ceil(_remaining() / 1000))
            cparams["options"] = "-c statement_timeout=10000 -c lock_timeout=3000"

    def close(self) -> None:
        self._engine.dispose()

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        failed = False
        try:
            _remaining()
            with self._engine.begin() as db:
                _bound(db, _remaining())
                if (
                    db.execute(text("SELECT current_user")).scalar_one()
                    != "wso_connection_worker"
                ):
                    raise AccountFailure()
                yield db
                _remaining()
            _remaining()
        except SQLAlchemyError:
            failed = True
        if failed:
            raise AccountFailure() from None

    @staticmethod
    def _params(lease: DirectoryLease) -> dict[str, object]:
        if type(lease) is not DirectoryLease or lease._seal is not _SEAL:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return {
            "lease": lease.value,
            "method": lease.method,
            "query": lease.query,
            "profile": lease.profile_id,
            "version": lease.consent_version,
        }

    @staticmethod
    def _context(db: Connection, params: dict[str, object]) -> dict[str, Any]:
        _bound(db, _remaining())
        row = (
            db.execute(
                text(
                    "SELECT * FROM public.wso_tvt_directory_context(:lease,:method,CAST(:query AS jsonb),:profile,:version)"
                ),
                params,
            )
            .mappings()
            .one_or_none()
        )
        _remaining()
        if row is None:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return dict(row)

    @_sql_boundary
    def redeem(
        self, ticket: str, method: str, body: DirectoryRequest
    ) -> DirectoryLease:
        query = None
        try:
            query = canonical_request(method, body)
        except (ValueError, TypeError):
            pass
        if (
            query is None
            or type(ticket) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", ticket)
        ):
            raise AccountFailure("ACCOUNT_DENIED", 404)
        policy = self.policies.get((body.region, body.brand))
        if policy is None:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        params: dict[str, object] = {
            "ticket": ticket,
            "lease": secrets.token_hex(32),
            "method": method,
            "query": query,
            "profile": policy.profile_id,
            "version": policy.consent_version,
        }
        with self.transaction() as db:
            ok: bool = db.execute(
                text(
                    "SELECT public.wso_tvt_directory_redeem(:ticket,:lease,:method,CAST(:query AS jsonb),:profile,:version)"
                ),
                params,
            ).scalar_one()
            if ok is not True:
                raise AccountFailure("ACCOUNT_DENIED", 404)
            values = self._context(db, params)
        return DirectoryLease(
            value=str(params["lease"]),
            method=method,
            query=query,
            profile_id=policy.profile_id,
            consent_version=policy.consent_version,
            _seal=_SEAL,
            **values,
        )

    @_sql_boundary
    def check(self, lease: DirectoryLease) -> None:
        params = self._params(lease)
        with self.transaction() as db:
            current = self._context(db, params)
            if any(value != getattr(lease, key) for key, value in current.items()):
                raise AccountFailure("ACCOUNT_DENIED", 404)

    @_sql_boundary
    def claim(self, lease: DirectoryLease) -> AccountLease:
        params = self._params(lease)
        with self.transaction() as db:
            value: str | None = db.execute(
                text(
                    "SELECT public.wso_tvt_directory_claim(:lease,:method,CAST(:query AS jsonb),:profile,:version)"
                ),
                params,
            ).scalar_one()
            if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise AccountFailure("ACCOUNT_DENIED", 404)
        return AccountLease(
            value,
            lease.tenant_id,
            lease.actor_id,
            lease.identity_id,
            lease.region,
            lease.brand,
            lease.generation,
            "profile",
        )

    @_sql_boundary
    def snapshot(self, lease: DirectoryLease) -> PrivateToken:
        """Bounded current USER snapshot, committed before any transport I/O."""
        params = self._params(lease)
        with self.transaction() as db:
            current = self._context(db, params)
            if any(value != getattr(lease, key) for key, value in current.items()):
                raise AccountFailure("ACCOUNT_DENIED", 404)
            _bound(db, _remaining())
            row = (
                db.execute(
                    text(
                        "SELECT * FROM public.wso_tvt_directory_secret(:lease,:method,CAST(:query AS jsonb),:profile,:version)"
                    ),
                    params,
                )
                .mappings()
                .one_or_none()
            )
            _remaining()
            if (
                row is None
                or row["tenant_id"] != lease.tenant_id
                or row["generation"] != lease.generation
            ):
                raise AccountFailure("ACCOUNT_DENIED", 404)
            value = None
            try:
                value = self._cipher.open(
                    row["tenant_id"],
                    row["connection_id"],
                    row["version_id"],
                    Envelope(row["nonce"], row["ciphertext"]),
                )
            except SecretRejected:
                pass
            if value is None:
                raise AccountFailure("ACCOUNT_DENIED", 404)
            try:
                result = PrivateToken(
                    TvtIdentityRef(
                        tenant_id=lease.tenant_id,
                        actor_user_id=lease.actor_id,
                        identity_id=lease.identity_id,
                    ),
                    TokenKind.USER,
                    private_text(value),
                )
                _remaining()
                current = self._context(db, params)
                if any(item != getattr(lease, key) for key, item in current.items()):
                    raise AccountFailure("ACCOUNT_DENIED", 404)
                _remaining()
            finally:
                del value
        return result

    @_sql_boundary
    def publish(self, lease: DirectoryLease) -> None:
        params = self._params(lease)
        with self.transaction() as db:
            if (
                db.execute(
                    text(
                        "SELECT public.wso_tvt_directory_publish(:lease,:method,CAST(:query AS jsonb),:profile,:version)"
                    ),
                    params,
                ).scalar_one()
                is not True
            ):
                raise AccountFailure("ACCOUNT_DENIED", 404)

    @_sql_boundary
    def dispose(self, lease: DirectoryLease) -> None:
        params = self._params(lease)
        with self.transaction() as db:
            db.execute(text("SELECT public.wso_tvt_directory_dispose(:lease)"), params)
