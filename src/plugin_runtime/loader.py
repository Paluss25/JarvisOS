from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from plugin_runtime.context import PluginContext
from plugin_runtime.errors import PluginLoadError
from plugin_runtime.manifest import PluginManifest, load_manifest_text
from plugin_runtime.tools import ToolSpec


@dataclass(frozen=True)
class LoadedPlugin:
    manifest: PluginManifest
    tools: tuple[ToolSpec, ...]


def load_plugin(plugin_dir: Path, context: PluginContext) -> LoadedPlugin:
    plugin_dir = plugin_dir.resolve()
    manifest_path = plugin_dir / "plugin.yaml"
    if not manifest_path.exists():
        raise PluginLoadError(f"plugin manifest not found: {manifest_path}")

    manifest = load_manifest_text(manifest_path.read_text(encoding="utf-8"))
    entrypoint = (plugin_dir / manifest.entrypoint).resolve()
    if not _is_relative_to(entrypoint, plugin_dir):
        raise PluginLoadError(f"plugin entrypoint escapes plugin directory: {manifest.entrypoint}")
    if not entrypoint.exists():
        raise PluginLoadError(f"plugin entrypoint not found: {entrypoint}")

    module_name = f"jarvisos_plugin_{manifest.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint)
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"could not import plugin entrypoint: {entrypoint}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    register = getattr(module, "register", None)
    if not callable(register):
        raise PluginLoadError("plugin entrypoint must expose register(context)")

    tools = register(context)
    if not isinstance(tools, list | tuple):
        raise PluginLoadError("register(context) must return a list of ToolSpec objects")
    for tool in tools:
        if not isinstance(tool, ToolSpec):
            raise PluginLoadError("register(context) returned a non-ToolSpec item")

    return LoadedPlugin(manifest=manifest, tools=tuple(tools))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
