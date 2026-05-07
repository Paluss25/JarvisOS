"""Governance and operator settings summary endpoints."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agent_runner.registry import load_registry
from platform_api.db import get_pool
from security.config_loader import (
    load_approval_policy,
    load_memory_policy,
    load_model_routing_rules,
    load_permissions,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])
_security = HTTPBearer()
_SHARED_ROOT = Path("/app/shared")


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def normalize_approval_classes(policy: dict[str, Any]) -> list[dict[str, Any]]:
    risk_by_name = {
        "auto_allowed": "low",
        "human_approval_required": "medium",
        "two_step_approval_required": "high",
    }
    classes = policy.get("approval_classes") or {}
    result: list[dict[str, Any]] = []
    for name in ("auto_allowed", "human_approval_required", "two_step_approval_required"):
        config = classes.get(name) or {}
        actions = list(config.get("actions") or [])
        result.append({
            "name": name,
            "description": config.get("description") or "",
            "action_count": len(actions),
            "actions": actions,
            "risk": risk_by_name[name],
        })
    return result


def normalize_memory_stores(policy: dict[str, Any]) -> list[dict[str, Any]]:
    stores = policy.get("stores") or {}
    return [
        {
            "name": name,
            "description": config.get("description") or "",
            "retention_days": int(config.get("retention_days") or 0),
            "access_roles": list(config.get("access_roles") or []),
            "vectorization_allowed": bool(config.get("vectorization_allowed", False)),
            "redaction_required": bool(config.get("redaction_required", False)),
            "pii_minimized": bool(config.get("pii_minimized", False)),
        }
        for name, config in sorted(stores.items())
    ]


def normalize_permission_agents(policy: dict[str, Any]) -> list[dict[str, Any]]:
    agents = policy.get("agents") or {}
    result: list[dict[str, Any]] = []
    for agent_id, config in sorted(agents.items()):
        permissions = config.get("permissions") or {}
        result.append({
            "agent_id": agent_id,
            "description": config.get("description") or "",
            "read_count": len(permissions.get("read") or []),
            "write_count": len(permissions.get("write") or []),
            "execute_count": len(permissions.get("execute") or []),
            "denied_count": len(permissions.get("denied") or []),
        })
    return result


def normalize_model_routing(rules: dict[str, Any]) -> dict[str, Any]:
    defaults = rules.get("defaults") or {}
    routing_rules = rules.get("routing_rules") or []
    return {
        "local_first": bool(defaults.get("local_first", False)),
        "cloud_default_disabled": bool(defaults.get("cloud_default_disabled", False)),
        "deny_if_route_uncertain": bool(defaults.get("deny_if_route_uncertain", False)),
        "rule_count": len(routing_rules),
        "rules": [
            {
                "id": rule.get("id"),
                "route": (rule.get("then") or {}).get("route"),
                "conditions": rule.get("if") or {},
            }
            for rule in routing_rules
        ],
    }


def extract_shared_constraints(policy: dict[str, Any]) -> list[str]:
    constraints = policy.get("shared_constraints") or {}
    return list(constraints.get("no_agent_may") or [])


def build_settings_summary(
    *,
    registry: dict[str, Any],
    domains: list[str],
    user_count: int | None,
    approval_classes: list[dict[str, Any]],
    memory_stores: list[dict[str, Any]],
    permission_agents: list[dict[str, Any]],
    model_rules: list[dict[str, Any]],
    shared_constraints: list[str],
    audit_config_events: int,
) -> dict[str, Any]:
    retention_values = [
        int(store["retention_days"])
        for store in memory_stores
        if int(store.get("retention_days") or 0) > 0
    ]
    approval_by_name = {item["name"]: item for item in approval_classes}
    return {
        "agent_count": len(registry.get("agents") or []),
        "worker_count": len(registry.get("workers") or []),
        "domain_count": len(domains),
        "user_count": user_count,
        "approval_class_count": len(approval_classes),
        "human_approval_actions": int((approval_by_name.get("human_approval_required") or {}).get("action_count") or 0),
        "two_step_actions": int((approval_by_name.get("two_step_approval_required") or {}).get("action_count") or 0),
        "memory_store_count": len(memory_stores),
        "min_retention_days": min(retention_values) if retention_values else 0,
        "max_retention_days": max(retention_values) if retention_values else 0,
        "permission_agent_count": len(permission_agents),
        "denied_action_count": sum(int(agent.get("denied_count") or 0) for agent in permission_agents),
        "model_rule_count": len(model_rules),
        "shared_constraint_count": len(shared_constraints),
        "audit_config_events": audit_config_events,
    }


def list_shared_domains() -> list[str]:
    if not _SHARED_ROOT.exists():
        return []
    return sorted(path.name for path in _SHARED_ROOT.iterdir() if path.is_dir())


async def _safe_user_count() -> int | None:
    try:
        pool = await get_pool()
        row = await pool.fetchrow("SELECT COUNT(*) AS total FROM users")
        return int(row["total"]) if row else 0
    except Exception:
        return None


async def _safe_config_audit_count() -> int:
    try:
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT COUNT(*) AS total
            FROM audit_log
            WHERE category IN ('platform', 'security')
              AND (
                action LIKE '%config%'
                OR action LIKE '%policy%'
                OR action LIKE '%domain%'
                OR action LIKE '%agent%'
                OR action LIKE '%user%'
              )
            """
        )
        return int(row["total"]) if row else 0
    except Exception:
        return 0


@router.get("/summary")
async def get_settings_summary(_user=Depends(_get_current_user)):
    registry = load_registry()
    domains = list_shared_domains()
    permissions = load_permissions()
    approval_classes = normalize_approval_classes(load_approval_policy())
    memory_stores = normalize_memory_stores(load_memory_policy())
    permission_agents = normalize_permission_agents(permissions)
    model_routing = normalize_model_routing(load_model_routing_rules())
    shared_constraints = extract_shared_constraints(permissions)
    user_count = await _safe_user_count()
    audit_config_events = await _safe_config_audit_count()

    return {
        "summary": build_settings_summary(
            registry=registry,
            domains=domains,
            user_count=user_count,
            approval_classes=approval_classes,
            memory_stores=memory_stores,
            permission_agents=permission_agents,
            model_rules=model_routing["rules"],
            shared_constraints=shared_constraints,
            audit_config_events=audit_config_events,
        ),
        "approval_classes": approval_classes,
        "memory_stores": memory_stores,
        "permission_agents": permission_agents,
        "model_routing": model_routing,
        "shared_constraints": shared_constraints,
        "domains": domains,
    }
