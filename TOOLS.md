# Tools Reference — Email Intelligence Agent

## Core platform tools (always available)

### `daily_log`
Append a timestamped note to today's memory file (`memory/YYYY-MM-DD.md`).

### `memory_search`
Text search across MEMORY.md + all `memory/*.md` files (most recent first).

### `memory_get`
Read a specific workspace file by relative path.

### `send_message`
Send a message to another agent via Redis pub/sub (e.g. `to="ceo"`).

### `cron_create` / `cron_list` / `cron_update` / `cron_delete`
Manage scheduled tasks. Schedule format: `daily@HH:MM` | `weekly@DOW@HH:MM` | `once@YYYY-MM-DD@HH:MM`. Times: Europe/Rome.

---

## Domain-specific tools

> **TODO:** Document any domain-specific tools added to tools.py.
