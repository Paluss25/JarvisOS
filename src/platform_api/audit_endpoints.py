"""Audit log query endpoint — GET /api/audit with category/agent/time filters."""

import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])
_security = HTTPBearer()


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def normalize_audit_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    ts = row.get("ts")
    return {
        "id": row.get("id"),
        "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
        "category": row.get("category"),
        "agent_id": row.get("agent_id"),
        "user_id": str(row.get("user_id")) if row.get("user_id") is not None else None,
        "action": row.get("action"),
        "detail": row.get("detail") or {},
        "source": row.get("source"),
    }


def build_audit_response(rows: list[Mapping[str, Any]], total: int) -> dict[str, Any]:
    return {
        "items": [normalize_audit_entry(row) for row in rows],
        "total": total,
    }


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
    _user=Depends(_get_current_user),
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

    count_row = await pool.fetchrow(
        f"""
        SELECT COUNT(*) AS total
        FROM audit_log
        {where}
        """,
        *params,
    )

    page_params = [*params, limit, offset]
    rows = await pool.fetch(
        f"""
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        {where}
        ORDER BY ts DESC
        LIMIT ${len(page_params) - 1} OFFSET ${len(page_params)}
        """,
        *page_params,
    )

    total = int(count_row["total"]) if count_row else 0
    return build_audit_response([dict(row) for row in rows], total)
