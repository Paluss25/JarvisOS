"""Tests for Timothy CIO morning briefing stale-memory policy."""

from agents.cio.config import TIMOTHY_BUILTIN_CRONS


def _morning_prompt() -> str:
    for cron in TIMOTHY_BUILTIN_CRONS:
        if cron["name"] == "morning_briefing":
            return cron["prompt"]
    raise AssertionError("morning_briefing cron not found")


def test_cio_morning_briefing_requires_fresh_evidence_for_open_actions():
    prompt = _morning_prompt()

    assert "Open Loop Registry" in prompt
    assert "Do not report pending actions from MEMORY.md" in prompt
    assert "fresh live verification" in prompt
    assert "RESOLVED/VERIFIED" in prompt
