from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PluginContext:
    agent_id: str
    workspace_path: Path
    config: dict[str, Any]
