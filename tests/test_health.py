"""Smoke test for the FastAPI shell.

Confirms the app boots and /health returns 200 with the expected body.
Intentionally trivial — the real tool tests land in step 7 of the build
plan once source adapters and fixtures exist.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_returns_metadata():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "ambient-advantage-mcp"
    assert payload["status"] == "scaffold"
    assert payload["mcp_enabled"] is False
