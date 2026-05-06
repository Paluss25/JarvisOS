"""Trace Explorer endpoints for JarvisOS agent execution traces."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool
from platform_api.links import build_chat_link

router = APIRouter(prefix="/api/traces", tags=["traces"])
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


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _redact_payload(value: Any) -> Any:
    sensitive_markers = ("password", "secret", "token", "api_key", "authorization")
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in sensitive_markers):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    return value


def _offset_ms(start: Any, baseline: Any) -> int:
    if not isinstance(start, datetime) or not isinstance(baseline, datetime):
        return 0
    return max(0, int((start - baseline).total_seconds() * 1000))


def _span_to_dict(span: dict) -> dict:
    return {
        "trace_id": span["trace_id"],
        "span_id": span["span_id"],
        "parent_span_id": span.get("parent_span_id"),
        "ts_start": _serialize(span.get("ts_start")),
        "ts_end": _serialize(span.get("ts_end")),
        "operation": span["operation"],
        "agent_id": span.get("agent_id"),
        "task_id": str(span["task_id"]) if span.get("task_id") is not None else None,
        "session_id": span.get("session_id"),
        "status": span.get("status") or "ok",
        "duration_ms": span.get("duration_ms") or 0,
        "input_tokens": span.get("input_tokens") or 0,
        "output_tokens": span.get("output_tokens") or 0,
        "cost_usd": _money(span.get("cost_usd")),
        "model": span.get("model"),
        "provider": span.get("provider"),
        "payload": _redact_payload(span.get("payload") or {}),
    }


def build_trace_summaries(spans: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for span in spans:
        grouped[span["trace_id"]].append(span)

    summaries = []
    for trace_id, trace_spans in grouped.items():
        ordered = sorted(trace_spans, key=lambda item: item.get("ts_start"))
        first = ordered[0]
        last = ordered[-1]
        status = "error" if any(span.get("status") == "error" for span in ordered) else "ok"
        duration_ms = sum((span.get("duration_ms") or 0) for span in ordered)
        input_tokens = sum((span.get("input_tokens") or 0) for span in ordered)
        output_tokens = sum((span.get("output_tokens") or 0) for span in ordered)
        cost_usd = sum(_money(span.get("cost_usd")) for span in ordered)

        summaries.append({
            "trace_id": trace_id,
            "agent_id": first.get("agent_id"),
            "task_id": str(first["task_id"]) if first.get("task_id") is not None else None,
            "session_id": first.get("session_id"),
            "status": status,
            "started_at": first.get("ts_start"),
            "ended_at": last.get("ts_end"),
            "duration_ms": duration_ms,
            "span_count": len(ordered),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 6),
            "links": {
                "detail": f"/traces/{trace_id}",
            },
        })

    return sorted(summaries, key=lambda item: item["started_at"], reverse=True)


def nest_trace_spans(spans: list[dict]) -> list[dict]:
    ordered = sorted(spans, key=lambda item: item.get("ts_start"))
    by_id = {
        span["span_id"]: {**_span_to_dict(span), "children": []}
        for span in ordered
    }
    roots = []

    for span in ordered:
        node = by_id[span["span_id"]]
        parent_id = span.get("parent_span_id")
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots


def build_trace_context(
    *,
    spans: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    summaries = build_trace_summaries(spans)
    summary = summaries[0]
    ordered = sorted(spans, key=lambda item: item.get("ts_start"))
    flat_spans = [_span_to_dict(span) for span in ordered]
    baseline = ordered[0].get("ts_start") if ordered else None
    trace_id = summary["trace_id"]
    agent_id = summary.get("agent_id")
    task_id = summary.get("task_id")
    return {
        "summary": summary,
        "spans": nest_trace_spans(spans),
        "flat_spans": flat_spans,
        "waterfall": [
            {
                "span_id": span["span_id"],
                "operation": span["operation"],
                "status": span.get("status") or "ok",
                "offset_ms": _offset_ms(span.get("ts_start"), baseline),
                "duration_ms": span.get("duration_ms") or 0,
            }
            for span in ordered
        ],
        "metrics": {
            "span_count": len(ordered),
            "error_count": sum(1 for span in ordered if span.get("status") in {"error", "failed"}),
            "log_count": len(logs),
            "audit_count": len(audit_entries),
            "decision_count": len(decisions),
            "token_count": summary["input_tokens"] + summary["output_tokens"],
            "cost_usd": summary["cost_usd"],
        },
        "links": {
            "detail": f"/traces/{trace_id}",
            "agent": f"/agents/{agent_id}" if agent_id else None,
            "chat": build_chat_link(agent_id, task_id=task_id, trace_id=trace_id),
            "task": f"/tasks/{task_id}" if task_id else None,
            "logs": f"/logs?trace_id={trace_id}",
            "audit": f"/audit?action=&source=&trace_id={trace_id}",
            "costs": "/costs",
        },
        "logs": logs,
        "audit_entries": audit_entries,
        "decisions": decisions,
    }


@router.get("")
async def list_traces(
    agent_id: str | None = Query(None),
    task_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
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
        SELECT trace_id, span_id, parent_span_id, ts_start, ts_end, operation,
               agent_id, task_id, session_id, status, duration_ms, input_tokens,
               output_tokens, cost_usd, model, provider, payload
        FROM trace_spans
        {where}
        ORDER BY ts_start DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return build_trace_summaries([dict(row) for row in rows])


@router.get("/{trace_id}")
async def get_trace(trace_id: str, _user=Depends(_get_current_user)):
    from platform_api.audit_endpoints import normalize_audit_entry
    from platform_api.decisions import normalize_decision
    from platform_api.logs import normalize_log_event

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT trace_id, span_id, parent_span_id, ts_start, ts_end, operation,
               agent_id, task_id, session_id, status, duration_ms, input_tokens,
               output_tokens, cost_usd, model, provider, payload
        FROM trace_spans
        WHERE trace_id = $1
        ORDER BY ts_start ASC
        """,
        trace_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = [dict(row) for row in rows]
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

    return build_trace_context(
        spans=spans,
        logs=[normalize_log_event(dict(row)) for row in event_rows],
        audit_entries=[normalize_audit_entry(dict(row)) for row in audit_rows],
        decisions=[normalize_decision(dict(row)) for row in decision_rows],
    )
