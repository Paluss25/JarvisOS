"""Logs endpoint backed by normalized JarvisOS platform events."""

from typing import Any

from fastapi import APIRouter, Depends, Query
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
