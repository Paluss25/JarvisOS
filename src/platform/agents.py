"""Agent management endpoints — CRUD + restart + chat proxy."""

import logging
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Depends

from agent_runner.registry import list_agents, load_registry, _REGISTRY_PATH
from platform.audit import audit, AuditEvent
from platform.auth import get_current_user
from platform.models import AgentCreateRequest, AgentStatus
from platform.supervisord_rpc import SupervisorClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])

_supervisor = SupervisorClient()
_AGENTS_YAML = _REGISTRY_PATH


def _write_registry(data: dict) -> None:
    """Persist modified agents.yaml."""
    with open(_AGENTS_YAML, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def _get_process_state(agent_id: str) -> str | None:
    try:
        info = _supervisor.get_process_info(agent_id)
        return info.get("statename")
    except Exception:
        return None


async def _check_agent_health(port: int) -> str:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://localhost:{port}/health")
            return "ok" if resp.status_code == 200 else "error"
    except Exception:
        return "unreachable"


# ---------------------------------------------------------------------------
# GET /api/agents
# ---------------------------------------------------------------------------

@router.get("")
async def list_all_agents(_user=Depends(get_current_user)):
    agents = list_agents()
    result = []
    for a in agents:
        state = _get_process_state(a["id"])
        result.append(AgentStatus(
            id=a["id"],
            port=a["port"],
            workspace=a.get("workspace", ""),
            domains=a.get("domains", []),
            capabilities=a.get("capabilities", []),
            supervisord_state=state,
        ))
    return result


# ---------------------------------------------------------------------------
# GET /api/agents/{id}
# ---------------------------------------------------------------------------

@router.get("/{agent_id}")
async def get_agent(agent_id: str, _user=Depends(get_current_user)):
    agents = list_agents()
    entry = next((a for a in agents if a["id"] == agent_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    state = _get_process_state(agent_id)
    health = await _check_agent_health(entry["port"])
    return AgentStatus(
        id=entry["id"],
        port=entry["port"],
        workspace=entry.get("workspace", ""),
        domains=entry.get("domains", []),
        capabilities=entry.get("capabilities", []),
        supervisord_state=state,
        health=health,
    )


# ---------------------------------------------------------------------------
# POST /api/agents
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_agent(req: AgentCreateRequest, _user=Depends(get_current_user)):
    data = load_registry()
    if any(a["id"] == req.id for a in data.get("agents", [])):
        raise HTTPException(status_code=409, detail=f"Agent '{req.id}' already exists")

    entry = {
        "id": req.id,
        "port": req.port,
        "workspace": req.workspace,
        "telegram_token_env": req.telegram_token_env,
        "telegram_chat_id_env": req.telegram_chat_id_env,
        "domains": req.domains,
        "capabilities": req.capabilities,
        "memory": {"backend": "filesystem"},
    }
    data.setdefault("agents", []).append(entry)
    _write_registry(data)

    # Create workspace directory
    ws = Path(f"/app/{req.workspace}")
    ws.mkdir(parents=True, exist_ok=True)

    # Regenerate supervisord config and reload
    try:
        _supervisor.reread()
        _supervisor.update()
        _supervisor.start_process(req.id)
    except Exception as exc:
        logger.warning("create_agent: supervisord update failed — %s", exc)

    await audit.log(AuditEvent(
        category="platform",
        action="agent_created",
        source="api",
        agent_id=req.id,
        user_id=_user.get("sub"),
        detail={"port": req.port, "workspace": req.workspace, "domains": req.domains},
    ))
    return entry


# ---------------------------------------------------------------------------
# DELETE /api/agents/{id}
# ---------------------------------------------------------------------------

@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, _user=Depends(get_current_user)):
    data = load_registry()
    agents = data.get("agents", [])
    if not any(a["id"] == agent_id for a in agents):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    try:
        _supervisor.stop_process(agent_id)
    except Exception as exc:
        logger.warning("delete_agent: stop failed — %s", exc)

    data["agents"] = [a for a in agents if a["id"] != agent_id]
    _write_registry(data)

    await audit.log(AuditEvent(
        category="platform",
        action="agent_deleted",
        source="api",
        agent_id=agent_id,
        user_id=_user.get("sub"),
    ))


# ---------------------------------------------------------------------------
# POST /api/agents/{id}/restart
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/restart")
async def restart_agent(agent_id: str, _user=Depends(get_current_user)):
    agents = list_agents()
    if not any(a["id"] == agent_id for a in agents):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    try:
        _supervisor.restart_process(agent_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    await audit.log(AuditEvent(
        category="platform",
        action="agent_restarted",
        source="api",
        agent_id=agent_id,
        user_id=_user.get("sub"),
    ))
    return {"status": "restarted", "agent_id": agent_id}


# ---------------------------------------------------------------------------
# POST /api/agents/{id}/chat
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/chat")
async def chat_proxy(agent_id: str, body: dict, _user=Depends(get_current_user)):
    agents = list_agents()
    entry = next((a for a in agents if a["id"] == agent_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"http://localhost:{entry['port']}/chat",
                json=body,
            )
            return resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {exc}")
