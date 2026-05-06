"""Tests for DON fast-path nutrition integrity guards."""

from agents.don.fast_actions import _plausibility_rejection_reason


def test_plausibility_guard_rejects_large_refinement_inflation():
    api_macros = {
        "calories_est": 752,
        "protein_g": 32.4,
        "carbs_g": 128.5,
        "fat_g": 12.1,
    }

    reason = _plausibility_rejection_reason(api_macros, haiku_kcal=364)

    assert reason is not None
    assert "Haiku" in reason


def test_plausibility_guard_rejects_macro_energy_mismatch():
    api_macros = {
        "calories_est": 650,
        "protein_g": 30,
        "carbs_g": 35,
        "fat_g": 5,
    }

    reason = _plausibility_rejection_reason(api_macros, haiku_kcal=610)

    assert reason is not None
    assert "macro energy" in reason


def test_plausibility_guard_allows_small_refinement_correction():
    api_macros = {
        "calories_est": 267,
        "protein_g": 30.0,
        "carbs_g": 27.5,
        "fat_g": 4.2,
    }

    reason = _plausibility_rejection_reason(api_macros, haiku_kcal=312)

    assert reason is None
