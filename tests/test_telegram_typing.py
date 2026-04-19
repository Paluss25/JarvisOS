"""Tests for the two-task Telegram typing animation."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import os

# Add src/ to path so agent_runner module can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from agent_runner.interfaces.telegram_bot import (
    _typing_keepalive_task,
    _run_status_task,
    _TYPING_RENEW_INTERVAL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ph_mock():
    """Fresh permission_hook mock for each test."""
    mock = MagicMock()
    mock.get_active_tool = MagicMock(return_value="")
    with patch.dict(sys.modules, {
        "agent_runner.hooks.permission_hook": mock,
        "agent_runner.hooks": MagicMock(permission_hook=mock),
    }):
        yield mock


# ---------------------------------------------------------------------------
# _typing_keepalive_task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_keepalive_calls_send_chat_action():
    """Keepalive must call send_chat_action at least once before state["done"] is set."""
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    state = {"done": False}

    async def _stop_after_first_call(*args, **kwargs):
        state["done"] = True

    bot.send_chat_action.side_effect = _stop_after_first_call

    await _typing_keepalive_task(bot, chat_id=123, state=state)

    bot.send_chat_action.assert_awaited_once_with(chat_id=123, action="typing")


@pytest.mark.asyncio
async def test_keepalive_exits_when_done_is_set():
    """Keepalive must exit its loop when state["done"] becomes True."""
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    state = {"done": True}  # already done before task starts

    # Should return immediately without calling send_chat_action
    await asyncio.wait_for(_typing_keepalive_task(bot, chat_id=123, state=state), timeout=1.0)

    bot.send_chat_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_keepalive_survives_send_chat_action_error():
    """Keepalive must not crash when send_chat_action raises."""
    bot = MagicMock()
    call_count = 0

    async def _fail_then_stop(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("network error")
        state["done"] = True

    bot.send_chat_action = AsyncMock(side_effect=_fail_then_stop)
    state = {"done": False}

    await asyncio.wait_for(_typing_keepalive_task(bot, chat_id=123, state=state), timeout=5.0)

    assert call_count == 2  # retried after error


@pytest.mark.asyncio
async def test_keepalive_cancellable():
    """Keepalive task must be cancellable without hanging."""
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    state = {"done": False}

    task = asyncio.create_task(_typing_keepalive_task(bot, chat_id=123, state=state))
    await asyncio.sleep(0)  # let task start
    task.cancel()
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=1.0)
    # No assertion — just verify no hang/error


# ---------------------------------------------------------------------------
# _run_status_task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_task_edits_placeholder(ph_mock):
    """Status task must call placeholder.edit_text at least once."""
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    placeholder = MagicMock()
    state = {"text": "", "done": False}

    async def _stop_after_first_edit(*args, **kwargs):
        state["done"] = True

    placeholder.edit_text = AsyncMock(side_effect=_stop_after_first_edit)

    await _run_status_task(bot, chat_id=123, placeholder=placeholder, state=state)

    placeholder.edit_text.assert_awaited_once()
    # Must not contain the cursor when text is empty
    call_args = placeholder.edit_text.call_args[0][0]
    assert " ▌" not in call_args  # cursor must not appear when text is empty


@pytest.mark.asyncio
async def test_status_task_shows_cursor_during_streaming(ph_mock):
    """Status task must append ' ▌' to partial text when no active tool."""
    bot = MagicMock()
    placeholder = MagicMock()
    state = {"text": "Partial response so far", "done": False}

    async def _stop_after_first_edit(*args, **kwargs):
        state["done"] = True

    placeholder.edit_text = AsyncMock(side_effect=_stop_after_first_edit)

    await _run_status_task(bot, chat_id=123, placeholder=placeholder, state=state)

    call_args = placeholder.edit_text.call_args[0][0]
    assert call_args.endswith(" ▌")


@pytest.mark.asyncio
async def test_status_task_exits_when_done_is_set(ph_mock):
    """Status task must exit immediately when state["done"] is already True."""
    bot = MagicMock()
    placeholder = MagicMock()
    placeholder.edit_text = AsyncMock()
    state = {"text": "", "done": True}

    await asyncio.wait_for(
        _run_status_task(bot, chat_id=123, placeholder=placeholder, state=state),
        timeout=1.0,
    )

    placeholder.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_task_survives_edit_error(ph_mock):
    """Status task must not crash when edit_text raises."""
    bot = MagicMock()
    placeholder = MagicMock()
    call_count = 0

    async def _fail_then_stop(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("message not modified")
        state["done"] = True

    placeholder.edit_text = AsyncMock(side_effect=_fail_then_stop)
    state = {"text": "", "done": False}

    await asyncio.wait_for(
        _run_status_task(bot, chat_id=123, placeholder=placeholder, state=state),
        timeout=5.0,
    )

    assert call_count == 2
