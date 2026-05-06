"""Decision ledger endpoints for JarvisOS agent audit trails."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool
from platform_api.links import build_chat_link

router = APIRouter(prefix="/api/decisions", tags=["decisions"])
_security = HTTPBearer()


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def normalize_decision(row: dict) -> dict:
    return {
        "id": _serialize(row.get("id")),
        "ts": _serialize(row.get("ts")),
        "agent_id": row.get("agent_id"),
        "task_id": _serialize(row.get("task_id")),
        "trace_id": row.get("trace_id"),
        "title": row.get("title"),
        "summary": row.get("summary"),
        "decision_type": row.get("decision_type") or "operational",
        "confidence": _number(row.get("confidence")),
        "status": row.get("status") or "proposed",
        "evidence": row.get("evidence") or [],
        "payload": row.get("payload") or {},
    }


def build_decision_context(
    *,
    decision: dict[str, Any],
    related_logs: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    agent_id = decision.get("agent_id")
    task_id = decision.get("task_id")
    trace_id = decision.get("trace_id")
    evidence = decision.get("evidence") or []
    payload = decision.get("payload") or {}

    return {
        "decision": decision,
        "metrics": {
            "evidence_count": len(evidence),
            "payload_key_count": len(payload.keys()) if isinstance(payload, dict) else 0,
            "related_log_count": len(related_logs),
            "trace_count": len(traces),
            "audit_count": len(audit_entries),
        },
        "links": {
            "agent": f"/agents/{agent_id}" if agent_id else None,
            "chat": build_chat_link(agent_id, task_id=task_id, trace_id=trace_id),
            "cockpit": f"/agents/{agent_id}/cockpit" if agent_id else None,
            "task": f"/tasks/{task_id}" if task_id else None,
            "trace": f"/traces/{trace_id}" if trace_id else None,
            "logs": f"/logs?trace_id={trace_id}" if trace_id else f"/logs?task_id={task_id}" if task_id else "/logs",
            "audit": f"/audit?action=&source=&agent_id={agent_id}" if agent_id else "/audit",
        },
        "evidence": evidence,
        "related_logs": related_logs,
        "traces": traces,
        "audit_entries": audit_entries,
    }


@router.get("")
async def list_decisions(
    agent_id: str | None = Query(None),
    task_id: str | None = Query(None),
    trace_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user=Depends(_get_current_user),
):
    pool = await get_pool()
    conditions: list[str] = []
    params: list[Any] = []

    def add_filter(column: str, value: str | None) -> None:
        if value is None:
            return
        params.append(value)
        conditions.append(f"{column} = ${len(params)}")

    add_filter("agent_id", agent_id)
    add_filter("task_id", task_id)
    add_filter("trace_id", trace_id)
    add_filter("status", status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        {where}
        ORDER BY ts DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [normalize_decision(dict(row)) for row in rows]


@router.get("/{decision_id}")
async def get_decision_context(decision_id: UUID, _user=Depends(_get_current_user)):
    from platform_api.audit_endpoints import normalize_audit_entry
    from platform_api.logs import normalize_log_event
    from platform_api.traces import build_trace_summaries

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE id = $1
        """,
        decision_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision = normalize_decision(dict(row))
    trace_id = decision.get("trace_id")
    task_id = decision.get("task_id")
    agent_id = decision.get("agent_id")

    event_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE ($1::text IS NOT NULL AND trace_id = $1)
           OR ($2::uuid IS NOT NULL AND task_id = $2::uuid)
           OR ($3::text IS NOT NULL AND agent_id = $3)
           OR decision_id = $4
        ORDER BY ts DESC
        LIMIT 100
        """,
        trace_id,
        task_id,
        agent_id,
        decision_id,
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

    audit_rows = await pool.fetch(
        """
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        WHERE detail->>'decision_id' = $1
           OR detail->>'trace_id' = $2
           OR detail->>'task_id' = $3
           OR agent_id = $4
        ORDER BY ts DESC
        LIMIT 100
        """,
        decision["id"],
        trace_id,
        task_id,
        agent_id,
    )

    return build_decision_context(
        decision=decision,
        related_logs=[normalize_log_event(dict(row)) for row in event_rows],
        traces=build_trace_summaries([dict(row) for row in trace_rows]),
        audit_entries=[normalize_audit_entry(dict(row)) for row in audit_rows],
    )
