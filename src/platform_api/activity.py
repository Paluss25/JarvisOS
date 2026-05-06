"""Activity workspace endpoints combining historical events and audit records."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool
from platform_api.links import build_chat_link

router = APIRouter(prefix="/api/activity", tags=["activity"])
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


def _preview(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload)[:240] if payload is not None else ""
    for key in ("message", "summary", "error", "title", "description", "output", "result"):
        if payload.get(key):
            return str(payload[key])[:240]
    return str(payload)[:240]


def normalize_activity_event(row: dict[str, Any]) -> dict[str, Any]:
    event_id = _serialize(row.get("id"))
    task_id = _serialize(row.get("task_id"))
    trace_id = row.get("trace_id")
    agent_id = row.get("agent_id")
    payload = row.get("payload") or {}
    return {
        "id": event_id,
        "ts": _serialize(row.get("ts")),
        "kind": "platform_event",
        "label": row.get("event_type"),
        "severity": row.get("severity") or "info",
        "agent_id": agent_id,
        "task_id": task_id,
        "trace_id": trace_id,
        "span_id": row.get("span_id"),
        "source": row.get("source") or "platform",
        "preview": _preview(payload),
        "payload": payload,
        "links": {
            "detail": f"/logs/{event_id}" if event_id else None,
            "agent": f"/agents/{agent_id}" if agent_id else None,
            "chat": build_chat_link(agent_id, task_id=task_id, trace_id=trace_id, log_event_id=event_id),
            "task": f"/tasks/{task_id}" if task_id else None,
            "trace": f"/traces/{trace_id}" if trace_id else None,
            "audit": f"/audit?action=&source=&agent_id={agent_id}" if agent_id else "/audit",
        },
    }


def normalize_activity_audit(row: dict[str, Any]) -> dict[str, Any]:
    raw_detail = row.get("detail")
    detail = raw_detail if isinstance(raw_detail, dict) else {"message": str(raw_detail)} if raw_detail is not None else {}
    audit_id = _serialize(row.get("id"))
    task_id = detail.get("task_id")
    trace_id = detail.get("trace_id")
    agent_id = row.get("agent_id")
    action = row.get("action")
    source = row.get("source") or "audit"
    query = f"action={action or ''}&source={source}&agent_id={agent_id or ''}"
    return {
        "id": audit_id,
        "ts": _serialize(row.get("ts")),
        "kind": "audit",
        "label": action,
        "severity": "info",
        "agent_id": agent_id,
        "task_id": task_id,
        "trace_id": trace_id,
        "span_id": None,
        "source": source,
        "preview": _preview(detail),
        "payload": detail,
        "links": {
            "detail": f"/audit/{audit_id}" if audit_id else f"/audit?{query}",
            "agent": f"/agents/{agent_id}" if agent_id else None,
            "chat": build_chat_link(agent_id, task_id=task_id, trace_id=trace_id),
            "task": f"/tasks/{task_id}" if task_id else None,
            "trace": f"/traces/{trace_id}" if trace_id else None,
            "audit": f"/audit?{query}",
        },
    }


def build_activity_summary(events: list[dict[str, Any]], audit_entries: list[dict[str, Any]]) -> dict[str, Any]:
    audit_items = [normalize_activity_audit(item) for item in audit_entries]
    items = sorted([*events, *audit_items], key=lambda item: item.get("ts") or "", reverse=True)
    agent_ids = {item.get("agent_id") for item in items if item.get("agent_id")}
    return {
        "metrics": {
            "total_count": len(items),
            "platform_event_count": len(events),
            "audit_count": len(audit_items),
            "critical_count": sum(1 for item in items if item.get("severity") == "critical"),
            "error_count": sum(1 for item in items if item.get("severity") == "error"),
            "warning_count": sum(1 for item in items if item.get("severity") == "warning"),
            "agent_count": len(agent_ids),
        },
        "items": items,
    }


@router.get("/summary")
async def get_activity_summary(
    agent_id: str | None = Query(None),
    severity: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(150, ge=1, le=500),
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
    add_filter("severity", severity)
    add_filter("event_type", event_type)
    params.append(limit)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    event_rows = await pool.fetch(
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

    audit_conditions: list[str] = []
    audit_params: list[Any] = []
    if agent_id:
        audit_params.append(agent_id)
        audit_conditions.append(f"agent_id = ${len(audit_params)}")
    audit_params.append(limit)
    audit_where = f"WHERE {' AND '.join(audit_conditions)}" if audit_conditions else ""
    audit_rows = await pool.fetch(
        f"""
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        {audit_where}
        ORDER BY ts DESC
        LIMIT ${len(audit_params)}
        """,
        *audit_params,
    )

    return build_activity_summary(
        events=[normalize_activity_event(dict(row)) for row in event_rows],
        audit_entries=[dict(row) for row in audit_rows],
    )
