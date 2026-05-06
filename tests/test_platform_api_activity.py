from datetime import datetime, timezone
from uuid import UUID

from platform_api.activity import build_activity_summary, normalize_activity_event


def test_normalize_activity_event_exposes_dashboard_links_and_preview():
    event = normalize_activity_event({
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "ts": datetime(2026, 5, 6, 15, 0, tzinfo=timezone.utc),
        "event_type": "tool_error",
        "severity": "error",
        "agent_id": "cio",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "trace_id": "trace-activity-1",
        "span_id": "span-1",
        "source": "agent",
        "payload": {"tool": "kubectl", "message": "pod crashloop"},
    })

    assert event["id"] == "00000000-0000-0000-0000-000000000001"
    assert event["ts"] == "2026-05-06T15:00:00+00:00"
    assert event["kind"] == "platform_event"
    assert event["label"] == "tool_error"
    assert event["severity"] == "error"
    assert event["agent_id"] == "cio"
    assert event["preview"] == "pod crashloop"
    assert event["links"] == {
        "detail": "/logs/00000000-0000-0000-0000-000000000001",
        "agent": "/agents/cio",
        "chat": "/agents/cio/chat?task_id=00000000-0000-0000-0000-000000000002&trace_id=trace-activity-1&log_event_id=00000000-0000-0000-0000-000000000001",
        "task": "/tasks/00000000-0000-0000-0000-000000000002",
        "trace": "/traces/trace-activity-1",
        "audit": "/audit?action=&source=&agent_id=cio",
    }


def test_build_activity_summary_merges_platform_events_and_audit_entries():
    event = normalize_activity_event({
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "ts": datetime(2026, 5, 6, 15, 0, tzinfo=timezone.utc),
        "event_type": "task_failed",
        "severity": "critical",
        "agent_id": "cio",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "trace_id": "trace-activity-1",
        "source": "task_runner",
        "payload": {"summary": "deployment failed"},
    })
    audit = {
        "id": 7,
        "ts": datetime(2026, 5, 6, 15, 1, tzinfo=timezone.utc),
        "category": "platform",
        "agent_id": "cio",
        "user_id": "operator",
        "action": "task_retried",
        "detail": {"task_id": "00000000-0000-0000-0000-000000000002", "trace_id": "trace-activity-1"},
        "source": "api",
    }

    summary = build_activity_summary(events=[event], audit_entries=[audit])

    assert summary["metrics"] == {
        "total_count": 2,
        "platform_event_count": 1,
        "audit_count": 1,
        "critical_count": 1,
        "error_count": 0,
        "warning_count": 0,
        "agent_count": 1,
    }
    assert [item["kind"] for item in summary["items"]] == ["audit", "platform_event"]
    assert summary["items"][0]["label"] == "task_retried"
    assert summary["items"][0]["links"]["detail"] == "/audit?action=task_retried&source=api&agent_id=cio"
    assert summary["items"][1]["links"]["trace"] == "/traces/trace-activity-1"
