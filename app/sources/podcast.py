"""Source adapter for podcast.ambient-advantage.ai.

Reads from three public endpoints:
  - /feed.xml                 RSS 2.0 with iTunes namespace (the index)
  - /transcripts/<date>.md    Markdown twin of an episode's transcript
  - /episodes/<date>.html     Per-episode page (used only as source_url; the
                              adapter prefers the markdown transcript twin)

Shape differences from the briefings/takes adapters:
- Index is RSS XML, not JSON. Parsed with stdlib xml.etree.ElementTree;
  no third-party RSS dep needed for a feed shape we own end to end.
- "Body" is the transcript, not the article body. The field is named
  transcript_markdown to make that explicit — descriptions live separately
  in EpisodeMeta.description.
- duration_seconds is parsed from <itunes:duration>, which the publisher
  writes as raw seconds but iTunes also allows HH:MM:SS / MM:SS. Both forms
  are accepted for robustness against future producer changes.
- Pre-2026-04-22 episodes have no transcript .md (transcripts weren't being
  archived to GCS yet). They surface transcript_format="unavailable".

Cloudflare-SPA-fallback defence (200 + text/html for missing paths) is
applied to transcript fetches, same pattern as the other adapters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Literal
from xml.etree import ElementTree as ET

from ..config import get_settings
from ._http import get_client


SCHEMA_VERSION = "v1"

# RSS feed namespaces. ElementTree requires fully-qualified tags like
# "{http://...}duration" when searching elements that live under a namespace.
NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
}


@dataclass(frozen=True)
class EpisodeMeta:
    """Metadata for a single podcast episode, no transcript."""

    date: str                   # YYYY-MM-DD, derived from <pubDate> in UTC
    title: str                  # Full feed title verbatim, e.g.
                                # "Ambient Advantage — May 8, 2026"
    description: str            # <description> show notes (CDATA unwrapped)
    audio_url: str              # <enclosure url=...>
    duration_seconds: int       # <itunes:duration>, parsed from int or HH:MM:SS
    guid: str                   # Stable RSS GUID (UUID)
    source_url: str             # Canonical episode page URL
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class EpisodeFull:
    """An episode with metadata + the full transcript markdown.

    transcript_markdown is the raw .md twin verbatim, including its H1 title
    and meta line linking back to the episode page and audio URL.

    transcript_format:
      "markdown"     — fetched the canonical transcript .md verbatim
      "unavailable"  — episode is in the feed but no transcript is reachable
                       (older episode, or transient Cloudflare SPA fallback)
    """

    date: str
    title: str
    description: str
    audio_url: str
    duration_seconds: int
    guid: str
    source_url: str
    transcript_markdown: str
    transcript_format: Literal["markdown", "unavailable"]
    schema_version: str = SCHEMA_VERSION


_DURATION_RE = re.compile(r"^\s*(\d+)(?::(\d+))?(?::(\d+))?\s*$")


def _parse_duration(raw: str | None) -> int:
    """Parse <itunes:duration> in any of the three formats iTunes allows:
      - integer seconds      "900"
      - "MM:SS" or "M:SS"    "15:00"
      - "HH:MM:SS"           "01:00:00"

    Returns 0 if the value is missing or unparseable rather than raising —
    the MCP tool can still surface the episode with a "duration unknown"
    rendering rather than 500-ing on a malformed feed.
    """
    if not raw:
        return 0
    m = _DURATION_RE.match(raw)
    if not m:
        return 0
    parts = [int(p) if p else 0 for p in m.groups()]
    if parts[2]:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if parts[1]:
        return parts[0] * 60 + parts[1]
    return parts[0]


def _parse_pub_date_to_iso_date(raw: str | None) -> str:
    """Convert an RSS <pubDate> ('Fri, 08 May 2026 18:57:36 +0000') to a
    UTC YYYY-MM-DD date string. The publisher writes pubDate in UTC and the
    transcript filenames use the same UTC date, so we don't reapply any
    timezone shift.
    """
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return ""
    return dt.strftime("%Y-%m-%d")


def _item_text(item: ET.Element, tag: str) -> str:
    """Return the trimmed text of the first matching child, or empty string.
    Supports namespaced tags like "itunes:summary"."""
    if ":" in tag:
        prefix, local = tag.split(":", 1)
        ns_uri = NS.get(prefix)
        if ns_uri is None:
            return ""
        el = item.find(f"{{{ns_uri}}}{local}")
    else:
        el = item.find(tag)
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _parse_item(item: ET.Element, base: str) -> EpisodeMeta:
    """Convert one <item> element to an EpisodeMeta."""
    title = _item_text(item, "title")
    description = _item_text(item, "description")
    pub_date_raw = _item_text(item, "pubDate")
    duration_raw = _item_text(item, "itunes:duration")
    guid = _item_text(item, "guid")

    enclosure = item.find("enclosure")
    audio_url = (enclosure.attrib.get("url", "") if enclosure is not None else "")

    date = _parse_pub_date_to_iso_date(pub_date_raw)
    return EpisodeMeta(
        date=date,
        title=title,
        description=description,
        audio_url=audio_url,
        duration_seconds=_parse_duration(duration_raw),
        guid=guid,
        source_url=f"{base}/episodes/{date}.html" if date else "",
    )


async def list_episodes(*, limit: int | None = None) -> list[EpisodeMeta]:
    """Fetch feed.xml and return parsed metadata.

    The upstream feed is sorted newest-first; we preserve that order.
    """
    settings = get_settings()
    base = settings.public_base_podcast
    client = await get_client()
    response = await client.get(f"{base}/feed.xml")
    response.raise_for_status()

    root = ET.fromstring(response.text)
    items = root.findall(".//channel/item")
    result = [_parse_item(item, base) for item in items]
    if limit is not None:
        result = result[:limit]
    return result


async def get_episode(date: str) -> EpisodeFull | None:
    """Fetch a single episode's metadata + transcript markdown.

    Returns None when the date is not present in the feed.
    Returns EpisodeFull with transcript_format="unavailable" when the
    episode is indexed but no transcript .md is reachable.
    """
    settings = get_settings()
    base = settings.public_base_podcast
    metas = await list_episodes()
    meta = next((m for m in metas if m.date == date), None)
    if meta is None:
        return None

    client = await get_client()
    response = await client.get(f"{base}/transcripts/{date}.md")
    content_type = response.headers.get("content-type", "").lower()
    if response.status_code == 200 and "text/markdown" in content_type:
        return EpisodeFull(
            date=meta.date,
            title=meta.title,
            description=meta.description,
            audio_url=meta.audio_url,
            duration_seconds=meta.duration_seconds,
            guid=meta.guid,
            source_url=meta.source_url,
            transcript_markdown=response.text,
            transcript_format="markdown",
        )

    return EpisodeFull(
        date=meta.date,
        title=meta.title,
        description=meta.description,
        audio_url=meta.audio_url,
        duration_seconds=meta.duration_seconds,
        guid=meta.guid,
        source_url=meta.source_url,
        transcript_markdown="",
        transcript_format="unavailable",
    )
