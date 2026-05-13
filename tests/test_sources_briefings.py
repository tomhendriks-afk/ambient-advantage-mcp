"""Offline tests for the briefings source adapter.

Uses httpx.MockTransport to intercept outbound requests so tests never hit
the network. The override hook in app.sources._http swaps the singleton
client for the mock-backed one for the duration of each test.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from app.sources import _http, briefings


FIXTURE_BRIEFINGS_JSON = [
    {
        "date": "2026-05-12",
        "headline": "OpenAI &amp; Anthropic Trade Punches",
        "snippet": "This edition covers eight stories including &quot;quoted&quot; phrases.",
        "read_time": 7,
    },
    {
        "date": "2026-05-11",
        "headline": "Second story",
        "snippet": "A snippet.",
        "read_time": 5,
    },
    {
        "date": "2026-04-15",
        "headline": "Older story without markdown twin",
        "snippet": "Body text.",
        "read_time": 6,
    },
]

FIXTURE_MD_2026_05_12 = (
    "# OpenAI & Anthropic Trade Punches\n"
    "\n"
    "*Published Tuesday · May 12, 2026*\n"
    "\n"
    "Today's briefing in full markdown.\n"
)


def _make_handler(*, missing_md_dates: set[str] | None = None):
    """Build a MockTransport handler that serves the fixtures above.

    missing_md_dates models the Cloudflare SPA-fallback case: requests for
    those dates' .md files return 200 + text/html (the homepage HTML body),
    which is exactly how the live site behaves when a path is missing.
    """
    missing = missing_md_dates or set()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/briefings.json":
            return httpx.Response(
                200,
                json=FIXTURE_BRIEFINGS_JSON,
                headers={"content-type": "application/json"},
            )
        if path == "/2026-05-12.md":
            if "2026-05-12" in missing:
                return httpx.Response(
                    200,
                    text="<!doctype html><html>...index page...</html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            return httpx.Response(
                200,
                text=FIXTURE_MD_2026_05_12,
                headers={"content-type": "text/markdown; charset=utf-8"},
            )
        if path == "/2026-04-15.md":
            # The pre-backfill cohort: Cloudflare falls back to the index HTML.
            return httpx.Response(
                200,
                text="<!doctype html><html>...index page...</html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        return httpx.Response(404)

    return handler


def _run_with_mock(coro_factory, *, missing_md_dates: set[str] | None = None):
    """Run an async test with the source adapter's http client mocked."""

    async def runner():
        transport = httpx.MockTransport(_make_handler(missing_md_dates=missing_md_dates))
        async with httpx.AsyncClient(transport=transport, base_url="https://briefing.ambient-advantage.ai") as mock_client:
            _http._set_override_client(mock_client)
            try:
                return await coro_factory()
            finally:
                _http._set_override_client(None)

    return asyncio.run(runner())


def test_list_briefings_unescapes_html_entities():
    result = _run_with_mock(lambda: briefings.list_briefings())
    assert len(result) == 3
    assert result[0].date == "2026-05-12"
    assert result[0].headline == "OpenAI & Anthropic Trade Punches"
    assert result[0].snippet == 'This edition covers eight stories including "quoted" phrases.'
    assert result[0].read_time == 7


def test_list_briefings_preserves_newest_first_order():
    result = _run_with_mock(lambda: briefings.list_briefings())
    assert [m.date for m in result] == ["2026-05-12", "2026-05-11", "2026-04-15"]


def test_list_briefings_respects_limit():
    result = _run_with_mock(lambda: briefings.list_briefings(limit=2))
    assert [m.date for m in result] == ["2026-05-12", "2026-05-11"]


def test_list_briefings_builds_canonical_source_url():
    result = _run_with_mock(lambda: briefings.list_briefings(limit=1))
    assert result[0].source_url == "https://briefing.ambient-advantage.ai/2026-05-12.html"


def test_get_briefing_returns_markdown_when_md_available():
    full = _run_with_mock(lambda: briefings.get_briefing("2026-05-12"))
    assert full is not None
    assert full.body_format == "markdown"
    assert full.body_markdown == FIXTURE_MD_2026_05_12
    # Header lines must be preserved verbatim — agents need them for citation.
    assert full.body_markdown.startswith("# OpenAI & Anthropic Trade Punches")
    assert "*Published Tuesday · May 12, 2026*" in full.body_markdown


def test_get_briefing_treats_cloudflare_html_fallback_as_unavailable():
    """Older dates whose .md doesn't exist: live response is 200 + text/html
    (the index page body), and the adapter must NOT mistake that for markdown.
    """
    full = _run_with_mock(lambda: briefings.get_briefing("2026-04-15"))
    assert full is not None
    assert full.body_format == "unavailable"
    assert full.body_markdown == ""
    # Metadata still surfaces, so the MCP tool can return "we know about this
    # date but the body isn't available" rather than a generic 404.
    assert full.headline == "Older story without markdown twin"


def test_get_briefing_returns_none_for_unknown_date():
    full = _run_with_mock(lambda: briefings.get_briefing("2025-01-01"))
    assert full is None


def test_get_briefing_handles_transient_md_fallback_for_known_date():
    """If a date IS in the index but its .md briefly returns HTML (e.g. mid-
    deploy on Cloudflare), we report unavailable rather than crashing.
    """
    full = _run_with_mock(
        lambda: briefings.get_briefing("2026-05-12"),
        missing_md_dates={"2026-05-12"},
    )
    assert full is not None
    assert full.body_format == "unavailable"


def test_briefingmeta_schema_version_is_v1():
    result = _run_with_mock(lambda: briefings.list_briefings(limit=1))
    assert result[0].schema_version == "v1"


def test_briefingfull_schema_version_is_v1():
    full = _run_with_mock(lambda: briefings.get_briefing("2026-05-12"))
    assert full is not None
    assert full.schema_version == "v1"
