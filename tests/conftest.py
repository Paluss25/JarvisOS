"""Shared test configuration and fixtures.

Installs module-level mocks for optional heavy dependencies (claude_agent_sdk,
agno, etc.) before any test module is collected, so that imports in src.*
never fail due to missing packages in the test venv.
"""
import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock claude_agent_sdk — not installed in test venv
# ---------------------------------------------------------------------------
if "claude_agent_sdk" not in sys.modules:
    _sdk_mock = MagicMock()
    _sdk_mock.ClaudeAgentOptions = MagicMock
    _sdk_mock.ClaudeSDKClient = MagicMock
    _sdk_mock.RateLimitEvent = type("RateLimitEvent", (), {})
    _sdk_mock.ResultMessage = type(
        "ResultMessage", (), {"total_cost_usd": 0.0, "duration_ms": 0, "num_turns": 0}
    )
    _sdk_mock.StreamEvent = type("StreamEvent", (), {"event": {}})
    _sdk_mock.TaskNotificationMessage = type("TaskNotificationMessage", (), {})
    _sdk_mock.TaskProgressMessage = type("TaskProgressMessage", (), {})
    _sdk_mock.TaskStartedMessage = type("TaskStartedMessage", (), {})
    _sdk_mock.ThinkingConfigAdaptive = MagicMock
    sys.modules["claude_agent_sdk"] = _sdk_mock

# ---------------------------------------------------------------------------
# Mock rapidfuzz — heavy dependency not needed for unit tests
# ---------------------------------------------------------------------------
if "rapidfuzz" not in sys.modules:
    _rf_mock = MagicMock()
    _rf_mock.fuzz = MagicMock()
    sys.modules["rapidfuzz"] = _rf_mock
    sys.modules["rapidfuzz.fuzz"] = _rf_mock.fuzz

# ---------------------------------------------------------------------------
# Mock telegram — for testing Telegram bot without python-telegram-bot
# ---------------------------------------------------------------------------
if "telegram" not in sys.modules:
    _tg_mock = MagicMock()
    _tg_mock.InlineKeyboardButton = MagicMock
    _tg_mock.InlineKeyboardMarkup = MagicMock
    _tg_mock.Update = MagicMock

    # telegram.constants
    _tg_constants = MagicMock()
    _tg_constants.ParseMode = MagicMock()

    # telegram.error
    _tg_error = MagicMock()
    _tg_error.BadRequest = Exception
    _tg_error.NetworkError = Exception
    _tg_error.RetryAfter = Exception

    # telegram.ext
    _tg_ext = MagicMock()
    _tg_ext.Application = MagicMock
    _tg_ext.CallbackQueryHandler = MagicMock
    _tg_ext.CommandHandler = MagicMock
    _tg_ext.MessageHandler = MagicMock
    _tg_ext.filters = MagicMock()

    # ContextTypes needs DEFAULT_TYPE as a class attribute
    _context_types = MagicMock()
    _context_types.DEFAULT_TYPE = MagicMock()
    _tg_ext.ContextTypes = _context_types

    sys.modules["telegram"] = _tg_mock
    sys.modules["telegram.constants"] = _tg_constants
    sys.modules["telegram.error"] = _tg_error
    sys.modules["telegram.ext"] = _tg_ext
