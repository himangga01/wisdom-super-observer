"""Public asset failure contracts through the normal ASGI exception handler."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from wso_api.assets.bootstrap import configure_assets
from wso_core import assets
from wso_core.asset_crypto import AssetCryptoFailure
from wso_core.asset_images import ImageValidationFailure


def _failure_app(errors: dict[str, Exception]) -> FastAPI:
    app = FastAPI()
    configure_assets(app, runtime=None)

    @app.post("/synthetic/{case}")
    async def fail(case: str) -> None:
        raise assets._failure(errors[case])

    return app


def _assert_public(response: Response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {"code": code, "message": "Asset request failed"},
        "request_id": None,
    }


def test_image_dimensions_return_public_limit() -> None:
    private = ImageValidationFailure("DIMENSIONS")
    with TestClient(_failure_app({"dimensions": private})) as client:
        response = client.post("/synthetic/dimensions")

    _assert_public(response, 413, "ASSET_LIMIT")
    assert private.code == "DIMENSIONS"
    assert "DIMENSIONS" not in response.text


def test_image_pixels_return_public_limit() -> None:
    private = ImageValidationFailure("PIXELS")
    with TestClient(_failure_app({"pixels": private})) as client:
        response = client.post("/synthetic/pixels")

    _assert_public(response, 413, "ASSET_LIMIT")
    assert private.code == "PIXELS"
    assert "PIXELS" not in response.text


@pytest.mark.parametrize(
    ("private_code", "mapped_status", "mapped_code", "public_status", "public_code"),
    [
        ("TYPE", 415, "ASSET_TYPE", 415, "ASSET_TYPE"),
        ("FRAMES", 422, "ASSET_FRAMES", 503, "ASSET_UNAVAILABLE"),
        ("DECODE", 422, "ASSET_DECODE", 503, "ASSET_UNAVAILABLE"),
        ("DEADLINE", 503, "ASSET_DEADLINE", 503, "ASSET_DEADLINE"),
        ("UNAVAILABLE", 503, "ASSET_UNAVAILABLE", 503, "ASSET_UNAVAILABLE"),
    ],
)
def test_other_image_failures_keep_existing_public_contract(
    private_code: str,
    mapped_status: int,
    mapped_code: str,
    public_status: int,
    public_code: str,
) -> None:
    private = ImageValidationFailure(private_code)
    mapped = assets._failure(private)
    assert (mapped.status, mapped.code) == (mapped_status, mapped_code)
    with TestClient(_failure_app({"image": private})) as client:
        response = client.post("/synthetic/image")

    _assert_public(response, public_status, public_code)
    assert private.code == private_code


@pytest.mark.parametrize(
    ("private_code", "status", "public_code"),
    [
        ("LIMIT", 413, "ASSET_LIMIT"),
        ("INTEGRITY", 422, "ASSET_INTEGRITY"),
        ("DEADLINE", 503, "ASSET_DEADLINE"),
        ("UNAVAILABLE", 503, "ASSET_UNAVAILABLE"),
    ],
)
def test_crypto_failures_keep_existing_public_contract(
    private_code: str, status: int, public_code: str
) -> None:
    private = AssetCryptoFailure(private_code)
    mapped = assets._failure(private)
    assert (mapped.status, mapped.code) == (status, public_code)
    with TestClient(_failure_app({"crypto": private})) as client:
        response = client.post("/synthetic/crypto")

    _assert_public(response, status, public_code)
    assert private.code == private_code


def test_unknown_asset_failure_is_sanitized_without_poisoning_next_request() -> None:
    unknown = assets.AssetFailure(413, "SYNTHETIC_PRIVATE_DETAIL")
    known = ImageValidationFailure("TYPE")
    assert assets._failure(unknown) is unknown
    with TestClient(_failure_app({"unknown": unknown, "known": known})) as client:
        response = client.post("/synthetic/unknown")
        _assert_public(response, 503, "ASSET_UNAVAILABLE")
        assert "SYNTHETIC_PRIVATE_DETAIL" not in response.text
        _assert_public(client.post("/synthetic/known"), 415, "ASSET_TYPE")

    assert (unknown.status, unknown.code) == (413, "SYNTHETIC_PRIVATE_DETAIL")
    assert known.code == "TYPE"
