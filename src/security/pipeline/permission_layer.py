"""Layer 6 — PermissionLayer: per-agent tool permission enforcement."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PermissionResult:
    allowed: bool
    denied_tools: List[str]
    reasons: List[str]


class PermissionLayer:
    """Check per-agent tool permissions against permissions.yaml config."""

    def __init__(self, permissions_config: Dict[str, Any]) -> None:
        self._agents = permissions_config.get("agents", {})

    def check(
        self,
        agent_id: str,
        requested_tools: List[str],
    ) -> PermissionResult:
        denied_tools: List[str] = []
        reasons: List[str] = []

        if agent_id not in self._agents:
            return PermissionResult(
                allowed=False,
                denied_tools=[],
                reasons=["UNKNOWN_AGENT"],
            )

        agent_config = self._agents[agent_id]
        permissions = agent_config.get("permissions", {})
        denied_list: List[str] = permissions.get("denied", [])
        execute_list: List[str] = permissions.get("execute", [])

        for tool in requested_tools:
            if tool in denied_list:
                denied_tools.append(tool)
                reasons.append(f"TOOL_DENIED:{tool}")
            elif execute_list and tool not in execute_list:
                denied_tools.append(tool)
                reasons.append(f"TOOL_NOT_ALLOWED:{tool}")

        return PermissionResult(
            allowed=len(denied_tools) == 0,
            denied_tools=denied_tools,
            reasons=reasons,
        )
