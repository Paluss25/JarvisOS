"""Structured strategic watchpoints for agent memory.

Watchpoints are not open actions. They are dated strategic risks or themes that
must remain visible until a decision gate, without reopening resolved loops.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

REGISTRY_PATH = Path("state/watchpoints.json")


def _coerce_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        value = raw.get("watchpoints", raw.get("items", []))
        items = value if isinstance(value, list) else []
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _format_evidence(value: Any) -> str:
    if isinstance(value, list):
        lines = [str(item).strip() for item in value if str(item).strip()]
        return "; ".join(lines)
    return str(value or "").strip()


def render_watchpoint_context(workspace_path: str | Path) -> str:
    """Render structured watchpoints for prompt injection."""
    root = Path(workspace_path)
    path = root / REGISTRY_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("watchpoint_registry: could not read %s — %s", path, exc)
        return ""

    lines: list[str] = []
    for item in _coerce_items(raw):
        status = str(item.get("status", "watching")).strip().lower()
        if status in {"closed", "resolved", "done", "archived"}:
            continue

        watchpoint_id = str(item.get("id", "")).strip() or "unknown"
        theme = str(item.get("theme", item.get("title", ""))).strip()
        owner = str(item.get("owner", "")).strip()
        decision_date = str(item.get("decision_date", item.get("decision_gate_at", ""))).strip()
        decision_trigger = str(item.get("decision_trigger", "")).strip()
        evidence = _format_evidence(item.get("evidence"))
        expected_output = str(item.get("expected_output", "")).strip()

        parts = [f"WATCHPOINT: {watchpoint_id}"]
        if theme:
            parts.append(f"- {theme}")
        if owner:
            parts.append(f"(owner={owner})")
        if decision_date:
            parts.append(f"[decision_date={decision_date}]")
        if decision_trigger:
            parts.append(f"trigger={decision_trigger}")
        if evidence:
            parts.append(f"evidence={evidence}")
        if expected_output:
            parts.append(f"expected_output={expected_output}")
        lines.append(" ".join(parts))

    if not lines:
        return ""

    return (
        "Strategic watchpoints. These are not open actions; keep them visible "
        "until their decision gate and do not reopen resolved loops without fresh evidence.\n"
        + "\n".join(f"- {line}" for line in lines)
    )
