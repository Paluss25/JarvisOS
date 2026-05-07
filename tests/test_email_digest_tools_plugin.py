from pathlib import Path

import pytest

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin


@pytest.mark.asyncio
async def test_email_digest_plugin_uses_workspace_client(monkeypatch, tmp_path):
    async def fake_read(workspace_path, args):
        return {"workspace": workspace_path, "args": args}

    monkeypatch.setattr("agent_runner.tools.email_digest_client.read_email_digest", fake_read)
    plugin = load_plugin(
        Path("plugins/email-digest-tools"),
        PluginContext(agent_id="mt", workspace_path=tmp_path, config={}),
    )

    assert [tool.name for tool in plugin.tools] == ["read_email_digest"]
    assert await plugin.tools[0].handler({"max_items": 2}) == {
        "workspace": tmp_path,
        "args": {"max_items": 2},
    }
