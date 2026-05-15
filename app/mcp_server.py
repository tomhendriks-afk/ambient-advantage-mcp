"""MCP server construction and tool registration.

build_mcp_server() returns a configured FastMCP instance with every
Phase 1 tool registered. Each tool is a module-level async function so
the test suite can call it directly without spinning up an MCP client.

This module hosts the 8 "simple" get/list tools (build plan step 6b);
the 4 search/topics tools land in step 6c.

Pattern for every tool:
  1. Open a tool_call_logger context manager so we get one structured
     log line per invocation (privacy-preserving — query_len only).
  2. Delegate to a source adapter (which is itself cache-backed).
  3. Validate the result into a Pydantic output model so the MCP SDK
     can publish a JSON Schema for clients.

Tool docstrings are the description the LLM sees when deciding whether
to call the tool. They lead with what the tool does, list inputs, and
remind the agent that every response carries source_url for citation.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import schemas, search
from .sources import briefings, build_log, podcast, takes
from .tool_logging import tool_call_logger


# Bumped only when tool input/output schemas change in a breaking way.
# Treated as a public contract once Phase 1 ships.
SCHEMA_VERSION = "v1"

SERVER_NAME = "ambient-advantage-mcp"
SERVER_INSTRUCTIONS = (
    "Read-only access to the Ambient Advantage content archive: daily AI "
    "briefings, Chiel's Take opinion pieces, podcast episodes, and Build "
    "Log posts. Every response carries source_url and published_at so "
    "answers can be cited correctly."
)


def build_mcp_server() -> FastMCP:
    """Construct the FastMCP instance and register all tools.

    streamable_http_path is set to "/" so that mounting the sub-app under
    "/mcp" on the parent FastAPI app produces a public endpoint of "/mcp/".

    DNS-rebinding protection is disabled deliberately. The SDK enables it
    by default with an empty allowed_hosts list, which rejects every
    non-localhost Host header with HTTP 421 ("Invalid Host header"). That
    protection exists to stop a malicious web page from driving a
    localhost/dev MCP server via DNS rebinding. This server is the
    opposite shape: public-internet by design (agents must reach it),
    read-only over already-public content, and reached through Firebase
    Hosting → Cloud Run where the Host header is the proxy's and not
    stable. There is no localhost/intranet resource it could be rebound
    onto, so the protection provides no security value here and only
    breaks legitimate access.
    """
    server = FastMCP(
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
    )
    register_tools(server)
    return server


# --------------------------------------------------------------------------- #
# Briefings tools                                                             #
# --------------------------------------------------------------------------- #

async def get_latest_briefing() -> schemas.BriefingFullModel | None:
    """Return the most recent daily AI briefing with its full markdown body.

    No inputs. The briefing is the morning intelligence brief published
    every weekday (ET) at briefing.ambient-advantage.ai. Every response
    includes source_url — cite the briefing by URL when quoting it.

    Returns None only if the archive is empty (should never happen in
    practice).
    """
    async with tool_call_logger("get_latest_briefing") as info:
        metas = await briefings.list_briefings(limit=1)
        if not metas:
            return None
        full = await briefings.get_briefing(metas[0].date)
        info["result_count"] = 1 if full is not None else 0
        if full is None:
            return None
        return schemas.BriefingFullModel.model_validate(full)


async def get_briefing_by_date(date: str) -> schemas.BriefingFullModel | None:
    """Return one daily AI briefing by its publication date.

    Input: date in YYYY-MM-DD format. Returns None if the archive has no
    briefing for that date (e.g. weekends — the briefing is weekday-only).
    body_format will be "unavailable" for older briefings whose markdown
    twin was never produced; the metadata and source_url still surface so
    the caller can recommend the HTML page.
    """
    async with tool_call_logger("get_briefing_by_date") as info:
        full = await briefings.get_briefing(date)
        info["result_count"] = 1 if full is not None else 0
        if full is None:
            return None
        return schemas.BriefingFullModel.model_validate(full)


# --------------------------------------------------------------------------- #
# Chiel's Take tools                                                          #
# --------------------------------------------------------------------------- #

async def get_chiels_take(slug: str) -> schemas.TakeFullModel | None:
    """Return a single opinion piece from Chiel's Take by its slug.

    Input: slug (the hyphenated URL identifier, e.g.
    "cfos-are-starting-to-code"). Use list_chiels_take to discover slugs.
    Returns None if the slug isn't published.
    """
    async with tool_call_logger("get_chiels_take") as info:
        full = await takes.get_take(slug)
        info["result_count"] = 1 if full is not None else 0
        if full is None:
            return None
        return schemas.TakeFullModel.model_validate(full)


async def list_chiels_take(
    limit: int = 20, offset: int = 0,
) -> list[schemas.TakeMetaModel]:
    """List recent Chiel's Take opinion pieces, newest-first, with metadata only.

    Inputs:
      - limit: maximum number to return (default 20).
      - offset: skip this many before taking `limit` (for pagination).

    Body content is NOT included — call get_chiels_take(slug) for that.
    """
    async with tool_call_logger("list_chiels_take") as info:
        metas = await takes.list_takes()
        page = metas[offset:offset + limit] if limit > 0 else []
        info["result_count"] = len(page)
        return [schemas.TakeMetaModel.model_validate(m) for m in page]


# --------------------------------------------------------------------------- #
# Podcast tools                                                               #
# --------------------------------------------------------------------------- #

async def get_podcast_episode(date: str) -> schemas.EpisodeFullModel | None:
    """Return a single podcast episode with its full transcript markdown.

    Input: date in YYYY-MM-DD format. Returns None if no episode aired on
    that date. transcript_format will be "unavailable" for older episodes
    (pre-2026-04-22) whose transcript was never archived; the episode
    metadata, audio_url, and source_url still surface so the caller can
    recommend the audio.
    """
    async with tool_call_logger("get_podcast_episode") as info:
        full = await podcast.get_episode(date)
        info["result_count"] = 1 if full is not None else 0
        if full is None:
            return None
        return schemas.EpisodeFullModel.model_validate(full)


async def list_podcast_episodes(
    limit: int = 20, offset: int = 0,
) -> list[schemas.EpisodeMetaModel]:
    """List recent podcast episodes, newest-first, with metadata only.

    Inputs:
      - limit: maximum number to return (default 20).
      - offset: skip this many before taking `limit` (for pagination).

    Transcript content is NOT included — call get_podcast_episode(date)
    for the full transcript.
    """
    async with tool_call_logger("list_podcast_episodes") as info:
        metas = await podcast.list_episodes()
        page = metas[offset:offset + limit] if limit > 0 else []
        info["result_count"] = len(page)
        return [schemas.EpisodeMetaModel.model_validate(m) for m in page]


# --------------------------------------------------------------------------- #
# Build Log tools                                                             #
# --------------------------------------------------------------------------- #

async def get_build_log_post(slug: str) -> schemas.PostFullModel | None:
    """Return a single Build Log post by its slug, with full markdown body.

    Input: slug (hyphenated URL identifier). The Build Log catalogues how
    the Ambient Advantage pipeline itself is built — architecture
    deep-dives, component notes, operational gotchas. Returns None if the
    slug isn't published.
    """
    async with tool_call_logger("get_build_log_post") as info:
        full = await build_log.get_post(slug)
        info["result_count"] = 1 if full is not None else 0
        if full is None:
            return None
        return schemas.PostFullModel.model_validate(full)


async def list_build_log_components() -> list[schemas.ComponentSummaryModel]:
    """Return every tag aggregated across Build Log posts, with counts.

    No inputs. The Build Log uses tags as a navigation spine — component
    tags (cloud-run, firestore, etc.) and theme tags (architecture,
    decisions, etc.) appear here uniformly. Sorted by post_count desc,
    then slug asc. Each entry includes the slugs of posts carrying that
    tag, newest-first, so the caller can navigate without re-fetching.
    """
    async with tool_call_logger("list_build_log_components") as info:
        components = await build_log.list_components()
        info["result_count"] = len(components)
        return [schemas.ComponentSummaryModel.model_validate(c) for c in components]


# --------------------------------------------------------------------------- #
# Search tools                                                                #
# --------------------------------------------------------------------------- #

def _in_range(date: str, date_from: str | None, date_to: str | None) -> bool:
    """ISO YYYY-MM-DD dates compare correctly as strings."""
    if date_from and date < date_from:
        return False
    if date_to and date > date_to:
        return False
    return True


async def search_briefings(
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
) -> list[schemas.BriefingSearchHit]:
    """Search briefings by headline and snippet.

    Inputs:
      - query: search terms; AND semantics (all terms must appear).
      - date_from / date_to: optional YYYY-MM-DD bounds (inclusive).
      - limit: max hits to return (default 10).

    Returns hits sorted by relevance score desc, then publish date desc.
    Phase 1 matches on title (headline) + snippet from briefings.json;
    full-body search lands later. source_url cites the canonical HTML
    page for each hit.
    """
    async with tool_call_logger("search_briefings", query_len=len(query)) as info:
        terms = search.tokenize(query)
        if not terms:
            info["result_count"] = 0
            return []

        metas = await briefings.list_briefings()
        scored: list[tuple[int, list[str], briefings.BriefingMeta]] = []
        for m in metas:
            if not _in_range(m.date, date_from, date_to):
                continue
            score, matched = search.score_text(f"{m.headline} {m.snippet}", terms)
            if score > 0:
                scored.append((score, matched, m))

        # Sort by (score, date) tuple in descending order: highest score
        # wins; on ties, newer date wins. ISO YYYY-MM-DD compares lexically.
        scored.sort(key=lambda t: (t[0], t[2].date), reverse=True)
        scored = scored[:max(0, limit)]

        hits = [
            schemas.BriefingSearchHit(
                date=m.date,
                headline=m.headline,
                snippet=m.snippet,
                read_time=m.read_time,
                source_url=m.source_url,
                score=score,
                matched_terms=matched,
            )
            for score, matched, m in scored
        ]
        info["result_count"] = len(hits)
        return hits


async def list_briefing_topics(
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[schemas.BriefingTopic]:
    """List distinct topics across briefings in a date range, with counts.

    PHASE 1 STUB: topic extraction requires either a tag taxonomy on the
    briefings (not currently published) or keyword extraction from
    headlines (noisy without curation). Phase 1 returns an empty list;
    the tool is shipped now so the schema is stable when the real
    implementation lands.

    date_from / date_to are accepted for forward compatibility but
    currently ignored.
    """
    async with tool_call_logger("list_briefing_topics") as info:
        # date_from/date_to deliberately unused in Phase 1; the parameters
        # are part of the locked schema for the eventual real implementation.
        _ = (date_from, date_to)
        info["result_count"] = 0
        return []


async def search_chiels_take(
    query: str,
    limit: int = 10,
) -> list[schemas.TakeSearchHit]:
    """Search Chiel's Take opinion pieces by title and excerpt.

    Inputs:
      - query: search terms; AND semantics.
      - limit: max hits to return (default 10).

    Sorted by relevance score desc, then date desc. Title + excerpt
    matching only; full-body search lands later.
    """
    async with tool_call_logger("search_chiels_take", query_len=len(query)) as info:
        terms = search.tokenize(query)
        if not terms:
            info["result_count"] = 0
            return []

        metas = await takes.list_takes()
        scored: list[tuple[int, list[str], takes.TakeMeta]] = []
        for m in metas:
            score, matched = search.score_text(f"{m.title} {m.excerpt}", terms)
            if score > 0:
                scored.append((score, matched, m))

        scored.sort(key=lambda t: (t[0], t[2].date), reverse=True)
        scored = scored[:max(0, limit)]

        hits = [
            schemas.TakeSearchHit(
                slug=m.slug,
                title=m.title,
                tag=m.tag,
                date=m.date,
                date_display=m.date_display,
                read_time=m.read_time,
                excerpt=m.excerpt,
                featured=m.featured,
                source_url=m.source_url,
                score=score,
                matched_terms=matched,
            )
            for score, matched, m in scored
        ]
        info["result_count"] = len(hits)
        return hits


async def search_build_log(
    query: str,
    tag: str | None = None,
    limit: int = 10,
) -> list[schemas.PostSearchHit]:
    """Search Build Log posts by title and excerpt, optionally tag-filtered.

    Inputs:
      - query: search terms; AND semantics.
      - tag: optional tag slug to filter on (e.g. "cloud-run", "firestore").
        If supplied, only posts carrying that tag are considered before
        scoring the query.
      - limit: max hits to return (default 10).

    Sorted by relevance score desc, then date desc.
    """
    async with tool_call_logger("search_build_log", query_len=len(query)) as info:
        terms = search.tokenize(query)
        if not terms:
            info["result_count"] = 0
            return []

        metas = await build_log.list_posts()
        scored: list[tuple[int, list[str], build_log.PostMeta]] = []
        for m in metas:
            if tag is not None and tag not in m.tags:
                continue
            score, matched = search.score_text(f"{m.title} {m.excerpt}", terms)
            if score > 0:
                scored.append((score, matched, m))

        scored.sort(key=lambda t: (t[0], t[2].date), reverse=True)
        scored = scored[:max(0, limit)]

        hits = [
            schemas.PostSearchHit(
                slug=m.slug,
                title=m.title,
                tag=m.tag,
                tags=list(m.tags),
                date=m.date,
                date_display=m.date_display,
                read_time=m.read_time,
                read_time_display=m.read_time_display,
                excerpt=m.excerpt,
                pinned=m.pinned,
                source_url=m.source_url,
                score=score,
                matched_terms=matched,
            )
            for score, matched, m in scored
        ]
        info["result_count"] = len(hits)
        return hits


def register_tools(server: FastMCP) -> None:
    """Register every public tool on the given FastMCP instance."""
    server.add_tool(get_latest_briefing)
    server.add_tool(get_briefing_by_date)
    server.add_tool(get_chiels_take)
    server.add_tool(list_chiels_take)
    server.add_tool(get_podcast_episode)
    server.add_tool(list_podcast_episodes)
    server.add_tool(get_build_log_post)
    server.add_tool(list_build_log_components)
    server.add_tool(search_briefings)
    server.add_tool(list_briefing_topics)
    server.add_tool(search_chiels_take)
    server.add_tool(search_build_log)
