from pathlib import Path

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin
from plugin_runtime.manifest import load_manifest_text


def test_each_plugin_directory_has_valid_manifest_and_entrypoint(tmp_path):
    plugin_root = Path("plugins")
    plugin_dirs = sorted(path for path in plugin_root.iterdir() if path.is_dir())

    assert plugin_dirs
    for plugin_dir in plugin_dirs:
        manifest_path = plugin_dir / "plugin.yaml"
        plugin_path = plugin_dir / "plugin.py"
        assert manifest_path.exists(), f"{plugin_dir} missing plugin.yaml"
        assert plugin_path.exists(), f"{plugin_dir} missing plugin.py"

        manifest = load_manifest_text(manifest_path.read_text(encoding="utf-8"))
        assert manifest.name == plugin_dir.name
        loaded = load_plugin(
            plugin_dir,
            PluginContext(agent_id=manifest.allowed_agents[0], workspace_path=tmp_path, config={}),
        )
        assert [tool.name for tool in loaded.tools] == list(manifest.tools)
