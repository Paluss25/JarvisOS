"""Plugin, capability, worker, and observed tool registry endpoints."""

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
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


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


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
    display_name = name or payload.get("name") or event.get("event_type")
    kind = "skill" if is_skill else "tool"
    return {
        "id": _serialize(event.get("id")),
        "ts": _serialize(event.get("ts")),
        "name": display_name,
        "kind": kind,
        "agent_id": event.get("agent_id"),
        "task_id": _serialize(event.get("task_id")),
        "trace_id": event.get("trace_id"),
        "event_type": event.get("event_type"),
        "severity": event.get("severity") or "info",
        "source": event.get("source") or "platform",
        "status": payload.get("status") or "unknown",
        "duration_ms": payload.get("duration_ms"),
        "payload": payload,
        "links": {
            "detail": f"/plugins/tools/{kind}/{display_name}",
        },
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


def _tool_name(event: dict) -> str:
    return str(normalize_observed_tool(event).get("name") or "")


def _tool_kind(event: dict) -> str:
    return str(normalize_observed_tool(event).get("kind") or "tool")


def _is_failure(event: dict) -> bool:
    normalized = normalize_observed_tool(event)
    return (
        normalized.get("severity") in {"critical", "error"}
        or normalized.get("status") in {"failed", "error"}
    )


def _agent_matches_tool(agent: dict, tool_name: str, tool_events: list[dict]) -> bool:
    agent_id = agent.get("id")
    if any(event.get("agent_id") == agent_id for event in tool_events):
        return True
    capabilities = [str(item) for item in agent.get("capabilities") or []]
    return tool_name in capabilities


def build_tool_context(
    *,
    name: str,
    kind: str,
    agents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    tool_events = [
        event for event in events
        if _is_observed_tool_event(event)
        and _tool_name(event) == name
        and _tool_kind(event) == kind
    ]
    normalized_events = [normalize_observed_tool(event) for event in tool_events]
    matched_agents = [
        {
            "id": str(agent.get("id")),
            "domains": [str(item) for item in agent.get("domains") or []],
            "capabilities": [str(item) for item in agent.get("capabilities") or []],
        }
        for agent in agents
        if agent.get("id") and _agent_matches_tool(agent, name, tool_events)
    ]
    durations = [
        event.get("duration_ms")
        for event in normalized_events
        if isinstance(event.get("duration_ms"), (int, float))
    ]
    failure_count = sum(1 for event in tool_events if _is_failure(event))
    diagnostics = []
    if failure_count:
        diagnostics.append({"kind": "failure", "label": "Recent failures", "count": failure_count, "tone": "incident"})
    if not matched_agents:
        diagnostics.append({"kind": "coverage", "label": "No registered agent owner", "count": 1, "tone": "warning"})

    first_event = normalized_events[0] if normalized_events else {}
    first_agent = first_event.get("agent_id")
    first_trace = first_event.get("trace_id")
    first_task = first_event.get("task_id")
    return {
        "tool": {
            "name": name,
            "kind": kind,
            "read_only": True,
        },
        "metrics": {
            "agent_count": len(matched_agents),
            "event_count": len(normalized_events),
            "failure_count": failure_count,
            "trace_count": len(traces),
            "audit_count": len(audit_entries),
            "decision_count": len(decisions),
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
        },
        "links": {
            "logs": f"/logs?event_type={normalized_events[0]['event_type']}" if normalized_events else "/logs",
            "audit": f"/audit?action=&source=&agent_id={first_agent}" if first_agent else "/audit",
            "first_trace": f"/traces/{first_trace}" if first_trace else None,
            "first_task": f"/tasks/{first_task}" if first_task else None,
        },
        "agents": matched_agents,
        "diagnostics": diagnostics,
        "events": normalized_events,
        "traces": traces,
        "audit_entries": audit_entries,
        "decisions": decisions,
    }


def _tool_event_where(kind: str) -> str:
    if kind == "skill":
        return "(event_type LIKE '%skill%' OR payload ? 'skill')"
    return "(event_type LIKE '%tool%' OR payload ? 'tool')"


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


@router.get("/tools/{tool_name}")
async def get_tool_context(
    tool_name: str,
    kind: str = Query("tool", pattern="^(tool|skill)$"),
    _user=Depends(_get_current_user),
):
    from platform_api.audit_endpoints import normalize_audit_entry
    from platform_api.decisions import normalize_decision
    from platform_api.traces import build_trace_summaries

    registry = load_registry()
    agents = registry.get("agents", [])
    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        SELECT id, ts, event_type, severity, agent_id, task_id, trace_id, source, payload
        FROM platform_events
        WHERE {_tool_event_where(kind)}
          AND (payload->>$1 = $2 OR payload->>'name' = $2 OR event_type = $2)
        ORDER BY ts DESC
        LIMIT 100
        """,
        kind,
        tool_name,
    )
    events = [dict(row) for row in rows]
    if not events and not any(tool_name in (agent.get("capabilities") or []) for agent in agents):
        raise HTTPException(status_code=404, detail="Tool not found")

    trace_ids = [event.get("trace_id") for event in events if event.get("trace_id")]
    task_ids = [str(event.get("task_id")) for event in events if event.get("task_id")]
    agent_ids = sorted({str(event.get("agent_id")) for event in events if event.get("agent_id")})

    trace_rows = []
    if trace_ids:
        trace_rows = await pool.fetch(
            """
            SELECT trace_id, span_id, parent_span_id, ts_start, ts_end, operation,
                   agent_id, task_id, session_id, status, duration_ms, input_tokens,
                   output_tokens, cost_usd, model, provider, payload
            FROM trace_spans
            WHERE trace_id = ANY($1::text[])
            ORDER BY ts_start DESC
            LIMIT 200
            """,
            trace_ids,
        )
    audit_rows = await pool.fetch(
        """
        SELECT id, ts, category, agent_id, user_id, action, detail, source
        FROM audit_log
        WHERE detail->>'tool' = $1
           OR detail->>'skill' = $1
           OR detail->>'task_id' = ANY($2::text[])
           OR agent_id = ANY($3::text[])
        ORDER BY ts DESC
        LIMIT 100
        """,
        tool_name,
        task_ids,
        agent_ids,
    )
    decision_rows = await pool.fetch(
        """
        SELECT id, ts, agent_id, task_id, trace_id, title, summary,
               decision_type, confidence, status, evidence, payload
        FROM decisions
        WHERE trace_id = ANY($1::text[])
           OR agent_id = ANY($2::text[])
        ORDER BY ts DESC
        LIMIT 100
        """,
        trace_ids,
        agent_ids,
    )

    return build_tool_context(
        name=tool_name,
        kind=kind,
        agents=agents,
        events=events,
        traces=build_trace_summaries([dict(row) for row in trace_rows]),
        audit_entries=[normalize_audit_entry(dict(row)) for row in audit_rows],
        decisions=[normalize_decision(dict(row)) for row in decision_rows],
    )
