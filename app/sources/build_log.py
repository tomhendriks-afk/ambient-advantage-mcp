"""Source adapter for build.ambient-advantage.ai (Build Log).

Reads from two public endpoints:
  - /posts.json       index of every published post
  - /<slug>.md        markdown twin of a single post

Shape differences from the takes adapter:
- Each post carries a single editorial `tag` AND a multi-tag `tags` array
  for component/theme cross-references. The adapter surfaces both.
- `read_time` (bare number string, e.g. "12") and `read_time_display`
  ("12 min read") are two separate fields in the feed. The adapter
  preserves both verbatim; step 5 (Pydantic) decides which the public
  contract exposes.
- `pinned` boolean is the analogue of takes' `featured` (drives the
  homepage hero card).

list_components() returns a structured aggregation of every tag that
appears across posts.json. Unlike the build-site homepage which renders
a curated COMPONENTS catalogue (with editorial blurbs/groups), this
function returns only the structural data — slug, post_count, post_slugs —
because the editorial labels live in build-site/publish.py and are not
exposed via any public URL today.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from ..config import get_settings
from ._http import get_client


SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class PostMeta:
    """Metadata for a single Build Log post, no body."""

    slug: str
    title: str
    tag: str                        # primary editorial tag, e.g. "Architecture"
    tags: tuple[str, ...]           # full tag list (tuple for frozen-dataclass)
    date: str                       # YYYY-MM-DD
    date_display: str               # "May 1, 2026"
    read_time: str                  # bare number form, e.g. "12"
    read_time_display: str          # "12 min read"
    excerpt: str
    pinned: bool
    source_url: str
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class PostFull:
    """A Build Log post with metadata + the full markdown body verbatim."""

    slug: str
    title: str
    tag: str
    tags: tuple[str, ...]
    date: str
    date_display: str
    read_time: str
    read_time_display: str
    excerpt: str
    pinned: bool
    source_url: str
    body_markdown: str
    body_format: Literal["markdown", "unavailable"]
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class ComponentSummary:
    """A structural summary of one tag aggregated across posts.json.

    Editorial metadata (name, blurb, group) is intentionally omitted: it
    lives in build-site/publish.py's COMPONENTS constant and is not
    exposed by any public URL today. Tools that need it can call
    list_posts() and join client-side.
    """

    slug: str                       # tag slug, e.g. "cloud-run"
    post_count: int
    post_slugs: tuple[str, ...]     # slugs of posts carrying this tag, newest-first
    schema_version: str = SCHEMA_VERSION


def _parse_meta(entry: dict, base: str) -> PostMeta:
    """Turn one raw posts.json entry into a clean PostMeta."""
    slug = entry["slug"]
    tags_raw = entry.get("tags", [])
    return PostMeta(
        slug=slug,
        title=entry.get("title", ""),
        tag=entry.get("tag", ""),
        tags=tuple(tags_raw) if isinstance(tags_raw, list) else tuple(),
        date=entry.get("date", ""),
        date_display=entry.get("date_display", ""),
        read_time=str(entry.get("read_time", "")),
        read_time_display=entry.get("read_time_display", ""),
        excerpt=entry.get("excerpt", ""),
        pinned=bool(entry.get("pinned", False)),
        source_url=f"{base}/{slug}.html",
    )


async def list_posts(*, limit: int | None = None) -> list[PostMeta]:
    """Fetch posts.json and return parsed metadata.

    The upstream feed is sorted newest-first; we preserve that order.
    """
    settings = get_settings()
    base = settings.public_base_build
    client = await get_client()
    response = await client.get(f"{base}/posts.json")
    response.raise_for_status()
    raw = response.json()

    result = [_parse_meta(entry, base) for entry in raw]
    if limit is not None:
        result = result[:limit]
    return result


async def get_post(slug: str) -> PostFull | None:
    """Fetch a single post's full markdown body.

    Returns None when the slug is not present in posts.json.
    Returns PostFull with body_format="unavailable" when the slug is
    indexed but no .md twin is reachable (transient Cloudflare SPA
    fallback, or a post whose .md was never produced).
    """
    settings = get_settings()
    base = settings.public_base_build
    metas = await list_posts()
    meta = next((m for m in metas if m.slug == slug), None)
    if meta is None:
        return None

    client = await get_client()
    response = await client.get(f"{base}/{slug}.md")
    content_type = response.headers.get("content-type", "").lower()
    if response.status_code == 200 and "text/markdown" in content_type:
        return PostFull(
            slug=meta.slug,
            title=meta.title,
            tag=meta.tag,
            tags=meta.tags,
            date=meta.date,
            date_display=meta.date_display,
            read_time=meta.read_time,
            read_time_display=meta.read_time_display,
            excerpt=meta.excerpt,
            pinned=meta.pinned,
            source_url=meta.source_url,
            body_markdown=response.text,
            body_format="markdown",
        )

    return PostFull(
        slug=meta.slug,
        title=meta.title,
        tag=meta.tag,
        tags=meta.tags,
        date=meta.date,
        date_display=meta.date_display,
        read_time=meta.read_time,
        read_time_display=meta.read_time_display,
        excerpt=meta.excerpt,
        pinned=meta.pinned,
        source_url=meta.source_url,
        body_markdown="",
        body_format="unavailable",
    )


async def list_components() -> list[ComponentSummary]:
    """Return a structural summary of every tag across posts.json.

    "Components" here is the union of every value in every post's `tags`
    array — i.e. both the curated component tags (cloud-run, firestore,
    etc.) and theme tags (architecture, decisions, etc.) treated uniformly.
    Sorted by post_count desc, then slug asc, for stable ordering even when
    counts tie.

    Each ComponentSummary.post_slugs preserves the upstream newest-first
    order of posts.json, so consumers can render "most recent post about
    X" without re-fetching.
    """
    posts = await list_posts()
    by_tag: dict[str, list[str]] = defaultdict(list)
    for p in posts:
        for tag in p.tags:
            by_tag[tag].append(p.slug)

    summaries = [
        ComponentSummary(
            slug=tag,
            post_count=len(slugs),
            post_slugs=tuple(slugs),
        )
        for tag, slugs in by_tag.items()
    ]
    summaries.sort(key=lambda c: (-c.post_count, c.slug))
    return summaries
