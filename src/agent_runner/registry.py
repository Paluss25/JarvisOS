"""Load and parse agents.yaml registry.

Supports hot-reload: subscribe_to_config_changes() starts a background
Redis subscriber that re-reads agents.yaml on platform:config_changed.
"""

import asyncio
import logging
import os
from pathlib import Path
from collections.abc import Callable
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


async def subscribe_to_config_changes(on_change: Callable | None = None) -> None:
    """Subscribe to platform:config_changed Redis channel.

    Logs whenever agents.yaml is updated. Calls on_change() if provided.
    Run as a background asyncio task from the agent lifespan.
    """
    import redis.asyncio as aioredis

    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        logger.debug("registry: REDIS_URL not set — skipping config change subscription")
        return

    try:
        r = aioredis.from_url(redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe("platform:config_changed")
        logger.info("registry: listening for config changes on platform:config_changed")
        async for message in pubsub.listen():
            if message["type"] == "message":
                logger.info("registry: config_changed — agents.yaml reloaded")
                if on_change:
                    try:
                        on_change()
                    except Exception as exc:
                        logger.warning("registry: on_change callback failed — %s", exc)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.warning("registry: config change subscriber error — %s", exc)
    finally:
        try:
            await r.aclose()
        except Exception:
            pass
