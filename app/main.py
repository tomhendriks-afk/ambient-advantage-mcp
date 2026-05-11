"""
FastAPI entrypoint for the Ambient Advantage MCP server.

Routes
------
GET  /health   Liveness check for Cloud Run health probes. Always returns
               {"status": "ok"} once the process is accepting connections.

GET  /        Friendly root that points humans at the README and the
               (future) MCP endpoint.

The MCP transport mount at /mcp/* is added in a later build-plan step and
is gated behind the MCP_ENABLED setting so the service can be deployed
before any tools are wired up.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from .config import get_settings

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ambient-advantage-mcp")

app = FastAPI(title="Ambient Advantage MCP Server")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    settings = get_settings()
    return {
        "service": "ambient-advantage-mcp",
        "status": "scaffold",
        "mcp_enabled": settings.mcp_enabled,
        "docs": "https://github.com/tomhendriks-afk/ambient-advantage-mcp",
    }
