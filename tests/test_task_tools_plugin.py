from pathlib import Path

import pytest

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin


@pytest.mark.asyncio
async def test_task_plugin_uses_task_client(monkeypatch, tmp_path):
    calls = []

    async def fake_create(agent_id, **kwargs):
        calls.append(("create", agent_id, kwargs))
        return "created"

    async def fake_update(task_id, **kwargs):
        calls.append(("update", task_id, kwargs))
        return "updated"

    async def fake_list(agent_id, **kwargs):
        calls.append(("list", agent_id, kwargs))
        return "listed"

    monkeypatch.setattr("agent_runner.tools.task_client.create_task", fake_create)
    monkeypatch.setattr("agent_runner.tools.task_client.update_task", fake_update)
    monkeypatch.setattr("agent_runner.tools.task_client.list_my_tasks", fake_list)

    plugin = load_plugin(
        Path("plugins/task-tools"),
        PluginContext(agent_id="mt", workspace_path=tmp_path, config={}),
    )
    tools = {tool.name: tool for tool in plugin.tools}

    assert set(tools) == {"create_task", "update_task", "list_my_tasks"}
    assert await tools["create_task"].handler({"title": "Close loop", "assign_to": "cio"}) == "created"
    assert await tools["update_task"].handler({"task_id": "abc", "status": "done"}) == "updated"
    assert await tools["list_my_tasks"].handler({"status": "pending"}) == "listed"
    assert calls[0] == (
        "create",
        "mt",
        {
            "title": "Close loop",
            "description": "",
            "priority": "normal",
            "depends_on": [],
            "assign_to": "cio",
        },
    )
