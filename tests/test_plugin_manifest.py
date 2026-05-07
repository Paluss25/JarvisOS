import pytest

from plugin_runtime.errors import PluginManifestError
from plugin_runtime.manifest import PluginManifest, load_manifest_text


def test_load_manifest_text_accepts_minimal_plugin_manifest():
    manifest = load_manifest_text(
        """
name: memory-box-tools
version: 1
entrypoint: plugin.py
tools:
  - memory_box_query
  - memory_box_write
allowed_agents:
  - ceo
  - cio
"""
    )

    assert manifest == PluginManifest(
        name="memory-box-tools",
        version=1,
        entrypoint="plugin.py",
        tools=("memory_box_query", "memory_box_write"),
        allowed_agents=("ceo", "cio"),
    )


def test_load_manifest_text_rejects_empty_tool_list():
    with pytest.raises(PluginManifestError, match="tools"):
        load_manifest_text(
            """
name: empty
version: 1
entrypoint: plugin.py
tools: []
allowed_agents: [ceo]
"""
        )
