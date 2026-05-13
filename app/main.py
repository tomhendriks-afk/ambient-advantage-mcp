"""
FastAPI entrypoint for the Ambient Advantage MCP server.

Routes
------
GET  /health    Liveness check for Cloud Run health probes.
GET  /healthz   Alias of /health (k8s-style; MCP registry probes prefer this).
GET  /          Friendly root that points humans at the README and reports
                whether the MCP transport is mounted on this instance.

MCP transport
-------------
When MCP_ENABLED=true, the streamable-HTTP transport from the official
mcp SDK is mounted at /mcp. When false (the default), /mcp returns 404
and the service behaves as a plain FastAPI app. This lets us deploy the
shell ahead of tool implementation without exposing a half-finished
surface.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings, get_settings
from .mcp_server import SCHEMA_VERSION, build_mcp_server
from .sources._http import aclose_client

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ambient-advantage-mcp")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the FastAPI app.

    Factored so tests can pass a custom Settings (e.g. mcp_enabled=True)
    without mutating environment variables. The module-level `app` below
    calls this with the default settings for uvicorn / Cloud Run.
    """
    settings = settings or get_settings()

    # Build the MCP sub-app eagerly when enabled so its lifespan can be
    # delegated to FastAPI. The streamable-HTTP transport starts a task
    # group inside its lifespan; without this delegation the sub-app
    # raises RuntimeError on the first request.
    mcp_app = build_mcp_server().streamable_http_app() if settings.mcp_enabled else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            if mcp_app is None:
                yield
            else:
                async with mcp_app.router.lifespan_context(_app):
                    yield
        finally:
            # Close the shared httpx.AsyncClient singleton used by the
            # source adapters so the connection pool releases cleanly
            # on shutdown. No-op if the client was never created.
            await aclose_client()

    app = FastAPI(title="Ambient Advantage MCP Server", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/")
    def root() -> dict:
        return {
            "service": "ambient-advantage-mcp",
            "status": "scaffold",
            "schema_version": SCHEMA_VERSION,
            "mcp_enabled": settings.mcp_enabled,
            "mcp_endpoint": "/mcp" if settings.mcp_enabled else None,
            "docs": "https://github.com/tomhendriks-afk/ambient-advantage-mcp",
        }

    if mcp_app is not None:
        # FastMCP exposes its streamable-HTTP transport as a Starlette ASGI
        # sub-app. We construct it with streamable_http_path="/" so this
        # mount under /mcp produces the public endpoint
        # https://mcp.ambient-advantage.ai/mcp/.
        app.mount("/mcp", mcp_app)
        log.info("MCP transport mounted at /mcp")
    else:
        log.info("MCP transport disabled (MCP_ENABLED=false)")

    return app


app = create_app()
