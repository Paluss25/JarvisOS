"""Tests for NutritionDirector scheduled operational tasks."""

from agents.don.config import NUTRITION_BUILTIN_CRONS


def _cron(name: str) -> dict:
    for cron in NUTRITION_BUILTIN_CRONS:
        if cron["name"] == name:
            return cron
    raise AssertionError(f"{name} cron not found")


def test_goal_review_prep_cron_is_persistent_for_next_review():
    cron = _cron("goal_review_prep")

    assert cron["schedule"] == "once@2026-05-19@09:03"
    assert cron["builtin"] is True
    assert cron["telegram_notify"] is False
    assert "COH" in cron["prompt"]
    assert "trusted W18/W19 nutrition snapshot" in cron["prompt"]
