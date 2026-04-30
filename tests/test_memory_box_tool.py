# tests/test_memory_box_tool.py
from unittest.mock import AsyncMock, MagicMock, patch
import sys
from pathlib import Path

import pytest


class TestCreateQueryMemoryTool:

    def test_returns_none_when_sdk_unavailable(self, monkeypatch):
        """Factory returns None when claude_agent_sdk cannot be imported."""
        # Temporarily make claude_agent_sdk unimportable
        monkeypatch.delitem(sys.modules, "agent_runner.tools.memory_box", raising=False)
        monkeypatch.delitem(sys.modules, "agent_runner.tools", raising=False)
        monkeypatch.delitem(sys.modules, "agent_runner", raising=False)

        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "claude_agent_sdk" or name.startswith("claude_agent_sdk."):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with monkeypatch.context() as mp:
            mp.setattr(builtins, "__import__", mock_import)
            # Import the tool directly (bypasses agent_runner imports)
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "memory_box",
                Path(__file__).parent.parent / "src" / "agent_runner" / "tools" / "memory_box.py"
            )
            memory_box = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(memory_box)

            result = memory_box.create_query_memory_tool("mt")
            assert result is None

    @pytest.mark.asyncio
    async def test_tool_returns_error_on_empty_query(self):
        from agent_runner.tools.memory_box import create_query_memory_tool
        tool_entry = create_query_memory_tool("mt")
        assert tool_entry is not None
        result = await tool_entry.fn({"query": ""})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tool_calls_memory_box_api(self, monkeypatch):
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
            result = await tool_entry.fn({"query": "calendario", "limit": 5})

        assert result["count"] == 1
        assert result["results"][0]["content"] == "calendario event"
        assert result["results"][0]["score"] == 0.9

    @pytest.mark.asyncio
    async def test_tool_filters_by_agent(self, monkeypatch):
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
            result = await tool_entry.fn({"query": "test", "agent_filter": "coh"})

        assert result["agent_filter"] == "coh"
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"]["user"] == "coh"

    @pytest.mark.asyncio
    async def test_tool_returns_error_on_http_failure(self, monkeypatch):
        monkeypatch.setenv("MEMORY_BOX_URL", "http://memory.test")
        from agent_runner.tools.memory_box import create_query_memory_tool

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=RuntimeError("connection refused"))

        with patch("agent_runner.tools.memory_box.httpx.AsyncClient", return_value=mock_client):
            tool_entry = create_query_memory_tool("mt")
            result = await tool_entry.fn({"query": "test"})

        assert "error" in result
        assert "connection refused" in result["error"]
