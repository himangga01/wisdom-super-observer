import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from wso_api.main import create_app

from tests.auth_support import login


def test_unconfigured_store_list_fails_closed():
    response = TestClient(create_app()).get(
        "/api/v1/stores?tenant_id=00000000-0000-0000-0000-000000000001"
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"


@pytest.mark.parametrize(
    "subject,expected", [("staff", ["assigned"]), ("owner", ["assigned", "hidden"])]
)
def test_store_list_is_scoped(auth_case, signing_key, subject, expected):
    client, ids, _, _ = auth_case
    login(client, signing_key, ids, subject)
    response = client.get(f"/api/v1/stores?tenant_id={ids['a']}")
    assert response.status_code == 200, response.text
    assert [store["id"] for store in response.json()["items"]] == [
        str(ids[name]) for name in expected
    ]
    assert response.json()["selected_tenant_id"] == str(ids["a"])
    assert response.headers["cache-control"] == "no-store"
    assert "cookie" in response.headers["vary"].lower()


def test_foreign_tenant_and_unassigned_store_are_sanitized_404(auth_case, signing_key):
    client, ids, _, _ = auth_case
    login(client, signing_key, ids)
    for path in (
        f"/api/v1/stores?tenant_id={ids['b']}",
        f"/api/v1/stores/{ids['hidden']}?tenant_id={ids['a']}",
        f"/api/v1/stores/{ids['foreign']}?tenant_id={ids['a']}",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"] == {"code": "not_found", "message": "Not found"}
        assert response.headers.get("cache-control") == "no-store"
        assert "cookie" in response.headers.get("vary", "").lower()
        assert response.headers["x-request-id"] == response.json()["request_id"]
    response = client.get(f"/api/v1/stores/{ids['assigned']}?tenant_id={ids['a']}")
    assert response.status_code == 200


def test_role_claims_cannot_grant_owner_access(auth_case, signing_key):
    client, ids, _, _ = auth_case
    login(client, signing_key, ids, roles=["OWNER", "SYSTEM_OPERATOR"])
    response = client.get(f"/api/v1/stores?tenant_id={ids['a']}")
    assert [store["id"] for store in response.json()["items"]] == [str(ids["assigned"])]


def test_revoked_membership_removes_access_without_relogin(auth_case, signing_key):
    client, ids, _, admin = auth_case
    login(client, signing_key, ids)
    with admin.begin() as db:
        db.execute(
            text("DELETE FROM store_memberships WHERE user_id=:u"), {"u": ids["staff"]}
        )
        db.execute(
            text("DELETE FROM memberships WHERE user_id=:u"), {"u": ids["staff"]}
        )
    assert client.get("/api/v1/me").json()["memberships"] == []
    assert client.get(f"/api/v1/stores?tenant_id={ids['a']}").status_code == 404


pytest_plugins = ["tests.auth_support"]
