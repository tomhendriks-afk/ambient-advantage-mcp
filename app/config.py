"""Runtime configuration for the MCP server.

Mirrors the cloud-run-podcast pattern: a single Settings dataclass populated
from env vars, accessed via get_settings(). No Secret Manager reads in
Phase 1 — the service has no secret dependencies.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    # Feature flag for the MCP transport mount. Defaults to off so the
    # service can be deployed before tools are wired up without exposing
    # a half-finished surface.
    mcp_enabled: bool

    # Public base URLs for the four content sites. Adapters in app/sources/
    # use these to compose feed and per-article URLs. TTLs are NOT a
    # setting; they're locked constants in app.cache (INDEX_TTL_SECONDS,
    # ARTICLE_TTL_SECONDS) so a config drift can't silently weaken caching.
    public_base_briefing: str
    public_base_take: str
    public_base_podcast: str
    public_base_build: str


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        mcp_enabled=_env_bool("MCP_ENABLED", False),
        public_base_briefing=os.environ.get(
            "PUBLIC_BASE_BRIEFING", "https://briefing.ambient-advantage.ai"
        ).rstrip("/"),
        public_base_take=os.environ.get(
            "PUBLIC_BASE_TAKE", "https://take.ambient-advantage.ai"
        ).rstrip("/"),
        public_base_podcast=os.environ.get(
            "PUBLIC_BASE_PODCAST", "https://podcast.ambient-advantage.ai"
        ).rstrip("/"),
        public_base_build=os.environ.get(
            "PUBLIC_BASE_BUILD", "https://build.ambient-advantage.ai"
        ).rstrip("/"),
    )
