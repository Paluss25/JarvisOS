"""Tests for Telegram webhook mode — config fields, route handler, proxy."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# P0.T1 — AgentConfig webhook fields
# ---------------------------------------------------------------------------

def test_agent_config_webhook_fields_default_none():
    """telegram_webhook_url_env and telegram_webhook_secret_env default to None."""
    from agent_runner.config import AgentConfig

    config = AgentConfig(
        id="test",
        name="Test",
        port=9999,
        workspace_path=Path("/tmp/test"),
        telegram_token_env="TEST_TOKEN",
        telegram_chat_id_env="TEST_CHAT",
    )
    assert config.telegram_webhook_url_env is None
    assert config.telegram_webhook_secret_env is None


def test_agent_config_webhook_fields_accept_values():
    """Both webhook env var fields accept string values."""
    from agent_runner.config import AgentConfig

    config = AgentConfig(
        id="ceo",
        name="CEO",
        port=8000,
        workspace_path=Path("/tmp/ceo"),
        telegram_token_env="CEO_TELEGRAM_TOKEN",
        telegram_chat_id_env="CEO_TELEGRAM_CHAT",
        telegram_webhook_url_env="CEO_TELEGRAM_WEBHOOK_URL",
        telegram_webhook_secret_env="CEO_TELEGRAM_WEBHOOK_SECRET",
    )
    assert config.telegram_webhook_url_env == "CEO_TELEGRAM_WEBHOOK_URL"
    assert config.telegram_webhook_secret_env == "CEO_TELEGRAM_WEBHOOK_SECRET"
