from platform_api.agents import normalize_agent_status


def test_normalize_agent_status_exposes_dashboard_fields():
    agent = normalize_agent_status(
        {
            "id": "cfo",
            "role": "ChiefFinancialOfficer",
            "port": 8003,
            "workspace": "workspace/cfo",
            "domains": ["finance", "crypto"],
            "capabilities": ["budget-analysis", "cost-analysis"],
        },
        supervisord_state="RUNNING",
        health="ok",
    )

    assert agent == {
        "id": "cfo",
        "name": "cfo",
        "role": "ChiefFinancialOfficer",
        "port": 8003,
        "workspace": "workspace/cfo",
        "domains": ["finance", "crypto"],
        "capabilities": ["budget-analysis", "cost-analysis"],
        "supervisord_state": "RUNNING",
        "status": "running",
        "health": "ok",
        "uptime_s": None,
        "uptime_seconds": None,
        "context_usage": None,
        "links": {
            "detail": "/agents/cfo",
            "chat": "/agents/cfo/chat",
            "cockpit": "/agents/cfo/cockpit",
        },
    }


def test_normalize_agent_status_defaults_unknown_state_and_identity():
    agent = normalize_agent_status({"id": "cio", "port": 8002}, supervisord_state=None, health=None)

    assert agent["name"] == "cio"
    assert agent["role"] == "Agent"
    assert agent["status"] == "unknown"
    assert agent["health"] == "unknown"
    assert agent["domains"] == []
    assert agent["capabilities"] == []
