"""CFO (Warren) MCP server — custom tools exposed to the Claude agent.

Tools:
  daily_log          — Append entry to today's memory log
  memory_search      — Text search across MEMORY.md + memory/*.md
  memory_get         — Read a specific memory file from workspace
  dispatch_worker    — Call a CFO worker runtime (finance / cost / market)
  memory_lookup      — Semantic search across the shared Memory API
  rag_search         — Vector search in the financial knowledge base (RAG API)
  send_message       — Send a message to another agent via Redis pub/sub
  cron_create/list/update/delete — Scheduled task management
"""

import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


try:
    from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    create_sdk_mcp_server = None
    sdk_tool = None


def create_cfo_mcp_server(workspace_path: Path, redis_a2a=None):
    """Build and return the in-process MCP server with CFO custom tools.

    Returns None if the SDK MCP server API is not available.
    """
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
        return None

    # --- Memory tools -------------------------------------------------------

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's Warren memory log. "
        "Use this to record portfolio snapshots, budget findings, cost anomalies, "
        "fiscal actions, and any financial decision worth preserving.",
        {"message": str},
    )
    async def daily_log(args: dict) -> dict:
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
        "Use this to recall past financial analyses, portfolio snapshots, budget deviations, "
        "cost baselines, and fiscal compliance history. "
        "Results include the matching lines with surrounding context, most recent files first.",
        {"query": str, "top_k": int},
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
            return _text(f"No results found for '{query}'.")

        return _text("\n\n---\n\n".join(results))

    @sdk_tool(
        "memory_get",
        "Read a specific memory file from the workspace. "
        "Use path relative to workspace root, e.g. 'MEMORY.md' or 'memory/2026-04-16.md'. "
        "Optionally specify start_line and num_lines to read a slice.",
        {"path": str, "start_line": int, "num_lines": int},
    )
    async def memory_get(args: dict) -> dict:
        args = _parse_args(args)
        rel_path = args.get("path", "").strip()
        if not rel_path:
            return _text("No path provided.")

        target = (workspace_path / rel_path).resolve()
        if not str(target).startswith(str(workspace_path.resolve())):
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

    # --- CFO domain tools ---------------------------------------------------

    @sdk_tool(
        "dispatch_worker",
        "Call a CFO worker runtime to execute a specialized sub-agent task. "
        "runtime: 'finance' | 'cost' | 'market'. "
        "sub_agent: specific sub-agent name (optional — omit to use the runtime default). "
        "task: JSON object with 'goal' (required) and optional 'scope' (period, filters). "
        "Finance sub-agents: ynab-finance, ynab-categorization, btc-fiscal-analysis, "
        "fiscal-730-agent, email-transaction-extraction, finance-reconciliation, merchant-resolution. "
        "Cost sub-agents: ai-cost, power-cost, budget-control, forecast, roi-procurement. "
        "Market sub-agents: polymarket-market-data, polymarket-risk, polymarket-position-sizing, "
        "polymarket-strategy, polymarket-trade-journal. "
        "Returns JSON response from the worker. Workers have a 30s timeout.",
        {"runtime": str, "sub_agent": str, "task": dict},
    )
    async def dispatch_worker(args: dict) -> dict:
        args = _parse_args(args)
        runtime = (args.get("runtime") or "").strip().lower()
        sub_agent = (args.get("sub_agent") or "").strip()
        task = args.get("task") or {}

        if runtime not in ("finance", "cost", "market"):
            return _text("runtime must be one of: finance, cost, market")

        if not task:
            return _text("task is required — provide at minimum {'goal': '...'}.")

        runtime_urls = {
            "finance": os.environ.get("CFO_FINANCE_WORKERS_URL", "").rstrip("/"),
            "cost":    os.environ.get("CFO_COST_WORKERS_URL", "").rstrip("/"),
            "market":  os.environ.get("CFO_MARKET_WORKERS_URL", "").rstrip("/"),
        }

        base_url = runtime_urls[runtime]
        if not base_url:
            return _text(
                f"Worker runtime '{runtime}' is not configured. "
                f"Set CFO_{runtime.upper()}_WORKERS_URL in the environment to enable it."
            )

        # Default sub-agent names when not specified
        default_sub_agents = {
            "finance": "finance-analyzer",
            "cost":    "cost-analyzer",
            "market":  "market-analyzer",
        }
        target = sub_agent if sub_agent else default_sub_agents[runtime]
        url = f"{base_url}/{target}/analyze"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    url,
                    json=task,
                    headers={"Content-Type": "application/json"},
                )
                if not resp.ok:
                    text = resp.text[:300]
                    return _text(
                        f"Worker {runtime}/{target} returned HTTP {resp.status_code}: {text}"
                    )
                data = resp.json()
                return _text(json.dumps(data, ensure_ascii=False, indent=2))

        except httpx.TimeoutException:
            return _text(f"Worker {runtime}/{target} timed out after 30 seconds.")
        except httpx.ConnectError as exc:
            return _text(f"Cannot reach worker {runtime} at {base_url}: {exc}")
        except Exception as exc:
            logger.error("dispatch_worker[%s/%s]: error — %s", runtime, target, exc)
            return _text(f"dispatch_worker error: {exc}")

    @sdk_tool(
        "memory_lookup",
        "Semantic search across the shared Memory API for past financial analyses. "
        "Use this to recall portfolio valuations, budget reports, cost analyses, "
        "Polymarket P&L summaries, and fiscal report history. "
        "query: natural language search query (be specific — include period, asset, metric). "
        "Returns the most relevant past findings with timestamps and context.",
        {"query": str},
    )
    async def memory_lookup(args: dict) -> dict:
        args = _parse_args(args)
        query = (args.get("query") or "").strip()
        if not query:
            return _text("query is required.")

        memory_api_url = os.environ.get("MEMORY_API_URL", "").rstrip("/")
        if not memory_api_url:
            return _text(
                "Memory API is not configured (MEMORY_API_URL env var missing). "
                "Use memory_search to search local filesystem memory instead."
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{memory_api_url}/memory/query",
                    json={
                        "user_id": "cfo",
                        "session_id": "cfo",
                        "query": query,
                        "collection": "cfo",
                        "top_k": 5,
                        "strategy": "hybrid",
                    },
                    headers={"Content-Type": "application/json"},
                )
                if not resp.ok:
                    return _text(f"Memory API returned HTTP {resp.status_code}: {resp.text[:200]}")

                body = resp.json()
                sources = body.get("sources", [])
                if not sources:
                    return _text(f"No results found for '{query}'.")

                lines = []
                for item in sources:
                    chunk = item.get("chunk") or item.get("content") or ""
                    if chunk:
                        lines.append(chunk)
                return _text("\n\n---\n\n".join(lines))

        except httpx.TimeoutException:
            return _text("Memory API timed out.")
        except Exception as exc:
            logger.error("memory_lookup: error — %s", exc)
            return _text(f"memory_lookup error: {exc}")

    @sdk_tool(
        "rag_search",
        "Vector search in the financial knowledge base (RAG API). "
        "Use this to find procedures, policies, past reports, and domain documentation. "
        "query: search query. "
        "collection: 'finance' (default — YNAB, crypto, Polymarket, fiscal docs) | "
        "'homelab-v2' (infrastructure cost docs, node specs, power data) | "
        "'general' (broader knowledge). "
        "Returns relevant document excerpts with source references.",
        {"query": str, "collection": str},
    )
    async def rag_search(args: dict) -> dict:
        args = _parse_args(args)
        query = (args.get("query") or "").strip()
        collection = (args.get("collection") or "finance").strip()

        if not query:
            return _text("query is required.")

        rag_api_url = os.environ.get("RAG_API_URL", "").rstrip("/")
        if not rag_api_url:
            return _text(
                "RAG API is not configured (RAG_API_URL env var missing). "
                "The financial knowledge base is unavailable."
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{rag_api_url}/query",
                    json={
                        "query": query,
                        "collection": collection,
                        "top_k": 5,
                        "use_hybrid": True,
                        "use_reranking": True,
                    },
                    headers={"Content-Type": "application/json"},
                )
                if not resp.ok:
                    return _text(f"RAG API returned HTTP {resp.status_code}: {resp.text[:200]}")

                data = resp.json()
                return _text(json.dumps(data, ensure_ascii=False, indent=2))

        except httpx.TimeoutException:
            return _text("RAG API timed out.")
        except Exception as exc:
            logger.error("rag_search: error — %s", exc)
            return _text(f"rag_search error: {exc}")

    # --- A2A send_message ---------------------------------------------------

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _send_message_fn = create_send_message_tool("cfo", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Use 'to' to specify the target agent ID (e.g. 'ceo' for the CEO). "
            "'message' is the natural language request to send. "
            "Use for executive briefings, HITL approvals for financial actions, "
            "or cross-domain escalation.",
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
        "Create a new scheduled financial task. "
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

    # --- Build server -------------------------------------------------------
    from agent_runner.tools.report_issue import create_report_issue_tool, REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA

    @sdk_tool("report_issue", REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA)
    async def report_issue(args: dict) -> dict:
        return await create_report_issue_tool("cfo")(args)

    all_tools = [
        daily_log, memory_search, memory_get,
        dispatch_worker, memory_lookup, rag_search,
        cron_create, cron_list, cron_update, cron_delete, report_issue,
    ]
    if send_message is not None:
        all_tools.append(send_message)

    try:
        server = create_sdk_mcp_server(name="cfo-tools", tools=all_tools)
        logger.info(
            "mcp_server: CFO (Warren) tools registered (%d tools)",
            len(all_tools),
        )
        return server
    except Exception as exc:
        logger.error("mcp_server: failed to create server — %s", exc)
        return None
