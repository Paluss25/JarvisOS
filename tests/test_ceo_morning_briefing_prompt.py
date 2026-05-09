"""Tests for Jarvis CEO morning briefing scope."""

from agents.cfo.config import CFO_BUILTIN_CRONS
from agents.cio.config import TIMOTHY_BUILTIN_CRONS
from agents.coh.config import DRHOUSE_BUILTIN_CRONS
from agents.cos.config import MARK_BUILTIN_CRONS
from agents.dos.config import ROGER_BUILTIN_CRONS
from agents.ceo.config import JARVIS_BUILTIN_CRONS
from agents.email_intelligence_agent.config import EMAIL_INTELLIGENCE_BUILTIN_CRONS
from agents.mt.config import MT_BUILTIN_CRONS


def _cron(crons: list[dict], name: str) -> dict:
    for cron in crons:
        if cron["name"] == name:
            return cron
    raise AssertionError(f"{name} cron not found")


def test_ceo_morning_briefing_is_strategic_not_operational():
    prompt = _cron(JARVIS_BUILTIN_CRONS, "morning_briefing")["prompt"]

    assert "vision and strategic briefing" in prompt
    assert "Do not repeat domain-level operational items" in prompt
    assert "CFO, COH, CIO, MT, DOS, COS, or EIA" in prompt
    assert "executive decision" in prompt
    assert "anything actionable I should know" not in prompt


def test_ceo_morning_briefing_is_escalation_only_and_not_user_facing():
    cron = _cron(JARVIS_BUILTIN_CRONS, "morning_briefing")
    prompt = cron["prompt"]

    assert cron["telegram_notify"] is False
    assert "Do not send a routine morning briefing to Paluss" in prompt
    assert "Only escalate" in prompt
    assert "send_message(to='cos'" in prompt


def test_cos_owns_single_user_facing_morning_briefing():
    cron = _cron(MARK_BUILTIN_CRONS, "morning_briefing")
    prompt = cron["prompt"]

    assert cron["schedule"] == "daily@08:55"
    assert cron["telegram_notify"] is True
    assert "single morning briefing" in prompt
    assert "CEO, CIO, CFO, COH, DOS, MT, EIA" in prompt
    assert "what matters today" in prompt
    assert "what needs Paluss" in prompt


def test_specialist_morning_briefings_feed_cos_without_direct_user_notifications():
    specialist_crons = [
        _cron(EMAIL_INTELLIGENCE_BUILTIN_CRONS, "morning_briefing"),
        _cron(ROGER_BUILTIN_CRONS, "morning_check"),
        _cron(DRHOUSE_BUILTIN_CRONS, "morning_briefing"),
        _cron(DRHOUSE_BUILTIN_CRONS, "morning_health_briefing"),
        _cron(CFO_BUILTIN_CRONS, "morning_cost_check"),
        _cron(TIMOTHY_BUILTIN_CRONS, "morning_briefing"),
        _cron(MT_BUILTIN_CRONS, "morning_briefing"),
    ]

    for cron in specialist_crons:
        prompt = cron["prompt"].lower()
        assert cron["telegram_notify"] is False
        assert "send_message(to='cos'" in prompt or "send a summary to cos via send_message" in prompt
