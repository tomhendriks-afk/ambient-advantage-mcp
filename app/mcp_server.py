"""MCP server construction.

Build-plan step 2 lands the empty FastMCP shell so the transport mount can
be exercised end-to-end before any tools exist. Tools are registered in
step 6 inside register_tools().

The shell is intentionally minimal: a named FastMCP instance with no tools.
Hitting the mounted endpoint returns a valid (but empty) MCP server that
will respond to initialize / list_tools handshakes.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


# Bumped only when tool input/output schemas change in a breaking way.
# Treated as a public contract once Phase 1 ships.
SCHEMA_VERSION = "v1"

SERVER_NAME = "ambient-advantage-mcp"
SERVER_INSTRUCTIONS = (
    "Read-only access to the Ambient Advantage content archive: daily AI "
    "briefings, Chiel's Take opinion pieces, podcast episodes, and Build "
    "Log posts. Every response carries source_url and published_at so "
    "answers can be cited correctly."
)


def build_mcp_server() -> FastMCP:
    """Construct the FastMCP instance and register all tools.

    Tools are registered here so the test suite and the FastAPI app share a
    single source of truth for what the server exposes. Step 2 leaves the
    registry empty; later build-plan steps fill it in.

    streamable_http_path is set to "/" so that mounting the sub-app under
    "/mcp" on the parent FastAPI app produces a public endpoint of
    "/mcp/". Without this override, the SDK's default "/mcp" path inside
    the sub-app would compose with the mount prefix to "/mcp/mcp", which
    is not the URL the README and DNS plan document.
    """
    server = FastMCP(
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        streamable_http_path="/",
    )
    register_tools(server)
    return server


def register_tools(server: FastMCP) -> None:
    """Register every public tool on the given FastMCP instance.

    Empty for now — step 6 of the build plan wires in the 12 Phase 1 tools.
    Kept as a separate function so tests can construct a clean server and
    call this explicitly when needed.
    """
    # Intentionally empty in build-plan step 2.
    return None
