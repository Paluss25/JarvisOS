"""DON fast-path A2A actions — direct Python handlers that bypass the LLM.

Supported actions (keyed by payload["action"]):
  log_meal — INSERT a meal record with Haiku estimates, then refine macros in background.

Macro pipeline:
  1. INSERT immediately with Haiku estimates (response ≤ 2s)
  2. asyncio.create_task → _refine_meal_macros (background, no impact on response)
     a. FatSecret search per ingredient (parallel)
     b. USDA fallback per ingredient (parallel)
     c. If ≥ 70% coverage: UPDATE meals SET macros = API data
  3. DB gets precise data within ~10s; user response is always fast.

Usage in app.py:
    config.a2a_fast_path = handle_a2a_action
"""

import asyncio
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DON_WORKSPACE = Path(os.environ.get("DON_WORKSPACE_PATH", "/app/workspace/don"))
_API_TIMEOUT = 10.0   # seconds — generous timeout for background refinement

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


def _coerce_params(params: list | None) -> list | None:
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


# ---------------------------------------------------------------------------
# API enrichment helpers
# ---------------------------------------------------------------------------

async def _lookup_single_ingredient(food: str, quantity_g: float) -> dict | None:
    """Open Food Facts (Italian) → FatSecret → USDA fallback chain.

    OFF is tried first: better coverage for Italian packaged products and
    no API key required. FatSecret and USDA are fallbacks for generic foods.
    Returns scaled macros or None.
    """
    from agents.don.clients.openfoodfacts import OpenFoodFactsClient
    from agents.don.clients.fatsecret import FatSecretClient
    from agents.don.clients.usda import USDAClient

    try:
        off = OpenFoodFactsClient()
        results = await off.search_foods(food, max_results=1)
        if results:
            hit = results[0]
            scale = quantity_g / hit.serving_g if hit.serving_g > 0 else quantity_g / 100
            return {
                "calories": round(hit.calories * scale, 1),
                "protein_g": round(hit.protein * scale, 1),
                "carbs_g": round(hit.carbs * scale, 1),
                "fat_g": round(hit.fat * scale, 1),
                "source": "openfoodfacts",
            }
    except Exception as exc:
        logger.debug("fast_actions: OFF miss for '%s' — %s", food, exc)

    try:
        fs = FatSecretClient()
        results = await fs.search_foods(food, max_results=1)
        if results:
            hit = results[0]
            scale = quantity_g / hit.serving_g if hit.serving_g > 0 else quantity_g / 100
            return {
                "calories": round(hit.calories * scale, 1),
                "protein_g": round(hit.protein * scale, 1),
                "carbs_g": round(hit.carbs * scale, 1),
                "fat_g": round(hit.fat * scale, 1),
                "source": "fatsecret",
            }
    except Exception as exc:
        logger.debug("fast_actions: FatSecret miss for '%s' — %s", food, exc)

    try:
        usda = USDAClient()
        results = await usda.search_foods(food, max_results=1)
        if results:
            hit = results[0]
            scale = quantity_g / hit.serving_g if hit.serving_g > 0 else quantity_g / 100
            return {
                "calories": round(hit.calories * scale, 1),
                "protein_g": round(hit.protein * scale, 1),
                "carbs_g": round(hit.carbs * scale, 1),
                "fat_g": round(hit.fat * scale, 1),
                "source": "usda",
            }
    except Exception as exc:
        logger.debug("fast_actions: USDA miss for '%s' — %s", food, exc)

    return None


async def _enrich_from_api(components: list[dict]) -> dict | None:
    """Parallel lookup of all components. Returns combined macros or None.
    Only uses API result if ≥ 70% of components are matched by count.
    """
    if not components:
        return None

    # Normalize: accept both {"food": ..., "quantity_g": ...} dicts and plain strings
    normalized = []
    for c in components:
        if isinstance(c, dict):
            if c.get("food"):
                normalized.append((c["food"], float(c.get("quantity_g") or 100)))
        elif isinstance(c, str) and c.strip():
            normalized.append((c.strip(), 100.0))

    tasks = [
        _lookup_single_ingredient(food, qty)
        for food, qty in normalized
    ]
    if not tasks:
        return None

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=_API_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("fast_actions: background API lookup timed out after %.1fs", _API_TIMEOUT)
        return None

    hits = [r for r in results if isinstance(r, dict)]
    if not hits:
        return None

    coverage = len(hits) / len(tasks)
    if coverage < 0.7:
        logger.info(
            "fast_actions: API coverage %.0f%% < 70%% (%d/%d) — keeping Haiku estimates",
            coverage * 100, len(hits), len(tasks),
        )
        return None

    misses = len(tasks) - len(hits)
    sources = {h["source"] for h in hits}
    combined = {
        "calories_est": round(sum(h["calories"] for h in hits)),
        "protein_g": round(sum(h["protein_g"] for h in hits), 1),
        "carbs_g": round(sum(h["carbs_g"] for h in hits), 1),
        "fat_g": round(sum(h["fat_g"] for h in hits), 1),
        "confidence_score": 0.92 if misses == 0 else 0.82,
        "source": next(iter(sources)),
    }
    logger.info(
        "fast_actions: API enrichment OK (%.0f%% coverage, %s) — "
        "%.0fkcal P%.1fg C%.1fg F%.1fg",
        coverage * 100, sources,
        combined["calories_est"], combined["protein_g"],
        combined["carbs_g"], combined["fat_g"],
    )
    return combined


async def _refine_meal_macros(meal_id: int, components: list[dict], haiku_kcal: float | None = None) -> None:
    """Background task: update meal row with API-precise macros if available.

    Runs after the INSERT has already responded to COH. No impact on response time.
    Sanity check: if API calories differ from Haiku by more than 2.5x, skip the update
    (likely a regional/non-standard food that the generic DB matched poorly).
    """
    import asyncpg

    url = os.environ.get("NUTRITION_POSTGRES_URL", "")
    if not url:
        return

    api_macros = await _enrich_from_api(components)
    if not api_macros:
        return

    # Sanity check: reject API data if it's wildly different from Haiku estimate
    if haiku_kcal and haiku_kcal > 0:
        ratio = api_macros["calories_est"] / haiku_kcal
        if ratio > 2.5 or ratio < 0.4:
            logger.warning(
                "fast_actions: API calories %s kcal vs Haiku %s kcal (ratio %.1fx) — "
                "sanity check failed, keeping Haiku estimates for meal %s",
                api_macros["calories_est"], haiku_kcal, ratio, meal_id,
            )
            return

    try:
        conn = await asyncpg.connect(url)
        try:
            result = await conn.execute(
                """
                UPDATE meals
                SET calories_est = $1, protein_g = $2, carbs_g = $3,
                    fat_g = $4, confidence_score = $5
                WHERE id = $6
                """,
                api_macros["calories_est"],
                api_macros["protein_g"],
                api_macros["carbs_g"],
                api_macros["fat_g"],
                api_macros["confidence_score"],
                meal_id,
            )
        finally:
            await conn.close()

        logger.info(
            "fast_actions: meal %s refined with %s data — "
            "%.0fkcal P%.1fg C%.1fg F%.1fg (conf %.2f)",
            meal_id, api_macros["source"],
            api_macros["calories_est"], api_macros["protein_g"],
            api_macros["carbs_g"], api_macros["fat_g"],
            api_macros["confidence_score"],
        )
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(_DON_WORKSPACE).log(
                f"[fast_path/{api_macros['source']}] meal {meal_id} refined: "
                f"{api_macros['calories_est']}kcal P{api_macros['protein_g']}g "
                f"C{api_macros['carbs_g']}g F{api_macros['fat_g']}g "
                f"conf={api_macros['confidence_score']:.2f}"
            )
        except Exception:
            pass

    except Exception as exc:
        logger.warning("fast_actions: refinement UPDATE failed for meal %s — %s", meal_id, exc)


# ---------------------------------------------------------------------------
# Core action handlers
# ---------------------------------------------------------------------------

async def _log_meal(payload: dict) -> dict:
    """INSERT a meal record with Haiku estimates, schedule API refinement in background.

    Expected payload fields:
        date              ISO date string, default: today
        meal_type         'breakfast' | 'lunch' | 'dinner' | 'snack', default: 'snack'
        description       str (required)
        components        list of {food, quantity_g} — used for background API refinement
        calories_est      int | None   (Haiku estimate)
        protein_g         float | None (Haiku estimate)
        carbs_g           float | None (Haiku estimate)
        fat_g             float | None (Haiku estimate)
        confidence_score  float 0.0–1.0, default: 0.75
        notes             str | None
    """
    import asyncpg

    url = os.environ.get("NUTRITION_POSTGRES_URL", "")
    if not url:
        return {"ok": False, "error": "NUTRITION_POSTGRES_URL not configured"}

    meal_date = payload.get("date") or date.today().isoformat()
    meal_type = payload.get("meal_type") or "snack"
    description = (payload.get("description") or "").strip()
    components = payload.get("components") or []
    calories_est = payload.get("calories_est")
    protein_g = payload.get("protein_g")
    carbs_g = payload.get("carbs_g")
    fat_g = payload.get("fat_g")
    confidence_score = payload.get("confidence_score") if payload.get("confidence_score") is not None else 0.75
    notes = payload.get("notes")

    if not description:
        return {"ok": False, "error": "description is required"}
    if calories_est is None:
        return {"ok": False, "error": "calories_est is required"}
    missing_macros = [
        name for name, value in (
            ("protein_g", protein_g),
            ("carbs_g", carbs_g),
            ("fat_g", fat_g),
        ) if value is None
    ]
    if missing_macros:
        return {"ok": False, "error": f"missing required macros: {missing_macros}"}

    sql = """
        INSERT INTO meals
            (date, meal_type, description, calories_est, protein_g, carbs_g, fat_g,
             confidence_score, notes, user_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 1)
        RETURNING id
    """
    params = [
        meal_date, meal_type, description,
        calories_est, protein_g, carbs_g, fat_g,
        confidence_score, notes,
    ]

    try:
        conn = await asyncpg.connect(url)
        try:
            row = await conn.fetchrow(sql, *(_coerce_params(params) or []))
            meal_id = row["id"] if row else None
        finally:
            await conn.close()
    except Exception as exc:
        logger.error("fast_actions._log_meal: DB error — %s", exc)
        return {"ok": False, "error": str(exc)}

    logger.info(
        "fast_actions: meal logged id=%s [haiku] '%s' — %.0fkcal",
        meal_id, description[:50], calories_est or 0,
    )

    try:
        from agent_runner.memory.daily_logger import DailyLogger
        DailyLogger(_DON_WORKSPACE).log(
            f"[fast_path/haiku] meal logged id={meal_id}: {description[:80]} "
            f"({meal_type}, ~{calories_est}kcal P{protein_g}g C{carbs_g}g F{fat_g}g "
            f"conf={confidence_score:.2f}) — API refinement queued"
        )
    except Exception as log_exc:
        logger.warning("fast_actions: daily_log failed — %s", log_exc)

    # Fire-and-forget: refine macros with API data in background
    if components and meal_id:
        asyncio.create_task(_refine_meal_macros(meal_id, components, float(calories_est or 0) or None))

    return {
        "ok": True,
        "meal_id": meal_id,
        "macro_source": "haiku",
        "calories_est": calories_est,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "confidence_score": confidence_score,
    }


async def _delete_meal(payload: dict) -> dict:
    """DELETE a meal record by id. Only deletes meals belonging to user_id=1.

    Expected payload fields:
        meal_id   int (required) — id of the meal to delete
    """
    import asyncpg

    url = os.environ.get("NUTRITION_POSTGRES_URL", "")
    if not url:
        return {"ok": False, "error": "NUTRITION_POSTGRES_URL not configured"}

    meal_id = payload.get("meal_id")
    if not meal_id:
        return {"ok": False, "error": "meal_id is required"}

    try:
        conn = await asyncpg.connect(url)
        try:
            result = await conn.execute(
                "DELETE FROM meals WHERE id = $1 AND user_id = 1",
                int(meal_id),
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.error("fast_actions._delete_meal: DB error — %s", exc)
        return {"ok": False, "error": str(exc)}

    deleted = result == "DELETE 1"
    logger.info(
        "fast_actions: meal %s %s",
        meal_id, "deleted" if deleted else "not found (NO-OP)",
    )

    try:
        from agent_runner.memory.daily_logger import DailyLogger
        if deleted:
            DailyLogger(_DON_WORKSPACE).log(
                f"[fast_path/delete] meal {meal_id} deleted"
            )
    except Exception:
        pass

    return {"ok": True, "meal_id": meal_id, "deleted": deleted}


_ACTION_HANDLERS = {
    "log_meal": _log_meal,
    "delete_meal": _delete_meal,
}


async def handle_a2a_action(payload: dict) -> dict | None:
    """Entry point for DON fast-path A2A handler.

    Called from app.py _handle_a2a before agent.query().
    Returns a result dict if payload["action"] is a known fast-path action.
    Returns None to fall through to the LLM for unknown payloads.
    """
    action = payload.get("action")
    if not action or action not in _ACTION_HANDLERS:
        return None
    return await _ACTION_HANDLERS[action](payload)
