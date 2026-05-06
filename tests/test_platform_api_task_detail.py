from datetime import datetime, timezone
from uuid import UUID

from platform_api.tasks import build_task_context, normalize_task


def test_build_task_context_counts_observability_links_and_artifacts():
    task = normalize_task({
        "id": UUID("22222222-2222-2222-2222-222222222222"),
        "parent_id": None,
        "title": "Investigate backup failure",
        "description": "Check homelab backup logs",
        "created_by": "operator",
        "assigned_to": "cio",
        "assignment_mode": "manual",
        "status": "running",
        "priority": "high",
        "depends_on": [],
        "retry_count": 1,
        "max_retries": 3,
        "summary": None,
        "created_at": datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc),
    })

    context = build_task_context(
        task=task,
        traces=[{"trace_id": "trace-1", "status": "ok"}],
        logs=[
            {"id": "event-1", "payload": {"artifact_path": "/tmp/report.md", "artifact_name": "report.md"}},
            {"id": "event-2", "payload": {"output": "backup restarted"}},
        ],
        audit_entries=[{"id": 7, "action": "task_assigned"}],
        decisions=[{"id": "decision-1", "status": "approved"}],
    )

    assert context["metrics"] == {
        "trace_count": 1,
        "log_count": 2,
        "audit_count": 1,
        "decision_count": 1,
        "artifact_count": 2,
    }
    assert context["links"] == {
        "detail": "/tasks/22222222-2222-2222-2222-222222222222",
        "agent": "/agents/cio",
        "chat": "/agents/cio/chat?task_id=22222222-2222-2222-2222-222222222222",
        "cockpit": "/agents/cio/cockpit",
        "traces": "/traces?task_id=22222222-2222-2222-2222-222222222222",
        "logs": "/logs?task_id=22222222-2222-2222-2222-222222222222",
        "audit": "/audit?action=&source=&task_id=22222222-2222-2222-2222-222222222222",
    }
    assert context["artifacts"] == [
        {"event_id": "event-1", "name": "report.md", "path": "/tmp/report.md", "kind": "artifact"},
        {"event_id": "event-2", "name": "output", "path": None, "kind": "output", "preview": "backup restarted"},
    ]


def test_build_task_context_omits_agent_links_when_unassigned():
    task = normalize_task({
        "id": UUID("33333333-3333-3333-3333-333333333333"),
        "title": "Backlog item",
        "created_by": "operator",
        "status": "backlog",
        "priority": "normal",
        "created_at": datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc),
    })

    context = build_task_context(task=task, traces=[], logs=[], audit_entries=[], decisions=[])

    assert context["links"]["agent"] is None
    assert context["links"]["chat"] is None
    assert context["metrics"]["artifact_count"] == 0
