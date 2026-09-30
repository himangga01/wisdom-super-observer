"""Opt-in, fixed-deadline PostgreSQL authorization transactions.

These engines are separate from ordinary application and worker pools. Relative
server timers bound server work; they are not a hard operating-system watchdog.
"""

from __future__ import annotations

import ipaddress
import math
import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol

import psycopg
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool


class DbUnavailable(Exception):
    """A bounded database operation failed; diagnostics contain no SQL values."""

    def __init__(self, phase: str = "transaction", sqlstate: str | None = None):
        super().__init__("bounded database operation unavailable")
        self.phase = phase
        self.sqlstate = sqlstate


class DbDeadlineExceeded(DbUnavailable):
    pass


class DbTimeout(DbUnavailable):
    pass


@dataclass(frozen=True, slots=True)
class DbDeadline:
    deadline_monotonic: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.deadline_monotonic):
            raise ValueError("finite database deadline required")

    def remaining_ms(self) -> int:
        remaining = math.floor((self.deadline_monotonic - monotonic()) * 1000)
        if remaining <= 0:
            raise DbDeadlineExceeded()
        return remaining


class BudgetedSessionProvider(Protocol):
    def __call__(self, *, deadline: DbDeadline) -> AbstractContextManager[Session]: ...


@dataclass(frozen=True, slots=True)
class AuthorizationDbFactories:
    web_session: BudgetedSessionProvider
    identity: BudgetedSessionProvider
    tenant: BudgetedSessionProvider
    redemption: BudgetedSessionProvider

    def for_deadline(self, deadline: DbDeadline) -> AuthorizationDbControls:
        deadline.remaining_ms()
        return AuthorizationDbControls(self, deadline)


@dataclass(frozen=True, slots=True)
class AuthorizationDbControls:
    factories: AuthorizationDbFactories
    deadline: DbDeadline


_ACTIVE: ContextVar[DbDeadline | None] = ContextVar("asset_db_deadline", default=None)
_TIMEOUT_STATES = {"55P03", "57014", "25P04", "25P03"}
_SET_LOCAL = text(
    "SELECT set_config('statement_timeout', :statement, true), "
    "set_config('lock_timeout', :lock, true), "
    "set_config('transaction_timeout', :transaction, true), "
    "set_config('idle_in_transaction_session_timeout', :idle, true)"
)
_SET_DEFAULTS = (
    "SELECT set_config('statement_timeout', %s, false), "
    "set_config('lock_timeout', %s, false), "
    "set_config('transaction_timeout', %s, false), "
    "set_config('idle_in_transaction_session_timeout', %s, false)"
)


def _limits(deadline: DbDeadline, *, reserve_ms: int = 0) -> dict[str, str]:
    ms = deadline.remaining_ms() - reserve_ms
    if ms <= 0:
        raise DbDeadlineExceeded()
    return {
        "statement": str(min(5000, ms)),
        "lock": str(min(1000, ms)),
        "transaction": str(min(5000, ms)),
        "idle": str(min(15000, ms)),
    }


def _reject_ambient_connection_configuration() -> None:
    # Read only at the explicitly effectful boundary, never at construction.
    # Reject the PG namespace rather than chasing libpq's evolving option list
    # (PGSERVICEFILE is not itself a conninfo parameter). Do not read/log values
    # or mutate process environment around a connect: requests run concurrently.
    if any(name.upper().startswith("PG") for name in os.environ):
        raise DbUnavailable("configuration")


def _configure_defaults(raw: psycopg.Connection[Any], deadline: DbDeadline) -> None:
    limits = _limits(deadline, reserve_ms=50)
    raw.autocommit = True
    try:
        with raw.cursor() as cursor:
            cursor.execute(_SET_DEFAULTS, tuple(limits.values()))
    finally:
        if not raw.closed:
            raw.autocommit = False
    deadline.remaining_ms()


class SqlAlchemyBudgetedSessionProvider:
    """Own an explicit asset-only engine and one transaction per entry."""

    def __init__(self, engine: Engine, *, null_pool: bool) -> None:
        self.engine = engine
        self._null_pool = null_pool

    def dispose(self) -> None:
        self.engine.dispose()

    @contextmanager
    def __call__(self, *, deadline: DbDeadline) -> Iterator[Session]:
        remaining = deadline.remaining_ms()
        _reject_ambient_connection_configuration()
        if not self._null_pool and remaining < 150:
            raise DbDeadlineExceeded("checkout")
        token = _ACTIVE.set(deadline)
        phase = "acquire"
        try:
            with self.engine.connect() as connection:
                phase = "transaction"
                connection.info["asset_db_deadline"] = deadline
                try:
                    # PG17 does not shorten an already active transaction timer
                    # when SET LOCAL changes a positive value to another one.
                    # Install the new remaining cap BEFORE BEGIN on every
                    # checkout, including warm pooled physical connections.
                    raw = connection.connection.driver_connection
                    if not isinstance(raw, psycopg.Connection):
                        raise TypeError("bounded provider requires psycopg connection")
                    _configure_defaults(raw, deadline)
                    with Session(bind=connection) as session, session.begin():
                        try:
                            session.execute(_SET_LOCAL, _limits(deadline))
                            deadline.remaining_ms()
                            yield session
                            deadline.remaining_ms()
                        except DbDeadlineExceeded:
                            # Retire before the transaction manager rolls back:
                            # a pending server termination must not replace the
                            # primary deadline failure with a rollback failure.
                            connection.invalidate()
                            raise
                    deadline.remaining_ms()
                except DbDeadlineExceeded:
                    # The local deadline may race a server termination that is
                    # not yet visible to the driver. Never recycle that socket.
                    connection.invalidate()
                    raise
                except psycopg.Error as exc:
                    closed = not isinstance(raw, psycopg.Connection) or raw.closed
                    if closed or (exc.sqlstate or "").startswith("08"):
                        connection.invalidate()
                    if exc.sqlstate in _TIMEOUT_STATES:
                        raise DbTimeout(sqlstate=exc.sqlstate) from exc
                    if closed or isinstance(exc, psycopg.OperationalError):
                        raise DbUnavailable(sqlstate=exc.sqlstate) from exc
                    raise
                except DBAPIError as exc:
                    state = getattr(exc.orig, "sqlstate", None)
                    broken = (
                        exc.connection_invalidated
                        or state in {"25P04", "25P03"}
                        or (isinstance(state, str) and state.startswith("08"))
                    )
                    if broken:
                        connection.invalidate()
                    if state in _TIMEOUT_STATES:
                        raise DbTimeout(sqlstate=state) from exc
                    if broken:
                        raise DbUnavailable(sqlstate=state) from exc
                    raise
                finally:
                    # Do not access .info on an invalidated connection: that
                    # property can reconnect and would start unrequested work.
                    if not connection.invalidated and not connection.closed:
                        connection.info.pop("asset_db_deadline", None)
        except PoolTimeout as exc:
            raise DbUnavailable("checkout") from exc
        except DBAPIError as exc:
            # Includes protected first-connect dialect initialization, which
            # happens before engine.connect() can yield its Connection object.
            state = getattr(exc.orig, "sqlstate", None)
            if state in _TIMEOUT_STATES:
                raise DbTimeout(phase, state) from exc
            if exc.connection_invalidated or (
                isinstance(state, str) and state.startswith("08")
            ):
                raise DbUnavailable(phase, state) from exc
            raise
        finally:
            _ACTIVE.reset(token)


def create_budgeted_provider(
    url: str,
    *,
    null_pool: bool = False,
    pool_size: int = 5,
    max_overflow: int = 0,
    hostaddr: str | None = None,
) -> SqlAlchemyBudgetedSessionProvider:
    """Build without connecting, DNS resolution, or reading the environment.

    A trusted numeric hostaddr preserves a DNS hostname for TLS verification.
    URL connect_timeout is accepted but always replaced by the deadline cap.
    All other connection routing or timeout overrides are rejected.
    """
    parsed = make_url(url)
    allowed = {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout"}
    if (
        parsed.drivername != "postgresql+psycopg"
        or not parsed.host
        or not parsed.database
        or not parsed.username
        or set(parsed.query) - allowed
        or any(not isinstance(value, str) for value in parsed.query.values())
        or any(c in parsed.host for c in ",/\\ \t\r\n")
        or pool_size < 1
        or max_overflow < 0
    ):
        raise ValueError("explicit single-address PostgreSQL configuration required")
    address = str(ipaddress.ip_address(hostaddr or parsed.host))
    parameters: dict[str, Any] = parsed.translate_connect_args(
        username="user", database="dbname"
    )
    parameters.update({k: v for k, v in parsed.query.items() if k != "connect_timeout"})
    parameters["hostaddr"] = address
    parameters.setdefault("port", 5432)
    parameters.setdefault("sslmode", "prefer")

    def connect() -> psycopg.Connection[Any]:
        deadline = _ACTIVE.get()
        if deadline is None:
            raise ValueError("bounded provider requires an active deadline")
        _reject_ambient_connection_configuration()
        limits = _limits(deadline, reserve_ms=50)
        seconds = (deadline.remaining_ms() - 50) // 1000
        if seconds < 2:
            raise DbDeadlineExceeded("connect")
        options = dict(parameters)
        options["connect_timeout"] = min(5, seconds)
        options["options"] = (
            f"-c statement_timeout={limits['statement']} "
            f"-c lock_timeout={limits['lock']} "
            f"-c transaction_timeout={limits['transaction']} "
            f"-c idle_in_transaction_session_timeout={limits['idle']}"
        )
        try:
            raw = psycopg.connect(**options)
        except psycopg.OperationalError as exc:
            raise DbUnavailable("connect", exc.sqlstate) from exc
        try:
            _configure_defaults(raw, deadline)
            return raw
        except BaseException:
            raw.close()
            raise

    kwargs: dict[str, Any] = {
        "creator": connect,
        "hide_parameters": True,
        "pool_pre_ping": False,
    }
    if null_pool:
        kwargs["poolclass"] = NullPool
    else:
        kwargs.update(pool_size=pool_size, max_overflow=max_overflow, pool_timeout=0.1)
    engine = create_engine(parsed, **kwargs)

    def before_statement(connection: Any, *args: Any) -> None:
        deadline = connection.info.get("asset_db_deadline")
        if deadline is None:
            raise ValueError("bounded provider requires a transaction deadline")
        deadline.remaining_ms()

    event.listen(engine, "before_cursor_execute", before_statement)
    event.listen(engine, "after_cursor_execute", before_statement)
    event.listen(engine, "commit", before_statement)
    return SqlAlchemyBudgetedSessionProvider(engine, null_pool=null_pool)
