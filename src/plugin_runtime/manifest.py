from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from plugin_runtime.errors import PluginManifestError


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: int
    entrypoint: str
    tools: tuple[str, ...]
    allowed_agents: tuple[str, ...]


def load_manifest_text(text: str) -> PluginManifest:
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise PluginManifestError("manifest must be a mapping")

    name = _required_str(raw, "name")
    version = int(raw.get("version", 1))
    entrypoint = _required_str(raw, "entrypoint")
    tools = _required_str_list(raw, "tools")
    allowed_agents = _required_str_list(raw, "allowed_agents")

    return PluginManifest(
        name=name,
        version=version,
        entrypoint=entrypoint,
        tools=tuple(tools),
        allowed_agents=tuple(allowed_agents),
    )


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginManifestError(f"{key} is required")
    return value.strip()


def _required_str_list(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise PluginManifestError(f"{key} must be a non-empty list")
    out = [str(item).strip() for item in value if str(item).strip()]
    if not out:
        raise PluginManifestError(f"{key} must be a non-empty list")
    return out
