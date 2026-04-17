"""Domain management endpoints — shared memory domains with ACL."""

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException

from agent_runner.registry import load_registry, list_agents, _REGISTRY_PATH
from platform.auth import get_current_user, require_admin
from platform.models import DomainCreate, DomainGrant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/domains", tags=["domains"])

_SHARED_ROOT = Path("/app/shared")


def _write_registry(data: dict) -> None:
    with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def _publish_config_changed() -> None:
    """Non-blocking Redis publish — swallowed on failure."""
    import asyncio
    import os
    import redis.asyncio as aioredis

    async def _pub():
        try:
            r = aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
            await r.publish("platform:config_changed", "domains_updated")
            await r.aclose()
        except Exception:
            pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_pub())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GET /api/domains
# ---------------------------------------------------------------------------

@router.get("")
async def list_domains(_user=Depends(get_current_user)):
    _SHARED_ROOT.mkdir(parents=True, exist_ok=True)
    return [d.name for d in _SHARED_ROOT.iterdir() if d.is_dir()]


# ---------------------------------------------------------------------------
# POST /api/domains
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_domain(req: DomainCreate, _user=Depends(require_admin)):
    domain_path = _SHARED_ROOT / req.name
    if domain_path.exists():
        raise HTTPException(status_code=409, detail=f"Domain '{req.name}' already exists")
    domain_path.mkdir(parents=True)
    return {"name": req.name, "path": str(domain_path)}


# ---------------------------------------------------------------------------
# DELETE /api/domains/{name}
# ---------------------------------------------------------------------------

@router.delete("/{name}", status_code=204)
async def delete_domain(name: str, _user=Depends(require_admin)):
    domain_path = _SHARED_ROOT / name
    if not domain_path.exists():
        raise HTTPException(status_code=404, detail=f"Domain '{name}' not found")
    import shutil
    shutil.rmtree(domain_path)


# ---------------------------------------------------------------------------
# PATCH /api/domains/{name}/grant
# ---------------------------------------------------------------------------

@router.patch("/{name}/grant")
async def grant_domain_access(name: str, req: DomainGrant, _user=Depends(require_admin)):
    data = load_registry()
    agents = data.get("agents", [])
    entry = next((a for a in agents if a["id"] == req.agent_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_id}' not found")

    domains = entry.get("domains", [])
    if name not in domains and "*" not in domains:
        domains.append(name)
        entry["domains"] = domains
        _write_registry(data)
        _publish_config_changed()

    return {"agent_id": req.agent_id, "domain": name, "mode": req.mode}
