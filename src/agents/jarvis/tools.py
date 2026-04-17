"""In-process MCP server exposing Jarvis custom tools to the claude-agent-sdk.

Tools:
  perplexity_search      — Web search via Perplexity AI
  daily_log              — Append to today's memory log
  memory_search          — Text search across MEMORY.md + memory/*.md
  memory_get             — Read a specific memory file from workspace
  consult_chief_of_sport — Send a message to Chief Of Sport and get a response
  cron_create            — Create a scheduled task
  cron_list              — List scheduled tasks
  cron_update            — Update a scheduled task
  cron_delete            — Delete a scheduled task
"""

import json
import logging
import os
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


def create_jarvis_mcp_server(workspace_path: Path):
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
    async def perplexity_search(args: dict) -> str:
        """Search via Perplexity API (sonar model) and return the answer."""
        args = _parse_args(args)
        query = args.get("query", "")
        if not query:
            return "No query provided."

        api_key = os.environ.get("PERPLEXITY_API_KEY", "")
        if not api_key:
            return "Perplexity API key not configured (PERPLEXITY_API_KEY env var missing)."

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
            return answer

        except Exception as exc:
            logger.error("perplexity: search failed — %s", exc)
            return f"Search failed: {exc}"

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's Jarvis memory log. Use this to record significant events, decisions, or information worth remembering.",
        {"message": str},
    )
    async def daily_log(args: dict) -> str:
        """Append a timestamped entry to today's memory/YYYY-MM-DD.md."""
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
        "Use this to recall past events, decisions, preferences, or facts. "
        "Results include the matching lines with surrounding context, most recent files first.",
        {"query": str, "top_k": int},
    )
    async def memory_search(args: dict) -> str:
        """Text search across MEMORY.md + memory/*.md, most recent first."""
        args = _parse_args(args)
        query = args.get("query", "").strip()
        if not query:
            return "No query provided."

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
        """Read a workspace memory file, optionally sliced by line range."""
        args = _parse_args(args)
        rel_path = args.get("path", "").strip()
        if not rel_path:
            return "No path provided."

        target = (workspace_path / rel_path).resolve()
        # Security: must stay inside workspace
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

    @sdk_tool(
        "consult_chief_of_sport",
        "Send a message to the Chief Of Sport agent and receive a response. "
        "Use to query sport/fitness/health data, request weekly training status, "
        "or delegate sport-domain tasks to the Chief Of Sport.",
        {"message": str, "session_id": str},
    )
    async def consult_chief_of_sport(args: dict) -> str:
        args = _parse_args(args)
        message = args.get("message", "").strip()
        if not message:
            return "No message provided."
        session_id = args.get("session_id") or "jarvis-to-chief"
        chief_url = os.environ.get("CHIEF_OF_SPORT_URL", "").rstrip("/")
        if not chief_url:
            return "Chief Of Sport URL not configured (CHIEF_OF_SPORT_URL env var missing)."
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{chief_url}/chat",
                    json={"message": message, "session_id": session_id},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "(empty response from Chief Of Sport)")
        except Exception as exc:
            logger.error("consult_chief_of_sport: error — %s", exc)
            return f"Could not reach Chief Of Sport: {exc}"

    # --- Cron tools ---------------------------------------------------------

    @sdk_tool(
        "cron_create",
        "Create a new scheduled task. "
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

    # --- Build server ---------------------------------------------------
    all_tools = [
        perplexity_search, daily_log, memory_search, memory_get, consult_chief_of_sport,
        cron_create, cron_list, cron_update, cron_delete,
    ]
    try:
        server = create_sdk_mcp_server(name="jarvis-tools", tools=all_tools)
        logger.info("mcp_server: in-process MCP server created with %d tools", len(all_tools))
        return server
    except Exception as exc:
        logger.error("mcp_server: failed to create server — %s", exc)
        return None
