"""Audit log query endpoint — GET /api/audit with category/agent/time filters."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from platform.auth import get_current_user
from platform.db import get_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def query_audit(
    category: str | None = Query(None, description="agent | platform | security | memory | task"),
    agent_id: str | None = Query(None),
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    source: str | None = Query(None),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _user=Depends(get_current_user),
):
    """Return paginated audit log entries, newest first.

    All filters are optional and AND-combined.  ``from`` and ``to`` accept ISO
    8601 timestamps (e.g. ``2026-04-17`` or ``2026-04-17T09:00:00Z``).
    """
    pool = await get_pool()

    conditions: list[str] = []
    params: list = []

    def _add(condition: str, value) -> None:
        params.append(value)
        conditions.append(condition.replace("?", f"${len(params)}"))

    if category:
        _add("category = ?", category)
    if agent_id:
        _add("agent_id = ?", agent_id)
    if user_id:
        _add("user_id = ?", user_id)
    if action:
        _add("action = ?", action)
    if source:
        _add("source = ?", source)
    if from_:
        # Make timezone-aware if naive
        if from_.tzinfo is None:
            from_ = from_.replace(tzinfo=timezone.utc)
        _add("ts >= ?", from_)
    if to:
        if to.tzinfo is None:
            to = to.replace(tzinfo=timezone.utc)
        _add("ts <= ?", to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    params.extend([limit, offset])
    rows = await pool.fetch(
        f"""
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        {where}
        ORDER BY ts DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )

    return [
        {
            "id": r["id"],
            "ts": r["ts"].isoformat(),
            "category": r["category"],
            "agent_id": r["agent_id"],
            "user_id": r["user_id"],
            "action": r["action"],
            "detail": r["detail"],
            "source": r["source"],
        }
        for r in rows
    ]
