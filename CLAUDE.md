# jarvisOS — Claude Code project instructions

## LOCKED: Agent naming convention

**DO NOT change any agent ID, directory name, workspace name, or Redis channel name without an explicit written order from the user.**

This convention was finalized on 2026-04-21 and is considered immutable. Automatic refactors, linter suggestions, "cleanup" passes, or any other unsolicited action that renames agents are strictly forbidden.

### Canonical mapping (read-only)

| Friendly name | Role | ID / directory / workspace / Redis channel |
|---|---|---|
| Jarvis | ChiefExecutiveOfficer | `ceo` |
| Timothy | ChiefInformationOfficer | `cio` |
| Warren | ChiefFinancialOfficer | `cfo` |
| DrHouse | ChiefOfHealth | `coh` |
| Mark | ChiefOfStaff | `cos` |
| Roger | DirectorOfSport | `dos` |
| NutritionDirector | DirectorOfNutrition | `don` |
| EmailIntelligenceAgent | — | `email_intelligence_agent` |

### Three-concept structure

- **ID** — machine key used in `agents.yaml`, `config.py`, Redis A2A channels, `create_send_message_tool()` first arg, `send_message(to=...)` values, tool docstring examples. Chiefs and Directors use role acronym (`ceo`, `cio`, …). Others use full snake_case name (`email_intelligence_agent`).
- **Role** — formal class name used in system prompts and logging.
- **Friendly name** — persona used in SOUL/system prompt prose only. Never used as an identifier.

### What is locked

Every occurrence in active source files is covered:

- `agents.yaml` — `id:`, `reports_to:`, `directors:` fields
- `src/agents/<id>/config.py` — `id=` in `AgentConfig`, `to=` in cron prompts
- `src/agents/<id>/tools.py` — `create_send_message_tool("<id>", ...)`, `create_sdk_mcp_server(name="<id>-tools", ...)`, docstring `to` examples
- `src/agents/<id>/memory_bridge.py` — `user_id=`, `session_id` prefix
- `src/agents/coh/router.py` — director IDs in `plan.consult`
- `src/agent_runner/tools/send_message.py` — channel naming `a2a:{id}`

### Allowed without order

- Editing system prompts, SOUL content, and friendly-name prose
- Adding new tools or modifying tool logic
- Any change that does not touch an agent ID

### Requires explicit user order

- Renaming any agent ID in any file
- Adding a new agent (must include ID assignment confirmation)
- Removing an agent
