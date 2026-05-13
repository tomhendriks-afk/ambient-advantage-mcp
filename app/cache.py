"""In-process TTL cache with request coalescing.

Sits between the tool layer (step 6) and the source adapters (step 3) so
repeated MCP tool invocations for the same content don't hammer the four
content sites. Two properties matter:

  1. **TTL-based expiry.** Each cached entry remembers its absolute expiry
     time; lookups past expiry trigger a fresh fetch. Caller decides the
     TTL per call, so index feeds (5 min) and article bodies (1 hour) can
     share the same cache.

  2. **Concurrent-request coalescing.** If two tool calls request the
     same key while a fetch is already in flight, the second waits on
     the first's result rather than launching a duplicate upstream
     request. Important on cold starts where N requests arrive
     simultaneously before any cache is warm.

Process-local: each Cloud Run instance has its own cache. That's a
deliberate trade-off — coordinating a shared cache across instances would
need Redis/Memcache infra that Phase 1 of the build plan explicitly
avoids. Cloud Run's max-instances=5 with concurrency=80 means worst-case
5x duplication of upstream fetches, which is fine for content sites that
sit behind Cloudflare's own CDN.

Failures are NOT cached. If fetch() raises, the exception is propagated
to every coalesced caller and the in-flight slot is cleared so the next
request retries cleanly.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


# Default TTLs the build plan locks in. Adapters/tools pass these (or
# explicit overrides) into get_or_fetch().
INDEX_TTL_SECONDS = 300        # 5 minutes for briefings.json/articles.json/etc.
ARTICLE_TTL_SECONDS = 3600     # 1 hour for per-article markdown twins


@dataclass
class _Entry:
    value: object
    expires_at: float


_cache: dict[str, _Entry] = {}
_in_flight: dict[str, asyncio.Future] = {}

# Lightweight counters surfaced for the structured-log line in step 6.
_hits = 0
_misses = 0
_coalesced = 0


def _now() -> float:
    """Monotonic time, separated for monkeypatch-based tests."""
    return time.monotonic()


async def get_or_fetch(
    key: str,
    ttl_seconds: float,
    fetch: Callable[[], Awaitable[T]],
) -> T:
    """Return the cached value for `key`, or invoke `fetch()` and cache it.

    Concurrent calls for the same key while a fetch is in flight are
    coalesced onto the in-flight future. Exceptions propagate to every
    waiter and the in-flight slot is cleared so the next call retries.
    """
    global _hits, _misses, _coalesced

    now = _now()

    entry = _cache.get(key)
    if entry is not None and entry.expires_at > now:
        _hits += 1
        return entry.value  # type: ignore[return-value]

    existing = _in_flight.get(key)
    if existing is not None:
        _coalesced += 1
        return await existing

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    _in_flight[key] = future
    _misses += 1
    try:
        value = await fetch()
        _cache[key] = _Entry(value=value, expires_at=_now() + ttl_seconds)
        future.set_result(value)
        return value
    except Exception as exc:
        future.set_exception(exc)
        # If no coalesced waiter arrived, nobody awaits this future, and
        # Python warns "exception was never retrieved" on GC. Mark it as
        # observed here — awaiters that DID coalesce will still see the
        # exception via their await.
        future.exception()
        raise
    finally:
        _in_flight.pop(key, None)


def clear() -> None:
    """Wipe the cache and stats. Useful for tests; not used at runtime."""
    global _hits, _misses, _coalesced
    _cache.clear()
    _in_flight.clear()
    _hits = 0
    _misses = 0
    _coalesced = 0


def stats() -> dict[str, int]:
    """Cumulative hit/miss/coalesce counts since process start (or last clear).

    Wired into the per-tool structured log line in step 6 so we can see
    how warm the cache actually is in production.
    """
    return {
        "entries": len(_cache),
        "in_flight": len(_in_flight),
        "hits": _hits,
        "misses": _misses,
        "coalesced": _coalesced,
    }
