"""T02 isolation contract: offline DDL checks and optional real PostgreSQL gates."""

from __future__ import annotations

import io
import os
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker
from wso_core.db import StoreRepository, tenant_session
from wso_core.migration import migration_database_url
from wso_core.tenancy import _ISSUER_KEY, TenantAuthorization, identity_session

ROOT = Path(__file__).resolve().parents[2]


def test_migration_emits_scoped_constraints_and_forced_policies() -> None:
    """Catch a migration that drops scoped FKs or leaves app tables unprotected."""
    config = Config(str(ROOT / "infra" / "alembic.ini"))
    output = io.StringIO()
    with redirect_stdout(output):
        command.upgrade(config, "head", sql=True)
    sql = output.getvalue().lower()
    assert "create table stores" in sql
    assert "foreign key(tenant_id, store_id)" in sql
    assert "foreign key(tenant_id, user_id)" in sql
    assert "foreign key(tenant_id, actor_user_id)" in sql
    for table in ("memberships", "stores", "store_memberships", "audit_events"):
        assert f"alter table {table} force row level security" in sql
        assert f"create policy {table}_tenant_policy" in sql
    assert "create policy users_identity_policy" in sql
    assert "create policy memberships_identity_policy" in sql
    assert "grant select on stores to wso_identity_bootstrap" not in sql
    assert "grant select" in sql
    assert "alter table stores owner to wso_migrator" in sql
    assert "nobypassrls" in sql
    assert "alter role wso_app login noinherit nosuperuser" in sql
    assert "alter role wso_identity_bootstrap login noinherit nosuperuser" in sql
    assert "pg_auth_members" in sql
    assert "raise exception 'runtime role membership is forbidden'" in sql
    for table in (
        "tenants",
        "users",
        "memberships",
        "stores",
        "store_memberships",
        "audit_events",
    ):
        assert (
            f"create policy {table}_migration_policy on {table} "
            "to wso_migrator using (true) with check (true)"
        ) in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog as" in sql
    assert "for share" in sql
    assert "return coalesce(current_role = p_role, false)" in sql
    assert "end; $wso$" in sql
    assert "revoke all on function public.wso_validate_tenant_authorization" in sql
    assert "grant execute on function public.wso_validate_tenant_authorization" in sql


def test_online_migration_requires_explicit_database_url(monkeypatch) -> None:
    """Catch an accidental connection to a configured default database."""
    monkeypatch.delenv("WSO_MIGRATION_DATABASE_URL", raising=False)
    config = Config(str(ROOT / "infra" / "alembic.ini"))
    with pytest.raises(RuntimeError, match="explicit Alembic URL"):
        command.current(config)


def test_explicit_migration_url_takes_priority_over_environment() -> None:
    assert (
        migration_database_url(
            "postgresql+psycopg://explicit/test",
            "postgresql+psycopg://environment/other",
            offline=False,
        )
        == "postgresql+psycopg://explicit/test"
    )


def test_tenant_session_requires_matching_authorization_before_opening_connection() -> (
    None
):
    """Catch a path that accepts a caller supplied tenant UUID as sufficient authority."""

    class UnexpectedFactory:
        def __call__(self) -> None:
            raise AssertionError("must reject before opening a database connection")

    with (
        pytest.raises(PermissionError),
        tenant_session(uuid4(), session_factory=UnexpectedFactory()),
    ):
        pass


def test_tenant_session_rejects_stale_membership_check() -> None:
    """Catch a transaction that trusts a previous bootstrap choice after revocation."""
    tenant_id, user_id = uuid4(), uuid4()
    choice = TenantAuthorization(tenant_id, user_id, "OWNER", _ISSUER_KEY)

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class Session:
        def execute(self, statement, params=None):
            sql = str(statement)
            if "current_user" in sql:
                return Result("wso_app")
            if "wso_validate_tenant_authorization" in sql:
                return Result(False)
            return Result("")

    class Factory:
        @contextmanager
        def begin(self):
            yield Session()

    with (
        pytest.raises(PermissionError),
        tenant_session(tenant_id, authorization=choice, session_factory=Factory()),
    ):
        pass


@pytest.fixture(scope="module")
def live_db():
    """Use only explicitly supplied PostgreSQL credentials for the RLS gate."""
    admin_url = os.getenv("WSO_TEST_ADMIN_DATABASE_URL")
    app_url = os.getenv("WSO_TEST_APP_DATABASE_URL")
    identity_url = os.getenv("WSO_TEST_IDENTITY_DATABASE_URL")
    if not all((admin_url, app_url, identity_url)):
        pytest.skip("requires three PostgreSQL role URLs; SQLite cannot prove RLS")
    if not all(
        url.startswith("postgresql+psycopg://")
        for url in (admin_url, app_url, identity_url)
    ):
        pytest.skip("RLS gate requires postgresql+psycopg role URLs")
    config = Config(str(ROOT / "infra" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", admin_url)
    command.upgrade(config, "head")
    admin = create_engine(admin_url)
    app = create_engine(app_url, pool_size=1, max_overflow=0)
    identity = create_engine(identity_url, pool_size=1, max_overflow=0)
    try:
        yield admin, app, identity
    finally:
        identity.dispose()
        app.dispose()
        admin.dispose()


@pytest.fixture
def seeded(live_db):
    admin, app, identity = live_db
    ids = {
        name: uuid4()
        for name in (
            "a",
            "b",
            "c",
            "user_one",
            "user_two",
            "store_a",
            "store_b",
            "store_c",
            "store_b_hidden",
        )
    }
    with admin.begin() as connection:
        for tenant in ("a", "b", "c"):
            connection.execute(
                text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
                {"id": ids[tenant], "name": tenant},
            )
        for user, subject in (("user_one", "one"), ("user_two", "two")):
            connection.execute(
                text(
                    "INSERT INTO users (id, oidc_issuer, oidc_subject) VALUES (:id, 'test-issuer', :subject)"
                ),
                {"id": ids[user], "subject": subject},
            )
        for tenant, user, role in (
            ("a", "user_one", "OWNER"),
            ("b", "user_one", "MANAGER"),
            ("c", "user_two", "STAFF"),
        ):
            connection.execute(
                text(
                    "INSERT INTO memberships (tenant_id, user_id, role) VALUES (:tenant_id, :user_id, :role)"
                ),
                {"tenant_id": ids[tenant], "user_id": ids[user], "role": role},
            )
        for tenant in ("a", "b", "c"):
            connection.execute(
                text(
                    "INSERT INTO stores (id, tenant_id, name, timezone) VALUES (:id, :tenant_id, :name, 'Asia/Seoul')"
                ),
                {
                    "id": ids[f"store_{tenant}"],
                    "tenant_id": ids[tenant],
                    "name": f"store-{tenant}",
                },
            )
        connection.execute(
            text(
                "INSERT INTO stores (id, tenant_id, name, timezone) VALUES (:id, :tenant_id, 'unassigned', 'Asia/Seoul')"
            ),
            {"id": ids["store_b_hidden"], "tenant_id": ids["b"]},
        )
        for tenant, user in (("b", "user_one"), ("c", "user_two")):
            connection.execute(
                text(
                    "INSERT INTO store_memberships (tenant_id, store_id, user_id) VALUES (:tenant_id, :store_id, :user_id)"
                ),
                {
                    "tenant_id": ids[tenant],
                    "store_id": ids[f"store_{tenant}"],
                    "user_id": ids[user],
                },
            )
    try:
        yield ids, sessionmaker(app), sessionmaker(identity)
    finally:
        with admin.begin() as connection:
            for table in (
                "store_memberships",
                "stores",
                "memberships",
                "users",
                "tenants",
            ):
                key = "id" if table in ("stores", "users", "tenants") else "tenant_id"
                values = (
                    [ids[f"store_{name}"] for name in ("a", "b", "c")]
                    + [ids["store_b_hidden"]]
                    if table == "stores"
                    else (
                        [ids["user_one"], ids["user_two"]]
                        if table == "users"
                        else [ids[name] for name in ("a", "b", "c")]
                    )
                )
                connection.execute(
                    text(f"DELETE FROM {table} WHERE {key} = ANY(:ids)"),
                    {"ids": values},
                )


def _choice(identity_factory, subject: str, tenant_id: UUID):
    with identity_session(
        "test-issuer", subject, session_factory=identity_factory
    ) as lookup:
        return next(
            choice for choice in lookup.list_tenants() if choice.tenant_id == tenant_id
        )


def test_database_role_cannot_read_another_tenant(seeded) -> None:
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    with tenant_session(
        ids["a"], authorization=choice, session_factory=app_factory
    ) as session:
        visible = set(session.execute(text("SELECT id FROM stores")).scalars())
    assert visible == {ids["store_a"]}


def test_raw_app_role_cannot_forge_tenant_context_release_gate(seeded) -> None:
    """Production gate: raw app SQL must not reach a foreign tenant by changing a GUC.

    This is expected to fail against the current migration. It remains an
    ordinary failing test on PostgreSQL until DB-verified scope replaces the
    caller-settable setting in every business-table RLS policy.
    """
    ids, app_factory, _ = seeded
    with app_factory() as session:
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(ids["b"])},
        )
        visible = set(session.execute(text("SELECT id FROM stores")).scalars())
    assert ids["store_b"] not in visible


def test_store_repository_respects_owner_and_assignments(seeded) -> None:
    ids, app_factory, identity_factory = seeded
    owner_choice = _choice(identity_factory, "one", ids["a"])
    manager_choice = _choice(identity_factory, "one", ids["b"])
    with tenant_session(
        ids["a"], authorization=owner_choice, session_factory=app_factory
    ) as session:
        assert [
            s.id for s in StoreRepository(session).list_visible(ids["user_one"])
        ] == [ids["store_a"]]
    with tenant_session(
        ids["b"], authorization=manager_choice, session_factory=app_factory
    ) as session:
        assert [
            s.id for s in StoreRepository(session).list_visible(ids["user_one"])
        ] == [ids["store_b"]]


def test_store_repository_does_not_use_another_users_membership(seeded) -> None:
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    with (
        tenant_session(
            ids["a"], authorization=choice, session_factory=app_factory
        ) as session,
        pytest.raises(PermissionError),
    ):
        StoreRepository(session).list_visible(ids["user_two"])


def test_store_repository_rejects_different_user_before_query() -> None:
    authorized_user, other_user = uuid4(), uuid4()

    class Session:
        def __init__(self):
            self.info = {"authorized_user_id": authorized_user}

        def scalars(self, statement):
            raise AssertionError("foreign user query must not reach database")

    with pytest.raises(PermissionError):
        StoreRepository(Session()).list_visible(other_user)


def test_revoked_choice_is_rejected_before_tenant_work(seeded, live_db) -> None:
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    admin, _, _ = live_db
    with admin.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM memberships WHERE tenant_id = :tenant AND user_id = :user"
            ),
            {"tenant": ids["a"], "user": ids["user_one"]},
        )
    with (
        pytest.raises(PermissionError),
        tenant_session(ids["a"], authorization=choice, session_factory=app_factory),
    ):
        pass


def test_downgraded_choice_is_rejected_and_new_role_loses_owner_view(
    seeded, live_db
) -> None:
    ids, app_factory, identity_factory = seeded
    stale_choice = _choice(identity_factory, "one", ids["a"])
    admin, _, _ = live_db
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE memberships SET role = 'STAFF' "
                "WHERE tenant_id = :tenant AND user_id = :user"
            ),
            {"tenant": ids["a"], "user": ids["user_one"]},
        )
    with (
        pytest.raises(PermissionError),
        tenant_session(
            ids["a"], authorization=stale_choice, session_factory=app_factory
        ),
    ):
        pass
    current_choice = _choice(identity_factory, "one", ids["a"])
    with tenant_session(
        ids["a"], authorization=current_choice, session_factory=app_factory
    ) as session:
        assert StoreRepository(session).list_visible(ids["user_one"]) == []


def test_membership_cannot_change_during_tenant_transaction(seeded, live_db) -> None:
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    admin, _, _ = live_db
    with (
        tenant_session(ids["a"], authorization=choice, session_factory=app_factory),
        admin.connect() as connection,
    ):
        connection.execute(text("SET lock_timeout = '100ms'"))
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "UPDATE memberships SET role = 'STAFF' "
                    "WHERE tenant_id = :tenant AND user_id = :user"
                ),
                {"tenant": ids["a"], "user": ids["user_one"]},
            )


def test_foreign_tenant_insert_and_composite_fk_are_rejected(seeded) -> None:
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    with (
        pytest.raises(DBAPIError),
        tenant_session(
            ids["a"], authorization=choice, session_factory=app_factory
        ) as session,
    ):
        session.execute(
            text(
                "INSERT INTO stores (id, tenant_id, name, timezone) VALUES (:id, :tenant_id, 'foreign', 'Asia/Seoul')"
            ),
            {"id": uuid4(), "tenant_id": ids["b"]},
        )
    with (
        pytest.raises(IntegrityError),
        tenant_session(
            ids["a"], authorization=choice, session_factory=app_factory
        ) as session,
    ):
        session.execute(
            text(
                "INSERT INTO store_memberships (tenant_id, store_id, user_id) VALUES (:tenant_id, :store_id, :user_id)"
            ),
            {
                "tenant_id": ids["a"],
                "store_id": ids["store_b"],
                "user_id": ids["user_one"],
            },
        )


def test_missing_context_and_pool_reuse_expose_no_stores(seeded) -> None:
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    with tenant_session(
        ids["a"], authorization=choice, session_factory=app_factory
    ) as session:
        assert session.execute(text("SELECT count(*) FROM stores")).scalar_one() == 1
    with app_factory() as session:
        assert session.execute(text("SELECT count(*) FROM stores")).scalar_one() == 0
    with (
        pytest.raises(PermissionError),
        tenant_session(ids["b"], authorization=choice, session_factory=app_factory),
    ):
        pass


def test_bootstrap_lists_only_verified_subject_memberships(seeded) -> None:
    ids, _, identity_factory = seeded
    with identity_session(
        "test-issuer", "one", session_factory=identity_factory
    ) as lookup:
        assert {item.tenant_id for item in lookup.list_tenants()} == {
            ids["a"],
            ids["b"],
        }
    with identity_session(
        "test-issuer", "two", session_factory=identity_factory
    ) as lookup:
        assert {item.tenant_id for item in lookup.list_tenants()} == {ids["c"]}


def test_bootstrap_unset_principal_and_denied_store_access(seeded) -> None:
    _, _, identity_factory = seeded
    with identity_factory() as session:
        assert session.execute(text("SELECT id FROM users")).all() == []
        assert session.execute(text("SELECT tenant_id FROM memberships")).all() == []
        with pytest.raises(DBAPIError):
            session.execute(text("SELECT id FROM stores")).all()
    with identity_factory() as session, pytest.raises(DBAPIError):
        session.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject) VALUES (:id, 'x', 'y')"
            ),
            {"id": uuid4()},
        )
    with identity_factory() as session, pytest.raises(DBAPIError):
        session.execute(text("SET ROLE wso_app"))


def test_bootstrap_principal_setting_does_not_survive_pool_reuse(seeded) -> None:
    ids, _, identity_factory = seeded
    with identity_session(
        "test-issuer", "one", session_factory=identity_factory
    ) as lookup:
        assert {item.tenant_id for item in lookup.list_tenants()} == {
            ids["a"],
            ids["b"],
        }
    with identity_factory() as session:
        assert session.execute(text("SELECT tenant_id FROM memberships")).all() == []


def test_database_roles_have_no_rls_bypass_or_cross_role_membership(live_db) -> None:
    admin, app, identity = live_db
    with admin.connect() as connection:
        roles = connection.execute(
            text(
                "SELECT rolname, rolbypassrls, rolsuper, rolcreaterole "
                "FROM pg_roles WHERE rolname IN "
                "('wso_app', 'wso_identity_bootstrap', 'wso_migrator')"
            )
        ).all()
    assert {row.rolname for row in roles} == {
        "wso_app",
        "wso_identity_bootstrap",
        "wso_migrator",
    }
    assert all(
        not row.rolbypassrls and not row.rolsuper and not row.rolcreaterole
        for row in roles
    )
    with admin.connect() as connection:
        inherited = connection.execute(
            text(
                "SELECT member_role.rolname FROM pg_auth_members AS grant_edge "
                "JOIN pg_roles AS member_role ON member_role.oid = grant_edge.member "
                "WHERE member_role.rolname IN ('wso_app', 'wso_identity_bootstrap')"
            )
        ).all()
    assert inherited == []
    for engine in (app, identity):
        with engine.connect() as connection, pytest.raises(DBAPIError):
            connection.execute(text("SET ROLE wso_migrator"))


def test_migrator_backfill_role_can_read_across_tenants(seeded) -> None:
    url = os.getenv("WSO_TEST_MIGRATOR_DATABASE_URL")
    if not url:
        pytest.skip("requires PostgreSQL wso_migrator role URL")
    if not url.startswith("postgresql+psycopg://"):
        pytest.skip("migrator backfill gate requires postgresql+psycopg")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT current_user")).scalar_one()
                == "wso_migrator"
            )
            assert (
                connection.execute(text("SELECT count(*) FROM stores")).scalar_one()
                >= 4
            )
    finally:
        engine.dispose()
