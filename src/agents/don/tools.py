"""NutritionDirector MCP server — custom tools exposed to the Claude agent.

Tools:
  daily_log          — Append entry to today's memory log
  memory_search      — Text search across MEMORY.md + memory/*.md
  memory_get         — Read a specific memory file from workspace
  nutrition_query    — SELECT queries against nutrition_data PostgreSQL DB
  nutrition_execute  — INSERT/UPDATE/DELETE operations on nutrition_data
  nutrition_ddl      — CREATE/ALTER schema changes on nutrition_data (bootstrap only)
  analyze_meal_image — Placeholder: delegates to Claude Vision API (P6)
  lookup_barcode     — Placeholder: delegates to Open Food Facts API (P5)
  search_fatsecret   — FatSecret Platform API food search (OAuth2)
  search_usda        — USDA FoodData Central API search
  send_message       — A2A via Redis pub/sub (conditional on redis_a2a)
"""

import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

from agents.don.clients.fatsecret import FatSecretClient
from agents.don.clients.usda import USDAClient

# Module-level singletons — token caching lives inside FatSecretClient
_fatsecret_client = FatSecretClient()
_usda_client = USDAClient()

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


try:
    from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    create_sdk_mcp_server = None
    sdk_tool = None


# ---------------------------------------------------------------------------
# PostgreSQL helpers
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


def _coerce_params(params: list | None) -> list | None:
    """Convert ISO date/datetime strings in params to proper Python types for asyncpg."""
    if not params:
        return params
    out = []
    for p in params:
        if isinstance(p, str):
            if _DATETIME_RE.match(p):
                try:
                    out.append(datetime.fromisoformat(p))
                    continue
                except ValueError:
                    pass
            if _DATE_RE.match(p):
                try:
                    out.append(date.fromisoformat(p))
                    continue
                except ValueError:
                    pass
        out.append(p)
    return out


async def _pg_query(sql: str, params: list | None = None) -> list[dict]:
    """Run a SELECT query against nutrition_data and return rows as list of dicts."""
    import asyncpg
    url = os.environ.get("NUTRITION_POSTGRES_URL", "")
    if not url:
        raise RuntimeError("NUTRITION_POSTGRES_URL not configured")

    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(sql, *(_coerce_params(params) or []))
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _pg_run(sql: str, params: list | None = None) -> str:
    """Run a DML/DDL statement against nutrition_data and return a status string."""
    import asyncpg
    url = os.environ.get("NUTRITION_POSTGRES_URL", "")
    if not url:
        raise RuntimeError("NUTRITION_POSTGRES_URL not configured")

    conn = await asyncpg.connect(url)
    try:
        result = await conn.execute(sql, *(_coerce_params(params) or []))
        return str(result)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------

def create_nutrition_mcp_server(workspace_path: Path, redis_a2a=None):
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
        return None

    # --- Memory tools -------------------------------------------------------

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's NutritionDirector memory log. Use this to record significant nutrition events, meal decisions, dietary flags, or information worth remembering. message is required.",
        {"message": {"type": "string", "default": ""}},
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
        "Search across long-term nutrition memory (MEMORY.md) and all daily logs (memory/*.md) using text matching. "
        "Use this to recall past meal logs, dietary decisions, food preferences, or nutrition flags. "
        "Results include the matching lines with surrounding context, most recent files first.",
        {"query": str, "top_k": {"type": "integer", "default": 5}},
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
        "Read a specific memory file from the NutritionDirector workspace. "
        "Use path relative to workspace root, e.g. 'MEMORY.md' or 'memory/2026-04-16.md'. "
        "Optionally specify start_line and num_lines to read a slice.",
        {"path": str, "start_line": {"type": "integer", "default": 1}, "num_lines": {"type": "integer", "default": 50}},
    )
    async def memory_get(args: dict) -> dict:
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
            s = int(start_line or 1) - 1
            n = int(num_lines) if num_lines is not None else len(lines)
            content = "\n".join(lines[s: s + n])

        return _text(content)

    # --- Nutrition DB tools -------------------------------------------------

    @sdk_tool(
        "nutrition_query",
        "Execute a SELECT query against the nutrition_data PostgreSQL database. "
        "  meals: id, date (DATE), meal_type, description, calories_est, protein_g, carbs_g, fat_g, confidence_score, image_ref, notes, created_at, user_id. "
        "  food_library: id, name, brand, category, serving_size, serving_unit, kcal_per_100, protein_per_100, carbs_per_100, fat_per_100, fiber_per_100, sugar_per_100. "
        "  meal_items: item_id (UUID), meal_id, food_name, canonical_name, portion_g, calories, protein, carbs, fat, match_confidence. "
        "  daily_summaries: date (DATE), total_calories, total_protein, total_carbs, total_fat, meals_logged, training_day. "
        "  nutrition_goals: goal_id (UUID), target_calories, target_protein, target_carbs, target_fat, goal_type, active_from, active_to. "
        "  user_corrections: correction_id (UUID), meal_id, original_food, corrected_food, original_portion_g, corrected_portion_g. "
        "Returns rows as JSON. Only SELECT statements are permitted.",
        {"sql": str, "params": {"type": "array", "items": {}, "default": []}},
    )
    async def nutrition_query(args: dict) -> dict:
        args = _parse_args(args)
        sql = (args.get("sql") or "").strip()
        raw_params = args.get("params") or []
        if isinstance(raw_params, str):
            try:
                raw_params = json.loads(raw_params)
            except Exception:
                raw_params = []
        params = raw_params if isinstance(raw_params, list) else []
        if not sql:
            return _text("No SQL provided.")
        if not sql.upper().startswith("SELECT"):
            return _text("nutrition_query only accepts SELECT statements. Use nutrition_execute for writes.")
        try:
            rows = await _pg_query(sql, params or None)
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("nutrition_query: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "nutrition_execute",
        "Execute an INSERT, UPDATE, or DELETE on the nutrition_data database. "
        "Use for logging meals and any custom nutrition tables. Returns affected row count.",
        {"sql": str, "params": {"type": "array", "items": {}, "default": []}},
    )
    async def nutrition_execute(args: dict) -> dict:
        args = _parse_args(args)
        sql = (args.get("sql") or "").strip()
        raw_params = args.get("params") or []
        if isinstance(raw_params, str):
            try:
                raw_params = json.loads(raw_params)
            except Exception:
                raw_params = []
        params = raw_params if isinstance(raw_params, list) else []
        if not sql:
            return _text("No SQL provided.")
        # Strict allowlist of leading verbs — rejects WITH (CTE), SELECT, DDL,
        # multi-statement payloads, and any other unexpected verb.
        first_word = sql.split()[0].upper() if sql.split() else ""
        _ALLOWED_VERBS = {"INSERT", "UPDATE", "DELETE"}
        if first_word not in _ALLOWED_VERBS:
            return {
                "content": [{"type": "text", "text": (
                    f"nutrition_execute rejects leading verb '{first_word}'. "
                    f"Only {sorted(_ALLOWED_VERBS)} are accepted. "
                    "CTEs (WITH ... DELETE/UPDATE/INSERT), SELECT, and DDL are all blocked."
                )}],
                "is_error": True,
            }
        # Reject multi-statement payloads (defence-in-depth).
        if ";" in sql.rstrip().rstrip(";"):
            return {
                "content": [{"type": "text", "text": (
                    "nutrition_execute rejects multi-statement SQL. Submit one statement at a time."
                )}],
                "is_error": True,
            }
        try:
            result = await _pg_run(sql, params or None)
            return _text(f"OK: {result}")
        except Exception as exc:
            logger.error("nutrition_execute: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Execute error: {exc}"}], "is_error": True}

    @sdk_tool(
        "nutrition_ddl",
        "DISABLED — schema changes must go through reviewed migrations, not the "
        "agent runtime. Calling this tool returns a rejection.",
        {"sql": str},
    )
    async def nutrition_ddl(args: dict) -> dict:
        return _text(
            "nutrition_ddl is disabled. Schema changes require a database "
            "migration reviewed by the operator. Add the change to "
            "projects/cfo-upgrade/cfo-data-service/migrations/ or the "
            "appropriate migration directory and apply it manually."
        )

    # --- API placeholder tools ----------------------------------------------

    @sdk_tool(
        "analyze_meal_image",
        "Analyze a meal image to identify food items and estimate nutritional content. "
        "image_base64: base64-encoded image data. "
        "text_hint: optional text description to guide recognition. "
        "NOTE: Real implementation will be added in P6 (Claude Vision API integration).",
        {"image_base64": str, "text_hint": str},
    )
    async def analyze_meal_image(args: dict) -> dict:
        return _text(
            "Vision analysis tool — delegates to Claude Vision API. "
            "Real implementation will be added in P6."
        )

    @sdk_tool(
        "lookup_barcode",
        "Look up a food product by its barcode (EAN/UPC) and return nutritional information. "
        "barcode: the product barcode string (EAN-13, UPC-A, etc.). "
        "NOTE: Real implementation will be added in P5 (Open Food Facts API integration).",
        {"barcode": str},
    )
    async def lookup_barcode(args: dict) -> dict:
        return _text(
            "Barcode lookup — delegates to Open Food Facts API. "
            "Real implementation will be added in P5."
        )

    @sdk_tool(
        "search_fatsecret",
        "Search the FatSecret food database for nutrition data by food name. "
        "Returns food name, type, and per-100g macro breakdown (calories, fat, carbs, protein). "
        "query: food name or description. max_results: number of results (default 5, max 20).",
        {"query": str, "max_results": int},
    )
    async def search_fatsecret(args: dict) -> dict:
        args = _parse_args(args)
        query = (args.get("query") or "").strip()
        if not query:
            return _text("No query provided.")
        max_results = min(int(args.get("max_results") or 5), 20)
        try:
            foods = await _fatsecret_client.search_foods(query, max_results)
            results = [
                {
                    "food_id": f.food_id,
                    "name": f.food_name,
                    "brand": f.brand,
                    "serving_description": f.serving_description,
                    "serving_g": f.serving_g,
                    "calories": f.calories,
                    "protein_g": f.protein,
                    "carbs_g": f.carbs,
                    "fat_g": f.fat,
                }
                for f in foods
            ]
            return {"content": [{"type": "text", "text": json.dumps(results, ensure_ascii=False, indent=2)}]}
        except Exception as exc:
            logger.error("search_fatsecret: error — %s", exc)
            return {"content": [{"type": "text", "text": f"FatSecret error: {exc}"}], "is_error": True}

    @sdk_tool(
        "search_usda",
        "Search the USDA FoodData Central database for nutrition data by food name. "
        "Returns food name, category, and per-100g nutrients (calories, protein, fat, carbs). "
        "query: food name or description. max_results: number of results (default 5, max 25).",
        {"query": str, "max_results": int},
    )
    async def search_usda(args: dict) -> dict:
        args = _parse_args(args)
        query = (args.get("query") or "").strip()
        if not query:
            return _text("No query provided.")
        max_results = min(int(args.get("max_results") or 5), 25)
        try:
            foods = await _usda_client.search_foods(query, max_results)
            results = [
                {
                    "fdc_id": f.fdc_id,
                    "name": f.food_name,
                    "serving_g": f.serving_g,
                    "calories": f.calories,
                    "protein_g": f.protein,
                    "carbs_g": f.carbs,
                    "fat_g": f.fat,
                }
                for f in foods
            ]
            return {"content": [{"type": "text", "text": json.dumps(results, ensure_ascii=False, indent=2)}]}
        except Exception as exc:
            logger.error("search_usda: error — %s", exc)
            return {"content": [{"type": "text", "text": f"USDA error: {exc}"}], "is_error": True}

    # --- A2A send_message (Redis pub/sub) -----------------------------------

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _send_message_fn = create_send_message_tool("don", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Use 'to' to specify the target agent ID (e.g. 'coh', 'dos', 'ceo'). "
            "'message' is the natural language request to send. "
            "Set wait_response=false for one-way notifications (morning briefings, FYI copies, status broadcasts) — returns immediately without blocking on the receiver's reasoning. Default true preserves request/response semantics: the call blocks until the target agent replies.",
            {"to": str, "message": str, "wait_response": bool},
        )
        async def send_message(args: dict) -> dict:
            args = _parse_args(args)
            return _text(await _send_message_fn(args))
    else:
        send_message = None  # Redis not configured

    from agent_runner.tools.report_issue import (
        create_report_issue_tool,
        REPORT_ISSUE_DESCRIPTION,
        REPORT_ISSUE_SCHEMA,
    )

    _report_issue_fn = create_report_issue_tool("don")

    @sdk_tool("report_issue", REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA)
    async def report_issue(args: dict) -> dict:
        return await _report_issue_fn(args)

    all_tools = [
        daily_log,
        memory_search,
        memory_get,
        nutrition_query,
        nutrition_execute,
        nutrition_ddl,
        analyze_meal_image,
        lookup_barcode,
        search_fatsecret,
        search_usda,
        report_issue,
    ]
    if send_message is not None:
        all_tools.append(send_message)

    try:
        server = create_sdk_mcp_server(name="don-tools", tools=all_tools)
        logger.info(
            "mcp_server: NutritionDirector tools registered (%d tools)",
            len(all_tools),
        )
        return server
    except Exception as exc:
        logger.warning("mcp_server: failed to create server — %s", exc)
        return None
