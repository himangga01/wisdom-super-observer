"""Public asset boundaries exclude provider authority and ambiguous metadata."""

from importlib import import_module
from types import ModuleType

import pytest
from pydantic import ValidationError

TENANT = "11111111-1111-4111-8111-111111111111"
ASSET = "22222222-2222-4222-8222-222222222222"
PARENT = "33333333-3333-4333-8333-333333333333"
STORE = "44444444-4444-4444-8444-444444444444"
SESSION = "55555555-5555-4555-8555-555555555555"
CHECKSUM = {"algorithm": "SHA256", "value": "a" * 64}
PATH = f"/api/v1/assets/{ASSET}/content?tenant_id={TENANT}"


@pytest.fixture
def models() -> ModuleType:
    return import_module("wso_contracts.assets")


def upload_request() -> dict[str, object]:
    return {
        "scope": {"scope_kind": "TENANT", "tenant_id": TENANT},
        "purpose": "IMPORT_PHOTO",
        "content_type": "image/png",
        "byte_size": 1024,
        "checksum": CHECKSUM,
    }


def asset_record() -> dict[str, object]:
    return {
        "id": ASSET,
        "tenant_id": TENANT,
        "store_id": None,
        "purpose": "IMPORT_PHOTO",
        "parent_asset_id": None,
        "state": "READY",
        "checksum": CHECKSUM,
        "byte_size": 1024,
        "content_type": "image/png",
        "created_at": "2026-09-30T12:00:00Z",
        "expires_at": "2026-10-07T21:00:00+09:00",
    }


def test_tenant_photo_needs_no_store_or_camera(models: ModuleType) -> None:
    request = models.BeginUpload.model_validate(upload_request())
    assert request.scope.model_dump(mode="json") == {
        "scope_kind": "TENANT",
        "tenant_id": TENANT,
    }
    assert request.parent_asset_id is None


@pytest.mark.parametrize("size", [True, False, 0, -1, 20_971_521, "1024", 1.5])
def test_declared_size_is_strict_and_bounded(models: ModuleType, size: object) -> None:
    with pytest.raises(ValidationError):
        models.BeginUpload.model_validate({**upload_request(), "byte_size": size})


@pytest.mark.parametrize("size", [1, 20_971_520])
def test_declared_size_boundaries_are_valid(models: ModuleType, size: int) -> None:
    assert (
        models.BeginUpload.model_validate(
            {**upload_request(), "byte_size": size}
        ).byte_size
        == size
    )


@pytest.mark.parametrize(
    "checksum",
    [
        {"algorithm": "SHA1", "value": "a" * 64},
        {"algorithm": "SHA256", "value": "A" * 64},
        {"algorithm": "SHA256", "value": "g" * 64},
        {"algorithm": "SHA256", "value": "a" * 63},
        {"algorithm": "SHA256", "value": "a" * 65},
        {"algorithm": "SHA256", "value": "a" * 64, "url": "https://provider.invalid"},
    ],
)
def test_checksum_is_exact_plaintext_sha256(
    models: ModuleType, checksum: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        models.BeginUpload.model_validate({**upload_request(), "checksum": checksum})


@pytest.mark.parametrize(
    "field,value",
    [
        ("object_key", "private/object"),
        ("url", "https://provider.invalid/object"),
        ("filename", "input.png"),
        ("actor_user_id", TENANT),
        ("retention_days", 365),
        ("state", "READY"),
    ],
)
def test_upload_request_cannot_choose_storage_or_authority(
    models: ModuleType, field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        models.BeginUpload.model_validate({**upload_request(), field: value})


def test_crop_requires_a_parent_but_no_invented_store(models: ModuleType) -> None:
    body = {**upload_request(), "purpose": "IMPORT_CROP"}
    with pytest.raises(ValidationError):
        models.BeginUpload.model_validate(body)
    crop = models.BeginUpload.model_validate({**body, "parent_asset_id": PARENT})
    assert str(crop.parent_asset_id) == PARENT
    assert crop.scope.scope_kind == "TENANT"


def test_photo_cannot_claim_a_derivative_parent(models: ModuleType) -> None:
    with pytest.raises(ValidationError):
        models.BeginUpload.model_validate(
            {**upload_request(), "parent_asset_id": PARENT}
        )


def test_evidence_requires_real_store_scope_shape(models: ModuleType) -> None:
    body = {**upload_request(), "purpose": "EVIDENCE"}
    with pytest.raises(ValidationError):
        models.BeginUpload.model_validate(body)
    evidence = models.BeginUpload.model_validate(
        {
            **body,
            "scope": {"scope_kind": "STORE", "tenant_id": TENANT, "store_id": STORE},
        }
    )
    assert str(evidence.scope.store_id) == STORE


@pytest.mark.parametrize(
    "mime", ["image/gif", "text/html", "image/svg+xml", "image/png;"]
)
def test_only_declared_jpeg_or_png(models: ModuleType, mime: str) -> None:
    with pytest.raises(ValidationError):
        models.BeginUpload.model_validate({**upload_request(), "content_type": mime})


def test_asset_view_preserves_null_scope_and_normalizes_utc(models: ModuleType) -> None:
    view = models.Asset.model_validate(asset_record()).model_dump(mode="json")
    assert view["store_id"] is None
    assert view["expires_at"] == "2026-10-07T12:00:00Z"
    assert set(view) == set(asset_record())


@pytest.mark.parametrize(
    "field", ["object_key", "envelope", "key_id", "lease_token", "provider_url"]
)
def test_asset_view_rejects_private_storage_fields(
    models: ModuleType, field: str
) -> None:
    with pytest.raises(ValidationError):
        models.Asset.model_validate({**asset_record(), field: "private-canary"})


@pytest.mark.parametrize("field", ["created_at", "expires_at"])
def test_asset_view_rejects_naive_timestamps(models: ModuleType, field: str) -> None:
    with pytest.raises(ValidationError):
        models.Asset.model_validate({**asset_record(), field: "2026-10-01T12:00:00"})


@pytest.mark.parametrize("state", ["PROCESSING", "FAILED", "PARTIAL", "ready"])
def test_asset_states_do_not_drift_into_job_states(
    models: ModuleType, state: str
) -> None:
    with pytest.raises(ValidationError):
        models.Asset.model_validate({**asset_record(), "state": state})


def test_upload_and_ticket_expose_only_authenticated_api_paths(
    models: ModuleType,
) -> None:
    upload = models.UploadSession(
        id=SESSION,
        asset_id=ASSET,
        upload_path=PATH,
        expires_at="2026-10-01T12:00:00Z",
        max_bytes=1024,
    )
    token = "b" * 64
    ticket = models.DownloadTicket(
        id=SESSION,
        asset_id=ASSET,
        download_path=PATH,
        token=token,
        expires_at="2026-10-01T12:00:00Z",
    )
    assert upload.upload_path == PATH
    assert ticket.model_dump(mode="json")["token"] == token
    assert token not in repr(ticket)


@pytest.mark.parametrize(
    "path",
    [
        "https://provider.invalid/object",
        "//provider.invalid/object",
        f"{PATH}&token=secret",
        f"{PATH}#fragment",
        PATH.replace(ASSET, PARENT),
        PATH.replace("/content", "/%63ontent"),
    ],
)
def test_access_path_cannot_redirect_or_embed_bearer(
    models: ModuleType, path: str
) -> None:
    with pytest.raises(ValidationError):
        models.DownloadTicket(
            id=SESSION,
            asset_id=ASSET,
            download_path=path,
            token="b" * 64,
            expires_at="2026-10-01T12:00:00Z",
        )
