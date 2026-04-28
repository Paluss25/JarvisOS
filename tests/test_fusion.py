import pytest
from src.agents.don.subagents.fusion import fuse_meal
from src.agents.don.models import ResolvedFood, SourceType, VisionHypothesis


def test_barcode_override_confidence():
    resolved = [ResolvedFood(
        canonical_name="Yogurt Vipiteno", source_database="openfoodfacts",
        portion_g=125, calories=95, protein=4.5, carbs=12, fat=3.2,
        match_confidence=0.60, barcode="8001234567890",
    )]
    result = fuse_meal(None, resolved, SourceType.BARCODE)
    assert result.confidence_score == 0.95
    assert not result.needs_confirmation


def test_low_confidence_needs_confirmation():
    resolved = [ResolvedFood(
        canonical_name="Mystery food", source_database="usda",
        portion_g=100, calories=200, protein=10, carbs=20, fat=8,
        match_confidence=0.40,
    )]
    result = fuse_meal(None, resolved, SourceType.TEXT)
    assert result.needs_confirmation


def test_image_pipeline_totals():
    hypotheses = [
        VisionHypothesis(food_name="grilled chicken", visible_ingredients=["chicken"],
                        portion_estimate_g=150, confidence=0.85),
        VisionHypothesis(food_name="white rice", visible_ingredients=["rice"],
                        portion_estimate_g=200, confidence=0.90),
    ]
    resolved = [
        ResolvedFood(canonical_name="Grilled Chicken Breast", source_database="fatsecret",
                    portion_g=150, calories=248, protein=46.5, carbs=0, fat=5.4,
                    match_confidence=0.85),
        ResolvedFood(canonical_name="White Rice, cooked", source_database="fatsecret",
                    portion_g=200, calories=260, protein=4.4, carbs=56.6, fat=0.6,
                    match_confidence=0.80),
    ]
    result = fuse_meal(hypotheses, resolved, SourceType.IMAGE)
    assert result.total_calories == pytest.approx(508, abs=1)
    assert len(result.items) == 2
    assert result.confidence_score > 0.60


def test_empty_meal():
    result = fuse_meal(None, [], SourceType.TEXT)
    assert result.total_calories == 0
    assert len(result.items) == 0
