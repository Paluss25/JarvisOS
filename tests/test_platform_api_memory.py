from datetime import datetime, timezone
from uuid import UUID

from platform_api.memory import (
    build_memory_event_context,
    build_memory_summary,
    is_memory_event,
    normalize_memory_event,
)


def test_is_memory_event_detects_memory_semantics():
    assert is_memory_event({"event_type": "memory_write", "payload": {}})
    assert is_memory_event({"event_type": "platform_event", "payload": {"kind": "memory_query"}})
    assert is_memory_event({"event_type": "daily_log_update", "payload": {}})
    assert not is_memory_event({"event_type": "task_created", "payload": {}})


def test_normalize_memory_event_extracts_provenance():
    event = normalize_memory_event({
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "ts": datetime(2026, 5, 6, 13, 0, tzinfo=timezone.utc),
        "event_type": "memory_write",
        "severity": "info",
        "agent_id": "cfo",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "trace_id": "trace-memory-1",
        "source": "memory-box",
        "payload": {"kind": "memory_write", "domain": "finance", "key": "btc-tax", "scope": "domain:finance"},
    })

    assert event["id"] == "00000000-0000-0000-0000-000000000001"
    assert event["ts"] == "2026-05-06T13:00:00+00:00"
    assert event["agent_id"] == "cfo"
    assert event["task_id"] == "00000000-0000-0000-0000-000000000002"
    assert event["trace_id"] == "trace-memory-1"
    assert event["source"] == "memory-box"
    assert event["kind"] == "memory_write"
    assert event["domain"] == "finance"
    assert event["key"] == "btc-tax"
    assert event["scope"] == "domain:finance"


def test_build_memory_summary_counts_memory_activity_and_decisions():
    summary = build_memory_summary(
        events=[
            {"event_type": "memory_query", "severity": "info", "agent_id": "cfo", "payload": {"kind": "memory_query", "domain": "finance"}},
            {"event_type": "memory_write", "severity": "info", "agent_id": "cfo", "payload": {"kind": "memory_write", "domain": "finance"}},
            {"event_type": "memory_conflict", "severity": "warning", "agent_id": "ciso", "payload": {"kind": "memory_conflict", "domain": "security"}},
            {"event_type": "daily_log_update", "severity": "info", "agent_id": "cio", "payload": {"kind": "daily_log"}},
            {"event_type": "task_created", "severity": "info", "agent_id": "cio", "payload": {}},
        ],
        decisions=[
            {"decision_type": "memory_promotion", "agent_id": "cfo"},
            {"decision_type": "portfolio", "agent_id": "cfo"},
        ],
    )

    assert summary["event_count"] == 4
    assert summary["query_count"] == 1
    assert summary["write_count"] == 1
    assert summary["daily_log_count"] == 1
    assert summary["conflict_count"] == 1
    assert summary["decision_promotions"] == 1
    assert summary["agent_count"] == 3
    assert summary["domain_count"] == 2


def test_build_memory_event_context_exposes_provenance_links_and_diagnostics():
    event = normalize_memory_event({
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "ts": datetime(2026, 5, 6, 13, 0, tzinfo=timezone.utc),
        "event_type": "memory_conflict",
        "severity": "warning",
        "agent_id": "cfo",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "trace_id": "trace-memory-1",
        "source": "memory-box",
        "payload": {"kind": "memory_conflict", "domain": "finance", "key": "btc-tax", "scope": "domain:finance"},
    })
    related = [
        event,
        {
            **event,
            "id": "event-2",
            "event_type": "memory_write",
            "severity": "info",
            "kind": "memory_write",
        },
    ]

    context = build_memory_event_context(
        event=event,
        related_events=related,
        traces=[{"trace_id": "trace-memory-1"}],
        audit_entries=[{"id": 1}],
        decisions=[{"id": "decision-1", "decision_type": "memory_promotion"}],
    )

    assert context["event"]["id"] == "00000000-0000-0000-0000-000000000001"
    assert context["metrics"] == {
        "related_event_count": 2,
        "trace_count": 1,
        "audit_count": 1,
        "decision_count": 1,
        "promotion_count": 1,
    }
    assert context["links"] == {
        "agent": "/agents/cfo",
        "chat": "/agents/cfo/chat?task_id=00000000-0000-0000-0000-000000000002&trace_id=trace-memory-1&memory_event_id=00000000-0000-0000-0000-000000000001",
        "task": "/tasks/00000000-0000-0000-0000-000000000002",
        "trace": "/traces/trace-memory-1",
        "logs": "/logs?trace_id=trace-memory-1",
        "audit": "/audit?action=&source=&agent_id=cfo",
    }
    assert context["diagnostics"] == [
        {"kind": "conflict", "label": "Conflict or duplicate detected", "tone": "warning"},
    ]
    assert [item["id"] for item in context["related_events"]] == [
        "00000000-0000-0000-0000-000000000001",
        "event-2",
    ]
