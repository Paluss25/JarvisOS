"""Chief Of Sport (Roger) MCP server — custom tools exposed to the Claude agent.

Tools:
  daily_log          — Append entry to today's memory log
  memory_search      — Text search across MEMORY.md + memory/*.md
  memory_get         — Read a specific memory file from workspace
  sport_query          — Arbitrary SELECT queries against sport_metrics PostgreSQL DB
  sport_execute        — INSERT/UPDATE/DELETE operations on sport_metrics
  sport_ddl            — CREATE/ALTER schema changes on sport_metrics
  get_activities       — Typed: activities by date range + optional type filter
  get_body_measurements— Typed: body measurements by date range
  get_strength_sets    — Typed: strength sets by date range + optional exercise filter
  get_weekly_summaries — Typed: weekly summaries by date range
  nutrition_query      — Arbitrary SELECT queries against nutrition_data PostgreSQL DB
  nutrition_execute    — INSERT/UPDATE/DELETE operations on nutrition_data
  nutrition_ddl        — CREATE/ALTER schema changes on nutrition_data
  run_rules_engine     — Deterministic rules evaluation (load, adherence, plateau)
  send_message       — Send a message to another agent via Redis pub/sub
  strava_list_recent — List recent Strava activities
  strava_download    — Download + store a Strava activity
  cron_create/list/update/delete — Scheduled task management
"""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

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
# PostgreSQL helpers (module-level so strava_sync can import them)
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


async def _pg_execute(sql: str, params: list | None = None) -> list[dict]:
    """Run a query against sport_metrics and return rows as list of dicts."""
    import asyncpg
    url = os.environ.get("SPORT_POSTGRES_URL", "")
    if not url:
        raise RuntimeError("SPORT_POSTGRES_URL not configured")

    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(sql, *(_coerce_params(params) or []))
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _pg_run(sql: str, params: list | None = None) -> str:
    """Run a DML statement and return a status string."""
    import asyncpg
    url = os.environ.get("SPORT_POSTGRES_URL", "")
    if not url:
        raise RuntimeError("SPORT_POSTGRES_URL not configured")

    conn = await asyncpg.connect(url)
    try:
        result = await conn.execute(sql, *(_coerce_params(params) or []))
        return str(result)
    finally:
        await conn.close()


async def _nutrition_execute(sql: str, params: list | None = None) -> list[dict]:
    """Run a query against nutrition_data and return rows as list of dicts."""
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


async def _nutrition_run(sql: str, params: list | None = None) -> str:
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
# Rules engine (deterministic)
# ---------------------------------------------------------------------------

_THRESHOLDS = {
    "load_increase_warning_pct": 20,
    "load_increase_critical_pct": 35,
    "min_rest_days_per_week": 1,
    "adherence_low_threshold_pct": 60,
    "adherence_good_threshold_pct": 80,
    "weight_plateau_days": 14,
    "waist_plateau_days": 14,
    "min_protein_g_per_kg": 1.6,
    "confidence_ask_threshold": 0.7,
    "visceral_fat_flag": 10,
}


def _load_thresholds(workspace_path: Path) -> dict:
    t = dict(_THRESHOLDS)
    p = workspace_path / "engine" / "thresholds.json"
    if p.exists():
        try:
            t.update(json.loads(p.read_text()))
        except Exception as exc:
            logger.warning("rules_engine: could not load thresholds.json — %s", exc)
    return t


async def _evaluate_rules(check_type: str, workspace_path: Path) -> dict:
    """Run deterministic rules against current sport_metrics data."""
    th = _load_thresholds(workspace_path)
    flags: list[str] = []
    reason_codes: list[str] = []
    data: dict[str, Any] = {}
    severity = "low"
    recommendations: list[str] = []

    sport_url = os.environ.get("SPORT_POSTGRES_URL", "")
    if not sport_url:
        return {
            "flags": ["db_not_configured"],
            "reason_codes": ["sport_postgres_url_missing"],
            "severity": "info",
            "data": {},
            "recommendations": ["Configure SPORT_POSTGRES_URL to enable rules engine"],
        }

    today = date.today()

    # --- Training load check ---
    if check_type in ("training_load", "weekly", "full"):
        try:
            week_start = today - timedelta(days=today.weekday())
            rows = await _pg_execute(
                "SELECT COALESCE(SUM(load_score), 0) AS total FROM activities "
                "WHERE date >= $1 AND date < $2",
                [week_start, week_start + timedelta(days=7)],
            )
            current_load = float(rows[0]["total"]) if rows else 0

            three_weeks_ago = week_start - timedelta(weeks=3)
            avg_rows = await _pg_execute(
                "SELECT AVG(weekly_total) AS avg FROM ("
                "  SELECT SUM(load_score) AS weekly_total "
                "  FROM activities WHERE date >= $1 AND date < $2 "
                "  GROUP BY DATE_TRUNC('week', date)"
                ") w",
                [three_weeks_ago, week_start],
            )
            avg_load = float(avg_rows[0]["avg"] or 0) if avg_rows else 0

            data["current_load"] = current_load
            data["avg_3w_load"] = avg_load

            if avg_load > 0:
                delta_pct = (current_load - avg_load) / avg_load * 100
                data["load_delta_pct"] = round(delta_pct, 1)

                if delta_pct > th["load_increase_critical_pct"]:
                    flags.append("load_increase_critical")
                    reason_codes.append("acute_chronic_ratio_critical")
                    severity = "high"
                    recommendations.append("Reduce training volume significantly this week")
                elif delta_pct > th["load_increase_warning_pct"]:
                    flags.append("load_increase_warning")
                    reason_codes.append("acute_chronic_ratio_elevated")
                    if severity == "low":
                        severity = "medium"
                    recommendations.append("Consider reducing one intense session")
        except Exception as exc:
            logger.warning("rules_engine: training load check failed — %s", exc)

    # --- Adherence check ---
    if check_type in ("adherence", "weekly", "full"):
        try:
            week_start = today - timedelta(days=today.weekday())
            plan_rows = await _pg_execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status IN ('completed','modified') THEN 1 ELSE 0 END) AS done "
                "FROM training_plan WHERE "
                "day_of_week >= EXTRACT(DOW FROM $1::date) "
                "AND week_number = EXTRACT(WEEK FROM $1::date)",
                [week_start],
            )
            if plan_rows and plan_rows[0]["total"]:
                total = int(plan_rows[0]["total"])
                done = int(plan_rows[0]["done"] or 0)
                adherence_pct = (done / total * 100) if total else 0
                data["adherence_pct"] = round(adherence_pct, 1)
                data["planned_sessions"] = total
                data["completed_sessions"] = done

                if adherence_pct < th["adherence_low_threshold_pct"]:
                    flags.append("adherence_low")
                    reason_codes.append("sessions_below_60pct")
                    if severity == "low":
                        severity = "medium"
                    recommendations.append("Review training schedule — too many skipped sessions")
        except Exception as exc:
            logger.warning("rules_engine: adherence check failed — %s", exc)

    # --- Body composition plateau check ---
    if check_type in ("body_comp", "weekly", "full"):
        try:
            plateau_days = th["weight_plateau_days"]
            cutoff = today - timedelta(days=plateau_days)
            rows = await _pg_execute(
                "SELECT AVG(weight_kg) AS avg_weight, "
                "MAX(weight_kg) AS max_w, MIN(weight_kg) AS min_w "
                "FROM body_measurements WHERE date >= $1",
                [cutoff],
            )
            if rows and rows[0]["avg_weight"]:
                avg_w = float(rows[0]["avg_weight"])
                max_w = float(rows[0]["max_w"])
                min_w = float(rows[0]["min_w"])
                range_kg = max_w - min_w
                data["weight_range_14d_kg"] = round(range_kg, 2)

                if range_kg < 0.5:
                    flags.append("weight_plateau")
                    reason_codes.append(f"weight_delta_below_500g_in_{plateau_days}d")
                    if severity == "low":
                        severity = "medium"
                    recommendations.append("Plateau detected — review caloric deficit and training stimulus")
        except Exception as exc:
            logger.warning("rules_engine: body comp check failed — %s", exc)

    # --- Visceral fat check ---
    if check_type in ("body_comp", "full"):
        try:
            rows = await _pg_execute(
                "SELECT visceral_fat FROM body_measurements ORDER BY date DESC LIMIT 1"
            )
            if rows and rows[0]["visceral_fat"]:
                vf = float(rows[0]["visceral_fat"])
                data["visceral_fat"] = vf
                if vf >= th["visceral_fat_flag"]:
                    flags.append("visceral_fat_elevated")
                    reason_codes.append(f"visceral_fat_gte_{int(th['visceral_fat_flag'])}")
                    severity = "high"
                    recommendations.append("Visceral fat above threshold — prioritize deficit and cardio")
        except Exception as exc:
            logger.warning("rules_engine: visceral fat check failed — %s", exc)

    return {
        "flags": flags,
        "reason_codes": reason_codes,
        "severity": severity,
        "data": data,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------

def create_chief_mcp_server(workspace_path: Path, redis_a2a=None):
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
        return None

    # --- Memory tools -------------------------------------------------------

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's Chief Of Sport memory log. Use this to record significant events, decisions, or information worth remembering. message is required.",
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
        "Search across long-term memory (MEMORY.md) and all daily logs (memory/*.md) using text matching. "
        "Use this to recall past events, decisions, preferences, or facts. "
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
        "Read a specific memory file from the workspace. "
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

    # --- Sport domain tools -------------------------------------------------

    @sdk_tool(
        "sport_query",
        "Execute a SELECT query against the sport_metrics PostgreSQL database. "
        "  activities: id, source, type, date (DATE), duration_min, distance_km, avg_hr, max_hr, calories, load_score, elevation_gain_m, avg_cadence, suffer_score, strava_activity_id. "
        "  body_measurements: id, date (DATE), weight_kg, bmi, body_fat_pct, muscle_rate_pct, fat_free_weight_kg, subcutaneous_fat_pct, visceral_fat, body_water_pct, skeletal_muscle_pct, muscle_mass_kg, bone_mass_kg, protein_pct, bmr_kcal, body_age. "
        "  waist_measurements: id, date (DATE), waist_cm, notes, user_id. "
        "  strength_sets: id, date (DATE), activity_id, session_label, exercise_name, exercise_category, set_number, reps, weight_kg, rpe, rest_sec, duration_sec. "
        "  training_plan: id, week_number, day_of_week, session_type, planned_duration, planned_intensity, status, actual_activity_id. "
        "  weekly_summaries: id, week_start (DATE), week_end (DATE), total_sessions, completed_sessions, adherence_pct, avg_weight_kg, avg_body_fat_pct, waist_cm, total_calories_consumed, avg_protein_g. "
        "  goals: id, goal_type, metric, current_value, target_value, unit, status, target_date. "
        "  athlete_profile: id, name, date_of_birth, height_cm, sex. "
        "Returns rows as JSON. For meal and nutrition data use nutrition_query instead.",
        {"sql": str, "params": {"type": "array", "items": {}, "default": []}},
    )
    async def sport_query(args: dict) -> dict:
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
            return {"content": [{"type": "text", "text": "No SQL provided."}]}
        if not sql.upper().startswith("SELECT"):
            return {"content": [{"type": "text", "text": "sport_query only accepts SELECT statements. Use sport_execute for writes."}]}
        try:
            rows = await _pg_execute(sql, params or None)
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("sport_query: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "sport_execute",
        "Execute an INSERT, UPDATE, or DELETE on the sport_metrics database. "
        "Use for logging activities, meals, measurements. Returns affected row count.",
        {"sql": str, "params": {"type": "array", "items": {}, "default": []}},
    )
    async def sport_execute(args: dict) -> dict:
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
            return {"content": [{"type": "text", "text": "No SQL provided."}]}
        first_word = sql.split()[0].upper() if sql.split() else ""
        _ALLOWED_VERBS = {"INSERT", "UPDATE", "DELETE"}
        if first_word not in _ALLOWED_VERBS:
            return {
                "content": [{"type": "text", "text": (
                    f"sport_execute rejects leading verb '{first_word}'. "
                    f"Only {sorted(_ALLOWED_VERBS)} are accepted. "
                    "CTEs (WITH ...), SELECT, and DDL are all blocked."
                )}],
                "is_error": True,
            }
        if ";" in sql.rstrip().rstrip(";"):
            return {
                "content": [{"type": "text", "text": (
                    "sport_execute rejects multi-statement SQL. Submit one statement at a time."
                )}],
                "is_error": True,
            }
        try:
            result = await _pg_run(sql, params or None)
            return {"content": [{"type": "text", "text": f"OK: {result}"}]}
        except Exception as exc:
            logger.error("sport_execute: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Execute error: {exc}"}], "is_error": True}

    @sdk_tool(
        "sport_ddl",
        "DISABLED — schema changes must go through reviewed migrations, not the "
        "agent runtime. Calling this tool returns a rejection.",
        {"sql": str},
    )
    async def sport_ddl(args: dict) -> dict:
        return _text(
            "sport_ddl is disabled. Schema changes require a database migration "
            "reviewed by the operator."
        )

    @sdk_tool(
        "nutrition_query",
        "Execute a SELECT query against the nutrition_data PostgreSQL database. "
        "  meals: id, date (DATE), meal_type, description, calories_est, protein_g, carbs_g, fat_g, confidence_score, image_ref, notes, created_at, user_id. "
        "  food_library: id, name, brand, category, serving_size, serving_unit, kcal_per_100, protein_per_100, carbs_per_100, fat_per_100, fiber_per_100, sugar_per_100. "
        "  meal_items: item_id (UUID), meal_id, food_name, canonical_name, portion_g, calories, protein, carbs, fat, match_confidence. "
        "  daily_summaries: date (DATE), total_calories, total_protein, total_carbs, total_fat, meals_logged, training_day. "
        "  nutrition_goals: goal_id (UUID), target_calories, target_protein, target_carbs, target_fat, goal_type, active_from, active_to. "
        "Returns rows as JSON.",
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
            rows = await _nutrition_execute(sql, params or None)
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
        first_word = sql.split()[0].upper() if sql.split() else ""
        _ALLOWED_VERBS = {"INSERT", "UPDATE", "DELETE"}
        if first_word not in _ALLOWED_VERBS:
            return {
                "content": [{"type": "text", "text": (
                    f"nutrition_execute rejects leading verb '{first_word}'. "
                    f"Only {sorted(_ALLOWED_VERBS)} are accepted. "
                    "CTEs (WITH ...), SELECT, and DDL are all blocked."
                )}],
                "is_error": True,
            }
        if ";" in sql.rstrip().rstrip(";"):
            return {
                "content": [{"type": "text", "text": (
                    "nutrition_execute rejects multi-statement SQL. Submit one statement at a time."
                )}],
                "is_error": True,
            }
        try:
            result = await _nutrition_run(sql, params or None)
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
            "migration reviewed by the operator."
        )

    # --- Typed convenience read tools ---------------------------------------

    @sdk_tool(
        "get_activities",
        "Get training activities for a date or date range. "
        "date_from and date_to are ISO date strings (YYYY-MM-DD). Omit date_to for a single day. "
        "activity_type: optional filter (e.g. 'Run', 'Ride', 'WeightTraining', 'Swim').",
        {"date_from": str, "date_to": str, "activity_type": str},
    )
    async def get_activities(args: dict) -> dict:
        args = _parse_args(args)
        date_from = (args.get("date_from") or date.today().isoformat()).strip()
        date_to = (args.get("date_to") or date_from).strip()
        activity_type = (args.get("activity_type") or "").strip()
        if activity_type:
            sql = "SELECT * FROM activities WHERE date BETWEEN $1 AND $2 AND type = $3 ORDER BY date"
            params = [date_from, date_to, activity_type]
        else:
            sql = "SELECT * FROM activities WHERE date BETWEEN $1 AND $2 ORDER BY date"
            params = [date_from, date_to]
        try:
            rows = await _pg_execute(sql, params)
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_activities: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "get_body_measurements",
        "Get body measurements for a date or date range. "
        "date_from and date_to are ISO date strings. Omit date_to for a single day. "
        "Returns weight, BMI, body fat, muscle mass, bone mass, BMR and more.",
        {"date_from": str, "date_to": str},
    )
    async def get_body_measurements(args: dict) -> dict:
        args = _parse_args(args)
        date_from = (args.get("date_from") or date.today().isoformat()).strip()
        date_to = (args.get("date_to") or date_from).strip()
        try:
            rows = await _pg_execute(
                "SELECT * FROM body_measurements WHERE date BETWEEN $1 AND $2 ORDER BY date",
                [date_from, date_to],
            )
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_body_measurements: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "get_strength_sets",
        "Get strength training sets for a date or date range. "
        "date_from and date_to are ISO date strings. Omit date_to for a single day. "
        "exercise_name: optional partial-match filter (e.g. 'Squat', 'Bench').",
        {"date_from": str, "date_to": str, "exercise_name": str},
    )
    async def get_strength_sets(args: dict) -> dict:
        args = _parse_args(args)
        date_from = (args.get("date_from") or date.today().isoformat()).strip()
        date_to = (args.get("date_to") or date_from).strip()
        exercise_name = (args.get("exercise_name") or "").strip()
        if exercise_name:
            sql = "SELECT * FROM strength_sets WHERE date BETWEEN $1 AND $2 AND exercise_name ILIKE $3 ORDER BY date, set_number"
            params = [date_from, date_to, f"%{exercise_name}%"]
        else:
            sql = "SELECT * FROM strength_sets WHERE date BETWEEN $1 AND $2 ORDER BY date, exercise_name, set_number"
            params = [date_from, date_to]
        try:
            rows = await _pg_execute(sql, params)
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_strength_sets: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "get_weekly_summaries",
        "Get weekly training and nutrition summaries for a date range. "
        "date_from and date_to are ISO date strings matched against week_start. "
        "Returns sessions completed, adherence, avg weight, avg body fat, avg protein, total training load.",
        {"date_from": str, "date_to": str},
    )
    async def get_weekly_summaries(args: dict) -> dict:
        args = _parse_args(args)
        date_from = (args.get("date_from") or date.today().isoformat()).strip()
        date_to = (args.get("date_to") or date_from).strip()
        try:
            rows = await _pg_execute(
                "SELECT * FROM weekly_summaries WHERE week_start BETWEEN $1 AND $2 ORDER BY week_start",
                [date_from, date_to],
            )
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_weekly_summaries: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "run_rules_engine",
        "Run the deterministic sport rules engine to evaluate current metrics. "
        "check_type options: 'training_load', 'adherence', 'body_comp', 'weekly' (all weekly checks), 'full' (everything). "
        "Returns flags, severity, and recommendations as JSON.",
        {"check_type": str},
    )
    async def run_rules_engine(args: dict) -> dict:
        args = _parse_args(args)
        check_type = (args.get("check_type") or "full")
        valid = {"training_load", "adherence", "body_comp", "weekly", "full"}
        if check_type not in valid:
            return {"content": [{"type": "text", "text": f"Invalid check_type '{check_type}'. Valid: {', '.join(sorted(valid))}"}]}
        try:
            result = await _evaluate_rules(check_type, workspace_path)
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        except Exception as exc:
            logger.error("run_rules_engine: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Rules engine error: {exc}"}], "is_error": True}

    # --- A2A send_message (Redis pub/sub) -----------------------------------

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _send_message_fn = create_send_message_tool("dos", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Use 'to' to specify the target agent ID (e.g. 'coh', 'ceo'). "
            "'message' is the natural language request to send.",
            "Set wait_response=false for one-way notifications (morning briefings, FYI copies, status broadcasts) — returns immediately without blocking on the receiver's reasoning. Default true preserves request/response semantics: the call blocks until the target agent replies.",
            {"to": str, "message": str, "wait_response": bool},
        )
        async def send_message(args: dict) -> dict:
            args = _parse_args(args)
            return _text(await _send_message_fn(args))

        @sdk_tool(
            "push_training_to_calendar",
            "Push the training plan for a given ISO week to the TrainingPlan calendar via MT. "
            "Call this after writing or updating training_plan rows for a week. "
            "week_number is the ISO week number (1-53).",
            {"week_number": {"anyOf": [{"type": "integer"}, {"type": "string"}]}},
        )
        async def push_training_to_calendar(args: dict) -> dict:
            args = _parse_args(args)
            week_number = int(args.get("week_number", 0))
            if not week_number:
                return _text("week_number is required.")
            year = date.today().isocalendar()[0]
            message = f"sync training week {week_number} year {year}"
            result = await _send_message_fn({"to": "mt", "message": message})
            return _text(f"Training plan week {week_number} pushed to calendar. MT response: {result}")

    else:
        send_message = None  # Redis not configured
        push_training_to_calendar = None

    @sdk_tool(
        "strava_list_recent",
        "List the N most recent activities from Strava (live, from Strava API). "
        "Returns id, name, type, date, duration_min, distance_km, avg_hr for each. "
        "Use this BEFORE strava_download when the user says 'last run' — to discover the activity_id. "
        "n: number of activities to fetch (default 5, max 50).",
        {"n": int},
    )
    async def strava_list_recent(args: dict) -> dict:
        n = int(args.get("n") or 5)
        try:
            from agents.dos.strava_sync import list_recent_activities
            activities = await list_recent_activities(n=n)
            return {"content": [{"type": "text", "text": json.dumps(activities, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("strava_list_recent: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Strava list error: {exc}"}], "is_error": True}

    @sdk_tool(
        "strava_download",
        "Download a specific Strava activity by its numeric ID. "
        "Fetches summary + raw sensor streams, saves to sport_metrics PostgreSQL (activities table) "
        "and exports a Parquet file to workspace/knowledge/strava_data/. "
        "Handles token refresh automatically. "
        "activity_id: numeric Strava activity ID (find it in the Strava URL). "
        "user_id: athlete user_id in sport_metrics (default 1 = Paluss).",
        {"activity_id": int, "user_id": int},
    )
    async def strava_download(args: dict) -> dict:
        activity_id = args.get("activity_id")
        user_id = int(args.get("user_id") or os.environ.get("SPORT_USER_ID", "1"))

        if not activity_id:
            return {"content": [{"type": "text", "text": "activity_id is required. Find it in the Strava activity URL."}]}

        try:
            activity_id = int(activity_id)
        except (TypeError, ValueError):
            return {"content": [{"type": "text", "text": f"activity_id must be a number, got: {activity_id}"}]}

        try:
            from agents.dos.strava_sync import fetch_and_store_activity
            result = await fetch_and_store_activity(
                activity_id=activity_id,
                user_id=user_id,
                workspace_path=workspace_path,
            )
            return {"content": [{"type": "text", "text": json.dumps(result, default=str, indent=2)}]}
        except ValueError as exc:
            return {"content": [{"type": "text", "text": f"Not found: {exc}"}], "is_error": True}
        except Exception as exc:
            logger.error("strava_download: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Download error: {exc}"}], "is_error": True}

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

    from agent_runner.tools.report_issue import (
        create_report_issue_tool,
        REPORT_ISSUE_DESCRIPTION,
        REPORT_ISSUE_SCHEMA,
    )

    _report_issue_fn = create_report_issue_tool("dos")

    @sdk_tool("report_issue", REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA)
    async def report_issue(args: dict) -> dict:
        return await _report_issue_fn(args)

    all_tools = [
        daily_log, memory_search, memory_get,
        sport_query, sport_execute, sport_ddl,
        get_activities, get_body_measurements, get_strength_sets, get_weekly_summaries,
        nutrition_query, nutrition_execute, nutrition_ddl,
        run_rules_engine,
        strava_list_recent, strava_download,
        cron_create, cron_list, cron_update, cron_delete, report_issue,
    ]
    if send_message is not None:
        all_tools.append(send_message)
    if push_training_to_calendar is not None:
        all_tools.append(push_training_to_calendar)
    try:
        server = create_sdk_mcp_server(name="chief-tools", tools=all_tools)
        logger.info(
            "mcp_server: Chief Of Sport tools registered (%d tools)",
            len(all_tools),
        )
        return server
    except Exception as exc:
        logger.warning("mcp_server: failed to create server — %s", exc)
        return None
