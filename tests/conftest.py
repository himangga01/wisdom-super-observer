"""Shared deterministic API test fixtures."""

import pytest
from fastapi.testclient import TestClient
from wso_api.main import create_app


@pytest.fixture
def api_client() -> TestClient:
    return TestClient(create_app())
