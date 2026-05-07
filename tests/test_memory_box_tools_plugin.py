from pathlib import Path

import pytest

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin


@pytest.mark.asyncio
async def test_memory_box_plugin_exposes_query_tool(monkeypatch, tmp_path):
    async def fake_query(agent_id, query, *, agent_filter=None, limit=10):
        return {
            "agent_id": agent_id,
            "query": query,
            "agent_filter": agent_filter,
            "limit": limit,
        }

    monkeypatch.setattr("agent_runner.tools.memory_box_client.query_agent_memory", fake_query)
    plugin = load_plugin(
        Path("plugins/memory-box-tools"),
        PluginContext(agent_id="ceo", workspace_path=tmp_path, config={}),
    )

    assert [tool.name for tool in plugin.tools] == ["query_agent_memory"]
    result = await plugin.tools[0].handler({"query": "budget", "agent_filter": "cfo", "limit": 3})

    assert result == {
        "agent_id": "ceo",
        "query": "budget",
        "agent_filter": "cfo",
        "limit": 3,
    }
