# agent_runner/issues/schema.py
"""Shared issue schema — used by all agents' report_issue tool and CIO's IssueCollector."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

IssueType = Literal[
    "connection_error",
    "db_error",
    "mcp_unreachable",
    "restart_detected",
    "high_error_rate",
    "auth_failure",
    "custom",
]

IssueSeverity = Literal["critical", "high", "medium"]

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2}


def severity_rank(s: IssueSeverity) -> int:
    return _SEVERITY_RANK.get(s, 99)


@dataclass
class Issue:
    type: IssueType
    severity: IssueSeverity
    component: str        # e.g. "redis", "postgres-shared", "protonmail-mcp"
    description: str      # max 200 chars

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "severity": self.severity,
            "component": self.component,
            "description": self.description[:200],
        }


@dataclass
class IssueReport:
    agent_id: str
    timestamp: str        # ISO 8601
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "issues": [i.to_dict() for i in self.issues],
        }

    @staticmethod
    def from_dict(data: dict) -> "IssueReport":
        issues = [
            Issue(
                type=i.get("type", "custom"),
                severity=i.get("severity", "medium"),
                component=i.get("component", "unknown"),
                description=i.get("description", ""),
            )
            for i in data.get("issues", [])
        ]
        return IssueReport(
            agent_id=data.get("agent_id", "unknown"),
            timestamp=data.get("timestamp", ""),
            issues=issues,
        )
