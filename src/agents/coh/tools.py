"""DrHouse (Chief of Health) MCP server — custom tools exposed to the Claude agent.

Tools:
  daily_log              — Append entry to today's memory log
  memory_search          — Text search across MEMORY.md + memory/*.md
  memory_get             — Read a specific memory file from workspace
  health_query           — Arbitrary SELECT queries against nutrition_data OR sport_metrics
  get_meals              — Typed: meals by date range + optional meal_type filter
  get_body_measurements  — Typed: body measurements by date range
  get_daily_nutrition    — Typed: daily_summaries by date range
  get_nutrition_goals    — Typed: active nutrition goals (calories + macros targets)
  get_recent_activities  — Typed: recent sport activities by date range
  get_training_plan      — Typed: training plan for a given ISO week number
  get_waist_measurements — Typed: waist circumference measurements by date range
  medical_query          — Semantic search across ingested medical PDFs (referti, analysis reports)
"""

import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

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


def _to_float(v) -> float | None:
    """Coerce a value (including numeric strings like '2.0') to float."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v) -> int | None:
    """Coerce a value (including '350' or '350.0') to int."""
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


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


async def _pg_query(url_env: str, env_label: str, sql: str, params: list | None = None) -> list[dict]:
    """Run a SELECT query against a PostgreSQL database and return rows as list of dicts."""
    import asyncpg
    url = os.environ.get(url_env, "")
    if not url:
        raise RuntimeError(f"{url_env} not configured")

    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(sql, *(_coerce_params(params) or []))
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------

def create_drhouse_mcp_server(workspace_path: Path, redis_a2a=None):
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
        return None

    # --- Memory tools -------------------------------------------------------

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's DrHouse health memory log. Use this to record significant health events, decisions, flags, or information worth remembering. message is required.",
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
        "Search across long-term health memory (MEMORY.md) and all daily logs (memory/*.md) using text matching. "
        "Use this to recall past health events, medical notes, decisions, or tracked conditions. "
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
        "Read a specific memory file from the DrHouse workspace. "
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

    # --- Health domain tools ------------------------------------------------

    # Known column name aliases — maps common LLM hallucinations to correct names.
    # Checked pre-flight in health_query before any DB round-trip.
    _COLUMN_ALIASES: dict[str, tuple[str, str]] = {
        # sport DB — activities
        "hr_avg": ("avg_hr", "activities"),
        "heart_rate_avg": ("avg_hr", "activities"),
        "average_hr": ("avg_hr", "activities"),
        # sport DB — training_plan
        "intensity": ("planned_intensity", "training_plan"),
        "intensity_level": ("planned_intensity", "training_plan"),
        # nutrition DB — nutrition_goals (no _g suffix on goal targets)
        "target_protein_g": ("target_protein", "nutrition_goals"),
        "target_carbs_g": ("target_carbs", "nutrition_goals"),
        "target_fat_g": ("target_fat", "nutrition_goals"),
        "start_date": ("active_from", "nutrition_goals"),
        "end_date": ("active_to", "nutrition_goals"),
        "valid_from": ("active_from", "nutrition_goals"),
        "valid_to": ("active_to", "nutrition_goals"),
    }

    @sdk_tool(
        "health_query",
        "Execute a read-only SELECT query against health databases. "
        "database: 'nutrition' — queries nutrition_data PostgreSQL. "
        "  meals: id, date (DATE), meal_type, description, calories_est, protein_g, carbs_g, fat_g, confidence_score, image_ref, notes, created_at, user_id. "
        "  food_library: id, name, brand, category, serving_size, serving_unit, kcal_per_100, protein_per_100, carbs_per_100, fat_per_100, fiber_per_100, sugar_per_100. "
        "  meal_items: item_id (UUID), meal_id, food_name, canonical_name, portion_g, calories, protein, carbs, fat, match_confidence. "
        "  daily_summaries: date (DATE), total_calories, total_protein, total_carbs, total_fat, meals_logged, training_day. "
        "  nutrition_goals: goal_id (UUID), target_calories, target_protein, target_carbs, target_fat, goal_type, active_from, active_to. "
        "  user_corrections: correction_id (UUID), meal_id, original_food, corrected_food, original_portion_g, corrected_portion_g. "
        "database: 'sport' — queries sport_metrics PostgreSQL. "
        "  activities: id, source, type, date (DATE), duration_min, distance_km, avg_hr, max_hr, calories, load_score, elevation_gain_m, avg_cadence, suffer_score, strava_activity_id. "
        "  body_measurements: id, date (DATE), weight_kg, bmi, body_fat_pct, muscle_rate_pct, fat_free_weight_kg, subcutaneous_fat_pct, visceral_fat, body_water_pct, skeletal_muscle_pct, muscle_mass_kg, bone_mass_kg, protein_pct, bmr_kcal, body_age. "
        "  waist_measurements: id, date (DATE), waist_cm, notes, user_id. "
        "  strength_sets: id, date (DATE), activity_id, session_label, exercise_name, exercise_category, set_number, reps, weight_kg, rpe, rest_sec, duration_sec. "
        "  training_plan: id, week_number, day_of_week, session_type, planned_duration, planned_intensity, status, actual_activity_id. "
        "  weekly_summaries: id, week_start (DATE), week_end (DATE), total_sessions, completed_sessions, adherence_pct, avg_weight_kg, avg_body_fat_pct, waist_cm, total_calories_consumed, avg_protein_g. "
        "  goals: id, goal_type, metric, current_value, target_value, unit, status, target_date. "
        "  athlete_profile: id, name, date_of_birth, height_cm, sex. "
        "Only SELECT statements are permitted — DrHouse has read-only access to both databases.",
        {
            "type": "object",
            "properties": {
                "database": {"type": "string"},
                "query": {"type": "string"},
                # params: accept both array and string form (LLM sometimes passes '[]' as a string)
                "params": {
                    "anyOf": [{"type": "array", "items": {}}, {"type": "string"}],
                    "default": [],
                },
            },
            "required": ["database", "query"],
        },
    )
    async def health_query(args: dict) -> dict:
        args = _parse_args(args)
        database = (args.get("database") or "").strip().lower()
        sql = (args.get("query") or "").strip()
        raw_params = args.get("params") or []
        if isinstance(raw_params, str):
            try:
                raw_params = json.loads(raw_params)
            except Exception:
                raw_params = []
        params = raw_params if isinstance(raw_params, list) else []

        if not database:
            return _text("database is required: 'nutrition' or 'sport'.")
        if database not in ("nutrition", "sport"):
            return _text(f"Unknown database '{database}'. Valid values: 'nutrition', 'sport'.")
        if not sql:
            return _text("No query provided.")
        if not sql.upper().startswith("SELECT"):
            return _text(
                "health_query only accepts SELECT statements. "
                "DrHouse has read-only access — use Roger or the appropriate agent for write operations."
            )

        # Pre-flight: detect known column name hallucinations before hitting DB.
        sql_lower = sql.lower()
        corrections = []
        for wrong, (correct, table_hint) in _COLUMN_ALIASES.items():
            if re.search(r"\b" + re.escape(wrong) + r"\b", sql_lower):
                corrections.append(f"  '{wrong}' → '{correct}' (table: {table_hint})")
        # Context-aware: meal_id is a real column on meal_items but NOT on meals.
        # Two wrong patterns we want to catch:
        #   (a) explicit qualification to wrong table: `meals.meal_id` / `m.meal_id` when alias `m` → meals
        #   (b) unqualified `meal_id` with `FROM meals` and no `meal_items` joined in
        wrong_meal_id = False
        if re.search(r"\bmeals\.meal_id\b", sql_lower):
            wrong_meal_id = True
        elif (
            re.search(r"(?<![.\w])meal_id\b", sql_lower)
            and re.search(r"from\s+meals\b(?!_items)", sql_lower)
            and not re.search(r"\bmeal_items\b", sql_lower)
        ):
            wrong_meal_id = True
        if wrong_meal_id:
            corrections.append(
                "  'meal_id' on table 'meals' → use 'meals.id' "
                "(meal_id exists only on meal_items as FK to meals.id)"
            )
        if corrections:
            return {"content": [{"type": "text", "text": (
                "Column name error — use the correct names:\n" +
                "\n".join(corrections) +
                "\n\nFor fixed query patterns prefer the typed tools "
                "(get_nutrition_goals, get_recent_activities, get_training_plan, get_waist_measurements)."
            )}], "is_error": True}

        url_env = "DRHOUSE_POSTGRES_URL" if database == "nutrition" else "DRHOUSE_SPORT_POSTGRES_URL"

        try:
            rows = await _pg_query(url_env, database, sql, params or None)
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("health_query(%s): error — %s", database, exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    # --- Typed convenience read tools ---------------------------------------

    @sdk_tool(
        "get_meals",
        "Get meals for a date or date range. "
        "date_from and date_to are ISO date strings (YYYY-MM-DD). Omit date_to for a single day. "
        "meal_type: optional filter — 'breakfast', 'lunch', 'dinner', 'snack'.",
        {"date_from": str, "date_to": str, "meal_type": str},
    )
    async def get_meals(args: dict) -> dict:
        args = _parse_args(args)
        date_from = (args.get("date_from") or date.today().isoformat()).strip()
        date_to = (args.get("date_to") or date_from).strip()
        meal_type = (args.get("meal_type") or "").strip()
        if meal_type:
            sql = "SELECT * FROM meals WHERE date BETWEEN $1 AND $2 AND meal_type = $3 ORDER BY date, meal_type"
            params = [date_from, date_to, meal_type]
        else:
            sql = "SELECT * FROM meals WHERE date BETWEEN $1 AND $2 ORDER BY date, meal_type"
            params = [date_from, date_to]
        try:
            rows = await _pg_query("DRHOUSE_POSTGRES_URL", "nutrition", sql, params)
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_meals: error — %s", exc)
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
            rows = await _pg_query(
                "DRHOUSE_SPORT_POSTGRES_URL", "sport",
                "SELECT * FROM body_measurements WHERE date BETWEEN $1 AND $2 ORDER BY date",
                [date_from, date_to],
            )
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_body_measurements: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "get_daily_nutrition",
        "Get aggregated daily nutrition summaries for a date range. "
        "date_from and date_to are ISO date strings. Omit date_to for a single day. "
        "Returns total_calories, total_protein, total_carbs, total_fat, meals_logged per day.",
        {"date_from": str, "date_to": str},
    )
    async def get_daily_nutrition(args: dict) -> dict:
        args = _parse_args(args)
        date_from = (args.get("date_from") or date.today().isoformat()).strip()
        date_to = (args.get("date_to") or date_from).strip()
        try:
            rows = await _pg_query(
                "DRHOUSE_POSTGRES_URL", "nutrition",
                "SELECT * FROM daily_summaries WHERE date BETWEEN $1 AND $2 ORDER BY date",
                [date_from, date_to],
            )
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_daily_nutrition: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "get_nutrition_goals",
        "Get the active nutrition targets (calories + macros). "
        "Returns the current goal row from nutrition_goals: target_calories, target_protein, target_carbs, target_fat, goal_type, active_from, active_to. "
        "Use this instead of health_query for the morning briefing and EOD consolidation.",
        {},
    )
    async def get_nutrition_goals(args: dict) -> dict:
        try:
            rows = await _pg_query(
                "DRHOUSE_POSTGRES_URL", "nutrition",
                "SELECT goal_id, goal_type, target_calories, target_protein, target_carbs, target_fat, "
                "active_from, active_to "
                "FROM nutrition_goals "
                "WHERE active_from <= CURRENT_DATE AND (active_to IS NULL OR active_to >= CURRENT_DATE) "
                "ORDER BY active_from DESC LIMIT 1",
            )
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_nutrition_goals: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "get_recent_activities",
        "Get recent sport activities from the activities table. "
        "days: how many days to look back (default 7). "
        "Returns id, source, type, date, duration_min, distance_km, avg_hr, max_hr, calories, load_score, elevation_gain_m. "
        "Use this instead of health_query for the morning briefing and EOD consolidation.",
        {"days": {"type": "integer", "default": 7}},
    )
    async def get_recent_activities(args: dict) -> dict:
        args = _parse_args(args)
        days = int(args.get("days") or 7)
        try:
            rows = await _pg_query(
                "DRHOUSE_SPORT_POSTGRES_URL", "sport",
                "SELECT id, source, type, date, duration_min, distance_km, avg_hr, max_hr, "
                "calories, load_score, elevation_gain_m, avg_cadence, suffer_score "
                "FROM activities "
                f"WHERE date >= CURRENT_DATE - INTERVAL '{days} days' "
                "ORDER BY date DESC",
            )
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_recent_activities: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "get_training_plan",
        "Get the training plan for a given ISO week number. "
        "week_number: ISO week (1–53). Omit to use current week. "
        "Returns id, week_number, day_of_week, session_type, planned_duration, planned_intensity, status, actual_activity_id. "
        "Use this instead of health_query for training plan lookups.",
        {"week_number": {"type": "integer", "default": 0}},
    )
    async def get_training_plan(args: dict) -> dict:
        args = _parse_args(args)
        week = int(args.get("week_number") or 0)
        try:
            rows = await _pg_query(
                "DRHOUSE_SPORT_POSTGRES_URL", "sport",
                "SELECT id, week_number, day_of_week, session_type, planned_duration, planned_intensity, "
                "status, actual_activity_id, notes "
                "FROM training_plan "
                "WHERE week_number = COALESCE($1::int, EXTRACT(WEEK FROM CURRENT_DATE)::int) "
                "ORDER BY day_of_week",
                [week if week > 0 else None],
            )
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_training_plan: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    @sdk_tool(
        "get_waist_measurements",
        "Get waist circumference measurements from the waist_measurements table. "
        "days: how many days to look back (default 30). "
        "NOTE: waist_cm lives in waist_measurements, NOT in body_measurements — use this tool, not health_query.",
        {"days": {"type": "integer", "default": 30}},
    )
    async def get_waist_measurements(args: dict) -> dict:
        args = _parse_args(args)
        days = int(args.get("days") or 30)
        try:
            rows = await _pg_query(
                "DRHOUSE_SPORT_POSTGRES_URL", "sport",
                "SELECT id, date, waist_cm, notes "
                "FROM waist_measurements "
                f"WHERE date >= CURRENT_DATE - INTERVAL '{days} days' "
                "ORDER BY date DESC",
            )
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("get_waist_measurements: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    # --- A2A send_message + log_meal (Redis pub/sub) ------------------------

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _send_message_fn = create_send_message_tool("coh", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Use 'to' to specify the target agent ID (e.g. 'dos', 'ceo'). "
            "'message' is the natural language request to send.",
            {"to": str, "message": str},
        )
        async def send_message(args: dict) -> dict:
            args = _parse_args(args)
            return _text(await _send_message_fn(args))

        @sdk_tool(
            "log_meal",
            "Log a meal to the nutrition database via the fast path (direct DB insert, no LLM sub-call). "
            "YOU (DrHouse) must estimate all macro fields before calling this tool — do not call it with null macros. "
            "description: natural language meal description in the original language. "
            "meal_type: 'breakfast' | 'lunch' | 'dinner' | 'snack'. "
            "date: ISO date string (default: today). "
            "components: list of {food (English name), quantity_g} for each ingredient — used for background API refinement. "
            "calories_est: your total kcal estimate for the whole meal (required). "
            "protein_g / carbs_g / fat_g: your macro estimates in grams (required). "
            "confidence_score: 0.0–1.0, your certainty (0.7 for typical estimates, 0.9 if quantities are explicit). "
            "notes: optional free-text note.",
            {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "meal_type": {"type": "string"},
                    # date and notes are optional — LLM may omit them
                    "date": {"type": "string", "default": ""},
                    "components": {"type": "array", "items": {}, "default": []},
                    # numeric fields: accept both number and string (LLM sometimes passes '2.0' as a string)
                    "calories_est": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "protein_g": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "carbs_g": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "fat_g": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                    "confidence_score": {
                        "anyOf": [{"type": "number"}, {"type": "string"}],
                        "default": 0.75,
                    },
                    "notes": {"type": "string", "default": ""},
                },
                "required": ["description", "meal_type", "calories_est", "protein_g", "carbs_g", "fat_g"],
            },
        )
        async def log_meal(args: dict) -> dict:
            args = _parse_args(args)
            description = (args.get("description") or "").strip()
            meal_type = (args.get("meal_type") or "snack").strip()
            meal_date = (args.get("date") or date.today().isoformat()).strip()
            components = args.get("components") or []
            # Coerce numeric fields — LLM may pass them as strings like '2.0' or '350'
            calories_est = _to_int(args.get("calories_est"))
            protein_g = _to_float(args.get("protein_g"))
            carbs_g = _to_float(args.get("carbs_g"))
            fat_g = _to_float(args.get("fat_g"))
            confidence_score = _to_float(args.get("confidence_score")) if args.get("confidence_score") is not None else 0.75
            notes = args.get("notes") or None

            if not description:
                return _text("description is required.")
            if calories_est is None:
                return _text("calories_est is required — estimate it before calling log_meal.")
            missing_macros = [
                name for name, value in (
                    ("protein_g", protein_g),
                    ("carbs_g", carbs_g),
                    ("fat_g", fat_g),
                ) if value is None
            ]
            if missing_macros:
                return _text(
                    f"Missing required macros: {missing_macros}. "
                    f"Estimate protein_g, carbs_g, and fat_g before calling log_meal."
                )

            # Send structured payload to DON fast path (direct asyncpg INSERT, no LLM)
            payload = json.dumps({
                "action": "log_meal",
                "date": meal_date,
                "meal_type": meal_type,
                "description": description,
                "components": components,
                "calories_est": calories_est,
                "protein_g": protein_g,
                "carbs_g": carbs_g,
                "fat_g": fat_g,
                "confidence_score": confidence_score,
                "notes": notes,
            })
            result_str = await _send_message_fn({"to": "don", "message": payload})

            try:
                result = json.loads(result_str)
                if result.get("ok"):
                    meal_id = result.get("meal_id", "?")
                    kcal = result.get("calories_est", calories_est)
                    prot = result.get("protein_g", protein_g)
                    carbs = result.get("carbs_g", carbs_g)
                    fat = result.get("fat_g", fat_g)
                    conf = result.get("confidence_score", confidence_score)
                    source = result.get("macro_source", "coh")
                    source_tag = "" if source in ("coh", "haiku") else f" [{source}]"
                    return _text(
                        f"✅ Logged (id {meal_id}): {description}\n"
                        f"~{kcal} kcal | P {prot}g | C {carbs}g | F {fat}g "
                        f"(conf {int(float(conf) * 100)}%{source_tag})"
                    )
                else:
                    return _text(f"DON error: {result.get('error', result_str)}")
            except Exception:
                return _text(f"DON response: {result_str}")

        @sdk_tool(
            "delete_meal",
            "Delete a logged meal from the nutrition database by its id. "
            "Use this to remove test entries, duplicates, or incorrectly logged meals. "
            "meal_id: the integer id returned by log_meal or from a health_query.",
            {"meal_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]}},
        )
        async def delete_meal(args: dict) -> dict:
            args = _parse_args(args)
            meal_id = args.get("meal_id")
            if not meal_id:
                return _text("meal_id is required.")

            payload = json.dumps({"action": "delete_meal", "meal_id": int(meal_id)})
            result_str = await _send_message_fn({"to": "don", "message": payload})

            try:
                result = json.loads(result_str)
                if result.get("ok"):
                    if result.get("deleted"):
                        return _text(f"✅ Meal {meal_id} deleted.")
                    else:
                        return _text(f"Meal {meal_id} not found (already deleted or wrong id).")
                else:
                    return _text(f"DON error: {result.get('error', result_str)}")
            except Exception:
                return _text(f"DON response: {result_str}")

    else:
        send_message = None   # Redis not configured
        log_meal = None
        delete_meal = None

    from agent_runner.tools.report_issue import (
        create_report_issue_tool,
        REPORT_ISSUE_DESCRIPTION,
        REPORT_ISSUE_SCHEMA,
    )

    _report_issue_fn = create_report_issue_tool("coh")

    @sdk_tool("report_issue", REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA)
    async def report_issue(args: dict) -> dict:
        return await _report_issue_fn(args)

    _MEMORY_BOX_URL = os.getenv("MEMORY_BOX_URL", "http://10.10.200.139:8000")

    @sdk_tool(
        "medical_query",
        "Semantic search across ingested medical PDF reports (referti, blood tests, diagnostics). "
        "Returns the most relevant excerpts from documents previously ingested via 'memory-box ingest --collection medical'. "
        "Use this when the user references a medical report, lab result, or diagnostic document. "
        "Do NOT infer or fabricate values — only report what is found in the results.",
        {"query": str, "top_k": {"type": "integer", "default": 5}},
    )
    async def medical_query(args: dict) -> dict:
        import httpx
        args = _parse_args(args)
        query = args.get("query", "").strip()
        if not query:
            return _text("No query provided.")
        top_k = _to_int(args.get("top_k")) or 5

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{_MEMORY_BOX_URL}/query",
                    json={"query": query, "collection": "medical", "top_k": top_k},
                )
        except httpx.RequestError as exc:
            return _text(f"medical_query: connection error — {exc}")

        if resp.status_code == 500:
            return _text(
                "No medical documents found. "
                "Ingest a PDF first with: memory-box ingest --file <path> --collection medical"
            )
        if not resp.is_success:
            return _text(f"medical_query: unexpected error {resp.status_code}")

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return _text(f"No results found for '{query}' in medical documents.")

        parts = []
        for i, r in enumerate(results, 1):
            text = r.get("text", "").strip()
            score = r.get("score", 0)
            source = r.get("source", "") or r.get("metadata", {}).get("source", "")
            header = f"[{i}] score={score:.2f}" + (f" — {source}" if source else "")
            parts.append(f"{header}\n{text}")

        return _text("\n\n---\n\n".join(parts))

    all_tools = [daily_log, memory_search, memory_get, health_query,
                 get_meals, get_body_measurements, get_daily_nutrition,
                 get_nutrition_goals, get_recent_activities, get_training_plan, get_waist_measurements,
                 medical_query, report_issue]
    if send_message is not None:
        all_tools.append(send_message)
    if log_meal is not None:
        all_tools.append(log_meal)
    if delete_meal is not None:
        all_tools.append(delete_meal)

    try:
        server = create_sdk_mcp_server(name="coh-tools", tools=all_tools)
        logger.info(
            "mcp_server: DrHouse tools registered (%d tools)",
            len(all_tools),
        )
        return server
    except Exception as exc:
        logger.warning("mcp_server: failed to create server — %s", exc)
        return None
