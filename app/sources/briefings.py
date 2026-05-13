"""Source adapter for briefing.ambient-advantage.ai.

Reads from two public endpoints:
  - /briefings.json       index of every published briefing
  - /<date>.md            markdown twin of a single briefing

The index entries are HTML-escaped at write time so they're safe to splice
into the homepage HTML; this adapter unescapes them so downstream consumers
see clean plain text.

Defensive parsing notes:
- Cloudflare Pages serves the SPA fallback (HTTP 200 + index.html body) for
  any path that doesn't exist on disk. The adapter MUST check the response's
  content-type when fetching .md twins; a text/html response means "missing"
  and is reported as body_format="unavailable" rather than masquerading as
  markdown.
- The pipeline only started emitting .md twins on 2026-05-10 and was
  backfilled to 2026-04-20. Older briefings (2026-04-10 through 2026-04-18)
  have no source for their markdown body; they appear in the index but
  return body_format="unavailable" from get_briefing().
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Literal

from .. import cache
from ..config import get_settings
from ._http import get_client


SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class BriefingMeta:
    """Metadata for a single briefing, no body."""

    date: str               # YYYY-MM-DD
    headline: str           # plain text, HTML entities unescaped
    snippet: str            # plain text, HTML entities unescaped
    read_time: int          # minutes
    source_url: str         # canonical HTML page URL
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class BriefingFull:
    """A briefing with metadata + the full markdown body verbatim.

    body_markdown is the raw .md file content as served, including the H1
    title and *Published <date>* line — agents need the title for citation
    and the date line for grounding, so we don't strip them.

    body_format reports the fidelity of body_markdown:
      "markdown"     — fetched the canonical .md twin verbatim
      "unavailable"  — the briefing exists in the index but no .md is reachable
    """

    date: str
    headline: str
    snippet: str
    read_time: int
    source_url: str
    body_markdown: str
    body_format: Literal["markdown", "unavailable"]
    schema_version: str = SCHEMA_VERSION


def _parse_meta(entry: dict, base: str) -> BriefingMeta:
    """Turn one raw briefings.json entry into a clean BriefingMeta."""
    date = entry["date"]
    return BriefingMeta(
        date=date,
        headline=html.unescape(entry.get("headline", "")),
        snippet=html.unescape(entry.get("snippet", "")),
        read_time=int(entry.get("read_time", 0)),
        source_url=f"{base}/{date}.html",
    )


async def _fetch_index_json() -> list[dict]:
    settings = get_settings()
    base = settings.public_base_briefing
    client = await get_client()
    response = await client.get(f"{base}/briefings.json")
    response.raise_for_status()
    return response.json()


async def list_briefings(*, limit: int | None = None) -> list[BriefingMeta]:
    """Fetch briefings.json and return parsed, unescaped metadata.

    The upstream feed is already sorted newest-first; we preserve that order.
    Backed by the TTL cache (INDEX_TTL_SECONDS) so repeated calls within
    the TTL window don't re-fetch.
    """
    settings = get_settings()
    base = settings.public_base_briefing
    raw = await cache.get_or_fetch(
        key="briefings.list",
        ttl_seconds=cache.INDEX_TTL_SECONDS,
        fetch=_fetch_index_json,
    )

    result = [_parse_meta(entry, base) for entry in raw]
    if limit is not None:
        result = result[:limit]
    return result


async def _fetch_body(date: str) -> tuple[str, str]:
    """Fetch one briefing's .md twin. Returns (body_markdown, body_format).

    body_format is "markdown" iff the response is HTTP 200 with text/markdown
    content-type; anything else (Cloudflare SPA fallback, 404, …) returns
    ("", "unavailable").
    """
    settings = get_settings()
    base = settings.public_base_briefing
    client = await get_client()
    response = await client.get(f"{base}/{date}.md")
    content_type = response.headers.get("content-type", "").lower()
    if response.status_code == 200 and "text/markdown" in content_type:
        return response.text, "markdown"
    return "", "unavailable"


async def get_briefing(date: str) -> BriefingFull | None:
    """Fetch a single briefing's full markdown body.

    Returns None when the date is not present in briefings.json.
    Returns BriefingFull with body_format="unavailable" when the date is
    indexed but no .md twin is reachable (older dates without source data,
    or a transient upstream gap).

    The body fetch is cached for ARTICLE_TTL_SECONDS — bodies don't change
    once published, so we can afford a longer TTL than the index.
    """
    metas = await list_briefings()
    meta = next((m for m in metas if m.date == date), None)
    if meta is None:
        return None

    body_markdown, body_format = await cache.get_or_fetch(
        key=f"briefings.body:{date}",
        ttl_seconds=cache.ARTICLE_TTL_SECONDS,
        fetch=lambda: _fetch_body(date),
    )

    return BriefingFull(
        date=meta.date,
        headline=meta.headline,
        snippet=meta.snippet,
        read_time=meta.read_time,
        source_url=meta.source_url,
        body_markdown=body_markdown,
        body_format=body_format,  # type: ignore[arg-type]
    )
