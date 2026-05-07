from pathlib import Path

import pytest

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin


@pytest.mark.asyncio
async def test_cron_plugin_exposes_cron_tools(monkeypatch, tmp_path):
    calls = []

    async def fake_create(workspace_path, args):
        calls.append(("create", workspace_path, args))
        return {"ok": "create"}

    async def fake_list(workspace_path):
        calls.append(("list", workspace_path, {}))
        return {"ok": "list"}

    async def fake_update(workspace_path, args):
        calls.append(("update", workspace_path, args))
        return {"ok": "update"}

    async def fake_delete(workspace_path, args):
        calls.append(("delete", workspace_path, args))
        return {"ok": "delete"}

    monkeypatch.setattr("agent_runner.tools.cron_client.create_cron", fake_create)
    monkeypatch.setattr("agent_runner.tools.cron_client.list_crons", fake_list)
    monkeypatch.setattr("agent_runner.tools.cron_client.update_cron", fake_update)
    monkeypatch.setattr("agent_runner.tools.cron_client.delete_cron", fake_delete)

    plugin = load_plugin(
        Path("plugins/cron-tools"),
        PluginContext(agent_id="cio", workspace_path=tmp_path, config={}),
    )
    tools = {tool.name: tool for tool in plugin.tools}

    assert set(tools) == {"cron_create", "cron_list", "cron_update", "cron_delete"}
    assert await tools["cron_create"].handler({"name": "briefing"}) == {"ok": "create"}
    assert await tools["cron_list"].handler({}) == {"ok": "list"}
    assert await tools["cron_update"].handler({"id": "1"}) == {"ok": "update"}
    assert await tools["cron_delete"].handler({"id": "1"}) == {"ok": "delete"}
    assert calls[0][1] == tmp_path
