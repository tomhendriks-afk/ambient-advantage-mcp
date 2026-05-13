"""Offline tests for the takes source adapter.

Uses httpx.MockTransport to intercept outbound requests so tests never hit
the network. Same override pattern as test_sources_briefings.py.
"""

from __future__ import annotations

import asyncio

import httpx

from app.sources import _http, takes


FIXTURE_ARTICLES_JSON = [
    {
        "slug": "test-take-the-thing-everyone-misses",
        "title": "The Thing Everyone Misses About Agentic Workflows",
        "tag": "Opinion",
        "date": "2026-05-10",
        "date_display": "May 10, 2026",
        "read_time": "5 min read",
        "excerpt": "Most teams plug an agent into a workflow and call it done.",
        "featured": True,
    },
    {
        "slug": "test-take-when-prompting-stopped-being-novelty",
        "title": "When Prompting Stopped Being a Novelty",
        "tag": "Opinion",
        "date": "2026-05-03",
        "date_display": "May 3, 2026",
        "read_time": "6 min read",
        "excerpt": "An observation about the slow normalisation of LLM work.",
        "featured": False,
    },
    {
        "slug": "test-take-numeric-read-time",
        "title": "Numeric Read Time Take",
        "tag": "Opinion",
        "date": "2026-04-18",
        "date_display": "April 18, 2026",
        "read_time": "4",   # legacy raw-number form, NOT "4 min read"
        "excerpt": "Tests the read_time pass-through path.",
        "featured": False,
    },
]

FIXTURE_MD_BODY = (
    "# The Thing Everyone Misses About Agentic Workflows\n"
    "\n"
    "*By Chiel Hendriks · Published May 10, 2026 · 5 min read*\n"
    "\n"
    "Most teams plug an agent into a workflow and call it done.\n"
)


def _make_handler(*, missing_md_slugs: set[str] | None = None):
    missing = missing_md_slugs or set()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/articles.json":
            return httpx.Response(
                200,
                json=FIXTURE_ARTICLES_JSON,
                headers={"content-type": "application/json"},
            )
        if path == "/test-take-the-thing-everyone-misses.md":
            if "test-take-the-thing-everyone-misses" in missing:
                return httpx.Response(
                    200,
                    text="<!doctype html>...</html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            return httpx.Response(
                200,
                text=FIXTURE_MD_BODY,
                headers={"content-type": "text/markdown; charset=utf-8"},
            )
        return httpx.Response(404)

    return handler


def _run_with_mock(coro_factory, *, missing_md_slugs: set[str] | None = None):
    async def runner():
        transport = httpx.MockTransport(_make_handler(missing_md_slugs=missing_md_slugs))
        async with httpx.AsyncClient(
            transport=transport, base_url="https://take.ambient-advantage.ai",
        ) as mock_client:
            _http._set_override_client(mock_client)
            try:
                return await coro_factory()
            finally:
                _http._set_override_client(None)

    return asyncio.run(runner())


def test_list_takes_parses_all_fields():
    result = _run_with_mock(lambda: takes.list_takes())
    assert len(result) == 3
    first = result[0]
    assert first.slug == "test-take-the-thing-everyone-misses"
    assert first.title == "The Thing Everyone Misses About Agentic Workflows"
    assert first.tag == "Opinion"
    assert first.date == "2026-05-10"
    assert first.date_display == "May 10, 2026"
    assert first.read_time == "5 min read"
    assert first.featured is True


def test_list_takes_preserves_feed_order():
    result = _run_with_mock(lambda: takes.list_takes())
    assert [m.slug for m in result] == [
        "test-take-the-thing-everyone-misses",
        "test-take-when-prompting-stopped-being-novelty",
        "test-take-numeric-read-time",
    ]


def test_list_takes_respects_limit():
    result = _run_with_mock(lambda: takes.list_takes(limit=2))
    assert len(result) == 2
    assert result[1].slug == "test-take-when-prompting-stopped-being-novelty"


def test_list_takes_builds_canonical_source_url():
    result = _run_with_mock(lambda: takes.list_takes(limit=1))
    assert result[0].source_url == \
        "https://take.ambient-advantage.ai/test-take-the-thing-everyone-misses.html"


def test_list_takes_passes_through_numeric_read_time():
    """The legacy frontmatter form stores read_time as a bare number; the
    adapter must NOT try to normalise. Step 5 (Pydantic) will decide.
    """
    result = _run_with_mock(lambda: takes.list_takes())
    legacy = next(m for m in result if m.slug == "test-take-numeric-read-time")
    assert legacy.read_time == "4"


def test_list_takes_handles_missing_featured_as_false():
    """The 'featured' field is optional in articles.json. Default is False."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"slug": "no-featured", "title": "X", "date": "2026-01-01"}],
            headers={"content-type": "application/json"},
        )

    async def runner():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://take.ambient-advantage.ai",
        ) as mock_client:
            _http._set_override_client(mock_client)
            try:
                return await takes.list_takes()
            finally:
                _http._set_override_client(None)

    result = asyncio.run(runner())
    assert result[0].featured is False


def test_get_take_returns_markdown_when_available():
    full = _run_with_mock(lambda: takes.get_take("test-take-the-thing-everyone-misses"))
    assert full is not None
    assert full.body_format == "markdown"
    assert full.body_markdown == FIXTURE_MD_BODY
    # Title preserved at top so agents can cite without losing context.
    assert full.body_markdown.startswith("# The Thing Everyone Misses About Agentic Workflows")
    # Byline and date line preserved verbatim.
    assert "*By Chiel Hendriks · Published May 10, 2026 · 5 min read*" in full.body_markdown


def test_get_take_metadata_matches_index_entry():
    full = _run_with_mock(lambda: takes.get_take("test-take-the-thing-everyone-misses"))
    assert full is not None
    assert full.title == "The Thing Everyone Misses About Agentic Workflows"
    assert full.tag == "Opinion"
    assert full.date == "2026-05-10"
    assert full.featured is True
    assert full.excerpt == "Most teams plug an agent into a workflow and call it done."


def test_get_take_returns_unavailable_on_html_fallback():
    """Same Cloudflare SPA-fallback defence as the briefings adapter."""
    full = _run_with_mock(
        lambda: takes.get_take("test-take-the-thing-everyone-misses"),
        missing_md_slugs={"test-take-the-thing-everyone-misses"},
    )
    assert full is not None
    assert full.body_format == "unavailable"
    assert full.body_markdown == ""
    # Metadata still surfaces so the MCP tool can return a helpful error.
    assert full.title == "The Thing Everyone Misses About Agentic Workflows"


def test_get_take_returns_none_for_unknown_slug():
    full = _run_with_mock(lambda: takes.get_take("totally-made-up-slug"))
    assert full is None


def test_takemeta_schema_version_is_v1():
    result = _run_with_mock(lambda: takes.list_takes(limit=1))
    assert result[0].schema_version == "v1"


def test_takefull_schema_version_is_v1():
    full = _run_with_mock(lambda: takes.get_take("test-take-the-thing-everyone-misses"))
    assert full is not None
    assert full.schema_version == "v1"
