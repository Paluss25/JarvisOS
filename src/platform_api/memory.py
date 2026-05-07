"""Memory and knowledge observability endpoints."""

from typing import Any

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool
from platform_api.links import build_chat_link
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
    event_id = _serialize(event.get("id"))
    return {
        "id": event_id,
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
        "links": {
            "detail": f"/memory/events/{event_id}",
        },
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


def build_memory_event_context(
    *,
    event: dict[str, Any],
    related_events: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    agent_id = event.get("agent_id")
    task_id = event.get("task_id")
    trace_id = event.get("trace_id")
    promotion_count = sum(1 for decision in decisions if "memory" in (decision.get("decision_type") or ""))
    diagnostics = []
    if _is_conflict(event):
        diagnostics.append({"kind": "conflict", "label": "Conflict or duplicate detected", "tone": "warning"})

    return {
        "event": event,
        "metrics": {
            "related_event_count": len(related_events),
            "trace_count": len(traces),
            "audit_count": len(audit_entries),
            "decision_count": len(decisions),
            "promotion_count": promotion_count,
        },
        "links": {
            "agent": f"/agents/{agent_id}" if agent_id else None,
            "chat": build_chat_link(agent_id, task_id=task_id, trace_id=trace_id, memory_event_id=event.get("id")),
            "task": f"/tasks/{task_id}" if task_id else None,
            "trace": f"/traces/{trace_id}" if trace_id else None,
            "logs": f"/logs?trace_id={trace_id}" if trace_id else f"/logs?task_id={task_id}" if task_id else "/logs",
            "audit": f"/audit?action=&source=&agent_id={agent_id}" if agent_id else "/audit",
        },
        "diagnostics": diagnostics,
        "related_events": related_events,
        "traces": traces,
        "audit_entries": audit_entries,
        "decisions": decisions,
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


@router.get("/events/{event_id}")
async def get_memory_event_context(event_id: UUID, _user=Depends(_get_current_user)):
    from platform_api.audit_endpoints import normalize_audit_entry
    from platform_api.traces import build_trace_summaries

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, trace_id, source, payload
        FROM platform_events
        WHERE id = $1
        """,
        event_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Memory event not found")

    raw_event = dict(row)
    if not is_memory_event(raw_event):
        raise HTTPException(status_code=404, detail="Memory event not found")

    event = normalize_memory_event(raw_event)
    payload = raw_event.get("payload") or {}
    domain = payload.get("domain")
    key = payload.get("key")
    scope = payload.get("scope")

    related_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, trace_id, source, payload
        FROM platform_events
        WHERE (
            id = $1
            OR ($2::text IS NOT NULL AND payload->>'key' = $2)
            OR ($3::text IS NOT NULL AND payload->>'domain' = $3)
            OR ($4::text IS NOT NULL AND payload->>'scope' = $4)
            OR ($5::text IS NOT NULL AND trace_id = $5)
            OR ($6::uuid IS NOT NULL AND task_id = $6::uuid)
        )
        ORDER BY ts DESC
        LIMIT 100
        """,
        event_id,
        key,
        domain,
        scope,
        event["trace_id"],
        event["task_id"],
    )
    related_events = [
        normalize_memory_event(dict(item))
        for item in related_rows
        if is_memory_event(dict(item))
    ]

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
    audit_rows = await pool.fetch(
        """
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        WHERE detail->>'memory_event_id' = $1
           OR detail->>'memory_key' = $2
           OR detail->>'task_id' = $3
           OR agent_id = $4
        ORDER BY ts DESC
        LIMIT 100
        """,
        event["id"],
        key,
        event["task_id"],
        event["agent_id"],
    )
    decision_rows = await pool.fetch(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE decision_type LIKE '%memory%'
           OR ($1::uuid IS NOT NULL AND task_id = $1::uuid)
           OR ($2::text IS NOT NULL AND trace_id = $2)
           OR ($3::text IS NOT NULL AND agent_id = $3)
        ORDER BY ts DESC
        LIMIT 100
        """,
        event["task_id"],
        event["trace_id"],
        event["agent_id"],
    )
    decisions = [normalize_decision(dict(row)) for row in decision_rows]

    return build_memory_event_context(
        event=event,
        related_events=related_events,
        traces=build_trace_summaries([dict(row) for row in trace_rows]),
        audit_entries=[normalize_audit_entry(dict(row)) for row in audit_rows],
        decisions=decisions,
    )
