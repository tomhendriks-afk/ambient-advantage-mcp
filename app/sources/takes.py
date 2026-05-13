"""Source adapter for take.ambient-advantage.ai (Chiel's Take).

Reads from two public endpoints:
  - /articles.json    index of every published take
  - /<slug>.md        markdown twin of a single take

The take site is the most coherent of the four: per-article .md twins
have existed since day one, so unlike the briefing/build/podcast adapters
this one rarely hits the body_format="unavailable" path. The fallback is
kept for symmetry and to defend against the Cloudflare Pages SPA-fallback
(HTTP 200 + text/html) if a slug ever becomes unreachable mid-deploy.

Shape differences vs the briefings feed:
- Primary key is `slug` (string), not `date` (multiple takes per day are
  permitted in theory; the column doesn't tie to a date).
- `read_time` is a free-form display string (e.g. "4 min read") rather
  than an integer minute count. Passed through verbatim — step 5
  (Pydantic) will decide whether to normalise.
- `featured` is a boolean indicating the hero card on the homepage.
- Headlines and excerpts are NOT HTML-escaped at write time, so no
  html.unescape() pass is needed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .. import cache
from ..config import get_settings
from ._http import get_client


SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class TakeMeta:
    """Metadata for a single take, no body."""

    slug: str
    title: str
    tag: str                # "Opinion" or similar editorial tag
    date: str               # YYYY-MM-DD
    date_display: str       # "April 26, 2026"
    read_time: str          # "4 min read" or "4" — passed through verbatim
    excerpt: str
    featured: bool
    source_url: str         # canonical HTML page URL
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class TakeFull:
    """A take with metadata + the full markdown body verbatim.

    body_markdown is the raw .md file content, including the H1 title and
    byline line, so agents can cite without losing the title context.

    body_format:
      "markdown"     — fetched the canonical .md twin verbatim
      "unavailable"  — the slug exists in the index but no .md is reachable
    """

    slug: str
    title: str
    tag: str
    date: str
    date_display: str
    read_time: str
    excerpt: str
    featured: bool
    source_url: str
    body_markdown: str
    body_format: Literal["markdown", "unavailable"]
    schema_version: str = SCHEMA_VERSION


def _parse_meta(entry: dict, base: str) -> TakeMeta:
    """Turn one raw articles.json entry into a clean TakeMeta."""
    slug = entry["slug"]
    return TakeMeta(
        slug=slug,
        title=entry.get("title", ""),
        tag=entry.get("tag", ""),
        date=entry.get("date", ""),
        date_display=entry.get("date_display", ""),
        read_time=str(entry.get("read_time", "")),
        excerpt=entry.get("excerpt", ""),
        featured=bool(entry.get("featured", False)),
        source_url=f"{base}/{slug}.html",
    )


async def _fetch_index_json() -> list[dict]:
    settings = get_settings()
    base = settings.public_base_take
    client = await get_client()
    response = await client.get(f"{base}/articles.json")
    response.raise_for_status()
    return response.json()


async def list_takes(*, limit: int | None = None) -> list[TakeMeta]:
    """Fetch articles.json and return parsed metadata.

    The upstream feed is sorted newest-first; we preserve that order.
    Backed by the TTL cache (INDEX_TTL_SECONDS).
    """
    settings = get_settings()
    base = settings.public_base_take
    raw = await cache.get_or_fetch(
        key="takes.list",
        ttl_seconds=cache.INDEX_TTL_SECONDS,
        fetch=_fetch_index_json,
    )

    result = [_parse_meta(entry, base) for entry in raw]
    if limit is not None:
        result = result[:limit]
    return result


async def _fetch_body(slug: str) -> tuple[str, str]:
    settings = get_settings()
    base = settings.public_base_take
    client = await get_client()
    response = await client.get(f"{base}/{slug}.md")
    content_type = response.headers.get("content-type", "").lower()
    if response.status_code == 200 and "text/markdown" in content_type:
        return response.text, "markdown"
    return "", "unavailable"


async def get_take(slug: str) -> TakeFull | None:
    """Fetch a single take's full markdown body.

    Returns None when the slug is not present in articles.json.
    Returns TakeFull with body_format="unavailable" when the slug is
    indexed but no .md twin is reachable.

    The body fetch is cached for ARTICLE_TTL_SECONDS.
    """
    metas = await list_takes()
    meta = next((m for m in metas if m.slug == slug), None)
    if meta is None:
        return None

    body_markdown, body_format = await cache.get_or_fetch(
        key=f"takes.body:{slug}",
        ttl_seconds=cache.ARTICLE_TTL_SECONDS,
        fetch=lambda: _fetch_body(slug),
    )

    return TakeFull(
        slug=meta.slug,
        title=meta.title,
        tag=meta.tag,
        date=meta.date,
        date_display=meta.date_display,
        read_time=meta.read_time,
        excerpt=meta.excerpt,
        featured=meta.featured,
        source_url=meta.source_url,
        body_markdown=body_markdown,
        body_format=body_format,  # type: ignore[arg-type]
    )
