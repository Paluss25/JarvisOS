from datetime import datetime, timezone
from uuid import UUID

from platform_api.a2a import build_a2a_message_context, build_a2a_summary, is_a2a_event, normalize_a2a_event


def test_is_a2a_event_requires_a2a_semantics():
    assert is_a2a_event({"event_type": "a2a_request", "payload": {}})
    assert is_a2a_event({"event_type": "platform_event", "a2a_message_id": "msg-1", "payload": {}})
    assert is_a2a_event({"event_type": "message", "payload": {"from_agent": "ceo", "to_agent": "cfo"}})
    assert not is_a2a_event({"event_type": "task_created", "payload": {"agent_id": "cio"}})


def test_normalize_a2a_event_extracts_envelope_fields():
    event = normalize_a2a_event({
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "ts": datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        "event_type": "a2a_request",
        "severity": "info",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "trace_id": "trace-a2a-1",
        "a2a_message_id": "msg-1",
        "payload": {
            "from_agent": "ceo",
            "to_agent": "cio",
            "type": "request",
            "mode": "async",
            "correlation_id": "cid-1",
            "hop_count": 2,
            "max_hops": 5,
            "status": "sent",
        },
    })

    assert event["id"] == "00000000-0000-0000-0000-000000000001"
    assert event["ts"] == "2026-05-06T12:00:00+00:00"
    assert event["task_id"] == "00000000-0000-0000-0000-000000000002"
    assert event["trace_id"] == "trace-a2a-1"
    assert event["message_id"] == "msg-1"
    assert event["from_agent"] == "ceo"
    assert event["to_agent"] == "cio"
    assert event["message_type"] == "request"
    assert event["mode"] == "async"
    assert event["correlation_id"] == "cid-1"
    assert event["hop_count"] == 2
    assert event["max_hops"] == 5


def test_build_a2a_summary_counts_traffic_and_warnings():
    summary = build_a2a_summary([
        {"event_type": "a2a_request", "severity": "info", "payload": {"type": "request", "mode": "async", "from_agent": "ceo", "to_agent": "cio"}},
        {"event_type": "a2a_response", "severity": "info", "payload": {"type": "response", "from_agent": "cio", "to_agent": "ceo"}},
        {"event_type": "a2a_notification", "severity": "info", "payload": {"type": "notification", "from_agent": "ciso", "to_agent": "cio"}},
        {"event_type": "a2a_dead_letter", "severity": "error", "payload": {"type": "request", "status": "failed", "from_agent": "cfo", "to_agent": "ceo"}},
        {"event_type": "a2a_request", "severity": "warning", "payload": {"type": "request", "hop_count": 5, "max_hops": 5, "from_agent": "cos", "to_agent": "ceo"}},
        {"event_type": "task_created", "severity": "info", "payload": {}},
    ])

    assert summary["message_count"] == 5
    assert summary["request_count"] == 3
    assert summary["response_count"] == 1
    assert summary["notification_count"] == 1
    assert summary["async_count"] == 1
    assert summary["failure_count"] == 1
    assert summary["loop_warnings"] == 1
    assert summary["edge_count"] == 5


def test_build_a2a_message_context_exposes_thread_metrics_links_and_actions():
    event = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "ts": datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
        "event_type": "a2a_request",
        "severity": "warning",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "trace_id": "trace-a2a-1",
        "a2a_message_id": "msg-1",
        "payload": {
            "from_agent": "ceo",
            "to_agent": "cio",
            "type": "request",
            "mode": "async",
            "correlation_id": "cid-1",
            "root_correlation_id": "root-1",
            "hop_count": 5,
            "max_hops": 5,
            "status": "failed",
        },
    }
    response = {
        **event,
        "id": UUID("00000000-0000-0000-0000-000000000003"),
        "event_type": "a2a_response",
        "severity": "error",
        "a2a_message_id": "msg-2",
        "payload": {
            "from_agent": "cio",
            "to_agent": "ceo",
            "type": "response",
            "mode": "async",
            "correlation_id": "cid-1",
            "root_correlation_id": "root-1",
            "parent_correlation_id": "cid-1",
            "status": "failed",
        },
    }

    context = build_a2a_message_context(
        event=event,
        thread_events=[event, response],
        logs=[{"id": "log-1"}],
        traces=[{"trace_id": "trace-a2a-1"}],
        audit_entries=[{"id": 1}],
        decisions=[{"id": "decision-1"}],
    )

    assert context["message"]["message_id"] == "msg-1"
    assert context["metrics"] == {
        "thread_count": 2,
        "failure_count": 2,
        "loop_warnings": 1,
        "log_count": 1,
        "trace_count": 1,
        "audit_count": 1,
        "decision_count": 1,
    }
    assert context["links"] == {
        "from_agent": "/agents/ceo",
        "from_chat": "/agents/ceo/chat?task_id=00000000-0000-0000-0000-000000000002&trace_id=trace-a2a-1",
        "to_agent": "/agents/cio",
        "to_chat": "/agents/cio/chat?task_id=00000000-0000-0000-0000-000000000002&trace_id=trace-a2a-1",
        "task": "/tasks/00000000-0000-0000-0000-000000000002",
        "trace": "/traces/trace-a2a-1",
        "logs": "/logs?trace_id=trace-a2a-1",
        "audit": "/audit?action=&source=&trace_id=trace-a2a-1",
    }
    assert [item["message_id"] for item in context["thread"]] == ["msg-1", "msg-2"]
    assert context["suggested_actions"] == [
        {"kind": "task", "label": "Create follow-up task", "priority": "high"},
        {"kind": "trace", "label": "Inspect linked trace", "trace_id": "trace-a2a-1"},
    ]
