"""Unit tests for send_telegram_message — the originator-authored Telegram
feedback tool that closes the loop after an async A2A delegation.

Hardened per Codex review 2026-05-03:
- 4 refusal modes (no chain context / wrong channel / wrong chat_id / idempotency)
- 3 send paths (markdown OK / markdown→plain fallback / RetryAfter backoff)
- Send-failure releases the idempotency lock for operator-driven retry
- Truncation preserves the 4000-char Telegram budget

Run with: pytest tests/test_send_telegram_message.py -v

Requires a running Redis (jarvios-redis container on 127.0.0.1:6379 by default)
on DB index 13 (dedicated to feedback-loop tests, flushed before/after).
"""

import asyncio
import os
from unittest.mock import patch

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from telegram.error import BadRequest, RetryAfter

from agent_runner.comms.chain_context import set_chain_context, reset_chain_context
from agent_runner.config import AgentConfig
from agent_runner.tools.send_telegram_message import create_send_telegram_message_tool

REDIS_URL = os.environ.get(
    "FEEDBACK_LOOP_TEST_REDIS_URL", "redis://127.0.0.1:6379/13"
)
REDIS_PASSWORD = os.environ.get("FEEDBACK_LOOP_TEST_REDIS_PASSWORD")

ALLOWED_CHAT_ID = "7218812451"
TEST_TOKEN = "0000000000:fake-token-for-tests"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture
def fake_redis_a2a(redis_client):
    """Minimal stand-in for RedisA2A — only ``.client`` is used by the tool."""
    class _RA2A:
        pass
    ra = _RA2A()
    ra.client = redis_client
    return ra


@pytest.fixture
def config(monkeypatch):
    """Per-agent config with TELEGRAM_TEST_TOKEN + TELEGRAM_TEST_CHAT_ID set."""
    monkeypatch.setenv("TELEGRAM_TEST_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("TELEGRAM_TEST_CHAT_ID", ALLOWED_CHAT_ID)
    from pathlib import Path
    return AgentConfig(
        id="testagent",
        name="TestAgent",
        port=9999,
        workspace_path=Path("/tmp/testagent"),
        telegram_token_env="TELEGRAM_TEST_TOKEN",
        telegram_chat_id_env="TELEGRAM_TEST_CHAT_ID",
        env_prefix="",
    )


@pytest.fixture
def tool(config, fake_redis_a2a):
    return create_send_telegram_message_tool(config, fake_redis_a2a)


def _set_chain(reply_channel="telegram", reply_chat_id=ALLOWED_CHAT_ID,
               reply_intent="test_intent", parent_cid="parent-abc"):
    """Helper: install a chain context for the current task."""
    return set_chain_context({
        "root_correlation_id": "root-xyz",
        "parent_correlation_id": parent_cid,
        "hop_count": 1,
        "reply_channel": reply_channel,
        "reply_chat_id": reply_chat_id,
        "reply_intent": reply_intent,
    })


# ---------------------------------------------------------------------------
# Refusal #1: no chain context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refuses_without_chain_context(tool):
    with patch("agent_runner.tools.send_telegram_message.Bot") as MockBot:
        out = await tool({"text": "hello"})
    assert "not in an A2A continuation turn" in out
    MockBot.assert_not_called()


# ---------------------------------------------------------------------------
# Refusal #2: wrong reply_channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refuses_when_reply_channel_not_telegram(tool):
    token = _set_chain(reply_channel="cron", reply_chat_id=None)
    try:
        with patch("agent_runner.tools.send_telegram_message.Bot") as MockBot:
            out = await tool({"text": "hello"})
    finally:
        reset_chain_context(token)
    assert "no Telegram origin" in out
    assert "reply_channel='cron'" in out
    MockBot.assert_not_called()


# ---------------------------------------------------------------------------
# Refusal #3: chat_id mismatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refuses_when_chat_id_mismatch(tool):
    token = _set_chain(reply_chat_id="9999999")
    try:
        with patch("agent_runner.tools.send_telegram_message.Bot") as MockBot:
            out = await tool({"text": "hello"})
    finally:
        reset_chain_context(token)
    assert "does not match this agent's allowed chat id" in out
    MockBot.assert_not_called()


# ---------------------------------------------------------------------------
# Refusal #4: idempotency lock already held
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refuses_when_idempotency_key_already_set(tool, redis_client):
    # Pre-claim the key — simulates a prior send (or a duplicated drain).
    await redis_client.set("a2a:feedback-sent:dup-cid", "1", nx=True, ex=3600)
    token = _set_chain(parent_cid="dup-cid")
    try:
        with patch("agent_runner.tools.send_telegram_message.Bot") as MockBot:
            out = await tool({"text": "hello"})
    finally:
        reset_chain_context(token)
    assert "already sent" in out
    assert "idempotency guard" in out
    MockBot.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path: markdown send succeeds, idempotency key persists
# ---------------------------------------------------------------------------


class _FakeBot:
    """Async context-manager fake matching python-telegram-bot 22.x."""
    def __init__(self, *, send_side_effects=None):
        # ``send_side_effects`` is a list of either None (success) or an
        # exception instance. Calls are popped from the head; if empty, success.
        self.send_calls = []
        self._side_effects = list(send_side_effects or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send_message(self, **kwargs):
        self.send_calls.append(kwargs)
        if self._side_effects:
            effect = self._side_effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect


@pytest.mark.asyncio
async def test_happy_path_markdown(tool, redis_client):
    fake = _FakeBot()
    token = _set_chain(parent_cid="happy-cid")
    try:
        with patch("agent_runner.tools.send_telegram_message.Bot",
                   return_value=fake):
            out = await tool({"text": "ciao **mondo**"})
    finally:
        reset_chain_context(token)
    assert "Telegram message sent to chat 7218812451" in out
    assert "markdown" in out
    assert len(fake.send_calls) == 1
    assert fake.send_calls[0]["chat_id"] == 7218812451
    # Idempotency key remains set on success.
    assert await redis_client.get("a2a:feedback-sent:happy-cid") == "1"


# ---------------------------------------------------------------------------
# Markdown → plain-text fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_markdown_then_plain_text_fallback(tool, redis_client):
    fake = _FakeBot(send_side_effects=[BadRequest("can't parse entities"), None])
    token = _set_chain(parent_cid="fallback-cid")
    try:
        with patch("agent_runner.tools.send_telegram_message.Bot",
                   return_value=fake):
            out = await tool({"text": "ciao [bad markdown"})
    finally:
        reset_chain_context(token)
    assert "plain text fallback" in out
    assert len(fake.send_calls) == 2
    # Second call must NOT pass parse_mode.
    assert "parse_mode" not in fake.send_calls[1]
    assert await redis_client.get("a2a:feedback-sent:fallback-cid") == "1"


# ---------------------------------------------------------------------------
# RetryAfter backoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_after_backoff(tool, redis_client):
    fake = _FakeBot(send_side_effects=[RetryAfter(retry_after=3), None])
    token = _set_chain(parent_cid="retry-cid")
    sleep_calls: list[float] = []

    async def _fake_sleep(delay):
        sleep_calls.append(delay)

    try:
        with patch("agent_runner.tools.send_telegram_message.Bot",
                   return_value=fake), \
             patch("agent_runner.tools.send_telegram_message.asyncio.sleep",
                   _fake_sleep):
            out = await tool({"text": "rate-limited"})
    finally:
        reset_chain_context(token)
    assert "after 3s rate-limit wait" in out
    # asyncio.sleep was called with the bounded retry-after value.
    assert sleep_calls and sleep_calls[0] == 3.0
    assert len(fake.send_calls) == 2
    assert await redis_client.get("a2a:feedback-sent:retry-cid") == "1"


# ---------------------------------------------------------------------------
# Send failure releases the idempotency lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_failure_releases_idempotency_lock(tool, redis_client):
    fake = _FakeBot(send_side_effects=[RuntimeError("network down")])
    token = _set_chain(parent_cid="failure-cid")
    try:
        with patch("agent_runner.tools.send_telegram_message.Bot",
                   return_value=fake):
            out = await tool({"text": "hello"})
    finally:
        reset_chain_context(token)
    assert out.startswith("Error: telegram send failed:")
    # The lock must be released so a future retry can succeed.
    assert await redis_client.get("a2a:feedback-sent:failure-cid") is None


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_truncation_to_4000_chars(tool):
    fake = _FakeBot()
    token = _set_chain(parent_cid="truncate-cid")
    try:
        with patch("agent_runner.tools.send_telegram_message.Bot",
                   return_value=fake):
            await tool({"text": "x" * 5000})
    finally:
        reset_chain_context(token)
    assert len(fake.send_calls) == 1
    sent = fake.send_calls[0]["text"]
    assert len(sent) <= 4000
    assert sent.endswith("…")


# ---------------------------------------------------------------------------
# Missing token (env unset)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refuses_when_token_env_unset(monkeypatch, fake_redis_a2a, redis_client):
    monkeypatch.delenv("TELEGRAM_TEST_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_TEST_CHAT_ID", ALLOWED_CHAT_ID)
    from pathlib import Path
    cfg = AgentConfig(
        id="noTok", name="NoTok", port=9998,
        workspace_path=Path("/tmp/notok"),
        telegram_token_env="TELEGRAM_TEST_TOKEN",
        telegram_chat_id_env="TELEGRAM_TEST_CHAT_ID",
        env_prefix="",
    )
    tool = create_send_telegram_message_tool(cfg, fake_redis_a2a)
    token = _set_chain(parent_cid="no-tok-cid")
    try:
        with patch("agent_runner.tools.send_telegram_message.Bot") as MockBot:
            out = await tool({"text": "hello"})
    finally:
        reset_chain_context(token)
    assert "telegram token env" in out and "is not set" in out
    MockBot.assert_not_called()
    # Lock must have been released so a future retry can succeed.
    assert await redis_client.get("a2a:feedback-sent:no-tok-cid") is None
