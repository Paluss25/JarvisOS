"""Session lifecycle management for Jarvis.

Tracks session start/end, persists end-of-session summaries to both the
daily memory file and the centralized memory-api.  A single session_id is
shared across Telegram and CLI so both interfaces resume the same context.
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from memory.daily_logger import DailyLogger

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Rome")


def _now() -> datetime:
    return datetime.now(tz=_TZ)


class SessionManager:
    """Track session lifecycle and persist summaries.

    One instance is created at JarvisOS startup and shared across all
    interfaces (Telegram, CLI).  Each logical conversation reuses the same
    ``session_id`` so Agno's PostgreSQL session store keeps continuity.

    Usage::

        sm = SessionManager(workspace_path, memory_api_client)
        sm.start()
        # ... conversation ...
        await sm.end("Summary of what was accomplished")
    """

    def __init__(
        self,
        workspace_path: str | Path,
        memory_client=None,
    ):
        self.workspace_path = Path(workspace_path)
        self._memory_client = memory_client
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

        Writes to:
        1. Daily memory file (always, even if no summary)
        2. memory-api (if client is configured and summary is provided)

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
            await self._persist_to_memory_api(summary)

        logger.info("session_manager: ended session %s%s", self._session_id, duration)
        self._session_id = None
        self._started_at = None

    def reset(self) -> None:
        """Force-start a new session without writing an end entry."""
        self._session_id = None
        self._started_at = None

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    async def _persist_to_memory_api(self, summary: str) -> None:
        """Best-effort write to memory-api; never raises."""
        if not self._memory_client:
            return
        try:
            await self._memory_client.write(
                content=summary,
                metadata={
                    "type": "session_summary",
                    "session_id": self._session_id or "unknown",
                    "date": _now().date().isoformat(),
                },
            )
            logger.debug("session_manager: summary persisted to memory-api")
        except Exception as exc:
            logger.warning("session_manager: could not persist to memory-api — %s", exc)
