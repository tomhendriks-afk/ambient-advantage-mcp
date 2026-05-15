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
        response = client.get("/mcp/")
        # Must be mounted (not 404)...
        assert response.status_code != 404
        # ...and must NOT be 421 "Invalid Host header". The SDK's
        # DNS-rebinding protection (on by default, empty allowed_hosts)
        # would 421 every non-localhost Host. TestClient sends
        # Host: testserver, so a 421 here is exactly the production
        # regression we hit behind Firebase/Cloud Run. This assertion is
        # the guard the old "!= 404" check was missing.
        assert response.status_code != 421, (
            "MCP endpoint rejected the Host header — DNS-rebinding "
            "protection is still active"
        )


def test_mcp_initialize_round_trip_succeeds_behind_proxy_host():
    """A real JSON-RPC initialize must succeed even when the Host header
    is not localhost — i.e. with DNS-rebinding protection disabled.
    This is the end-to-end proof that the production 421 is fixed.
    """
    enabled_settings = replace(get_settings(), mcp_enabled=True)
    with TestClient(create_app(settings=enabled_settings)) as client:
        resp = client.post(
            "/mcp/",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                # Simulate the proxy-forwarded Host that broke prod.
                "Host": "mcp.ambient-advantage.ai",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            },
        )
        # Not rejected at the security layer.
        assert resp.status_code != 421
        assert resp.status_code != 404
        body = resp.text
        assert "Invalid Host header" not in body
        # A successful initialize returns the server info / capabilities.
        assert "ambient-advantage-mcp" in body or "serverInfo" in body or "result" in body


def test_build_mcp_server_returns_named_instance():
    server = build_mcp_server()
    assert server.name == "ambient-advantage-mcp"


def test_build_mcp_server_disables_dns_rebinding_protection():
    """Pin the security posture so a future SDK-default change or an
    accidental revert is caught by CI rather than in production.
    """
    server = build_mcp_server()
    ts = server.settings.transport_security
    assert ts is not None
    assert ts.enable_dns_rebinding_protection is False
