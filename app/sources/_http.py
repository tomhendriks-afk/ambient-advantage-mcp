"""Shared httpx.AsyncClient used by every source adapter.

Lazy module-level singleton so the connection pool is reused across tool
invocations rather than torn down between requests. Cloud Run uses a single
uvicorn worker (see Dockerfile CMD), so there's no cross-worker sharing
concern and no race to guard against — the first call wins.

Tests override the client via _set_override_client(); see
tests/test_sources_briefings.py for an example using httpx.MockTransport.
"""

from __future__ import annotations

import httpx


_DEFAULT_TIMEOUT = 10.0  # seconds
_DEFAULT_HEADERS = {
    "User-Agent": "ambient-advantage-mcp/1.0 (+https://mcp.ambient-advantage.ai)",
    "Accept": "application/json, text/markdown, text/plain, application/rss+xml",
}

_client: httpx.AsyncClient | None = None
_override_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    """Return the shared async client, creating it on first use."""
    if _override_client is not None:
        return _override_client
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers=_DEFAULT_HEADERS,
        )
    return _client


async def aclose_client() -> None:
    """Close the singleton client. Wired into the FastAPI lifespan in
    build-plan step 6 once the MCP mount goes live.
    """
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _set_override_client(client: httpx.AsyncClient | None) -> None:
    """Test hook: swap the singleton with a MockTransport-backed client."""
    global _override_client
    _override_client = client
