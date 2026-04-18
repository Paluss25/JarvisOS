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
