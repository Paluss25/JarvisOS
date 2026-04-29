"""HealthCoachAgent — generates post-meal coaching notes.

Queries daily_summaries for running totals and nutrition_goals for the
active target. Generates at most 2 suggestions with positive framing.
"""

import logging
import os
from datetime import date

import asyncpg

from agents.don.models import CoachingNote, FusedResult

logger = logging.getLogger(__name__)

_DEFAULT_CALORIE_GOAL = 2000.0
_DEFAULT_PROTEIN_GOAL = 50.0

# High calorie threshold as fraction of daily goal that a single meal should not exceed
_MEAL_HIGH_CAL_FRACTION = 0.50


class HealthCoachAgent:
    """Generates post-meal coaching notes based on daily progress."""

    def __init__(self):
        self._dsn = os.environ.get("NUTRITION_POSTGRES_URL", "")

    async def coach(self, fused: FusedResult, user_id: int | None = None) -> CoachingNote:
        """Generate a coaching note after a meal is logged.

        Args:
            fused: The just-logged fused meal result.
            user_id: Optional user identifier for personalized goals.

        Returns:
            CoachingNote with a summary and up to 2 suggestions.
        """
        try:
            daily_totals, goals = await self._fetch_context(user_id)
        except Exception as exc:
            logger.warning("Could not fetch coaching context: %s", exc)
            return _fallback_note(fused)

        calories_today = (daily_totals.get("total_calories") or 0) + fused.total_calories
        protein_today = (daily_totals.get("total_protein") or 0) + fused.total_protein

        cal_goal = goals.get("calories_target") or _DEFAULT_CALORIE_GOAL
        prot_goal = goals.get("protein_target") or _DEFAULT_PROTEIN_GOAL

        suggestions = _build_suggestions(
            fused=fused,
            calories_today=calories_today,
            protein_today=protein_today,
            cal_goal=cal_goal,
            prot_goal=prot_goal,
        )

        summary = _build_summary(fused, calories_today, cal_goal)

        return CoachingNote(
            summary=summary,
            suggestions=suggestions[:2],
            calories_today=round(calories_today, 1),
            protein_today=round(protein_today, 1),
        )

    async def _fetch_context(self, user_id: int | None) -> tuple[dict, dict]:
        """Fetch today's running totals and active nutrition goals from DB."""
        conn = await asyncpg.connect(self._dsn)
        try:
            today = date.today()

            # Daily summary for today
            if user_id is not None:
                row = await conn.fetchrow(
                    "SELECT total_calories, total_protein FROM daily_summaries "
                    "WHERE summary_date = $1 AND user_id = $2",
                    today,
                    user_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT total_calories, total_protein FROM daily_summaries "
                    "WHERE summary_date = $1 ORDER BY id DESC LIMIT 1",
                    today,
                )
            totals = dict(row) if row else {}

            # Active nutrition goal
            if user_id is not None:
                goal_row = await conn.fetchrow(
                    "SELECT calories_target, protein_target FROM nutrition_goals "
                    "WHERE active_from <= $1 AND (active_to IS NULL OR active_to >= $1) "
                    "AND user_id = $2 ORDER BY id DESC LIMIT 1",
                    today,
                    user_id,
                )
            else:
                goal_row = await conn.fetchrow(
                    "SELECT calories_target, protein_target FROM nutrition_goals "
                    "WHERE active_from <= $1 AND (active_to IS NULL OR active_to >= $1) "
                    "ORDER BY id DESC LIMIT 1",
                    today,
                )
            goals = dict(goal_row) if goal_row else {}

        finally:
            await conn.close()

        return totals, goals


# ---------------------------------------------------------------------------
# Coaching logic
# ---------------------------------------------------------------------------

def _build_suggestions(
    fused: FusedResult,
    calories_today: float,
    protein_today: float,
    cal_goal: float,
    prot_goal: float,
) -> list[str]:
    suggestions = []

    # Calorie check
    remaining_cal = cal_goal - calories_today
    if calories_today > cal_goal:
        over = calories_today - cal_goal
        suggestions.append(
            f"You're {over:.0f} kcal above your daily goal. "
            "A lighter dinner or an extra walk would help balance things out."
        )
    elif fused.total_calories > cal_goal * _MEAL_HIGH_CAL_FRACTION:
        suggestions.append(
            f"This meal used a big chunk of your daily budget. "
            f"You have {remaining_cal:.0f} kcal left — keep the next meals light."
        )

    # Protein check
    protein_gap = prot_goal - protein_today
    if protein_gap > 20:
        suggestions.append(
            f"You still need {protein_gap:.0f} g of protein today. "
            "A snack with Greek yogurt, eggs, or legumes would help you hit your target."
        )
    elif protein_today >= prot_goal:
        suggestions.append("Great job hitting your protein goal today!")

    return suggestions


def _build_summary(fused: FusedResult, calories_today: float, cal_goal: float) -> str:
    pct = int(calories_today / cal_goal * 100) if cal_goal else 0
    meal_cal = round(fused.total_calories)
    return (
        f"Logged {meal_cal} kcal from this meal. "
        f"You've now had {calories_today:.0f} kcal today ({pct}% of your daily goal)."
    )


def _fallback_note(fused: FusedResult) -> CoachingNote:
    return CoachingNote(
        summary=f"Logged {fused.total_calories:.0f} kcal. Keep it up!",
        suggestions=[],
        calories_today=None,
        protein_today=None,
    )
