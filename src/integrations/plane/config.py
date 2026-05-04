"""Configuration for the Plane REST API integration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlaneConfig:
    api_key: str
    workspace_slug: str
    default_project_id: str
    base_url: str = "https://api.plane.so"
    project_map: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            "PlaneConfig("
            f"base_url={self.base_url!r}, "
            f"workspace_slug={self.workspace_slug!r}, "
            f"default_project_id={self.default_project_id!r}, "
            f"project_map_keys={sorted(self.project_map)!r}, "
            "api_key='REDACTED')"
        )


def load_plane_config() -> PlaneConfig:
    api_key = os.environ.get("PLANE_API_KEY", "").strip()
    if not api_key:
        raise ValueError("PLANE_API_KEY is required for Plane integration")

    workspace_slug = os.environ.get("PLANE_WORKSPACE_SLUG", "").strip()
    if not workspace_slug:
        raise ValueError("PLANE_WORKSPACE_SLUG is required for Plane integration")

    default_project_id = os.environ.get("PLANE_DEFAULT_PROJECT_ID", "").strip()
    if not default_project_id:
        raise ValueError("PLANE_DEFAULT_PROJECT_ID is required for Plane integration")

    raw_map = os.environ.get("PLANE_PROJECT_MAP_JSON", "{}").strip() or "{}"
    try:
        project_map = json.loads(raw_map)
    except json.JSONDecodeError as exc:
        raise ValueError("PLANE_PROJECT_MAP_JSON must be valid JSON") from exc
    if not isinstance(project_map, dict):
        raise ValueError("PLANE_PROJECT_MAP_JSON must decode to an object")

    return PlaneConfig(
        api_key=api_key,
        base_url=os.environ.get("PLANE_BASE_URL", "https://api.plane.so").rstrip("/"),
        workspace_slug=workspace_slug,
        default_project_id=default_project_id,
        project_map={str(k): str(v) for k, v in project_map.items()},
    )
