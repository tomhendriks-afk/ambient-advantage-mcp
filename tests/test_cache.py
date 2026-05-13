"""Tests for the in-process TTL cache.

Covers cache hits/misses, TTL expiry (monkeypatched clock), concurrent
coalescing, exception propagation (failed fetches NOT cached), and the
public stats() surface.
"""

from __future__ import annotations

import asyncio
import itertools

import pytest

from app import cache


@pytest.fixture(autouse=True)
def _isolate_cache():
    """Reset module-level state between tests so they don't bleed."""
    cache.clear()
    yield
    cache.clear()


def _run(coro):
    return asyncio.run(coro)


def test_first_call_invokes_fetch_and_caches_value():
    call_count = 0

    async def fetch():
        nonlocal call_count
        call_count += 1
        return "value-1"

    async def go():
        first = await cache.get_or_fetch("k", 60.0, fetch)
        second = await cache.get_or_fetch("k", 60.0, fetch)
        return first, second

    first, second = _run(go())
    assert first == "value-1"
    assert second == "value-1"
    assert call_count == 1, "second call should hit the cache"


def test_stats_track_hits_and_misses():
    async def fetch():
        return "v"

    async def go():
        await cache.get_or_fetch("k", 60.0, fetch)
        await cache.get_or_fetch("k", 60.0, fetch)
        await cache.get_or_fetch("k", 60.0, fetch)

    _run(go())
    s = cache.stats()
    assert s["misses"] == 1
    assert s["hits"] == 2
    assert s["entries"] == 1


def test_expired_entry_triggers_refetch(monkeypatch):
    """After the TTL elapses, the next call must invoke fetch() again."""
    fake_time = itertools.count(start=1000.0, step=1.0)

    def patched_now() -> float:
        return next(fake_time)

    monkeypatch.setattr(cache, "_now", patched_now)

    call_count = 0

    async def fetch():
        nonlocal call_count
        call_count += 1
        return f"value-{call_count}"

    # TTL = 5 "seconds" but our fake clock advances by 1 on each _now() call,
    # which is invoked: at lookup, then at expiry-set, then again on next call,
    # etc. Use a TTL of 2 so two more lookups push us past expiry.
    async def go():
        first = await cache.get_or_fetch("k", 2.0, fetch)
        # Several reads to advance the fake clock past expiry.
        await cache.get_or_fetch("k", 2.0, fetch)
        await cache.get_or_fetch("k", 2.0, fetch)
        third = await cache.get_or_fetch("k", 2.0, fetch)
        return first, third

    first, third = _run(go())
    assert first == "value-1"
    assert call_count >= 2, "expected at least one refetch after TTL elapsed"
    assert third != first or call_count >= 2  # value rotated or refetch happened


def test_different_keys_are_cached_separately():
    async def fetch_a():
        return "A"

    async def fetch_b():
        return "B"

    async def go():
        a = await cache.get_or_fetch("a", 60.0, fetch_a)
        b = await cache.get_or_fetch("b", 60.0, fetch_b)
        a_again = await cache.get_or_fetch("a", 60.0, fetch_a)
        return a, b, a_again

    a, b, a_again = _run(go())
    assert a == "A"
    assert b == "B"
    assert a_again == "A"
    assert cache.stats()["entries"] == 2


def test_concurrent_calls_for_same_key_coalesce_to_one_fetch():
    """The build plan requires stampede protection: N concurrent callers
    on cold cache must yield exactly 1 upstream fetch.
    """
    call_count = 0
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def slow_fetch():
        nonlocal call_count
        call_count += 1
        started.set()
        # Yield control so concurrent waiters can pile on before we resolve.
        await proceed.wait()
        return "value"

    async def go():
        # Kick off 5 concurrent calls; first will start the fetch, the
        # other 4 must coalesce onto it.
        tasks = [
            asyncio.create_task(cache.get_or_fetch("k", 60.0, slow_fetch))
            for _ in range(5)
        ]
        await started.wait()
        # Give all 5 tasks a chance to enter the cache code.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        proceed.set()
        return await asyncio.gather(*tasks)

    results = _run(go())
    assert results == ["value"] * 5
    assert call_count == 1, "coalescing must collapse N concurrent calls into 1 fetch"
    s = cache.stats()
    assert s["misses"] == 1
    assert s["coalesced"] == 4


def test_failed_fetch_is_not_cached_and_exception_propagates():
    """If the upstream errors, the cache must stay empty so the next
    call retries cleanly. Otherwise a transient blip would poison the
    cache for the full TTL.
    """
    call_count = 0

    async def flaky_fetch():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("upstream blip")
        return "value-after-retry"

    async def go():
        with pytest.raises(RuntimeError, match="upstream blip"):
            await cache.get_or_fetch("k", 60.0, flaky_fetch)
        return await cache.get_or_fetch("k", 60.0, flaky_fetch)

    result = _run(go())
    assert result == "value-after-retry"
    assert call_count == 2
    assert cache.stats()["entries"] == 1


def test_failed_fetch_clears_in_flight_slot():
    """After a failed fetch, the in-flight slot must be empty so the
    next caller doesn't await a settled-failed future forever.
    """

    async def failing_fetch():
        raise RuntimeError("nope")

    async def go():
        with pytest.raises(RuntimeError):
            await cache.get_or_fetch("k", 60.0, failing_fetch)
        # in_flight slot should be cleared
        return cache.stats()

    s = _run(go())
    assert s["in_flight"] == 0


def test_coalesced_callers_all_see_the_same_exception():
    """If the in-flight fetch raises, every coalesced waiter sees the
    same exception rather than hanging.
    """
    call_count = 0
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def failing_slow_fetch():
        nonlocal call_count
        call_count += 1
        started.set()
        await proceed.wait()
        raise ValueError("planned failure")

    async def go():
        tasks = [
            asyncio.create_task(cache.get_or_fetch("k", 60.0, failing_slow_fetch))
            for _ in range(3)
        ]
        await started.wait()
        await asyncio.sleep(0)
        proceed.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    results = _run(go())
    assert all(isinstance(r, ValueError) for r in results)
    assert call_count == 1


def test_clear_resets_cache_and_stats():
    async def fetch():
        return "v"

    async def go():
        await cache.get_or_fetch("k", 60.0, fetch)
        await cache.get_or_fetch("k", 60.0, fetch)

    _run(go())
    assert cache.stats()["entries"] == 1
    cache.clear()
    assert cache.stats() == {
        "entries": 0,
        "in_flight": 0,
        "hits": 0,
        "misses": 0,
        "coalesced": 0,
    }


def test_default_ttls_match_build_plan():
    """The constants are the public contract; if these need to change,
    the build plan needs an explicit decision.
    """
    assert cache.INDEX_TTL_SECONDS == 300
    assert cache.ARTICLE_TTL_SECONDS == 3600


def test_cached_value_is_returned_by_reference():
    """The cache doesn't deep-copy. Callers must treat returned values as
    read-only — this test pins that contract.
    """
    payload = {"a": 1}

    async def fetch():
        return payload

    async def go():
        first = await cache.get_or_fetch("k", 60.0, fetch)
        second = await cache.get_or_fetch("k", 60.0, fetch)
        return first, second

    first, second = _run(go())
    assert first is second, "cache returns by reference; mutation contract is read-only"
