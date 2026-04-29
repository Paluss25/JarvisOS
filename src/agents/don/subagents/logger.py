"""MealLogAgent — persists FusedResult to the nutrition_data PostgreSQL database."""

import logging
import os
from datetime import date, datetime

import asyncpg

from agents.don.models import ConfirmationStatus, FusedResult, MealRecord, SourceType

logger = logging.getLogger(__name__)


class MealLogAgent:
    """Persists a FusedResult into PostgreSQL nutrition_data tables."""

    def __init__(self):
        self._dsn = os.environ.get("NUTRITION_POSTGRES_URL", "")

    async def log_meal(
        self,
        fused: FusedResult,
        meal_type: str = "other",
        notes: str = "",
        image_ref: str | None = None,
        user_id: int | None = None,
    ) -> MealRecord:
        """Persist a fused meal result and return the saved MealRecord.

        Args:
            fused: The FusedResult to persist.
            meal_type: One of breakfast, lunch, dinner, snack, other.
            notes: Optional free-text note.
            image_ref: Optional reference to the original image (path or URL).
            user_id: Optional user identifier.

        Returns:
            MealRecord populated with the generated meal_id.
        """
        conn = await asyncpg.connect(self._dsn)
        try:
            async with conn.transaction():
                meal_id = await self._insert_meal(
                    conn, fused, meal_type, notes, image_ref, user_id
                )
                await self._insert_items(conn, meal_id, fused)
                await self._upsert_food_library(conn, fused)
        finally:
            await conn.close()

        confirmation_status = _determine_confirmation_status(fused)
        return MealRecord(
            meal_type=meal_type,
            source_type=fused.source_type,
            items=fused.items,
            total_calories=fused.total_calories,
            total_protein=fused.total_protein,
            total_carbs=fused.total_carbs,
            total_fat=fused.total_fat,
            confidence=fused.confidence_score,
            confirmation_status=confirmation_status,
            needs_confirmation=fused.needs_confirmation,
            notes=notes,
        )

    async def _insert_meal(
        self,
        conn: asyncpg.Connection,
        fused: FusedResult,
        meal_type: str,
        notes: str,
        image_ref: str | None,
        user_id: int | None,
    ) -> int:
        """Insert into meals table and return the generated integer PK."""
        row = await conn.fetchrow(
            """
            INSERT INTO meals (
                date, meal_type, description,
                calories_est, protein_g, carbs_g, fat_g,
                confidence_score, image_ref, notes,
                created_at, user_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING id
            """,
            date.today(),
            meal_type,
            _build_description(fused),
            fused.total_calories,
            fused.total_protein,
            fused.total_carbs,
            fused.total_fat,
            fused.confidence_score,
            image_ref,
            notes,
            datetime.now(),
            user_id,
        )
        return row["id"]

    async def _insert_items(
        self,
        conn: asyncpg.Connection,
        meal_id: int,
        fused: FusedResult,
    ) -> None:
        """Insert each food item into meal_items table."""
        for item in fused.items:
            await conn.execute(
                """
                INSERT INTO meal_items (
                    meal_id, food_name, canonical_name,
                    portion_g, calories, protein, carbs, fat,
                    source_database, match_confidence
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                meal_id,
                item.food_name,
                item.canonical_name,
                item.portion_g,
                item.calories,
                item.protein,
                item.carbs,
                item.fat,
                item.source_database,
                item.match_confidence,
            )

    async def _upsert_food_library(
        self,
        conn: asyncpg.Connection,
        fused: FusedResult,
    ) -> None:
        """Update food_library: insert or increment use_count + update last_used."""
        for item in fused.items:
            await conn.execute(
                """
                INSERT INTO food_library (
                    name,
                    kcal_per_100, protein_per_100, carbs_per_100, fat_per_100,
                    use_count, last_used
                ) VALUES ($1, $2, $3, $4, $5, 1, NOW())
                ON CONFLICT (name) DO UPDATE
                    SET use_count = food_library.use_count + 1,
                        last_used = NOW()
                """,
                item.canonical_name,
                round(item.calories / item.portion_g * 100, 4) if item.portion_g else 0,
                round(item.protein / item.portion_g * 100, 4) if item.portion_g else 0,
                round(item.carbs / item.portion_g * 100, 4) if item.portion_g else 0,
                round(item.fat / item.portion_g * 100, 4) if item.portion_g else 0,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_description(fused: FusedResult) -> str:
    if not fused.items:
        return "Unknown meal"
    names = [item.food_name for item in fused.items]
    return ", ".join(names[:5]) + (" ..." if len(names) > 5 else "")


def _determine_confirmation_status(fused: FusedResult) -> ConfirmationStatus:
    if fused.source_type == SourceType.BARCODE:
        return ConfirmationStatus.EXACT_BARCODE_MATCH
    if fused.confidence_score >= 0.80:
        return ConfirmationStatus.ESTIMATED_HIGH
    return ConfirmationStatus.ESTIMATED_MODERATE
