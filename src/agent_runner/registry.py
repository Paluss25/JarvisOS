"""Load and parse agents.yaml registry."""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path("/app/agents.yaml")


def load_registry(path: Path = _REGISTRY_PATH) -> dict[str, Any]:
    """Load agents.yaml and return the full config dict."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def get_agent_entry(agent_id: str, path: Path = _REGISTRY_PATH) -> dict[str, Any] | None:
    """Return the agent entry dict for the given agent_id, or None."""
    data = load_registry(path)
    for agent in data.get("agents", []):
        if agent.get("id") == agent_id:
            return agent
    return None


def get_platform_config(path: Path = _REGISTRY_PATH) -> dict[str, Any]:
    """Return the platform-level config section."""
    data = load_registry(path)
    return data.get("platform", {})


def list_agents(path: Path = _REGISTRY_PATH) -> list[dict[str, Any]]:
    """Return all agent entries."""
    data = load_registry(path)
    return data.get("agents", [])
