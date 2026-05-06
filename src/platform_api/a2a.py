"""A2A network endpoints derived from platform event envelopes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool
from platform_api.links import build_chat_link

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
    event_id = _serialize(event.get("id"))
    return {
        "id": event_id,
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
        "links": {
            "detail": f"/a2a/messages/{event_id}",
        },
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


def _is_normalized_failure(message: dict) -> bool:
    return (
        message.get("severity") in {"critical", "error"}
        or message.get("status") == "failed"
        or "dead_letter" in (message.get("event_type") or "")
        or "failed" in (message.get("event_type") or "")
    )


def _is_loop_warning(event: dict) -> bool:
    payload = event.get("payload") or {}
    hop_count = payload.get("hop_count") or 0
    max_hops = payload.get("max_hops") or 5
    return bool(payload.get("loop_detected")) or hop_count >= max_hops


def build_a2a_edges(messages: list[dict]) -> list[dict]:
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for message in messages:
        from_agent = message.get("from_agent")
        to_agent = message.get("to_agent")
        if not from_agent or not to_agent:
            continue
        key = (from_agent, to_agent)
        edge = edges.setdefault(key, {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "message_count": 0,
            "failure_count": 0,
            "last_seen": message.get("ts"),
        })
        edge["message_count"] += 1
        if _is_normalized_failure(message):
            edge["failure_count"] += 1
        if message.get("ts") and (edge["last_seen"] is None or message["ts"] > edge["last_seen"]):
            edge["last_seen"] = message["ts"]

    return sorted(edges.values(), key=lambda item: (item["message_count"], item["last_seen"] or ""), reverse=True)


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


def build_a2a_message_context(
    *,
    event: dict[str, Any],
    thread_events: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    message = normalize_a2a_event(event)
    thread = [normalize_a2a_event(item) for item in thread_events if is_a2a_event(item)]
    trace_id = message.get("trace_id")
    task_id = message.get("task_id")
    from_agent = message.get("from_agent")
    to_agent = message.get("to_agent")
    priority = "urgent" if message.get("severity") == "critical" else "high" if _is_normalized_failure(message) or message.get("severity") == "warning" else "normal"
    suggested_actions = [
        {"kind": "task", "label": "Create follow-up task", "priority": priority},
    ]
    if trace_id:
        suggested_actions.append({"kind": "trace", "label": "Inspect linked trace", "trace_id": trace_id})

    return {
        "message": message,
        "metrics": {
            "thread_count": len(thread),
            "failure_count": sum(1 for item in thread if _is_normalized_failure(item)),
            "loop_warnings": sum(1 for item in thread if (item.get("hop_count") or 0) >= (item.get("max_hops") or 5)),
            "log_count": len(logs),
            "trace_count": len(traces),
            "audit_count": len(audit_entries),
            "decision_count": len(decisions),
        },
        "links": {
            "from_agent": f"/agents/{from_agent}" if from_agent else None,
            "from_chat": build_chat_link(from_agent, task_id=task_id, trace_id=trace_id),
            "to_agent": f"/agents/{to_agent}" if to_agent else None,
            "to_chat": build_chat_link(to_agent, task_id=task_id, trace_id=trace_id),
            "task": f"/tasks/{task_id}" if task_id else None,
            "trace": f"/traces/{trace_id}" if trace_id else None,
            "logs": f"/logs?trace_id={trace_id}" if trace_id else f"/logs?task_id={task_id}" if task_id else "/logs",
            "audit": f"/audit?action=&source=&trace_id={trace_id}" if trace_id else "/audit",
        },
        "suggested_actions": suggested_actions,
        "thread": thread,
        "related_logs": logs,
        "traces": traces,
        "audit_entries": audit_entries,
        "decisions": decisions,
    }


async def _fetch_a2a_events(limit: int = 100, agent_id: str | None = None) -> list[dict[str, Any]]:
    pool = await get_pool()
    conditions = [
        "(event_type LIKE '%a2a%' OR a2a_message_id IS NOT NULL OR payload ? 'from_agent')"
    ]
    params: list[Any] = []
    if agent_id:
        params.append(agent_id)
        conditions.append(f"(payload->>'from_agent' = ${len(params)} OR payload->>'to_agent' = ${len(params)})")
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT id, ts, event_type, severity, task_id, trace_id, a2a_message_id,
               payload
        FROM platform_events
        WHERE {' AND '.join(conditions)}
        ORDER BY ts DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [dict(row) for row in rows]


@router.get("/summary")
async def get_a2a_summary(_user=Depends(_get_current_user)):
    events = await _fetch_a2a_events(limit=100)
    messages = [normalize_a2a_event(event) for event in events if is_a2a_event(event)]
    return {
        "summary": build_a2a_summary(events),
        "messages": messages,
        "edges": build_a2a_edges(messages),
    }


@router.get("/messages")
async def list_a2a_messages(
    agent_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user=Depends(_get_current_user),
):
    events = await _fetch_a2a_events(limit=limit, agent_id=agent_id)
    messages = [normalize_a2a_event(event) for event in events if is_a2a_event(event)]
    return {
        "summary": build_a2a_summary(events),
        "messages": messages,
        "edges": build_a2a_edges(messages),
    }


@router.get("/messages/{event_id}")
async def get_a2a_message_context(event_id: UUID, _user=Depends(_get_current_user)):
    from platform_api.audit_endpoints import normalize_audit_entry
    from platform_api.decisions import normalize_decision
    from platform_api.logs import normalize_log_event
    from platform_api.traces import build_trace_summaries

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, ts, event_type, severity, task_id, trace_id, a2a_message_id,
               payload
        FROM platform_events
        WHERE id = $1
        """,
        event_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="A2A message not found")

    event = dict(row)
    if not is_a2a_event(event):
        raise HTTPException(status_code=404, detail="A2A message not found")

    payload = event.get("payload") or {}
    message_id = event.get("a2a_message_id") or payload.get("id")
    correlation_id = payload.get("correlation_id")
    root_correlation_id = payload.get("root_correlation_id")
    parent_correlation_id = payload.get("parent_correlation_id")
    trace_id = event.get("trace_id")
    task_id = event.get("task_id")
    from_agent = payload.get("from_agent") or payload.get("from")
    to_agent = payload.get("to_agent") or payload.get("to")

    thread_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, task_id, trace_id, a2a_message_id,
               payload
        FROM platform_events
        WHERE (event_type LIKE '%a2a%' OR a2a_message_id IS NOT NULL OR payload ? 'from_agent')
          AND (
              id = $1
              OR ($2::text IS NOT NULL AND a2a_message_id = $2)
              OR ($3::text IS NOT NULL AND payload->>'correlation_id' = $3)
              OR ($3::text IS NOT NULL AND payload->>'parent_correlation_id' = $3)
              OR ($4::text IS NOT NULL AND payload->>'root_correlation_id' = $4)
              OR ($5::text IS NOT NULL AND trace_id = $5)
          )
        ORDER BY ts ASC
        LIMIT 100
        """,
        event_id,
        message_id,
        correlation_id or parent_correlation_id,
        root_correlation_id,
        trace_id,
    )

    event_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE ($1::text IS NOT NULL AND trace_id = $1)
           OR ($2::uuid IS NOT NULL AND task_id = $2::uuid)
           OR ($3::text IS NOT NULL AND payload->>'from_agent' = $3)
           OR ($4::text IS NOT NULL AND payload->>'to_agent' = $4)
        ORDER BY ts DESC
        LIMIT 100
        """,
        trace_id,
        str(task_id) if task_id is not None else None,
        from_agent,
        to_agent,
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
    audit_rows = await pool.fetch(
        """
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        WHERE detail->>'a2a_message_id' = $1
           OR detail->>'trace_id' = $2
           OR detail->>'task_id' = $3
           OR agent_id = $4
           OR agent_id = $5
        ORDER BY ts DESC
        LIMIT 100
        """,
        message_id,
        trace_id,
        str(task_id) if task_id is not None else None,
        from_agent,
        to_agent,
    )
    decision_rows = await pool.fetch(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE ($1::text IS NOT NULL AND trace_id = $1)
           OR ($2::uuid IS NOT NULL AND task_id = $2::uuid)
           OR ($3::text IS NOT NULL AND agent_id = $3)
           OR ($4::text IS NOT NULL AND agent_id = $4)
        ORDER BY ts DESC
        LIMIT 100
        """,
        trace_id,
        str(task_id) if task_id is not None else None,
        from_agent,
        to_agent,
    )

    return build_a2a_message_context(
        event=event,
        thread_events=[dict(row) for row in thread_rows],
        logs=[normalize_log_event(dict(row)) for row in event_rows if dict(row).get("id") != event_id],
        traces=build_trace_summaries([dict(row) for row in trace_rows]),
        audit_entries=[normalize_audit_entry(dict(row)) for row in audit_rows],
        decisions=[normalize_decision(dict(row)) for row in decision_rows],
    )
