"""Pydantic v2 models for the MCP tool-output contract.

This module wraps the adapter dataclasses (app.sources.*) in Pydantic
models so the MCP SDK can generate JSON Schema from the return-type
annotations of tools registered in step 6. The models intentionally
mirror the adapter shapes one-for-one; this is a contract layer, not a
transformation layer.

Why a separate Pydantic layer at all:
1. The MCP SDK introspects return-type annotations to publish a tool's
   output schema to clients. Pydantic gives that schema for free.
2. schema_version is locked to "v1" as a Literal so it appears as a
   JSON Schema `const`, making it visible to downstream consumers.
3. Keeps the adapters dataclass-only and dep-light so they can be
   tested without pydantic.

Construction pattern: every model has `from_attributes=True`, so
   BriefingMetaModel.model_validate(meta_dataclass)
works directly without a custom converter. Tuples on the adapter side
(e.g. tags) coerce cleanly to list[str] on the model side.

Inputs (GetBriefingByDateInput etc.) land in step 6 alongside the
@mcp.tool() registrations, since each input shape is tightly coupled
to one tool's signature.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


SCHEMA_VERSION = "v1"


class _MCPModel(BaseModel):
    """Base for every public schema.

    from_attributes=True lets us run e.g. Model.model_validate(dataclass_obj).
    frozen=True matches the adapter dataclasses (read-only contract).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)


# --------------------------------------------------------------------------- #
# Briefings                                                                   #
# --------------------------------------------------------------------------- #

class BriefingMetaModel(_MCPModel):
    """Briefing metadata: index entry without body. Mirrors BriefingMeta."""

    date: str
    headline: str
    snippet: str
    read_time: int
    source_url: str
    schema_version: Literal["v1"] = SCHEMA_VERSION


class BriefingFullModel(_MCPModel):
    """Briefing with full markdown body. Mirrors BriefingFull."""

    date: str
    headline: str
    snippet: str
    read_time: int
    source_url: str
    body_markdown: str
    body_format: Literal["markdown", "unavailable"]
    schema_version: Literal["v1"] = SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Chiel's Take                                                                #
# --------------------------------------------------------------------------- #

class TakeMetaModel(_MCPModel):
    """Take metadata. Mirrors TakeMeta."""

    slug: str
    title: str
    tag: str
    date: str
    date_display: str
    read_time: str
    excerpt: str
    featured: bool
    source_url: str
    schema_version: Literal["v1"] = SCHEMA_VERSION


class TakeFullModel(_MCPModel):
    """Take with full markdown body. Mirrors TakeFull."""

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
    schema_version: Literal["v1"] = SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Podcast                                                                     #
# --------------------------------------------------------------------------- #

class EpisodeMetaModel(_MCPModel):
    """Podcast episode metadata. Mirrors EpisodeMeta."""

    date: str
    title: str
    description: str
    audio_url: str
    duration_seconds: int
    guid: str
    source_url: str
    schema_version: Literal["v1"] = SCHEMA_VERSION


class EpisodeFullModel(_MCPModel):
    """Episode with full transcript markdown. Mirrors EpisodeFull."""

    date: str
    title: str
    description: str
    audio_url: str
    duration_seconds: int
    guid: str
    source_url: str
    transcript_markdown: str
    transcript_format: Literal["markdown", "unavailable"]
    schema_version: Literal["v1"] = SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Build Log                                                                   #
# --------------------------------------------------------------------------- #

class PostMetaModel(_MCPModel):
    """Build Log post metadata. Mirrors PostMeta.

    Adapter stores `tags` as tuple[str, ...] for frozen-dataclass hashing;
    Pydantic surfaces it as a JSON array.
    """

    slug: str
    title: str
    tag: str
    tags: list[str]
    date: str
    date_display: str
    read_time: str
    read_time_display: str
    excerpt: str
    pinned: bool
    source_url: str
    schema_version: Literal["v1"] = SCHEMA_VERSION


class PostFullModel(_MCPModel):
    """Build Log post with full markdown body. Mirrors PostFull."""

    slug: str
    title: str
    tag: str
    tags: list[str]
    date: str
    date_display: str
    read_time: str
    read_time_display: str
    excerpt: str
    pinned: bool
    source_url: str
    body_markdown: str
    body_format: Literal["markdown", "unavailable"]
    schema_version: Literal["v1"] = SCHEMA_VERSION


class ComponentSummaryModel(_MCPModel):
    """Aggregated tag summary across posts.json. Mirrors ComponentSummary.

    Surfaces only structural data (slug, post_count, post_slugs).
    Editorial labels (name, blurb, group) live in build-site/publish.py
    and are not exposed by any public URL today.
    """

    slug: str
    post_count: int
    post_slugs: list[str]
    schema_version: Literal["v1"] = SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Search hit shapes — extend the meta models with relevance fields            #
# --------------------------------------------------------------------------- #

class BriefingSearchHit(_MCPModel):
    """A briefing matched by search_briefings, scored against the query."""

    date: str
    headline: str
    snippet: str
    read_time: int
    source_url: str
    score: int
    matched_terms: list[str]
    schema_version: Literal["v1"] = SCHEMA_VERSION


class TakeSearchHit(_MCPModel):
    """A take matched by search_chiels_take, scored against the query."""

    slug: str
    title: str
    tag: str
    date: str
    date_display: str
    read_time: str
    excerpt: str
    featured: bool
    source_url: str
    score: int
    matched_terms: list[str]
    schema_version: Literal["v1"] = SCHEMA_VERSION


class PostSearchHit(_MCPModel):
    """A Build Log post matched by search_build_log, scored against the query."""

    slug: str
    title: str
    tag: str
    tags: list[str]
    date: str
    date_display: str
    read_time: str
    read_time_display: str
    excerpt: str
    pinned: bool
    source_url: str
    score: int
    matched_terms: list[str]
    schema_version: Literal["v1"] = SCHEMA_VERSION


class BriefingTopic(_MCPModel):
    """A distinct topic across briefings with its occurrence count.

    PHASE 1 STUB: list_briefing_topics returns an empty list; this model
    is shipped so the tool's published JSON Schema is stable across the
    eventual switch from stub to real implementation.
    """

    topic: str
    count: int
    schema_version: Literal["v1"] = SCHEMA_VERSION
