"""Unit tests for the 8 read-only get/list MCP tools.

Each tool is tested directly (imported as a Python function) with the
relevant content site's HTTP layer mocked via httpx.MockTransport.
Tools return Pydantic models so we can validate fields cleanly.

Tests also confirm:
- Tool registration on the FastMCP instance picks up all 8 tools.
- Pagination behaves (limit/offset).
- Unknown slug/date returns None rather than raising.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import cache, mcp_server
from app.sources import _http


@pytest.fixture(autouse=True)
def _isolate_cache():
    cache.clear()
    yield
    cache.clear()


# --------------------------------------------------------------------------- #
# Mock HTTP helpers — one combined handler routing by host                    #
# --------------------------------------------------------------------------- #

BRIEFING_FIXTURE = [
    {"date": "2026-05-12", "headline": "B12", "snippet": "s12", "read_time": 7},
    {"date": "2026-05-11", "headline": "B11", "snippet": "s11", "read_time": 5},
]

TAKE_FIXTURE = [
    {
        "slug": "take-a", "title": "Take A", "tag": "Opinion",
        "date": "2026-05-10", "date_display": "May 10, 2026",
        "read_time": "5 min read", "excerpt": "a", "featured": True,
    },
    {
        "slug": "take-b", "title": "Take B", "tag": "Opinion",
        "date": "2026-05-03", "date_display": "May 3, 2026",
        "read_time": "6 min read", "excerpt": "b", "featured": False,
    },
    {
        "slug": "take-c", "title": "Take C", "tag": "Opinion",
        "date": "2026-04-26", "date_display": "April 26, 2026",
        "read_time": "4 min read", "excerpt": "c", "featured": False,
    },
]

PODCAST_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Test</title>
    <item>
      <title>Episode May 12</title>
      <description>D12</description>
      <pubDate>Tue, 12 May 2026 13:00:00 +0000</pubDate>
      <enclosure url="https://example.com/2026-05-12.mp3" length="1" type="audio/mpeg" />
      <itunes:duration>900</itunes:duration>
      <guid>g-2026-05-12</guid>
    </item>
    <item>
      <title>Episode May 8</title>
      <description>D08</description>
      <pubDate>Fri, 08 May 2026 13:00:00 +0000</pubDate>
      <enclosure url="https://example.com/2026-05-08.mp3" length="1" type="audio/mpeg" />
      <itunes:duration>900</itunes:duration>
      <guid>g-2026-05-08</guid>
    </item>
  </channel>
</rss>
"""

POSTS_FIXTURE = [
    {
        "slug": "post-a", "title": "Post A", "tag": "Architecture",
        "tags": ["cloud-run", "decisions"], "date": "2026-05-10",
        "date_display": "May 10, 2026", "read_time": "8",
        "read_time_display": "8 min read", "excerpt": "a", "pinned": True,
    },
    {
        "slug": "post-b", "title": "Post B", "tag": "Notes",
        "tags": ["firestore", "decisions"], "date": "2026-05-03",
        "date_display": "May 3, 2026", "read_time": "5",
        "read_time_display": "5 min read", "excerpt": "b", "pinned": False,
    },
]


def _combined_handler(request: httpx.Request) -> httpx.Response:
    """Route requests to the right fixture based on host + path."""
    host = request.url.host
    path = request.url.path

    if host == "briefing.ambient-advantage.ai":
        if path == "/briefings.json":
            return httpx.Response(200, json=BRIEFING_FIXTURE,
                                  headers={"content-type": "application/json"})
        if path == "/2026-05-12.md":
            return httpx.Response(200, text="# B12\n\nbody.\n",
                                  headers={"content-type": "text/markdown"})
        if path == "/2026-05-11.md":
            return httpx.Response(200, text="<!doctype html>...",
                                  headers={"content-type": "text/html"})

    if host == "take.ambient-advantage.ai":
        if path == "/articles.json":
            return httpx.Response(200, json=TAKE_FIXTURE,
                                  headers={"content-type": "application/json"})
        if path == "/take-a.md":
            return httpx.Response(200, text="# Take A\n\nbody.\n",
                                  headers={"content-type": "text/markdown"})

    if host == "podcast.ambient-advantage.ai":
        if path == "/feed.xml":
            return httpx.Response(200, text=PODCAST_FEED,
                                  headers={"content-type": "application/rss+xml"})
        if path == "/transcripts/2026-05-12.md":
            return httpx.Response(200, text="# Episode May 12\n\n[JON]\nhi\n",
                                  headers={"content-type": "text/markdown"})

    if host == "build.ambient-advantage.ai":
        if path == "/posts.json":
            return httpx.Response(200, json=POSTS_FIXTURE,
                                  headers={"content-type": "application/json"})
        if path == "/post-a.md":
            return httpx.Response(200, text="# Post A\n\nbody.\n",
                                  headers={"content-type": "text/markdown"})

    return httpx.Response(404)


def _run(coro_factory):
    """Run a coroutine factory with the combined mock transport installed."""

    async def runner():
        transport = httpx.MockTransport(_combined_handler)
        async with httpx.AsyncClient(transport=transport) as mock_client:
            _http._set_override_client(mock_client)
            try:
                return await coro_factory()
            finally:
                _http._set_override_client(None)

    return asyncio.run(runner())


# --------------------------------------------------------------------------- #
# Tool registration                                                           #
# --------------------------------------------------------------------------- #

def test_register_tools_registers_all_eight_get_list_tools():
    server = mcp_server.build_mcp_server()
    # FastMCP's list_tools() is async; pull the tool names off the
    # internal manager instead (synchronous, no event loop needed).
    names = {t.name for t in server._tool_manager.list_tools()}
    expected = {
        "get_latest_briefing",
        "get_briefing_by_date",
        "get_chiels_take",
        "list_chiels_take",
        "get_podcast_episode",
        "list_podcast_episodes",
        "get_build_log_post",
        "list_build_log_components",
    }
    assert expected.issubset(names)


def test_registered_tools_carry_their_docstrings_as_descriptions():
    """Tool descriptions are what the LLM sees when deciding to call.
    Empty docstrings would render the tools useless.
    """
    server = mcp_server.build_mcp_server()
    for tool in server._tool_manager.list_tools():
        if tool.name.startswith("get_") or tool.name.startswith("list_"):
            assert tool.description, f"{tool.name} has no description"
            # Pin the source_url citation guidance for tools that return
            # citable content.
            if tool.name in {"get_latest_briefing", "get_briefing_by_date"}:
                assert "source_url" in tool.description


# --------------------------------------------------------------------------- #
# Briefings tools                                                             #
# --------------------------------------------------------------------------- #

def test_get_latest_briefing_returns_full_model_with_body():
    result = _run(mcp_server.get_latest_briefing)
    assert result is not None
    assert result.date == "2026-05-12"
    assert result.body_format == "markdown"
    assert result.body_markdown.startswith("# B12")
    assert result.schema_version == "v1"


def test_get_briefing_by_date_returns_full_model_for_known_date():
    result = _run(lambda: mcp_server.get_briefing_by_date("2026-05-12"))
    assert result is not None
    assert result.body_format == "markdown"
    assert result.headline == "B12"


def test_get_briefing_by_date_surfaces_unavailable_when_md_missing():
    """Cloudflare SPA-fallback case: .md exists in index but returns HTML."""
    result = _run(lambda: mcp_server.get_briefing_by_date("2026-05-11"))
    assert result is not None
    assert result.body_format == "unavailable"
    assert result.body_markdown == ""
    # Metadata still surfaces.
    assert result.headline == "B11"


def test_get_briefing_by_date_returns_none_for_unknown_date():
    result = _run(lambda: mcp_server.get_briefing_by_date("2024-01-01"))
    assert result is None


# --------------------------------------------------------------------------- #
# Takes tools                                                                 #
# --------------------------------------------------------------------------- #

def test_get_chiels_take_returns_full_model_for_known_slug():
    result = _run(lambda: mcp_server.get_chiels_take("take-a"))
    assert result is not None
    assert result.title == "Take A"
    assert result.body_format == "markdown"
    assert result.featured is True


def test_get_chiels_take_returns_none_for_unknown_slug():
    result = _run(lambda: mcp_server.get_chiels_take("does-not-exist"))
    assert result is None


def test_list_chiels_take_returns_metas_newest_first():
    result = _run(mcp_server.list_chiels_take)
    assert [m.slug for m in result] == ["take-a", "take-b", "take-c"]


def test_list_chiels_take_respects_limit_and_offset():
    result = _run(lambda: mcp_server.list_chiels_take(limit=1, offset=1))
    assert [m.slug for m in result] == ["take-b"]


def test_list_chiels_take_limit_zero_returns_empty_list():
    result = _run(lambda: mcp_server.list_chiels_take(limit=0))
    assert result == []


# --------------------------------------------------------------------------- #
# Podcast tools                                                               #
# --------------------------------------------------------------------------- #

def test_get_podcast_episode_returns_full_model_for_known_date():
    result = _run(lambda: mcp_server.get_podcast_episode("2026-05-12"))
    assert result is not None
    assert result.transcript_format == "markdown"
    assert "[JON]" in result.transcript_markdown


def test_get_podcast_episode_returns_unavailable_when_transcript_missing():
    result = _run(lambda: mcp_server.get_podcast_episode("2026-05-08"))
    assert result is not None
    assert result.transcript_format == "unavailable"
    assert result.transcript_markdown == ""
    assert result.audio_url.endswith("2026-05-08.mp3")


def test_get_podcast_episode_returns_none_for_unknown_date():
    result = _run(lambda: mcp_server.get_podcast_episode("2024-01-01"))
    assert result is None


def test_list_podcast_episodes_returns_metas_newest_first():
    result = _run(mcp_server.list_podcast_episodes)
    assert [m.date for m in result] == ["2026-05-12", "2026-05-08"]
    assert all(m.schema_version == "v1" for m in result)


def test_list_podcast_episodes_respects_limit():
    result = _run(lambda: mcp_server.list_podcast_episodes(limit=1))
    assert len(result) == 1
    assert result[0].date == "2026-05-12"


# --------------------------------------------------------------------------- #
# Build Log tools                                                             #
# --------------------------------------------------------------------------- #

def test_get_build_log_post_returns_full_model_for_known_slug():
    result = _run(lambda: mcp_server.get_build_log_post("post-a"))
    assert result is not None
    assert result.title == "Post A"
    assert result.tags == ["cloud-run", "decisions"]
    assert result.pinned is True


def test_get_build_log_post_returns_none_for_unknown_slug():
    result = _run(lambda: mcp_server.get_build_log_post("nope"))
    assert result is None


def test_list_build_log_components_aggregates_tags():
    result = _run(mcp_server.list_build_log_components)
    counts = {c.slug: c.post_count for c in result}
    assert counts == {"cloud-run": 1, "decisions": 2, "firestore": 1}


def test_list_build_log_components_sorts_by_count_desc_then_slug_asc():
    result = _run(mcp_server.list_build_log_components)
    assert [c.slug for c in result] == ["decisions", "cloud-run", "firestore"]
