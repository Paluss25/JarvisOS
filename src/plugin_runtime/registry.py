from __future__ import annotations

from pathlib import Path

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin
from plugin_runtime.manifest import PluginManifest, load_manifest_text
from plugin_runtime.tools import ToolSpec


def discover_plugins(root: Path) -> list[PluginManifest]:
    if not root.exists():
        return []
    manifests: list[PluginManifest] = []
    for plugin_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest_path = plugin_dir / "plugin.yaml"
        if not manifest_path.exists():
            continue
        manifests.append(load_manifest_text(manifest_path.read_text(encoding="utf-8")))
    return manifests


def tools_for_agent(root: Path, agent_id: str, context: PluginContext) -> list[ToolSpec]:
    if not root.exists():
        return []
    tools: list[ToolSpec] = []
    for plugin_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest_path = plugin_dir / "plugin.yaml"
        if not manifest_path.exists():
            continue
        manifest = load_manifest_text(manifest_path.read_text(encoding="utf-8"))
        if agent_id not in manifest.allowed_agents:
            continue
        plugin = load_plugin(plugin_dir, context)
        tools.extend(plugin.tools)
    return tools
