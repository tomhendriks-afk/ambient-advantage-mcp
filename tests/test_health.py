"""Smoke tests for the FastAPI shell.

Confirms the app boots, /health and /healthz both return 200, and the root
endpoint reports the expected metadata. Tool tests land in step 7 once
source adapters and fixtures exist.
"""

from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app, create_app


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_alias_returns_ok():
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_returns_metadata_with_mcp_disabled_by_default():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "ambient-advantage-mcp"
    assert payload["status"] == "scaffold"
    assert payload["schema_version"] == "v1"
    assert payload["mcp_enabled"] is False
    assert payload["mcp_endpoint"] is None


def test_root_reports_mcp_endpoint_when_enabled():
    enabled_settings = replace(get_settings(), mcp_enabled=True)
    test_app = create_app(settings=enabled_settings)
    client = TestClient(test_app)
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mcp_enabled"] is True
    assert payload["mcp_endpoint"] == "/mcp"
