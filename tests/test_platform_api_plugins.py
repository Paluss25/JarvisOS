from platform_api.plugins import (
    build_plugin_summary,
    build_tool_context,
    collect_capability_registry,
    normalize_observed_tool,
)


def test_collect_capability_registry_groups_capabilities_by_agent():
    capabilities = collect_capability_registry([
        {"id": "cfo", "capabilities": ["budget-analysis", "cost-analysis"], "domains": ["finance"]},
        {"id": "cio", "capabilities": ["cost-analysis", "infra-monitoring"], "domains": ["infrastructure"]},
    ])

    assert capabilities == [
        {"name": "budget-analysis", "kind": "capability", "agents": ["cfo"], "domains": ["finance"]},
        {"name": "cost-analysis", "kind": "capability", "agents": ["cfo", "cio"], "domains": ["finance", "infrastructure"]},
        {"name": "infra-monitoring", "kind": "capability", "agents": ["cio"], "domains": ["infrastructure"]},
    ]


def test_normalize_observed_tool_extracts_tool_or_skill_from_event():
    tool = normalize_observed_tool({
        "event_type": "tool_call",
        "id": "event-1",
        "ts": "2026-05-06T12:00:00+00:00",
        "agent_id": "cio",
        "task_id": "task-1",
        "trace_id": "trace-1",
        "severity": "info",
        "source": "platform",
        "payload": {"tool": "kubectl", "duration_ms": 120, "status": "ok"},
    })
    skill = normalize_observed_tool({
        "event_type": "skill_used",
        "agent_id": "cfo",
        "severity": "warning",
        "payload": {"skill": "market-research", "status": "failed"},
    })

    assert tool["name"] == "kubectl"
    assert tool["kind"] == "tool"
    assert tool["agent_id"] == "cio"
    assert tool["id"] == "event-1"
    assert tool["task_id"] == "task-1"
    assert tool["trace_id"] == "trace-1"
    assert tool["source"] == "platform"
    assert tool["duration_ms"] == 120
    assert tool["status"] == "ok"
    assert skill["name"] == "market-research"
    assert skill["kind"] == "skill"
    assert skill["status"] == "failed"


def test_build_plugin_summary_counts_registry_and_observed_tools():
    summary = build_plugin_summary(
        agents=[
            {"id": "cfo", "capabilities": ["budget-analysis", "cost-analysis"], "domains": ["finance"]},
            {"id": "cio", "capabilities": ["infra-monitoring"], "domains": ["infrastructure"]},
        ],
        workers=[
            {"id": "cost", "module": "workers.cost.app"},
            {"id": "finance", "module": "workers.finance.app"},
        ],
        events=[
            {"event_type": "tool_call", "agent_id": "cio", "payload": {"tool": "kubectl"}},
            {"event_type": "skill_used", "agent_id": "cfo", "payload": {"skill": "market-research"}},
            {"event_type": "task_created", "agent_id": "ceo", "payload": {}},
        ],
    )

    assert summary["agent_count"] == 2
    assert summary["worker_count"] == 2
    assert summary["capability_count"] == 3
    assert summary["observed_tool_count"] == 2
    assert summary["tool_event_count"] == 1
    assert summary["skill_event_count"] == 1


def test_build_tool_context_exposes_agents_diagnostics_and_links():
    context = build_tool_context(
        name="kubectl",
        kind="tool",
        agents=[
            {"id": "cio", "capabilities": ["infra-monitoring"], "domains": ["infrastructure"]},
            {"id": "ciso", "capabilities": ["security-scan"], "domains": ["security"]},
        ],
        events=[
            {
                "id": "event-1",
                "event_type": "tool_call",
                "severity": "info",
                "agent_id": "cio",
                "task_id": "task-1",
                "trace_id": "trace-1",
                "source": "platform",
                "payload": {"tool": "kubectl", "status": "ok", "duration_ms": 120},
            },
            {
                "id": "event-2",
                "event_type": "tool_call",
                "severity": "error",
                "agent_id": "cio",
                "task_id": "task-2",
                "trace_id": "trace-2",
                "source": "platform",
                "payload": {"tool": "kubectl", "status": "failed", "duration_ms": 900},
            },
            {
                "id": "event-3",
                "event_type": "skill_used",
                "severity": "info",
                "agent_id": "cfo",
                "payload": {"skill": "market-research", "status": "ok"},
            },
        ],
        traces=[{"trace_id": "trace-1"}, {"trace_id": "trace-2"}],
        audit_entries=[{"id": 1}],
        decisions=[{"id": "decision-1"}],
    )

    assert context["tool"]["name"] == "kubectl"
    assert context["metrics"] == {
        "agent_count": 1,
        "event_count": 2,
        "failure_count": 1,
        "trace_count": 2,
        "audit_count": 1,
        "decision_count": 1,
        "avg_duration_ms": 510,
    }
    assert context["links"] == {
        "logs": "/logs?event_type=tool_call",
        "audit": "/audit?action=&source=&agent_id=cio",
        "first_trace": "/traces/trace-1",
        "first_task": "/tasks/task-1",
    }
    assert context["agents"] == [{"id": "cio", "domains": ["infrastructure"], "capabilities": ["infra-monitoring"]}]
    assert context["diagnostics"] == [
        {"kind": "failure", "label": "Recent failures", "count": 1, "tone": "incident"},
    ]
    assert [event["id"] for event in context["events"]] == ["event-1", "event-2"]
