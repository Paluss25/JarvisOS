"""Tests for Jarvis CEO morning briefing scope."""

from agents.ceo.config import JARVIS_BUILTIN_CRONS


def _morning_prompt() -> str:
    for cron in JARVIS_BUILTIN_CRONS:
        if cron["name"] == "morning_briefing":
            return cron["prompt"]
    raise AssertionError("morning_briefing cron not found")


def test_ceo_morning_briefing_is_strategic_not_operational():
    prompt = _morning_prompt()

    assert "vision and strategic briefing" in prompt
    assert "Do not repeat domain-level operational items" in prompt
    assert "CFO, COH, CIO, MT, DOS, COS, or EIA" in prompt
    assert "executive decision" in prompt
    assert "anything actionable I should know" not in prompt

