"""Cost and model usage endpoints backed by trace spans."""

from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool

router = APIRouter(prefix="/api/costs", tags=["costs"])
_security = HTTPBearer()


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def _money(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def normalize_cost_group(row: dict) -> dict:
    input_tokens = _int(row.get("input_tokens"))
    output_tokens = _int(row.get("output_tokens"))
    return {
        "key": row.get("key") or "unknown",
        "cost_usd": round(_money(row.get("cost_usd")), 6),
        "tokens": input_tokens + output_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "span_count": _int(row.get("span_count")),
        "duration_ms": _int(row.get("duration_ms")),
    }


def _percentile_nearest(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(min(round((len(ordered) - 1) * percentile), len(ordered) - 1), 0)
    return ordered[index]


def _group_spans(spans: list[dict], key_fn) -> list[dict]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "span_count": 0,
        "duration_ms": 0,
    })
    for span in spans:
        key = key_fn(span) or "unknown"
        row = grouped[str(key)]
        row["cost_usd"] += _money(span.get("cost_usd"))
        row["input_tokens"] += _int(span.get("input_tokens"))
        row["output_tokens"] += _int(span.get("output_tokens"))
        row["span_count"] += 1
        row["duration_ms"] += _int(span.get("duration_ms"))

    rows = [normalize_cost_group({"key": key, **value}) for key, value in grouped.items()]
    return sorted(rows, key=lambda item: item["cost_usd"], reverse=True)


def _is_retry_span(span: dict[str, Any]) -> bool:
    payload = span.get("payload") or {}
    operation = span.get("operation") or ""
    return bool(payload.get("retry")) or "retry" in operation


def _span_to_cost_dict(span: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _int(span.get("input_tokens"))
    output_tokens = _int(span.get("output_tokens"))
    return {
        "trace_id": span.get("trace_id"),
        "span_id": span.get("span_id"),
        "operation": span.get("operation"),
        "status": span.get("status") or "ok",
        "agent_id": span.get("agent_id"),
        "task_id": str(span.get("task_id")) if span.get("task_id") is not None else None,
        "session_id": span.get("session_id"),
        "model": span.get("model"),
        "provider": span.get("provider"),
        "duration_ms": _int(span.get("duration_ms")),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": input_tokens + output_tokens,
        "cost_usd": round(_money(span.get("cost_usd")), 6),
        "retry": _is_retry_span(span),
    }


def _trace_status(spans: list[dict[str, Any]]) -> str:
    if any((span.get("status") or "ok") in {"error", "failed"} for span in spans):
        return "error"
    return "ok"


def build_cost_summary(spans: list[dict]) -> dict:
    input_tokens = sum(_int(span.get("input_tokens")) for span in spans)
    output_tokens = sum(_int(span.get("output_tokens")) for span in spans)
    total_cost = sum(_money(span.get("cost_usd")) for span in spans)
    durations = [_int(span.get("duration_ms")) for span in spans if span.get("duration_ms") is not None]

    return {
        "total_cost_usd": round(total_cost, 6),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": input_tokens + output_tokens,
        "span_count": len(spans),
        "p95_latency_ms": _percentile_nearest(durations, 0.95),
        "by_agent": _group_spans(spans, lambda span: span.get("agent_id")),
        "by_model": _group_spans(
            spans,
            lambda span: "/".join(
                part for part in [span.get("provider"), span.get("model")] if part
            ),
        ),
        "by_task": _group_spans(spans, lambda span: span.get("task_id")),
        "by_session": _group_spans(spans, lambda span: span.get("session_id")),
        "top_traces": _group_spans(spans, lambda span: span.get("trace_id")),
    }


def build_cost_trace_context(
    *,
    trace_id: str,
    spans: list[dict[str, Any]],
    related_logs: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = list(spans)
    input_tokens = sum(_int(span.get("input_tokens")) for span in ordered)
    output_tokens = sum(_int(span.get("output_tokens")) for span in ordered)
    duration_ms = sum(_int(span.get("duration_ms")) for span in ordered)
    total_cost = sum(_money(span.get("cost_usd")) for span in ordered)
    retry_cost = sum(_money(span.get("cost_usd")) for span in ordered if _is_retry_span(span))
    durations = [_int(span.get("duration_ms")) for span in ordered if span.get("duration_ms") is not None]
    models = {
        "/".join(part for part in [span.get("provider"), span.get("model")] if part)
        for span in ordered
        if span.get("provider") or span.get("model")
    }
    first = ordered[0] if ordered else {}
    agent_id = first.get("agent_id")
    task_id = str(first.get("task_id")) if first.get("task_id") is not None else None
    p95_latency = _percentile_nearest(durations, 0.95)
    anomalies = []
    if p95_latency >= 5000:
        anomalies.append({"kind": "latency", "label": "High p95 latency", "tone": "warning"})
    if len(models) > 1:
        anomalies.append({"kind": "routing", "label": "Multiple model routes", "tone": "warning"})
    if retry_cost:
        anomalies.append({"kind": "retry_cost", "label": "Retry spend detected", "tone": "incident"})

    return {
        "summary": {
            "trace_id": trace_id,
            "agent_id": agent_id,
            "task_id": task_id,
            "session_id": first.get("session_id"),
            "status": _trace_status(ordered),
            "total_cost_usd": round(total_cost, 6),
            "tokens": input_tokens + output_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "span_count": len(ordered),
            "duration_ms": duration_ms,
            "p95_latency_ms": p95_latency,
            "retry_cost_usd": round(retry_cost, 6),
        },
        "metrics": {
            "log_count": len(related_logs),
            "audit_count": len(audit_entries),
            "decision_count": len(decisions),
            "model_count": len(models),
        },
        "links": {
            "trace": f"/traces/{trace_id}",
            "agent": f"/agents/{agent_id}" if agent_id else None,
            "task": f"/tasks/{task_id}" if task_id else None,
            "logs": f"/logs?trace_id={trace_id}",
            "audit": f"/audit?action=&source=&trace_id={trace_id}",
        },
        "anomalies": anomalies,
        "model_breakdown": _group_spans(ordered, lambda span: "/".join(part for part in [span.get("provider"), span.get("model")] if part)),
        "spans": [_span_to_cost_dict(span) for span in ordered],
        "related_logs": related_logs,
        "audit_entries": audit_entries,
        "decisions": decisions,
    }


@router.get("/summary")
async def get_cost_summary(
    agent_id: str | None = Query(None),
    task_id: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    _user=Depends(_get_current_user),
):
    pool = await get_pool()
    conditions: list[str] = []
    params: list[Any] = []

    if agent_id:
        params.append(agent_id)
        conditions.append(f"agent_id = ${len(params)}")
    if task_id:
        params.append(task_id)
        conditions.append(f"task_id = ${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT agent_id, task_id, session_id, model, provider, duration_ms,
               input_tokens, output_tokens, cost_usd, trace_id, span_id,
               operation, status, payload
        FROM trace_spans
        {where}
        ORDER BY ts_start DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return build_cost_summary([dict(row) for row in rows])


@router.get("/traces/{trace_id}")
async def get_cost_trace_context(trace_id: str, _user=Depends(_get_current_user)):
    from platform_api.audit_endpoints import normalize_audit_entry
    from platform_api.decisions import normalize_decision
    from platform_api.logs import normalize_log_event

    pool = await get_pool()
    span_rows = await pool.fetch(
        """
        SELECT trace_id, span_id, operation, agent_id, task_id, session_id, model,
               provider, duration_ms, input_tokens, output_tokens, cost_usd, status,
               payload
        FROM trace_spans
        WHERE trace_id = $1
        ORDER BY ts_start ASC
        """,
        trace_id,
    )
    if not span_rows:
        raise HTTPException(status_code=404, detail="Cost trace not found")

    spans = [dict(row) for row in span_rows]
    task_id = next((span.get("task_id") for span in spans if span.get("task_id") is not None), None)
    agent_id = next((span.get("agent_id") for span in spans if span.get("agent_id")), None)
    event_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE trace_id = $1
        ORDER BY ts DESC
        LIMIT 100
        """,
        trace_id,
    )
    audit_rows = await pool.fetch(
        """
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        WHERE detail->>'trace_id' = $1
           OR detail->>'task_id' = $2
           OR agent_id = $3
        ORDER BY ts DESC
        LIMIT 100
        """,
        trace_id,
        str(task_id) if task_id is not None else None,
        agent_id,
    )
    decision_rows = await pool.fetch(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE trace_id = $1
           OR ($2::uuid IS NOT NULL AND task_id = $2::uuid)
           OR ($3::text IS NOT NULL AND agent_id = $3)
        ORDER BY ts DESC
        LIMIT 100
        """,
        trace_id,
        str(task_id) if task_id is not None else None,
        agent_id,
    )

    return build_cost_trace_context(
        trace_id=trace_id,
        spans=spans,
        related_logs=[normalize_log_event(dict(row)) for row in event_rows],
        audit_entries=[normalize_audit_entry(dict(row)) for row in audit_rows],
        decisions=[normalize_decision(dict(row)) for row in decision_rows],
    )
