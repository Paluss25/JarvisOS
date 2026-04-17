"""Tests for AgentConfig dataclass."""
import os
import pytest
from pathlib import Path
from src.agent_runner.config import AgentConfig


def test_agent_config_minimal():
    """AgentConfig can be created with required fields only."""
    config = AgentConfig(
        id="test",
        name="Test",
        port=8099,
        workspace_path=Path("/tmp/workspace/test"),
        telegram_token_env="TELEGRAM_TEST_TOKEN",
        telegram_chat_id_env="TELEGRAM_TEST_CHAT_ID",
    )
    assert config.id == "test"
    assert config.port == 8099
    assert config.domains == []
    assert config.capabilities == []
    assert config.memory_backend == "filesystem"
    assert config.mcp_server_factory is None


def test_agent_config_defaults():
    """AgentConfig has sensible defaults for optional fields."""
    config = AgentConfig(
        id="jarvis",
        name="Jarvis",
        port=8000,
        workspace_path=Path("/app/workspace/jarvis"),
        telegram_token_env="TELEGRAM_JARVIS_TOKEN",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
    )
    assert "Bash" in config.allowed_tools
    assert config.model_env == "CLAUDE_MODEL"
    assert config.env_prefix == ""


def test_agent_config_env_method(monkeypatch):
    """env() returns value for the given key, with prefix fallback."""
    monkeypatch.setenv("MYBOT_LOG_LEVEL", "DEBUG")
    config = AgentConfig(
        id="bot",
        name="Bot",
        port=8002,
        workspace_path=Path("/tmp/ws"),
        telegram_token_env="BOT_TOKEN",
        telegram_chat_id_env="BOT_CHAT_ID",
        env_prefix="MYBOT_",
    )
    assert config.log_level == "DEBUG"


def test_agent_config_env_fallback(monkeypatch):
    """env() falls back to unprefixed key if prefixed key is absent."""
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    config = AgentConfig(
        id="bot",
        name="Bot",
        port=8002,
        workspace_path=Path("/tmp/ws"),
        telegram_token_env="BOT_TOKEN",
        telegram_chat_id_env="BOT_CHAT_ID",
        env_prefix="MISSING_",
    )
    assert config.log_level == "WARNING"


def test_agent_config_budget_none(monkeypatch):
    """budget returns None when env var not set."""
    monkeypatch.delenv("CLAUDE_MAX_BUDGET_USD", raising=False)
    config = AgentConfig(
        id="j",
        name="J",
        port=8000,
        workspace_path=Path("/tmp"),
        telegram_token_env="T",
        telegram_chat_id_env="C",
    )
    assert config.budget is None


def test_agent_config_budget_float(monkeypatch):
    """budget returns float when env var set."""
    monkeypatch.setenv("CLAUDE_MAX_BUDGET_USD", "5.0")
    config = AgentConfig(
        id="j",
        name="J",
        port=8000,
        workspace_path=Path("/tmp"),
        telegram_token_env="T",
        telegram_chat_id_env="C",
    )
    assert config.budget == 5.0


def test_agent_config_thinking_flag(monkeypatch):
    """thinking returns True for truthy env values."""
    for val in ("true", "1", "yes", "True", "YES"):
        monkeypatch.setenv("CLAUDE_THINKING", val)
        config = AgentConfig(
            id="j", name="J", port=8000,
            workspace_path=Path("/tmp"),
            telegram_token_env="T", telegram_chat_id_env="C",
        )
        assert config.thinking is True

    monkeypatch.setenv("CLAUDE_THINKING", "false")
    config = AgentConfig(
        id="j", name="J", port=8000,
        workspace_path=Path("/tmp"),
        telegram_token_env="T", telegram_chat_id_env="C",
    )
    assert config.thinking is False
