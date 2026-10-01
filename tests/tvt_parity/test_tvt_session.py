"""W05 synthetic development tests; no upstream/runtime acceptance."""

import base64
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_login_inputs_are_bounded_and_redacted():
    from wso_contracts.tvt.account import AccountLogin

    value = AccountLogin(
        region="test",
        brand="SuperLivePlus",
        mode="email",
        account="person@example.test",
        secret="private-secret",
    )
    assert "private-secret" not in repr(value)
    assert "person@example.test" not in repr(value)
    assert "private-secret" not in value.model_dump_json()
    for patch in (
        {"mode": "other"},
        {"account": "wrong"},
        {"secret": ""},
        {"origin": "https://invalid.test"},
    ):
        with pytest.raises(ValidationError):
            AccountLogin.model_validate(
                {
                    "region": "test",
                    "brand": "SuperLivePlus",
                    "mode": "email",
                    "account": "person@example.test",
                    "secret": "private-secret",
                }
                | patch
            )


def test_profile_is_allowlisted_and_preserves_unknown_account_type():
    from wso_core.tvt.account_projection import project_profile

    result = project_profile(
        json.dumps(
            {
                "data": {
                    "type": 4,
                    "userName": "name",
                    "nickName": "nickname",
                    "email": "person@example.test",
                    "noPassword": True,
                    "image": "/private/avatar.jpg",
                    "userId": "PRIVATE-ID",
                    "installerCoId": "PRIVATE-CO",
                    "token": "PRIVATE-TOKEN",
                }
            }
        ).encode()
    )
    assert result.account_type == 4
    assert result.avatar_available is True
    assert result.avatar_url is None
    assert "PRIVATE" not in result.model_dump_json()
    assert "/private/" not in result.model_dump_json()
    assert project_profile(b'{"data":{"type":99}}').account_type == 99


def test_image_representation_is_decoded_not_forwarded():
    from wso_core.tvt.account_projection import project_image

    # Only a bounded image representation is public; a URL is never fetched.
    jpeg = b"\xff\xd8\xff\xe0" + b"test" + b"\xff\xd9"
    encoded = base64.b64encode(jpeg).decode()
    assert project_image("data:image/jpg;base64," + encoded) == ("image/jpeg", encoded)
    for invalid in (
        "https://private.test/image",
        "data:image/svg+xml;base64,PHN2Zy8+",
        "notbase64",
        "",
    ):
        with pytest.raises(ValueError, match="ACCOUNT_PROTOCOL_INVALID"):
            project_image(invalid)


def test_worker_does_not_call_user_renewal_for_native_token_kinds():
    from wso_contracts.tvt.identity import TokenKind
    from wso_core.tvt.token_vault import require_user_kind

    require_user_kind(TokenKind.USER)
    for kind in (TokenKind.P2P, TokenKind.DEVICE, "USER", None):
        with pytest.raises(ValueError, match="CAPABILITY_UNSUPPORTED"):
            require_user_kind(kind)


def test_anonymous_login_authenticates_before_body_parse():
    from fastapi.testclient import TestClient
    from wso_api.main import create_app

    response = TestClient(create_app()).post(
        f"/api/v1/tvt/identities/login?tenant_id={uuid4()}",
        content="{bad",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert "Cookie" in response.headers["vary"]
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_server_endpoint_profile_is_explicit_bounded_and_rejects_duplicates(tmp_path):
    from wso_api.tvt.session_service import load_account_endpoints
    from wso_core.tvt.account_projection import AccountFailure

    profile = tmp_path / "profile.json"
    data = {
        "region": "test",
        "brand": "SuperLivePlus",
        "origin": "https://upstream.test",
        "language": "en",
        "country": "US",
        "app_version": "1.18.1",
    }
    profile.write_text(json.dumps([data]), encoding="utf-8")
    assert load_account_endpoints(profile)[0].region == "test"
    for invalid in (
        [data, data],
        [data | {"origin": "http://unsafe.test"}],
        [data | {"worker_database_url": "not-allowed"}],
    ):
        profile.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(AccountFailure):
            load_account_endpoints(profile)


def test_saved_invalid_text_cannot_attach_private_bytes_to_error():
    from wso_core.tvt.account_projection import AccountFailure
    from wso_core.tvt.token_vault import private_text

    with pytest.raises(AccountFailure) as failed:
        private_text(b"private-invalid-\xff")
    assert failed.value.__context__ is None
    assert "private-invalid" not in str(failed.value)


def test_nested_worker_budget_preserves_cancel_deadline_and_explicit_detach(
    monkeypatch,
):
    from wso_api.tvt import session_service
    from wso_core.tvt.account_projection import AccountFailure
    from wso_core.tvt.token_vault import remaining_budget, token_budget

    clock = [100.0]
    cancelled = [False]
    monkeypatch.setattr(session_service.time, "monotonic", lambda: clock[0])

    def outer():
        if cancelled[0]:
            raise AccountFailure("ACCOUNT_DEADLINE_EXCEEDED", 504)
        return 75

    @session_service.worker_budget
    def operation(*, deadline_ms):
        assert remaining_budget() == 75
        with token_budget(lambda: 50):
            assert remaining_budget() == 50
        cancelled[0] = True
        with pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"):
            remaining_budget()
        with token_budget(None):
            assert remaining_budget() is None
            with token_budget(lambda: 25):
                assert remaining_budget() == 25
        with pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"):
            remaining_budget()
        cancelled[0] = False
        clock[0] += 0.2
        with pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED"):
            remaining_budget()

    with token_budget(outer):
        operation(deadline_ms=100)
        assert remaining_budget() == 75
    assert remaining_budget() is None
