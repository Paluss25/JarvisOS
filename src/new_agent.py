#!/usr/bin/env python3
"""Scaffold a new agent for the JarvisOS platform.

Creates:
  src/agents/{id}/__init__.py       — package stub
  src/agents/{id}/run.py            — supervisord entrypoint
  src/agents/{id}/config.py         — AgentConfig factory + builtin crons
  src/agents/{id}/tools.py          — in-process MCP server (all core tools + fixes)
  workspace/{id}/SOUL.md            — identity placeholder
  workspace/{id}/AGENTS.md          — operating manual placeholder
  workspace/{id}/USER.md            — user profile placeholder
  workspace/{id}/TOOLS.md           — tool reference placeholder
  workspace/{id}/MEMORY.md          — long-term memory (empty)
  workspace/{id}/HEARTBEAT.md       — scheduled task log placeholder
  workspace/{id}/memory/            — daily log directory

Appends the new agent entry to agents.yaml.

Usage:
  python scripts/new_agent.py <id> <port> [options]

Examples:
  python scripts/new_agent.py alice 8003 --domains finance,accounting
  python scripts/new_agent.py bob 8004 --name Bob --env-prefix BOB_
"""

import argparse
import sys
import textwrap
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Resolve repo root (script lives in scripts/, repo root is one level up)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent.resolve()
_REPO_ROOT = _SCRIPT_DIR.parent


# ---------------------------------------------------------------------------
# Template builders
# All fixes from live agents are baked in:
#   • _text()     — wrap str returns as MCP content dict (avoids SDK crash)
#   • _parse_args() — normalize JSON-string args from older SDK versions
#   • _SDK_AVAILABLE guard — graceful degradation if SDK not installed
#   • workspace path traversal check in memory_get
#   • Agent tool in allowed_tools (sub-agent dispatch)
#   • env_prefix support for isolated env var overrides
# ---------------------------------------------------------------------------


def _render_init(id_: str, name: str) -> str:
    return f'"""{name} agent."""\n'


def _render_run(id_: str, name: str) -> str:
    ID = id_.upper()
    return textwrap.dedent(f"""\
        \"\"\"{name} agent entry point — invoked by supervisord.\"\"\"

        import logging
        import os
        from pathlib import Path

        import uvicorn

        from agents.{id_}.config import build_{id_}_config
        from agent_runner.app import create_app


        def main():
            workspace = os.environ.get("{ID}_WORKSPACE", "/app/workspace/{id_}")
            config = build_{id_}_config(workspace_root=Path(workspace))

            logging.basicConfig(
                level=getattr(logging, config.log_level.upper(), logging.INFO),
                format="%(asctime)s %(levelname)s %(name)s — %(message)s",
            )

            app = create_app(config)
            port = int(os.environ.get("AGENT_PORT", str(config.port)))
            uvicorn.run(app, host="0.0.0.0", port=port, log_level=config.log_level.lower())


        if __name__ == "__main__":
            main()
        """)


def _render_config(
    id_: str,
    name: str,
    port: int,
    env_prefix: str,
    telegram_token_env: str,
    telegram_chat_id_env: str,
    domains: list[str],
    capabilities: list[str],
) -> str:
    ID = id_.upper()
    return textwrap.dedent(f"""\
        \"\"\"{name}-specific configuration.\"\"\"

        from pathlib import Path

        from agent_runner.config import AgentConfig


        {ID}_BUILTIN_CRONS = [
            {{
                "name": "morning_briefing",
                "schedule": "daily@08:00",
                "prompt": (
                    "Good morning. Prepare a concise briefing (under 200 words): "
                    "key items from yesterday's log, any tasks or follow-ups for today, "
                    "anything actionable. Be direct."
                ),
                "session_id": "heartbeat-morning",
                "telegram_notify": True,
                "builtin": True,
            }},
            {{
                "name": "eod_consolidation",
                "schedule": "daily@23:00",
                "prompt": (
                    "End of day. Summarise today in 3-5 bullet points: "
                    "decisions made, tasks completed, issues encountered, lessons learned."
                ),
                "session_id": "heartbeat-eod",
                "telegram_notify": False,
                "builtin": True,
            }},
            {{
                "name": "weekly_consolidation",
                "schedule": "weekly@sun@20:00",
                "prompt": (
                    "Weekly memory consolidation. Review this week's daily logs and the current "
                    "MEMORY.md. Produce an updated MEMORY.md. Return ONLY the raw markdown."
                ),
                "session_id": "heartbeat-weekly",
                "telegram_notify": True,
                "builtin": True,
            }},
        ]


        def build_{id_}_config(workspace_root: Path = Path("/app/workspace/{id_}")) -> AgentConfig:
            from agents.{id_}.tools import create_{id_}_mcp_server
            return AgentConfig(
                id="{id_}",
                name="{name}",
                port={port},
                workspace_path=workspace_root,
                telegram_token_env="{telegram_token_env}",
                telegram_chat_id_env="{telegram_chat_id_env}",
                domains={domains!r},
                capabilities={capabilities!r},
                model_env="CLAUDE_MODEL",
                fallback_model_env="CLAUDE_FALLBACK_MODEL",
                budget_env="CLAUDE_MAX_BUDGET_USD",
                effort_env="CLAUDE_EFFORT",
                thinking_env="CLAUDE_THINKING",
                context_1m_env="CLAUDE_CONTEXT_1M",
                log_level_env="LOG_LEVEL",
                env_prefix="{env_prefix}",
                memory_backend="filesystem",
                mcp_server_factory=create_{id_}_mcp_server,
                builtin_crons={ID}_BUILTIN_CRONS,
                # Agent tool enables sub-agent dispatch (required for delegate workflows)
                allowed_tools=[
                    "Bash", "Read", "Write", "Edit",
                    "WebSearch", "WebFetch", "Glob", "Grep",
                    "Agent",
                ],
            )
        """)


def _render_tools(id_: str, name: str) -> str:
    return textwrap.dedent(f"""\
        \"\"\"In-process MCP server exposing {name} custom tools to the claude-agent-sdk.

        Core tools (platform-standard — do not remove):
          daily_log      — Append to today's memory log
          memory_search  — Text search across MEMORY.md + memory/*.md
          memory_get     — Read a specific memory file from workspace
          send_message   — Send a message to another agent via Redis pub/sub
          cron_create    — Create a scheduled task
          cron_list      — List scheduled tasks
          cron_update    — Update a scheduled task
          cron_delete    — Delete a scheduled task

        Domain-specific tools (add below):
          # TODO: add your domain tools here
        \"\"\"

        import json
        import logging
        from pathlib import Path

        logger = logging.getLogger(__name__)


        # ---------------------------------------------------------------------------
        # Helpers — do NOT remove these; they fix known SDK/MCP compatibility issues
        # ---------------------------------------------------------------------------

        def _parse_args(args) -> dict:
            \"\"\"Normalize tool args — older SDK versions pass a JSON string instead of a dict.\"\"\"
            if isinstance(args, str):
                try:
                    parsed = json.loads(args)
                    return parsed if isinstance(parsed, dict) else {{}}
                except (json.JSONDecodeError, ValueError):
                    return {{}}
            return args if isinstance(args, dict) else {{}}


        def _text(s: str) -> dict:
            \"\"\"Wrap a plain string as an MCP text content response.

            The SDK's call_tool handler calls result.get("is_error") unconditionally,
            so every tool MUST return a dict — never a bare string.
            \"\"\"
            return {{"content": [{{"type": "text", "text": str(s)}}]}}


        # ---------------------------------------------------------------------------
        # SDK import guard — graceful degradation if SDK not installed
        # ---------------------------------------------------------------------------

        try:
            from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool
            _SDK_AVAILABLE = True
        except ImportError:
            _SDK_AVAILABLE = False
            create_sdk_mcp_server = None
            sdk_tool = None


        # ---------------------------------------------------------------------------
        # MCP server factory
        # ---------------------------------------------------------------------------

        def create_{id_}_mcp_server(workspace_path: Path, redis_a2a=None):
            \"\"\"Build and return the in-process MCP server with {name} custom tools.

            Returns None if the SDK MCP server API is not available.
            \"\"\"
            if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
                logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
                return None

            # --- Core platform tools ------------------------------------------------

            @sdk_tool(
                "daily_log",
                "Append a timestamped entry to today's memory log. "
                "Use this to record significant events, decisions, or facts worth remembering.",
                {{"message": str}},
            )
            async def daily_log(args: dict) -> dict:
                args = _parse_args(args)
                message = args.get("message", "")
                if not message:
                    return _text("No message provided.")
                try:
                    from agent_runner.memory.daily_logger import DailyLogger
                    DailyLogger(workspace_path).log(message)
                    return _text(f"Logged: {{message[:80]}}")
                except Exception as exc:
                    logger.error("daily_log: failed — %s", exc)
                    return _text(f"Failed to log: {{exc}}")

            @sdk_tool(
                "memory_search",
                "Search across long-term memory (MEMORY.md) and all daily logs (memory/*.md) "
                "using text matching. Use this to recall past events, decisions, or facts. "
                "Results include matching lines with surrounding context, most recent files first.",
                {{"query": str, "top_k": int}},
            )
            async def memory_search(args: dict) -> dict:
                args = _parse_args(args)
                query = args.get("query", "").strip()
                if not query:
                    return _text("No query provided.")

                top_k = int(args.get("top_k") or 5)
                query_lower = query.lower()

                memory_dir = workspace_path / "memory"
                dated_files = sorted(memory_dir.glob("*.md"), reverse=True) if memory_dir.exists() else []
                files_to_search = list(dated_files) + [workspace_path / "MEMORY.md"]

                results = []
                for f in files_to_search:
                    if not f.exists():
                        continue
                    try:
                        lines = f.read_text(encoding="utf-8").split("\\n")
                    except OSError:
                        continue

                    for i, line in enumerate(lines):
                        if query_lower in line.lower():
                            start = max(0, i - 2)
                            end = min(len(lines), i + 3)
                            snippet = "\\n".join(lines[start:end])
                            results.append(f"**{{f.name}}** (line {{i + 1}}):\\n```\\n{{snippet}}\\n```")
                            if len(results) >= top_k:
                                break
                    if len(results) >= top_k:
                        break

                if not results:
                    return _text(f"No results found for '{{query}}'.")
                return _text("\\n\\n---\\n\\n".join(results))

            @sdk_tool(
                "memory_get",
                "Read a specific memory file from the workspace. "
                "Use path relative to workspace root, e.g. 'MEMORY.md' or 'memory/2026-04-16.md'. "
                "Optionally specify start_line and num_lines to read a slice.",
                {{"path": str, "start_line": int, "num_lines": int}},
            )
            async def memory_get(args: dict) -> dict:
                args = _parse_args(args)
                rel_path = args.get("path", "").strip()
                if not rel_path:
                    return _text("No path provided.")

                target = (workspace_path / rel_path).resolve()
                # Security: path traversal guard — must stay inside workspace
                if not str(target).startswith(str(workspace_path.resolve())):
                    return _text("Access denied: path is outside the workspace directory.")

                if not target.exists():
                    return _text(f"File not found: {{rel_path}}")

                try:
                    content = target.read_text(encoding="utf-8")
                except OSError as exc:
                    return _text(f"Error reading {{rel_path}}: {{exc}}")

                start_line = args.get("start_line")
                num_lines = args.get("num_lines")
                if start_line is not None or num_lines is not None:
                    lines = content.split("\\n")
                    s = int(start_line or 1) - 1  # 1-indexed → 0-indexed
                    n = int(num_lines) if num_lines is not None else len(lines)
                    content = "\\n".join(lines[s: s + n])

                return _text(content)

            # --- A2A send_message (Redis pub/sub) -----------------------------------

            if redis_a2a is not None:
                from agent_runner.tools.send_message import create_send_message_tool
                _send_message_fn = create_send_message_tool("{id_}", redis_a2a)

                @sdk_tool(
                    "send_message",
                    "Send a message to another agent and wait for their response. "
                    "Use 'to' to specify the target agent ID (e.g. 'ceo'). "
                    "'message' is the natural language request to send.",
                    {{"to": str, "message": str}},
                )
                async def send_message(args: dict) -> dict:
                    args = _parse_args(args)
                    return _text(await _send_message_fn(args))
            else:
                send_message = None  # Redis not configured

            # --- Cron tools ---------------------------------------------------------

            @sdk_tool(
                "cron_create",
                "Create a new scheduled task. "
                "schedule format: 'daily@HH:MM' | 'weekly@DOW@HH:MM' (mon/tue/.../sun) | "
                "'once@YYYY-MM-DD@HH:MM'. All times are Europe/Rome (CET/CEST). "
                "telegram_notify: set to true to receive a Telegram message with the result.",
                {{"name": str, "schedule": str, "prompt": str, "session_id": str, "telegram_notify": bool}},
            )
            async def cron_create(args: dict) -> dict:
                args = _parse_args(args)
                name = args.get("name", "").strip()
                schedule = args.get("schedule", "").strip()
                prompt_text = args.get("prompt", "").strip()
                if not name or not schedule or not prompt_text:
                    return _text("name, schedule, and prompt are required.")
                try:
                    from agent_runner.scheduler.cron_store import get_store
                    store = get_store(workspace_path)
                    entry = store.create(
                        name=name,
                        schedule=schedule,
                        prompt=prompt_text,
                        session_id=args.get("session_id") or "",
                        telegram_notify=bool(args.get("telegram_notify", False)),
                    )
                    return _text(f"Created cron '{{entry.name}}' (id={{entry.id}}, schedule={{entry.schedule}})")
                except Exception as exc:
                    return _text(f"Error: {{exc}}")

            @sdk_tool(
                "cron_list",
                "List all scheduled tasks (built-in and user-created) with their current status.",
                {{}},
            )
            async def cron_list(args: dict) -> dict:
                try:
                    from agent_runner.scheduler.cron_store import get_store
                    store = get_store(workspace_path)
                    entries = store.all()
                    if not entries:
                        return _text("No scheduled tasks.")
                    lines = []
                    for e in entries:
                        status = e.last_status if e.last_run else "never run"
                        enabled = "enabled" if e.enabled else "disabled"
                        builtin_tag = " [builtin]" if e.builtin else ""
                        lines.append(
                            f"- **{{e.name}}** (id={{e.id}}){{builtin_tag}}\\n"
                            f"  schedule={{e.schedule}}, {{enabled}}, last={{status}}\\n"
                            f"  telegram_notify={{e.telegram_notify}}"
                        )
                    return _text("\\n\\n".join(lines))
                except Exception as exc:
                    return _text(f"Error: {{exc}}")

            @sdk_tool(
                "cron_update",
                "Update a scheduled task by its id. "
                "Updatable fields: name, schedule, prompt, session_id, telegram_notify, enabled.",
                {{"id": str, "name": str, "schedule": str, "prompt": str,
                  "session_id": str, "telegram_notify": bool, "enabled": bool}},
            )
            async def cron_update(args: dict) -> dict:
                args = _parse_args(args)
                cron_id = args.get("id", "").strip()
                if not cron_id:
                    return _text("id is required.")
                updates = {{k: v for k, v in args.items() if k != "id" and v is not None}}
                if not updates:
                    return _text("No fields to update.")
                try:
                    from agent_runner.scheduler.cron_store import get_store
                    store = get_store(workspace_path)
                    entry = store.update(cron_id, **updates)
                    return _text(f"Updated cron '{{entry.name}}' (id={{entry.id}})")
                except Exception as exc:
                    return _text(f"Error: {{exc}}")

            @sdk_tool(
                "cron_delete",
                "Delete a user-created scheduled task by its id. "
                "Built-in tasks cannot be deleted — use cron_update with enabled=false to disable them.",
                {{"id": str}},
            )
            async def cron_delete(args: dict) -> dict:
                args = _parse_args(args)
                cron_id = args.get("id", "").strip()
                if not cron_id:
                    return _text("id is required.")
                try:
                    from agent_runner.scheduler.cron_store import get_store
                    store = get_store(workspace_path)
                    store.delete(cron_id)
                    return _text(f"Deleted cron id={{cron_id}}")
                except Exception as exc:
                    return _text(f"Error: {{exc}}")

            # --- TODO: add domain-specific tools here --------------------------------
            # Example:
            #
            # @sdk_tool("my_tool", "Description of what it does.", {{"param": str}})
            # async def my_tool(args: dict) -> dict:
            #     args = _parse_args(args)
            #     value = args.get("param", "")
            #     # ... do work ...
            #     return _text(result)

            # --- Assemble server ----------------------------------------------------

            all_tools = [
                daily_log, memory_search, memory_get,
                cron_create, cron_list, cron_update, cron_delete,
            ]
            if send_message is not None:
                all_tools.append(send_message)

            # TODO: append domain-specific tools to all_tools here

            try:
                server = create_sdk_mcp_server(name="{id_}-tools", tools=all_tools)
                logger.info("mcp_server: in-process MCP server created with %d tools", len(all_tools))
                return server
            except Exception as exc:
                logger.error("mcp_server: failed to create server — %s", exc)
                return None
        """)


# ---------------------------------------------------------------------------
# Workspace markdown templates
# ---------------------------------------------------------------------------

_SOUL_MD = """\
# Soul — {name}

> **TODO:** Define the agent's identity, values, and guiding principles.

## Who I am

I am {name}, an AI agent built on the JarvisOS platform.

## My purpose

<!-- Describe the domain this agent is responsible for -->

## Core values

- Accuracy over speed
- Clarity over verbosity
- Action over commentary

## What I am NOT

<!-- Define what falls outside this agent's scope -->
"""

_AGENTS_MD = """\
# Agents — {name} Operating Manual

> **TODO:** Define how this agent works, what it delegates, and to whom.

## My role

<!-- Describe what this agent is responsible for -->

## Sub-agents available

<!-- List sub-agents if this agent uses the Agent tool -->
None configured yet.

## Escalation rules

- Escalate to Jarvis when: <!-- define cross-domain conditions -->

## What I never do

- Do not perform actions outside my domain without escalation
"""

_USER_MD = """\
# User Profile — {name}

> **TODO:** Describe the user this agent serves.

## About the user

Name: Paluss
Timezone: Europe/Rome

## Preferences

<!-- Add user preferences relevant to this agent's domain -->

## Context

<!-- Add background context the agent should always have -->
"""

_TOOLS_MD = """\
# Tools Reference — {name}

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
"""

_MEMORY_MD = """\
# Memory — {name}

<!-- This file is maintained by the agent. Do not edit manually. -->
"""

_HEARTBEAT_MD = """\
# Heartbeat — {name}

## Scheduled tasks

| Task | Schedule | Last run | Status |
|------|----------|----------|--------|
| morning_briefing | daily@08:00 | — | — |
| eod_consolidation | daily@23:00 | — | — |
| weekly_consolidation | weekly@sun@20:00 | — | — |

## Notes

<!-- Agent adds notes here during heartbeat runs -->
"""


# ---------------------------------------------------------------------------
# Main scaffolding logic
# ---------------------------------------------------------------------------

def validate_id(id_: str) -> None:
    if not id_.isidentifier():
        sys.exit(f"Error: '{id_}' is not a valid Python identifier.")
    if not id_.islower():
        sys.exit(f"Error: agent id must be lowercase (got '{id_}').")
    if id_ in ("ceo", "dos", "cio"):
        sys.exit(f"Error: '{id_}' is already a live agent.")


def check_conflicts(id_: str, port: int, repo_root: Path) -> None:
    pkg_dir = repo_root / "src" / "agents" / id_
    if pkg_dir.exists():
        sys.exit(f"Error: {pkg_dir} already exists.")

    agents_yaml = repo_root / "agents.yaml"
    if agents_yaml.exists():
        with open(agents_yaml) as f:
            data = yaml.safe_load(f) or {}
        for agent in data.get("agents", []):
            if agent["id"] == id_:
                sys.exit(f"Error: agent '{id_}' already in agents.yaml.")
            if agent["port"] == port:
                sys.exit(f"Error: port {port} already used by agent '{agent['id']}'.")


def write_file(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] would write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  created  {path.relative_to(_REPO_ROOT)}")


def append_agents_yaml(
    id_: str,
    port: int,
    telegram_token_env: str,
    telegram_chat_id_env: str,
    domains: list[str],
    capabilities: list[str],
    repo_root: Path,
    dry_run: bool,
) -> None:
    agents_yaml = repo_root / "agents.yaml"
    if dry_run:
        print(f"  [dry-run] would append '{id_}' entry to agents.yaml")
        return

    with open(agents_yaml) as f:
        data = yaml.safe_load(f) or {}

    data.setdefault("agents", []).append({
        "id": id_,
        "port": port,
        "workspace": f"workspace/{id_}",
        "telegram_token_env": telegram_token_env,
        "telegram_chat_id_env": telegram_chat_id_env,
        "domains": domains,
        "capabilities": capabilities,
        "memory": {"backend": "filesystem"},
    })

    with open(agents_yaml, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"  updated  agents.yaml → added '{id_}' on port {port}")


def scaffold(args: argparse.Namespace) -> None:
    id_ = args.id
    port = args.port
    name = args.name or id_.capitalize()
    env_prefix = args.env_prefix or f"{id_.upper()}_"
    domains = [d.strip() for d in args.domains.split(",")] if args.domains else []
    capabilities = [c.strip() for c in args.capabilities.split(",")] if args.capabilities else []
    telegram_token_env = args.telegram_token_env or f"TELEGRAM_{id_.upper()}_TOKEN"
    telegram_chat_id_env = args.telegram_chat_id_env or "TELEGRAM_ALLOWED_CHAT_ID"
    dry_run = args.dry_run

    validate_id(id_)
    check_conflicts(id_, port, _REPO_ROOT)

    print(f"\nScaffolding agent '{id_}' (name={name}, port={port})\n")

    # --- Python package -------------------------------------------------
    pkg = _REPO_ROOT / "src" / "agents" / id_
    write_file(pkg / "__init__.py", _render_init(id_, name), dry_run)
    write_file(pkg / "run.py", _render_run(id_, name), dry_run)
    write_file(
        pkg / "config.py",
        _render_config(
            id_, name, port, env_prefix,
            telegram_token_env, telegram_chat_id_env,
            domains, capabilities,
        ),
        dry_run,
    )
    write_file(pkg / "tools.py", _render_tools(id_, name), dry_run)

    # --- Workspace documentation ----------------------------------------
    ws = _REPO_ROOT / "workspace" / id_
    ctx = {"name": name, "id": id_}
    write_file(ws / "SOUL.md",      _SOUL_MD.format(**ctx),      dry_run)
    write_file(ws / "AGENTS.md",    _AGENTS_MD.format(**ctx),    dry_run)
    write_file(ws / "USER.md",      _USER_MD.format(**ctx),      dry_run)
    write_file(ws / "TOOLS.md",     _TOOLS_MD.format(**ctx),     dry_run)
    write_file(ws / "MEMORY.md",    _MEMORY_MD.format(**ctx),    dry_run)
    write_file(ws / "HEARTBEAT.md", _HEARTBEAT_MD.format(**ctx), dry_run)
    write_file(ws / "memory" / ".gitkeep", "", dry_run)

    # --- agents.yaml ----------------------------------------------------
    append_agents_yaml(
        id_, port, telegram_token_env, telegram_chat_id_env,
        domains, capabilities, _REPO_ROOT, dry_run,
    )

    # --- Next steps checklist -------------------------------------------
    ID = id_.upper()
    print(textwrap.dedent(f"""
        ✅  Agent '{id_}' scaffolded successfully.

        Next steps:
          1. Edit  src/agents/{id_}/tools.py
               Add domain-specific tools below the "TODO" comment.
               Each tool MUST use _text() for returns and _parse_args() for args.

          2. Edit  src/agents/{id_}/config.py
               Update BUILTIN_CRONS prompts to match the agent's domain.
               Adjust domains/capabilities if needed.

          3. Fill  workspace/{id_}/SOUL.md       — agent identity & values
                   workspace/{id_}/AGENTS.md     — operating manual
                   workspace/{id_}/USER.md       — user context
                   workspace/{id_}/TOOLS.md      — tool reference

          4. Add env vars to .env:
               {telegram_token_env}=<bot-token>
               {telegram_chat_id_env}=<telegram-chat-id>   (if different from default)
               {ID}_WORKSPACE=/app/workspace/{id_}          (optional override)

          5. Rebuild the image and redeploy:
               docker compose build && docker compose up -d

          6. Verify startup:
               docker logs jarvios-platform | grep {id_}
    """))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scaffold a new JarvisOS agent with all platform fixes and core tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/new_agent.py alice 8003
              python scripts/new_agent.py alice 8003 --domains finance,accounting --capabilities budget-tracking
              python scripts/new_agent.py alice 8003 --name Alice --env-prefix ALICE_
              python scripts/new_agent.py alice 8003 --dry-run
        """),
    )
    parser.add_argument("id",   help="Agent ID (lowercase Python identifier, e.g. 'alice')")
    parser.add_argument("port", type=int, help="HTTP port (e.g. 8003)")
    parser.add_argument("--name",               help="Display name (default: capitalized id)")
    parser.add_argument("--env-prefix",         help="Env var prefix (default: {ID}_)")
    parser.add_argument("--domains",            help="Comma-separated domains (e.g. 'finance,tax')")
    parser.add_argument("--capabilities",       help="Comma-separated capabilities")
    parser.add_argument("--telegram-token-env", help="Env var name for Telegram bot token")
    parser.add_argument("--telegram-chat-id-env", help="Env var name for allowed chat id")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without writing")
    args = parser.parse_args()
    scaffold(args)


if __name__ == "__main__":
    main()
