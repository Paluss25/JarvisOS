"""End-to-end tests for the receiver-side restart-safety drain.

Simulates the scenario: a sender publishes an async A2A request, then the
receiver crashes mid-processing. On startup, the receiver scans for stale
pending entries addressed to it and emits explicit error responses so the
sender's continuation can fire with a clear failure message instead of
waiting up to 24h for TTL expiry.

These tests exercise ``PendingResponseStore.scan_stale`` directly (mirroring
the lifespan helper in ``app.py``) and the ``a2a_dead_letter.py`` CLI flows
against a real Redis instance.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from agent_runner.comms.message import A2AMessage
from agent_runner.comms.pending_store import PendingEntry, PendingResponseStore

REDIS_URL = os.environ.get(
    "PENDING_STORE_TEST_REDIS_URL", "redis://127.0.0.1:6379/13"
)
REDIS_PASSWORD = os.environ.get("PENDING_STORE_TEST_REDIS_PASSWORD")

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "a2a_dead_letter.py"
)


@pytest_asyncio.fixture
async def redis_client():
    kwargs = {"decode_responses": True}
    if REDIS_PASSWORD:
        kwargs["password"] = REDIS_PASSWORD
    base = REDIS_URL.rsplit("/", 1)[0]
    client = aioredis.from_url(f"{base}/13", **kwargs)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def store(redis_client):
    return PendingResponseStore(redis_client, default_ttl_s=60)


# ---------- Stale-pending startup scan ---------------------------------------


@pytest.mark.asyncio
async def test_startup_scan_emits_error_for_stale_request(store, redis_client):
    """Two pending requests addressed to 'cio' — one stale, one fresh.
    The startup scan publishes an error response only for the stale one."""
    now = time.time()
    # Stale: 600s old (older than the 300s cutoff used by the lifespan).
    await store.put(PendingEntry(
        correlation_id="stale-cid",
        from_agent="ceo", to_agent="cio",
        original_message="long task",
        sent_at=now - 600,
        mode="async", root_correlation_id="stale-cid",
        hop_count=1, max_hops=5,
    ))
    # Fresh: 30s old — must NOT be drained.
    await store.put(PendingEntry(
        correlation_id="fresh-cid",
        from_agent="ceo", to_agent="cio",
        original_message="quick task",
        sent_at=now - 30,
        mode="async", root_correlation_id="fresh-cid",
        hop_count=1, max_hops=5,
    ))

    # Mirror the lifespan logic.
    stale = await store.scan_stale(agent_id="cio", older_than_s=300.0)
    assert {e.correlation_id for e in stale} == {"stale-cid"}

    # Build + publish (smoke — we re-read the published payload via pub/sub
    # subscription).
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("a2a:ceo")
    try:
        for entry in stale:
            err = A2AMessage(
                from_agent="cio", to_agent=entry.from_agent,
                type="response",
                payload=(
                    f"[ERROR: receiver 'cio' restarted while processing "
                    f"— request dropped at startup scan. "
                    f"cid={entry.correlation_id[:8]}]"
                ),
                correlation_id=entry.correlation_id,
            )
            from dataclasses import asdict
            await redis_client.publish("a2a:ceo", json.dumps(asdict(err)))

        # Pull the message off the channel.
        # Skip the initial subscription confirmation message.
        for _ in range(5):
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=2.0
            )
            if msg is not None:
                break
        assert msg is not None, "no error response received"
        body = json.loads(msg["data"])
        assert body["correlation_id"] == "stale-cid"
        assert body["type"] == "response"
        assert "[ERROR: receiver 'cio' restarted" in body["payload"]
        assert "cid=stale-ci" in body["payload"]
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()


@pytest.mark.asyncio
async def test_startup_scan_no_op_when_only_fresh_pending(store):
    now = time.time()
    await store.put(PendingEntry(
        correlation_id="fresh",
        from_agent="ceo", to_agent="cio",
        original_message="x",
        sent_at=now - 5,
        mode="async", root_correlation_id="fresh",
        hop_count=1, max_hops=5,
    ))
    stale = await store.scan_stale(agent_id="cio", older_than_s=300.0)
    assert stale == []


@pytest.mark.asyncio
async def test_startup_scan_filters_by_to_agent(store):
    now = time.time()
    await store.put(PendingEntry(
        correlation_id="other-agent",
        from_agent="ceo", to_agent="cos",
        original_message="x",
        sent_at=now - 600,
        mode="async", root_correlation_id="other-agent",
        hop_count=1, max_hops=5,
    ))
    # Scanning as 'cio' must NOT see entries addressed to 'cos'.
    stale = await store.scan_stale(agent_id="cio", older_than_s=300.0)
    assert stale == []


# ---------- a2a_dead_letter.py CLI -------------------------------------------


def _cli_env() -> dict:
    env = os.environ.copy()
    base = REDIS_URL.rsplit("/", 1)[0]
    env["REDIS_URL"] = f"{base}/13"
    if REDIS_PASSWORD:
        env["REDIS_PASSWORD"] = REDIS_PASSWORD
    return env


@pytest.mark.asyncio
async def test_cli_list_count_drain_round_trip(redis_client):
    # Seed 2 entries.
    for cid, sender, payload in [
        ("cid-a", "cio", "[a2a-retry=2] reply A"),
        ("cid-b", "dos", "[a2a-retry=2] reply B"),
    ]:
        env = {
            "from_agent": sender, "to_agent": "ceo",
            "type": "notification", "payload": payload,
            "correlation_id": cid,
            "timestamp": "2026-05-03T10:00:00", "id": f"id-{cid}",
            "mode": "async", "root_correlation_id": cid,
            "parent_correlation_id": cid, "hop_count": 1, "max_hops": 5,
        }
        await redis_client.lpush("a2a:dead-letter:ceo", json.dumps(env))

    # count → 2
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "count", "ceo"],
        env=_cli_env(), capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "2"

    # list → both cids visible
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "list", "ceo"],
        env=_cli_env(), capture_output=True, text=True, check=True,
    )
    assert "cid=cid-a" in out.stdout
    assert "cid=cid-b" in out.stdout
    assert "[0]" in out.stdout and "[1]" in out.stdout

    # drain → empty
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "drain", "ceo"],
        env=_cli_env(), capture_output=True, text=True, check=True,
    )
    assert "cleared" in out.stdout
    assert await redis_client.llen("a2a:dead-letter:ceo") == 0


@pytest.mark.asyncio
async def test_cli_requeue_strips_retry_marker_and_moves_to_inbox(redis_client):
    env = {
        "from_agent": "cio", "to_agent": "ceo",
        "type": "notification",
        "payload": "[a2a-retry=2] Original continuation",
        "correlation_id": "cid-x",
        "timestamp": "2026-05-03T10:00:00", "id": "id-x",
        "mode": "async", "root_correlation_id": "cid-x",
        "parent_correlation_id": "cid-x", "hop_count": 1, "max_hops": 5,
    }
    await redis_client.lpush("a2a:dead-letter:ceo", json.dumps(env))

    out = subprocess.run(
        [sys.executable, str(SCRIPT), "requeue", "ceo", "0"],
        env=_cli_env(), capture_output=True, text=True, check=True,
    )
    assert "Requeued entry #0" in out.stdout

    # Dead-letter is empty; inbox has the entry without the retry marker.
    assert await redis_client.llen("a2a:dead-letter:ceo") == 0
    raw = await redis_client.lrange("a2a:inbox:ceo", 0, -1)
    assert len(raw) == 1
    decoded = json.loads(raw[0])
    assert decoded["correlation_id"] == "cid-x"
    assert decoded["payload"] == "Original continuation"


@pytest.mark.asyncio
async def test_cli_requeue_out_of_range_returns_error(redis_client):
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "requeue", "ceo", "0"],
        env=_cli_env(), capture_output=True, text=True,
    )
    assert out.returncode == 1
    assert "empty" in out.stderr.lower()
