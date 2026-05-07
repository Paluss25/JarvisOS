"""Load workspace MD files into a dict for agent instructions.

All files are read from the workspace directory at session start.
Missing optional files are returned as empty strings (never raise).
"""

import logging
import hashlib
import os
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from agent_runner.memory.open_loop_registry import (
    FRESHNESS_GUARD,
    render_open_loop_context,
)
from agent_runner.memory.watchpoint_registry import render_watchpoint_context

logger = logging.getLogger(__name__)

# Required files (warn if missing)
_REQUIRED = ["SOUL.md", "AGENTS.md", "USER.md"]

# Optional files (silently empty if missing)
_OPTIONAL = ["TOOLS.md", "MEMORY.md", "HEARTBEAT.md", "IDENTITY.md", "ARCHITECTURE.md", "DREAMS.md"]

# Truncation limits — daily logs are append-only and can grow large; capped to
# avoid hitting the kernel ARG_MAX limit when the system prompt is passed to the
# Claude Code subprocess.  We take the TAIL of log files so recent entries survive.
_DAILY_MAX_CHARS = 8_000
_YESTERDAY_MAX_CHARS = 4_000
_MEMORY_MAX_CHARS = 10_000
_DREAMS_MAX_CHARS = 6_000
_SKILLS_MAX_CHARS = 12_000


def _read(path: Path) -> str:
    """Read a file, returning empty string if it doesn't exist."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        logger.warning("workspace_loader: could not read %s — %s", path, exc)
        return ""


def _read_tail(path: Path, max_chars: int) -> str:
    """Read a file and return the last `max_chars` characters (tail of log files)."""
    content = _read(path)
    if len(content) > max_chars:
        logger.debug("workspace_loader: truncating %s (%d→%d chars)", path.name, len(content), max_chars)
        return content[-max_chars:]
    return content


def _read_head(path: Path, max_chars: int) -> str:
    """Read a file and return the first `max_chars` characters."""
    content = _read(path)
    if len(content) > max_chars:
        logger.debug("workspace_loader: truncating %s (%d→%d chars)", path.name, len(content), max_chars)
        return content[:max_chars]
    return content


def _skill_search_roots(root: Path) -> list[Path]:
    """Return AgentSkills-compatible locations for this agent workspace."""
    candidates = [
        root.parent / "skills",
        root.parent / ".agents" / "skills",
        root / ".agents" / "skills",
        root / "skills",
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) != 3:
        return {}, content
    raw_meta = yaml.safe_load(parts[1]) or {}
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    return meta, parts[2].strip()


def _metadata_requires(meta: dict[str, Any]) -> dict[str, Any]:
    metadata = meta.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    direct = metadata.get("requires")
    if isinstance(direct, dict):
        return direct
    for value in metadata.values():
        if isinstance(value, dict) and isinstance(value.get("requires"), dict):
            return value["requires"]
    return {}


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _requirements_available(meta: dict[str, Any]) -> bool:
    requires = _metadata_requires(meta)
    bins = _list_value(requires.get("bins"))
    if bins and not all(shutil.which(name) for name in bins):
        return False
    any_bins = _list_value(requires.get("anyBins"))
    if any_bins and not any(shutil.which(name) for name in any_bins):
        return False
    env = _list_value(requires.get("env"))
    if env and not all(os.environ.get(name) for name in env):
        return False
    # Structured config requirements are intentionally not inferred; the user
    # or deploy config should allowlist such skills only after provisioning.
    if requires.get("config"):
        return False
    return True


def _format_skill(path: Path) -> str:
    content = _read(path)
    if not content:
        return ""

    name = path.parent.name
    description = ""
    body = content
    meta, parsed_body = _parse_frontmatter(content)
    if meta:
        if not _requirements_available(meta):
            return ""
        body = parsed_body
        name = str(meta.get("name", "")).strip() or name
        description = str(meta.get("description", "")).strip()

    header = f"### {name}"
    if description:
        header = f"{header}\n\n{description}"
    return f"{header}\n\n{body}".strip()


def _iter_skill_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for skills_root in _skill_search_roots(root):
        if not skills_root.exists():
            continue
        for skill_md in sorted(skills_root.glob("*/SKILL.md")):
            files.append(skill_md)
    return files


def _skill_name(path: Path) -> str:
    content = _read(path)
    meta, _body = _parse_frontmatter(content)
    return str(meta.get("name", "")).strip() or path.parent.name


def _selected_skill_files(root: Path, skills_allowlist: list[str] | None) -> list[Path]:
    allowed = None if skills_allowlist is None else set(skills_allowlist)
    selected: dict[str, Path] = {}
    for skill_md in _iter_skill_files(root):
        name = _skill_name(skill_md)
        if allowed is not None and name not in allowed:
            continue
        # Search roots are ordered from shared to agent-local. Later matches
        # override earlier shared skills with the same logical name.
        selected[name] = skill_md
    return [selected[name] for name in sorted(selected)]


def _read_skills(root: Path, skills_allowlist: list[str] | None = None) -> str:
    """Load AgentSkills-compatible SKILL.md files for prompt injection."""
    sections: list[str] = []
    for skill_md in _selected_skill_files(root, skills_allowlist):
        rendered = _format_skill(skill_md)
        if rendered:
            sections.append(rendered)
    return "\n\n---\n\n".join(sections)[:_SKILLS_MAX_CHARS]


def skills_snapshot_signature(workspace_path: str | Path, skills_allowlist: list[str] | None = None) -> str:
    root = Path(workspace_path)
    hasher = hashlib.sha256()
    for skill_md in _selected_skill_files(root, skills_allowlist):
        try:
            stat = skill_md.stat()
        except OSError:
            continue
        hasher.update(str(skill_md.resolve()).encode("utf-8"))
        hasher.update(str(stat.st_mtime_ns).encode("ascii"))
        hasher.update(str(stat.st_size).encode("ascii"))
        try:
            hasher.update(skill_md.read_bytes())
        except OSError:
            continue
    return hasher.hexdigest()


def load_workspace_context(workspace_path: str | Path, skills_allowlist: list[str] | None = None) -> dict:
    """Load all workspace MD files into a dict for agent instructions.

    Returns:
        dict with keys:
        - soul         — SOUL.md
        - agents       — AGENTS.md
        - user         — USER.md
        - tools_md     — TOOLS.md
        - memory       — MEMORY.md
        - dreams       — DREAMS.md (nightly dream log)
        - heartbeat    — HEARTBEAT.md
        - identity     — IDENTITY.md
        - daily        — memory/YYYY-MM-DD.md (today)
        - yesterday    — memory/YYYY-MM-DD.md (yesterday)
        - architecture — ARCHITECTURE.md (optional; technical self-knowledge)
        - memory_guard — global instructions for resolving stale memory
        - open_loops   — authoritative structured open-loop state
        - watchpoints  — strategic non-action watchpoints with decision gates
    """
    root = Path(workspace_path)

    for filename in _REQUIRED:
        p = root / filename
        if not p.exists():
            logger.warning("workspace_loader: required file missing: %s", p)

    ctx = {
        "soul":      _read(root / "SOUL.md"),
        "memory_guard": FRESHNESS_GUARD,
        "open_loops": render_open_loop_context(root),
        "watchpoints": render_watchpoint_context(root),
        "agents":    _read(root / "AGENTS.md"),
        "user":      _read(root / "USER.md"),
        "tools_md":  _read(root / "TOOLS.md"),
        "memory":    _read_head(root / "MEMORY.md", _MEMORY_MAX_CHARS),
        "dreams":    _read_head(root / "DREAMS.md", _DREAMS_MAX_CHARS),
        "heartbeat": _read(root / "HEARTBEAT.md"),
        "identity":  _read(root / "IDENTITY.md"),
        "daily":     _read_tail(root / "memory" / f"{date.today().isoformat()}.md", _DAILY_MAX_CHARS),
        "yesterday": _read_tail(root / "memory" / f"{(date.today() - timedelta(days=1)).isoformat()}.md", _YESTERDAY_MAX_CHARS),
        "architecture": _read(root / "ARCHITECTURE.md"),
        "skills": _read_skills(root, skills_allowlist),
        "skills_signature": skills_snapshot_signature(root, skills_allowlist),
    }

    loaded = [k for k, v in ctx.items() if v]
    logger.info("workspace_loader: loaded %d/%d files from %s", len(loaded), len(ctx), root)
    return ctx


def get_today_memory_path(workspace_path: str | Path) -> Path:
    """Return the path for today's memory file (creates parent dir if needed)."""
    root = Path(workspace_path)
    memory_dir = root / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir / f"{date.today().isoformat()}.md"
