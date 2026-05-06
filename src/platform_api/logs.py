"""Logs endpoint backed by normalized JarvisOS platform events."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool

router = APIRouter(prefix="/api/logs", tags=["logs"])
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


def normalize_log_event(row: dict) -> dict:
    return {
        "id": _serialize(row.get("id")),
        "ts": _serialize(row.get("ts")),
        "event_type": row.get("event_type"),
        "severity": row.get("severity") or "info",
        "agent_id": row.get("agent_id"),
        "task_id": _serialize(row.get("task_id")),
        "session_id": row.get("session_id"),
        "trace_id": row.get("trace_id"),
        "span_id": row.get("span_id"),
        "source": row.get("source") or "platform",
        "payload": row.get("payload") or {},
    }


def build_log_context(
    *,
    event: dict[str, Any],
    related_logs: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    agent_id = event.get("agent_id")
    task_id = event.get("task_id")
    trace_id = event.get("trace_id")
    severity = event.get("severity") or "info"
    priority = "urgent" if severity == "critical" else "high" if severity in {"error", "warning"} else "normal"
    return {
        "event": event,
        "metrics": {
            "related_log_count": len(related_logs),
            "audit_count": len(audit_entries),
            "decision_count": len(decisions),
            "trace_count": len(traces),
        },
        "links": {
            "agent": f"/agents/{agent_id}" if agent_id else None,
            "task": f"/tasks/{task_id}" if task_id else None,
            "trace": f"/traces/{trace_id}" if trace_id else None,
            "logs": f"/logs?trace_id={trace_id}" if trace_id else f"/logs?agent_id={agent_id}" if agent_id else "/logs",
            "audit": f"/audit?agent_id={agent_id}" if agent_id else "/audit",
        },
        "suggested_actions": [
            {"kind": "incident", "label": "Create incident", "severity": severity},
            {"kind": "task", "label": "Create task", "priority": priority},
        ],
        "related_logs": related_logs,
        "audit_entries": audit_entries,
        "decisions": decisions,
        "traces": traces,
    }


@router.get("")
async def list_logs(
    agent_id: str | None = Query(None),
    task_id: str | None = Query(None),
    trace_id: str | None = Query(None),
    severity: str | None = Query(None),
    event_type: str | None = Query(None),
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
    add_filter("severity", severity)
    add_filter("event_type", event_type)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        {where}
        ORDER BY ts DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [normalize_log_event(dict(row)) for row in rows]


@router.get("/{event_id}")
async def get_log_context(event_id: UUID, _user=Depends(_get_current_user)):
    from platform_api.audit_endpoints import normalize_audit_entry
    from platform_api.decisions import normalize_decision
    from platform_api.traces import build_trace_summaries

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE id = $1
        """,
        event_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Log event not found")

    event = normalize_log_event(dict(row))
    params: list[Any] = []
    conditions: list[str] = []
    if event["trace_id"]:
        params.append(event["trace_id"])
        conditions.append(f"trace_id = ${len(params)}")
    if event["task_id"]:
        params.append(event["task_id"])
        conditions.append(f"task_id = ${len(params)}")
    if event["agent_id"]:
        params.append(event["agent_id"])
        conditions.append(f"agent_id = ${len(params)}")

    related_logs: list[dict[str, Any]] = []
    if conditions:
        params.append(event_id)
        params.append(100)
        event_rows = await pool.fetch(
            f"""
            SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
                   trace_id, span_id, source, payload
            FROM platform_events
            WHERE ({' OR '.join(conditions)})
              AND id <> ${len(params) - 1}
            ORDER BY ts DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
        related_logs = [normalize_log_event(dict(item)) for item in event_rows]

    trace_rows = []
    if event["trace_id"]:
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
            event["trace_id"],
        )
    elif event["task_id"]:
        trace_rows = await pool.fetch(
            """
            SELECT trace_id, span_id, parent_span_id, ts_start, ts_end, operation,
                   agent_id, task_id, session_id, status, duration_ms, input_tokens,
                   output_tokens, cost_usd, model, provider, payload
            FROM trace_spans
            WHERE task_id = $1
            ORDER BY ts_start DESC
            LIMIT 200
            """,
            event["task_id"],
        )

    audit_rows = await pool.fetch(
        """
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        WHERE detail->>'event_id' = $1
           OR detail->>'task_id' = $2
           OR agent_id = $3
        ORDER BY ts DESC
        LIMIT 100
        """,
        event["id"],
        event["task_id"],
        event["agent_id"],
    )
    decision_rows = await pool.fetch(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE ($1::uuid IS NOT NULL AND task_id = $1::uuid)
           OR ($2::text IS NOT NULL AND trace_id = $2)
           OR ($3::text IS NOT NULL AND agent_id = $3)
        ORDER BY ts DESC
        LIMIT 100
        """,
        event["task_id"],
        event["trace_id"],
        event["agent_id"],
    )

    return build_log_context(
        event=event,
        related_logs=related_logs,
        audit_entries=[normalize_audit_entry(dict(item)) for item in audit_rows],
        decisions=[normalize_decision(dict(item)) for item in decision_rows],
        traces=build_trace_summaries([dict(item) for item in trace_rows]),
    )
