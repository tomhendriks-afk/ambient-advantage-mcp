"""Unit tests for the 4 search/topics MCP tools."""

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
# Fixtures: small but discriminative corpora                                  #
# --------------------------------------------------------------------------- #

BRIEFING_FIXTURE = [
    {
        "date": "2026-05-12",
        "headline": "Anthropic launches Claude 4.7 with multi-modal upgrades",
        "snippet": "Anthropic's latest update extends agentic capabilities.",
        "read_time": 7,
    },
    {
        "date": "2026-05-08",
        "headline": "EU AI Act enforcement begins for high-risk systems",
        "snippet": "Implementation deadlines reach the first major milestone.",
        "read_time": 6,
    },
    {
        "date": "2026-05-01",
        "headline": "OpenAI demos Sora updates",
        "snippet": "New video features for Sora; no Anthropic news today.",
        "read_time": 5,
    },
    {
        "date": "2026-04-20",
        "headline": "Quiet news week",
        "snippet": "A summary of mid-tier announcements.",
        "read_time": 4,
    },
]

TAKE_FIXTURE = [
    {
        "slug": "the-prompting-premium", "title": "The Prompting Premium",
        "tag": "Opinion", "date": "2026-05-10", "date_display": "May 10, 2026",
        "read_time": "5 min read",
        "excerpt": "Anthropic's Claude shines when prompts are precise.",
        "featured": True,
    },
    {
        "slug": "shipping-beats-prototyping", "title": "Shipping beats prototyping",
        "tag": "Opinion", "date": "2026-04-26", "date_display": "April 26, 2026",
        "read_time": "4 min read",
        "excerpt": "Cat Wu on the move from demo to daily use.",
        "featured": False,
    },
    {
        "slug": "irrelevant-musing", "title": "An unrelated musing",
        "tag": "Opinion", "date": "2026-04-10", "date_display": "April 10, 2026",
        "read_time": "3 min read",
        "excerpt": "About something else entirely.",
        "featured": False,
    },
]

POSTS_FIXTURE = [
    {
        "slug": "cloud-run-scaling", "title": "Cloud Run scales to zero",
        "tag": "Architecture", "tags": ["cloud-run", "architecture"],
        "date": "2026-05-10", "date_display": "May 10, 2026",
        "read_time": "8", "read_time_display": "8 min read",
        "excerpt": "Why scale-to-zero is the whole pitch.",
        "pinned": True,
    },
    {
        "slug": "firestore-decisions", "title": "Firestore: two collections, no migrations",
        "tag": "Architecture", "tags": ["firestore", "decisions"],
        "date": "2026-05-03", "date_display": "May 3, 2026",
        "read_time": "5", "read_time_display": "5 min read",
        "excerpt": "How Firestore covers state without ceremony.",
        "pinned": False,
    },
    {
        "slug": "elevenlabs-tuning", "title": "Tuning ElevenLabs voices",
        "tag": "Notes", "tags": ["elevenlabs"],
        "date": "2026-04-26", "date_display": "April 26, 2026",
        "read_time": "4", "read_time_display": "4 min read",
        "excerpt": "Notes on voice prosody.",
        "pinned": False,
    },
]


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    path = request.url.path
    if host == "briefing.ambient-advantage.ai" and path == "/briefings.json":
        return httpx.Response(200, json=BRIEFING_FIXTURE,
                              headers={"content-type": "application/json"})
    if host == "take.ambient-advantage.ai" and path == "/articles.json":
        return httpx.Response(200, json=TAKE_FIXTURE,
                              headers={"content-type": "application/json"})
    if host == "build.ambient-advantage.ai" and path == "/posts.json":
        return httpx.Response(200, json=POSTS_FIXTURE,
                              headers={"content-type": "application/json"})
    return httpx.Response(404)


def _run(coro_factory):
    async def runner():
        transport = httpx.MockTransport(_handler)
        async with httpx.AsyncClient(transport=transport) as mock_client:
            _http._set_override_client(mock_client)
            try:
                return await coro_factory()
            finally:
                _http._set_override_client(None)

    return asyncio.run(runner())


# --------------------------------------------------------------------------- #
# search_briefings                                                            #
# --------------------------------------------------------------------------- #

def test_search_briefings_finds_matching_headlines():
    """'Anthropic' appears in two briefings (2026-05-12 headline + snippet,
    2026-05-01 snippet)."""
    result = _run(lambda: mcp_server.search_briefings("Anthropic"))
    dates = [h.date for h in result]
    assert "2026-05-12" in dates
    assert "2026-05-01" in dates


def test_search_briefings_sorts_by_score_desc_then_date_desc():
    """2026-05-12 has 'Anthropic' twice (headline + snippet); 2026-05-01 has
    it once. Higher score should rank first.
    """
    result = _run(lambda: mcp_server.search_briefings("Anthropic"))
    assert result[0].date == "2026-05-12"
    assert result[0].score >= result[1].score


def test_search_briefings_excludes_unmatched():
    result = _run(lambda: mcp_server.search_briefings("Anthropic"))
    assert "2026-04-20" not in [h.date for h in result]  # no match


def test_search_briefings_and_semantics_requires_all_terms():
    """'EU AI' must match both terms; only the May 8 briefing has both."""
    result = _run(lambda: mcp_server.search_briefings("EU AI"))
    assert len(result) == 1
    assert result[0].date == "2026-05-08"


def test_search_briefings_returns_empty_on_blank_query():
    result = _run(lambda: mcp_server.search_briefings(""))
    assert result == []


def test_search_briefings_respects_date_from_and_date_to():
    result = _run(lambda: mcp_server.search_briefings(
        "Anthropic", date_from="2026-05-05", date_to="2026-05-31",
    ))
    # 2026-05-01 has 'Anthropic' but is outside the date_from window.
    assert [h.date for h in result] == ["2026-05-12"]


def test_search_briefings_respects_limit():
    result = _run(lambda: mcp_server.search_briefings("Anthropic", limit=1))
    assert len(result) == 1


def test_search_briefings_hit_includes_score_and_matched_terms():
    result = _run(lambda: mcp_server.search_briefings("Anthropic"))
    top = result[0]
    assert top.score > 0
    assert "anthropic" in top.matched_terms
    assert top.schema_version == "v1"


# --------------------------------------------------------------------------- #
# search_chiels_take                                                          #
# --------------------------------------------------------------------------- #

def test_search_chiels_take_finds_matching_title_or_excerpt():
    result = _run(lambda: mcp_server.search_chiels_take("Anthropic"))
    slugs = [h.slug for h in result]
    assert "the-prompting-premium" in slugs


def test_search_chiels_take_excludes_unrelated_takes():
    result = _run(lambda: mcp_server.search_chiels_take("Anthropic"))
    assert "irrelevant-musing" not in [h.slug for h in result]


def test_search_chiels_take_returns_empty_on_blank_query():
    result = _run(lambda: mcp_server.search_chiels_take("   "))
    assert result == []


def test_search_chiels_take_respects_limit():
    result = _run(lambda: mcp_server.search_chiels_take("Anthropic", limit=0))
    assert result == []


# --------------------------------------------------------------------------- #
# search_build_log                                                            #
# --------------------------------------------------------------------------- #

def test_search_build_log_finds_matching_posts():
    """'Firestore' is in one post's title."""
    result = _run(lambda: mcp_server.search_build_log("Firestore"))
    assert len(result) == 1
    assert result[0].slug == "firestore-decisions"


def test_search_build_log_tag_filter_narrows_scope():
    """Tag filter applies BEFORE the query match: tag=cloud-run + query 'cloud'
    only matches the cloud-run post.
    """
    result = _run(lambda: mcp_server.search_build_log(
        "cloud", tag="cloud-run",
    ))
    assert [h.slug for h in result] == ["cloud-run-scaling"]


def test_search_build_log_tag_filter_zero_matches_returns_empty():
    """tag=elevenlabs + query 'Firestore': no post in elevenlabs tag has
    Firestore.
    """
    result = _run(lambda: mcp_server.search_build_log(
        "Firestore", tag="elevenlabs",
    ))
    assert result == []


def test_search_build_log_returns_empty_on_blank_query():
    result = _run(lambda: mcp_server.search_build_log(""))
    assert result == []


def test_search_build_log_hit_preserves_tags_as_list():
    """Adapter PostMeta carries tags as tuple; Pydantic surfaces a list."""
    result = _run(lambda: mcp_server.search_build_log("Firestore"))
    assert result[0].tags == ["firestore", "decisions"]


# --------------------------------------------------------------------------- #
# list_briefing_topics (stub)                                                 #
# --------------------------------------------------------------------------- #

def test_list_briefing_topics_returns_empty_list_in_phase_1():
    """Phase 1 stub. Returning empty rather than fake topics is the point."""
    result = _run(lambda: mcp_server.list_briefing_topics())
    assert result == []


def test_list_briefing_topics_accepts_date_range_args_without_error():
    """The schema is locked for forward compatibility; the args are
    accepted but ignored in Phase 1.
    """
    result = _run(lambda: mcp_server.list_briefing_topics(
        date_from="2026-05-01", date_to="2026-05-12",
    ))
    assert result == []


# --------------------------------------------------------------------------- #
# Registration                                                                #
# --------------------------------------------------------------------------- #

def test_register_tools_now_includes_all_twelve_phase_1_tools():
    server = mcp_server.build_mcp_server()
    names = {t.name for t in server._tool_manager.list_tools()}
    expected = {
        # 8 from step 6b
        "get_latest_briefing", "get_briefing_by_date",
        "get_chiels_take", "list_chiels_take",
        "get_podcast_episode", "list_podcast_episodes",
        "get_build_log_post", "list_build_log_components",
        # 4 from step 6c
        "search_briefings", "list_briefing_topics",
        "search_chiels_take", "search_build_log",
    }
    assert expected == names, f"unexpected: {names ^ expected}"


def test_search_tools_carry_their_docstrings_as_descriptions():
    server = mcp_server.build_mcp_server()
    by_name = {t.name: t for t in server._tool_manager.list_tools()}
    for name in ("search_briefings", "search_chiels_take", "search_build_log"):
        assert by_name[name].description, f"{name} has no description"


def test_list_briefing_topics_docstring_calls_out_phase_1_stub():
    """The tool description visible to the LLM must say so explicitly,
    otherwise agents will keep calling it expecting topics.
    """
    server = mcp_server.build_mcp_server()
    by_name = {t.name: t for t in server._tool_manager.list_tools()}
    desc = (by_name["list_briefing_topics"].description or "").lower()
    assert "phase 1" in desc or "stub" in desc or "empty list" in desc
