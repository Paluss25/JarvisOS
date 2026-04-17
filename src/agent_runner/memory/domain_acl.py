"""Domain ACL — check agent access to shared memory domains."""

import logging

from agent_runner.registry import get_agent_entry

logger = logging.getLogger(__name__)


def can_access_domain(agent_id: str, domain: str, mode: str = "read") -> bool:
    """Check if agent_id can read/write the given domain.

    Returns True if:
    - Agent has domains: ["*"] (Jarvis — full access)
    - domain is in agent's domains list
    - domain is "global" and mode is "read" (all agents can read global)
    """
    entry = get_agent_entry(agent_id)
    if not entry:
        return False

    domains = entry.get("domains", [])
    if "*" in domains:
        return True

    if domain == "global" and mode == "read":
        return True

    return domain in domains
