from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from platform_api.cockpits import build_cfo_summary, is_cfo_alert_event
from platform_api.decisions import normalize_decision


def test_normalize_decision_serializes_audit_fields():
    decision = normalize_decision({
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "ts": datetime(2026, 5, 6, 9, 30, tzinfo=timezone.utc),
        "agent_id": "cfo",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "trace_id": "trace-cfo-1",
        "title": "Hold BTC",
        "summary": "No rebalance until tax impact is checked.",
        "decision_type": "portfolio",
        "confidence": Decimal("0.875"),
        "status": "proposed",
        "evidence": [{"source": "btc-fiscal-api", "ts": "2026-05-06T09:00:00Z"}],
        "payload": {"currency": "EUR", "period": "2026-Q2"},
    })

    assert decision["id"] == "00000000-0000-0000-0000-000000000001"
    assert decision["ts"] == "2026-05-06T09:30:00+00:00"
    assert decision["task_id"] == "00000000-0000-0000-0000-000000000002"
    assert decision["trace_id"] == "trace-cfo-1"
    assert decision["confidence"] == 0.875
    assert decision["evidence"][0]["source"] == "btc-fiscal-api"
    assert decision["payload"]["currency"] == "EUR"


def test_build_cfo_summary_counts_decisions_and_alerts():
    summary = build_cfo_summary(
        decisions=[
            {"status": "proposed", "decision_type": "portfolio"},
            {"status": "approved", "decision_type": "tax"},
            {"status": "rejected", "decision_type": "budget"},
        ],
        events=[
            {"agent_id": "cfo", "event_type": "finance_alert", "severity": "warning", "payload": {"category": "market"}},
            {"agent_id": "cfo", "event_type": "tax_alert", "severity": "critical", "payload": {"category": "tax"}},
            {"agent_id": "cio", "event_type": "tax_alert", "severity": "critical", "payload": {"category": "tax"}},
        ],
    )

    assert summary["decision_count"] == 3
    assert summary["open_approvals"] == 1
    assert summary["approved_decisions"] == 1
    assert summary["rejected_decisions"] == 1
    assert summary["market_alerts"] == 1
    assert summary["tax_alerts"] == 1
    assert summary["critical_alerts"] == 1


def test_is_cfo_alert_event_requires_cfo_agent_and_alert_semantics():
    assert is_cfo_alert_event({"agent_id": "cfo", "event_type": "tax_alert", "payload": {}})
    assert is_cfo_alert_event({"agent_id": "cfo", "event_type": "finance_event", "payload": {"kind": "alert"}})
    assert not is_cfo_alert_event({"agent_id": "cio", "event_type": "tax_alert", "payload": {}})
    assert not is_cfo_alert_event({"agent_id": "cfo", "event_type": "trace_span", "payload": {}})
