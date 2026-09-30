from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from wso_api.auth import AuthService, OIDCVerifier
from wso_api.main import create_app

from tests.auth_support import login, signed_token


def test_unconfigured_auth_exchange_fails_closed():
    response = TestClient(create_app()).post(
        "/api/v1/auth/sessions", json={"id_token": "invalid", "nonce": "n"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"


def test_unconfigured_me_fails_closed():
    response = TestClient(create_app()).get("/api/v1/me")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"


def test_partial_database_configuration_fails_closed(monkeypatch):
    for name, value in {
        "WSO_OIDC_ISSUER": "https://issuer.test",
        "WSO_OIDC_CLIENT_ID": "wso-web",
        "WSO_OIDC_JWKS_URL": "https://issuer.test/jwks",
        "WSO_AUTH_EXCHANGE_KEY": "a" * 48,
        "WSO_PUBLIC_ORIGIN": "https://app.test",
        "WSO_SESSION_DATABASE_URL": "postgresql+psycopg://wso_web_session@localhost/wso",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("WSO_IDENTITY_DATABASE_URL", raising=False)
    response = TestClient(create_app()).get("/api/v1/me")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"


@pytest.mark.parametrize(
    "mutation",
    [
        "signature",
        "issuer",
        "audience",
        "expiry",
        "nonce",
        "algorithm",
        "azp",
        "boolean_iat",
    ],
)
def test_invalid_token_rejected_before_identity_pool(settings, signing_key, mutation):
    changes = {}
    key = signing_key
    if mutation == "signature":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif mutation == "issuer":
        changes["iss"] = "https://foreign.test"
    elif mutation == "audience":
        changes["aud"] = "foreign-client"
    elif mutation == "expiry":
        changes["exp"] = int((datetime.now(UTC) - timedelta(seconds=1)).timestamp())
    elif mutation == "nonce":
        changes["nonce"] = "attacker-nonce"
    elif mutation == "azp":
        changes.update(aud=["wso-web", "other"], azp="other")
    elif mutation == "boolean_iat":
        changes["iat"] = True
    token = signed_token(key, **changes)
    if mutation == "algorithm":
        import jwt

        token = jwt.encode({"iss": settings.issuer}, "b" * 32, algorithm="HS256")

    class NoDatabase:
        def begin(self):
            raise AssertionError("invalid token must not open bootstrap pool")

    service = AuthService(
        settings,
        OIDCVerifier(settings, key_resolver=lambda _: signing_key.public_key()),
        NoDatabase(),
        identity_factory=NoDatabase(),
    )
    api = create_app()
    api.state.auth_service = service
    response = TestClient(api).post(
        "/api/v1/auth/sessions",
        headers={"X-WSO-Auth-Key": "a" * 48},
        json={"id_token": token, "nonce": "test-nonce"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("key", [None, "wrong"])
def test_exchange_requires_server_auth_before_bootstrap(settings, signing_key, key):
    class NoDatabase:
        def begin(self):
            raise AssertionError(
                "unauthenticated exchange must not open bootstrap pool"
            )

    service = AuthService(
        settings,
        OIDCVerifier(settings, key_resolver=lambda _: signing_key.public_key()),
        NoDatabase(),
        identity_factory=NoDatabase(),
    )
    api = create_app()
    api.state.auth_service = service
    response = TestClient(api).post(
        "/api/v1/auth/sessions",
        headers={} if key is None else {"X-WSO-Auth-Key": key},
        json={"id_token": signed_token(signing_key), "nonce": "test-nonce"},
    )
    assert response.status_code == 401


def test_me_current_memberships_and_empty_membership(auth_case, signing_key):
    client, ids, _, _ = auth_case
    login(client, signing_key, ids)
    response = client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "cookie" in response.headers["vary"].lower()
    assert response.json()["memberships"] == [
        {"tenant_id": str(ids["a"]), "role": "STAFF"}
    ]
    login(client, signing_key, ids, "empty")
    assert client.get("/api/v1/me").json()["memberships"] == []


@pytest.mark.parametrize(
    "origin,csrf",
    [
        (None, "good"),
        ("https://evil.test", "good"),
        ("https://app.test", "bad"),
        ("https://app.test", ""),
    ],
)
def test_logout_rejects_origin_and_csrf(auth_case, signing_key, origin, csrf):
    client, ids, _, _ = auth_case
    data = login(client, signing_key, ids)
    headers = {"X-CSRF-Token": data["csrf_token"] if csrf == "good" else csrf}
    if origin:
        headers["Origin"] = origin
    assert client.delete("/api/v1/auth/session", headers=headers).status_code == 403
    assert client.get("/api/v1/me").status_code == 200


def test_logout_revokes_session_and_secure_cookies(auth_case, signing_key):
    client, ids, _, _ = auth_case
    data = login(client, signing_key, ids)
    response = client.delete(
        "/api/v1/auth/session",
        headers={"Origin": "https://app.test", "X-CSRF-Token": data["csrf_token"]},
    )
    assert response.status_code == 204
    cookies = response.headers.get_list("set-cookie")
    assert any(
        "HttpOnly" in c and "Secure" in c and "SameSite=lax" in c for c in cookies
    )
    assert any("Secure" in c and "SameSite=strict" in c for c in cookies)
    client.cookies.set(
        "__Host-wso-session", data["session_id"], domain="app.test", path="/"
    )
    denied = client.get("/api/v1/me")
    assert denied.status_code == 401
    assert denied.headers["cache-control"] == "no-store"
    assert "cookie" in denied.headers["vary"].lower()


def test_session_expiry_and_token_storage(auth_case, signing_key):
    client, ids, _service, admin = auth_case
    data = login(client, signing_key, ids)
    from wso_api.auth import token_digest

    with admin.begin() as db:
        row = (
            db.execute(
                text("SELECT * FROM web_sessions WHERE session_digest=:d"),
                {"d": token_digest(data["session_id"])},
            )
            .mappings()
            .one()
        )
        assert data["session_id"] not in str(dict(row))
        assert data["csrf_token"] not in str(dict(row))
        assert datetime.fromisoformat(data["expires_at"]) <= datetime.now(
            UTC
        ) + timedelta(minutes=5)
        # Preserve creation/expiry invariant while simulating passage of time.
        db.execute(
            text(
                "UPDATE web_sessions SET created_at=clock_timestamp()-interval '2 hours', "
                "expires_at=clock_timestamp()-interval '1 hour' WHERE session_digest=:d"
            ),
            {"d": token_digest(data["session_id"])},
        )
    for path in ("/api/v1/me", f"/api/v1/stores?tenant_id={ids['a']}"):
        denied = client.get(path)
        assert denied.status_code == 401
        assert denied.headers["cache-control"] == "no-store"
        assert "cookie" in denied.headers["vary"].lower()


@pytest.mark.parametrize("replay_subject", ["staff", "owner"])
def test_verified_nonce_is_consumed_once(auth_case, signing_key, replay_subject):
    from uuid import uuid4

    client, ids, _, _ = auth_case
    nonce = str(uuid4())
    login(client, signing_key, ids, nonce=nonce)
    response = client.post(
        "/api/v1/auth/sessions",
        headers={"X-WSO-Auth-Key": "a" * 48},
        json={
            "id_token": signed_token(
                signing_key, sub=str(ids[replay_subject]), nonce=nonce
            ),
            "nonce": nonce,
        },
    )
    assert response.status_code == 401


@pytest.mark.parametrize("subjects", [("staff", "staff"), ("staff", "owner")])
def test_concurrent_exchange_consumes_verified_nonce_once(
    auth_case, signing_key, subjects
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4

    client, ids, _, admin = auth_case
    nonce = str(uuid4())
    tokens = [
        signed_token(signing_key, sub=str(ids[subject]), nonce=nonce)
        for subject in subjects
    ]
    barrier = Barrier(2)

    def exchange(token):
        barrier.wait(timeout=5)
        with TestClient(client.app, base_url="https://app.test") as concurrent_client:
            return concurrent_client.post(
                "/api/v1/auth/sessions",
                headers={"X-WSO-Auth-Key": "a" * 48},
                json={"id_token": token, "nonce": nonce},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(exchange, tokens))
    assert sorted(statuses) == [200, 401]
    with admin.connect() as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM web_sessions WHERE user_id = ANY(:users)"),
                {"users": [ids["staff"], ids["owner"]]},
            ).scalar_one()
            == 1
        )


def test_expiry_between_verification_and_session_insert_is_401(
    auth_case, signing_key, monkeypatch
):
    from time import sleep
    from uuid import uuid4

    client, ids, service, admin = auth_case
    create = service.sessions.create
    nonce = str(uuid4())

    def delayed_create(digest, session, exchange_digest):
        sleep(3.1)
        return create(digest, session, exchange_digest)

    monkeypatch.setattr(service.sessions, "create", delayed_create)
    response = client.post(
        "/api/v1/auth/sessions",
        headers={"X-WSO-Auth-Key": "a" * 48},
        json={
            "id_token": signed_token(
                signing_key,
                sub=str(ids["staff"]),
                nonce=nonce,
                exp=int(datetime.now(UTC).timestamp()) + 3,
            ),
            "nonce": nonce,
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["cache-control"] == "no-store"
    with admin.connect() as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM web_sessions WHERE user_id=:u"),
                {"u": ids["staff"]},
            ).scalar_one()
            == 0
        )


def test_session_role_cannot_read_raw_tables_or_impersonate_roles(auth_db):
    _, app, identity, session_engine = auth_db
    for engine, query in (
        (session_engine, "SELECT * FROM web_sessions"),
        (session_engine, "SELECT * FROM users"),
        (session_engine, "SET ROLE wso_app"),
        (app, "SELECT * FROM web_sessions"),
        (identity, "SELECT * FROM web_sessions"),
    ):
        with engine.begin() as db, pytest.raises(DBAPIError):
            db.execute(text(query))


pytest_plugins = ["tests.auth_support"]
