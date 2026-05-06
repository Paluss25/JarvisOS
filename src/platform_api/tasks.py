"""Task CRUD endpoints — Mission Control."""

import logging
import os
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.audit import audit, AuditEvent
from platform_api.db import get_pool
from platform_api.links import build_chat_link
from platform_api.models import TaskCreate, TaskPatch, TaskResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])
_security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def _serialize(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _serialize_uuid_list(values) -> list[str]:
    if not values:
        return []
    return [str(value) for value in values]


def normalize_task(row: dict) -> dict:
    status = row.get("status") or "pending"
    assigned_to = row.get("assigned_to")
    updated_at = (
        row.get("completed_at")
        or row.get("started_at")
        or row.get("assigned_at")
        or row.get("created_at")
    )
    return {
        "id": _serialize(row.get("id")),
        "parent_id": _serialize(row.get("parent_id")),
        "title": row.get("title"),
        "description": row.get("description") or "",
        "created_by": row.get("created_by"),
        "assigned_to": assigned_to,
        "assigned_agent": assigned_to,
        "assignment_mode": row.get("assignment_mode") or "pending",
        "status": status,
        "state": status,
        "priority": row.get("priority") or "normal",
        "depends_on": _serialize_uuid_list(row.get("depends_on")),
        "retry_count": row.get("retry_count") or 0,
        "max_retries": row.get("max_retries") or 3,
        "summary": row.get("summary"),
        "created_at": _serialize(row.get("created_at")),
        "assigned_at": _serialize(row.get("assigned_at")),
        "started_at": _serialize(row.get("started_at")),
        "completed_at": _serialize(row.get("completed_at")),
        "updated_at": _serialize(updated_at),
        "duration_ms": row.get("duration_ms"),
    }


def _artifact_from_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    payload = event.get("payload") or {}
    event_id = event.get("id")
    artifacts: list[dict[str, Any]] = []

    artifact_path = payload.get("artifact_path") or payload.get("artifact_url")
    if artifact_path:
        artifacts.append({
            "event_id": str(event_id) if event_id is not None else None,
            "name": payload.get("artifact_name") or payload.get("name") or str(artifact_path).split("/")[-1],
            "path": artifact_path,
            "kind": "artifact",
        })

    output = payload.get("output") or payload.get("result")
    if output:
        preview = str(output)
        artifacts.append({
            "event_id": str(event_id) if event_id is not None else None,
            "name": "output",
            "path": None,
            "kind": "output",
            "preview": preview[:240],
        })

    return artifacts


def build_task_context(
    *,
    task: dict[str, Any],
    traces: list[dict[str, Any]],
    logs: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    task_id = task["id"]
    agent_id = task.get("assigned_agent") or task.get("assigned_to")
    artifacts = [
        artifact
        for event in logs
        for artifact in _artifact_from_event(event)
    ]
    return {
        "task": task,
        "metrics": {
            "trace_count": len(traces),
            "log_count": len(logs),
            "audit_count": len(audit_entries),
            "decision_count": len(decisions),
            "artifact_count": len(artifacts),
        },
        "links": {
            "agent": f"/agents/{agent_id}" if agent_id else None,
            "chat": build_chat_link(agent_id, task_id=task_id),
            "cockpit": f"/agents/{agent_id}/cockpit" if agent_id else None,
            "traces": f"/traces?task_id={task_id}",
            "logs": f"/logs?task_id={task_id}",
            "audit": f"/audit?action=&source=&task_id={task_id}",
        },
        "traces": traces,
        "logs": logs,
        "audit_entries": audit_entries,
        "decisions": decisions,
        "artifacts": artifacts,
    }


async def _publish_event(channel: str, data: str) -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    try:
        r = aioredis.from_url(redis_url)
        await r.publish(channel, data)
        await r.aclose()
    except Exception as exc:
        logger.warning("tasks: Redis publish failed — %s", exc)


# ---------------------------------------------------------------------------
# GET /api/tasks
# ---------------------------------------------------------------------------

@router.get("")
async def list_tasks(
    status: str | None = Query(None),
    state: str | None = Query(None),
    assigned_to: str | None = Query(None),
    agent_id: str | None = Query(None),
    priority: str | None = Query(None),
    _user=Depends(get_current_user),
):
    pool = await get_pool()
    conditions = []
    params: list = []

    status_filter = status or state
    agent_filter = assigned_to or agent_id

    if status_filter:
        params.append(status_filter)
        conditions.append(f"status = ${len(params)}")
    if agent_filter:
        params.append(agent_filter)
        conditions.append(f"assigned_to = ${len(params)}")
    if priority:
        params.append(priority)
        conditions.append(f"priority = ${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await pool.fetch(
        f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at ASC",
        *params,
    )
    return [normalize_task(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# POST /api/tasks
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_task(req: TaskCreate, _user=Depends(get_current_user)):
    pool = await get_pool()

    # Auto-assign if not specified
    assigned_to = req.assign_to or req.assigned_agent
    assignment_mode = "manual" if assigned_to else "pending"
    if not assigned_to:
        from platform_api.task_router import auto_assign

        result = await auto_assign(req.title, req.description)
        assigned_to = result.get("agent_id")
        assignment_mode = "auto" if assigned_to else "pending"

    # Derive actor from validated JWT — never trust req.created_by
    actor = _user.get("sub") if hasattr(_user, "get") else str(_user)

    row = await pool.fetchrow(
        """
        INSERT INTO tasks
            (title, description, created_by, assigned_to, assignment_mode,
             priority, depends_on)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING *
        """,
        req.title,
        req.description,
        actor,
        assigned_to,
        assignment_mode,
        req.priority,
        [str(d) for d in req.depends_on],
    )
    task = dict(row)
    await _publish_event("platform:events", f"task_created:{task['id']}")
    await audit.log(AuditEvent(
        category="task",
        action="task_created",
        source="api",
        user_id=_user.get("sub") if hasattr(_user, "get") else None,
        detail={
            "task_id": str(task["id"]),
            "title": task["title"],
            "assigned_to": assigned_to,
            "assignment_mode": assignment_mode,
            "priority": req.priority,
        },
    ))
    return normalize_task(task)


# ---------------------------------------------------------------------------
# GET /api/tasks/{id}
# ---------------------------------------------------------------------------

@router.get("/{task_id}")
async def get_task(task_id: UUID, _user=Depends(get_current_user)):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return normalize_task(dict(row))


@router.get("/{task_id}/context")
async def get_task_context(task_id: UUID, _user=Depends(get_current_user)):
    from platform_api.audit_endpoints import normalize_audit_entry
    from platform_api.decisions import normalize_decision
    from platform_api.logs import normalize_log_event
    from platform_api.traces import build_trace_summaries

    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

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
        task_id,
    )
    event_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE task_id = $1
        ORDER BY ts DESC
        LIMIT 100
        """,
        task_id,
    )
    audit_rows = await pool.fetch(
        """
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        WHERE detail->>'task_id' = $1
        ORDER BY ts DESC
        LIMIT 100
        """,
        str(task_id),
    )
    decision_rows = await pool.fetch(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE task_id = $1
        ORDER BY ts DESC
        LIMIT 100
        """,
        task_id,
    )

    logs = [normalize_log_event(dict(row)) for row in event_rows]
    return build_task_context(
        task=normalize_task(dict(row)),
        traces=build_trace_summaries([dict(row) for row in trace_rows]),
        logs=logs,
        audit_entries=[normalize_audit_entry(dict(row)) for row in audit_rows],
        decisions=[normalize_decision(dict(row)) for row in decision_rows],
    )


# ---------------------------------------------------------------------------
# PATCH /api/tasks/{id}
# ---------------------------------------------------------------------------

@router.patch("/{task_id}")
async def update_task(task_id: UUID, patch: TaskPatch, _user=Depends(get_current_user)):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    updates: list[str] = []
    params: list = []

    status_patch = patch.status or patch.state
    if status_patch is not None:
        params.append(status_patch)
        updates.append(f"status = ${len(params)}")
        if status_patch == "done":
            updates.append("completed_at = NOW()")
        elif status_patch == "running":
            updates.append("started_at = NOW()")

    if patch.summary is not None:
        params.append(patch.summary)
        updates.append(f"summary = ${len(params)}")

    if patch.assigned_to is not None:
        params.append(patch.assigned_to)
        updates.append(f"assigned_to = ${len(params)}, assigned_at = NOW()")

    if not updates:
        return normalize_task(dict(row))

    params.append(task_id)
    updated = await pool.fetchrow(
        f"UPDATE tasks SET {', '.join(updates)} WHERE id = ${len(params)} RETURNING *",
        *params,
    )
    task = dict(updated)
    await _publish_event(f"tasks:{task_id}", f"updated:{status_patch or 'patched'}")
    await _publish_event("platform:events", f"task_updated:{task_id}")

    audit_action = (
        "task_completed" if status_patch == "done"
        else "task_failed" if status_patch == "failed"
        else "task_updated"
    )
    await audit.log(AuditEvent(
        category="task",
        action=audit_action,
        source="api",
        user_id=_user.get("sub") if hasattr(_user, "get") else None,
        detail={"task_id": str(task_id), "status": status_patch, "assigned_to": patch.assigned_to},
    ))

    # Retry logic on failure
    if status_patch == "failed":
        await _handle_failure(pool, task)

    return normalize_task(task)


async def _handle_failure(pool, task: dict) -> None:
    retry_count = task["retry_count"] + 1
    max_retries = task["max_retries"]
    task_id = task["id"]

    if retry_count < max_retries:
        await pool.execute(
            "UPDATE tasks SET status='pending', retry_count=$1 WHERE id=$2",
            retry_count,
            task_id,
        )
        await _publish_event(f"tasks:{task_id}", "retry_scheduled")
        logger.info("tasks: task %s retry %d/%d scheduled", task_id, retry_count, max_retries)
    else:
        await pool.execute(
            "UPDATE tasks SET status='failed', retry_count=$1 WHERE id=$2",
            retry_count,
            task_id,
        )
        # Escalate to CEO via A2A channel
        await _publish_event("a2a:ceo", f"task_failed:{task_id}")
        logger.warning("tasks: task %s exhausted retries — escalated to CEO", task_id)

    # Check parent task completion
    parent_id = task.get("parent_id")
    if parent_id:
        await _check_parent_completion(pool, parent_id)


async def _check_parent_completion(pool, parent_id: UUID) -> None:
    children = await pool.fetch(
        "SELECT status FROM tasks WHERE parent_id = $1", parent_id
    )
    if not children:
        return  # no children — parent not auto-completed
    statuses = {r["status"] for r in children}

    if all(s == "done" for s in statuses):
        await pool.execute("UPDATE tasks SET status='done', completed_at=NOW() WHERE id=$1", parent_id)
        await _publish_event("platform:events", f"task_parent_done:{parent_id}")
    elif "failed" in statuses and not any(s == "pending" for s in statuses):
        await pool.execute("UPDATE tasks SET status='partially_failed' WHERE id=$1", parent_id)
        await _publish_event("platform:events", f"task_parent_partial:{parent_id}")


# ---------------------------------------------------------------------------
# POST /api/tasks/{id}/assign
# ---------------------------------------------------------------------------

@router.post("/{task_id}/assign")
async def assign_task(task_id: UUID, body: dict, _user=Depends(get_current_user)):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    agent_id = body.get("agent_id")
    if not agent_id:
        # Auto-assign
        from platform_api.task_router import auto_assign

        result = await auto_assign(row["title"], row["description"] or "")
        agent_id = result.get("agent_id")
        if not agent_id:
            raise HTTPException(status_code=422, detail="Auto-assign found no suitable agent")

    updated = await pool.fetchrow(
        "UPDATE tasks SET assigned_to=$1, assigned_at=NOW(), assignment_mode='manual' WHERE id=$2 RETURNING *",
        agent_id,
        task_id,
    )
    await _publish_event(f"tasks:{task_id}", f"assigned:{agent_id}")
    await audit.log(AuditEvent(
        category="task",
        action="task_assigned",
        source="api",
        user_id=_user.get("sub") if hasattr(_user, "get") else None,
        detail={"task_id": str(task_id), "agent_id": agent_id},
    ))
    return normalize_task(dict(updated))
