"""Load workspace MD files into a dict for agent instructions.

All files are read from the workspace directory at session start.
Missing optional files are returned as empty strings (never raise).
"""

import logging
from datetime import date, timedelta
from pathlib import Path

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


def _extract_frontmatter_value(frontmatter: str, key: str) -> str:
    prefix = f"{key}:"
    for line in frontmatter.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip().strip("\"'")
    return ""


def _format_skill(path: Path) -> str:
    content = _read(path)
    if not content:
        return ""

    name = path.parent.name
    description = ""
    body = content
    if content.startswith("---\n"):
        parts = content.split("---", 2)
        if len(parts) == 3:
            frontmatter = parts[1]
            body = parts[2].strip()
            name = _extract_frontmatter_value(frontmatter, "name") or name
            description = _extract_frontmatter_value(frontmatter, "description")

    header = f"### {name}"
    if description:
        header = f"{header}\n\n{description}"
    return f"{header}\n\n{body}".strip()


def _read_skills(root: Path) -> str:
    """Load AgentSkills/OpenClaw-compatible SKILL.md files for prompt injection."""
    sections: list[str] = []
    loaded_names: set[str] = set()
    for skills_root in _skill_search_roots(root):
        if not skills_root.exists():
            continue
        for skill_md in sorted(skills_root.glob("*/SKILL.md")):
            skill_name = skill_md.parent.name
            if skill_name in loaded_names:
                continue
            rendered = _format_skill(skill_md)
            if rendered:
                sections.append(rendered)
                loaded_names.add(skill_name)
    return "\n\n---\n\n".join(sections)[:_SKILLS_MAX_CHARS]


def load_workspace_context(workspace_path: str | Path) -> dict:
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
    """
    root = Path(workspace_path)

    for filename in _REQUIRED:
        p = root / filename
        if not p.exists():
            logger.warning("workspace_loader: required file missing: %s", p)

    ctx = {
        "soul":      _read(root / "SOUL.md"),
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
        "skills": _read_skills(root),
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
