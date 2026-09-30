"""Credential confidentiality and capability lifecycle against actual PostgreSQL."""

from uuid import uuid4

import pytest


def test_authenticated_encryption_binds_all_identity_fields(tmp_path):
    from wso_core.secrets import FileKeyProvider, SecretCipher, SecretRejected

    key = tmp_path / "key"
    key.write_bytes(bytes(range(32)))
    cipher = SecretCipher(FileKeyProvider(key))
    tenant, connection, version = uuid4(), uuid4(), uuid4()
    envelope = cipher.seal(tenant, connection, version, b"saved-password")
    assert b"saved-password" not in envelope.ciphertext
    assert "saved-password" not in repr(envelope)
    assert cipher.open(tenant, connection, version, envelope) == b"saved-password"
    assert cipher.seal(tenant, connection, version, b"saved-password") != envelope
    for identity in (
        (uuid4(), connection, version),
        (tenant, uuid4(), version),
        (tenant, connection, uuid4()),
    ):
        with pytest.raises(SecretRejected):
            cipher.open(*identity, envelope)
    from dataclasses import replace

    with pytest.raises(SecretRejected):
        cipher.open(
            tenant,
            connection,
            version,
            replace(
                envelope,
                ciphertext=envelope.ciphertext[:-1]
                + bytes([envelope.ciphertext[-1] ^ 1]),
            ),
        )


def test_missing_and_invalid_key_fail_closed(tmp_path):
    from wso_core.secrets import FileKeyProvider, SecretCipher, SecretRejected

    path = tmp_path / "missing"
    for contents in (None, b"short"):
        if contents is not None:
            path.write_bytes(contents)
        with pytest.raises(SecretRejected):
            SecretCipher(FileKeyProvider(path)).seal(
                uuid4(), uuid4(), uuid4(), b"secret"
            )


import os

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.auth_support import login

pytest_plugins = ["tests.auth_support"]


@pytest.fixture
def connection_case(auth_case, signing_key, tmp_path):
    from wso_api.connections.router import configure_connections
    from wso_core.secrets import FileKeyProvider

    client, ids, service, admin = auth_case
    key = tmp_path / "key"
    key.write_bytes(bytes(range(32)))
    configure_connections(client.app, FileKeyProvider(key))
    auth = login(client, signing_key, ids, "owner")
    headers = {"Origin": "https://app.test", "X-CSRF-Token": auth["csrf_token"]}
    try:
        yield client, ids, service, admin, headers, FileKeyProvider(key)
    finally:
        with admin.begin() as db:
            db.execute(
                text("DELETE FROM connections WHERE tenant_id = ANY(:ids)"),
                {"ids": [ids["a"], ids["b"]]},
            )
            db.execute(
                text("DELETE FROM audit_events WHERE tenant_id = ANY(:ids)"),
                {"ids": [ids["a"], ids["b"]]},
            )


def create_connection(case, **changes):
    client, ids, _, _, headers, _ = case
    data = {
        "kind": "TVT_ACCOUNT",
        "alias": "Office",
        "site": "Seoul",
        "username": "fixture-user",
        "password": "password-canary-84726",
        "store_ids": [],
    }
    data.update(changes)
    return client.post(
        f"/api/v1/connections?tenant_id={ids['a']}", json=data, headers=headers
    )


def test_api_roundtrip_redaction_generation_and_disconnect(connection_case, caplog):
    client, ids, _, admin, headers, _ = connection_case
    response = create_connection(connection_case)
    assert response.status_code == 201, response.text
    item = response.json()
    assert set(item) == {
        "id",
        "tenant_id",
        "kind",
        "alias",
        "site",
        "status",
        "last_success",
        "generation",
        "store_ids",
    }
    assert item["status"] == "NOT_VERIFIED" and item["store_ids"] == []
    path = f"/api/v1/connections/{item['id']}?tenant_id={ids['a']}"
    updated = client.patch(
        path,
        headers=headers,
        json={
            "expected_generation": 1,
            "username": "new-user",
            "password": "next-password",
            "store_ids": [str(ids["assigned"])],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["generation"] == 2
    assert (
        client.patch(
            path, headers=headers, json={"expected_generation": 1, "alias": "stale"}
        ).status_code
        == 409
    )
    disconnected = client.post(
        path.replace("?", "/disconnect?"),
        headers=headers,
        json={"expected_generation": 2},
    )
    assert disconnected.status_code == 200, disconnected.text
    assert disconnected.json()["status"] == "DISCONNECTED"
    with admin.connect() as db:
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.connection_secrets WHERE connection_id=:id"
                ),
                {"id": item["id"]},
            ).scalar_one()
            == 0
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM wso_private.connection_revocations WHERE connection_id=:id"
                ),
                {"id": item["id"]},
            ).scalar_one()
            == 2
        )
        audit = str(
            db.execute(
                text("SELECT * FROM audit_events WHERE entity_id=:id"),
                {"id": item["id"]},
            ).all()
        )
    assert "password-canary-84726" not in response.text + audit + caplog.text
    assert "fixture-user" not in response.text + audit + caplog.text
    assert (
        client.request(
            "DELETE", path, headers=headers, json={"expected_generation": 3}
        ).status_code
        == 204
    )
    assert client.get(path).status_code == 404


def test_foreign_mapping_csrf_nonowner_and_validation(connection_case, signing_key):
    client, ids, _, _, headers, _ = connection_case
    assert (
        create_connection(connection_case, store_ids=[str(ids["foreign"])]).status_code
        == 404
    )
    assert (
        create_connection(connection_case, store_ids=[str(ids["inactive"])]).status_code
        == 404
    )
    item = create_connection(connection_case).json()
    path = f"/api/v1/connections/{item['id']}?tenant_id={ids['a']}"
    for invalid in (
        {},
        {"Origin": "https://evil.test", "X-CSRF-Token": headers["X-CSRF-Token"]},
        {"Origin": "https://app.test", "X-CSRF-Token": "wrong"},
    ):
        assert (
            client.patch(
                path, json={"expected_generation": 1, "alias": "oops"}, headers=invalid
            ).status_code
            == 403
        )
    for body in (
        {"expected_generation": 1, "username": "canary-credential"},
        {"expected_generation": 1, "password": ""},
        {"expected_generation": 1, "secret": "canary-credential"},
    ):
        response = client.patch(path, headers=headers, json=body)
        assert response.status_code == 422
        assert "canary-credential" not in response.text
    assert client.get(path.replace(str(ids["a"]), str(ids["b"]))).status_code == 404
    auth = login(client, signing_key, ids, "staff")
    assert client.get(f"/api/v1/connections?tenant_id={ids['a']}").status_code == 403
    assert (
        client.patch(
            path,
            headers={"Origin": "https://app.test", "X-CSRF-Token": auth["csrf_token"]},
            json={"expected_generation": 1, "alias": "oops"},
        ).status_code
        == 403
    )


def owner_scope(case):
    from datetime import UTC, datetime, timedelta

    from wso_api.auth import WebSession
    from wso_api.stores.router import require_tenant

    _, ids, service, _, _, _ = case
    principal = WebSession(
        "https://issuer.test",
        str(ids["owner"]),
        ids["owner"],
        "",
        datetime.now(UTC) + timedelta(minutes=5),
    )
    return require_tenant(
        "connections:write", ids["a"], service=service, principal=principal
    )


def issue(case, item):
    from wso_core.connections import ConnectionService

    with owner_scope(case) as scope:
        return ConnectionService(scope.session, case[5]).authorize_worker(
            item["id"], item["generation"]
        )


def test_one_use_worker_handle_revalidation_and_expiry(connection_case):
    from wso_core.secrets import SecretRejected, WorkerSecretStore

    client, ids, _, admin, headers, provider = connection_case
    worker = WorkerSecretStore(os.environ["WSO_TEST_WORKER_DATABASE_URL"], provider)
    item = create_connection(connection_case).json()
    handle = issue(connection_case, item)
    lease = worker.with_secret(handle)
    assert "password-canary-84726" in lease.use(lambda credential: credential.decode())
    with pytest.raises(SecretRejected):
        worker.with_secret(handle)
    with pytest.raises(SecretRejected):
        worker.with_secret("guessed-capability")
    path = f"/api/v1/connections/{item['id']}?tenant_id={ids['a']}"
    response = client.patch(
        path,
        headers=headers,
        json={"expected_generation": 1, "username": "new", "password": "new-password"},
    )
    assert response.status_code == 200
    with pytest.raises(SecretRejected):
        lease.use(lambda value: value)
    with pytest.raises(SecretRejected):
        issue(connection_case, item)
    fresh = issue(connection_case, response.json())
    with admin.begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.connection_handles SET expires_at=clock_timestamp()-interval '1 second' WHERE connection_id=:id"
            ),
            {"id": item["id"]},
        )
    with pytest.raises(SecretRejected):
        worker.with_secret(fresh)


@pytest.mark.parametrize(
    "env",
    [
        "WSO_TEST_APP_DATABASE_URL",
        "WSO_TEST_IDENTITY_DATABASE_URL",
        "WSO_TEST_SESSION_DATABASE_URL",
        "WSO_TEST_WORKER_DATABASE_URL",
    ],
)
@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM wso_private.connection_secrets",
        "SELECT * FROM wso_private.connection_handles",
        "SELECT * FROM wso_private.connection_leases",
        "SELECT * FROM wso_private.connection_revocations",
        "SET ROLE wso_migrator",
    ],
)
def test_runtime_roles_cannot_read_private_rows_or_escalate(
    connection_case, env, query
):
    engine = create_engine(os.environ[env], hide_parameters=True)
    try:
        with engine.connect() as db:
            with pytest.raises(DBAPIError) as denied:
                db.execute(text(query))
            assert denied.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "env",
    [
        "WSO_TEST_APP_DATABASE_URL",
        "WSO_TEST_IDENTITY_DATABASE_URL",
        "WSO_TEST_SESSION_DATABASE_URL",
    ],
)
@pytest.mark.parametrize(
    "query",
    [
        "SET ROLE wso_connection_worker",
        "SELECT * FROM public.wso_use_connection_lease(repeat('0',64))",
        "SELECT public.wso_redeem_connection_handle(repeat('0',64),repeat('1',64))",
    ],
)
def test_nonworker_cannot_redeem_decrypt_or_switch(connection_case, env, query):
    engine = create_engine(os.environ[env], hide_parameters=True)
    try:
        with engine.connect() as db:
            with pytest.raises(DBAPIError) as denied:
                db.execute(text(query))
            assert denied.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM connections",
        "SELECT * FROM store_connections",
        "SELECT * FROM web_sessions",
        "SELECT * FROM users",
        "SELECT * FROM memberships",
        "SELECT public.wso_issue_connection_handle(gen_random_uuid(),1)",
        "SELECT * FROM public.wso_issue_tenant_grant(gen_random_uuid())",
        "SET ROLE wso_app",
        "SET ROLE wso_identity_bootstrap",
        "SET ROLE wso_web_session",
    ],
)
def test_worker_cannot_bootstrap_or_issue_its_own_capability(connection_case, query):
    engine = create_engine(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], hide_parameters=True
    )
    try:
        with engine.connect() as db:
            with pytest.raises(DBAPIError) as denied:
                db.execute(text(query))
            assert denied.value.orig.sqlstate == "42501"
    finally:
        engine.dispose()


def test_disconnect_and_delete_revoke_pending_handles_and_leases(connection_case):
    from wso_core.secrets import SecretRejected, WorkerSecretStore

    client, ids, _, _, headers, provider = connection_case
    worker = WorkerSecretStore(os.environ["WSO_TEST_WORKER_DATABASE_URL"], provider)
    for action in ("disconnect", "delete"):
        item = create_connection(connection_case).json()
        pending = issue(connection_case, item)
        lease = worker.with_secret(issue(connection_case, item))
        path = f"/api/v1/connections/{item['id']}"
        response = client.request(
            "POST" if action == "disconnect" else "DELETE",
            path
            + ("/disconnect" if action == "disconnect" else "")
            + f"?tenant_id={ids['a']}",
            headers=headers,
            json={"expected_generation": 1},
        )
        assert response.status_code == (200 if action == "disconnect" else 204)
        with pytest.raises(SecretRejected):
            worker.with_secret(pending)
        with pytest.raises(SecretRejected):
            lease.use(lambda value: value)
        if action == "disconnect":
            reconnected = client.patch(
                path + f"?tenant_id={ids['a']}",
                headers=headers,
                json={
                    "expected_generation": 2,
                    "username": "reconnected",
                    "password": "replacement",
                },
            )
            assert reconnected.status_code == 200
            fresh = worker.with_secret(issue(connection_case, reconnected.json()))
            assert b"replacement" in fresh.use(lambda value: value)


def test_worker_rechecks_membership_and_lease_expiry(connection_case):
    from wso_core.secrets import SecretRejected, WorkerSecretStore

    _, ids, _, admin, _, provider = connection_case
    worker = WorkerSecretStore(os.environ["WSO_TEST_WORKER_DATABASE_URL"], provider)
    item = create_connection(connection_case).json()
    lease = worker.with_secret(issue(connection_case, item))
    pending = issue(connection_case, item)
    with admin.begin() as db:
        db.execute(
            text(
                "UPDATE memberships SET role='STAFF' WHERE tenant_id=:t AND user_id=:u"
            ),
            {"t": ids["a"], "u": ids["owner"]},
        )
    with pytest.raises(SecretRejected):
        lease.use(lambda value: value)
    with pytest.raises(SecretRejected):
        worker.with_secret(pending)
    with admin.begin() as db:
        db.execute(
            text(
                "UPDATE memberships SET role='OWNER' WHERE tenant_id=:t AND user_id=:u"
            ),
            {"t": ids["a"], "u": ids["owner"]},
        )
        db.execute(
            text(
                "UPDATE wso_private.connection_leases SET expires_at=clock_timestamp()-interval '1 second' WHERE connection_id=:id"
            ),
            {"id": item["id"]},
        )
    with pytest.raises(SecretRejected):
        lease.use(lambda value: value)


def test_callback_rollback_cannot_restore_consumed_handle(connection_case):
    from wso_core.secrets import SecretRejected, WorkerSecretStore

    worker = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    handle = issue(connection_case, create_connection(connection_case).json())
    lease = worker.with_secret(handle)

    def failing_use(value):
        raise RuntimeError("controlled adapter failure")

    with pytest.raises(RuntimeError, match="controlled adapter failure"):
        lease.use(failing_use)
    with pytest.raises(SecretRejected):
        worker.with_secret(handle)


def test_mutation_waits_for_inflight_use_then_old_lease_is_denied(connection_case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    from wso_core.connections import ConnectionService
    from wso_core.secrets import SecretRejected, WorkerSecretStore

    item = create_connection(connection_case).json()
    worker = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    lease = worker.with_secret(issue(connection_case, item))
    entered, release, started = Event(), Event(), Event()
    mutation_pid = []

    def use(value):
        entered.set()
        assert release.wait(5)
        return b"password-canary-84726" in value

    def disconnect():
        with owner_scope(connection_case) as scope:
            mutation_pid.append(
                scope.session.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            started.set()
            return ConnectionService(scope.session).disconnect(item["id"], 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        current = pool.submit(lease.use, use)
        assert entered.wait(5)
        pending = pool.submit(disconnect)
        assert started.wait(5)
        try:
            # The worker holds a FOR SHARE connection lock until use finishes.
            deadline = monotonic() + 3
            while True:
                assert not pending.done(), "mutation committed during credential use"
                with connection_case[3].connect() as db:
                    waiting = db.execute(
                        text(
                            "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"
                        ),
                        {"pid": mutation_pid[0]},
                    ).scalar_one()
                if waiting == "Lock":
                    break
                assert monotonic() < deadline, (
                    "mutation did not wait on the credential-use lock"
                )
                sleep(0.01)
        finally:
            release.set()
        assert current.result(timeout=5)
        assert pending.result(timeout=5).generation == 2
    with pytest.raises(SecretRejected):
        lease.use(lambda value: value)


def test_two_updates_with_same_generation_have_exactly_one_winner(connection_case):
    from concurrent.futures import ThreadPoolExecutor

    from wso_core.connections import ConnectionFailure, ConnectionService

    item = create_connection(connection_case).json()

    def update(alias):
        try:
            with owner_scope(connection_case) as scope:
                return (
                    ConnectionService(scope.session)
                    .mutate(
                        "update",
                        {"alias": alias},
                        connection_id=item["id"],
                        expected_generation=1,
                    )
                    .generation
                )
        except ConnectionFailure as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["first", "second"]))
    assert sorted(results) == [2, 409]


def test_foreign_mapping_is_rejected_by_composite_database_fk(connection_case):
    from sqlalchemy.exc import IntegrityError

    _, ids, _, admin, _, _ = connection_case
    item = create_connection(connection_case).json()
    with admin.begin() as db:
        with pytest.raises(IntegrityError) as denied:
            db.execute(
                text(
                    "INSERT INTO store_connections(tenant_id,connection_id,store_id) VALUES(:t,:c,:s)"
                ),
                {"t": ids["a"], "c": item["id"], "s": ids["foreign"]},
            )
        assert denied.value.orig.sqlstate == "23503"


def test_worker_rejects_tampered_saved_ciphertext(connection_case):
    from wso_core.secrets import SecretRejected, WorkerSecretStore

    item = create_connection(connection_case).json()
    worker = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    lease = worker.with_secret(issue(connection_case, item))
    with connection_case[3].begin() as db:
        db.execute(
            text(
                "UPDATE wso_private.connection_secrets SET ciphertext=set_byte(ciphertext,0,get_byte(ciphertext,0)#1) WHERE connection_id=:id"
            ),
            {"id": item["id"]},
        )
    with pytest.raises(SecretRejected):
        lease.use(lambda value: value)


def test_migration_roundtrip_on_isolated_database():
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    admin_url = os.getenv("WSO_TEST_ADMIN_DATABASE_URL")
    if not admin_url:
        pytest.skip("requires explicit PostgreSQL admin URL")
    database = "t04_roundtrip_" + uuid4().hex
    control = create_engine(
        make_url(admin_url).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
    )
    isolated = None
    try:
        with control.connect() as db:
            db.execute(text(f'CREATE DATABASE "{database}" OWNER wso_migrator'))
        isolated = create_engine(
            make_url(admin_url).set(database=database), hide_parameters=True
        )
        with isolated.begin() as db:
            db.execute(text("GRANT USAGE, CREATE ON SCHEMA public TO wso_migrator"))
        config = Config(str(Path(__file__).resolve().parents[2] / "infra/alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            make_url(admin_url)
            .set(database=database)
            .render_as_string(hide_password=False)
            .replace("%", "%%"),
        )
        command.upgrade(config, "0001c_auth_sessions")
        command.upgrade(config, "head")
        with isolated.connect() as db:
            assert (
                db.execute(
                    text(
                        "SELECT has_table_privilege('wso_app','wso_private.connection_secrets','SELECT')"
                    )
                ).scalar_one()
                is False
            )
            assert (
                db.execute(
                    text(
                        "SELECT has_function_privilege('wso_connection_worker','public.wso_use_connection_lease(text)','EXECUTE')"
                    )
                ).scalar_one()
                is True
            )
        command.downgrade(config, "0001c_auth_sessions")
        with isolated.connect() as db:
            assert db.execute(
                text("SELECT to_regclass('public.connections') IS NULL")
            ).scalar_one()
            assert db.execute(
                text("SELECT to_regclass('public.web_sessions') IS NOT NULL")
            ).scalar_one()
        command.upgrade(config, "head")
        command.downgrade(config, "base")
    finally:
        if isolated:
            isolated.dispose()
        with control.connect() as db:
            db.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        control.dispose()


def test_missing_key_is_sanitized_and_does_not_persist_partial_connection(
    connection_case,
):
    client, ids, _, admin, _, _ = connection_case
    client.app.state.connection_key_provider = None
    response = create_connection(connection_case)
    assert response.status_code == 503
    assert "password-canary-84726" not in response.text
    with admin.connect() as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM connections WHERE tenant_id=:t"),
                {"t": ids["a"]},
            ).scalar_one()
            == 0
        )


def test_owner_grant_required_even_for_raw_application_sql(connection_case):
    engine = create_engine(
        os.environ["WSO_TEST_APP_DATABASE_URL"], hide_parameters=True
    )
    item = create_connection(connection_case).json()
    try:
        with engine.begin() as db:
            db.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": item["tenant_id"]},
            )
            assert (
                db.execute(text("SELECT count(*) FROM connections")).scalar_one() == 0
            )
            assert (
                db.execute(
                    text("SELECT public.wso_issue_connection_handle(:id,1)"),
                    {"id": item["id"]},
                ).scalar_one()
                is None
            )
    finally:
        engine.dispose()


def test_worker_sql_logs_never_include_capability_or_credential(
    connection_case, caplog
):
    import logging

    from wso_core.secrets import WorkerSecretStore

    worker = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    item = create_connection(connection_case).json()
    handle = issue(connection_case, item)
    with caplog.at_level(logging.INFO, logger="sqlalchemy.engine"):
        worker.with_secret(handle).use(lambda value: len(value))
    assert handle not in caplog.text
    assert "password-canary-84726" not in caplog.text
    assert "fixture-user" not in caplog.text
    assert "SQL parameters hidden" in caplog.text


def test_connection_catalog_has_hardened_owner_rls_and_function_grants(connection_case):
    with connection_case[3].connect() as db:
        tables = db.execute(
            text("""
            SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,r.rolname AS owner
            FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='wso_private' AND c.relname IN
            ('connection_secrets','connection_handles','connection_leases','connection_revocations')
        """)
        ).all()
        assert len(tables) == 4
        for row in tables:
            assert row.owner == "wso_migrator"
            assert row.relrowsecurity and row.relforcerowsecurity
        functions = db.execute(
            text("""
            SELECT p.proname,p.prosecdef,p.proconfig,r.rolname AS owner,
              has_function_privilege('wso_app',p.oid,'EXECUTE') AS app,
              has_function_privilege('wso_connection_worker',p.oid,'EXECUTE') AS worker,
              has_function_privilege('wso_identity_bootstrap',p.oid,'EXECUTE') AS bootstrap,
              has_function_privilege('wso_web_session',p.oid,'EXECUTE') AS session
            FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
            WHERE p.proname IN ('wso_connection_owner','wso_mutate_connection','wso_issue_connection_handle','wso_redeem_connection_handle','wso_use_connection_lease')
        """)
        ).all()
        assert len(functions) == 5
        for row in functions:
            assert row.owner == "wso_migrator" and row.prosecdef
            assert row.proconfig == ["search_path=pg_catalog"]
            assert not row.bootstrap and not row.session
            assert row.worker == (
                row.proname
                in ("wso_redeem_connection_handle", "wso_use_connection_lease")
            )
            assert row.app != row.worker


def test_concurrent_worker_redemption_has_one_winner(connection_case):
    from concurrent.futures import ThreadPoolExecutor

    from wso_core.secrets import SecretRejected, WorkerSecretStore

    worker = WorkerSecretStore(
        os.environ["WSO_TEST_WORKER_DATABASE_URL"], connection_case[5]
    )
    handle = issue(connection_case, create_connection(connection_case).json())

    def consume(_):
        try:
            worker.with_secret(handle)
            return True
        except SecretRejected:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, range(2))) == [False, True]


def test_wrong_worker_role_is_rejected_before_capability_use(connection_case):
    from wso_core.secrets import SecretRejected, WorkerSecretStore

    worker = WorkerSecretStore(
        os.environ["WSO_TEST_APP_DATABASE_URL"], connection_case[5]
    )
    with pytest.raises(SecretRejected):
        worker.with_secret("guessed")


@pytest.mark.parametrize("key", [b"x" * 16, b"x" * 24])
def test_injected_key_provider_cannot_silently_downgrade_aes256(key):
    from wso_core.secrets import SecretCipher, SecretRejected

    class MisconfiguredProvider:
        def encryption_key(self):
            return key

    with pytest.raises(SecretRejected):
        SecretCipher(MisconfiguredProvider()).seal(
            uuid4(), uuid4(), uuid4(), b"credential"
        )
