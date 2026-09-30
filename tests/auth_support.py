"""Real signed test issuer and opt-in PostgreSQL integration fixtures."""

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from wso_api.auth import AuthService, AuthSettings, OIDCVerifier, PostgresSessionStore
from wso_api.main import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings():
    return AuthSettings(
        issuer="https://issuer.test",
        audience="wso-web",
        jwks_url="https://issuer.test/jwks",
        exchange_key="a" * 48,
        public_origin="https://app.test",
        session_database_url="postgresql+psycopg://wso_web_session@localhost/wso",
    )


def signed_token(signing_key, **changes):
    now = datetime.now(UTC)
    claims = {
        "iss": "https://issuer.test",
        "sub": "staff",
        "aud": "wso-web",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": "test-nonce",
    }
    claims.update(changes)
    return jwt.encode(
        claims, signing_key, algorithm="RS256", headers={"kid": "fixture"}
    )


@pytest.fixture(scope="module")
def auth_db():
    urls = [
        os.getenv("WSO_TEST_ADMIN_DATABASE_URL"),
        os.getenv("WSO_TEST_APP_DATABASE_URL"),
        os.getenv("WSO_TEST_IDENTITY_DATABASE_URL"),
        os.getenv("WSO_TEST_SESSION_DATABASE_URL"),
    ]
    if not all(urls):
        pytest.skip("requires four explicit PostgreSQL role URLs")
    config = Config(str(ROOT / "infra/alembic.ini"))
    config.set_main_option("sqlalchemy.url", urls[0])
    command.upgrade(config, "head")
    engines = [create_engine(url) for url in urls]
    try:
        yield engines
    finally:
        for engine in engines:
            engine.dispose()


@pytest.fixture
def auth_case(auth_db, settings, signing_key):
    admin, app, identity, session_engine = auth_db
    ids = {
        name: uuid4()
        for name in (
            "a",
            "b",
            "staff",
            "owner",
            "empty",
            "foreign_user",
            "assigned",
            "hidden",
            "foreign",
            "inactive",
        )
    }
    with admin.begin() as db:
        for name in ("a", "b"):
            db.execute(
                text("INSERT INTO tenants(id,name) VALUES (:id,:name)"),
                {"id": ids[name], "name": name},
            )
        for subject in ("staff", "owner", "empty", "foreign_user"):
            # Unique subject prevents cross-test principal collisions.
            db.execute(
                text(
                    "INSERT INTO users(id,oidc_issuer,oidc_subject) VALUES "
                    "(:id,'https://issuer.test',:subject)"
                ),
                {"id": ids[subject], "subject": str(ids[subject])},
            )
        for tenant, user, role in (
            ("a", "staff", "STAFF"),
            ("a", "owner", "OWNER"),
            ("b", "foreign_user", "STAFF"),
        ):
            db.execute(
                text(
                    "INSERT INTO memberships(tenant_id,user_id,role) VALUES(:t,:u,:r)"
                ),
                {"t": ids[tenant], "u": ids[user], "r": role},
            )
        for name, tenant, active in (
            ("assigned", "a", True),
            ("hidden", "a", True),
            ("inactive", "a", False),
            ("foreign", "b", True),
        ):
            db.execute(
                text(
                    "INSERT INTO stores(id,tenant_id,name,timezone,active) "
                    "VALUES(:id,:t,:name,'Asia/Seoul',:active)"
                ),
                {"id": ids[name], "t": ids[tenant], "name": name, "active": active},
            )
        db.execute(
            text(
                "INSERT INTO store_memberships(tenant_id,store_id,user_id) VALUES(:t,:s,:u)"
            ),
            {"t": ids["a"], "s": ids["assigned"], "u": ids["staff"]},
        )
    service = AuthService(
        settings,
        OIDCVerifier(settings, key_resolver=lambda _: signing_key.public_key()),
        PostgresSessionStore(
            str(session_engine.url), session_factory=sessionmaker(session_engine)
        ),
        identity_factory=sessionmaker(identity),
        tenant_factory=sessionmaker(app),
    )
    api = create_app()
    api.state.auth_service = service
    client = TestClient(api, base_url="https://app.test")
    try:
        yield client, ids, service, admin
    finally:
        client.close()
        with admin.begin() as db:
            db.execute(
                text("DELETE FROM web_sessions WHERE user_id = ANY(:ids)"),
                {"ids": [ids[k] for k in ("staff", "owner", "empty", "foreign_user")]},
            )
            db.execute(
                text("DELETE FROM store_memberships WHERE tenant_id = ANY(:ids)"),
                {"ids": [ids["a"], ids["b"]]},
            )
            db.execute(
                text("DELETE FROM stores WHERE tenant_id = ANY(:ids)"),
                {"ids": [ids["a"], ids["b"]]},
            )
            db.execute(
                text("DELETE FROM memberships WHERE tenant_id = ANY(:ids)"),
                {"ids": [ids["a"], ids["b"]]},
            )
            db.execute(
                text("DELETE FROM users WHERE id = ANY(:ids)"),
                {"ids": [ids[k] for k in ("staff", "owner", "empty", "foreign_user")]},
            )
            db.execute(
                text("DELETE FROM tenants WHERE id = ANY(:ids)"),
                {"ids": [ids["a"], ids["b"]]},
            )


def login(client, signing_key, ids, subject="staff", **claims):
    nonce = claims.pop("nonce", secrets.token_urlsafe(32))
    response = client.post(
        "/api/v1/auth/sessions",
        headers={"X-WSO-Auth-Key": "a" * 48},
        json={
            "id_token": signed_token(
                signing_key, sub=str(ids[subject]), nonce=nonce, **claims
            ),
            "nonce": nonce,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    client.cookies.set(
        "__Host-wso-session", data["session_id"], domain="app.test", path="/"
    )
    return data
