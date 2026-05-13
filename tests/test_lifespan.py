"""Tests that the FastAPI lifespan tears down the shared httpx client.

The source adapters share a singleton AsyncClient. If we don't close it
on shutdown, Cloud Run shutdown will leak file descriptors and the
connection pool sits open during the SIGTERM grace period. The lifespan
must call aclose_client() on exit.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.sources import _http


def test_lifespan_closes_http_client_singleton_on_shutdown():
    # Force a fresh client by clearing the override and module state.
    _http._set_override_client(None)
    _http._client = None

    settings = replace(get_settings(), mcp_enabled=False)

    async def _ensure_client_built():
        # Touching get_client() ensures the singleton exists before exit.
        await _http.get_client()

    import asyncio

    with TestClient(create_app(settings=settings)) as client:
        client.get("/health")
        asyncio.run(_ensure_client_built())
        assert _http._client is not None

    # After the TestClient context exits, the lifespan teardown has run.
    assert _http._client is None
