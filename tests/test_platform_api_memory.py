from datetime import datetime, timezone
from uuid import UUID

from platform_api.memory import build_memory_summary, is_memory_event, normalize_memory_event


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
