from decimal import Decimal

from platform_api.costs import build_cost_summary, build_cost_trace_context, normalize_cost_group


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
            "trace_id": "trace-cfo-1",
            "span_id": "span-1",
            "agent_id": "cfo",
            "task_id": "task-1",
            "session_id": "session-1",
            "operation": "invoke_model",
            "status": "ok",
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": Decimal("0.10"),
            "duration_ms": 100,
        },
        {
            "trace_id": "trace-cfo-1",
            "span_id": "span-2",
            "agent_id": "cfo",
            "task_id": "task-1",
            "session_id": "session-1",
            "operation": "invoke_model",
            "status": "ok",
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 40,
            "output_tokens": 10,
            "cost_usd": Decimal("0.05"),
            "duration_ms": 300,
        },
        {
            "trace_id": "trace-cio-1",
            "span_id": "span-3",
            "agent_id": "cio",
            "task_id": "task-2",
            "session_id": "session-2",
            "operation": "invoke_model",
            "status": "ok",
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
    assert summary["top_traces"][0]["key"] == "trace-cio-1"


def test_build_cost_trace_context_exposes_anomalies_links_and_breakdowns():
    context = build_cost_trace_context(
        trace_id="trace-expensive",
        spans=[
            {
                "trace_id": "trace-expensive",
                "span_id": "root",
                "agent_id": "cfo",
                "task_id": "task-1",
                "session_id": "session-1",
                "operation": "invoke_model",
                "status": "ok",
                "model": "gpt-4o",
                "provider": "openai",
                "input_tokens": 1000,
                "output_tokens": 500,
                "cost_usd": Decimal("1.20"),
                "duration_ms": 1000,
                "payload": {},
            },
            {
                "trace_id": "trace-expensive",
                "span_id": "retry",
                "agent_id": "cfo",
                "task_id": "task-1",
                "session_id": "session-1",
                "operation": "invoke_model_retry",
                "status": "error",
                "model": "claude-sonnet",
                "provider": "anthropic",
                "input_tokens": 600,
                "output_tokens": 100,
                "cost_usd": Decimal("0.80"),
                "duration_ms": 8000,
                "payload": {"retry": True},
            },
        ],
        related_logs=[{"id": "log-1"}],
        audit_entries=[{"id": 1}],
        decisions=[{"id": "decision-1"}],
    )

    assert context["summary"] == {
        "trace_id": "trace-expensive",
        "agent_id": "cfo",
        "task_id": "task-1",
        "session_id": "session-1",
        "status": "error",
        "total_cost_usd": 2.0,
        "tokens": 2200,
        "input_tokens": 1600,
        "output_tokens": 600,
        "span_count": 2,
        "duration_ms": 9000,
        "p95_latency_ms": 8000,
        "retry_cost_usd": 0.8,
    }
    assert context["links"] == {
        "trace": "/traces/trace-expensive",
        "agent": "/agents/cfo",
        "chat": "/agents/cfo/chat?task_id=task-1&trace_id=trace-expensive",
        "task": "/tasks/task-1",
        "logs": "/logs?trace_id=trace-expensive",
        "audit": "/audit?action=&source=&trace_id=trace-expensive",
    }
    assert context["anomalies"] == [
        {"kind": "latency", "label": "High p95 latency", "tone": "warning"},
        {"kind": "routing", "label": "Multiple model routes", "tone": "warning"},
        {"kind": "retry_cost", "label": "Retry spend detected", "tone": "incident"},
    ]
    assert context["model_breakdown"][0]["key"] == "openai/gpt-4o"
    assert context["spans"][1]["retry"] is True
    assert context["metrics"]["log_count"] == 1
