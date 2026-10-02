"""Typed SQL capabilities for W06, separate from saved-account credentials."""

from __future__ import annotations

import math
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import wraps
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from wso_contracts.tvt.account_flows import AccountFlowReference, AccountFlowStart

from .account_projection import AccountFailure
from .token_vault import remaining_budget

_SEAL = object()
OPERATIONS = frozenset(
    {
        "start",
        "state",
        "existence",
        "image",
        "issue_code",
        "register",
        "recover",
        "cancel",
    }
)


def _sql_boundary[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    @wraps(operation)
    def checked(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return operation(*args, **kwargs)
        except AccountFailure as error:
            code, status = error.code, error.status
        except SQLAlchemyError:
            code, status = "ACCOUNT_UNAVAILABLE", 503
        # A contextmanager can attach its injected SQL exception to a yielded
        # failure even after `from None`. Recreate at the outside call boundary.
        raise AccountFailure(code, status) from None

    return checked


def _remaining() -> int:
    value = remaining_budget()
    if value is None:
        return 10000
    if value < 1:
        raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
    return min(value, 10000)


def _bound(db: Connection | Session, milliseconds: int) -> None:
    db.execute(
        text(
            "SELECT set_config('statement_timeout',:s,true),set_config('lock_timeout',:l,true)"
        ),
        {"s": str(milliseconds), "l": str(min(milliseconds, 3000))},
    )


@dataclass(frozen=True, slots=True)
class FlowLease:
    value: str = field(repr=False)
    tenant_id: UUID
    actor_id: UUID
    session_digest: str = field(repr=False)
    flow_id: UUID
    region: str
    brand: str
    purpose: str
    generation: int
    state: str
    expires_at: datetime
    operation: str
    _seal: object = field(repr=False, compare=False)
    key_commitment: str = field(repr=False)


class FlowTicketIssuer:
    """API-side, called inside an actual consumed tenant transaction.

    session_digest must be T03 token_digest(authenticated request cookie), never
    a browser DTO field. SQL independently proves actor/session/policy consent.
    The caller commits the tenant transaction before dispatching this ticket.
    """

    def __init__(self, session: Session, remaining: Callable[[], int]) -> None:
        self._session, self._remaining = session, remaining

    def issue(
        self,
        session_digest: str,
        operation: str,
        body: AccountFlowStart | AccountFlowReference,
    ) -> str:
        if (
            operation not in OPERATIONS
            or type(session_digest) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", session_digest)
        ):
            raise AccountFailure("ACCOUNT_DENIED", 404)
        if (operation == "start") != isinstance(body, AccountFlowStart):
            raise AccountFailure("ACCOUNT_DENIED", 404)
        result: str | None = None
        try:
            _bound(self._session, min(self._remaining(), _remaining()))
            result = self._session.execute(
                text(
                    "SELECT public.wso_tvt_flow_issue(:session,:operation,:region,:brand,:purpose,:flow)"
                ),
                {
                    "session": session_digest,
                    "operation": operation,
                    "region": body.region,
                    "brand": body.brand,
                    "purpose": body.purpose,
                    "flow": body.flow_id
                    if isinstance(body, AccountFlowReference)
                    else None,
                },
            ).scalar_one()
            self._remaining()
        except SQLAlchemyError:
            pass
        if type(result) is not str or not re.fullmatch(r"[0-9a-f]{64}", result):
            raise AccountFailure("ACCOUNT_DENIED", 404) from None
        return result


class FlowAdmission:
    """Worker-only function calls; no tables, tokens, keys or network callbacks."""

    def __init__(self, worker_url: str, key_commitment: str) -> None:
        if (
            not worker_url.startswith("postgresql+psycopg://")
            or type(key_commitment) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", key_commitment)
        ):
            raise AccountFailure()
        self._key_commitment = key_commitment
        self._engine = create_engine(
            worker_url, hide_parameters=True, poolclass=NullPool
        )

        @event.listens_for(self._engine, "do_connect")
        def bounded_connect(
            dialect: Any, conn_rec: Any, cargs: Any, cparams: Any
        ) -> None:
            # NullPool eliminates pool queue waits. libpq has whole-second
            # connect timeouts; a post-connect budget check prevents late use.
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
        except SQLAlchemyError:
            failed = True
        if failed:
            raise AccountFailure() from None

    @staticmethod
    def _sealed(lease: FlowLease) -> None:
        if type(lease) is not FlowLease or lease._seal is not _SEAL:
            raise AccountFailure("ACCOUNT_DENIED", 404)

    def _context(self, db: Connection, value: str, operation: str) -> FlowLease:
        row = (
            db.execute(
                text(
                    "SELECT * FROM public.wso_tvt_flow_context(:lease,:operation,:key)"
                ),
                {"lease": value, "operation": operation, "key": self._key_commitment},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return FlowLease(value=value, operation=operation, _seal=_SEAL, **dict(row))

    @_sql_boundary
    def redeem(self, ticket: str, operation: str) -> FlowLease:
        if (
            type(ticket) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", ticket)
            or operation not in OPERATIONS
        ):
            raise AccountFailure("ACCOUNT_DENIED", 404)
        lease = secrets.token_hex(32)
        with self.transaction() as db:
            accepted: bool = db.execute(
                text(
                    "SELECT public.wso_tvt_flow_redeem(:ticket,:lease,:operation,:key)"
                ),
                {
                    "ticket": ticket,
                    "lease": lease,
                    "operation": operation,
                    "key": self._key_commitment,
                },
            ).scalar_one()
            if accepted is not True:
                raise AccountFailure("ACCOUNT_DENIED", 404)
            result = self._context(db, lease, operation)
        return result

    @_sql_boundary
    def check(self, lease: FlowLease) -> None:
        self._sealed(lease)
        with self.transaction() as db:
            current = self._context(db, lease.value, lease.operation)
            # Claim intentionally changes only state to durable UNKNOWN.
            if replace(current, state=lease.state) != lease:
                raise AccountFailure("ACCOUNT_DENIED", 404)

    @_sql_boundary
    def claim(self, lease: FlowLease, intent: str | None = None) -> str:
        self._sealed(lease)
        with self.transaction() as db:
            result: str = db.execute(
                text(
                    "SELECT public.wso_tvt_flow_claim(:lease,:operation,:intent,:key)"
                ),
                {
                    "lease": lease.value,
                    "operation": lease.operation,
                    "intent": intent,
                    "key": self._key_commitment,
                },
            ).scalar_one()
        if result not in {"CLAIMED", "UNKNOWN_OUTCOME", "BUSY"}:
            raise AccountFailure("ACCOUNT_DENIED", 404)
        return str(result)

    @_sql_boundary
    def publish(self, lease: FlowLease, state: str) -> FlowLease:
        self._sealed(lease)
        with self.transaction() as db:
            generation: int | None = db.execute(
                text(
                    "SELECT public.wso_tvt_flow_publish(:lease,:operation,:state,:key)"
                ),
                {
                    "lease": lease.value,
                    "operation": lease.operation,
                    "state": state,
                    "key": self._key_commitment,
                },
            ).scalar_one()
            if generation != lease.generation + 1:
                raise AccountFailure("ACCOUNT_DENIED", 404)
        return replace(lease, state=state, generation=generation)
