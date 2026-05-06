"""Audit log query endpoint — GET /api/audit with category/agent/time filters."""

import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool
from platform_api.links import build_chat_link

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])
_security = HTTPBearer()


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def normalize_audit_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    ts = row.get("ts")
    return {
        "id": row.get("id"),
        "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
        "category": row.get("category"),
        "agent_id": row.get("agent_id"),
        "user_id": str(row.get("user_id")) if row.get("user_id") is not None else None,
        "action": row.get("action"),
        "detail": row.get("detail") or {},
        "source": row.get("source"),
    }


def build_audit_response(rows: list[Mapping[str, Any]], total: int) -> dict[str, Any]:
    return {
        "items": [normalize_audit_entry(row) for row in rows],
        "total": total,
    }


def build_audit_context(
    *,
    entry: dict[str, Any],
    related_logs: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    detail = entry.get("detail") or {}
    agent_id = entry.get("agent_id")
    task_id = detail.get("task_id")
    trace_id = detail.get("trace_id")
    event_id = detail.get("event_id")
    decision_id = detail.get("decision_id")
    action = entry.get("action") or ""
    source = entry.get("source") or ""
    audit_href = f"/audit?action={action}&source={source}&agent_id={agent_id or ''}"
    return {
        "entry": entry,
        "metrics": {
            "detail_key_count": len(detail.keys()) if isinstance(detail, dict) else 0,
            "related_log_count": len(related_logs),
            "trace_count": len(traces),
            "decision_count": len(decisions),
        },
        "links": {
            "agent": f"/agents/{agent_id}" if agent_id else None,
            "chat": build_chat_link(agent_id, task_id=task_id, trace_id=trace_id, log_event_id=event_id),
            "task": f"/tasks/{task_id}" if task_id else None,
            "trace": f"/traces/{trace_id}" if trace_id else None,
            "event": f"/logs/{event_id}" if event_id else None,
            "decision": f"/decisions/{decision_id}" if decision_id else None,
            "logs": f"/logs?trace_id={trace_id}" if trace_id else f"/logs?task_id={task_id}" if task_id else "/logs",
            "audit": audit_href,
        },
        "related_logs": related_logs,
        "traces": traces,
        "decisions": decisions,
    }


@router.get("")
async def query_audit(
    category: str | None = Query(None, description="agent | platform | security | memory | task"),
    agent_id: str | None = Query(None),
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    source: str | None = Query(None),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _user=Depends(_get_current_user),
):
    """Return paginated audit log entries, newest first.

    All filters are optional and AND-combined.  ``from`` and ``to`` accept ISO
    8601 timestamps (e.g. ``2026-04-17`` or ``2026-04-17T09:00:00Z``).
    """
    pool = await get_pool()

    conditions: list[str] = []
    params: list = []

    def _add(condition: str, value) -> None:
        params.append(value)
        conditions.append(condition.replace("?", f"${len(params)}"))

    if category:
        _add("category = ?", category)
    if agent_id:
        _add("agent_id = ?", agent_id)
    if user_id:
        _add("user_id = ?", user_id)
    if action:
        _add("action = ?", action)
    if source:
        _add("source = ?", source)
    if from_:
        # Make timezone-aware if naive
        if from_.tzinfo is None:
            from_ = from_.replace(tzinfo=timezone.utc)
        _add("ts >= ?", from_)
    if to:
        if to.tzinfo is None:
            to = to.replace(tzinfo=timezone.utc)
        _add("ts <= ?", to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_row = await pool.fetchrow(
        f"""
        SELECT COUNT(*) AS total
        FROM audit_log
        {where}
        """,
        *params,
    )

    page_params = [*params, limit, offset]
    rows = await pool.fetch(
        f"""
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        {where}
        ORDER BY ts DESC
        LIMIT ${len(page_params) - 1} OFFSET ${len(page_params)}
        """,
        *page_params,
    )

    total = int(count_row["total"]) if count_row else 0
    return build_audit_response([dict(row) for row in rows], total)


@router.get("/{entry_id}")
async def get_audit_context(entry_id: int, _user=Depends(_get_current_user)):
    from platform_api.decisions import normalize_decision
    from platform_api.logs import normalize_log_event
    from platform_api.traces import build_trace_summaries

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        WHERE id = $1
        """,
        entry_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Audit entry not found")

    entry = normalize_audit_entry(dict(row))
    detail = entry.get("detail") or {}
    task_id = detail.get("task_id")
    trace_id = detail.get("trace_id")
    event_id = detail.get("event_id")
    decision_id = detail.get("decision_id")
    agent_id = entry.get("agent_id")

    event_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE ($1::text IS NOT NULL AND trace_id = $1)
           OR ($2::uuid IS NOT NULL AND task_id = $2::uuid)
           OR ($3::uuid IS NOT NULL AND id = $3::uuid)
           OR ($4::text IS NOT NULL AND agent_id = $4)
        ORDER BY ts DESC
        LIMIT 100
        """,
        trace_id,
        task_id,
        event_id,
        agent_id,
    )

    trace_rows = []
    if trace_id:
        trace_rows = await pool.fetch(
            """
            SELECT trace_id, span_id, parent_span_id, ts_start, ts_end, operation,
                   agent_id, task_id, session_id, status, duration_ms, input_tokens,
                   output_tokens, cost_usd, model, provider, payload
            FROM trace_spans
            WHERE trace_id = $1
            ORDER BY ts_start DESC
            LIMIT 200
            """,
            trace_id,
        )
    elif task_id:
        trace_rows = await pool.fetch(
            """
            SELECT trace_id, span_id, parent_span_id, ts_start, ts_end, operation,
                   agent_id, task_id, session_id, status, duration_ms, input_tokens,
                   output_tokens, cost_usd, model, provider, payload
            FROM trace_spans
            WHERE task_id = $1::uuid
            ORDER BY ts_start DESC
            LIMIT 200
            """,
            task_id,
        )

    decision_rows = await pool.fetch(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE ($1::uuid IS NOT NULL AND id = $1::uuid)
           OR ($2::text IS NOT NULL AND trace_id = $2)
           OR ($3::uuid IS NOT NULL AND task_id = $3::uuid)
           OR ($4::text IS NOT NULL AND agent_id = $4)
        ORDER BY ts DESC
        LIMIT 100
        """,
        decision_id,
        trace_id,
        task_id,
        agent_id,
    )

    return build_audit_context(
        entry=entry,
        related_logs=[normalize_log_event(dict(item)) for item in event_rows],
        traces=build_trace_summaries([dict(item) for item in trace_rows]),
        decisions=[normalize_decision(dict(item)) for item in decision_rows],
    )
