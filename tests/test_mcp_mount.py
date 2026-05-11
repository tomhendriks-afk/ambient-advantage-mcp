"""Tests for the MCP transport mount feature flag.

The streamable-HTTP transport is mounted at /mcp only when
settings.mcp_enabled is true. These tests confirm both states without
mutating environment variables.
"""

from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.mcp_server import build_mcp_server


def test_mcp_endpoint_returns_404_when_disabled():
    disabled_settings = replace(get_settings(), mcp_enabled=False)
    client = TestClient(create_app(settings=disabled_settings))
    response = client.get("/mcp/")
    assert response.status_code == 404


def test_mcp_endpoint_is_mounted_when_enabled():
    enabled_settings = replace(get_settings(), mcp_enabled=True)
    # Using TestClient as a context manager triggers the FastAPI lifespan,
    # which in turn starts the MCP sub-app's task group. Without this the
    # streamable-HTTP transport raises RuntimeError on the first request.
    with TestClient(create_app(settings=enabled_settings)) as client:
        # FastMCP's streamable_http_app rejects GET on the protocol endpoint
        # (it requires a POST with the JSON-RPC initialize call). A non-404
        # status proves the sub-app is mounted and reachable; the exact
        # method-not-allowed semantics are owned by the SDK.
        response = client.get("/mcp/")
        assert response.status_code != 404


def test_build_mcp_server_returns_named_instance():
    server = build_mcp_server()
    assert server.name == "ambient-advantage-mcp"
