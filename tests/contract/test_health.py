import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from wso_api.main import create_app


def test_liveness_has_no_dependency_secrets():
    response = TestClient(create_app(readiness_checks={"database": lambda: False})).get(
        "/health/live"
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_unavailable_database_without_leaking_details():
    secret = "postgresql://operator:password@private-db/internal"

    def unavailable_database() -> bool:
        raise ConnectionError(secret)

    response = TestClient(
        create_app(readiness_checks={"database": unavailable_database})
    ).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "dependencies": {"database": "unavailable"},
    }
    assert secret not in response.text


def test_readiness_reports_healthy_injected_checks():
    response = TestClient(create_app(readiness_checks={"database": lambda: True})).get(
        "/health/ready"
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"database": "ready"},
    }


def test_request_id_is_returned_on_handled_errors(api_client: TestClient):
    response = api_client.get("/missing")
    assert response.status_code == 404
    assert response.headers["x-request-id"]
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not found"},
        "request_id": response.headers["x-request-id"],
    }


def test_readiness_requires_configured_checks():
    response = TestClient(create_app()).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "dependencies": {}}


def test_unhandled_error_hides_exception_and_keeps_request_id():
    secret = "operator-private-token"
    app = create_app()
    router = APIRouter()

    @router.get("/crash")
    def crash() -> None:
        raise RuntimeError(secret)

    app.include_router(router)
    response = TestClient(app, raise_server_exceptions=False).get("/crash")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"},
        "request_id": response.headers["x-request-id"],
    }
    assert secret not in response.text


def test_wire_models_reject_negative_price_and_extra_fields():
    from pydantic import ValidationError
    from wso_contracts.models import Money, TenantScope

    with pytest.raises(ValidationError):
        Money(amount_minor=-1)
    with pytest.raises(ValidationError):
        TenantScope(tenant_id="00000000-0000-0000-0000-000000000001", password="secret")


def test_product_candidate_preserves_barcode_leading_zeroes():
    from uuid import UUID

    from wso_contracts.models import ProductCandidate

    candidate = ProductCandidate(
        id=UUID(int=1),
        tenant_id=UUID(int=2),
        revision=1,
        barcode="0012345",
        name="Fixture",
        purchase_price=None,
        sale_price=None,
        source_kind="TEXT",
        source_ref="fixture",
        confidence=1,
        errors=[],
    )
    assert candidate.model_dump(mode="json")["barcode"] == "0012345"


def test_contract_export_is_deterministic_and_includes_health_routes(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "export_contracts.py"
    command = [sys.executable, str(script), "--out-dir", str(tmp_path)]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    before = {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}
    assert "openapi.json" in before
    assert "ProductCandidate.json" in before
    assert "/health/ready" in json.loads(before["openapi.json"])["paths"]
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    after = {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}
    assert before == after
    assert first.stdout == second.stdout
