"""Pydantic models for the meal recognition pipeline."""

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    IMAGE = "image"
    BARCODE = "barcode"
    TEXT = "text"
    IMAGE_PLUS_TEXT = "image_plus_text"
    MIXED = "mixed"


class ConfirmationStatus(str, Enum):
    CONFIRMED_BY_USER = "confirmed_by_user"
    EXACT_BARCODE_MATCH = "exact_barcode_match"
    ESTIMATED_HIGH = "estimated_high_confidence"
    ESTIMATED_MODERATE = "estimated_moderate_confidence"
    CORRECTED = "corrected_after_prompt"


class VisionHypothesis(BaseModel):
    food_name: str
    visible_ingredients: list[str] = []
    portion_estimate_g: float
    confidence: float
    notes: str = ""


class VisionResult(BaseModel):
    hypotheses: list[VisionHypothesis]
    scene_complexity: str = "low"
    needs_confirmation: bool = False


class ResolvedFood(BaseModel):
    canonical_name: str
    source_database: str
    portion_g: float
    calories: float
    protein: float
    carbs: float
    fat: float
    match_confidence: float
    barcode: str | None = None


class FusedMealItem(BaseModel):
    food_name: str
    canonical_name: str
    portion_g: float
    calories: float
    protein: float
    carbs: float
    fat: float
    source_database: str
    match_confidence: float


class FusedResult(BaseModel):
    items: list[FusedMealItem]
    total_calories: float
    total_protein: float
    total_carbs: float
    total_fat: float
    confidence_score: float
    needs_confirmation: bool = False
    clarification_question: str | None = None
    source_type: SourceType = SourceType.TEXT


class MealRecord(BaseModel):
    meal_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.now)
    meal_type: str = "other"
    source_type: SourceType = SourceType.TEXT
    items: list[FusedMealItem] = []
    total_calories: float = 0
    total_protein: float = 0
    total_carbs: float = 0
    total_fat: float = 0
    confidence: float = 0
    confirmation_status: ConfirmationStatus = ConfirmationStatus.ESTIMATED_MODERATE
    needs_confirmation: bool = False
    notes: str = ""


class CoachingNote(BaseModel):
    summary: str
    suggestions: list[str] = []
    calories_today: float | None = None
    protein_today: float | None = None
