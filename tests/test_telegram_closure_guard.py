import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_runner.interfaces.telegram_bot import _stream_to_agent


class FakeAgent:
    def __init__(self, chunks, stats):
        self.chunks = chunks
        self.stats = stats

    async def stream(self, text, session_id=None):
        for chunk in self.chunks:
            yield chunk

    def get_last_turn_stats(self):
        return dict(self.stats)


def _telegram_context(agent):
    config = SimpleNamespace(
        id="cio",
        telegram_streaming_mode="off",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
        budget=None,
    )
    return SimpleNamespace(
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
        bot_data={
            "agent": agent,
            "session_manager": None,
            "config": config,
            "redis_a2a": None,
        },
    )


def _telegram_update(chat_id=1234):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_stream_to_agent_replaces_stale_tool_failure_with_closure_notice():
    agent = FakeAgent(
        chunks=["Tool failed: Read\nFile does not exist."],
        stats={"tool_calls": 7, "mutating_tool_calls": 2, "last_tool_name": "daily_log"},
    )
    update = _telegram_update()

    await _stream_to_agent(update, _telegram_context(agent), "aggiorna i prompt MT")

    sent_text = update.message.reply_text.await_args_list[-1].args[0]
    assert "Turno concluso senza riepilogo finale" in sent_text
    assert "tool eseguiti: 7" in sent_text
    assert "daily_log" in sent_text
    assert "Tool failed: Read" not in sent_text


@pytest.mark.asyncio
async def test_stream_to_agent_keeps_normal_final_response_after_tools():
    agent = FakeAgent(
        chunks=["Tutto fatto: SOUL.md e TOOLS.md aggiornati."],
        stats={"tool_calls": 5, "mutating_tool_calls": 2, "last_tool_name": "daily_log"},
    )
    update = _telegram_update()

    await _stream_to_agent(update, _telegram_context(agent), "aggiorna i prompt MT")

    sent_text = update.message.reply_text.await_args_list[-1].args[0]
    assert sent_text == "Tutto fatto: SOUL.md e TOOLS.md aggiornati."


@pytest.mark.asyncio
async def test_stream_to_agent_replaces_pre_tool_progress_without_final_response():
    agent = FakeAgent(
        chunks=["Re-verifico ora, con prova fresca e controllo schema."],
        stats={
            "tool_calls": 4,
            "mutating_tool_calls": 1,
            "last_tool_name": "send_message",
            "text_after_last_tool_chars": 0,
        },
    )
    update = _telegram_update()

    await _stream_to_agent(update, _telegram_context(agent), "hai verificato?")

    sent_text = update.message.reply_text.await_args_list[-1].args[0]
    assert "Turno concluso senza riepilogo finale" in sent_text
    assert "send_message" in sent_text
    assert "Re-verifico ora" not in sent_text
