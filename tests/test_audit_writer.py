"""Unit tests for AuditWriter."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from security.audit_writer import AuditWriter


def test_write_creates_jsonl_entry(tmp_path):
    """Writing one event should create a JSONL file with exactly 1 line of valid JSON."""
    path = tmp_path / "audit.jsonl"
    writer = AuditWriter(str(path))
    event = writer.make_event(
        event_id="evt-001",
        event_type="pipeline_run",
        agent_id="email_intelligence_agent",
        action="route_and_review",
        outcome="allow",
    )
    writer.write(event)

    assert path.exists(), "audit.jsonl was not created"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"
    parsed = json.loads(lines[0])
    assert isinstance(parsed, dict), "Line is not a valid JSON object"


def test_multiple_entries_appended(tmp_path):
    """Writing 3 events should produce exactly 3 lines in the JSONL file."""
    path = tmp_path / "audit.jsonl"
    writer = AuditWriter(str(path))
    for i in range(3):
        event = writer.make_event(
            event_id=f"evt-{i:03d}",
            event_type="pipeline_run",
            agent_id="email_intelligence_agent",
            action="route_and_review",
            outcome="allow",
        )
        writer.write(event)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}"
    for line in lines:
        assert json.loads(line), "Each line must be valid JSON"


def test_audit_entry_has_timestamp(tmp_path):
    """Every audit event must include a 'timestamp' field."""
    path = tmp_path / "audit.jsonl"
    writer = AuditWriter(str(path))
    event = writer.make_event(
        event_id="evt-ts-001",
        event_type="pipeline_run",
        agent_id="email_intelligence_agent",
        action="route_and_review",
        outcome="allow",
    )
    writer.write(event)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    parsed = json.loads(lines[0])
    assert "timestamp" in parsed, "Audit entry missing 'timestamp' field"
    assert parsed["timestamp"], "timestamp must be non-empty"


def test_audit_parent_dir_created_automatically(tmp_path):
    """AuditWriter must create nested parent directories if they don't exist yet."""
    nested_path = tmp_path / "a" / "b" / "c" / "audit.jsonl"
    writer = AuditWriter(str(nested_path))
    event = writer.make_event(
        event_id="evt-dir-001",
        event_type="pipeline_run",
        agent_id="email_intelligence_agent",
        action="route_and_review",
        outcome="allow",
    )
    writer.write(event)
    assert nested_path.exists()


def test_forbidden_detail_keys_are_stripped(tmp_path):
    """FORBIDDEN_DETAIL_KEYS must not appear in the written JSON."""
    path = tmp_path / "audit.jsonl"
    writer = AuditWriter(str(path))
    event = writer.make_event(
        event_id="evt-redact-001",
        event_type="pipeline_run",
        agent_id="email_intelligence_agent",
        action="route_and_review",
        outcome="allow",
        details={
            "account": "protonmail",
            "raw_email_body": "This must be stripped",
            "system_prompt": "Also must be stripped",
        },
    )
    writer.write(event)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    parsed = json.loads(lines[0])
    details = parsed.get("details", {})
    assert "raw_email_body" not in details
    assert "system_prompt" not in details
    assert details.get("account") == "protonmail", "Safe keys must be preserved"


def test_make_event_returns_audit_event(tmp_path):
    """make_event() must return an AuditEvent with the fields passed in."""
    from security.audit_writer import AuditEvent

    path = tmp_path / "audit.jsonl"
    writer = AuditWriter(str(path))
    event = writer.make_event(
        event_id="evt-type-001",
        event_type="quarantine",
        agent_id="email_intelligence_agent",
        action="quarantine",
        outcome="quarantined",
        email_id="email-abc",
    )
    assert isinstance(event, AuditEvent)
    assert event.event_id == "evt-type-001"
    assert event.event_type == "quarantine"
    assert event.email_id == "email-abc"
