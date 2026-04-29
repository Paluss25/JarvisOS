"""In-process MCP server exposing Jarvis custom tools to the claude-agent-sdk.

Tools:
  perplexity_search — Web search via Perplexity AI
  daily_log         — Append to today's memory log
  memory_search     — Text search across MEMORY.md + memory/*.md
  memory_get        — Read a specific memory file from workspace
  platform_health   — Docker container state + healthcheck + all supervisord process states
  send_message      — Send a message to another agent via Redis pub/sub
  cron_create       — Create a scheduled task
  cron_list         — List scheduled tasks
  cron_update       — Update a scheduled task
  cron_delete       — Delete a scheduled task
  scaffold_agent    — Scaffold a new agent in the platform repo (SSH to host)
"""

import asyncio
import json
import logging
import os
import re
import shlex
from pathlib import Path

import httpx  # used by perplexity_search

logger = logging.getLogger(__name__)


def _parse_args(args) -> dict:
    """Normalize tool args — older SDK versions pass a JSON string instead of a dict."""
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return args if isinstance(args, dict) else {}


def _text(s: str) -> dict:
    """Wrap a plain string as an MCP text content response."""
    return {"content": [{"type": "text", "text": str(s)}]}


_PERPLEXITY_BASE = "https://api.perplexity.ai"
_DEFAULT_MODEL = "sonar"
_MAX_TOKENS = 1024

# SDK imports — may need adjustment depending on installed claude-agent-sdk version
try:
    from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    create_sdk_mcp_server = None
    sdk_tool = None


def create_jarvis_mcp_server(workspace_path: Path, redis_a2a=None):
    """Build and return the in-process MCP server with Jarvis custom tools.

    Returns None if the SDK MCP server API is not available.
    """
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
        return None

    # --- Tool definitions -----------------------------------------------

    @sdk_tool(
        "perplexity_search",
        "Search the web using Perplexity AI for real-time information. Use this for current events, facts, or any topic requiring up-to-date information.",
        {"query": str},
    )
    async def perplexity_search(args: dict) -> dict:
        """Search via Perplexity API (sonar model) and return the answer."""
        args = _parse_args(args)
        query = args.get("query", "")
        if not query:
            return _text("No query provided.")

        api_key = os.environ.get("PERPLEXITY_API_KEY", "")
        if not api_key:
            return _text("Perplexity API key not configured (PERPLEXITY_API_KEY env var missing).")

        payload = {
            "model": _DEFAULT_MODEL,
            "messages": [
                {"role": "system", "content": "Be precise and concise. Cite your sources."},
                {"role": "user", "content": query},
            ],
            "max_tokens": _MAX_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{_PERPLEXITY_BASE}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                answer = data["choices"][0]["message"]["content"]

            # Log to daily memory
            try:
                from agent_runner.memory.daily_logger import DailyLogger
                DailyLogger(workspace_path).log(f"[SEARCH] {query[:120]}")
            except Exception:
                pass

            logger.info("perplexity: search completed for %r", query[:80])
            return _text(answer)

        except Exception as exc:
            logger.error("perplexity: search failed — %s", exc)
            return _text(f"Search failed: {exc}")

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's Jarvis memory log. Use this to record significant events, decisions, or information worth remembering. message is required.",
        {"message": {"type": "string", "default": ""}},
    )
    async def daily_log(args: dict) -> dict:
        """Append a timestamped entry to today's memory/YYYY-MM-DD.md."""
        args = _parse_args(args)
        message = args.get("message", "")
        if not message:
            return _text("No message provided.")
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(message)
            return _text(f"Logged: {message[:80]}")
        except Exception as exc:
            logger.error("daily_log: failed — %s", exc)
            return _text(f"Failed to log: {exc}")

    @sdk_tool(
        "memory_search",
        "Search across long-term memory (MEMORY.md) and all daily logs (memory/*.md) using text matching. "
        "Use this to recall past events, decisions, preferences, or facts. "
        "Results include the matching lines with surrounding context, most recent files first.",
        {"query": str, "top_k": {"type": "integer", "default": 5}},
    )
    async def memory_search(args: dict) -> dict:
        """Text search across MEMORY.md + memory/*.md, most recent first."""
        args = _parse_args(args)
        query = args.get("query", "").strip()
        if not query:
            return _text("No query provided.")

        top_k = int(args.get("top_k") or 5)
        query_lower = query.lower()

        # Collect files: all dated logs (newest first) + MEMORY.md at the end
        memory_dir = workspace_path / "memory"
        dated_files = sorted(memory_dir.glob("*.md"), reverse=True) if memory_dir.exists() else []
        files_to_search = list(dated_files) + [workspace_path / "MEMORY.md"]

        results = []
        for f in files_to_search:
            if not f.exists():
                continue
            try:
                lines = f.read_text(encoding="utf-8").split("\n")
            except OSError:
                continue

            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    # ±2 lines context
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    snippet = "\n".join(lines[start:end])
                    results.append(f"**{f.name}** (line {i + 1}):\n```\n{snippet}\n```")
                    if len(results) >= top_k:
                        break
            if len(results) >= top_k:
                break

        if not results:
            return _text(f"No results found for '{query}'.")

        return _text("\n\n---\n\n".join(results))

    @sdk_tool(
        "memory_get",
        "Read a specific memory file from the workspace. "
        "Use path relative to workspace root, e.g. 'MEMORY.md' or 'memory/2026-04-16.md'. "
        "Optionally specify start_line and num_lines to read a slice.",
        {"path": str, "start_line": {"type": "integer", "default": 1}, "num_lines": {"type": "integer", "default": 50}},
    )
    async def memory_get(args: dict) -> dict:
        """Read a workspace memory file, optionally sliced by line range."""
        args = _parse_args(args)
        rel_path = args.get("path", "").strip()
        if not rel_path:
            return _text("No path provided.")

        target = (workspace_path / rel_path).resolve()
        try:
            target.relative_to(workspace_path.resolve())
        except ValueError:
            return _text("Access denied: path is outside the workspace directory.")

        if not target.exists():
            return _text(f"File not found: {rel_path}")

        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return _text(f"Error reading {rel_path}: {exc}")

        start_line = args.get("start_line")
        num_lines = args.get("num_lines")

        if start_line is not None or num_lines is not None:
            lines = content.split("\n")
            s = int(start_line or 1) - 1  # 1-indexed → 0-indexed
            n = int(num_lines) if num_lines is not None else len(lines)
            content = "\n".join(lines[s: s + n])

        return _text(content)

    # --- A2A send_message (Redis pub/sub) -----------------------------------

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _send_message_fn = create_send_message_tool("ceo", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Use 'to' to specify the target agent ID (e.g. 'dos'). "
            "'message' is the natural language request to send.",
            {"to": str, "message": str},
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
        "schedule format: 'daily@HH:MM' | 'weekly@DOW@HH:MM' (mon/tue/.../sun) | 'once@YYYY-MM-DD@HH:MM'. "
        "All times are Europe/Rome (CET/CEST). "
        "telegram_notify: set to true to receive a Telegram message with the result.",
        {"name": str, "schedule": str, "prompt": str, "session_id": str, "telegram_notify": bool},
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
            return _text(f"Created cron '{entry.name}' (id={entry.id}, schedule={entry.schedule})")
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool(
        "cron_list",
        "List all scheduled tasks (built-in and user-created) with their current status.",
        {},
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
                    f"- **{e.name}** (id={e.id}){builtin_tag}\n"
                    f"  schedule={e.schedule}, {enabled}, last={status}\n"
                    f"  telegram_notify={e.telegram_notify}"
                )
            return _text("\n\n".join(lines))
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool(
        "cron_update",
        "Update a scheduled task by its id. "
        "Updatable fields: name, schedule, prompt, session_id, telegram_notify, enabled.",
        {"id": str, "name": str, "schedule": str, "prompt": str,
         "session_id": str, "telegram_notify": bool, "enabled": bool},
    )
    async def cron_update(args: dict) -> dict:
        args = _parse_args(args)
        cron_id = args.get("id", "").strip()
        if not cron_id:
            return _text("id is required.")
        updates = {k: v for k, v in args.items() if k != "id" and v is not None}
        if not updates:
            return _text("No fields to update.")
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            entry = store.update(cron_id, **updates)
            return _text(f"Updated cron '{entry.name}' (id={entry.id})")
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool(
        "cron_delete",
        "Delete a user-created scheduled task by its id. "
        "Built-in tasks cannot be deleted — use cron_update with enabled=false to disable them.",
        {"id": str},
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
            return _text(f"Deleted cron id={cron_id}")
        except Exception as exc:
            return _text(f"Error: {exc}")

    # --- Platform management --------------------------------------------

    @sdk_tool(
        "scaffold_agent",
        "Scaffold a new agent in the JarvisOS platform repo on the Docker host. "
        "Creates the Python package (src/agents/<id>/), workspace files, and appends the entry to agents.yaml. "
        "Runs on the host machine via SSH so changes persist in the git repo. "
        "A docker rebuild + redeploy is required after scaffolding to activate the new agent. "
        "Use dry_run=true to preview what would be created without writing anything. "
        "Env overrides: PLATFORM_SSH_HOST (default paluss@10.10.200.139), "
        "PLATFORM_REPO_PATH (default /home/paluss/docker/compose/jarvisOS).",
        {"id": str, "port": int, "name": str, "env_prefix": str, "dry_run": bool},
    )
    async def scaffold_agent(args: dict) -> dict:
        """SSH to the Docker host and run scripts/new_agent.py in the platform repo."""
        args = _parse_args(args)

        agent_id = args.get("id", "").strip()
        port = args.get("port")
        if not agent_id:
            return _text("id is required.")
        if port is None:
            return _text("port is required.")

        if not re.match(r'^[a-z][a-z0-9_]*$', agent_id):
            return _text(
                "id must start with a lowercase letter and contain only "
                "lowercase letters, digits, and underscores."
            )

        try:
            port_int = int(port)
        except (TypeError, ValueError):
            return _text("port must be an integer.")

        host_ssh = os.environ.get("PLATFORM_SSH_HOST", "paluss@10.10.200.139")
        repo_path = os.environ.get(
            "PLATFORM_REPO_PATH",
            "/home/paluss/docker/compose/jarvisOS",
        )
        script = f"{repo_path}/scripts/new_agent.py"

        cmd_parts = ["python3", script, agent_id, str(port_int)]

        name = args.get("name", "").strip()
        if name:
            cmd_parts += ["--name", name]

        env_prefix = args.get("env_prefix", "").strip()
        if env_prefix:
            cmd_parts += ["--env-prefix", env_prefix]

        if args.get("dry_run"):
            cmd_parts.append("--dry-run")

        # Build the remote command string, shell-quoting each part so spaces/specials are safe
        remote_cmd = " ".join(shlex.quote(p) for p in cmd_parts)

        # Strict host-key check against ~/.ssh/known_hosts — operator must have
        # pre-seeded the entry. This prevents MITM/DNS-poisoning during scaffold.
        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "BatchMode=yes",       # fail immediately if no key auth
            "-o", "UserKnownHostsFile=/root/.ssh/known_hosts",
            "-i", "/root/.ssh/id_ed25519",
            host_ssh,
            remote_cmd,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                err = stderr_text or stdout_text or "unknown error"
                logger.error(
                    "scaffold_agent: SSH command failed (rc=%d) — %s",
                    proc.returncode, err[:300],
                )
                return _text(f"scaffold_agent failed (exit {proc.returncode}):\n{err}")

            if stderr_text:
                logger.warning("scaffold_agent: stderr — %s", stderr_text[:200])

            logger.info("scaffold_agent: scaffolded '%s' on %s", agent_id, host_ssh)
            return _text(stdout_text or "Done.")

        except asyncio.TimeoutError:
            return _text("scaffold_agent timed out after 60 seconds.")
        except Exception as exc:
            logger.error("scaffold_agent: unexpected error — %s", exc)
            return _text(f"scaffold_agent error: {exc}")

    # --- Platform health ------------------------------------------------

    @sdk_tool(
        "platform_health",
        "Get a unified health snapshot of the jarvios-platform container: "
        "Docker container state + healthcheck result + all supervisord process states. "
        "Use this to check which agents are alive, diagnose a crashed process, or verify "
        "platform health before delegating tasks. No arguments required.",
        {},
    )
    async def platform_health(args: dict) -> dict:
        proxy = os.environ.get("DOCKER_PROXY_URL", "http://socket-proxy:2375")
        container = "jarvios-platform"
        lines: list[str] = []

        # Docker layer: container state + healthcheck
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{proxy}/containers/{container}/json")
                if resp.status_code == 200:
                    d = resp.json()
                    state = d.get("State", {})
                    lines.append(
                        f"Container: {state.get('Status', '?')} "
                        f"(exit {state.get('ExitCode', '?')})"
                    )
                    hc = state.get("Health", {})
                    if hc:
                        lines.append(f"Healthcheck: {hc.get('Status', 'n/a')}")
                        log = hc.get("Log") or []
                        if log:
                            last = log[-1]
                            out = (last.get("Output") or "").strip()[:120]
                            lines.append(
                                f"  Last check: exit {last.get('ExitCode', '?')}"
                                + (f" — {out}" if out else "")
                            )
                elif resp.status_code == 404:
                    lines.append(f"Container '{container}' not found via socket proxy.")
                else:
                    lines.append(f"Docker API error: {resp.status_code}")
        except Exception as exc:
            lines.append(f"Cannot reach socket proxy ({proxy}): {exc}")

        # Supervisord layer: per-process states via Unix socket
        try:
            from platform_api.supervisord_rpc import SupervisorClient
            procs = SupervisorClient().get_all_process_info()
            lines.append("")
            lines.append("Processes:")
            for p in procs:
                name = p.get("name", "?")
                statename = p.get("statename", "?")
                desc = p.get("description", "")
                exitstatus = p.get("exitstatus", "")
                suffix = f" (exit {exitstatus})" if exitstatus and statename not in ("RUNNING",) else ""
                lines.append(f"  {name:<38} {statename:<10} {desc}{suffix}")
        except Exception as exc:
            lines.append(f"Supervisord unavailable: {exc}")

        return _text("\n".join(lines))

    # --- Build server ---------------------------------------------------

    from agent_runner.tools.report_issue import (
        create_report_issue_tool,
        REPORT_ISSUE_DESCRIPTION,
        REPORT_ISSUE_SCHEMA,
    )

    _report_issue_fn = create_report_issue_tool("ceo")

    @sdk_tool("report_issue", REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA)
    async def report_issue(args: dict) -> dict:
        return await _report_issue_fn(args)

    all_tools = [
        perplexity_search, daily_log, memory_search, memory_get,
        platform_health,
        cron_create, cron_list, cron_update, cron_delete,
        scaffold_agent, report_issue,
    ]
    if send_message is not None:
        all_tools.append(send_message)
    try:
        server = create_sdk_mcp_server(name="ceo-tools", tools=all_tools)
        logger.info("mcp_server: in-process MCP server created with %d tools", len(all_tools))
        return server
    except Exception as exc:
        logger.error("mcp_server: failed to create server — %s", exc)
        return None
