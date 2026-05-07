from pathlib import Path

import pytest

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin


@pytest.mark.asyncio
async def test_contacts_plugin_exposes_mt_contacts_tools(monkeypatch, tmp_path):
    async def fake_handler(args):
        return {"args": args}

    for name in [
        "contacts_list",
        "contacts_search",
        "contacts_get",
        "contacts_update",
        "contacts_delete",
    ]:
        monkeypatch.setattr(f"agent_runner.tools.contacts_client.{name}", fake_handler)

    plugin = load_plugin(
        Path("plugins/contacts-tools"),
        PluginContext(agent_id="mt", workspace_path=tmp_path, config={}),
    )
    tools = {tool.name: tool for tool in plugin.tools}

    assert set(tools) == {
        "contacts_list",
        "contacts_search",
        "contacts_get",
        "contacts_update",
        "contacts_delete",
    }
    assert await tools["contacts_search"].handler({"query": "Ada"}) == {"args": {"query": "Ada"}}
