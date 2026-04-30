"""Daily memory logger — append timestamped entries to memory/YYYY-MM-DD.md.

Used directly and also as an Agno tool via DailyLogger.as_tool().
"""

import logging
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Rome")


def _now_str() -> str:
    return datetime.now(tz=_TZ).strftime("%H:%M:%S")


def _dated_path(workspace_path: Path, d: date, user_id: int | None = None) -> Path:
    """Compute the path for a memory file on a specific date.

    Does NOT create directories — only computes the path.
    """
    if user_id is not None:
        return workspace_path / "memory" / f"user-{user_id}" / f"{d.isoformat()}.md"
    return workspace_path / "memory" / f"{d.isoformat()}.md"


def _today_path(workspace_path: str | Path, user_id: int | None = None) -> Path:
    root = Path(workspace_path)
    if user_id is not None:
        memory_dir = root / "memory" / f"user-{user_id}"
    else:
        memory_dir = root / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return _dated_path(root, date.today(), user_id)


def _append(path: Path, entry: str) -> None:
    """Append a line to the daily memory file, creating it if needed."""
    if not path.exists():
        path.write_text(
            f"# Memory — {date.today().isoformat()}\n\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as f:
        f.write(entry + "\n")


class DailyLogger:
    """Append-only logger to today's memory/YYYY-MM-DD.md.

    Can be used standalone or passed to an Agno Agent as a tool:
        tools=[DailyLogger(workspace_path=settings.WORKSPACE_PATH)]
    """

    def __init__(self, workspace_path: str | Path, user_id: int | None = None):
        self.workspace_path = Path(workspace_path)
        self.user_id = user_id

    def _path(self) -> Path:
        return _today_path(self.workspace_path, self.user_id)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def log(self, message: str) -> None:
        """Append a timestamped entry to today's memory file."""
        entry = f"- [{_now_str()}] {message}"
        _append(self._path(), entry)
        logger.debug("daily_logger: %s", entry)

    def log_fallback_event(
        self,
        agent: str,
        from_model: str,
        to_model: str,
        error: str,
    ) -> None:
        """Log a model fallback cascade."""
        self.log(
            f"[FALLBACK] {agent}: {from_model} → {to_model} "
            f"({type(error).__name__ if not isinstance(error, str) else error})"
        )

    def log_session_summary(self, summary: str) -> None:
        """Append a session summary block."""
        block = (
            f"\n## Session Summary — {_now_str()}\n"
            f"{summary.strip()}\n"
        )
        _append(self._path(), block)

    def read_today(self) -> str:
        """Return today's memory file content (empty string if not yet created)."""
        p = self._path()
        try:
            return p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def read_date(self, d: date) -> str:
        """Return the memory file content for a specific date (empty string if absent)."""
        p = _dated_path(self.workspace_path, d, self.user_id)
        try:
            return p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
