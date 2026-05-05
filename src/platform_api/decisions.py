"""Decision ledger endpoints for JarvisOS agent audit trails."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool

router = APIRouter(prefix="/api/decisions", tags=["decisions"])
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


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def normalize_decision(row: dict) -> dict:
    return {
        "id": _serialize(row.get("id")),
        "ts": _serialize(row.get("ts")),
        "agent_id": row.get("agent_id"),
        "task_id": _serialize(row.get("task_id")),
        "trace_id": row.get("trace_id"),
        "title": row.get("title"),
        "summary": row.get("summary"),
        "decision_type": row.get("decision_type") or "operational",
        "confidence": _number(row.get("confidence")),
        "status": row.get("status") or "proposed",
        "evidence": row.get("evidence") or [],
        "payload": row.get("payload") or {},
    }


@router.get("")
async def list_decisions(
    agent_id: str | None = Query(None),
    task_id: str | None = Query(None),
    trace_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user=Depends(_get_current_user),
):
    pool = await get_pool()
    conditions: list[str] = []
    params: list[Any] = []

    def add_filter(column: str, value: str | None) -> None:
        if value is None:
            return
        params.append(value)
        conditions.append(f"{column} = ${len(params)}")

    add_filter("agent_id", agent_id)
    add_filter("task_id", task_id)
    add_filter("trace_id", trace_id)
    add_filter("status", status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        {where}
        ORDER BY ts DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [normalize_decision(dict(row)) for row in rows]
