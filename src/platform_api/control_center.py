"""Control Center summary endpoints for JarvisOS operations dashboard."""

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

    return {
        "agents": {
            "total": len(agents),
            "running": running,
            "not_running": max(len(agents) - running, 0),
        },
        "tasks": {
            "open": open_tasks,
            "total": len(tasks),
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
            "today_usd": 0,
            "tokens_today": 0,
        },
        "recent_audit": audit_rows[:10],
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

    return build_control_summary(agents, tasks, events, audit_rows)
