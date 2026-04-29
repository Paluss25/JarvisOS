"""NutritionResolverAgent — resolves food names to nutrition facts.

Resolution order: FatSecret (primary) → USDA (fallback).
Results are cached via NutritionCache to avoid repeated API calls.
"""

import json
import logging

from agents.don.cache import NutritionCache
from agents.don.clients.fatsecret import FatSecretClient, FatSecretFood
from agents.don.clients.usda import USDAClient, USDAFood
from agents.don.models import ResolvedFood

logger = logging.getLogger(__name__)


class NutritionResolverAgent:
    """Resolves a food name + portion to a ResolvedFood using FatSecret → USDA."""

    def __init__(self):
        self._fatsecret = FatSecretClient()
        self._usda = USDAClient()
        self._cache = NutritionCache()

    async def resolve(self, food_name: str, portion_g: float) -> ResolvedFood | None:
        """Resolve a food name to nutrition facts scaled to portion_g.

        Args:
            food_name: Human-readable food name (e.g. "grilled chicken breast").
            portion_g: Target portion in grams.

        Returns:
            ResolvedFood scaled to portion_g, or None if no match found.
        """
        # 1. Try FatSecret (with cache)
        resolved = await self._resolve_fatsecret(food_name, portion_g)
        if resolved is not None:
            return resolved

        # 2. Fallback to USDA (with cache)
        return await self._resolve_usda(food_name, portion_g)

    async def _resolve_fatsecret(self, food_name: str, portion_g: float) -> ResolvedFood | None:
        cached = await self._cache.get("fatsecret", food_name)
        if cached:
            return _fatsecret_dict_to_resolved(cached, food_name, portion_g)

        try:
            results = await self._fatsecret.search_foods(food_name, max_results=3)
        except Exception as exc:
            logger.warning("FatSecret search failed for %r: %s", food_name, exc)
            results = []

        if not results:
            return None

        best = results[0]
        cache_payload = _fatsecret_food_to_dict(best)
        await self._cache.set("fatsecret", food_name, cache_payload)
        return _fatsecret_food_to_resolved(best, food_name, portion_g)

    async def _resolve_usda(self, food_name: str, portion_g: float) -> ResolvedFood | None:
        cached = await self._cache.get("usda", food_name)
        if cached:
            return _usda_dict_to_resolved(cached, food_name, portion_g)

        try:
            results = await self._usda.search_foods(food_name, max_results=3)
        except Exception as exc:
            logger.warning("USDA search failed for %r: %s", food_name, exc)
            results = []

        if not results:
            return None

        best = results[0]
        cache_payload = _usda_food_to_dict(best)
        await self._cache.set("usda", food_name, cache_payload)
        return _usda_food_to_resolved(best, food_name, portion_g)


# ---------------------------------------------------------------------------
# Helpers — FatSecret
# ---------------------------------------------------------------------------

def _fatsecret_food_to_dict(food: FatSecretFood) -> dict:
    return {
        "food_name": food.food_name,
        "calories": food.calories,
        "protein": food.protein,
        "carbs": food.carbs,
        "fat": food.fat,
        "serving_g": food.serving_g,
        "confidence": food.confidence,
    }


def _fatsecret_food_to_resolved(food: FatSecretFood, query: str, portion_g: float) -> ResolvedFood:
    return _scale_resolved(
        canonical_name=food.food_name or query,
        source="fatsecret",
        base_calories=food.calories,
        base_protein=food.protein,
        base_carbs=food.carbs,
        base_fat=food.fat,
        base_g=food.serving_g or 100.0,
        target_g=portion_g,
        confidence=food.confidence,
    )


def _fatsecret_dict_to_resolved(d: dict, query: str, portion_g: float) -> ResolvedFood:
    return _scale_resolved(
        canonical_name=d.get("food_name", query),
        source="fatsecret",
        base_calories=d["calories"],
        base_protein=d["protein"],
        base_carbs=d["carbs"],
        base_fat=d["fat"],
        base_g=d.get("serving_g", 100.0),
        target_g=portion_g,
        confidence=d.get("confidence", 0.85),
    )


# ---------------------------------------------------------------------------
# Helpers — USDA
# ---------------------------------------------------------------------------

def _usda_food_to_dict(food: USDAFood) -> dict:
    return {
        "food_name": food.food_name,
        "calories": food.calories,
        "protein": food.protein,
        "carbs": food.carbs,
        "fat": food.fat,
        "serving_g": food.serving_g,
        "confidence": food.confidence,
    }


def _usda_food_to_resolved(food: USDAFood, query: str, portion_g: float) -> ResolvedFood:
    return _scale_resolved(
        canonical_name=food.food_name or query,
        source="usda",
        base_calories=food.calories,
        base_protein=food.protein,
        base_carbs=food.carbs,
        base_fat=food.fat,
        base_g=food.serving_g,
        target_g=portion_g,
        confidence=food.confidence,
    )


def _usda_dict_to_resolved(d: dict, query: str, portion_g: float) -> ResolvedFood:
    return _scale_resolved(
        canonical_name=d.get("food_name", query),
        source="usda",
        base_calories=d["calories"],
        base_protein=d["protein"],
        base_carbs=d["carbs"],
        base_fat=d["fat"],
        base_g=d.get("serving_g", 100.0),
        target_g=portion_g,
        confidence=d.get("confidence", 0.70),
    )


# ---------------------------------------------------------------------------
# Shared scaling helper
# ---------------------------------------------------------------------------

def _scale_resolved(
    *,
    canonical_name: str,
    source: str,
    base_calories: float,
    base_protein: float,
    base_carbs: float,
    base_fat: float,
    base_g: float,
    target_g: float,
    confidence: float,
) -> ResolvedFood:
    scale = target_g / (base_g or 100.0)
    return ResolvedFood(
        canonical_name=canonical_name,
        source_database=source,
        portion_g=target_g,
        calories=round(base_calories * scale, 2),
        protein=round(base_protein * scale, 2),
        carbs=round(base_carbs * scale, 2),
        fat=round(base_fat * scale, 2),
        match_confidence=confidence,
    )
