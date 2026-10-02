"""Startup contracts and HTTP boundary; real persistence runs in the PG diagnostic."""

from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from wso_api.auth import (
    AuthService,
    AuthSettings,
    OIDCVerifier,
    WebSession,
    token_digest,
)
from wso_api.main import create_app


class Sessions:
    def get(self, digest):
        if digest == token_digest("valid"):
            return WebSession(
                "https://issuer.test",
                "actor",
                uuid4(),
                token_digest("csrf"),
                datetime.now(UTC) + timedelta(minutes=1),
            )
        return None


def client():
    settings = AuthSettings(
        issuer="https://issuer.test",
        audience="web",
        jwks_url="https://issuer.test/keys",
        exchange_key="x" * 48,
        public_origin="https://app.test",
        session_database_url="postgresql+psycopg://wso_web_session@localhost/test",
    )
    app = create_app()
    app.state.auth_service = AuthService(settings, OIDCVerifier(settings), Sessions())
    return TestClient(app, base_url="https://app.test")


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"]["code"] == code
    assert body["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    assert "cookie" in response.headers["vary"].lower()


@pytest.mark.parametrize("cookie", [None, "invalid"])
def test_bootstrap_requires_real_web_session(cookie):
    with client() as api:
        if cookie:
            api.cookies.set("__Host-wso-session", cookie)
        assert_error(
            api.get("/api/v1/tvt/bootstrap", params={"tenant_id": str(uuid4())}),
            401,
            "unauthenticated",
        )


def test_absent_profile_fails_closed_for_authenticated_user(monkeypatch):
    monkeypatch.delenv("WSO_TVT_STARTUP_PROFILE", raising=False)
    with client() as api:
        api.cookies.set("__Host-wso-session", "valid")
        assert_error(
            api.get("/api/v1/tvt/bootstrap", params={"tenant_id": str(uuid4())}),
            503,
            "startup_unavailable",
        )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "consent", {"version": "1", "decision": "accepted"}),
        ("put", "preferences", {"locale": "en", "timezone": "UTC"}),
    ],
)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://evil.test", "X-CSRF-Token": "csrf"},
        {"Origin": "https://app.test", "X-CSRF-Token": "wrong"},
    ],
)
def test_mutations_check_origin_and_csrf_before_configuration(
    method, path, body, headers
):
    with client() as api:
        api.cookies.set("__Host-wso-session", "valid")
        assert_error(
            getattr(api, method)(
                "/api/v1/tvt/" + path,
                params={"tenant_id": str(uuid4())},
                json=body,
                headers=headers,
            ),
            403,
            "csrf_rejected",
        )


def test_missing_tenant_and_extra_mutation_fields_are_redacted():
    with client() as api:
        api.cookies.set("__Host-wso-session", "valid")
        assert_error(api.get("/api/v1/tvt/bootstrap"), 422, "validation_error")
        r = api.put(
            "/api/v1/tvt/preferences",
            params={"tenant_id": str(uuid4())},
            json={"locale": "en", "timezone": "UTC", "user_id": "SECRET"},
        )
        assert_error(r, 422, "validation_error")
        assert "SECRET" not in r.text


def test_public_schema_never_exports_private_domain_models():
    schema = create_app().openapi()
    assert "/api/v1/tvt/bootstrap" in schema["paths"]
    assert (
        schema["paths"]["/api/v1/tvt/bootstrap"]["get"]["operationId"] == "tvtBootstrap"
    )
    names = schema["components"]["schemas"]
    for private in (
        "AccountLoginRequest",
        "AccountToken",
        "AuthorizationFacts",
        "AuthorizedScope",
    ):
        assert private not in names
    assert set(names["StartupIdentity"]["properties"]) == {"state", "accounts"}
    assert set(names["StartupAccount"]["properties"]) == {"id", "brand", "region"}


@pytest.mark.parametrize(
    "body",
    [
        {"locale": "en", "timezone": "../UTC"},
        {"locale": "en", "timezone": "Mars/Olympus"},
        {"locale": "not_a_locale", "timezone": "UTC"},
        {"locale": 5, "timezone": "UTC"},
        {"locale": "en", "timezone": "UTC", "actor_id": str(uuid4())},
    ],
)
def test_preferences_reject_invalid_and_identity_input(body):
    model = import_module("wso_contracts.tvt.startup").PreferenceUpdate
    with pytest.raises(ValidationError):
        model.model_validate(body)


def test_consent_rejects_unsupported_and_browser_authored_timestamp():
    model = import_module("wso_contracts.tvt.startup").ConsentUpdate
    for data in (
        {"version": "1", "decision": "pending"},
        {"version": "1", "decision": "accepted", "decided_at": "2026-01-01"},
    ):
        with pytest.raises(ValidationError):
            model.model_validate(data)


def test_profile_unknown_brand_flag_unsafe_policy_and_missing_binding_fail_closed(
    monkeypatch,
):
    import json

    from wso_core.tvt.startup import StartupProfile, load_profile, menu

    from tests.integration.test_tvt_startup import profile_data

    base = profile_data()
    for changed in (
        {"brand": "Unknown"},
        {"tyco_enabled": True},
        {"source_apk_sha256": "0" * 64},
        {"local_routes": ["/tvt/live"]},
        {
            "privacy": {
                "source_reference": "agreement/PrivacyStatement_en.html",
                "url": "javascript:secret",
            }
        },
    ):
        monkeypatch.setenv("WSO_TVT_STARTUP_PROFILE", json.dumps({**base, **changed}))
        assert load_profile() is None
    profile = StartupProfile.model_validate({**base, "local_routes": []})
    assert menu(profile) == []
    assert [item.path for item in menu(StartupProfile.model_validate(base))] == [
        "/tvt/settings"
    ]


def test_account_route_is_explicit_unique_and_has_exact_menu_pair():
    from wso_contracts.tvt.startup import StartupMenuEntry
    from wso_core.tvt.startup import StartupProfile, menu

    from tests.integration.test_tvt_startup import profile_data

    profile = StartupProfile.model_validate(
        {**profile_data(), "local_routes": ["/tvt/settings", "/tvt/account"]}
    )
    assert [entry.model_dump() for entry in menu(profile)] == [
        {"id": "local-settings", "label": "Settings", "path": "/tvt/settings"},
        {"id": "local-account", "label": "Account", "path": "/tvt/account"},
    ]
    with pytest.raises(ValidationError):
        StartupProfile.model_validate(
            {**profile_data(), "local_routes": ["/tvt/account", "/tvt/account"]}
        )
    with pytest.raises(ValidationError):
        StartupMenuEntry(id="local-account", label="Settings", path="/tvt/settings")


def test_unhandled_auth_seam_failure_is_redacted_and_uncacheable():
    class FailingAuth(AuthService):
        def authenticate(self, request, **kwargs):
            raise RuntimeError("PRIVATE-SECRET")

    with client() as api:
        old = api.app.state.auth_service
        api.app.state.auth_service = FailingAuth(
            old.settings, old.verifier, old.sessions
        )
        api.cookies.set("__Host-wso-session", "valid")
        response = api.get("/api/v1/tvt/bootstrap", params={"tenant_id": str(uuid4())})
        assert_error(response, 500, "internal_error")
        assert "PRIVATE-SECRET" not in response.text


def test_openapi_declares_actual_nested_errors_for_every_startup_route():
    schema = create_app().openapi()
    for path, method in (
        ("bootstrap", "get"),
        ("consent", "post"),
        ("preferences", "put"),
    ):
        responses = schema["paths"]["/api/v1/tvt/" + path][method]["responses"]
        for status in ("401", "403", "404", "422", "500", "503"):
            assert responses[status]["content"]["application/json"]["schema"][
                "$ref"
            ].endswith("/StartupErrorEnvelope")


def test_anonymous_invalid_input_is_still_signed_out():
    with client() as api:
        assert_error(api.get("/api/v1/tvt/bootstrap"), 401, "unauthenticated")
        assert_error(
            api.put("/api/v1/tvt/preferences", json={"unexpected": "value"}),
            401,
            "unauthenticated",
        )


@pytest.mark.parametrize("method,path", [("post", "consent"), ("put", "preferences")])
@pytest.mark.parametrize(
    "cookie,status,code",
    [
        (None, 401, "unauthenticated"),
        ("invalid", 401, "unauthenticated"),
        ("valid", 422, "validation_error"),
    ],
)
def test_malformed_json_authenticates_before_body_parsing(
    method, path, cookie, status, code
):
    with client() as api:
        if cookie is not None:
            api.cookies.set("__Host-wso-session", cookie)
        response = getattr(api, method)(
            "/api/v1/tvt/" + path,
            params={"tenant_id": str(uuid4())},
            content="{",
            headers={
                "Content-Type": "application/json",
                "Origin": "https://app.test",
                "X-CSRF-Token": "csrf",
            },
        )
        assert_error(response, status, code)
        assert response.json()["error"]["message"] in {
            "Request failed",
            "Invalid request",
        }
