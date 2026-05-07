from platform_api.cockpits import build_cio_summary, is_cio_operational_event


def test_build_cio_summary_counts_homelab_operations():
    summary = build_cio_summary([
        {"agent_id": "cio", "event_type": "tool_call", "severity": "info", "payload": {"tool": "kubectl"}},
        {"agent_id": "cio", "event_type": "skill_used", "severity": "info", "payload": {"skill": "homelab"}},
        {"agent_id": "cio", "event_type": "deploy_completed", "severity": "info", "payload": {"service": "gateway"}},
        {"agent_id": "cio", "event_type": "backup_failed", "severity": "error", "payload": {"service": "postgres"}},
        {"agent_id": "cio", "event_type": "health_check", "severity": "info", "payload": {"status": "healthy"}},
        {"agent_id": "cio", "event_type": "incident_opened", "severity": "critical", "payload": {"service": "loki"}},
        {"agent_id": "cfo", "event_type": "tool_call", "severity": "info", "payload": {"tool": "ynab"}},
    ])

    assert summary["event_count"] == 6
    assert summary["tool_events"] == 1
    assert summary["skill_events"] == 1
    assert summary["deploy_events"] == 1
    assert summary["backup_events"] == 1
    assert summary["health_events"] == 1
    assert summary["incident_events"] == 1
    assert summary["failed_events"] == 2


def test_is_cio_operational_event_requires_cio_agent_and_ops_semantics():
    assert is_cio_operational_event({"agent_id": "cio", "event_type": "tool_call", "payload": {}})
    assert is_cio_operational_event({"agent_id": "cio", "event_type": "homelab_event", "payload": {"kind": "deploy"}})
    assert is_cio_operational_event({"agent_id": "cio", "event_type": "health_check", "payload": {}})
    assert not is_cio_operational_event({"agent_id": "cfo", "event_type": "tool_call", "payload": {}})
    assert not is_cio_operational_event({"agent_id": "cio", "event_type": "conversation", "payload": {}})
