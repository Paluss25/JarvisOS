"""Tests for BaseAgentClient."""
# claude_agent_sdk is mocked by tests/conftest.py before any test module is
# collected — no duplicate mock block needed here.

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from src.agent_runner import AgentConfig
from src.agent_runner.client import BaseAgentClient


@pytest.fixture
def config():
    return AgentConfig(
        id="test",
        name="TestAgent",
        port=8099,
        workspace_path=Path("/tmp/test_workspace"),
        telegram_token_env="TELEGRAM_TEST_TOKEN",
        telegram_chat_id_env="TELEGRAM_TEST_CHAT_ID",
    )


@pytest.fixture
def mock_sdk():
    sdk = AsyncMock()
    sdk.connect = AsyncMock()
    sdk.disconnect = AsyncMock()
    sdk.query = AsyncMock()
    sdk.interrupt = AsyncMock(return_value=None)
    sdk.get_context_usage = AsyncMock(return_value=MagicMock(
        input_tokens=100, output_tokens=50,
        cache_creation_tokens=0, cache_read_tokens=0,
    ))
    sdk.get_mcp_status = AsyncMock(return_value=MagicMock(servers={}))
    return sdk


def make_client(config, mock_sdk, tmp_path):
    """Build a BaseAgentClient with mocked DailyLogger."""
    with patch("src.agent_runner.client.DailyLogger"):
        options = MagicMock()
        client = BaseAgentClient(
            config=config,
            system_prompt="You are a test agent.",
            options=options,
        )
    return client


def test_base_agent_client_init(config, tmp_path):
    """BaseAgentClient initialises correctly from AgentConfig."""
    with patch("src.agent_runner.client.DailyLogger"):
        client = BaseAgentClient(
            config=config,
            system_prompt="sys",
            options=MagicMock(),
        )
    assert client.name == "TestAgent"
    assert client.config.id == "test"
    assert client._sdk is None


@pytest.mark.asyncio
async def test_connect_sets_sdk(config, mock_sdk):
    """connect() creates and connects the SDK subprocess."""
    with patch("src.agent_runner.client.DailyLogger"), \
         patch("src.agent_runner.client.ClaudeSDKClient", return_value=mock_sdk):
        client = BaseAgentClient(config=config, system_prompt="s", options=MagicMock())
        await client.connect()
    assert client._sdk is mock_sdk
    mock_sdk.connect.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_clears_sdk(config, mock_sdk):
    """disconnect() disconnects and clears the SDK reference."""
    with patch("src.agent_runner.client.DailyLogger"), \
         patch("src.agent_runner.client.ClaudeSDKClient", return_value=mock_sdk):
        client = BaseAgentClient(config=config, system_prompt="s", options=MagicMock())
        await client.connect()
        await client.disconnect()
    assert client._sdk is None
    mock_sdk.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_interrupt_returns_false_when_not_connected(config):
    """interrupt() returns False when SDK is not connected."""
    with patch("src.agent_runner.client.DailyLogger"):
        client = BaseAgentClient(config=config, system_prompt="s", options=MagicMock())
    result = await client.interrupt()
    assert result is False


@pytest.mark.asyncio
async def test_get_context_usage_returns_empty_when_not_connected(config):
    """get_context_usage() returns {} when not connected."""
    with patch("src.agent_runner.client.DailyLogger"):
        client = BaseAgentClient(config=config, system_prompt="s", options=MagicMock())
    result = await client.get_context_usage()
    assert result == {}


@pytest.mark.asyncio
async def test_query_raises_when_not_connected(config):
    """query() raises RuntimeError when not connected."""
    with patch("src.agent_runner.client.DailyLogger"):
        client = BaseAgentClient(config=config, system_prompt="s", options=MagicMock())
    with pytest.raises(RuntimeError, match="not connected"):
        await client.query("hello")
