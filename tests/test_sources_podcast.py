"""Offline tests for the podcast source adapter."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.sources import _http, podcast


FIXTURE_FEED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Ambient Advantage</title>
    <link>https://podcast.ambient-advantage.ai</link>
    <description>Test channel.</description>
    <item>
      <title>Ambient Advantage — May 12, 2026</title>
      <description><![CDATA[Tuesday's briefing covers eight stories.]]></description>
      <pubDate>Tue, 12 May 2026 13:00:00 +0000</pubDate>
      <enclosure url="https://storage.googleapis.com/ambient-advantage-podcast/2026-05-12.mp3" length="11000000" type="audio/mpeg" />
      <itunes:duration>912</itunes:duration>
      <guid isPermaLink="false">guid-2026-05-12</guid>
    </item>
    <item>
      <title>Ambient Advantage — May 8, 2026</title>
      <description><![CDATA[Friday's briefing covers twelve stories.]]></description>
      <pubDate>Fri, 08 May 2026 18:57:36 +0000</pubDate>
      <enclosure url="https://storage.googleapis.com/ambient-advantage-podcast/2026-05-08.mp3" length="10500000" type="audio/mpeg" />
      <itunes:duration>15:32</itunes:duration>
      <guid isPermaLink="false">guid-2026-05-08</guid>
    </item>
    <item>
      <title>Ambient Advantage — April 14, 2026</title>
      <description><![CDATA[Older episode, pre-transcript-archival.]]></description>
      <pubDate>Mon, 14 Apr 2026 13:00:00 +0000</pubDate>
      <enclosure url="https://storage.googleapis.com/ambient-advantage-podcast/2026-04-14.mp3" length="9000000" type="audio/mpeg" />
      <itunes:duration>01:02:15</itunes:duration>
      <guid isPermaLink="false">guid-2026-04-14</guid>
    </item>
  </channel>
</rss>
"""

FIXTURE_TRANSCRIPT_2026_05_12 = (
    "# Ambient Advantage — May 12, 2026\n"
    "\n"
    "*Tuesday · May 12, 2026 · [Episode page](https://podcast.ambient-advantage.ai/episodes/2026-05-12.html) · "
    "[Audio](https://storage.googleapis.com/ambient-advantage-podcast/2026-05-12.mp3)*\n"
    "\n"
    "[JON]\n"
    "Hello.\n"
)


def _make_handler(*, missing_transcript_dates: set[str] | None = None):
    missing = missing_transcript_dates or set()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/feed.xml":
            return httpx.Response(
                200,
                text=FIXTURE_FEED_XML,
                headers={"content-type": "application/rss+xml"},
            )
        if path == "/transcripts/2026-05-12.md":
            if "2026-05-12" in missing:
                return httpx.Response(
                    200,
                    text="<!doctype html>...</html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            return httpx.Response(
                200,
                text=FIXTURE_TRANSCRIPT_2026_05_12,
                headers={"content-type": "text/markdown; charset=utf-8"},
            )
        if path == "/transcripts/2026-04-14.md":
            # Pre-archival cohort: Cloudflare SPA fallback.
            return httpx.Response(
                200,
                text="<!doctype html>...</html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        return httpx.Response(404)

    return handler


def _run_with_mock(coro_factory, *, missing_transcript_dates: set[str] | None = None):
    async def runner():
        transport = httpx.MockTransport(
            _make_handler(missing_transcript_dates=missing_transcript_dates)
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://podcast.ambient-advantage.ai",
        ) as mock_client:
            _http._set_override_client(mock_client)
            try:
                return await coro_factory()
            finally:
                _http._set_override_client(None)

    return asyncio.run(runner())


def test_list_episodes_parses_three_items():
    result = _run_with_mock(lambda: podcast.list_episodes())
    assert len(result) == 3


def test_list_episodes_preserves_feed_order():
    result = _run_with_mock(lambda: podcast.list_episodes())
    assert [e.date for e in result] == ["2026-05-12", "2026-05-08", "2026-04-14"]


def test_list_episodes_extracts_full_title_verbatim():
    result = _run_with_mock(lambda: podcast.list_episodes(limit=1))
    assert result[0].title == "Ambient Advantage — May 12, 2026"


def test_list_episodes_unwraps_cdata_description():
    result = _run_with_mock(lambda: podcast.list_episodes(limit=1))
    assert result[0].description == "Tuesday's briefing covers eight stories."


def test_list_episodes_extracts_audio_url_and_guid():
    result = _run_with_mock(lambda: podcast.list_episodes(limit=1))
    assert result[0].audio_url == \
        "https://storage.googleapis.com/ambient-advantage-podcast/2026-05-12.mp3"
    assert result[0].guid == "guid-2026-05-12"


def test_list_episodes_builds_source_url_from_date():
    result = _run_with_mock(lambda: podcast.list_episodes(limit=1))
    assert result[0].source_url == \
        "https://podcast.ambient-advantage.ai/episodes/2026-05-12.html"


@pytest.mark.parametrize("raw,expected", [
    ("912", 912),               # raw seconds
    ("15:32", 932),             # MM:SS  → 15*60 + 32
    ("01:02:15", 3735),         # HH:MM:SS → 3600 + 120 + 15
    ("", 0),                    # missing → 0
    ("garbage", 0),             # unparseable → 0 (don't raise)
])
def test_parse_duration_handles_all_iTunes_forms(raw, expected):
    assert podcast._parse_duration(raw) == expected


def test_list_episodes_picks_up_each_duration_form_from_real_xml():
    result = _run_with_mock(lambda: podcast.list_episodes())
    durations = {e.date: e.duration_seconds for e in result}
    assert durations["2026-05-12"] == 912       # raw seconds
    assert durations["2026-05-08"] == 932       # MM:SS
    assert durations["2026-04-14"] == 3735      # HH:MM:SS


def test_list_episodes_respects_limit():
    result = _run_with_mock(lambda: podcast.list_episodes(limit=2))
    assert [e.date for e in result] == ["2026-05-12", "2026-05-08"]


def test_get_episode_returns_transcript_when_available():
    full = _run_with_mock(lambda: podcast.get_episode("2026-05-12"))
    assert full is not None
    assert full.transcript_format == "markdown"
    assert full.transcript_markdown == FIXTURE_TRANSCRIPT_2026_05_12
    # Title preserved in the body so agents can cite without losing context.
    assert full.transcript_markdown.startswith("# Ambient Advantage — May 12, 2026")


def test_get_episode_metadata_matches_feed_entry():
    full = _run_with_mock(lambda: podcast.get_episode("2026-05-12"))
    assert full is not None
    assert full.title == "Ambient Advantage — May 12, 2026"
    assert full.description == "Tuesday's briefing covers eight stories."
    assert full.duration_seconds == 912
    assert full.guid == "guid-2026-05-12"


def test_get_episode_returns_unavailable_for_pre_archival_episode():
    """Episodes from before 2026-04-22 have no transcript .md."""
    full = _run_with_mock(lambda: podcast.get_episode("2026-04-14"))
    assert full is not None
    assert full.transcript_format == "unavailable"
    assert full.transcript_markdown == ""
    # Metadata still surfaces so the MCP tool can answer "we have the audio
    # but not the transcript" rather than 404.
    assert full.title == "Ambient Advantage — April 14, 2026"
    assert full.audio_url.endswith("2026-04-14.mp3")


def test_get_episode_returns_unavailable_on_cloudflare_html_fallback():
    full = _run_with_mock(
        lambda: podcast.get_episode("2026-05-12"),
        missing_transcript_dates={"2026-05-12"},
    )
    assert full is not None
    assert full.transcript_format == "unavailable"
    assert full.transcript_markdown == ""


def test_get_episode_returns_none_for_unknown_date():
    full = _run_with_mock(lambda: podcast.get_episode("2025-01-01"))
    assert full is None


def test_episodemeta_schema_version_is_v1():
    result = _run_with_mock(lambda: podcast.list_episodes(limit=1))
    assert result[0].schema_version == "v1"


def test_episodefull_schema_version_is_v1():
    full = _run_with_mock(lambda: podcast.get_episode("2026-05-12"))
    assert full is not None
    assert full.schema_version == "v1"
