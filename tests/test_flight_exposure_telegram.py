from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runner.interfaces import telegram_bot


class FakeMessage:
    def __init__(self):
        self.reply_text = AsyncMock()


class FakeUpdate:
    def __init__(self, chat_id=123):
        self.effective_chat = MagicMock(id=chat_id)
        self.message = FakeMessage()


class FakeConfig:
    id = "coh"
    telegram_chat_id_env = "TELEGRAM_ALLOWED_CHAT_ID"


class FakeContext:
    def __init__(self, args):
        self.args = args
        self.bot_data = {"config": FakeConfig()}


@pytest.mark.asyncio
async def test_decollo_command_streams_to_coh(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "123")
    stream = AsyncMock()
    monkeypatch.setattr(telegram_bot, "_stream_to_agent", stream)

    await telegram_bot._cmd_decollo(FakeUpdate(), FakeContext(["11:30", "M-346", "Handling", "Qualities"]))

    stream.assert_awaited_once()
    assert "flight_takeoff" in stream.await_args.args[2]
    assert "11:30 M-346 Handling Qualities" in stream.await_args.args[2]


@pytest.mark.asyncio
async def test_atterraggio_command_streams_to_coh(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "123")
    stream = AsyncMock()
    monkeypatch.setattr(telegram_bot, "_stream_to_agent", stream)

    await telegram_bot._cmd_atterraggio(FakeUpdate(), FakeContext(["12:30", "LIRE"]))

    stream.assert_awaited_once()
    assert "flight_landing" in stream.await_args.args[2]
    assert "12:30 LIRE" in stream.await_args.args[2]
