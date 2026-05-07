from pathlib import Path

import pytest

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin


@pytest.mark.asyncio
async def test_report_issue_plugin_uses_shared_client(monkeypatch, tmp_path):
    async def fake_report(agent_id, args):
        return {"agent_id": agent_id, "issues": args["issues"]}

    monkeypatch.setattr("agent_runner.tools.report_issue_client.report_issue", fake_report)
    plugin = load_plugin(
        Path("plugins/report-issue-tools"),
        PluginContext(agent_id="cio", workspace_path=tmp_path, config={}),
    )

    assert [tool.name for tool in plugin.tools] == ["report_issue"]
    result = await plugin.tools[0].handler({"issues": [{"type": "custom"}]})

    assert result == {"agent_id": "cio", "issues": [{"type": "custom"}]}
