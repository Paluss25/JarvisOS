"""Incident endpoints backed by platform_events."""

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from platform_api.audit import AuditEvent, audit
from platform_api.db import get_pool
from platform_api.logs import normalize_log_event

router = APIRouter(prefix="/api/incidents", tags=["incidents"])
_security = HTTPBearer()


class IncidentCreate(BaseModel):
    title: str
    severity: str = "warning"
    description: str = ""
    agent_id: str | None = None
    task_id: str | None = None
    trace_id: str | None = None


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def build_incident_event(
    *,
    title: str,
    severity: str = "warning",
    agent_id: str | None = None,
    task_id: str | None = None,
    trace_id: str | None = None,
    description: str = "",
    created_by: str | None = None,
) -> dict:
    return {
        "event_type": "incident",
        "severity": severity,
        "agent_id": agent_id,
        "task_id": task_id,
        "trace_id": trace_id,
        "source": "dashboard",
        "payload": {
            "kind": "incident",
            "title": title,
            "description": description,
            "status": "open",
            "created_by": created_by,
        },
    }


def is_incident_event(row: dict) -> bool:
    payload = row.get("payload") or {}
    return row.get("event_type") == "incident" and payload.get("kind") == "incident"


def build_incident_context(
    *,
    incident: dict[str, Any],
    related_logs: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    agent_id = incident.get("agent_id")
    task_id = incident.get("task_id")
    trace_id = incident.get("trace_id")
    return {
        "incident": incident,
        "metrics": {
            "log_count": len(related_logs),
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
            "ciso": "/agents/ciso/cockpit",
            "cio": "/agents/cio/cockpit",
        },
        "related_logs": related_logs,
        "audit_entries": audit_entries,
        "decisions": decisions,
        "traces": traces,
    }


@router.get("")
async def list_incidents(
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user=Depends(_get_current_user),
):
    pool = await get_pool()
    params: list[Any] = []
    conditions = ["event_type = 'incident'", "payload->>'kind' = 'incident'"]
    if status:
        params.append(status)
        conditions.append(f"payload->>'status' = ${len(params)}")

    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE {' AND '.join(conditions)}
        ORDER BY ts DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [normalize_log_event(dict(row)) for row in rows]


@router.get("/{incident_id}")
async def get_incident_context(incident_id: UUID, _user=Depends(_get_current_user)):
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
          AND event_type = 'incident'
          AND payload->>'kind' = 'incident'
        """,
        incident_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident = normalize_log_event(dict(row))
    params: list[Any] = []
    conditions: list[str] = []
    if incident["trace_id"]:
        params.append(incident["trace_id"])
        conditions.append(f"trace_id = ${len(params)}")
    if incident["task_id"]:
        params.append(incident["task_id"])
        conditions.append(f"task_id = ${len(params)}")
    if incident["agent_id"]:
        params.append(incident["agent_id"])
        conditions.append(f"agent_id = ${len(params)}")

    related_logs: list[dict[str, Any]] = []
    if conditions:
        params.append(incident_id)
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
        related_logs = [normalize_log_event(dict(event)) for event in event_rows]

    trace_rows = []
    if incident["trace_id"]:
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
            incident["trace_id"],
        )
    elif incident["task_id"]:
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
            incident["task_id"],
        )

    audit_rows = await pool.fetch(
        """
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        WHERE detail->>'incident_id' = $1
           OR detail->>'task_id' = $2
           OR agent_id = $3
        ORDER BY ts DESC
        LIMIT 100
        """,
        incident["id"],
        incident["task_id"],
        incident["agent_id"],
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
        incident["task_id"],
        incident["trace_id"],
        incident["agent_id"],
    )

    return build_incident_context(
        incident=incident,
        related_logs=related_logs,
        audit_entries=[normalize_audit_entry(dict(item)) for item in audit_rows],
        decisions=[normalize_decision(dict(item)) for item in decision_rows],
        traces=build_trace_summaries([dict(item) for item in trace_rows]),
    )


@router.post("", status_code=201)
async def create_incident(req: IncidentCreate, user=Depends(_get_current_user)):
    pool = await get_pool()
    created_by = user.get("sub") if hasattr(user, "get") else None
    incident = build_incident_event(
        title=req.title,
        severity=req.severity,
        agent_id=req.agent_id,
        task_id=req.task_id,
        trace_id=req.trace_id,
        description=req.description,
        created_by=created_by,
    )
    row = await pool.fetchrow(
        """
        INSERT INTO platform_events
            (event_type, severity, agent_id, task_id, trace_id, source, payload)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        RETURNING id, ts, event_type, severity, agent_id, task_id, session_id,
                  trace_id, span_id, source, payload
        """,
        incident["event_type"],
        incident["severity"],
        incident["agent_id"],
        incident["task_id"],
        incident["trace_id"],
        incident["source"],
        json.dumps(incident["payload"]),
    )
    normalized = normalize_log_event(dict(row))
    await audit.log(AuditEvent(
        category="platform",
        action="incident_created",
        source="api",
        agent_id=req.agent_id,
        user_id=created_by,
        detail={
            "incident_id": normalized["id"],
            "title": req.title,
            "severity": req.severity,
            "trace_id": req.trace_id,
            "task_id": req.task_id,
        },
    ))
    return normalized
