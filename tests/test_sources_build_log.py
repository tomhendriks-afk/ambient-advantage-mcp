"""Offline tests for the build_log source adapter."""

from __future__ import annotations

import asyncio

import httpx

from app.sources import _http, build_log


FIXTURE_POSTS_JSON = [
    {
        "slug": "test-post-on-cloud-run",
        "title": "How Cloud Run shines",
        "tag": "Architecture",
        "tags": ["cloud-run", "architecture", "decisions"],
        "date": "2026-05-10",
        "date_display": "May 10, 2026",
        "read_time": "8",
        "read_time_display": "8 min read",
        "excerpt": "Test post about Cloud Run.",
        "pinned": True,
    },
    {
        "slug": "test-post-on-firestore",
        "title": "Firestore for the lazy",
        "tag": "Notes",
        "tags": ["firestore", "decisions"],
        "date": "2026-05-03",
        "date_display": "May 3, 2026",
        "read_time": "5",
        "read_time_display": "5 min read",
        "excerpt": "Test post about Firestore.",
        "pinned": False,
    },
    {
        "slug": "test-post-with-no-tags",
        "title": "Untagged thoughts",
        "tag": "Notes",
        "date": "2026-04-21",
        "date_display": "April 21, 2026",
        "read_time": "3",
        "read_time_display": "3 min read",
        "excerpt": "No tags array on this one.",
        # 'tags' field intentionally missing
        # 'pinned' field intentionally missing
    },
]

FIXTURE_MD_BODY = (
    "# How Cloud Run shines\n"
    "\n"
    "*By Chiel Hendriks · Published May 10, 2026 · 8 min read · Architecture*\n"
    "\n"
    "*Tags: cloud-run, architecture, decisions*\n"
    "\n"
    "Cloud Run scales to zero. That's the whole pitch.\n"
)


def _make_handler(*, missing_md_slugs: set[str] | None = None):
    missing = missing_md_slugs or set()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/posts.json":
            return httpx.Response(
                200,
                json=FIXTURE_POSTS_JSON,
                headers={"content-type": "application/json"},
            )
        if path == "/test-post-on-cloud-run.md":
            if "test-post-on-cloud-run" in missing:
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
        transport = httpx.MockTransport(
            _make_handler(missing_md_slugs=missing_md_slugs)
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://build.ambient-advantage.ai",
        ) as mock_client:
            _http._set_override_client(mock_client)
            try:
                return await coro_factory()
            finally:
                _http._set_override_client(None)

    return asyncio.run(runner())


# ----------------------------- list_posts ----------------------------- #

def test_list_posts_parses_all_fields():
    result = _run_with_mock(lambda: build_log.list_posts())
    assert len(result) == 3
    first = result[0]
    assert first.slug == "test-post-on-cloud-run"
    assert first.title == "How Cloud Run shines"
    assert first.tag == "Architecture"
    assert first.tags == ("cloud-run", "architecture", "decisions")
    assert first.date == "2026-05-10"
    assert first.date_display == "May 10, 2026"
    assert first.read_time == "8"
    assert first.read_time_display == "8 min read"
    assert first.pinned is True


def test_list_posts_preserves_feed_order():
    result = _run_with_mock(lambda: build_log.list_posts())
    assert [m.slug for m in result] == [
        "test-post-on-cloud-run",
        "test-post-on-firestore",
        "test-post-with-no-tags",
    ]


def test_list_posts_respects_limit():
    result = _run_with_mock(lambda: build_log.list_posts(limit=2))
    assert len(result) == 2


def test_list_posts_builds_canonical_source_url():
    result = _run_with_mock(lambda: build_log.list_posts(limit=1))
    assert result[0].source_url == \
        "https://build.ambient-advantage.ai/test-post-on-cloud-run.html"


def test_list_posts_returns_tags_as_immutable_tuple():
    """Tuples are required for the frozen-dataclass to remain hashable."""
    result = _run_with_mock(lambda: build_log.list_posts(limit=1))
    assert isinstance(result[0].tags, tuple)


def test_list_posts_handles_missing_tags_array_as_empty_tuple():
    result = _run_with_mock(lambda: build_log.list_posts())
    untagged = next(p for p in result if p.slug == "test-post-with-no-tags")
    assert untagged.tags == ()


def test_list_posts_handles_missing_pinned_as_false():
    result = _run_with_mock(lambda: build_log.list_posts())
    untagged = next(p for p in result if p.slug == "test-post-with-no-tags")
    assert untagged.pinned is False


# ------------------------------- get_post ----------------------------- #

def test_get_post_returns_markdown_when_available():
    full = _run_with_mock(lambda: build_log.get_post("test-post-on-cloud-run"))
    assert full is not None
    assert full.body_format == "markdown"
    assert full.body_markdown == FIXTURE_MD_BODY
    assert full.body_markdown.startswith("# How Cloud Run shines")


def test_get_post_metadata_matches_index_entry():
    full = _run_with_mock(lambda: build_log.get_post("test-post-on-cloud-run"))
    assert full is not None
    assert full.title == "How Cloud Run shines"
    assert full.tag == "Architecture"
    assert full.tags == ("cloud-run", "architecture", "decisions")
    assert full.pinned is True
    assert full.read_time_display == "8 min read"


def test_get_post_returns_unavailable_on_html_fallback():
    full = _run_with_mock(
        lambda: build_log.get_post("test-post-on-cloud-run"),
        missing_md_slugs={"test-post-on-cloud-run"},
    )
    assert full is not None
    assert full.body_format == "unavailable"
    assert full.body_markdown == ""
    # Metadata still surfaces.
    assert full.title == "How Cloud Run shines"


def test_get_post_returns_none_for_unknown_slug():
    full = _run_with_mock(lambda: build_log.get_post("totally-made-up-slug"))
    assert full is None


# -------------------------- list_components --------------------------- #

def test_list_components_aggregates_every_tag_across_posts():
    components = _run_with_mock(lambda: build_log.list_components())
    slugs = {c.slug for c in components}
    # Every tag from every post's tags array should be present, including
    # both component tags (cloud-run, firestore) and theme tags
    # (architecture, decisions).
    assert slugs == {"cloud-run", "architecture", "decisions", "firestore"}


def test_list_components_post_count_is_accurate():
    components = _run_with_mock(lambda: build_log.list_components())
    counts = {c.slug: c.post_count for c in components}
    # decisions appears on the cloud-run AND firestore posts → 2
    assert counts["decisions"] == 2
    assert counts["cloud-run"] == 1
    assert counts["firestore"] == 1
    assert counts["architecture"] == 1


def test_list_components_sorts_by_count_desc_then_slug_asc():
    components = _run_with_mock(lambda: build_log.list_components())
    # decisions (count=2) should be first; the three count=1 tags should
    # follow in alphabetical order.
    assert [c.slug for c in components] == [
        "decisions",
        "architecture",
        "cloud-run",
        "firestore",
    ]


def test_list_components_post_slugs_preserve_feed_order():
    """post_slugs should be newest-first, matching posts.json ordering."""
    components = _run_with_mock(lambda: build_log.list_components())
    decisions = next(c for c in components if c.slug == "decisions")
    assert decisions.post_slugs == (
        "test-post-on-cloud-run",   # 2026-05-10 (newer)
        "test-post-on-firestore",   # 2026-05-03 (older)
    )


def test_list_components_returns_immutable_tuples():
    components = _run_with_mock(lambda: build_log.list_components())
    assert all(isinstance(c.post_slugs, tuple) for c in components)


def test_list_components_returns_empty_when_no_posts():
    """A site with no posts (or no tagged posts) should yield [], not error."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[],
            headers={"content-type": "application/json"},
        )

    async def runner():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://build.ambient-advantage.ai",
        ) as mock_client:
            _http._set_override_client(mock_client)
            try:
                return await build_log.list_components()
            finally:
                _http._set_override_client(None)

    assert asyncio.run(runner()) == []


# ------------------------- schema_version tags ------------------------ #

def test_postmeta_schema_version_is_v1():
    result = _run_with_mock(lambda: build_log.list_posts(limit=1))
    assert result[0].schema_version == "v1"


def test_postfull_schema_version_is_v1():
    full = _run_with_mock(lambda: build_log.get_post("test-post-on-cloud-run"))
    assert full is not None
    assert full.schema_version == "v1"


def test_componentsummary_schema_version_is_v1():
    components = _run_with_mock(lambda: build_log.list_components())
    assert components[0].schema_version == "v1"
