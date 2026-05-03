"""Unit tests for InboxQueue retry counter + dead-letter helpers.

Run with: pytest tests/test_inbox_retry.py -v

Requires a running Redis (jarvios-redis on 127.0.0.1:6379 by default). Tests
use DB 14 to avoid colliding with the production data and the pending-store
test DB 15.
"""

import json
import os
import time

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from agent_runner.comms.inbox import InboxQueue
from agent_runner.comms.message import A2AMessage

REDIS_URL = os.environ.get(
    "PENDING_STORE_TEST_REDIS_URL", "redis://127.0.0.1:6379/14"
)
REDIS_PASSWORD = os.environ.get("PENDING_STORE_TEST_REDIS_PASSWORD")


@pytest_asyncio.fixture
async def redis_client():
    kwargs = {"decode_responses": True}
    if REDIS_PASSWORD:
        kwargs["password"] = REDIS_PASSWORD
    # Override db to 14 to keep this suite isolated from the pending-store
    # tests (which use db 15).
    base = REDIS_URL.rsplit("/", 1)[0]
    client = aioredis.from_url(f"{base}/14", **kwargs)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def inbox(redis_client):
    return InboxQueue("ceo", redis_client)


def _msg(payload: str, cid: str = "abc12345") -> A2AMessage:
    return A2AMessage(
        from_agent="cio",
        to_agent="ceo",
        type="notification",
        payload=payload,
        correlation_id=cid,
        mode="async",
        root_correlation_id=cid,
        parent_correlation_id=cid,
        hop_count=1,
    )


@pytest.mark.asyncio
async def test_requeue_first_attempt_stamps_retry_1(inbox):
    msg = _msg("Original payload")
    requeued = await inbox.requeue_with_retry(msg, max_retries=2)
    assert requeued is True
    drained = await inbox.drain()
    assert len(drained) == 1
    assert drained[0].payload == "[a2a-retry=1] Original payload"
    # Other envelope fields are preserved bit-for-bit.
    assert drained[0].correlation_id == msg.correlation_id
    assert drained[0].hop_count == msg.hop_count
    assert drained[0].mode == "async"


@pytest.mark.asyncio
async def test_requeue_increments_existing_counter(inbox):
    msg = _msg("[a2a-retry=1] Original payload")
    requeued = await inbox.requeue_with_retry(msg, max_retries=2)
    assert requeued is True
    drained = await inbox.drain()
    assert drained[0].payload == "[a2a-retry=2] Original payload"


@pytest.mark.asyncio
async def test_requeue_returns_false_when_cap_reached(inbox):
    msg = _msg("[a2a-retry=2] Original payload")
    requeued = await inbox.requeue_with_retry(msg, max_retries=2)
    assert requeued is False
    # Nothing pushed to the inbox when the cap is hit.
    assert await inbox.length() == 0


@pytest.mark.asyncio
async def test_dead_letter_moves_to_dedicated_list(inbox, redis_client):
    msg = _msg("Failed continuation")
    new_len = await inbox.dead_letter(msg)
    assert new_len == 1
    # Stored under a:2a:dead-letter:<agent_id>, NOT in the regular inbox.
    assert await inbox.length() == 0
    raw = await redis_client.lrange("a2a:dead-letter:ceo", 0, -1)
    assert len(raw) == 1
    decoded = json.loads(raw[0])
    assert decoded["correlation_id"] == msg.correlation_id
    assert decoded["payload"] == "Failed continuation"


@pytest.mark.asyncio
async def test_requeue_then_drain_then_dead_letter_full_cycle(inbox, redis_client):
    """Simulate: 3 failed turns → requeue, requeue, dead-letter."""
    msg = _msg("Continuation reply")

    # Failure 1
    assert await inbox.requeue_with_retry(msg, max_retries=2) is True
    drained = await inbox.drain()
    assert drained[0].payload == "[a2a-retry=1] Continuation reply"

    # Failure 2
    assert await inbox.requeue_with_retry(drained[0], max_retries=2) is True
    drained = await inbox.drain()
    assert drained[0].payload == "[a2a-retry=2] Continuation reply"

    # Failure 3 — cap hit; caller should dead-letter.
    assert await inbox.requeue_with_retry(drained[0], max_retries=2) is False
    await inbox.dead_letter(drained[0])
    raw = await redis_client.lrange("a2a:dead-letter:ceo", 0, -1)
    assert len(raw) == 1
    decoded = json.loads(raw[0])
    assert decoded["payload"] == "[a2a-retry=2] Continuation reply"


@pytest.mark.asyncio
async def test_requeue_handles_malformed_marker_as_retry_zero(inbox):
    # A payload that *looks* like a marker but isn't parseable cleanly.
    msg = _msg("[a2a-retry=NOPE] payload")
    assert await inbox.requeue_with_retry(msg, max_retries=2) is True
    drained = await inbox.drain()
    # Falls back to retry 1 with the original payload preserved.
    assert drained[0].payload == "[a2a-retry=1] [a2a-retry=NOPE] payload"


@pytest.mark.asyncio
async def test_drain_strips_unknown_envelope_fields(inbox, redis_client):
    """A future writer that adds a field shouldn't crash an older reader."""
    forward_compat = {
        "from_agent": "cio",
        "to_agent": "ceo",
        "type": "notification",
        "payload": "hello future",
        "id": "fid-1",
        "correlation_id": "fcid-1",
        "timestamp": "2026-05-03T10:00:00",
        "mode": "async",
        "root_correlation_id": None,
        "parent_correlation_id": None,
        "hop_count": 0,
        "max_hops": 5,
        # Hypothetical new field added in a later version.
        "future_only_field": "boom",
    }
    await redis_client.lpush(
        "a2a:inbox:ceo", json.dumps(forward_compat)
    )
    drained = await inbox.drain()
    assert len(drained) == 1
    assert drained[0].payload == "hello future"
