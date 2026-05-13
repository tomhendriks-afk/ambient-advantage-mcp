"""Tests for tool_logging.tool_call_logger.

Capture log output via the caplog fixture and assert the structured
JSON line has the expected shape per §8 of the build plan.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app import cache, tool_logging


@pytest.fixture(autouse=True)
def _isolate_cache():
    cache.clear()
    yield
    cache.clear()


def _run(coro):
    return asyncio.run(coro)


def _parse_log_lines(caplog: pytest.LogCaptureFixture) -> list[dict]:
    """Pull structured tool_call records out of caplog."""
    out = []
    for record in caplog.records:
        if record.name != "ambient-advantage-mcp.tool":
            continue
        try:
            out.append(json.loads(record.getMessage()))
        except json.JSONDecodeError:
            continue
    return [r for r in out if r.get("event") == "tool_call"]


def test_emits_one_structured_line_on_success(caplog):
    caplog.set_level(logging.INFO, logger="ambient-advantage-mcp.tool")

    async def go():
        async with tool_logging.tool_call_logger("my_tool", query_len=5) as info:
            info["result_count"] = 3

    _run(go())
    lines = _parse_log_lines(caplog)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["tool_name"] == "my_tool"
    assert entry["query_len"] == 5
    assert entry["result_count"] == 3
    assert entry["failed"] is False
    # total_latency_ms is non-negative; we don't assert an exact value.
    assert entry["total_latency_ms"] >= 0


def test_records_cache_hit_when_no_fresh_miss_occurred(caplog):
    caplog.set_level(logging.INFO, logger="ambient-advantage-mcp.tool")

    async def go():
        # No cache fetch inside the body → miss counter unchanged → cache_hit=True
        async with tool_logging.tool_call_logger("warm_tool") as info:
            info["result_count"] = 0

    _run(go())
    entry = _parse_log_lines(caplog)[0]
    assert entry["cache_hit"] is True


def test_records_cache_miss_when_a_fresh_fetch_occurred(caplog):
    caplog.set_level(logging.INFO, logger="ambient-advantage-mcp.tool")

    async def fetch():
        return "value"

    async def go():
        async with tool_logging.tool_call_logger("cold_tool") as info:
            await cache.get_or_fetch("k", 60.0, fetch)
            info["result_count"] = 1

    _run(go())
    entry = _parse_log_lines(caplog)[0]
    assert entry["cache_hit"] is False


def test_logs_failure_flag_when_tool_raises(caplog):
    caplog.set_level(logging.INFO, logger="ambient-advantage-mcp.tool")

    async def go():
        with pytest.raises(RuntimeError, match="boom"):
            async with tool_logging.tool_call_logger("failing_tool"):
                raise RuntimeError("boom")

    _run(go())
    entry = _parse_log_lines(caplog)[0]
    assert entry["tool_name"] == "failing_tool"
    assert entry["failed"] is True


def test_does_not_log_raw_query_text(caplog):
    """Privacy invariant: query length is recorded, not the query itself."""
    caplog.set_level(logging.INFO, logger="ambient-advantage-mcp.tool")
    sensitive = "PwC engagement with ACME Corp on transformation strategy"

    async def go():
        async with tool_logging.tool_call_logger(
            "search_briefings", query_len=len(sensitive),
        ) as info:
            info["result_count"] = 0

    _run(go())
    raw = caplog.records[-1].getMessage()
    assert "ACME" not in raw
    assert "PwC engagement" not in raw
    assert "query_len" in raw
    # The recorded length is what we passed.
    entry = json.loads(raw)
    assert entry["query_len"] == len(sensitive)


def test_yielded_info_dict_defaults_result_count_to_zero(caplog):
    caplog.set_level(logging.INFO, logger="ambient-advantage-mcp.tool")

    async def go():
        async with tool_logging.tool_call_logger("noop"):
            pass  # don't set result_count

    _run(go())
    entry = _parse_log_lines(caplog)[0]
    assert entry["result_count"] == 0
