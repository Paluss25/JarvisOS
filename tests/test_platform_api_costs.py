from decimal import Decimal

from platform_api.costs import build_cost_summary, normalize_cost_group


def test_normalize_cost_group_serializes_decimal_and_token_totals():
    group = normalize_cost_group({
        "key": "cfo",
        "cost_usd": Decimal("0.123456"),
        "input_tokens": 100,
        "output_tokens": 50,
        "span_count": 2,
        "duration_ms": 1200,
    })

    assert group["key"] == "cfo"
    assert group["cost_usd"] == 0.123456
    assert group["tokens"] == 150
    assert group["input_tokens"] == 100
    assert group["output_tokens"] == 50
    assert group["span_count"] == 2
    assert group["duration_ms"] == 1200


def test_build_cost_summary_groups_agents_models_tasks_and_latency():
    summary = build_cost_summary([
        {
            "agent_id": "cfo",
            "task_id": "task-1",
            "session_id": "session-1",
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": Decimal("0.10"),
            "duration_ms": 100,
        },
        {
            "agent_id": "cfo",
            "task_id": "task-1",
            "session_id": "session-1",
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 40,
            "output_tokens": 10,
            "cost_usd": Decimal("0.05"),
            "duration_ms": 300,
        },
        {
            "agent_id": "cio",
            "task_id": "task-2",
            "session_id": "session-2",
            "model": "claude-sonnet",
            "provider": "anthropic",
            "input_tokens": 20,
            "output_tokens": 30,
            "cost_usd": Decimal("0.20"),
            "duration_ms": 900,
        },
    ])

    assert summary["total_cost_usd"] == 0.35
    assert summary["input_tokens"] == 160
    assert summary["output_tokens"] == 90
    assert summary["tokens"] == 250
    assert summary["span_count"] == 3
    assert summary["p95_latency_ms"] == 900
    assert summary["by_agent"][0]["key"] == "cio"
    assert summary["by_agent"][0]["cost_usd"] == 0.2
    assert summary["by_model"][0]["key"] == "anthropic/claude-sonnet"
    assert summary["by_task"][0]["key"] == "task-2"
    assert summary["by_session"][0]["key"] == "session-2"
