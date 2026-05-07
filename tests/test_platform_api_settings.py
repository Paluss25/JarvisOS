from platform_api.settings import (
    build_settings_summary,
    normalize_approval_classes,
    normalize_memory_stores,
    normalize_permission_agents,
)


def test_normalize_approval_classes_counts_actions_by_risk_class():
    classes = normalize_approval_classes({
        "approval_classes": {
            "auto_allowed": {"description": "Safe", "actions": ["classify", "summarize"]},
            "human_approval_required": {"description": "Sensitive", "actions": ["send_email"]},
            "two_step_approval_required": {"description": "High risk", "actions": ["payment"]},
        }
    })

    assert classes == [
        {"name": "auto_allowed", "description": "Safe", "action_count": 2, "actions": ["classify", "summarize"], "risk": "low"},
        {"name": "human_approval_required", "description": "Sensitive", "action_count": 1, "actions": ["send_email"], "risk": "medium"},
        {"name": "two_step_approval_required", "description": "High risk", "action_count": 1, "actions": ["payment"], "risk": "high"},
    ]


def test_normalize_memory_stores_extracts_retention_and_controls():
    stores = normalize_memory_stores({
        "stores": {
            "vector_store": {
                "description": "Semantic retrieval",
                "retention_days": 60,
                "access_roles": ["cfo", "cio"],
                "vectorization_allowed": True,
                "redaction_required": True,
            }
        }
    })

    assert stores == [{
        "name": "vector_store",
        "description": "Semantic retrieval",
        "retention_days": 60,
        "access_roles": ["cfo", "cio"],
        "vectorization_allowed": True,
        "redaction_required": True,
        "pii_minimized": False,
    }]


def test_normalize_permission_agents_summarizes_access_counts():
    permissions = normalize_permission_agents({
        "agents": {
            "cfo": {
                "description": "Finance operator",
                "permissions": {
                    "read": ["structured_store"],
                    "write": ["decision_store"],
                    "execute": ["approve_budget", "analyze_market"],
                    "denied": ["payment_execution"],
                },
            }
        }
    })

    assert permissions == [{
        "agent_id": "cfo",
        "description": "Finance operator",
        "read_count": 1,
        "write_count": 1,
        "execute_count": 2,
        "denied_count": 1,
    }]


def test_build_settings_summary_combines_registry_and_policy_posture():
    summary = build_settings_summary(
        registry={
            "agents": [{"id": "cfo"}, {"id": "cio"}],
            "workers": [{"id": "finance"}],
        },
        domains=["finance", "ops"],
        user_count=3,
        approval_classes=[
            {"name": "auto_allowed", "action_count": 2},
            {"name": "human_approval_required", "action_count": 3},
            {"name": "two_step_approval_required", "action_count": 1},
        ],
        memory_stores=[
            {"name": "raw", "retention_days": 90},
            {"name": "vector", "retention_days": 60},
        ],
        permission_agents=[
            {"agent_id": "cfo", "denied_count": 4},
            {"agent_id": "cio", "denied_count": 2},
        ],
        model_rules=[{"id": "local_only"}, {"id": "cloud_allowed"}],
        shared_constraints=["no_bypass", "no_unscoped_memory"],
        audit_config_events=5,
    )

    assert summary == {
        "agent_count": 2,
        "worker_count": 1,
        "domain_count": 2,
        "user_count": 3,
        "approval_class_count": 3,
        "human_approval_actions": 3,
        "two_step_actions": 1,
        "memory_store_count": 2,
        "min_retention_days": 60,
        "max_retention_days": 90,
        "permission_agent_count": 2,
        "denied_action_count": 6,
        "model_rule_count": 2,
        "shared_constraint_count": 2,
        "audit_config_events": 5,
    }
