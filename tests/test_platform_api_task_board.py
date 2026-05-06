from datetime import datetime, timezone
from uuid import UUID

from platform_api.tasks import normalize_task


def test_normalize_task_exposes_canonical_and_dashboard_aliases():
    task = normalize_task({
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "parent_id": None,
        "title": "Patch gateway",
        "description": "Deploy validated gateway build.",
        "created_by": "operator",
        "assigned_to": "cio",
        "assignment_mode": "manual",
        "status": "running",
        "priority": "high",
        "depends_on": [UUID("00000000-0000-0000-0000-000000000002")],
        "retry_count": 1,
        "max_retries": 3,
        "summary": "Started",
        "created_at": datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc),
        "assigned_at": datetime(2026, 5, 6, 10, 1, tzinfo=timezone.utc),
        "started_at": datetime(2026, 5, 6, 10, 2, tzinfo=timezone.utc),
        "completed_at": None,
        "duration_ms": None,
    })

    assert task["id"] == "00000000-0000-0000-0000-000000000001"
    assert task["status"] == "running"
    assert task["state"] == "running"
    assert task["assigned_to"] == "cio"
    assert task["assigned_agent"] == "cio"
    assert task["depends_on"] == ["00000000-0000-0000-0000-000000000002"]
    assert task["created_at"] == "2026-05-06T10:00:00+00:00"
    assert task["updated_at"] == "2026-05-06T10:02:00+00:00"
    assert task["links"]["detail"] == "/tasks/00000000-0000-0000-0000-000000000001"


def test_normalize_task_uses_created_at_as_updated_at_when_no_lifecycle_timestamps():
    task = normalize_task({
        "id": UUID("00000000-0000-0000-0000-000000000003"),
        "title": "Collect logs",
        "status": "pending",
        "priority": "normal",
        "created_at": datetime(2026, 5, 6, 11, 0, tzinfo=timezone.utc),
    })

    assert task["updated_at"] == "2026-05-06T11:00:00+00:00"
    assert task["assignment_mode"] == "pending"
    assert task["retry_count"] == 0
