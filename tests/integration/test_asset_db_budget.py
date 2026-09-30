"""Real PG17 authority locks must time out before a protected session is yielded."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from starlette.requests import Request
from wso_api.auth import (
    AuthFailure,
    AuthService,
    PostgresSessionStore,
    WebSession,
    token_digest,
)
from wso_api.stores.router import require_tenant
from wso_core.db import tenant_session
from wso_core.db_budget import (
    AuthorizationDbFactories,
    DbDeadline,
    DbDeadlineExceeded,
    DbTimeout,
    DbUnavailable,
    create_budgeted_provider,
)
from wso_core.tenancy import identity_session

from tests.support.job_handlers import verify_fixture_database


class FixtureURLs(dict):
    def __repr__(self):
        return "<explicit fixture URLs redacted>"


@pytest.fixture(scope="module")
def budget_database():
    names = ("ADMIN", "SESSION", "IDENTITY", "APP")
    urls = FixtureURLs(
        {name: os.getenv(f"WSO_TEST_{name}_DATABASE_URL") for name in names}
    )
    if not all(urls.values()):
        pytest.skip("requires explicit owned PostgreSQL fixture roles")
    admin = create_engine(urls["ADMIN"], hide_parameters=True)
    verify_fixture_database(admin, domain_only=sys.platform == "win32")
    with admin.connect() as db:
        assert (
            db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0003a_assets"
        )
    providers = [
        create_budgeted_provider(urls["SESSION"], pool_size=1),
        create_budgeted_provider(urls["IDENTITY"], pool_size=1),
        create_budgeted_provider(urls["APP"], pool_size=1),
        create_budgeted_provider(urls["APP"], null_pool=True),
    ]
    try:
        yield admin, AuthorizationDbFactories(*providers), urls
    finally:
        for provider in providers:
            provider.dispose()
        admin.dispose()


@pytest.fixture
def authority(budget_database):
    admin, factories, urls = budget_database
    tenant, user = uuid4(), uuid4()
    issuer, subject = "https://budget.test", str(user)
    cookie = str(uuid4())
    with admin.begin() as db:
        db.execute(
            text("INSERT INTO tenants(id,name) VALUES(:id,'budget-test')"),
            {"id": tenant},
        )
        db.execute(
            text(
                "INSERT INTO users(id,oidc_issuer,oidc_subject) VALUES(:id,:issuer,:subject)"
            ),
            {"id": user, "issuer": issuer, "subject": subject},
        )
        db.execute(
            text(
                "INSERT INTO memberships(tenant_id,user_id,role) VALUES(:t,:u,'OWNER')"
            ),
            {"t": tenant, "u": user},
        )
    legacy = create_engine(urls["SESSION"], hide_parameters=True)
    sessions = PostgresSessionStore(
        urls["SESSION"], session_factory=sessionmaker(legacy)
    )
    principal = WebSession(
        issuer,
        subject,
        user,
        token_digest("csrf"),
        datetime.now(UTC) + timedelta(minutes=5),
    )
    assert sessions.create(token_digest(cookie), principal, token_digest(str(uuid4())))
    service = AuthService(None, None, sessions)
    request = Request(
        {
            "type": "http",
            "headers": [(b"cookie", f"__Host-wso-session={cookie}".encode())],
        }
    )
    try:
        yield admin, factories, service, request, tenant, principal
    finally:
        with admin.begin() as db:
            db.execute(text("DELETE FROM web_sessions WHERE user_id=:u"), {"u": user})
            db.execute(
                text("DELETE FROM wso_private.tenant_grants WHERE user_id=:u"),
                {"u": user},
            )
            db.execute(
                text("DELETE FROM wso_private.tenant_contexts WHERE user_id=:u"),
                {"u": user},
            )
            db.execute(text("DELETE FROM memberships WHERE user_id=:u"), {"u": user})
            db.execute(text("DELETE FROM users WHERE id=:u"), {"u": user})
            db.execute(text("DELETE FROM tenants WHERE id=:t"), {"t": tenant})
        legacy.dispose()


def timeout_ms(setting):
    if setting.endswith("ms"):
        return int(setting[:-2])
    if setting.endswith("s"):
        return int(setting[:-1]) * 1000
    raise AssertionError("unexpected timeout unit")


def controls(factories, seconds=5):
    return factories.for_deadline(DbDeadline(monotonic() + seconds))


def issue(factories, tenant, principal, control=None):
    with identity_session(
        principal.issuer, principal.subject, db_controls=control or controls(factories)
    ) as lookup:
        return lookup.authorize_tenant(tenant)


def lock_membership(holder, tenant, principal):
    holder.execute(
        text("SELECT 1 FROM memberships WHERE tenant_id=:t AND user_id=:u FOR UPDATE"),
        {"t": tenant, "u": principal.user_id},
    ).one()


def run_while_locked(admin, holder, operation, query_fragment, expected):
    """A four-second watchdog releases holder even if bounded code regresses."""
    observed = []
    started = monotonic()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(operation)
        try:
            while not future.done() and monotonic() - started < 4:
                with admin.connect() as observer:
                    rows = observer.execute(
                        text(
                            "SELECT pid,usename,query FROM pg_stat_activity "
                            "WHERE datname=current_database() AND wait_event_type='Lock' "
                            "AND query LIKE :pattern"
                        ),
                        {"pattern": f"%{query_fragment}%"},
                    ).all()
                    observed.extend(rows)
                sleep(0.01)
            assert future.done(), "database operation exceeded watchdog while lock held"
            assert holder.in_transaction(), "holder released before timeout"
            with pytest.raises(expected) as failure:
                future.result()
            assert observed, "intended PostgreSQL authority lock was never observed"
            assert monotonic() - started < 3, (
                "one-second lock cap exceeded scheduling margin"
            )
            return failure.value, observed
        finally:
            holder.rollback()


def test_actual_cookie_lookup_times_out_before_identity(authority):
    admin, factories, service, request, tenant, _principal = authority
    yielded = []
    control = controls(factories)

    def operation():
        session = service.authenticate(request, db_controls=control)
        with require_tenant(
            "assets:read",
            tenant,
            service=service,
            principal=session,
            db_controls=control,
        ):
            yielded.append(True)

    with admin.connect() as holder:
        holder.execute(text("LOCK TABLE public.web_sessions IN ACCESS EXCLUSIVE MODE"))
        failure, rows = run_while_locked(
            admin, holder, operation, "wso_get_web_session", AuthFailure
        )
        assert failure.status == 503
        assert {row.usename for row in rows} == {"wso_web_session"}
    assert yielded == []


def test_real_grant_issuance_membership_lock_is_bounded(authority):
    admin, factories, service, request, tenant, principal = authority
    yielded = []
    control = controls(factories)

    def operation():
        session = service.authenticate(request, db_controls=control)
        with require_tenant(
            "assets:read",
            tenant,
            service=service,
            principal=session,
            db_controls=control,
        ):
            yielded.append(True)

    with admin.connect() as holder:
        lock_membership(holder, tenant, principal)
        failure, _ = run_while_locked(
            admin, holder, operation, "wso_issue_tenant_grant", AuthFailure
        )
        assert failure.status == 503
    assert yielded == []
    fresh = controls(factories)
    with require_tenant(
        "assets:read", tenant, service=service, principal=principal, db_controls=fresh
    ):
        pass


def test_nullpool_redemption_times_out_with_one_business_checkout(authority):
    admin, factories, _service, _request, tenant, principal = authority
    choice = issue(factories, tenant, principal)
    assert isinstance(factories.redemption.engine.pool, NullPool)
    business_pids = []
    original = factories.tenant

    @contextmanager
    def tenant_provider(*, deadline):
        with original(deadline=deadline) as db:
            business_pids.append(
                db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            yield db

    control = controls(replace(factories, tenant=tenant_provider))

    def operation():
        with tenant_session(tenant, authorization=choice, db_controls=control):
            pytest.fail("locked grant must not yield authority")

    with admin.connect() as holder:
        holder.execute(
            text(
                "SELECT 1 FROM wso_private.tenant_grants WHERE token_hash=sha256(convert_to(:token,'UTF8')) FOR UPDATE"
            ),
            {"token": choice._grant_token},
        ).one()
        failure, observed = run_while_locked(
            admin, holder, operation, "wso_consume_tenant_grant", DbTimeout
        )
        assert failure.sqlstate == "55P03"
        assert all(row.pid != business_pids[0] for row in observed)
    assert original.engine.pool.checkedout() == 0


def test_current_tenant_recheck_is_bounded_and_consumption_survives_rollback(authority):
    admin, factories, _service, _request, tenant, principal = authority
    choice = issue(factories, tenant, principal)
    original = factories.redemption
    with admin.connect() as holder:

        @contextmanager
        def after_redemption(*, deadline):
            with original(deadline=deadline) as db:
                yield db
            lock_membership(holder, tenant, principal)

        control = controls(replace(factories, redemption=after_redemption))

        def operation():
            with tenant_session(tenant, authorization=choice, db_controls=control):
                pytest.fail("locked current membership must not yield authority")

        run_while_locked(admin, holder, operation, "wso_current_tenant_id", DbTimeout)
    with admin.connect() as db:
        assert db.execute(
            text(
                "SELECT consumed_at IS NOT NULL FROM wso_private.tenant_grants WHERE token_hash=sha256(convert_to(:token,'UTF8'))"
            ),
            {"token": choice._grant_token},
        ).scalar_one()
    with (
        pytest.raises(PermissionError),
        tenant_session(tenant, authorization=choice, db_controls=controls(factories)),
    ):
        pass
    fresh = issue(factories, tenant, principal)
    with tenant_session(tenant, authorization=fresh, db_controls=controls(factories)):
        pass


def test_all_physical_connections_get_single_address_options(
    budget_database, monkeypatch
):
    import psycopg

    _admin, factories, _urls = budget_database
    captured = []
    original = psycopg.connect

    def connect(*args, **kwargs):
        captured.append(
            {key: kwargs[key] for key in ("hostaddr", "connect_timeout", "options")}
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", connect)
    roles = ["wso_web_session", "wso_identity_bootstrap", "wso_app", "wso_app"]
    for provider, role in zip(
        (
            factories.web_session,
            factories.identity,
            factories.tenant,
            factories.redemption,
        ),
        roles,
        strict=True,
    ):
        provider.dispose()
        for _ in range(
            2 if role == "wso_app" and provider is factories.redemption else 1
        ):
            with provider(deadline=DbDeadline(monotonic() + 5)) as db:
                row = db.execute(
                    text(
                        "SELECT current_user, current_setting('statement_timeout'), current_setting('lock_timeout'), current_setting('transaction_timeout'), current_setting('idle_in_transaction_session_timeout')"
                    )
                ).one()
                assert row[0] == role
                assert all(value not in {"0", "0ms"} for value in row[1:])
    assert len(captured) == 5
    for options in captured:
        assert options["hostaddr"] == "127.0.0.1"
        assert options["connect_timeout"] == 4
        assert "-c lock_timeout=1000" in options["options"]
        assert "transaction_timeout=" in options["options"]


def test_later_transaction_uses_remaining_deadline_and_warm_pool(budget_database):
    _admin, factories, _urls = budget_database
    provider = factories.identity
    with provider(deadline=DbDeadline(monotonic() + 5)):
        pass
    deadline = DbDeadline(monotonic() + 0.65)
    with pytest.raises(DbDeadlineExceeded), provider(deadline=deadline) as db:
        setting = db.execute(
            text("SELECT current_setting('transaction_timeout')")
        ).scalar_one()
        assert 0 < int(setting.removesuffix("ms")) <= 650
        sleep(0.7)
        db.execute(text("SELECT 1"))


def test_pool_busy_is_finite_and_programming_error_is_not_timeout(budget_database):
    _admin, factories, _urls = budget_database
    provider = factories.tenant
    with provider(deadline=DbDeadline(monotonic() + 5)):
        started = monotonic()
        with (
            pytest.raises(DbUnavailable) as failure,
            provider(deadline=DbDeadline(monotonic() + 5)),
        ):
            pass
        assert failure.value.phase == "checkout"
        assert monotonic() - started < 0.7
    with (
        pytest.raises(ProgrammingError),
        provider(deadline=DbDeadline(monotonic() + 5)) as db,
    ):
        db.execute(text("SELECT nonexistent_budget_column"))


def test_expired_or_too_short_new_connect_opens_no_physical_connection(budget_database):
    _admin, _factories, urls = budget_database
    provider = create_budgeted_provider(urls["APP"], null_pool=True)
    opened = []
    event.listen(provider.engine, "connect", lambda *args: opened.append(True))
    try:
        for seconds in (-1, 1.9):
            with (
                pytest.raises(DbDeadlineExceeded),
                provider(deadline=DbDeadline(monotonic() + seconds)),
            ):
                pass
        assert opened == []
    finally:
        provider.dispose()


def test_deadline_killed_business_connection_is_not_reused(budget_database):
    _admin, factories, _urls = budget_database
    provider = factories.tenant
    with provider(deadline=DbDeadline(monotonic() + 5)) as db:
        previous = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
    with (
        pytest.raises(DbUnavailable),
        provider(deadline=DbDeadline(monotonic() + 0.3)) as db,
    ):
        sleep(0.4)
        db.execute(text("SELECT 1"))
    with provider(deadline=DbDeadline(monotonic() + 5)) as db:
        assert db.execute(text("SELECT pg_backend_pid()")).scalar_one() != previous


def test_debited_deadline_shortens_actual_later_grant_lock(authority):
    admin, factories, _service, _request, tenant, principal = authority
    with factories.identity(deadline=DbDeadline(monotonic() + 5)):
        pass
    deadline = DbDeadline(monotonic() + 1.2)
    sleep(0.5)  # Fixture barrier spends existing budget; no replacement deadline.
    configured = []
    original = factories.identity

    @contextmanager
    def observe(*, deadline):
        with original(deadline=deadline) as db:
            configured.append(
                db.execute(
                    text(
                        "SELECT current_setting('lock_timeout'),current_setting('transaction_timeout')"
                    )
                ).one()
            )
            yield db

    control = replace(factories, identity=observe).for_deadline(deadline)
    with admin.connect() as holder:
        lock_membership(holder, tenant, principal)
        failure, _ = run_while_locked(
            admin,
            holder,
            lambda: issue(factories, tenant, principal, control),
            "wso_issue_tenant_grant",
            DbUnavailable,
        )
        assert failure.sqlstate in {"55P03", "25P04", "57014"}
    assert configured
    assert all(0 < int(value.removesuffix("ms")) <= 700 for value in configured[0])
    assert monotonic() < deadline.deadline_monotonic + 0.8


def test_server_transaction_timeout_bounds_successive_statements(budget_database):
    _admin, factories, _urls = budget_database
    provider = factories.identity
    with provider(deadline=DbDeadline(monotonic() + 5)):
        pass
    started = monotonic()
    with (
        pytest.raises(DbTimeout) as failure,
        provider(deadline=DbDeadline(monotonic() + 0.7)) as db,
    ):
        db.execute(text("SELECT pg_sleep(0.45)"))
        db.execute(text("SELECT pg_sleep(0.5)"))
    assert failure.value.sqlstate == "25P04"
    assert monotonic() - started < 1.2


def test_raw_connect_delay_reduces_defaults_before_first_dialect_sql(
    budget_database, monkeypatch
):
    import psycopg

    _admin, _factories, urls = budget_database
    original = psycopg.connect
    startup = []
    before_dialect = []

    def connect(**kwargs):
        startup.append(kwargs["options"])
        raw = original(**kwargs)
        sleep(0.2)  # Spend the same deadline after the physical handshake.
        return raw

    monkeypatch.setattr(psycopg, "connect", connect)
    provider = create_budgeted_provider(urls["IDENTITY"])
    initialize = provider.engine.dialect.initialize

    def inspect(connection):
        raw = connection.connection.driver_connection
        with raw.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_timeout')")
            before_dialect.append(cursor.fetchone()[0])
        initialize(connection)

    monkeypatch.setattr(provider.engine.dialect, "initialize", inspect)
    try:
        with provider(deadline=DbDeadline(monotonic() + 5)):
            pass
        assert len(before_dialect) == 1
        assert 0 < int(before_dialect[0].removesuffix("ms")) < 4800
        assert "transaction_timeout=49" in startup[0]
    finally:
        provider.dispose()


def test_warm_pool_replaces_old_deadline_and_thread_context_is_isolated(
    budget_database,
):
    _admin, _factories, urls = budget_database
    provider = create_budgeted_provider(urls["IDENTITY"], pool_size=2)

    def read_limits(seconds):
        with provider(deadline=DbDeadline(monotonic() + seconds)) as db:
            return db.execute(
                text("SELECT current_setting('transaction_timeout')")
            ).scalar_one()

    try:
        # Warm both sockets so the deliberately short request needs no connect.
        with provider(deadline=DbDeadline(monotonic() + 5)):
            read_limits(5)
        with ThreadPoolExecutor(max_workers=2) as executor:
            short = executor.submit(read_limits, 0.5)
            long = executor.submit(read_limits, 4)
            assert 0 < timeout_ms(short.result()) <= 500
            assert timeout_ms(long.result()) > 3000
        assert timeout_ms(read_limits(5)) > 4000
    finally:
        provider.dispose()


def test_loopback_accept_without_handshake_has_finite_connect_timeout():
    import socket
    from threading import Event, Thread

    accepted = Event()
    release = Event()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(4)
        port = listener.getsockname()[1]

        def stall():
            with listener.accept()[0]:
                accepted.set()
                release.wait(4)

        server = Thread(target=stall)
        server.start()
        provider = create_budgeted_provider(
            f"postgresql+psycopg://wso_app@127.0.0.1:{port}/fixture"
        )
        started = monotonic()
        try:
            with (
                pytest.raises(DbUnavailable) as failure,
                provider(deadline=DbDeadline(monotonic() + 3.4)),
            ):
                pass
            assert failure.value.phase == "connect"
            assert accepted.is_set()
            assert not release.is_set()
            assert monotonic() - started < 4
        finally:
            release.set()
            server.join(5)
            provider.dispose()
