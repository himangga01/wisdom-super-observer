"""T02 isolation contract: offline DDL checks and optional real PostgreSQL gates."""

from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
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
        return lookup.authorize_tenant(tenant_id)


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

    RLS authority comes exclusively from a protected transaction context.
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
    choice = _choice(identity_factory, "one", ids["a"])
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


def test_membership_metadata_cannot_open_tenant_transaction() -> None:
    """A listed membership alone must not bypass database grant issuance."""
    choice = TenantAuthorization(uuid4(), uuid4(), "OWNER", _ISSUER_KEY)

    class UnexpectedFactory:
        def begin(self):
            raise AssertionError("metadata must not open a database connection")

    with (
        pytest.raises(PermissionError),
        tenant_session(
            choice.tenant_id, authorization=choice, session_factory=UnexpectedFactory()
        ),
    ):
        pass


def test_grant_guessing_cannot_establish_context(seeded) -> None:
    """A plausible random token cannot establish any tenant authority."""
    from dataclasses import replace

    ids, app_factory, identity_factory = seeded
    real_choice = _choice(identity_factory, "one", ids["a"])
    guessed = replace(real_choice, _grant_token="0" * 64)
    with (
        pytest.raises(PermissionError),
        tenant_session(ids["a"], authorization=guessed, session_factory=app_factory),
    ):
        pass


@pytest.mark.parametrize("rollback", [False, True])
def test_grant_replay_after_commit_or_rollback_is_rejected(seeded, rollback) -> None:
    """A failed business transaction must not resurrect its consumed grant."""
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])

    class BusinessFailure(Exception):
        pass

    try:
        with tenant_session(
            ids["a"], authorization=choice, session_factory=app_factory
        ) as session:
            assert (
                session.execute(text("SELECT count(*) FROM stores")).scalar_one() == 1
            )
            if rollback:
                raise BusinessFailure
    except BusinessFailure:
        pass
    with (
        pytest.raises(PermissionError),
        tenant_session(ids["a"], authorization=choice, session_factory=app_factory),
    ):
        pass


def test_expired_grant_is_rejected(seeded, live_db) -> None:
    """Expiry is enforced by database time even for genuine issued tokens."""
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    admin, _, _ = live_db
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE wso_private.tenant_grants SET expires_at = clock_timestamp() - interval '1 second' WHERE tenant_id = :tenant"
            ),
            {"tenant": ids["a"]},
        )
    with (
        pytest.raises(PermissionError),
        tenant_session(ids["a"], authorization=choice, session_factory=app_factory),
    ):
        pass


def test_bootstrap_cannot_issue_foreign_tenant_grant(seeded) -> None:
    ids, _, identity_factory = seeded
    with identity_session(
        "test-issuer", "one", session_factory=identity_factory
    ) as lookup:
        assert lookup.user_id() == ids["user_one"]
        with pytest.raises(PermissionError):
            lookup.authorize_tenant(ids["c"])
    with identity_factory() as session:
        assert (
            session.execute(
                text("SELECT * FROM public.wso_issue_tenant_grant(:tenant)"),
                {"tenant": ids["a"]},
            ).all()
            == []
        )


def test_valid_grant_cannot_be_relabelled_for_foreign_tenant(seeded) -> None:
    from dataclasses import replace

    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    forged = replace(choice, tenant_id=ids["c"], user_id=ids["user_two"], role="STAFF")
    with (
        pytest.raises(PermissionError),
        tenant_session(ids["c"], authorization=forged, session_factory=app_factory),
    ):
        pass


def test_app_cannot_replace_active_context_using_gucs(seeded) -> None:
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    with tenant_session(
        ids["a"], authorization=choice, session_factory=app_factory
    ) as session:
        for setting, value in (
            ("app.tenant_id", str(ids["c"])),
            ("app.oidc_issuer", "test-issuer"),
            ("app.oidc_subject", "two"),
        ):
            session.execute(
                text("SELECT set_config(:setting, :value, true)"),
                {"setting": setting, "value": value},
            )
        assert set(session.execute(text("SELECT id FROM stores")).scalars()) == {
            ids["store_a"]
        }
        assert set(session.execute(text("SELECT id FROM tenants")).scalars()) == {
            ids["a"]
        }
        assert set(
            session.execute(text("SELECT tenant_id FROM memberships")).scalars()
        ) == {ids["a"]}


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM wso_private.tenant_grants",
        "SELECT * FROM wso_private.tenant_contexts",
        "INSERT INTO wso_private.tenant_contexts VALUES (1, 1, gen_random_uuid(), gen_random_uuid(), 'OWNER')",
        "SELECT * FROM public.wso_issue_tenant_grant(gen_random_uuid())",
        "SELECT public.wso_validate_tenant_authorization(gen_random_uuid(), gen_random_uuid(), 'OWNER')",
        "SET ROLE wso_identity_bootstrap",
    ],
)
def test_app_cannot_access_grant_internals_or_issuer(seeded, query) -> None:
    _, app_factory, _ = seeded
    with app_factory() as session, pytest.raises(DBAPIError):
        session.execute(text(query))


def test_runtime_roles_do_not_own_grant_tables_or_functions(live_db) -> None:
    admin, _, _ = live_db
    with admin.connect() as connection:
        functions = connection.execute(
            text("""
            SELECT p.proname, p.prosecdef, p.proconfig, r.rolname AS owner,
                   has_function_privilege('wso_app', p.oid, 'EXECUTE') AS app_execute,
                   has_function_privilege('wso_identity_bootstrap', p.oid, 'EXECUTE') AS identity_execute
            FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
            WHERE p.proname IN ('wso_issue_tenant_grant', 'wso_consume_tenant_grant', 'wso_current_tenant_id')
        """)
        ).all()
        assert len(functions) == 3
        for function in functions:
            assert function.owner == "wso_migrator"
            assert function.prosecdef
            assert function.proconfig == ["search_path=pg_catalog"]
            assert function.identity_execute == (
                function.proname == "wso_issue_tenant_grant"
            )
            assert function.app_execute == (
                function.proname != "wso_issue_tenant_grant"
            )
        tables = connection.execute(
            text("""
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, r.rolname AS owner
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_roles r ON r.oid = c.relowner
            WHERE n.nspname = 'wso_private' AND c.relkind = 'r'
        """)
        ).all()
        assert {"tenant_grants", "tenant_contexts"} <= {
            table.relname for table in tables
        }
        assert all(
            t.owner == "wso_migrator" and t.relrowsecurity and t.relforcerowsecurity
            for t in tables
        )


def test_grant_secret_is_not_in_authorization_repr(seeded) -> None:
    ids, _, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    assert choice._grant_token not in repr(choice)


def test_provisioned_user_without_membership_is_visible_to_bootstrap(
    seeded, live_db
) -> None:
    ids, _, identity_factory = seeded
    admin, _, _ = live_db
    with admin.begin() as connection:
        connection.execute(
            text("DELETE FROM store_memberships WHERE user_id = :user"),
            {"user": ids["user_two"]},
        )
        connection.execute(
            text("DELETE FROM memberships WHERE user_id = :user"),
            {"user": ids["user_two"]},
        )
    with identity_session(
        "test-issuer", "two", session_factory=identity_factory
    ) as lookup:
        assert lookup.user_id() == ids["user_two"]
        assert lookup.list_tenants() == []


def test_membership_change_after_redemption_before_work_is_rejected(
    seeded, live_db
) -> None:
    """The durable-consume/business-transaction gap cannot retain a stale role."""
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    admin, app, _ = live_db
    redemption = create_engine(app.url)
    try:
        with app_factory.begin() as session:
            target = session.execute(
                text("SELECT pg_backend_pid(), txid_current()")
            ).one()
            with redemption.begin() as connection:
                accepted = connection.execute(
                    text(
                        "SELECT public.wso_consume_tenant_grant(:token, :pid, :tx, :tenant, :user, :role)"
                    ),
                    {
                        "token": choice._grant_token,
                        "pid": target[0],
                        "tx": target[1],
                        "tenant": choice.tenant_id,
                        "user": choice.user_id,
                        "role": choice.role,
                    },
                ).scalar_one()
                assert accepted
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE memberships SET role = 'STAFF' WHERE tenant_id = :tenant AND user_id = :user"
                    ),
                    {"tenant": ids["a"], "user": ids["user_one"]},
                )
            assert (
                session.execute(
                    text("SELECT public.wso_current_tenant_id()")
                ).scalar_one()
                is None
            )
            assert session.execute(text("SELECT id FROM stores")).all() == []
    finally:
        redemption.dispose()


def test_redemption_cannot_bind_a_nonexistent_future_transaction(
    seeded, live_db
) -> None:
    """A committed context cannot be planted for a guessed future transaction."""
    ids, app_factory, identity_factory = seeded
    choice = _choice(identity_factory, "one", ids["a"])
    _, app, _ = live_db
    redemption = create_engine(app.url)
    try:
        with app_factory.begin() as session:
            target = session.execute(
                text("SELECT pg_backend_pid(), txid_current()")
            ).one()
            with redemption.begin() as connection:
                accepted = connection.execute(
                    text(
                        "SELECT public.wso_consume_tenant_grant(:token, :pid, :tx, :tenant, :user, :role)"
                    ),
                    {
                        "token": choice._grant_token,
                        "pid": target[0],
                        "tx": target[1] + 1000000,
                        "tenant": choice.tenant_id,
                        "user": choice.user_id,
                        "role": choice.role,
                    },
                ).scalar_one()
                assert not accepted
            assert session.execute(text("SELECT id FROM stores")).all() == []
    finally:
        redemption.dispose()


def test_grant_migration_empty_upgrade_and_predecessor_roundtrip(live_db) -> None:
    """The new revision must remain independently reversible on real PostgreSQL."""
    admin, _, _ = live_db
    database_name = "wso_grant_migration_" + uuid4().hex
    control = create_engine(admin.url, isolation_level="AUTOCOMMIT")
    isolated = None
    try:
        with control.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        isolated_url = admin.url.set(database=database_name)
        isolated = create_engine(isolated_url)
        config = Config(str(ROOT / "infra" / "alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            isolated_url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        command.upgrade(config, "0001b_tenant_grants")
        with isolated.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "0001b_tenant_grants"
            )
            assert connection.execute(
                text("SELECT to_regclass('wso_private.tenant_grants') IS NOT NULL")
            ).scalar_one()
        command.downgrade(config, "0001_tenants")
        with isolated.connect() as connection:
            assert connection.execute(
                text("SELECT to_regclass('wso_private.tenant_grants') IS NULL")
            ).scalar_one()
            assert connection.execute(
                text(
                    "SELECT has_function_privilege('wso_app', 'public.wso_validate_tenant_authorization(uuid,uuid,text)', 'EXECUTE')"
                )
            ).scalar_one()
        migrator_url = os.getenv("WSO_TEST_MIGRATOR_DATABASE_URL")
        if migrator_url:
            with control.connect() as connection:
                connection.execute(
                    text(f'GRANT CREATE ON DATABASE "{database_name}" TO wso_migrator')
                )
            config.set_main_option(
                "sqlalchemy.url",
                make_url(migrator_url)
                .set(database=database_name)
                .render_as_string(hide_password=False)
                .replace("%", "%%"),
            )
        command.upgrade(config, "0001b_tenant_grants")
        with isolated.connect() as connection:
            assert not connection.execute(
                text(
                    "SELECT has_function_privilege('wso_app', 'public.wso_validate_tenant_authorization(uuid,uuid,text)', 'EXECUTE')"
                )
            ).scalar_one()
        command.downgrade(config, "base")
        with isolated.connect() as connection:
            assert connection.execute(
                text("SELECT to_regclass('public.stores') IS NULL")
            ).scalar_one()
    finally:
        if isolated is not None:
            isolated.dispose()
        with control.connect() as connection:
            connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        control.dispose()


def test_concurrent_grants_cannot_replace_same_transaction_context(
    seeded, live_db
) -> None:
    """Two genuine grants racing for one PID/XID must install exactly one scope."""
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic, sleep

    ids, app_factory, identity_factory = seeded
    choices = (
        _choice(identity_factory, "one", ids["a"]),
        _choice(identity_factory, "two", ids["c"]),
    )
    admin, app, _ = live_db
    application_name = "t02-context-race-" + uuid4().hex
    redemption = create_engine(
        app.url,
        hide_parameters=True,
        connect_args={"application_name": application_name},
    )

    def consume(choice, target):
        with redemption.begin() as connection:
            connection.execute(text("SET LOCAL statement_timeout = '10s'"))
            return connection.execute(
                text(
                    "SELECT public.wso_consume_tenant_grant(:token, :pid, :tx, :tenant, :user, :role)"
                ),
                {
                    "token": choice._grant_token,
                    "pid": target[0],
                    "tx": target[1],
                    "tenant": choice.tenant_id,
                    "user": choice.user_id,
                    "role": choice.role,
                },
            ).scalar_one()

    try:
        with app_factory.begin() as session, ThreadPoolExecutor(max_workers=2) as pool:
            target = session.execute(
                text("SELECT pg_backend_pid(), txid_current()")
            ).one()
            with admin.begin() as blocker:
                # Both consumers must pass the previous non-atomic precheck
                # before either INSERT can obtain its RowExclusiveLock.
                blocker.execute(
                    text("LOCK TABLE wso_private.tenant_contexts IN SHARE MODE")
                )
                futures = [pool.submit(consume, choice, target) for choice in choices]
                deadline = monotonic() + 5
                while True:
                    with admin.connect() as observer:
                        waiting = observer.execute(
                            text("""
                            SELECT count(*) FROM pg_locks l
                            JOIN pg_stat_activity a ON a.pid = l.pid
                            WHERE a.application_name = :name
                              AND l.relation = 'wso_private.tenant_contexts'::regclass
                              AND l.mode = 'RowExclusiveLock' AND NOT l.granted
                        """),
                            {"name": application_name},
                        ).scalar_one()
                    if waiting == 2:
                        break
                    assert monotonic() < deadline, (
                        "both consumers did not reach context installation"
                    )
                    sleep(0.01)
            accepted = [future.result(timeout=10) for future in futures]
            assert accepted.count(True) == 1, (
                "same-transaction context was installed more than once"
            )
            winner = choices[accepted.index(True)]
            loser = choices[accepted.index(False)]
            assert (
                session.execute(
                    text("SELECT public.wso_current_tenant_id()")
                ).scalar_one()
                == winner.tenant_id
            )
            assert not consume(loser, target)
            assert (
                session.execute(
                    text("SELECT public.wso_current_tenant_id()")
                ).scalar_one()
                == winner.tenant_id
            )
            with admin.connect() as observer:
                context = observer.execute(
                    text(
                        "SELECT tenant_id, user_id FROM wso_private.tenant_contexts WHERE backend_pid = :pid AND transaction_id = :tx"
                    ),
                    {"pid": target[0], "tx": target[1]},
                ).one()
                assert context.tenant_id == winner.tenant_id
                assert context.user_id == winner.user_id
    finally:
        redemption.dispose()


def test_issuance_skips_locked_expired_grants_before_locking_membership(
    seeded, live_db
) -> None:
    """Cleanup must not wait on a grant while retaining a membership share lock."""
    from concurrent.futures import ThreadPoolExecutor

    ids, _, identity_factory = seeded
    _choice(identity_factory, "one", ids["a"])
    admin, _, identity = live_db
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE wso_private.tenant_grants SET expires_at = clock_timestamp() - interval '1 second' WHERE tenant_id = :tenant"
            ),
            {"tenant": ids["a"]},
        )
    issuer_engine = create_engine(identity.url, hide_parameters=True)

    def issue_while_locked():
        with issuer_engine.begin() as connection:
            connection.execute(text("SET LOCAL statement_timeout = '1s'"))
            connection.execute(
                text(
                    "SELECT set_config('app.oidc_issuer', 'test-issuer', true), set_config('app.oidc_subject', 'one', true)"
                )
            )
            return connection.execute(
                text("SELECT user_id FROM public.wso_issue_tenant_grant(:tenant)"),
                {"tenant": ids["a"]},
            ).scalar_one()

    try:
        with (
            ThreadPoolExecutor(max_workers=1) as pool,
            admin.begin() as redemption_stage,
        ):
            # Model a redemption holding its grant lock before requesting
            # its membership lock. Cleanup must never wait on that row.
            redemption_stage.execute(
                text(
                    "SELECT token_hash FROM wso_private.tenant_grants WHERE tenant_id = :tenant FOR UPDATE"
                ),
                {"tenant": ids["a"]},
            )
            future = pool.submit(issue_while_locked)
            issued_user = future.result(timeout=3)
            assert issued_user == ids["user_one"]
            # A concurrent membership mutation must then be free to finish;
            # the issuer cannot retain a share lock while waiting on cleanup.
            with admin.begin() as mutation:
                mutation.execute(text("SET LOCAL lock_timeout = '100ms'"))
                mutation.execute(
                    text(
                        "UPDATE memberships SET role = 'STAFF' WHERE tenant_id = :tenant AND user_id = :user"
                    ),
                    {"tenant": ids["a"], "user": ids["user_one"]},
                )
    finally:
        issuer_engine.dispose()


@pytest.mark.parametrize("role_index", [1, 2], ids=["app", "bootstrap"])
def test_tenant_runtime_roles_cannot_switch_to_session_role(
    live_db, role_index
) -> None:
    """Tenant or identity credentials must not reach pre-tenant session storage."""
    with live_db[role_index].connect() as connection:
        with pytest.raises(DBAPIError) as denied:
            connection.execute(text("SET ROLE wso_web_session"))
        assert denied.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM public.wso_issue_tenant_grant(gen_random_uuid())",
        "SELECT public.wso_consume_tenant_grant(repeat('0', 64), pg_backend_pid(), txid_current(), gen_random_uuid(), gen_random_uuid(), 'OWNER')",
        "SELECT public.wso_current_tenant_id()",
        "SELECT * FROM wso_private.tenant_grants",
        "SELECT * FROM wso_private.tenant_contexts",
        "SELECT * FROM public.tenants",
        "SELECT * FROM public.users",
        "SELECT * FROM public.memberships",
        "SELECT * FROM public.stores",
        "SELECT * FROM public.store_memberships",
        "SELECT * FROM public.audit_events",
        "SET ROLE wso_app",
        "SET ROLE wso_identity_bootstrap",
        "SET ROLE wso_migrator",
    ],
)
def test_session_role_cannot_enter_tenant_or_identity_authority(live_db, query) -> None:
    """Session credentials have no tenant grants, business rows or role switches."""
    session_url = os.getenv("WSO_TEST_SESSION_DATABASE_URL")
    if not session_url:
        pytest.skip("requires PostgreSQL wso_web_session role URL")
    if not session_url.startswith("postgresql+psycopg://"):
        pytest.skip("session-role denial gate requires postgresql+psycopg")
    engine = create_engine(session_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT current_user")).scalar_one()
                == "wso_web_session"
            )
            with pytest.raises(DBAPIError) as denied:
                connection.execute(text(query))
            # Authentication/schema/function errors cannot masquerade as denial.
            assert denied.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()
