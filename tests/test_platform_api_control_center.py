from platform_api.control_center import build_control_summary


def test_build_control_summary_defaults_empty():
    summary = build_control_summary(
        agents=[],
        tasks=[],
        events=[],
        audit_rows=[],
    )

    assert summary["agents"]["total"] == 0
    assert summary["agents"]["running"] == 0
    assert summary["tasks"]["open"] == 0
    assert summary["incidents"]["critical"] == 0
    assert summary["costs"]["today_usd"] == 0


def test_build_control_summary_counts_running_agents_and_open_tasks():
    summary = build_control_summary(
        agents=[
            {"id": "cio", "supervisord_state": "RUNNING"},
            {"id": "cfo", "supervisord_state": "STOPPED"},
        ],
        tasks=[
            {"id": "1", "status": "running"},
            {"id": "2", "status": "done"},
            {"id": "3", "status": "blocked"},
        ],
        events=[
            {"severity": "critical"},
            {"severity": "warning"},
        ],
        audit_rows=[],
    )

    assert summary["agents"]["total"] == 2
    assert summary["agents"]["running"] == 1
    assert summary["tasks"]["open"] == 2
    assert summary["incidents"]["critical"] == 1


def test_build_control_summary_exposes_operator_work_queues_and_links():
    summary = build_control_summary(
        agents=[
            {"id": "cio", "supervisord_state": "RUNNING"},
            {"id": "cfo", "supervisord_state": "STOPPED"},
        ],
        tasks=[
            {"id": "task-1", "title": "Fix backup", "status": "running", "priority": "high", "assigned_to": "cio", "created_at": "2026-05-06T10:00:00+00:00"},
            {"id": "task-2", "title": "Approve spend", "status": "needs_review", "priority": "urgent", "assigned_to": "cfo", "created_at": "2026-05-06T11:00:00+00:00"},
            {"id": "task-3", "title": "Finished", "status": "done", "priority": "normal", "assigned_to": "cio", "created_at": "2026-05-06T09:00:00+00:00"},
        ],
        events=[
            {"id": "event-1", "ts": "2026-05-06T12:00:00+00:00", "severity": "critical", "event_type": "backup_failed", "agent_id": "cio", "task_id": "task-1", "trace_id": "trace-1", "payload": {"summary": "NFS backup failed"}},
            {"id": "event-2", "ts": "2026-05-06T12:05:00+00:00", "severity": "warning", "event_type": "policy_warning", "agent_id": "cfo", "task_id": "task-2", "payload": {}},
        ],
        audit_rows=[],
        decisions=[
            {"id": "decision-1", "ts": "2026-05-06T12:10:00+00:00", "agent_id": "cfo", "task_id": "task-2", "trace_id": "trace-2", "title": "Hold purchase", "status": "proposed"},
        ],
        trace_spans=[
            {"trace_id": "trace-1", "task_id": "task-1", "agent_id": "cio", "duration_ms": 1500, "input_tokens": 100, "output_tokens": 40, "cost_usd": 0.25, "status": "ok"},
            {"trace_id": "trace-1", "task_id": "task-1", "agent_id": "cio", "duration_ms": 500, "input_tokens": 50, "output_tokens": 10, "cost_usd": 0.05, "status": "ok"},
            {"trace_id": "trace-2", "task_id": "task-2", "agent_id": "cfo", "duration_ms": 3000, "input_tokens": 200, "output_tokens": 80, "cost_usd": 0.5, "status": "error"},
        ],
    )

    assert summary["tasks"]["needs_review"] == 1
    assert summary["tasks"]["running"] == 1
    assert summary["costs"]["today_usd"] == 0.8
    assert summary["costs"]["tokens_today"] == 480
    assert summary["work_in_progress"][0]["href"] == "/tasks/task-1"
    assert summary["needs_review"][0]["agent_href"] == "/agents/cfo"
    assert summary["incident_feed"][0]["detail_href"] == "/logs/event-1"
    assert summary["incident_feed"][0]["trace_href"] == "/traces/trace-1"
    assert summary["recent_decisions"][0]["detail_href"] == "/decisions/decision-1"
    assert summary["recent_decisions"][0]["href"] == "/tasks/task-2"
    assert summary["slow_traces"][0]["trace_id"] == "trace-2"
    assert summary["agent_spotlight"][0] == {
        "id": "cfo",
        "status": "stopped",
        "href": "/agents/cfo",
        "cockpit_href": "/agents/cfo/cockpit",
    }
