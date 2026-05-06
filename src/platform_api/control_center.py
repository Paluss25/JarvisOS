"""Control Center summary endpoints for JarvisOS operations dashboard."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent_runner.registry import list_agents
from platform_api.db import get_pool

router = APIRouter(prefix="/api/control", tags=["control"])
_security = HTTPBearer()


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def build_control_summary(
    agents: list[dict],
    tasks: list[dict],
    events: list[dict],
    audit_rows: list[dict],
    decisions: list[dict] | None = None,
    trace_spans: list[dict] | None = None,
) -> dict:
    """Build the high-level dashboard summary from normalized row dictionaries."""
    running = sum(1 for agent in agents if agent.get("supervisord_state") == "RUNNING")
    open_statuses = {
        "backlog",
        "assigned",
        "pending",
        "running",
        "waiting",
        "needs_review",
        "blocked",
        "failed",
    }
    open_tasks = sum(1 for task in tasks if task.get("status") in open_statuses)
    critical = sum(1 for event in events if event.get("severity") == "critical")
    decisions = decisions or []
    trace_spans = trace_spans or []

    def serialize(value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def money(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    def task_card(task: dict) -> dict:
        task_id = serialize(task.get("id"))
        agent_id = task.get("assigned_to") or task.get("assigned_agent")
        return {
            "id": task_id,
            "title": task.get("title") or task_id,
            "status": task.get("status") or "pending",
            "priority": task.get("priority") or "normal",
            "agent_id": agent_id,
            "created_at": serialize(task.get("created_at")),
            "href": f"/tasks/{task_id}",
            "agent_href": f"/agents/{agent_id}" if agent_id else None,
        }

    def event_card(event: dict) -> dict:
        task_id = serialize(event.get("task_id"))
        trace_id = event.get("trace_id")
        payload = event.get("payload") or {}
        return {
            "id": serialize(event.get("id")),
            "ts": serialize(event.get("ts")),
            "severity": event.get("severity") or "info",
            "event_type": event.get("event_type"),
            "agent_id": event.get("agent_id"),
            "task_id": task_id,
            "trace_id": trace_id,
            "summary": payload.get("summary") or payload.get("message") or event.get("event_type"),
            "task_href": f"/tasks/{task_id}" if task_id else None,
            "trace_href": f"/traces/{trace_id}" if trace_id else None,
        }

    def decision_card(decision: dict) -> dict:
        task_id = serialize(decision.get("task_id"))
        trace_id = decision.get("trace_id")
        return {
            "id": serialize(decision.get("id")),
            "ts": serialize(decision.get("ts")),
            "agent_id": decision.get("agent_id"),
            "task_id": task_id,
            "trace_id": trace_id,
            "title": decision.get("title"),
            "status": decision.get("status") or "proposed",
            "href": f"/tasks/{task_id}" if task_id else None,
            "trace_href": f"/traces/{trace_id}" if trace_id else None,
        }

    work_in_progress = [
        task_card(task)
        for task in tasks
        if task.get("status") in {"assigned", "pending", "running", "waiting", "blocked", "failed"}
    ][:8]
    review_queue = [
        task_card(task)
        for task in tasks
        if task.get("status") == "needs_review"
    ][:8]
    incident_feed = [
        event_card(event)
        for event in events
        if event.get("severity") in {"critical", "error", "warning"}
    ][:8]
    recent_decisions = [decision_card(decision) for decision in decisions[:8]]

    grouped_traces: dict[str, dict[str, Any]] = {}
    for span in trace_spans:
        trace_id = span.get("trace_id")
        if not trace_id:
            continue
        entry = grouped_traces.setdefault(str(trace_id), {
            "trace_id": str(trace_id),
            "task_id": serialize(span.get("task_id")),
            "agent_id": span.get("agent_id"),
            "duration_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "status": "ok",
            "href": f"/traces/{trace_id}",
            "task_href": f"/tasks/{serialize(span.get('task_id'))}" if span.get("task_id") else None,
        })
        entry["duration_ms"] += span.get("duration_ms") or 0
        entry["input_tokens"] += span.get("input_tokens") or 0
        entry["output_tokens"] += span.get("output_tokens") or 0
        entry["cost_usd"] += money(span.get("cost_usd"))
        if span.get("status") == "error":
            entry["status"] = "error"

    slow_traces = sorted(
        grouped_traces.values(),
        key=lambda item: item["duration_ms"],
        reverse=True,
    )[:8]
    for trace in slow_traces:
        trace["cost_usd"] = round(trace["cost_usd"], 6)

    agent_spotlight = [
        {
            "id": agent.get("id"),
            "status": "running" if agent.get("supervisord_state") == "RUNNING" else "stopped",
            "href": f"/agents/{agent.get('id')}",
            "cockpit_href": f"/agents/{agent.get('id')}/cockpit",
        }
        for agent in agents
        if agent.get("supervisord_state") != "RUNNING"
    ][:8]
    if not agent_spotlight:
        agent_spotlight = [
            {
                "id": agent.get("id"),
                "status": "running",
                "href": f"/agents/{agent.get('id')}",
                "cockpit_href": f"/agents/{agent.get('id')}/cockpit",
            }
            for agent in agents[:4]
        ]

    cost_today = round(sum(trace["cost_usd"] for trace in grouped_traces.values()), 6)
    tokens_today = sum(
        trace["input_tokens"] + trace["output_tokens"]
        for trace in grouped_traces.values()
    )

    return {
        "agents": {
            "total": len(agents),
            "running": running,
            "not_running": max(len(agents) - running, 0),
        },
        "tasks": {
            "open": open_tasks,
            "total": len(tasks),
            "running": sum(1 for task in tasks if task.get("status") == "running"),
            "needs_review": sum(1 for task in tasks if task.get("status") == "needs_review"),
            "blocked": sum(1 for task in tasks if task.get("status") in {"blocked", "failed"}),
        },
        "incidents": {
            "critical": critical,
            "active": sum(
                1
                for event in events
                if event.get("severity") in {"critical", "error", "warning"}
            ),
        },
        "costs": {
            "today_usd": cost_today,
            "tokens_today": tokens_today,
        },
        "recent_audit": audit_rows[:10],
        "work_in_progress": work_in_progress,
        "needs_review": review_queue,
        "incident_feed": incident_feed,
        "recent_decisions": recent_decisions,
        "slow_traces": slow_traces,
        "agent_spotlight": agent_spotlight,
    }


@router.get("/summary")
async def control_summary(_user=Depends(_get_current_user)):
    pool = await get_pool()
    agents = list_agents()
    tasks = [
        dict(row)
        for row in await pool.fetch("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 200")
    ]
    events = [
        dict(row)
        for row in await pool.fetch(
            "SELECT severity, event_type, agent_id, ts, payload FROM platform_events ORDER BY ts DESC LIMIT 200"
        )
    ]
    audit_rows = [
        dict(row)
        for row in await pool.fetch(
            "SELECT ts, category, agent_id, action, detail, source FROM audit_log ORDER BY ts DESC LIMIT 20"
        )
    ]
    decisions = [
        dict(row)
        for row in await pool.fetch(
            """
            SELECT id, ts, agent_id, task_id, trace_id, title, status
            FROM decisions
            ORDER BY ts DESC
            LIMIT 20
            """
        )
    ]
    trace_spans = [
        dict(row)
        for row in await pool.fetch(
            """
            SELECT trace_id, task_id, agent_id, duration_ms, input_tokens,
                   output_tokens, cost_usd, status
            FROM trace_spans
            WHERE ts_start >= NOW() - INTERVAL '24 hours'
            ORDER BY ts_start DESC
            LIMIT 500
            """
        )
    ]

    return build_control_summary(agents, tasks, events, audit_rows, decisions, trace_spans)
