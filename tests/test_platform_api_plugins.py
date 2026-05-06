from platform_api.plugins import build_plugin_summary, collect_capability_registry, normalize_observed_tool


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
        "agent_id": "cio",
        "severity": "info",
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
