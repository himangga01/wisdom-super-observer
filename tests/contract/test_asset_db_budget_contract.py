"""An asset authorization request may never fall back to an unbounded store."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.requests import Request
from wso_api.auth import AuthFailure, AuthService, WebSession


def test_deadline_floor_and_expired_auth_never_calls_bounded_store(monkeypatch):
    from wso_core import db_budget

    monkeypatch.setattr(db_budget, "monotonic", lambda: 10.0)
    assert db_budget.DbDeadline(10.1259).remaining_ms() == 125

    class Store:
        def get_bounded(self, *args, **kwargs):
            raise AssertionError("expired request reached cookie database")

    controls = SimpleNamespace(deadline=db_budget.DbDeadline(9))
    with pytest.raises(AuthFailure) as failed:
        AuthService(None, None, Store()).authenticate(request(), db_controls=controls)
    assert failed.value.status == 503


@pytest.mark.parametrize(
    "url,hostaddr",
    [
        ("postgresql+psycopg://wso_app@localhost/test", None),
        (
            "postgresql+psycopg://wso_app@127.0.0.1/test?options=-c+statement_timeout=0",
            None,
        ),
        ("postgresql+psycopg://wso_app@127.0.0.1/test?service=remote", None),
        ("postgresql+psycopg://wso_app@127.0.0.1/test?host=other", None),
        ("postgresql+psycopg://wso_app@one,two/test", "127.0.0.1"),
        ("postgresql+psycopg://wso_app@tls-host/test", "one,two"),
    ],
)
def test_provider_rejects_routing_or_timeout_overrides_without_connect(url, hostaddr):
    from wso_core.db_budget import create_budgeted_provider

    with pytest.raises(ValueError):
        create_budgeted_provider(url, hostaddr=hostaddr)


def test_provider_construction_is_offline_and_unscoped_use_fails_closed(monkeypatch):
    import psycopg
    from wso_core.db_budget import create_budgeted_provider

    def unexpected(*args, **kwargs):
        raise AssertionError("unscoped or constructor database connection")

    monkeypatch.setattr(psycopg, "connect", unexpected)
    provider = create_budgeted_provider(
        "postgresql+psycopg://wso_app@tls-host/test?sslmode=verify-full&connect_timeout=99",
        hostaddr="127.0.0.1",
    )
    try:
        with (
            pytest.raises(ValueError, match="active deadline"),
            provider.engine.connect(),
        ):
            pass
    finally:
        provider.dispose()


def test_expired_physical_connect_closes_before_dialect_sql(monkeypatch):
    import psycopg
    from wso_core import db_budget

    now = [10.0]
    closed = []

    class Raw:
        def close(self):
            closed.append(True)

        def cursor(self):
            raise AssertionError("expired raw connection reached dialect/setup SQL")

    def connect(**kwargs):
        now[0] = 16.0
        return Raw()

    monkeypatch.setattr(db_budget, "monotonic", lambda: now[0])
    monkeypatch.setattr(psycopg, "connect", connect)
    provider = db_budget.create_budgeted_provider(
        "postgresql+psycopg://wso_app@127.0.0.1/test"
    )
    try:
        with (
            pytest.raises(db_budget.DbDeadlineExceeded),
            provider(deadline=db_budget.DbDeadline(15)),
        ):
            pass
        assert closed == [True]
    finally:
        provider.dispose()


def test_expired_identity_and_grant_never_enter_any_provider():
    from time import monotonic

    from wso_core.db import tenant_session
    from wso_core.db_budget import (
        AuthorizationDbControls,
        AuthorizationDbFactories,
        DbDeadline,
        DbDeadlineExceeded,
    )
    from wso_core.tenancy import _ISSUER_KEY, TenantAuthorization, identity_session

    def forbidden(*, deadline):
        raise AssertionError("expired request opened authority provider")

    factories = AuthorizationDbFactories(forbidden, forbidden, forbidden, forbidden)
    controls = AuthorizationDbControls(factories, DbDeadline(monotonic() - 1))
    tenant = uuid4()
    choice = TenantAuthorization(tenant, uuid4(), "OWNER", _ISSUER_KEY, "x" * 64)
    with (
        pytest.raises(DbDeadlineExceeded),
        identity_session("issuer", "subject", db_controls=controls),
    ):
        pass
    with (
        pytest.raises(DbDeadlineExceeded),
        tenant_session(tenant, authorization=choice, db_controls=controls),
    ):
        pass


def test_ambiguous_legacy_and_controlled_factory_is_rejected():
    from time import monotonic

    from wso_core.db import tenant_session
    from wso_core.db_budget import AuthorizationDbControls, DbDeadline
    from wso_core.tenancy import _ISSUER_KEY, TenantAuthorization, identity_session

    controls = AuthorizationDbControls(None, DbDeadline(monotonic() + 5))
    tenant = uuid4()
    choice = TenantAuthorization(tenant, uuid4(), "OWNER", _ISSUER_KEY, "x" * 64)
    with (
        pytest.raises(ValueError, match="ambiguous"),
        identity_session(
            "issuer", "subject", session_factory=object(), db_controls=controls
        ),
    ):
        pass
    with (
        pytest.raises(ValueError, match="ambiguous"),
        tenant_session(
            tenant, authorization=choice, session_factory=object(), db_controls=controls
        ),
    ):
        pass


def request():
    return Request(
        {"type": "http", "headers": [(b"cookie", b"__Host-wso-session=opaque-cookie")]}
    )


def test_bounded_auth_refuses_legacy_store_without_calling_get():
    class LegacyStore:
        def get(self, digest):
            raise AssertionError("bounded authentication fell back to legacy get")

    service = AuthService(None, None, LegacyStore())
    controls = SimpleNamespace(deadline=SimpleNamespace(remaining_ms=lambda: 4000))
    with pytest.raises(AuthFailure) as failed:
        service.authenticate(request(), db_controls=controls)
    assert failed.value.status == 503


def test_legacy_auth_still_accepts_get_only_store():
    session = WebSession(
        "issuer", "subject", uuid4(), "csrf", datetime.now(UTC) + timedelta(minutes=1)
    )

    class LegacyStore:
        def get(self, digest):
            return session

    assert AuthService(None, None, LegacyStore()).authenticate(request()) == session


@pytest.mark.parametrize("null_pool", [False, True])
def test_ambient_service_configuration_rejected_before_libpq_lookup(null_pool):
    """Use synthetic child-only configuration; neither fixture nor secrets enter it."""
    import os
    import subprocess
    import sys

    script = f"""
from time import monotonic
from wso_core.db_budget import create_budgeted_provider, DbDeadline, DbUnavailable
provider = create_budgeted_provider(
    'postgresql+psycopg://wso_app@127.0.0.1:1/synthetic', null_pool={null_pool!r})
try:
    with provider(deadline=DbDeadline(monotonic() + 5)):
        raise AssertionError('synthetic service must never reach database')
except DbUnavailable as failure:
    print(failure.phase)
finally:
    provider.dispose()
"""
    # Explicit small child environment avoids copying WSO fixture credentials.
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    }
    child_env.update(
        PGSERVICE="synthetic_forbidden_service",
        PGSERVICEFILE="C:/__t05a_review_missing_pg_service__.conf",
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "configuration"


@pytest.mark.parametrize(
    "name",
    ["PGPORT", "PGSSLMODE", "PGOPTIONS", "PGHOSTADDR", "PGSSLROOTCERT", "PGGSSENCMODE"],
)
def test_ambient_connection_defaults_never_enter_driver(monkeypatch, name):
    from time import monotonic

    import psycopg
    from wso_core.db_budget import DbDeadline, DbUnavailable, create_budgeted_provider

    def forbidden(**kwargs):
        raise AssertionError("ambient connection defaults reached driver")

    monkeypatch.setenv(name, "synthetic-untrusted-default")
    monkeypatch.setattr(psycopg, "connect", forbidden)
    # Construction stays offline even when admission will fail closed.
    provider = create_budgeted_provider("postgresql+psycopg://wso_app@127.0.0.1/test")
    try:
        with (
            pytest.raises(DbUnavailable) as failed,
            provider(deadline=DbDeadline(monotonic() + 5)),
        ):
            pass
        assert failed.value.phase == "configuration"
        assert "synthetic" not in str(failed.value)
    finally:
        provider.dispose()
