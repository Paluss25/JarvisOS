"""Task CRUD endpoints — Mission Control."""

import logging
import os
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query

from platform.audit import audit, AuditEvent
from platform.auth import get_current_user
from platform.db import get_pool
from platform.models import TaskCreate, TaskPatch, TaskResponse
from platform.task_router import auto_assign

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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
    assigned_to: str | None = Query(None),
    priority: str | None = Query(None),
    _user=Depends(get_current_user),
):
    pool = await get_pool()
    conditions = []
    params: list = []

    if status:
        params.append(status)
        conditions.append(f"status = ${len(params)}")
    if assigned_to:
        params.append(assigned_to)
        conditions.append(f"assigned_to = ${len(params)}")
    if priority:
        params.append(priority)
        conditions.append(f"priority = ${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await pool.fetch(
        f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at ASC",
        *params,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /api/tasks
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_task(req: TaskCreate, _user=Depends(get_current_user)):
    pool = await get_pool()

    # Auto-assign if not specified
    assigned_to = req.assign_to
    assignment_mode = "manual" if assigned_to else "pending"
    if not assigned_to:
        result = await auto_assign(req.title, req.description)
        assigned_to = result.get("agent_id")
        assignment_mode = "auto" if assigned_to else "pending"

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
        req.created_by,
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
    return task


# ---------------------------------------------------------------------------
# GET /api/tasks/{id}
# ---------------------------------------------------------------------------

@router.get("/{task_id}")
async def get_task(task_id: UUID, _user=Depends(get_current_user)):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return dict(row)


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

    if patch.status is not None:
        params.append(patch.status)
        updates.append(f"status = ${len(params)}")
        if patch.status == "done":
            updates.append("completed_at = NOW()")
        elif patch.status == "running":
            updates.append("started_at = NOW()")

    if patch.summary is not None:
        params.append(patch.summary)
        updates.append(f"summary = ${len(params)}")

    if patch.assigned_to is not None:
        params.append(patch.assigned_to)
        updates.append(f"assigned_to = ${len(params)}, assigned_at = NOW()")

    if not updates:
        return dict(row)

    params.append(task_id)
    updated = await pool.fetchrow(
        f"UPDATE tasks SET {', '.join(updates)} WHERE id = ${len(params)} RETURNING *",
        *params,
    )
    task = dict(updated)
    await _publish_event(f"tasks:{task_id}", f"updated:{patch.status or 'patched'}")
    await _publish_event("platform:events", f"task_updated:{task_id}")

    audit_action = (
        "task_completed" if patch.status == "done"
        else "task_failed" if patch.status == "failed"
        else "task_updated"
    )
    await audit.log(AuditEvent(
        category="task",
        action=audit_action,
        source="api",
        user_id=_user.get("sub") if hasattr(_user, "get") else None,
        detail={"task_id": str(task_id), "status": patch.status, "assigned_to": patch.assigned_to},
    ))

    # Retry logic on failure
    if patch.status == "failed":
        await _handle_failure(pool, task)

    return task


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
        # Escalate to Jarvis via A2A channel
        await _publish_event("a2a:jarvis", f"task_failed:{task_id}")
        logger.warning("tasks: task %s exhausted retries — escalated to Jarvis", task_id)

    # Check parent task completion
    parent_id = task.get("parent_id")
    if parent_id:
        await _check_parent_completion(pool, parent_id)


async def _check_parent_completion(pool, parent_id: UUID) -> None:
    children = await pool.fetch(
        "SELECT status FROM tasks WHERE parent_id = $1", parent_id
    )
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
    return dict(updated)
