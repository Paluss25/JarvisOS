"""MealFusionAgent — merges multi-source evidence into a single FusedResult.

Confidence model
----------------
- Barcode exact match  → 0.95 (hard override, skips formula)
- Image path:  vision(0.40) + provider(0.35) + portion(0.15) + context(0.10)
- Text path:   provider(0.80) + context(0.10)

Thresholds
----------
- >= 0.80  accept without confirmation
- 0.55–0.79  flag for user review
- < 0.55  ask clarification

Material ambiguity
------------------
- calorie delta > 20% among items → ask
- portion variance > 30% → ask
"""

import logging
from statistics import mean, stdev

from agents.don.models import (
    FusedMealItem,
    FusedResult,
    ResolvedFood,
    SourceType,
    VisionHypothesis,
)

logger = logging.getLogger(__name__)

_ACCEPT_THRESHOLD = 0.80
_REVIEW_THRESHOLD = 0.55


def fuse_meal(
    hypotheses: list[VisionHypothesis] | None,
    resolved: list[ResolvedFood],
    source_type: SourceType,
) -> FusedResult:
    """Merge vision hypotheses and resolved nutrition data into a FusedResult.

    Args:
        hypotheses: Vision hypotheses (may be None for text/barcode paths).
        resolved: Resolved nutrition data, one entry per food item.
        source_type: Origin of the meal data.

    Returns:
        FusedResult with aggregated totals and confidence score.
    """
    if not resolved:
        return FusedResult(
            items=[],
            total_calories=0.0,
            total_protein=0.0,
            total_carbs=0.0,
            total_fat=0.0,
            confidence_score=0.0,
            needs_confirmation=False,
            source_type=source_type,
        )

    # Build items
    items = _build_items(hypotheses, resolved, source_type)

    # Compute totals
    total_calories = sum(i.calories for i in items)
    total_protein = sum(i.protein for i in items)
    total_carbs = sum(i.carbs for i in items)
    total_fat = sum(i.fat for i in items)

    # Compute confidence
    confidence = _compute_confidence(hypotheses, resolved, source_type)

    # Check material ambiguity
    clarification = _check_ambiguity(items)

    needs_confirmation = (confidence < _ACCEPT_THRESHOLD) or (clarification is not None)

    return FusedResult(
        items=items,
        total_calories=round(total_calories, 2),
        total_protein=round(total_protein, 2),
        total_carbs=round(total_carbs, 2),
        total_fat=round(total_fat, 2),
        confidence_score=round(confidence, 4),
        needs_confirmation=needs_confirmation,
        clarification_question=clarification,
        source_type=source_type,
    )


# ---------------------------------------------------------------------------
# Item building
# ---------------------------------------------------------------------------

def _build_items(
    hypotheses: list[VisionHypothesis] | None,
    resolved: list[ResolvedFood],
    source_type: SourceType,
) -> list[FusedMealItem]:
    """Build FusedMealItem list, pairing resolved foods with hypotheses when available."""
    items = []
    hyp_map = {}
    if hypotheses:
        # Map by index; vision and resolver maintain same order
        for idx, h in enumerate(hypotheses):
            hyp_map[idx] = h

    for idx, food in enumerate(resolved):
        hyp = hyp_map.get(idx)
        food_name = hyp.food_name if hyp else food.canonical_name
        items.append(
            FusedMealItem(
                food_name=food_name,
                canonical_name=food.canonical_name,
                portion_g=food.portion_g,
                calories=food.calories,
                protein=food.protein,
                carbs=food.carbs,
                fat=food.fat,
                source_database=food.source_database,
                match_confidence=food.match_confidence,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Confidence model
# ---------------------------------------------------------------------------

def _compute_confidence(
    hypotheses: list[VisionHypothesis] | None,
    resolved: list[ResolvedFood],
    source_type: SourceType,
) -> float:
    """Compute overall meal confidence score."""
    if not resolved:
        return 0.0

    # Barcode hard override — all items must carry barcode flag
    if source_type == SourceType.BARCODE:
        if all(r.barcode is not None for r in resolved):
            return 0.95
        # Mixed barcode situation: use average provider confidence
        provider_conf = mean(r.match_confidence for r in resolved)
        return min(0.95, provider_conf)

    provider_conf = mean(r.match_confidence for r in resolved)

    if source_type == SourceType.IMAGE and hypotheses:
        vision_conf = mean(h.confidence for h in hypotheses)
        # portion factor: how well hypothesized portions align with resolved portions
        portion_factor = _portion_alignment_factor(hypotheses, resolved)
        # context factor: number of items identified (more items, slightly lower certainty)
        context_factor = max(0.5, 1.0 - 0.05 * len(resolved))
        score = (
            vision_conf * 0.40
            + provider_conf * 0.35
            + portion_factor * 0.15
            + context_factor * 0.10
        )
        return min(1.0, score)

    if source_type in (SourceType.IMAGE, SourceType.IMAGE_PLUS_TEXT) and not hypotheses:
        # Image path but no vision result
        context_factor = max(0.5, 1.0 - 0.05 * len(resolved))
        return min(1.0, provider_conf * 0.35 + context_factor * 0.10)

    # Text path (and fallback for any other source type)
    context_factor = max(0.5, 1.0 - 0.05 * len(resolved))
    score = provider_conf * 0.80 + context_factor * 0.10
    return min(1.0, score)


def _portion_alignment_factor(
    hypotheses: list[VisionHypothesis],
    resolved: list[ResolvedFood],
) -> float:
    """Score how well vision portion estimates match resolved portions (0–1)."""
    if not hypotheses or not resolved:
        return 0.5

    scores = []
    for h, r in zip(hypotheses, resolved):
        if r.portion_g == 0:
            scores.append(0.5)
            continue
        ratio = h.portion_estimate_g / r.portion_g
        # Perfect alignment = 1.0; 2× or 0.5× = 0.5; further = lower
        deviation = abs(1.0 - ratio)
        scores.append(max(0.0, 1.0 - deviation))

    return mean(scores)


# ---------------------------------------------------------------------------
# Ambiguity detection
# ---------------------------------------------------------------------------

def _check_ambiguity(items: list[FusedMealItem]) -> str | None:
    """Return a clarification question if material ambiguity is detected."""
    if len(items) < 2:
        return None

    calories = [i.calories for i in items if i.calories > 0]
    portions = [i.portion_g for i in items if i.portion_g > 0]

    if calories:
        cal_mean = mean(calories)
        if cal_mean > 0 and stdev(calories) / cal_mean > 0.20:
            names = ", ".join(i.food_name for i in items[:3])
            return (
                f"I noticed significant calorie variation among the items ({names}). "
                "Could you confirm the portions are correct?"
            )

    if portions:
        port_mean = mean(portions)
        if port_mean > 0 and stdev(portions) / port_mean > 0.30:
            return "The portion sizes vary quite a bit. Could you confirm the amounts for each item?"

    return None
