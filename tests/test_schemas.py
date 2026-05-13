"""Tests for the Pydantic output models in app/schemas.py.

Each model must:
1. Construct cleanly from its adapter dataclass via model_validate(),
2. Carry schema_version="v1" surfaced as a JSON Schema const,
3. Round-trip to dict with all expected fields preserved.

The "schema_version is const in JSON Schema" check is the load-bearing
one for downstream consumers: it makes the version explicit and
machine-readable on the MCP tool's published schema.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import schemas
from app.sources import briefings, build_log, podcast, takes


# --------------------------------------------------------------------------- #
# Briefings                                                                   #
# --------------------------------------------------------------------------- #

def test_briefing_meta_model_validates_from_dataclass():
    meta = briefings.BriefingMeta(
        date="2026-05-12",
        headline="A & B",
        snippet="Snippet text.",
        read_time=7,
        source_url="https://briefing.ambient-advantage.ai/2026-05-12.html",
    )
    m = schemas.BriefingMetaModel.model_validate(meta)
    assert m.date == "2026-05-12"
    assert m.headline == "A & B"
    assert m.read_time == 7
    assert m.schema_version == "v1"


def test_briefing_full_model_validates_from_dataclass():
    full = briefings.BriefingFull(
        date="2026-05-12",
        headline="A",
        snippet="S",
        read_time=7,
        source_url="https://briefing.ambient-advantage.ai/2026-05-12.html",
        body_markdown="# A\n\nbody.\n",
        body_format="markdown",
    )
    m = schemas.BriefingFullModel.model_validate(full)
    assert m.body_format == "markdown"
    assert m.body_markdown == "# A\n\nbody.\n"


def test_briefing_full_model_rejects_unknown_body_format():
    """body_format is a Literal — anything else must fail validation."""
    with pytest.raises(ValidationError):
        schemas.BriefingFullModel(
            date="2026-05-12",
            headline="A",
            snippet="S",
            read_time=7,
            source_url="x",
            body_markdown="",
            body_format="html_derived",  # not in the Literal
        )


# --------------------------------------------------------------------------- #
# Takes                                                                       #
# --------------------------------------------------------------------------- #

def test_take_meta_model_validates_from_dataclass():
    meta = takes.TakeMeta(
        slug="some-take",
        title="Some Take",
        tag="Opinion",
        date="2026-05-10",
        date_display="May 10, 2026",
        read_time="5 min read",
        excerpt="An excerpt.",
        featured=True,
        source_url="https://take.ambient-advantage.ai/some-take.html",
    )
    m = schemas.TakeMetaModel.model_validate(meta)
    assert m.slug == "some-take"
    assert m.featured is True
    assert m.read_time == "5 min read"


def test_take_full_model_validates_from_dataclass():
    full = takes.TakeFull(
        slug="some-take",
        title="Some Take",
        tag="Opinion",
        date="2026-05-10",
        date_display="May 10, 2026",
        read_time="5 min read",
        excerpt="An excerpt.",
        featured=False,
        source_url="x",
        body_markdown="# Some Take\n\nBody.\n",
        body_format="markdown",
    )
    m = schemas.TakeFullModel.model_validate(full)
    assert m.body_markdown == "# Some Take\n\nBody.\n"
    assert m.featured is False


# --------------------------------------------------------------------------- #
# Podcast                                                                     #
# --------------------------------------------------------------------------- #

def test_episode_meta_model_validates_from_dataclass():
    meta = podcast.EpisodeMeta(
        date="2026-05-12",
        title="Ambient Advantage — May 12, 2026",
        description="Show notes.",
        audio_url="https://example.com/audio.mp3",
        duration_seconds=899,
        guid="guid-123",
        source_url="https://podcast.ambient-advantage.ai/episodes/2026-05-12.html",
    )
    m = schemas.EpisodeMetaModel.model_validate(meta)
    assert m.duration_seconds == 899
    assert m.guid == "guid-123"


def test_episode_full_model_validates_from_dataclass():
    full = podcast.EpisodeFull(
        date="2026-05-12",
        title="t",
        description="d",
        audio_url="u",
        duration_seconds=900,
        guid="g",
        source_url="s",
        transcript_markdown="# t\n\n[JON]\nhi\n",
        transcript_format="markdown",
    )
    m = schemas.EpisodeFullModel.model_validate(full)
    assert m.transcript_format == "markdown"
    assert "[JON]" in m.transcript_markdown


def test_episode_full_model_rejects_unknown_transcript_format():
    with pytest.raises(ValidationError):
        schemas.EpisodeFullModel(
            date="2026-05-12",
            title="t",
            description="d",
            audio_url="u",
            duration_seconds=900,
            guid="g",
            source_url="s",
            transcript_markdown="",
            transcript_format="audio_only",  # not in the Literal
        )


# --------------------------------------------------------------------------- #
# Build Log                                                                   #
# --------------------------------------------------------------------------- #

def test_post_meta_model_coerces_tuple_tags_to_list():
    """Adapter dataclass stores tags as tuple; Pydantic surfaces a list."""
    meta = build_log.PostMeta(
        slug="post-1",
        title="Title",
        tag="Architecture",
        tags=("cloud-run", "decisions"),
        date="2026-05-10",
        date_display="May 10, 2026",
        read_time="8",
        read_time_display="8 min read",
        excerpt="x",
        pinned=True,
        source_url="x",
    )
    m = schemas.PostMetaModel.model_validate(meta)
    assert m.tags == ["cloud-run", "decisions"]
    assert isinstance(m.tags, list)
    assert m.pinned is True


def test_post_full_model_validates_from_dataclass():
    full = build_log.PostFull(
        slug="post-1",
        title="Title",
        tag="Architecture",
        tags=("cloud-run", "decisions"),
        date="2026-05-10",
        date_display="May 10, 2026",
        read_time="8",
        read_time_display="8 min read",
        excerpt="x",
        pinned=False,
        source_url="x",
        body_markdown="# T\n\nBody.\n",
        body_format="markdown",
    )
    m = schemas.PostFullModel.model_validate(full)
    assert m.tags == ["cloud-run", "decisions"]
    assert m.body_format == "markdown"


def test_component_summary_model_validates_from_dataclass():
    summary = build_log.ComponentSummary(
        slug="cloud-run",
        post_count=3,
        post_slugs=("post-1", "post-2", "post-3"),
    )
    m = schemas.ComponentSummaryModel.model_validate(summary)
    assert m.slug == "cloud-run"
    assert m.post_count == 3
    assert m.post_slugs == ["post-1", "post-2", "post-3"]


# --------------------------------------------------------------------------- #
# Cross-model: schema_version is locked + visible in JSON Schema              #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("model_cls", [
    schemas.BriefingMetaModel,
    schemas.BriefingFullModel,
    schemas.TakeMetaModel,
    schemas.TakeFullModel,
    schemas.EpisodeMetaModel,
    schemas.EpisodeFullModel,
    schemas.PostMetaModel,
    schemas.PostFullModel,
    schemas.ComponentSummaryModel,
])
def test_schema_version_appears_as_const_in_json_schema(model_cls):
    """The MCP SDK publishes this JSON Schema to clients; consumers must
    be able to read schema_version="v1" as a machine-readable constant.
    """
    schema = model_cls.model_json_schema()
    sv = schema["properties"]["schema_version"]
    # Pydantic v2 surfaces a Literal field as either `const: "v1"` or
    # `enum: ["v1"]` depending on version; either is fine for consumers.
    assert sv.get("const") == "v1" or sv.get("enum") == ["v1"]


def test_models_are_frozen():
    """The contract is read-only; mutating a returned model should fail."""
    m = schemas.BriefingMetaModel(
        date="2026-05-12",
        headline="h",
        snippet="s",
        read_time=7,
        source_url="x",
    )
    with pytest.raises(ValidationError):
        m.headline = "mutated"


def test_round_trip_briefing_meta_to_dict_preserves_all_fields():
    meta = briefings.BriefingMeta(
        date="2026-05-12",
        headline="A & B",
        snippet="S",
        read_time=7,
        source_url="x",
    )
    dumped = schemas.BriefingMetaModel.model_validate(meta).model_dump()
    assert dumped == {
        "date": "2026-05-12",
        "headline": "A & B",
        "snippet": "S",
        "read_time": 7,
        "source_url": "x",
        "schema_version": "v1",
    }
