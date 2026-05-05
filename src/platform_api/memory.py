"""Memory and knowledge observability endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool
from platform_api.decisions import normalize_decision

router = APIRouter(prefix="/api/memory", tags=["memory"])
_security = HTTPBearer()

MEMORY_KEYWORDS = {
    "daily_log",
    "knowledge",
    "memory",
    "memory_box",
    "memory-api",
    "memory_write",
}


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


def is_memory_event(event: dict) -> bool:
    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    kind = payload.get("kind")
    source = event.get("source") or ""
    return (
        any(keyword in event_type for keyword in MEMORY_KEYWORDS)
        or kind in MEMORY_KEYWORDS
        or "memory" in str(kind or "")
        or "memory" in source
    )


def normalize_memory_event(event: dict) -> dict:
    payload = event.get("payload") or {}
    return {
        "id": _serialize(event.get("id")),
        "ts": _serialize(event.get("ts")),
        "event_type": event.get("event_type"),
        "severity": event.get("severity") or "info",
        "agent_id": event.get("agent_id"),
        "task_id": _serialize(event.get("task_id")),
        "trace_id": event.get("trace_id"),
        "source": event.get("source") or "platform",
        "kind": payload.get("kind") or event.get("event_type"),
        "domain": payload.get("domain"),
        "key": payload.get("key"),
        "scope": payload.get("scope"),
        "payload": payload,
    }


def _is_query(event: dict) -> bool:
    payload = event.get("payload") or {}
    text = f"{event.get('event_type') or ''} {payload.get('kind') or ''}"
    return "query" in text or "search" in text or "read" in text


def _is_write(event: dict) -> bool:
    if _is_daily_log(event):
        return False
    payload = event.get("payload") or {}
    text = f"{event.get('event_type') or ''} {payload.get('kind') or ''}"
    return "write" in text or "update" in text or "promotion" in text


def _is_daily_log(event: dict) -> bool:
    payload = event.get("payload") or {}
    text = f"{event.get('event_type') or ''} {payload.get('kind') or ''}"
    return "daily_log" in text


def _is_conflict(event: dict) -> bool:
    payload = event.get("payload") or {}
    text = f"{event.get('event_type') or ''} {payload.get('kind') or ''}"
    return "conflict" in text or "duplicate" in text


def build_memory_summary(events: list[dict], decisions: list[dict]) -> dict:
    memory_events = [event for event in events if is_memory_event(event)]
    domains = {
        (event.get("payload") or {}).get("domain")
        for event in memory_events
        if (event.get("payload") or {}).get("domain")
    }
    agents = {event.get("agent_id") for event in memory_events if event.get("agent_id")}
    return {
        "event_count": len(memory_events),
        "query_count": sum(1 for event in memory_events if _is_query(event)),
        "write_count": sum(1 for event in memory_events if _is_write(event)),
        "daily_log_count": sum(1 for event in memory_events if _is_daily_log(event)),
        "conflict_count": sum(1 for event in memory_events if _is_conflict(event)),
        "decision_promotions": sum(
            1
            for decision in decisions
            if "memory" in (decision.get("decision_type") or "")
        ),
        "agent_count": len(agents),
        "domain_count": len(domains),
    }


@router.get("/summary")
async def get_memory_summary(
    agent_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user=Depends(_get_current_user),
):
    pool = await get_pool()
    conditions: list[str] = []
    params: list[Any] = []

    if agent_id:
        params.append(agent_id)
        conditions.append(f"agent_id = ${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    event_rows = await pool.fetch(
        f"""
        SELECT id, ts, event_type, severity, agent_id, task_id, trace_id, source, payload
        FROM platform_events
        {where}
        ORDER BY ts DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    decision_rows = await pool.fetch(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE decision_type LIKE '%memory%'
        ORDER BY ts DESC
        LIMIT 25
        """
    )

    events = [dict(row) for row in event_rows]
    decisions = [normalize_decision(dict(row)) for row in decision_rows]
    memory_events = [normalize_memory_event(event) for event in events if is_memory_event(event)]
    return {
        "summary": build_memory_summary(events, decisions),
        "events": memory_events,
        "decisions": decisions,
    }
