"""Integration tests for DrHouse health system.

Verifies router, medical gate, fusion engine, and models work together.
"""

import pytest

# Router tests
from src.agents.coh.router import classify
from src.agents.coh.medical import screen_input, ApprovalStatus

# Nutrition pipeline tests
from src.agents.don.models import (
    ResolvedFood, SourceType, VisionHypothesis, FusedResult,
    ConfirmationStatus, MealRecord, CoachingNote,
)
from src.agents.don.subagents.fusion import fuse_meal


class TestRouterIntegration:
    """Test the DrHouse request router handles real-world input."""

    def test_photo_routes_to_nutrition(self):
        plan = classify("", has_image=True)
        assert "don" in plan.consult

    def test_italian_food_text(self):
        plan = classify("Ho mangiato pollo alla griglia con riso e zucchine")
        assert "don" in plan.consult

    def test_english_training(self):
        plan = classify("How was my morning run?")
        assert "dos" in plan.consult

    def test_cross_domain_routes_both(self):
        plan = classify("Mangiato pizza, domani mattina vado in corsa")
        assert "don" in plan.consult
        assert "dos" in plan.consult

    def test_medical_red_flag_gates(self):
        plan = classify("Ho dolore al petto dopo la corsa")
        assert plan.medical_gate_first
        assert "dos" in plan.consult

    def test_barcode_routes_to_nutrition(self):
        plan = classify("8001234567890", has_barcode=True)
        assert "don" in plan.consult

    def test_strategic_question_direct(self):
        plan = classify("Come va il mio progresso questa settimana?")
        assert plan.is_strategic

    def test_generic_greeting_strategic(self):
        plan = classify("Ciao DrHouse!")
        assert plan.is_strategic


class TestMedicalGateIntegration:
    """Test medical safety gate catches dangerous inputs."""

    def test_chest_pain_blocks(self):
        result = screen_input("sudden chest pain while running")
        assert result.status == ApprovalStatus.NOT_APPROVED
        assert result.escalation_advice

    def test_italian_red_flag(self):
        result = screen_input("Ho un forte mal di testa e vista offuscata")
        assert result.status == ApprovalStatus.NOT_APPROVED

    def test_injury_adds_constraints(self):
        result = screen_input("I hurt my ankle during the run")
        assert result.status == ApprovalStatus.APPROVED_WITH_CONSTRAINTS
        assert len(result.constraints) > 0

    def test_normal_food_passes(self):
        result = screen_input("chicken breast 150g for lunch")
        assert result.status == ApprovalStatus.APPROVED

    def test_eating_disorder_caution(self):
        result = screen_input("I think I might have an eating disorder")
        assert result.status == ApprovalStatus.APPROVED_WITH_CONSTRAINTS


class TestFusionIntegration:
    """Test the meal fusion engine merges evidence correctly."""

    def test_barcode_gets_highest_confidence(self):
        resolved = [ResolvedFood(
            canonical_name="Yogurt Vipiteno", source_database="openfoodfacts",
            portion_g=125, calories=95, protein=4.5, carbs=12, fat=3.2,
            match_confidence=0.60, barcode="8001234567890",
        )]
        result = fuse_meal(None, resolved, SourceType.BARCODE)
        assert result.confidence_score == 0.95
        assert not result.needs_confirmation

    def test_low_confidence_triggers_confirmation(self):
        resolved = [ResolvedFood(
            canonical_name="Unknown dish", source_database="usda",
            portion_g=100, calories=200, protein=10, carbs=20, fat=8,
            match_confidence=0.40,
        )]
        result = fuse_meal(None, resolved, SourceType.TEXT)
        assert result.needs_confirmation
        assert result.confidence_score < 0.80

    def test_image_pipeline_sums_correctly(self):
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
        assert result.total_protein == pytest.approx(50.9, abs=1)
        assert len(result.items) == 2

    def test_empty_meal_safe(self):
        result = fuse_meal(None, [], SourceType.TEXT)
        assert result.total_calories == 0
        assert len(result.items) == 0
        assert result.confidence_score == 0


class TestModels:
    """Test Pydantic models serialize/deserialize correctly."""

    def test_meal_record_defaults(self):
        record = MealRecord()
        assert record.meal_type == "other"
        assert record.source_type == SourceType.TEXT
        assert record.confirmation_status == ConfirmationStatus.ESTIMATED_MODERATE

    def test_coaching_note(self):
        note = CoachingNote(
            summary="Good protein hit (38g)",
            suggestions=["Consider adding vegetables"],
            calories_today=1200,
        )
        assert len(note.suggestions) == 1
        assert note.protein_today is None

    def test_fused_result_serialization(self):
        result = FusedResult(
            items=[], total_calories=0, total_protein=0,
            total_carbs=0, total_fat=0, confidence_score=0.85,
        )
        data = result.model_dump()
        assert data["confidence_score"] == 0.85
        rebuilt = FusedResult(**data)
        assert rebuilt.confidence_score == 0.85
