from datetime import datetime, timezone
from decimal import Decimal

from platform_api.traces import build_trace_context, build_trace_summaries, nest_trace_spans


def _span(
    trace_id,
    span_id,
    *,
    parent_span_id=None,
    operation="invoke_agent",
    status="ok",
    duration_ms=10,
):
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "ts_start": datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc),
        "ts_end": datetime(2026, 5, 5, 10, 0, 1, tzinfo=timezone.utc),
        "operation": operation,
        "agent_id": "cio",
        "task_id": None,
        "session_id": "session-1",
        "status": status,
        "duration_ms": duration_ms,
        "input_tokens": 10,
        "output_tokens": 20,
        "cost_usd": Decimal("0.123456"),
        "model": "claude-sonnet",
        "provider": "anthropic",
        "payload": {"label": span_id},
    }


def test_build_trace_summaries_groups_and_orders_by_latest_start():
    summaries = build_trace_summaries([
        _span("trace-a", "a1", duration_ms=100),
        _span("trace-b", "b1", status="error", duration_ms=25),
        _span("trace-a", "a2", parent_span_id="a1", duration_ms=50),
    ])

    assert [item["trace_id"] for item in summaries] == ["trace-a", "trace-b"]
    assert summaries[0]["span_count"] == 2
    assert summaries[0]["duration_ms"] == 150
    assert summaries[0]["input_tokens"] == 20
    assert summaries[0]["output_tokens"] == 40
    assert summaries[0]["cost_usd"] == 0.246912
    assert summaries[1]["status"] == "error"


def test_nest_trace_spans_builds_parent_child_tree():
    nested = nest_trace_spans([
        _span("trace-a", "child", parent_span_id="root", operation="execute_tool"),
        _span("trace-a", "root"),
    ])

    assert len(nested) == 1
    assert nested[0]["span_id"] == "root"
    assert nested[0]["children"][0]["span_id"] == "child"
    assert nested[0]["children"][0]["operation"] == "execute_tool"


def test_build_trace_context_exposes_links_metrics_and_redacted_payloads():
    spans = [
        {
            **_span("trace-a", "root", duration_ms=100),
            "task_id": "22222222-2222-2222-2222-222222222222",
            "payload": {
                "prompt": "inspect service",
                "api_token": "secret-token",
                "nested": {"password": "hidden"},
            },
        },
        {
            **_span("trace-a", "tool", parent_span_id="root", operation="execute_tool", duration_ms=50),
            "task_id": "22222222-2222-2222-2222-222222222222",
            "status": "error",
            "payload": {"args": {"path": "/srv/app", "authorization": "Bearer token"}},
        },
    ]

    context = build_trace_context(
        spans=spans,
        logs=[{"id": "event-1"}],
        audit_entries=[{"id": 7}],
        decisions=[{"id": "decision-1"}],
    )

    assert context["summary"]["trace_id"] == "trace-a"
    assert context["summary"]["status"] == "error"
    assert context["metrics"] == {
        "span_count": 2,
        "error_count": 1,
        "log_count": 1,
        "audit_count": 1,
        "decision_count": 1,
        "token_count": 60,
        "cost_usd": 0.246912,
    }
    assert context["links"] == {
        "agent": "/agents/cio",
        "chat": "/agents/cio/chat?task_id=22222222-2222-2222-2222-222222222222&trace_id=trace-a",
        "task": "/tasks/22222222-2222-2222-2222-222222222222",
        "logs": "/logs?trace_id=trace-a",
        "audit": "/audit?action=&source=&trace_id=trace-a",
        "costs": "/costs",
    }
    assert context["flat_spans"][0]["payload"]["api_token"] == "[redacted]"
    assert context["flat_spans"][0]["payload"]["nested"]["password"] == "[redacted]"
    assert context["flat_spans"][1]["payload"]["args"]["authorization"] == "[redacted]"
    assert context["waterfall"][0]["offset_ms"] == 0
    assert context["waterfall"][1]["duration_ms"] == 50
