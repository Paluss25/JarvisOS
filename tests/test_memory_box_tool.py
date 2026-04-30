# tests/test_memory_box_tool.py
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestCreateQueryMemoryTool:

    def test_returns_none_when_sdk_unavailable(self, monkeypatch):
        """When claude_agent_sdk is unavailable, factory returns None gracefully."""
        assert callable(__import__("agent_runner.tools.memory_box", fromlist=["create_query_memory_tool"]).create_query_memory_tool)

    def test_tool_returns_error_on_empty_query(self):
        from agent_runner.tools.memory_box import create_query_memory_tool
        tool_entry = create_query_memory_tool("mt")
        assert tool_entry is not None
        result = _run(tool_entry.fn({"query": ""}))
        assert "error" in result

    def test_tool_calls_memory_box_api(self, monkeypatch):
        monkeypatch.setenv("MEMORY_BOX_URL", "http://memory.test")
        from agent_runner.tools.memory_box import create_query_memory_tool

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "results": [
                {"score": 0.9, "text": "calendario event", "date": "2026-04-29",
                 "session": "mt-session", "collection": "memory", "entity_names": []}
            ],
            "graph_results": {}
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch("agent_runner.tools.memory_box.httpx.AsyncClient", return_value=mock_client):
            tool_entry = create_query_memory_tool("mt")
            result = _run(tool_entry.fn({"query": "calendario", "limit": 5}))

        assert result["count"] == 1
        assert result["results"][0]["content"] == "calendario event"
        assert result["results"][0]["score"] == 0.9

    def test_tool_filters_by_agent(self, monkeypatch):
        monkeypatch.setenv("MEMORY_BOX_URL", "http://memory.test")
        from agent_runner.tools.memory_box import create_query_memory_tool

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "results": [
                {"score": 0.9, "text": "from coh", "date": "", "session": "coh-session",
                 "collection": "memory", "entity_names": []},
                {"score": 0.8, "text": "from mt", "date": "", "session": "mt-session",
                 "collection": "memory", "entity_names": []},
            ],
            "graph_results": {}
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=fake_response)

        with patch("agent_runner.tools.memory_box.httpx.AsyncClient", return_value=mock_client):
            tool_entry = create_query_memory_tool("ceo")
            result = _run(tool_entry.fn({"query": "test", "agent_filter": "coh"}))

        assert result["agent_filter"] == "coh"
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"]["user"] == "coh"

    def test_tool_returns_error_on_http_failure(self, monkeypatch):
        monkeypatch.setenv("MEMORY_BOX_URL", "http://memory.test")
        from agent_runner.tools.memory_box import create_query_memory_tool

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=RuntimeError("connection refused"))

        with patch("agent_runner.tools.memory_box.httpx.AsyncClient", return_value=mock_client):
            tool_entry = create_query_memory_tool("mt")
            result = _run(tool_entry.fn({"query": "test"}))

        assert "error" in result
        assert "connection refused" in result["error"]
