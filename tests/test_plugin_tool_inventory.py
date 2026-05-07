from pathlib import Path

from plugin_runtime.context import PluginContext
from plugin_runtime.loader import load_plugin
from plugin_runtime.manifest import load_manifest_text


ALLOWED_DIRECT_TOOL_SHADOWS = {
    "calendar_create_event",
    "calendar_delete_event",
    "calendar_get_events",
    "calendar_list",
    "calendar_update_event",
    "contacts_delete",
    "contacts_get",
    "contacts_list",
    "contacts_search",
    "contacts_update",
    "cron_create",
    "cron_delete",
    "cron_list",
    "cron_update",
    "perplexity_search",
    "query_agent_memory",
    "read_email_digest",
    "report_issue",
}


def test_plugin_tool_inventory_matches_manifests(tmp_path):
    for plugin_dir in sorted(path for path in Path("plugins").iterdir() if path.is_dir()):
        manifest = load_manifest_text(plugin_dir.joinpath("plugin.yaml").read_text(encoding="utf-8"))
        loaded = load_plugin(
            plugin_dir,
            PluginContext(agent_id=manifest.allowed_agents[0], workspace_path=tmp_path, config={}),
        )

        assert tuple(tool.name for tool in loaded.tools) == manifest.tools


def test_shadowed_direct_tool_names_are_explicitly_allowlisted(tmp_path):
    all_tool_names = set()
    for plugin_dir in sorted(path for path in Path("plugins").iterdir() if path.is_dir()):
        manifest = load_manifest_text(plugin_dir.joinpath("plugin.yaml").read_text(encoding="utf-8"))
        loaded = load_plugin(
            plugin_dir,
            PluginContext(agent_id=manifest.allowed_agents[0], workspace_path=tmp_path, config={}),
        )
        all_tool_names.update(tool.name for tool in loaded.tools)

    unexpected = all_tool_names.intersection(_known_direct_tool_names()) - ALLOWED_DIRECT_TOOL_SHADOWS
    assert unexpected == set()


def _known_direct_tool_names() -> set[str]:
    return {
        "calendar_create_event",
        "calendar_delete_event",
        "calendar_get_events",
        "calendar_list",
        "calendar_update_event",
        "contacts_delete",
        "contacts_get",
        "contacts_list",
        "contacts_search",
        "contacts_update",
        "cron_create",
        "cron_delete",
        "cron_list",
        "cron_update",
        "perplexity_search",
        "query_agent_memory",
        "read_email_digest",
        "report_issue",
    }
