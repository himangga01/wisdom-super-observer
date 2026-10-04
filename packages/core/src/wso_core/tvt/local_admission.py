"""Purpose-bound local SQL admission; API issuer/reader never decrypt secrets."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from wso_contracts.tvt.local_device import (
    LocalChannelView,
    LocalDeviceView,
    LocalVerifyRequest,
)

from wso_core.secrets import Envelope, KeyProvider, SecretCipher, SecretRejected

from .local_credentials import (
    LocalCredentialError,
    LocalDeviceCredentials,
    parse_local_device_credentials,
)
from .local_service import (
    LocalDeviceFailure,
    LocalInventoryObservation,
    LocalVerifyBudget,
)

_SEAL = object()


def _boundary[**P, R](operation: Callable[P, R]) -> Callable[P, R]:
    @wraps(operation)
    def checked(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return operation(*args, **kwargs)
        except LocalDeviceFailure as exc:
            code, status = exc.code, exc.status
        except LocalCredentialError:
            code, status = "LOCAL_DEVICE_INPUT_INVALID", 422
        except SecretRejected:
            code, status = "LOCAL_DEVICE_UNAVAILABLE", 503
        except DBAPIError as exc:
            code, status = {
                "40001": ("LOCAL_DEVICE_GENERATION_CONFLICT", 409),
                "53300": ("LOCAL_DEVICE_BUSY", 429),
                "42501": ("LOCAL_DEVICE_DENIED", 404),
                "22023": ("LOCAL_DEVICE_PROTOCOL_INVALID", 502),
            }.get(
                str(getattr(exc.orig, "sqlstate", "")),
                ("LOCAL_DEVICE_UNAVAILABLE", 503),
            )
        except (SQLAlchemyError, ValidationError, ValueError, TypeError):
            code, status = "LOCAL_DEVICE_UNAVAILABLE", 503
        raise LocalDeviceFailure(code, status) from None

    return checked


def _bound(db: Session | Connection, remaining: Callable[[], int]) -> None:
    left = remaining()
    if type(left) is not int or not 1 <= left <= 20000:
        raise LocalDeviceFailure("LOCAL_DEVICE_DEADLINE_EXCEEDED", 504)
    db.execute(
        text(
            "SELECT set_config('statement_timeout',:s,true),set_config('lock_timeout',:l,true)"
        ),
        {"s": str(left), "l": str(min(left, 3000))},
    )


def _token(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class LocalDeviceTicketIssuer:
    """Issue inside tenant_session; caller must commit before RPC dispatch."""

    def __init__(self, session: Session, remaining: Callable[[], int]) -> None:
        self._session, self._remaining = session, remaining

    @_boundary
    def issue(
        self, session_digest: str, connection_id: UUID, body: LocalVerifyRequest
    ) -> str:
        if (
            not _token(session_digest)
            or type(connection_id) is not UUID
            or type(body) is not LocalVerifyRequest
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        _bound(self._session, self._remaining)
        ticket: str | None = self._session.execute(
            text("SELECT public.wso_tvt_local_issue(:s,:c,:store,:gen)"),
            {
                "s": session_digest,
                "c": connection_id,
                "store": body.store_id,
                "gen": body.expected_generation,
            },
        ).scalar_one()
        _bound(self._session, self._remaining)
        if not _token(ticket):
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return str(ticket)


class LocalDeviceInventoryReader:
    """Safe OWNER inventory only, using the caller's protected transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @_boundary
    def list(
        self, store_id: UUID, *, correlation_id: str
    ) -> tuple[LocalDeviceView, ...]:
        return self._read(None, store_id, correlation_id)

    @_boundary
    def get(
        self, connection_id: UUID, store_id: UUID, *, correlation_id: str
    ) -> LocalDeviceView:
        items = self._read(connection_id, store_id, correlation_id)
        if len(items) != 1:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return items[0]

    def channels(
        self, connection_id: UUID, store_id: UUID, *, correlation_id: str
    ) -> tuple[LocalChannelView, ...]:
        return self.get(connection_id, store_id, correlation_id=correlation_id).channels

    def _read(
        self, connection: UUID | None, store: UUID, correlation: str
    ) -> tuple[LocalDeviceView, ...]:
        if (
            type(store) is not UUID
            or (connection is not None and type(connection) is not UUID)
            or type(correlation) is not str
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", correlation) is None
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        rows: Any = self._session.execute(
            text("SELECT public.wso_tvt_local_inventory(:c,:s)"),
            {"c": connection, "s": store},
        ).scalars()
        return tuple(
            LocalDeviceView.model_validate(row).model_copy(
                update={"request_id": correlation}
            )
            for row in rows
        )


@dataclass(frozen=True, slots=True, repr=False)
class LocalDeviceLease:
    token: str = field(repr=False)
    _seal: object = field(repr=False)


class LocalDeviceAdmission:
    def __init__(self, worker_url: str, provider: KeyProvider) -> None:
        if not worker_url.startswith("postgresql+psycopg://"):
            raise LocalDeviceFailure()
        self._cipher = SecretCipher(provider)
        self._engine = create_engine(
            worker_url,
            hide_parameters=True,
            poolclass=NullPool,
            connect_args={
                "connect_timeout": 3,
                "options": "-c statement_timeout=20000 -c lock_timeout=3000",
            },
        )

    @contextmanager
    def _transaction(self, budget: LocalVerifyBudget) -> Iterator[Connection]:
        budget.remaining_ms()
        with self._engine.begin() as db:
            _bound(db, budget.remaining_ms)
            if (
                db.execute(text("SELECT current_user")).scalar_one()
                != "wso_connection_worker"
            ):
                raise LocalDeviceFailure()
            yield db
            budget.remaining_ms()
        budget.remaining_ms()

    @staticmethod
    def _lease(lease: object) -> LocalDeviceLease:
        if (
            type(lease) is not LocalDeviceLease
            or lease._seal is not _SEAL
            or not _token(lease.token)
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return lease

    @_boundary
    def redeem(self, ticket: str, *, budget: LocalVerifyBudget) -> object:
        if not _token(ticket):
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        lease = secrets.token_hex(32)
        owned = LocalDeviceLease(lease, _SEAL)
        try:
            with self._transaction(budget) as db:
                accepted: bool = db.execute(
                    text("SELECT public.wso_tvt_local_redeem(:t,:l)"),
                    {"t": ticket, "l": lease},
                ).scalar_one()
                if accepted is not True:
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        except BaseException:
            # Commit may have succeeded before its budget check or before a
            # transport error. Keep the generated token until retirement even
            # though the executor has not received cleanup ownership yet.
            # close uses independent bounded SQL, never the expired budget.
            self.close(owned, budget=budget)
            raise
        return owned

    @_boundary
    def run(
        self,
        lease: object,
        callback: Callable[
            [LocalDeviceCredentials, Callable[[], bool]], LocalInventoryObservation
        ],
        *,
        budget: LocalVerifyBudget,
    ) -> LocalDeviceView:
        from wso_core.worker import JOB_STEP_ACTIVE

        if JOB_STEP_ACTIVE.get():
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        given = self._lease(lease)
        with self._transaction(budget) as db:
            row = (
                db.execute(
                    text("SELECT * FROM public.wso_tvt_local_use(:l)"),
                    {"l": given.token},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)

            def current() -> bool:
                _bound(db, budget.remaining_ms)
                accepted: bool = db.execute(
                    text("SELECT public.wso_tvt_local_current(:l)"), {"l": given.token}
                ).scalar_one()
                budget.remaining_ms()
                return accepted is True

            if not current():
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            raw = self._cipher.open(
                row["tenant_id"],
                row["connection_id"],
                row["version_id"],
                Envelope(bytes(row["nonce"]), bytes(row["ciphertext"])),
            )
            credentials = None
            try:
                credentials = parse_local_device_credentials(raw)
                if not current():
                    raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
                observation = callback(credentials, current)
            finally:
                del raw, credentials
            if type(observation) is not LocalInventoryObservation:
                raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
            observation.validate()
            if not current():
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            projected = {
                name: getattr(observation, name)
                for name in (
                    "login_accepted",
                    "same_original_session",
                    "serial_matched",
                    "channels_complete",
                    "cleanup_confirmed",
                    "group_provenance",
                    "metadata_branch_complete",
                    "permissions_complete",
                    "proof_verified",
                )
            }
            projected["channels"] = [
                {
                    "guid": c.guid.hex(),
                    "raw_index": c.raw_index,
                    "window_index": c.window_index,
                    "ordinal": c.ordinal,
                    "kind": c.kind,
                }
                for c in observation.channels
            ]
            _bound(db, budget.remaining_ms)
            result: Any = db.execute(
                text("SELECT public.wso_tvt_local_publish(:l,CAST(:o AS jsonb))"),
                {"l": given.token, "o": json.dumps(projected, separators=(",", ":"))},
            ).scalar_one()
            budget.remaining_ms()
            if result is None:
                raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
            view = LocalDeviceView.model_validate(result)
            if (
                view.connection_id != row["connection_id"]
                or view.store_id != row["store_id"]
                or view.connection_generation != row["generation"]
                or view.inventory_state != "AVAILABLE"
            ):
                raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        return view

    @_boundary
    def close(self, lease: object, *, budget: LocalVerifyBudget) -> None:
        given = self._lease(lease)
        # Disposal gets its own short SQL timeout; a cancelled/expired original
        # budget must not prevent retirement. It cannot authorize another effect.
        with self._engine.begin() as db:
            _bound(db, lambda: 1000)
            if (
                db.execute(text("SELECT current_user")).scalar_one()
                != "wso_connection_worker"
            ):
                raise LocalDeviceFailure()
            db.execute(
                text("SELECT public.wso_tvt_local_close(:l)"), {"l": given.token}
            )

    @staticmethod
    def inventory(
        session: Session, connection_id: UUID, store_id: UUID, *, correlation_id: str
    ) -> LocalDeviceView:
        return LocalDeviceInventoryReader(session).get(
            connection_id, store_id, correlation_id=correlation_id
        )

    def shutdown(self) -> None:
        self._engine.dispose()
