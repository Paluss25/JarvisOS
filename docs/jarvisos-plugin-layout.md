# JarvisOS Plugin Layout

JarvisOS plugins are local, trusted Python packages copied into the image at `/app/plugins`.

The runtime contract is intentionally narrow:

- Manifest: `plugin.yaml`
- Entrypoint: `plugin.py`
- Function: `register(context)`
- Return type: `list[plugin_runtime.ToolSpec]`

`AgentConfig` controls loading through `plugin_root`, `plugins_enabled`, and per-agent plugin allowlists. The client registers plugin tools in a separate `{agent}-plugin-tools` MCP server after direct tools. Direct tools win on duplicate names.

Current packages:

- `memory-box-tools`
- `task-tools`
- `report-issue-tools`
- `cron-tools`
- `calendar-tools`
- `contacts-tools`
- `email-digest-tools`
- `perplexity-tools`
