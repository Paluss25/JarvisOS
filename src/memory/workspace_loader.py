"""Load workspace MD files into a dict for agent instructions.

All files are read from the workspace directory at session start.
Missing optional files are returned as empty strings (never raise).
"""

import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# Required files (warn if missing)
_REQUIRED = ["SOUL.md", "AGENTS.md", "USER.md"]

# Optional files (silently empty if missing)
_OPTIONAL = ["TOOLS.md", "MEMORY.md", "HEARTBEAT.md", "IDENTITY.md"]


def _read(path: Path) -> str:
    """Read a file, returning empty string if it doesn't exist."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        logger.warning("workspace_loader: could not read %s — %s", path, exc)
        return ""


def load_workspace_context(workspace_path: str | Path) -> dict:
    """Load all workspace MD files into a dict for agent instructions.

    Returns:
        dict with keys:
        - soul       — SOUL.md
        - agents     — AGENTS.md
        - user       — USER.md
        - tools_md   — TOOLS.md
        - memory     — MEMORY.md
        - heartbeat  — HEARTBEAT.md
        - identity   — IDENTITY.md
        - daily      — memory/YYYY-MM-DD.md (today; empty string if not yet created)
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
        "memory":    _read(root / "MEMORY.md"),
        "heartbeat": _read(root / "HEARTBEAT.md"),
        "identity":  _read(root / "IDENTITY.md"),
        "daily":     _read(root / "memory" / f"{date.today().isoformat()}.md"),
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
