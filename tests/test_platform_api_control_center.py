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
