"""Only run against Root's explicitly owned PostgreSQL auth fixture."""

import json

from sqlalchemy import text
from wso_core.connections import ConnectionService
from wso_core.secrets import WorkerSecretStore
from wso_core.tvt.local_credentials import parse_local_device_credentials

from tests.auth_support import login
from tests.integration.test_connection_secrets import (
    create_connection,
    issue,
    owner_scope,
)

pytest_plugins = ["tests.auth_support", "tests.integration.test_connection_secrets"]


def local(case, **changes):
    return create_connection(
        case,
        kind="TVT_DEVICE",
        device={
            "serial": "inert123",
            "country": "KR",
            "qr_payload": "<sn>INERT123</sn><user>fixture-user</user>",
        },
        **changes,
    )


def test_encrypted_canonical_device_store_association_and_public_redaction(
    connection_case, caplog
):
    import os

    client, ids, _, admin, headers, provider = connection_case
    response = local(connection_case, store_ids=[str(ids["assigned"])])
    assert response.status_code == 201
    item = response.json()
    assert item["status"] == "NOT_VERIFIED" and item["last_success"] is None
    assert item["store_ids"] == [str(ids["assigned"])]
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
    worker = WorkerSecretStore(os.environ["WSO_TEST_WORKER_DATABASE_URL"], provider)
    parsed = worker.with_secret(issue(connection_case, item)).use(
        parse_local_device_credentials
    )
    assert parsed.serial == "INERT123" and parsed.country == "KR"
    assert (
        parsed.username == "fixture-user" and parsed.password == "password-canary-84726"
    )
    path = f"/api/v1/connections/{item['id']}?tenant_id={ids['a']}"
    assert client.get(path).json() == item
    with admin.connect() as db:
        encrypted = db.execute(
            text(
                "SELECT ciphertext FROM wso_private.connection_secrets WHERE connection_id=:id"
            ),
            {"id": item["id"]},
        ).scalar_one()
        audit = str(
            db.execute(
                text("SELECT * FROM audit_events WHERE entity_id=:id"),
                {"id": item["id"]},
            ).all()
        )
    for private in (
        "INERT123",
        "inert123",
        "fixture-user",
        "password-canary-84726",
        "<sn>",
    ):
        assert private.encode() not in bytes(encrypted)
        assert private not in response.text + audit + caplog.text
    replacement = client.patch(
        path,
        headers=headers,
        json={
            "expected_generation": 1,
            "username": "next-user",
            "password": "next-password",
            "device": {"serial": "next456", "country": "US"},
        },
    )
    assert replacement.status_code == 200 and replacement.json()["generation"] == 2
    fresh = worker.with_secret(issue(connection_case, replacement.json())).use(
        parse_local_device_credentials
    )
    assert fresh.serial == "NEXT456" and fresh.username == "next-user"
    assert (
        client.patch(
            path, headers=headers, json={"expected_generation": 1, "alias": "stale"}
        ).status_code
        == 409
    )


def test_protected_kind_validation_and_legacy_metadata_only(connection_case):
    client, ids, _, _, headers, _ = connection_case
    with owner_scope(connection_case) as scope:
        legacy = ConnectionService(scope.session, connection_case[5]).mutate(
            "create",
            {
                "kind": "TVT_DEVICE",
                "alias": "Legacy",
                "site": "Human location",
                "store_ids": [],
            },
            credentials=json.dumps(
                {"username": "legacy", "password": "legacy"}
            ).encode(),
        )
    path = f"/api/v1/connections/{legacy.id}?tenant_id={ids['a']}"
    assert (
        client.patch(
            path, headers=headers, json={"expected_generation": 1, "alias": "Renamed"}
        ).status_code
        == 200
    )
    for body in [
        {"expected_generation": 2, "username": "u", "password": "p"},
        {"expected_generation": 2, "device": {"serial": "inert123"}},
        {
            "expected_generation": 2,
            "username": "u",
            "password": "p",
            "kind": "TVT_ACCOUNT",
        },
        {
            "expected_generation": 2,
            "username": "u",
            "password": "p",
            "device": {"serial": "inert123", "sourceType": "TVT_ACCOUNT"},
        },
        {
            "expected_generation": 2,
            "username": "u",
            "password": "p",
            "device": {
                "serial": "inert123",
                "qr_payload": "<sn>OTHER</sn><user>u</user>",
            },
        },
    ]:
        rejected = client.patch(path, headers=headers, json=body)
        assert rejected.status_code == 422
        assert "inert123" not in rejected.text and "OTHER" not in rejected.text
    account = create_connection(connection_case).json()
    path = f"/api/v1/connections/{account['id']}?tenant_id={ids['a']}"
    assert (
        client.patch(
            path,
            headers=headers,
            json={
                "expected_generation": 1,
                "username": "u",
                "password": "p",
                "device": {"serial": "inert123"},
            },
        ).status_code
        == 422
    )


def test_owner_csrf_tenant_store_and_device_validation(connection_case, signing_key):
    client, ids, _, _, headers, _ = connection_case
    for store in ("foreign", "inactive"):
        assert local(connection_case, store_ids=[str(ids[store])]).status_code == 404
    item = local(connection_case).json()
    path = f"/api/v1/connections/{item['id']}?tenant_id={ids['a']}"
    body = {
        "expected_generation": 1,
        "username": "u",
        "password": "p",
        "device": {"serial": "inert123"},
    }
    for invalid in (
        {},
        {"Origin": "https://evil.test", "X-CSRF-Token": headers["X-CSRF-Token"]},
        {"Origin": "https://app.test", "X-CSRF-Token": "wrong"},
    ):
        assert client.patch(path, headers=invalid, json=body).status_code == 403
    assert (
        client.patch(
            path.replace(str(ids["a"]), str(ids["b"])), headers=headers, json=body
        ).status_code
        == 404
    )
    auth = login(client, signing_key, ids, "staff")
    assert (
        client.patch(
            path,
            headers={"Origin": "https://app.test", "X-CSRF-Token": auth["csrf_token"]},
            json=body,
        ).status_code
        == 403
    )
