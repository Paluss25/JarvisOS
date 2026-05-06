"""Structured open-loop state for agent memory freshness.

The registry is intentionally simple JSON so live workspaces can be edited by
agents or humans without a migration step.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

REGISTRY_PATH = Path("state/open_loops.json")
DEFAULT_FRESH_HOURS = 48
RECENT_RESOLVED_DAYS = 14


FRESHNESS_GUARD = """\
Treat MEMORY.md and daily logs as append-only narrative, not as authoritative
state. The Open Loop Registry below is authoritative when it contradicts older
memory text. Do not reopen stale MEMORY.md or DREAMS.md items when the registry
has a newer RESOLVED entry. Do not report STALE_NEEDS_REVERIFY items as active
actions; run or request a fresh verification first, then update the registry.
Every action surfaced from memory must include fresh evidence or an explicit
live verification step."""


def _coerce_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        value = raw.get("open_loops", raw.get("items", []))
        items = value if isinstance(value, list) else []
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _item_timestamp(item: dict[str, Any]) -> datetime | None:
    for key in ("last_verified_at", "updated_at", "resolved_at", "created_at"):
        parsed = _parse_dt(item.get(key))
        if parsed:
            return parsed
    return None


def _format_item(prefix: str, item: dict[str, Any], timestamp: datetime | None) -> str:
    loop_id = str(item.get("id", "")).strip() or "unknown"
    title = str(item.get("title", "")).strip()
    owner = str(item.get("owner", "")).strip()
    evidence = str(item.get("evidence", "")).strip()
    parts = [f"{prefix}: {loop_id}"]
    if title:
        parts.append(f"- {title}")
    if owner:
        parts.append(f"(owner={owner})")
    if timestamp:
        parts.append(f"[ts={timestamp.isoformat()}]")
    if evidence:
        parts.append(f"evidence={evidence}")
    return " ".join(parts)


def render_open_loop_context(
    workspace_path: str | Path,
    *,
    now: datetime | None = None,
    fresh_hours: int = DEFAULT_FRESH_HOURS,
) -> str:
    """Render authoritative open-loop state for prompt injection."""
    root = Path(workspace_path)
    path = root / REGISTRY_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("open_loop_registry: could not read %s — %s", path, exc)
        return ""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    fresh_after = current - timedelta(hours=fresh_hours)
    resolved_after = current - timedelta(days=RECENT_RESOLVED_DAYS)

    open_lines: list[str] = []
    resolved_lines: list[str] = []
    stale_lines: list[str] = []

    for item in _coerce_items(raw):
        status = str(item.get("status", "open")).strip().lower()
        timestamp = _item_timestamp(item)
        if status in {"resolved", "closed", "done", "verified"}:
            if timestamp is None or timestamp >= resolved_after:
                resolved_lines.append(_format_item("RESOLVED", item, timestamp))
            continue
        if status in {"stale", "expired"}:
            stale_lines.append(_format_item("STALE_NEEDS_REVERIFY", item, timestamp))
            continue
        if timestamp is not None and timestamp < fresh_after:
            stale_lines.append(_format_item("STALE_NEEDS_REVERIFY", item, timestamp))
            continue
        open_lines.append(_format_item("OPEN", item, timestamp))

    if not (open_lines or resolved_lines or stale_lines):
        return ""

    sections = [
        "Authoritative open-loop state. Use this over older MEMORY.md text.",
    ]
    if open_lines:
        sections.append("Fresh open actions:\n" + "\n".join(f"- {line}" for line in open_lines))
    if resolved_lines:
        sections.append("Recently resolved suppressors:\n" + "\n".join(f"- {line}" for line in resolved_lines))
    if stale_lines:
        sections.append(
            "Stale narrative items requiring live re-verification; do not report as an active action:\n"
            + "\n".join(f"- {line}" for line in stale_lines)
        )
    return "\n\n".join(sections)
