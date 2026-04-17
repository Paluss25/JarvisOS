"""Timothy (CIO) MCP server — custom tools exposed to the Claude agent.

Tools:
  daily_log          — Append entry to today's memory log
  memory_search      — Text search across MEMORY.md + memory/*.md
  memory_get         — Read a specific memory file from workspace
  infra_check        — HTTP health check on internal service URLs
  send_message       — Send a message to another agent via Redis pub/sub
  cron_create/list/update/delete — Scheduled task management
"""

import json
import logging
from pathlib import Path

import httpx

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


try:
    from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    create_sdk_mcp_server = None
    sdk_tool = None


def create_timothy_mcp_server(workspace_path: Path, redis_a2a=None):
    """Build and return the in-process MCP server with Timothy custom tools.

    Returns None if the SDK MCP server API is not available.
    """
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
        return None

    # --- Memory tools -------------------------------------------------------

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's Timothy memory log. "
        "Use this to record infrastructure changes, incidents, decisions, findings, and resolved issues.",
        {"message": str},
    )
    async def daily_log(args: dict) -> str:
        args = _parse_args(args)
        message = args.get("message", "")
        if not message:
            return "No message provided."
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(message)
            return f"Logged: {message[:80]}"
        except Exception as exc:
            logger.error("daily_log: failed — %s", exc)
            return f"Failed to log: {exc}"

    @sdk_tool(
        "memory_search",
        "Search across long-term memory (MEMORY.md) and all daily logs (memory/*.md) using text matching. "
        "Use this to recall past incidents, infrastructure changes, decisions, or known issues. "
        "Results include the matching lines with surrounding context, most recent files first.",
        {"query": str, "top_k": int},
    )
    async def memory_search(args: dict) -> str:
        args = _parse_args(args)
        query = args.get("query", "").strip()
        if not query:
            return "No query provided."

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
                lines = f.read_text(encoding="utf-8").split("\n")
            except OSError:
                continue

            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    snippet = "\n".join(lines[start:end])
                    results.append(f"**{f.name}** (line {i + 1}):\n```\n{snippet}\n```")
                    if len(results) >= top_k:
                        break
            if len(results) >= top_k:
                break

        if not results:
            return f"No results found for '{query}'."

        return "\n\n---\n\n".join(results)

    @sdk_tool(
        "memory_get",
        "Read a specific memory file from the workspace. "
        "Use path relative to workspace root, e.g. 'MEMORY.md' or 'memory/2026-04-16.md'. "
        "Optionally specify start_line and num_lines to read a slice.",
        {"path": str, "start_line": int, "num_lines": int},
    )
    async def memory_get(args: dict) -> str:
        args = _parse_args(args)
        rel_path = args.get("path", "").strip()
        if not rel_path:
            return "No path provided."

        target = (workspace_path / rel_path).resolve()
        if not str(target).startswith(str(workspace_path.resolve())):
            return "Access denied: path is outside the workspace directory."

        if not target.exists():
            return f"File not found: {rel_path}"

        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Error reading {rel_path}: {exc}"

        start_line = args.get("start_line")
        num_lines = args.get("num_lines")

        if start_line is not None or num_lines is not None:
            lines = content.split("\n")
            s = int(start_line or 1) - 1  # 1-indexed → 0-indexed
            n = int(num_lines) if num_lines is not None else len(lines)
            content = "\n".join(lines[s: s + n])

        return content

    # --- CIO domain tools ---------------------------------------------------

    @sdk_tool(
        "infra_check",
        "Run HTTP health checks against one or more internal service URLs. "
        "Returns HTTP status code and response time for each URL. "
        "Use this before writing any health report to verify actual service state. "
        "urls: comma-separated list of URLs (e.g. 'http://10.10.200.50/ping,http://10.10.200.62:80'). "
        "timeout: per-request timeout in seconds (default 5).",
        {"urls": str, "timeout": int},
    )
    async def infra_check(args: dict) -> str:
        args = _parse_args(args)
        urls_raw = args.get("urls", "").strip()
        if not urls_raw:
            return "No URLs provided."
        timeout = max(1, int(args.get("timeout") or 5))

        url_list = [u.strip() for u in urls_raw.split(",") if u.strip()]
        results = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            for url in url_list:
                try:
                    import time
                    t0 = time.monotonic()
                    resp = await client.get(url, follow_redirects=True)
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    results.append(f"{url}: HTTP {resp.status_code} ({elapsed_ms}ms)")
                except httpx.TimeoutException:
                    results.append(f"{url}: TIMEOUT after {timeout}s")
                except Exception as exc:
                    results.append(f"{url}: ERROR — {exc}")

        return "\n".join(results)

    # --- A2A send_message (Redis pub/sub) -----------------------------------

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _send_message_fn = create_send_message_tool("timothy", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Use 'to' to specify the target agent ID (e.g. 'jarvis' for the CEO). "
            "'message' is the natural language request to send. "
            "Use this for cross-domain escalation, executive decisions, or business context.",
            {"to": str, "message": str},
        )
        async def send_message(args: dict) -> str:
            args = _parse_args(args)
            return await _send_message_fn(args)
    else:
        send_message = None  # Redis not configured

    # --- Cron tools ---------------------------------------------------------

    @sdk_tool(
        "cron_create",
        "Create a new scheduled IT task. "
        "schedule format: 'daily@HH:MM' | 'weekly@DOW@HH:MM' (mon/tue/.../sun) | 'once@YYYY-MM-DD@HH:MM'. "
        "All times are Europe/Rome (CET/CEST). "
        "telegram_notify: set to true to receive a Telegram message with the result.",
        {"name": str, "schedule": str, "prompt": str, "session_id": str, "telegram_notify": bool},
    )
    async def cron_create(args: dict) -> str:
        args = _parse_args(args)
        name = args.get("name", "").strip()
        schedule = args.get("schedule", "").strip()
        prompt_text = args.get("prompt", "").strip()
        if not name or not schedule or not prompt_text:
            return "name, schedule, and prompt are required."
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
            return f"Created cron '{entry.name}' (id={entry.id}, schedule={entry.schedule})"
        except Exception as exc:
            return f"Error: {exc}"

    @sdk_tool(
        "cron_list",
        "List all scheduled tasks (built-in and user-created) with their current status.",
        {},
    )
    async def cron_list(args: dict) -> str:
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            entries = store.all()
            if not entries:
                return "No scheduled tasks."
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
            return "\n\n".join(lines)
        except Exception as exc:
            return f"Error: {exc}"

    @sdk_tool(
        "cron_update",
        "Update a scheduled task by its id. "
        "Updatable fields: name, schedule, prompt, session_id, telegram_notify, enabled.",
        {"id": str, "name": str, "schedule": str, "prompt": str,
         "session_id": str, "telegram_notify": bool, "enabled": bool},
    )
    async def cron_update(args: dict) -> str:
        args = _parse_args(args)
        cron_id = args.get("id", "").strip()
        if not cron_id:
            return "id is required."
        updates = {k: v for k, v in args.items() if k != "id" and v is not None}
        if not updates:
            return "No fields to update."
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            entry = store.update(cron_id, **updates)
            return f"Updated cron '{entry.name}' (id={entry.id})"
        except Exception as exc:
            return f"Error: {exc}"

    @sdk_tool(
        "cron_delete",
        "Delete a user-created scheduled task by its id. "
        "Built-in tasks cannot be deleted — use cron_update with enabled=false to disable them.",
        {"id": str},
    )
    async def cron_delete(args: dict) -> str:
        args = _parse_args(args)
        cron_id = args.get("id", "").strip()
        if not cron_id:
            return "id is required."
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            store.delete(cron_id)
            return f"Deleted cron id={cron_id}"
        except Exception as exc:
            return f"Error: {exc}"

    # --- Build server -------------------------------------------------------

    all_tools = [
        daily_log, memory_search, memory_get,
        infra_check,
        cron_create, cron_list, cron_update, cron_delete,
    ]
    if send_message is not None:
        all_tools.append(send_message)
    try:
        server = create_sdk_mcp_server(name="timothy-tools", tools=all_tools)
        logger.info(
            "mcp_server: Timothy (CIO) tools registered (%d tools)",
            len(all_tools),
        )
        return server
    except Exception as exc:
        logger.error("mcp_server: failed to create server — %s", exc)
        return None
