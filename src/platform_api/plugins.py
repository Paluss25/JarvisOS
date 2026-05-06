"""Plugin, capability, worker, and observed tool registry endpoints."""

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent_runner.registry import load_registry
from platform_api.db import get_pool

router = APIRouter(prefix="/api/plugins", tags=["plugins"])
_security = HTTPBearer()


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def collect_capability_registry(agents: list[dict]) -> list[dict]:
    by_name: dict[str, dict[str, set[str]]] = defaultdict(lambda: {
        "agents": set(),
        "domains": set(),
    })
    for agent in agents:
        agent_id = agent.get("id")
        domains = agent.get("domains") or []
        for capability in agent.get("capabilities") or []:
            row = by_name[str(capability)]
            if agent_id:
                row["agents"].add(str(agent_id))
            row["domains"].update(str(domain) for domain in domains)

    return [
        {
            "name": name,
            "kind": "capability",
            "agents": sorted(values["agents"]),
            "domains": sorted(values["domains"]),
        }
        for name, values in sorted(by_name.items())
    ]


def normalize_worker(worker: dict) -> dict:
    return {
        "id": worker.get("id"),
        "kind": "worker",
        "port": worker.get("port"),
        "module": worker.get("module"),
        "description": worker.get("description") or "",
    }


def normalize_observed_tool(event: dict) -> dict:
    payload = event.get("payload") or {}
    is_skill = "skill" in (event.get("event_type") or "") or payload.get("skill")
    name = payload.get("skill") if is_skill else payload.get("tool")
    return {
        "name": name or payload.get("name") or event.get("event_type"),
        "kind": "skill" if is_skill else "tool",
        "agent_id": event.get("agent_id"),
        "event_type": event.get("event_type"),
        "severity": event.get("severity") or "info",
        "status": payload.get("status") or "unknown",
        "duration_ms": payload.get("duration_ms"),
        "payload": payload,
    }


def _is_observed_tool_event(event: dict) -> bool:
    payload = event.get("payload") or {}
    event_type = event.get("event_type") or ""
    return "tool" in event_type or "skill" in event_type or "tool" in payload or "skill" in payload


def build_plugin_summary(agents: list[dict], workers: list[dict], events: list[dict]) -> dict:
    capabilities = collect_capability_registry(agents)
    observed = [event for event in events if _is_observed_tool_event(event)]
    return {
        "agent_count": len(agents),
        "worker_count": len(workers),
        "capability_count": len(capabilities),
        "observed_tool_count": len(observed),
        "tool_event_count": sum(1 for event in observed if "tool" in (event.get("event_type") or "")),
        "skill_event_count": sum(1 for event in observed if "skill" in (event.get("event_type") or "")),
    }


@router.get("/summary")
async def get_plugin_summary(_user=Depends(_get_current_user)):
    registry = load_registry()
    agents = registry.get("agents", [])
    workers = registry.get("workers", [])

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT event_type, severity, agent_id, payload
        FROM platform_events
        WHERE event_type LIKE '%tool%'
           OR event_type LIKE '%skill%'
           OR payload ? 'tool'
           OR payload ? 'skill'
        ORDER BY ts DESC
        LIMIT 100
        """
    )
    events = [dict(row) for row in rows]
    return {
        "summary": build_plugin_summary(agents, workers, events),
        "capabilities": collect_capability_registry(agents),
        "workers": [normalize_worker(worker) for worker in workers],
        "observed_tools": [
            normalize_observed_tool(event)
            for event in events
            if _is_observed_tool_event(event)
        ],
    }
