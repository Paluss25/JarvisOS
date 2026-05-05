"""Data models for creating Plane work items from JarvisOS incidents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def priority_from_severity(severity: str) -> str:
    normalized = severity.strip().lower()
    return {
        "p0": "urgent",
        "critical": "urgent",
        "urgent": "urgent",
        "p1": "high",
        "high": "high",
        "p2": "medium",
        "medium": "medium",
        "normal": "medium",
        "p3": "low",
        "low": "low",
    }.get(normalized, "none")


@dataclass(frozen=True)
class PlaneWorkItemDraft:
    name: str
    description_html: str
    priority: str = "none"
    external_source: str = "jarvisos-mt"
    external_id: str = ""
    state: str = ""
    parent: str = ""

    def to_payload(self) -> dict[str, str]:
        payload = {
            "name": self.name,
            "description_html": self.description_html,
            "priority": self.priority,
            "external_source": self.external_source,
            "external_id": self.external_id,
        }
        if self.state:
            payload["state"] = self.state
        if self.parent:
            payload["parent"] = self.parent
        return payload


@dataclass(frozen=True)
class IncidentResolutionUpdate:
    service: str
    title: str
    severity: str
    status: str
    problem: str
    root_cause: str = ""
    resolution_plan: list[str] = field(default_factory=list)
    source_agent: str = "cio"

    def external_id(self) -> str:
        service_key = self.service.strip().lower()
        digest_input = "\0".join(
            [
                self.source_agent.strip().lower(),
                service_key,
                self.title.strip(),
            ]
        )
        digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]
        return f"cio:{service_key}:{digest}"
