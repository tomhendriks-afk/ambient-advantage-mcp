"""Structured-log helper for MCP tool invocations.

§8 of the build plan specifies a single structured log line per tool call:

    {tool_name, query_len, result_count, upstream_latency_ms,
     total_latency_ms, cache_hit}

We deliberately do NOT log raw query bodies — some agent queries will
include sensitive context (client names, internal projects). Length-only
is enough for observability without the privacy risk.

The MCPToolLogger context manager handles the bookkeeping (timing,
cache stats) so each tool function only declares what it knows
(query_len up front, result_count once the call returns).
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from . import cache


log = logging.getLogger("ambient-advantage-mcp.tool")


@asynccontextmanager
async def tool_call_logger(
    tool_name: str,
    *,
    query_len: int = 0,
) -> AsyncIterator[dict]:
    """Wrap a tool body and emit one structured log line on exit.

    Usage::

        async def search_briefings(query: str, limit: int = 10):
            async with tool_call_logger(
                "search_briefings", query_len=len(query),
            ) as info:
                results = await ...
                info["result_count"] = len(results)
                return results

    The yielded dict is mutable so the tool can record the result count
    once it has one. cache_hit is computed automatically from the cache
    miss counter delta — if no fresh fetch was performed during the
    tool body, every value was served from cache.

    Failures: if the tool raises, the structured log line is still
    emitted with whatever info was set, plus a "failed" flag, so the
    metric is preserved.
    """
    start = time.monotonic()
    pre_misses = cache.stats()["misses"]
    info: dict = {"result_count": 0}
    failed = False
    try:
        yield info
    except Exception:
        failed = True
        raise
    finally:
        total_ms = int((time.monotonic() - start) * 1000)
        post_misses = cache.stats()["misses"]
        cache_hit = post_misses == pre_misses
        log.info(json.dumps({
            "event": "tool_call",
            "tool_name": tool_name,
            "query_len": query_len,
            "result_count": info.get("result_count", 0),
            "total_latency_ms": total_ms,
            "cache_hit": cache_hit,
            "failed": failed,
        }))
