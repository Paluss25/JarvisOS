from datetime import datetime, timezone
from uuid import UUID

from platform_api.decisions import build_decision_context, normalize_decision


def test_build_decision_context_exposes_links_metrics_and_evidence():
    decision = normalize_decision({
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "ts": datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
        "agent_id": "cfo",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "trace_id": "trace-decision-1",
        "title": "Hold BTC",
        "summary": "No rebalance until tax impact is checked.",
        "decision_type": "portfolio",
        "confidence": None,
        "status": "approved",
        "evidence": [
            {"kind": "source", "id": "market-note"},
            {"kind": "chat_message", "id": "msg-1"},
        ],
        "payload": {"currency": "EUR", "period": "2026-Q2"},
    })

    context = build_decision_context(
        decision=decision,
        related_logs=[{"id": "event-1"}],
        traces=[{"trace_id": "trace-decision-1"}],
        audit_entries=[{"id": 7}],
    )

    assert context["decision"]["id"] == "00000000-0000-0000-0000-000000000001"
    assert context["metrics"] == {
        "evidence_count": 2,
        "payload_key_count": 2,
        "related_log_count": 1,
        "trace_count": 1,
        "audit_count": 1,
    }
    assert context["links"] == {
        "agent": "/agents/cfo",
        "chat": "/agents/cfo/chat?task_id=00000000-0000-0000-0000-000000000002&trace_id=trace-decision-1",
        "cockpit": "/agents/cfo/cockpit",
        "task": "/tasks/00000000-0000-0000-0000-000000000002",
        "trace": "/traces/trace-decision-1",
        "logs": "/logs?trace_id=trace-decision-1",
        "audit": "/audit?action=&source=&agent_id=cfo",
    }
    assert context["evidence"] == [
        {"kind": "source", "id": "market-note"},
        {"kind": "chat_message", "id": "msg-1"},
    ]
    assert context["related_logs"] == [{"id": "event-1"}]
