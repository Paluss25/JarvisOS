from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool

from src.agent_runner.client import _build_mcp_servers
from src.agent_runner.config import AgentConfig


def _write_plugin(root: Path, name: str, tool_name: str, allowed_agents: list[str]) -> None:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True)
    plugin_dir.joinpath("plugin.yaml").write_text(
        f"""
name: {name}
version: 1
entrypoint: plugin.py
tools:
  - {tool_name}
allowed_agents:
{chr(10).join(f"  - {agent}" for agent in allowed_agents)}
""",
        encoding="utf-8",
    )
    plugin_dir.joinpath("plugin.py").write_text(
        f"""
from plugin_runtime.tools import ToolSpec


def register(context):
    return [
        ToolSpec(
            name={tool_name!r},
            description="Plugin tool.",
            schema={{"value": {{"type": "string"}}}},
            handler=lambda args: {{"agent": context.agent_id, "value": args.get("value", "")}},
        )
    ]
""",
        encoding="utf-8",
    )


def _config(plugin_root: Path, **kwargs) -> AgentConfig:
    return AgentConfig(
        id="ceo",
        name="Jarvis",
        port=8000,
        workspace_path=Path("/tmp/workspace/ceo"),
        telegram_token_env="TELEGRAM_JARVIS_TOKEN",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
        plugin_root=plugin_root,
        **kwargs,
    )


def test_build_mcp_servers_adds_plugin_server_after_builtin_tools(tmp_path):
    _write_plugin(tmp_path, "memory-box-tools", "memory_box_query", ["ceo"])

    @sdk_tool("daily_log", "Built-in log.", {})
    async def daily_log(args):
        return {"ok": True}

    def factory(workspace_path, redis_a2a=None):
        return create_sdk_mcp_server(name="ceo-tools", tools=[daily_log])

    servers = _build_mcp_servers(
        _config(tmp_path, mcp_server_factory=factory, plugins=["memory-box-tools"]),
        Path("/tmp/workspace/ceo"),
    )

    assert list(servers) == ["ceo-tools", "ceo-plugin-tools"]
    assert [tool.name for tool in servers["ceo-tools"]._tools] == ["daily_log"]
    assert [tool.name for tool in servers["ceo-plugin-tools"]._tools] == ["memory_box_query"]


def test_build_mcp_servers_keeps_builtin_when_plugin_tool_name_duplicates(tmp_path):
    _write_plugin(tmp_path, "task-tools", "daily_log", ["ceo"])

    @sdk_tool("daily_log", "Built-in log.", {})
    async def daily_log(args):
        return {"ok": True}

    def factory(workspace_path, redis_a2a=None):
        return create_sdk_mcp_server(name="ceo-tools", tools=[daily_log])

    servers = _build_mcp_servers(
        _config(tmp_path, mcp_server_factory=factory, plugins=["task-tools"]),
        Path("/tmp/workspace/ceo"),
    )

    assert list(servers) == ["ceo-tools"]
    assert [tool.name for tool in servers["ceo-tools"]._tools] == ["daily_log"]


def test_build_mcp_servers_skips_plugins_when_disabled(tmp_path):
    _write_plugin(tmp_path, "memory-box-tools", "memory_box_query", ["ceo"])

    servers = _build_mcp_servers(
        _config(tmp_path, plugins_enabled=False, plugins=["memory-box-tools"]),
        Path("/tmp/workspace/ceo"),
    )

    assert servers == {}
