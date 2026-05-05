"""Incident endpoints backed by platform_events."""

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
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
