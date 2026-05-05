"""Trace Explorer endpoints for JarvisOS agent execution traces."""

from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool

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


def _span_to_dict(span: dict) -> dict:
    return {
        "trace_id": span["trace_id"],
        "span_id": span["span_id"],
        "parent_span_id": span.get("parent_span_id"),
        "ts_start": span.get("ts_start"),
        "ts_end": span.get("ts_end"),
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
        "payload": span.get("payload") or {},
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
    summaries = build_trace_summaries(spans)
    return {
        "summary": summaries[0],
        "spans": nest_trace_spans(spans),
    }
