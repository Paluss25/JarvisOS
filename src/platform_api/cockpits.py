"""Agent cockpit endpoints derived from JarvisOS observability tables."""

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool
from platform_api.decisions import normalize_decision
from platform_api.logs import normalize_log_event

router = APIRouter(prefix="/api/cockpits", tags=["cockpits"])
_security = HTTPBearer()

OPEN_DECISION_STATUSES = {"proposed", "needs_review", "pending_approval"}


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def is_cfo_alert_event(event: dict) -> bool:
    if event.get("agent_id") != "cfo":
        return False

    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    return (
        "alert" in event_type
        or event_type.endswith("_alert")
        or payload.get("kind") == "alert"
    )


def _is_market_alert(event: dict) -> bool:
    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    category = payload.get("category")
    return category == "market" or "market" in event_type or "finance" in event_type


def _is_tax_alert(event: dict) -> bool:
    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    return payload.get("category") == "tax" or "tax" in event_type


def build_cfo_summary(decisions: list[dict], events: list[dict]) -> dict:
    alerts = [event for event in events if is_cfo_alert_event(event)]
    return {
        "decision_count": len(decisions),
        "open_approvals": sum(1 for item in decisions if item.get("status") in OPEN_DECISION_STATUSES),
        "approved_decisions": sum(1 for item in decisions if item.get("status") == "approved"),
        "rejected_decisions": sum(1 for item in decisions if item.get("status") == "rejected"),
        "market_alerts": sum(1 for event in alerts if _is_market_alert(event)),
        "tax_alerts": sum(1 for event in alerts if _is_tax_alert(event)),
        "critical_alerts": sum(1 for event in alerts if event.get("severity") == "critical"),
    }


@router.get("/cfo")
async def get_cfo_cockpit(_user=Depends(_get_current_user)):
    pool = await get_pool()
    decision_rows = await pool.fetch(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE agent_id = $1
        ORDER BY ts DESC
        LIMIT 50
        """,
        "cfo",
    )
    event_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE agent_id = $1
        ORDER BY ts DESC
        LIMIT 100
        """,
        "cfo",
    )

    decisions = [normalize_decision(dict(row)) for row in decision_rows]
    events = [dict(row) for row in event_rows]
    alerts = [normalize_log_event(event) for event in events if is_cfo_alert_event(event)]
    return {
        "summary": build_cfo_summary(decisions, events),
        "decisions": decisions,
        "alerts": alerts,
    }
