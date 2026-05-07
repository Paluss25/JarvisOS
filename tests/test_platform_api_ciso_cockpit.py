from platform_api.cockpits import build_ciso_summary, is_ciso_security_event


def test_build_ciso_summary_counts_security_operations():
    summary = build_ciso_summary([
        {"agent_id": "ciso", "event_type": "security_alert", "severity": "warning", "payload": {"category": "threat"}},
        {"agent_id": "ciso", "event_type": "vulnerability_found", "severity": "critical", "payload": {"service": "gateway"}},
        {"agent_id": "ciso", "event_type": "auth_failure", "severity": "error", "payload": {"principal": "api"}},
        {"agent_id": "ciso", "event_type": "policy_violation", "severity": "warning", "payload": {"status": "open"}},
        {"agent_id": "ciso", "event_type": "scan_completed", "severity": "info", "payload": {"tool": "trivy"}},
        {"agent_id": "ciso", "event_type": "incident_opened", "severity": "critical", "payload": {"category": "security"}},
        {"agent_id": "cio", "event_type": "security_alert", "severity": "critical", "payload": {}},
    ])

    assert summary["event_count"] == 6
    assert summary["alert_events"] == 1
    assert summary["incident_events"] == 1
    assert summary["vulnerability_events"] == 1
    assert summary["auth_events"] == 1
    assert summary["policy_events"] == 1
    assert summary["scan_events"] == 1
    assert summary["critical_events"] == 2
    assert summary["open_findings"] == 4


def test_is_ciso_security_event_requires_ciso_agent_and_security_semantics():
    assert is_ciso_security_event({"agent_id": "ciso", "event_type": "security_alert", "payload": {}})
    assert is_ciso_security_event({"agent_id": "ciso", "event_type": "auth_failure", "payload": {}})
    assert is_ciso_security_event({"agent_id": "ciso", "event_type": "platform_event", "payload": {"kind": "vulnerability"}})
    assert not is_ciso_security_event({"agent_id": "cio", "event_type": "security_alert", "payload": {}})
    assert not is_ciso_security_event({"agent_id": "ciso", "event_type": "conversation", "payload": {}})
