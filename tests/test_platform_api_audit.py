from datetime import datetime, timezone
from uuid import UUID

from platform_api.audit_endpoints import build_audit_context, build_audit_response, normalize_audit_entry


def test_normalize_audit_entry_serializes_timestamp_and_defaults_detail():
    entry = normalize_audit_entry({
        "id": 7,
        "ts": datetime(2026, 5, 6, 14, 30, tzinfo=timezone.utc),
        "category": "task",
        "agent_id": "cio",
        "user_id": UUID("11111111-1111-1111-1111-111111111111"),
        "action": "task_created",
        "detail": None,
        "source": "api",
    })

    assert entry == {
        "id": 7,
        "ts": "2026-05-06T14:30:00+00:00",
        "category": "task",
        "agent_id": "cio",
        "user_id": "11111111-1111-1111-1111-111111111111",
        "action": "task_created",
        "detail": {},
        "source": "api",
    }


def test_build_audit_response_wraps_items_with_total_count():
    response = build_audit_response(
        [
            {
                "id": 3,
                "ts": datetime(2026, 5, 6, 15, 0, tzinfo=timezone.utc),
                "category": "security",
                "agent_id": "ciso",
                "user_id": None,
                "action": "finding_opened",
                "detail": {"severity": "critical"},
                "source": "agent",
            }
        ],
        total=24,
    )

    assert response["total"] == 24
    assert len(response["items"]) == 1
    assert response["items"][0]["category"] == "security"
    assert response["items"][0]["detail"] == {"severity": "critical"}


def test_build_audit_context_exposes_links_metrics_and_related_records():
    entry = normalize_audit_entry({
        "id": 7,
        "ts": datetime(2026, 5, 6, 15, 0, tzinfo=timezone.utc),
        "category": "task",
        "agent_id": "cio",
        "user_id": None,
        "action": "task_created",
        "detail": {
            "task_id": "00000000-0000-0000-0000-000000000002",
            "trace_id": "trace-audit-1",
            "event_id": "00000000-0000-0000-0000-000000000003",
            "decision_id": "00000000-0000-0000-0000-000000000004",
        },
        "source": "api",
    })

    context = build_audit_context(
        entry=entry,
        related_logs=[{"id": "event-1"}],
        traces=[{"trace_id": "trace-audit-1"}],
        decisions=[{"id": "decision-1"}],
    )

    assert context["entry"]["id"] == 7
    assert context["metrics"] == {
        "detail_key_count": 4,
        "related_log_count": 1,
        "trace_count": 1,
        "decision_count": 1,
    }
    assert context["links"] == {
        "agent": "/agents/cio",
        "chat": "/agents/cio/chat?task_id=00000000-0000-0000-0000-000000000002&trace_id=trace-audit-1&log_event_id=00000000-0000-0000-0000-000000000003",
        "task": "/tasks/00000000-0000-0000-0000-000000000002",
        "trace": "/traces/trace-audit-1",
        "event": "/logs/00000000-0000-0000-0000-000000000003",
        "decision": "/decisions/00000000-0000-0000-0000-000000000004",
        "logs": "/logs?trace_id=trace-audit-1",
        "audit": "/audit?action=task_created&source=api&agent_id=cio",
    }
    assert context["related_logs"] == [{"id": "event-1"}]
