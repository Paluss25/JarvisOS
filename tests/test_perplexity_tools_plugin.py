from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin


@pytest.mark.asyncio
async def test_perplexity_plugin_returns_existing_tool_name(monkeypatch, tmp_path):
    async def fake_search(query, *, workspace_path=None):
        return {"content": [{"type": "text", "text": f"answer:{query}:{workspace_path.name}"}]}

    monkeypatch.setattr("agent_runner.tools.perplexity_client.search_perplexity", fake_search)
    plugin = load_plugin(
        Path("plugins/perplexity-tools"),
        PluginContext(agent_id="ceo", workspace_path=tmp_path, config={}),
    )

    assert [tool.name for tool in plugin.tools] == ["perplexity_search"]
    result = await plugin.tools[0].handler({"query": "latest"})

    assert result["content"][0]["text"] == f"answer:latest:{tmp_path.name}"


@pytest.mark.asyncio
async def test_perplexity_client_calls_perplexity_api(monkeypatch, tmp_path):
    from agent_runner.tools.perplexity_client import search_perplexity

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "cited answer"}}],
    }

    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = AsyncMock(return_value=fake_response)

    monkeypatch.setattr(
        "agent_runner.tools.perplexity_client.httpx.AsyncClient",
        MagicMock(return_value=fake_client),
    )

    result = await search_perplexity("whoop api", workspace_path=tmp_path, api_key="secret")

    assert result["content"][0]["text"] == "cited answer"
    assert fake_client.post.call_args.kwargs["headers"]["Authorization"] == "Bearer secret"
