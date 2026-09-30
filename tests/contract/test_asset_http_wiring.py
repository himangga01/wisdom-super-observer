"""The normal application publishes asset routes and protects all error caching."""

import pytest
from fastapi.testclient import TestClient
from wso_api.auth import auth_service
from wso_api.main import create_app

ASSET_ID = "10000000-0000-4000-8000-000000000001"
TENANT_ID = "20000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/assets"),
        ("GET", f"/api/v1/assets/{ASSET_ID}?tenant_id={TENANT_ID}"),
        ("DELETE", f"/api/v1/assets/{ASSET_ID}?tenant_id={TENANT_ID}"),
    ],
)
def test_disabled_asset_subsystem_fails_closed_with_private_error_headers(
    monkeypatch, method, path
):
    monkeypatch.delenv("WSO_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("WSO_ASSET_INSTALLATION_ID", raising=False)
    app = create_app()
    app.dependency_overrides[auth_service] = lambda: None
    with TestClient(app) as client:
        response = client.request(
            method,
            path,
            json={
                "scope": {"scope_kind": "TENANT", "tenant_id": TENANT_ID},
                "purpose": "IMPORT_PHOTO",
                "byte_size": 1,
                "content_type": "image/png",
                "checksum": {"algorithm": "SHA256", "value": "a" * 64},
            },
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ASSET_CONFIGURATION_UNAVAILABLE"
    assert response.headers["cache-control"] == "no-store"
    assert "cookie" in response.headers["vary"].lower()
    assert response.headers["x-request-id"] == response.json()["request_id"]
    assert "https://" not in response.text


def test_normal_openapi_includes_all_private_asset_operations():
    paths = create_app().openapi()["paths"]
    assert set(paths["/api/v1/assets"]) == {"post"}
    assert set(paths["/api/v1/assets/{asset_id}"]) == {"get", "delete"}
    assert set(paths["/api/v1/assets/{asset_id}/content"]) == {"get", "put"}
    assert set(paths["/api/v1/assets/{asset_id}/complete"]) == {"post"}
    assert set(paths["/api/v1/assets/{asset_id}/download-tickets"]) == {"post"}


@pytest.mark.parametrize(
    "method,header,schema",
    [
        ("put", "X-Upload-Session", {"type": "string", "format": "uuid"}),
        (
            "get",
            "X-Asset-Ticket",
            {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
                "minLength": 64,
                "maxLength": 64,
            },
        ),
    ],
)
def test_asset_byte_operation_documents_required_header(method, header, schema):
    operation = create_app().openapi()["paths"]["/api/v1/assets/{asset_id}/content"][
        method
    ]
    matches = [
        item
        for item in operation["parameters"]
        if item["in"] == "header" and item["name"] == header
    ]
    assert len(matches) == 1
    assert matches[0]["required"] is True
    assert matches[0]["schema"] == schema


def test_asset_upload_documents_required_raw_jpeg_and_png_body():
    operation = create_app().openapi()["paths"]["/api/v1/assets/{asset_id}/content"][
        "put"
    ]
    assert operation["requestBody"]["required"] is True
    content = operation["requestBody"]["content"]
    assert set(content) == {"image/jpeg", "image/png"}
    assert all(
        item["schema"] == {"type": "string", "format": "binary"}
        for item in content.values()
    )
    assert "content" not in operation["responses"]["204"]


def test_asset_download_documents_binary_images_without_json_success():
    operation = create_app().openapi()["paths"]["/api/v1/assets/{asset_id}/content"][
        "get"
    ]
    content = operation["responses"]["200"]["content"]
    assert set(content) == {"image/jpeg", "image/png"}
    assert all(
        item["schema"] == {"type": "string", "format": "binary"}
        for item in content.values()
    )
