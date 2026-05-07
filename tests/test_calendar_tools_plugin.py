from pathlib import Path

import pytest

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin


@pytest.mark.asyncio
async def test_calendar_plugin_exposes_mt_calendar_tools(monkeypatch, tmp_path):
    async def fake_handler(args):
        return {"args": args}

    for name in [
        "calendar_list",
        "calendar_get_events",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
    ]:
        monkeypatch.setattr(f"agent_runner.tools.calendar_client.{name}", fake_handler)

    plugin = load_plugin(
        Path("plugins/calendar-tools"),
        PluginContext(agent_id="mt", workspace_path=tmp_path, config={}),
    )
    tools = {tool.name: tool for tool in plugin.tools}

    assert set(tools) == {
        "calendar_list",
        "calendar_get_events",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
    }
    assert await tools["calendar_list"].handler({}) == {"args": {}}
