"""Session lifecycle management for the agent runner.

Tracks session start/end and persists summaries to the daily memory file.
File-first approach — no external memory API dependency.
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_runner.memory.daily_logger import DailyLogger

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Rome")


def _now() -> datetime:
    return datetime.now(tz=_TZ)


class SessionManager:
    """Track session lifecycle and persist summaries to the daily log.

    One instance is created at agent startup and shared across all
    interfaces (Telegram, CLI).

    Usage::

        sm = SessionManager(workspace_path)
        sm.start()
        # ... conversation ...
        await sm.end("Summary of what was accomplished")
    """

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = Path(workspace_path)
        self._session_id: str | None = None
        self._started_at: datetime | None = None
        self._daily = DailyLogger(workspace_path)

    # ------------------------------------------------------------------ #
    #  Session lifecycle                                                   #
    # ------------------------------------------------------------------ #

    @property
    def session_id(self) -> str:
        """Return the current session ID, generating one if needed."""
        if self._session_id is None:
            self._session_id = str(uuid.uuid4())
        return self._session_id

    def start(self, session_id: str | None = None) -> str:
        """Start a new session (or resume an existing one by ID).

        Args:
            session_id: Resume a specific session; if None, a new UUID is
                        generated.  Interfaces (Telegram, CLI) pass the same
                        ID to share context.

        Returns:
            The active session_id.
        """
        if session_id:
            self._session_id = session_id
        else:
            self._session_id = str(uuid.uuid4())
        self._started_at = _now()

        self._daily.log(f"[SESSION START] id={self._session_id}")
        logger.info("session_manager: started session %s", self._session_id)
        return self._session_id

    async def end(self, summary: str | None = None) -> None:
        """Close the current session, optionally persisting a summary.

        Args:
            summary: Human-readable description of what happened this session.
        """
        if not self._session_id:
            logger.debug("session_manager: end() called with no active session")
            return

        duration = ""
        if self._started_at:
            delta = _now() - self._started_at
            minutes = int(delta.total_seconds() // 60)
            duration = f" (duration: {minutes}m)"

        self._daily.log(f"[SESSION END] id={self._session_id}{duration}")

        if summary:
            self._daily.log_session_summary(summary)

        logger.info("session_manager: ended session %s%s", self._session_id, duration)
        self._session_id = None
        self._started_at = None

    def reset(self) -> None:
        """Force-start a new session without writing an end entry."""
        self._session_id = None
        self._started_at = None
