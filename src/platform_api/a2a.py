"""A2A network endpoints derived from platform event envelopes."""

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool

router = APIRouter(prefix="/api/a2a", tags=["a2a"])
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


def is_a2a_event(event: dict) -> bool:
    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    return (
        "a2a" in event_type
        or bool(event.get("a2a_message_id"))
        or ("from_agent" in payload and "to_agent" in payload)
    )


def normalize_a2a_event(event: dict) -> dict:
    payload = event.get("payload") or {}
    return {
        "id": _serialize(event.get("id")),
        "ts": _serialize(event.get("ts")),
        "event_type": event.get("event_type"),
        "severity": event.get("severity") or "info",
        "task_id": _serialize(event.get("task_id")),
        "trace_id": event.get("trace_id"),
        "message_id": event.get("a2a_message_id") or payload.get("id"),
        "correlation_id": payload.get("correlation_id"),
        "root_correlation_id": payload.get("root_correlation_id"),
        "parent_correlation_id": payload.get("parent_correlation_id"),
        "from_agent": payload.get("from_agent") or payload.get("from"),
        "to_agent": payload.get("to_agent") or payload.get("to"),
        "message_type": payload.get("type") or payload.get("message_type"),
        "mode": payload.get("mode") or "sync",
        "hop_count": payload.get("hop_count") or 0,
        "max_hops": payload.get("max_hops") or 5,
        "status": payload.get("status") or event.get("severity") or "info",
        "payload": payload,
    }


def _is_failure(event: dict) -> bool:
    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    return (
        event.get("severity") in {"critical", "error"}
        or "dead_letter" in event_type
        or "failed" in event_type
        or payload.get("status") == "failed"
    )


def _is_loop_warning(event: dict) -> bool:
    payload = event.get("payload") or {}
    hop_count = payload.get("hop_count") or 0
    max_hops = payload.get("max_hops") or 5
    return bool(payload.get("loop_detected")) or hop_count >= max_hops


def build_a2a_summary(events: list[dict]) -> dict:
    a2a_events = [event for event in events if is_a2a_event(event)]
    normalized = [normalize_a2a_event(event) for event in a2a_events]
    edges = {
        (event.get("from_agent"), event.get("to_agent"))
        for event in normalized
        if event.get("from_agent") and event.get("to_agent")
    }
    return {
        "message_count": len(normalized),
        "request_count": sum(1 for event in normalized if event.get("message_type") == "request"),
        "response_count": sum(1 for event in normalized if event.get("message_type") == "response"),
        "notification_count": sum(1 for event in normalized if event.get("message_type") == "notification"),
        "async_count": sum(1 for event in normalized if event.get("mode") == "async"),
        "failure_count": sum(1 for event in a2a_events if _is_failure(event)),
        "loop_warnings": sum(1 for event in a2a_events if _is_loop_warning(event)),
        "edge_count": len(edges),
    }


@router.get("/summary")
async def get_a2a_summary(_user=Depends(_get_current_user)):
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, task_id, trace_id, a2a_message_id,
               payload
        FROM platform_events
        WHERE event_type LIKE '%a2a%'
           OR a2a_message_id IS NOT NULL
           OR payload ? 'from_agent'
        ORDER BY ts DESC
        LIMIT 100
        """
    )
    events = [dict(row) for row in rows]
    messages = [normalize_a2a_event(event) for event in events if is_a2a_event(event)]
    return {
        "summary": build_a2a_summary(events),
        "messages": messages,
    }
