from pathlib import Path

from plugin_runtime.context import PluginContext
from plugin_runtime.registry import discover_plugins, tools_for_agent


def _write_plugin(root: Path, name: str, allowed_agents: list[str]) -> None:
    plugin_dir = root / name
    plugin_dir.mkdir()
    agents_yaml = "\n".join(f"  - {agent}" for agent in allowed_agents)
    (plugin_dir / "plugin.yaml").write_text(
        f"""
name: {name}
version: 1
entrypoint: plugin.py
tools:
  - {name}_tool
allowed_agents:
{agents_yaml}
""",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        f"""
from plugin_runtime.tools import ToolSpec


def register(context):
    return [
        ToolSpec(
            name="{name}_tool",
            description="Test tool.",
            schema={{"type": "object"}},
            handler=lambda args: args,
        )
    ]
""",
        encoding="utf-8",
    )


def test_discover_plugins_returns_manifest_for_each_plugin_directory(tmp_path):
    _write_plugin(tmp_path, "calendar-tools", ["mt"])
    _write_plugin(tmp_path, "memory-box-tools", ["ceo", "cio"])

    manifests = discover_plugins(tmp_path)

    assert [manifest.name for manifest in manifests] == [
        "calendar-tools",
        "memory-box-tools",
    ]


def test_tools_for_agent_filters_by_allowed_agents(tmp_path):
    _write_plugin(tmp_path, "calendar-tools", ["mt"])
    _write_plugin(tmp_path, "memory-box-tools", ["ceo", "cio"])
    context = PluginContext(agent_id="mt", workspace_path=tmp_path, config={})

    tools = tools_for_agent(tmp_path, "mt", context)

    assert [tool.name for tool in tools] == ["calendar-tools_tool"]
