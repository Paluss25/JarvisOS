# JarvisOS Plugins

`plugins/` contains trusted local tool packages loaded by `plugin_runtime`.

Each plugin directory must include:

- `plugin.yaml`: manifest with `name`, `version`, `entrypoint`, `tools`, and `allowed_agents`.
- `plugin.py`: entrypoint exposing `register(context) -> list[ToolSpec]`.

Plugins are additive. Direct in-agent MCP tools remain canonical during this migration; if a plugin tool name duplicates a direct tool, the agent runner keeps the direct tool and skips the plugin copy.

Runtime defaults:

- `JARVIOS_PLUGIN_ROOT`: defaults to `/app/plugins`.
- `JARVIOS_PLUGINS_ENABLED`: defaults to enabled.
- `JARVIOS_PLUGINS_<AGENT_ID>` or `JARVIOS_PLUGINS`: optional comma-separated allowlist override.
