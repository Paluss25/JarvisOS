from datetime import datetime, timezone
from uuid import UUID

from platform_api.incidents import build_incident_context, build_incident_event, is_incident_event
from platform_api.logs import normalize_log_event


def test_normalize_log_event_serializes_ids_and_timestamp():
    event = normalize_log_event({
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "ts": datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        "event_type": "tool_call",
        "severity": "warning",
        "agent_id": "cio",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "session_id": "session-1",
        "trace_id": "trace-1",
        "span_id": "span-1",
        "source": "agent",
        "payload": {"tool": "kubectl"},
    })

    assert event["id"] == "00000000-0000-0000-0000-000000000001"
    assert event["ts"] == "2026-05-05T12:00:00+00:00"
    assert event["task_id"] == "00000000-0000-0000-0000-000000000002"
    assert event["trace_id"] == "trace-1"
    assert event["payload"]["tool"] == "kubectl"


def test_build_incident_event_sets_payload_and_defaults():
    incident = build_incident_event(
        title="CIO detected failed deployment",
        severity="critical",
        agent_id="cio",
        task_id="00000000-0000-0000-0000-000000000002",
        trace_id="trace-1",
        description="Deployment validation failed",
        created_by="user-1",
    )

    assert incident["event_type"] == "incident"
    assert incident["severity"] == "critical"
    assert incident["agent_id"] == "cio"
    assert incident["task_id"] == "00000000-0000-0000-0000-000000000002"
    assert incident["trace_id"] == "trace-1"
    assert incident["source"] == "dashboard"
    assert incident["payload"]["kind"] == "incident"
    assert incident["payload"]["title"] == "CIO detected failed deployment"
    assert incident["payload"]["status"] == "open"
    assert incident["payload"]["created_by"] == "user-1"


def test_is_incident_event_requires_type_and_payload_kind():
    assert is_incident_event({"event_type": "incident", "payload": {"kind": "incident"}})
    assert not is_incident_event({"event_type": "incident", "payload": {"kind": "log"}})
    assert not is_incident_event({"event_type": "tool_call", "payload": {"kind": "incident"}})


def test_build_incident_context_correlates_links_and_metrics():
    incident = normalize_log_event({
        "id": UUID("00000000-0000-0000-0000-000000000010"),
        "ts": datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        "event_type": "incident",
        "severity": "critical",
        "agent_id": "cio",
        "task_id": UUID("00000000-0000-0000-0000-000000000002"),
        "session_id": "session-1",
        "trace_id": "trace-1",
        "span_id": None,
        "source": "dashboard",
        "payload": {"kind": "incident", "title": "Backup failure", "status": "open"},
    })
    context = build_incident_context(
        incident=incident,
        related_logs=[{"id": "log-1"}, {"id": "log-2"}],
        audit_entries=[{"id": 8}],
        decisions=[{"id": "decision-1"}],
        traces=[{"trace_id": "trace-1"}],
    )

    assert context["metrics"] == {
        "log_count": 2,
        "audit_count": 1,
        "decision_count": 1,
        "trace_count": 1,
    }
    assert context["links"] == {
        "agent": "/agents/cio",
        "task": "/tasks/00000000-0000-0000-0000-000000000002",
        "trace": "/traces/trace-1",
        "logs": "/logs?trace_id=trace-1",
        "audit": "/audit?agent_id=cio",
        "ciso": "/agents/ciso/cockpit",
        "cio": "/agents/cio/cockpit",
    }
