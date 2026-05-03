"""Unit tests for PendingResponseStore.

Run with: pytest tests/test_pending_store.py -v

Requires a running Redis (jarvios-redis container on 127.0.0.1:6379 by default).
Tests use a dedicated DB index (15) to avoid colliding with production state
and flush it before/after each test.
"""

import asyncio
import os
import time

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from agent_runner.comms.pending_store import PendingEntry, PendingResponseStore

REDIS_URL = os.environ.get(
    "PENDING_STORE_TEST_REDIS_URL", "redis://127.0.0.1:6379/15"
)
# Password is supplied separately so the URL doesn't have to URL-encode chars
# like "/" / "+" / "=" common in randomly-generated secrets.
REDIS_PASSWORD = os.environ.get("PENDING_STORE_TEST_REDIS_PASSWORD")


@pytest_asyncio.fixture
async def redis_client():
    kwargs = {"decode_responses": True}
    if REDIS_PASSWORD:
        kwargs["password"] = REDIS_PASSWORD
    client = aioredis.from_url(REDIS_URL, **kwargs)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def store(redis_client):
    return PendingResponseStore(redis_client, default_ttl_s=60)


def _entry(cid: str = "abc123", **overrides) -> PendingEntry:
    base = dict(
        correlation_id=cid,
        from_agent="ceo",
        to_agent="cio",
        original_message="build the WHOOP CLI tool",
        sent_at=time.time(),
        mode="async",
        root_correlation_id=cid,
        hop_count=1,
        max_hops=5,
        sender_session_id=None,
        sender_user_id=None,
        context_hint="testing",
    )
    base.update(overrides)
    return PendingEntry(**base)


@pytest.mark.asyncio
async def test_put_and_claim_happy_path(store):
    e = _entry()
    await store.put(e)
    claimed = await store.claim(e.correlation_id)
    assert claimed is not None
    assert claimed.correlation_id == e.correlation_id
    assert claimed.from_agent == "ceo"
    assert claimed.to_agent == "cio"
    assert claimed.original_message == "build the WHOOP CLI tool"
    assert claimed.mode == "async"
    assert claimed.hop_count == 1
    assert claimed.max_hops == 5
    assert claimed.context_hint == "testing"
    # sender_*_id were None on write — must come back as None, not "" or "None".
    assert claimed.sender_session_id is None
    assert claimed.sender_user_id is None


@pytest.mark.asyncio
async def test_claim_missing_returns_none(store):
    assert await store.claim("does-not-exist") is None


@pytest.mark.asyncio
async def test_claim_is_idempotent_only_one_winner(store):
    e = _entry(cid="race-test")
    await store.put(e)

    # Two concurrent claims — only one returns the entry.
    results = await asyncio.gather(
        store.claim(e.correlation_id),
        store.claim(e.correlation_id),
    )
    populated = [r for r in results if r is not None]
    nulled = [r for r in results if r is None]
    assert len(populated) == 1
    assert len(nulled) == 1


@pytest.mark.asyncio
async def test_ttl_expiry(redis_client):
    short_ttl_store = PendingResponseStore(redis_client, default_ttl_s=1)
    e = _entry(cid="expires-fast")
    await short_ttl_store.put(e)
    # Confirm written
    assert await short_ttl_store.peek(e.correlation_id) is not None
    # Wait for TTL to lapse + a small grace
    await asyncio.sleep(1.5)
    assert await short_ttl_store.peek(e.correlation_id) is None
    assert await short_ttl_store.claim(e.correlation_id) is None


@pytest.mark.asyncio
async def test_scan_stale_filters_by_to_agent_and_age(store):
    now = time.time()
    # Old enough to be stale, addressed to cio.
    await store.put(_entry(cid="stale-1", to_agent="cio", sent_at=now - 600))
    # Old but addressed to a different agent — must NOT match cio scan.
    await store.put(_entry(cid="stale-2", to_agent="cos", sent_at=now - 600))
    # Fresh (within cutoff) — must NOT match.
    await store.put(_entry(cid="fresh-1", to_agent="cio", sent_at=now - 10))

    stale = await store.scan_stale(agent_id="cio", older_than_s=300)
    cids = {e.correlation_id for e in stale}
    assert cids == {"stale-1"}


@pytest.mark.asyncio
async def test_peek_does_not_consume(store):
    e = _entry(cid="peek-test")
    await store.put(e)
    p1 = await store.peek(e.correlation_id)
    p2 = await store.peek(e.correlation_id)
    assert p1 is not None and p2 is not None
    # Claim should still work — peek must not be destructive.
    claimed = await store.claim(e.correlation_id)
    assert claimed is not None
    # After claim, peek returns None.
    assert await store.peek(e.correlation_id) is None


@pytest.mark.asyncio
async def test_delete(store):
    e = _entry(cid="delete-test")
    await store.put(e)
    assert await store.delete(e.correlation_id) is True
    assert await store.peek(e.correlation_id) is None
    # Deleting a missing key returns False.
    assert await store.delete("not-there") is False


@pytest.mark.asyncio
async def test_optional_fields_round_trip_with_values(store):
    e = _entry(
        cid="optional-fields",
        sender_session_id="sess-123",
        sender_user_id="user-42",
        context_hint="some hint with unicode é à 😀",
        root_correlation_id="root-cid",
    )
    await store.put(e)
    claimed = await store.claim(e.correlation_id)
    assert claimed is not None
    assert claimed.sender_session_id == "sess-123"
    assert claimed.sender_user_id == "user-42"
    assert claimed.context_hint == "some hint with unicode é à 😀"
    assert claimed.root_correlation_id == "root-cid"
