"""In-memory cooldown tracker for ops-detector patterns.

Prevents the same pattern from firing more than once per cooldown window.
State is lost on process restart (intentional — avoids stale suppression).
"""
from datetime import datetime, timedelta, timezone


class DedupTracker:
    """Track when each pattern last fired to enforce cooldown windows."""

    def __init__(self) -> None:
        self._last_fired: dict[str, datetime] = {}

    def is_allowed(self, pattern_id: str, cooldown_minutes: int) -> bool:
        """Return True if pattern_id may fire (cooldown elapsed or first fire)."""
        last = self._last_fired.get(pattern_id)
        if last is None:
            return True
        return datetime.now(timezone.utc) - last >= timedelta(minutes=cooldown_minutes)

    def record(self, pattern_id: str) -> None:
        """Record that pattern_id fired now."""
        self._last_fired[pattern_id] = datetime.now(timezone.utc)
