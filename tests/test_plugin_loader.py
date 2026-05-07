from pathlib import Path

import pytest

from plugin_runtime.context import PluginContext
from plugin_runtime.errors import PluginLoadError
from plugin_runtime.loader import load_plugin


def _write_plugin(root: Path, name: str, *, entrypoint: str = "plugin.py", body: str = "") -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        f"""
name: {name}
version: 1
entrypoint: {entrypoint}
tools:
  - echo
allowed_agents:
  - mt
""",
        encoding="utf-8",
    )
    (plugin_dir / entrypoint).write_text(
        body
        or """
from plugin_runtime.tools import ToolSpec


def register(context):
    def echo(args):
        return {"echo": args["text"], "agent": context.agent_id}

    return [
        ToolSpec(
            name="echo",
            description="Echo text.",
            schema={"type": "object"},
            handler=echo,
        )
    ]
""",
        encoding="utf-8",
    )
    return plugin_dir


def test_load_plugin_imports_register_function_and_returns_tool_specs(tmp_path):
    plugin_dir = _write_plugin(tmp_path, "echo-tools")
    context = PluginContext(agent_id="mt", workspace_path=tmp_path, config={})

    plugin = load_plugin(plugin_dir, context)

    assert plugin.manifest.name == "echo-tools"
    assert [tool.name for tool in plugin.tools] == ["echo"]
    assert plugin.tools[0].handler({"text": "ciao"}) == {"echo": "ciao", "agent": "mt"}


def test_load_plugin_rejects_entrypoint_outside_plugin_directory(tmp_path):
    plugin_dir = tmp_path / "bad-tools"
    plugin_dir.mkdir()
    (tmp_path / "outside.py").write_text("def register(context): return []", encoding="utf-8")
    (plugin_dir / "plugin.yaml").write_text(
        """
name: bad-tools
version: 1
entrypoint: ../outside.py
tools:
  - bad
allowed_agents:
  - mt
""",
        encoding="utf-8",
    )
    context = PluginContext(agent_id="mt", workspace_path=tmp_path, config={})

    with pytest.raises(PluginLoadError, match="entrypoint"):
        load_plugin(plugin_dir, context)
