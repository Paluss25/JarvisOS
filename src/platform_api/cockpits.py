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
CIO_OPERATION_KEYWORDS = {
    "backup",
    "deploy",
    "health",
    "homelab",
    "incident",
    "release",
    "skill",
    "tool",
}
CISO_SECURITY_KEYWORDS = {
    "alert",
    "auth",
    "compliance",
    "incident",
    "policy",
    "scan",
    "security",
    "threat",
    "vulnerability",
}
CISO_FINDING_KEYWORDS = {"alert", "auth", "policy", "threat", "vulnerability"}


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


def is_cio_operational_event(event: dict) -> bool:
    if event.get("agent_id") != "cio":
        return False

    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    kind = payload.get("kind")
    return any(keyword in event_type for keyword in CIO_OPERATION_KEYWORDS) or kind in CIO_OPERATION_KEYWORDS


def _event_matches(event: dict, *keywords: str) -> bool:
    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    kind = payload.get("kind")
    return any(keyword in event_type for keyword in keywords) or kind in keywords


def _is_failed_event(event: dict) -> bool:
    payload = event.get("payload") or {}
    return (
        event.get("severity") in {"critical", "error"}
        or "failed" in (event.get("event_type") or "")
        or payload.get("status") == "failed"
    )


def build_cio_summary(events: list[dict]) -> dict:
    operational_events = [event for event in events if is_cio_operational_event(event)]
    return {
        "event_count": len(operational_events),
        "tool_events": sum(1 for event in operational_events if _event_matches(event, "tool")),
        "skill_events": sum(1 for event in operational_events if _event_matches(event, "skill")),
        "deploy_events": sum(1 for event in operational_events if _event_matches(event, "deploy", "release")),
        "backup_events": sum(1 for event in operational_events if _event_matches(event, "backup")),
        "health_events": sum(1 for event in operational_events if _event_matches(event, "health")),
        "incident_events": sum(1 for event in operational_events if _event_matches(event, "incident")),
        "failed_events": sum(1 for event in operational_events if _is_failed_event(event)),
    }


def is_ciso_security_event(event: dict) -> bool:
    if event.get("agent_id") != "ciso":
        return False

    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    kind = payload.get("kind")
    category = payload.get("category")
    return (
        any(keyword in event_type for keyword in CISO_SECURITY_KEYWORDS)
        or kind in CISO_SECURITY_KEYWORDS
        or category in CISO_SECURITY_KEYWORDS
    )


def _is_open_ciso_finding(event: dict) -> bool:
    payload = event.get("payload") or {}
    status = payload.get("status")
    if status in {"closed", "resolved", "accepted"}:
        return False
    return _event_matches(event, *CISO_FINDING_KEYWORDS) or payload.get("category") in CISO_FINDING_KEYWORDS


def build_ciso_summary(events: list[dict]) -> dict:
    security_events = [event for event in events if is_ciso_security_event(event)]
    return {
        "event_count": len(security_events),
        "alert_events": sum(1 for event in security_events if _event_matches(event, "alert")),
        "incident_events": sum(1 for event in security_events if _event_matches(event, "incident")),
        "vulnerability_events": sum(1 for event in security_events if _event_matches(event, "vulnerability")),
        "auth_events": sum(1 for event in security_events if _event_matches(event, "auth")),
        "policy_events": sum(1 for event in security_events if _event_matches(event, "policy", "compliance")),
        "scan_events": sum(1 for event in security_events if _event_matches(event, "scan")),
        "critical_events": sum(1 for event in security_events if event.get("severity") == "critical"),
        "open_findings": sum(1 for event in security_events if _is_open_ciso_finding(event)),
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


@router.get("/cio")
async def get_cio_cockpit(_user=Depends(_get_current_user)):
    pool = await get_pool()
    event_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE agent_id = $1
        ORDER BY ts DESC
        LIMIT 100
        """,
        "cio",
    )

    raw_events = [dict(row) for row in event_rows]
    operational_events = [event for event in raw_events if is_cio_operational_event(event)]
    return {
        "summary": build_cio_summary(raw_events),
        "events": [normalize_log_event(event) for event in operational_events],
        "incidents": [normalize_log_event(event) for event in operational_events if _is_failed_event(event)],
        "tool_events": [
            normalize_log_event(event)
            for event in operational_events
            if _event_matches(event, "tool", "skill")
        ],
    }


@router.get("/ciso")
async def get_ciso_cockpit(_user=Depends(_get_current_user)):
    pool = await get_pool()
    event_rows = await pool.fetch(
        """
        SELECT id, ts, event_type, severity, agent_id, task_id, session_id,
               trace_id, span_id, source, payload
        FROM platform_events
        WHERE agent_id = $1
        ORDER BY ts DESC
        LIMIT 100
        """,
        "ciso",
    )

    raw_events = [dict(row) for row in event_rows]
    security_events = [event for event in raw_events if is_ciso_security_event(event)]
    return {
        "summary": build_ciso_summary(raw_events),
        "events": [normalize_log_event(event) for event in security_events],
        "alerts": [
            normalize_log_event(event)
            for event in security_events
            if _event_matches(event, "alert", "threat") or event.get("severity") == "critical"
        ],
        "findings": [
            normalize_log_event(event)
            for event in security_events
            if _is_open_ciso_finding(event)
        ],
    }
