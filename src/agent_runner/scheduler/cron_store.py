"""Persistent cron store — read/write workspace/crons.json.

Schedule format:
    daily@HH:MM              — every day at HH:MM (Europe/Rome)
    weekly@DOW@HH:MM         — every week on DOW at HH:MM
                               DOW: mon / tue / wed / thu / fri / sat / sun
    once@YYYY-MM-DD@HH:MM   — one-shot; auto-disables after running

crons.json schema:
{
    "version": 1,
    "crons": [
        {
            "id":              str    # 8-char hex
            "name":            str    # human label
            "schedule":        str
            "prompt":          str    # sent to agent.query()
            "session_id":      str
            "telegram_notify": bool
            "enabled":         bool
            "created_at":      str    # ISO datetime
            "last_run":        str | null   # ISO datetime of last run
            "last_status":     str    # "ok" | "error" | "never"
            "last_error":      str | null
            "builtin":         bool   # True = system task (cannot delete)
        }
    ]
}

get_store(workspace_path) returns a module-level singleton so both the
heartbeat scheduler and the MCP tools share the same in-memory object.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Rome")

_DOW_MAP: dict[str, int] = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

_WINDOW_MINUTES = 4        # minutes after target time still considered "due"
_MISSED_WINDOW_HOURS = 23  # max age of a missed task before we stop trying


# ---------------------------------------------------------------------------
# CronEntry
# ---------------------------------------------------------------------------

class CronEntry:
    __slots__ = (
        "id", "name", "schedule", "prompt", "session_id",
        "telegram_notify", "enabled", "created_at",
        "last_run", "last_status", "last_error", "builtin",
    )

    def __init__(self, data: dict) -> None:
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.schedule: str = data["schedule"]
        self.prompt: str = data["prompt"]
        self.session_id: str = data.get("session_id", f"heartbeat-{self.id}")
        self.telegram_notify: bool = bool(data.get("telegram_notify", False))
        self.enabled: bool = bool(data.get("enabled", True))
        self.created_at: str = data.get("created_at", datetime.now(_TZ).isoformat())
        self.last_run: str | None = data.get("last_run")
        self.last_status: str = data.get("last_status", "never")
        self.last_error: str | None = data.get("last_error")
        self.builtin: bool = bool(data.get("builtin", False))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "schedule": self.schedule,
            "prompt": self.prompt,
            "session_id": self.session_id,
            "telegram_notify": self.telegram_notify,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "builtin": self.builtin,
        }


# ---------------------------------------------------------------------------
# Schedule parsing
# ---------------------------------------------------------------------------

def parse_schedule(schedule: str) -> tuple[str, dict]:
    """Parse a schedule string. Returns (kind, params) or raises ValueError.

    kinds and params:
        "daily"  → {"hour": int, "minute": int}
        "weekly" → {"dow": int, "hour": int, "minute": int}
        "once"   → {"date": datetime.date, "hour": int, "minute": int}
    """
    parts = schedule.strip().split("@")
    kind = parts[0].lower()

    if kind == "daily" and len(parts) == 2:
        h, m = _parse_hhmm(parts[1])
        return "daily", {"hour": h, "minute": m}

    if kind == "weekly" and len(parts) == 3:
        dow_str = parts[1].lower()
        if dow_str not in _DOW_MAP:
            raise ValueError(
                f"Unknown day-of-week '{dow_str}'. Valid: {', '.join(_DOW_MAP)}"
            )
        h, m = _parse_hhmm(parts[2])
        return "weekly", {"dow": _DOW_MAP[dow_str], "hour": h, "minute": m}

    if kind == "once" and len(parts) == 3:
        from datetime import date as _date
        try:
            target_date = _date.fromisoformat(parts[1])
        except ValueError:
            raise ValueError(f"Invalid date '{parts[1]}'. Use YYYY-MM-DD.")
        h, m = _parse_hhmm(parts[2])
        return "once", {"date": target_date, "hour": h, "minute": m}

    raise ValueError(
        f"Invalid schedule '{schedule}'. "
        "Valid: daily@HH:MM | weekly@DOW@HH:MM | once@YYYY-MM-DD@HH:MM"
    )


def _parse_hhmm(s: str) -> tuple[int, int]:
    try:
        h_str, m_str = s.split(":")
        h, m = int(h_str), int(m_str)
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid time '{s}'. Use HH:MM (24h).")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Time out of range: '{s}'.")
    return h, m


# ---------------------------------------------------------------------------
# Due-time helpers
# ---------------------------------------------------------------------------

def is_due(entry: CronEntry, now: datetime) -> bool:
    """True if this entry should fire during the current tick window."""
    if not entry.enabled:
        return False
    try:
        kind, params = parse_schedule(entry.schedule)
    except ValueError:
        return False

    h = params["hour"]

    if kind == "daily":
        if now.hour != h or now.minute >= _WINDOW_MINUTES:
            return False
        if entry.last_run:
            lr = datetime.fromisoformat(entry.last_run).astimezone(_TZ)
            if lr.date() == now.date():
                return False  # already ran today
        return True

    if kind == "weekly":
        if (now.weekday() != params["dow"]
                or now.hour != h
                or now.minute >= _WINDOW_MINUTES):
            return False
        if entry.last_run:
            lr = datetime.fromisoformat(entry.last_run).astimezone(_TZ)
            if lr.isocalendar()[:2] == now.isocalendar()[:2]:
                return False  # already ran this ISO week
        return True

    if kind == "once":
        if (now.date() != params["date"]
                or now.hour != h
                or now.minute >= _WINDOW_MINUTES):
            return False
        if entry.last_run:
            return False  # already ran
        return True

    return False


def was_missed(entry: CronEntry, now: datetime) -> bool:
    """True if the entry was due recently but missed (e.g. container was restarted).

    Detects: container was stopped at 08:00, restarted at 08:10 — morning briefing
    would have been skipped without this check.
    """
    if not entry.enabled:
        return False
    try:
        kind, params = parse_schedule(entry.schedule)
    except ValueError:
        return False

    h, m_target = params["hour"], params["minute"]
    cutoff = timedelta(hours=_MISSED_WINDOW_HOURS)

    if kind == "daily":
        expected = now.replace(hour=h, minute=m_target, second=0, microsecond=0)
        if expected > now or (now - expected) > cutoff:
            return False
        if entry.last_run:
            lr = datetime.fromisoformat(entry.last_run).astimezone(_TZ)
            if lr >= expected:
                return False
        return True

    if kind == "weekly":
        dow = params["dow"]
        days_since = (now.weekday() - dow) % 7
        expected = (now - timedelta(days=days_since)).replace(
            hour=h, minute=m_target, second=0, microsecond=0
        )
        if expected > now or (now - expected) > cutoff:
            return False
        if entry.last_run:
            lr = datetime.fromisoformat(entry.last_run).astimezone(_TZ)
            if lr >= expected:
                return False
        return True

    if kind == "once":
        from datetime import date as _date
        target_date = params["date"]
        target_dt = datetime(
            target_date.year, target_date.month, target_date.day,
            h, m_target, tzinfo=_TZ,
        )
        if target_dt > now or (now - target_dt) > cutoff:
            return False
        if entry.last_run:
            return False
        return True

    return False


# ---------------------------------------------------------------------------
# CronStore
# ---------------------------------------------------------------------------

class CronStore:
    """Persistent cron store backed by workspace/crons.json."""

    def __init__(self, workspace_path: Path) -> None:
        self._path = workspace_path / "crons.json"
        self._crons: dict[str, CronEntry] = {}
        self._load()

    # --- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for raw in data.get("crons", []):
                entry = CronEntry(raw)
                self._crons[entry.id] = entry
            logger.info("cron_store: loaded %d cron(s)", len(self._crons))
        except Exception as exc:
            logger.error("cron_store: failed to load crons.json — %s", exc)

    def _save(self) -> None:
        try:
            payload = {
                "version": 1,
                "crons": [e.to_dict() for e in self._crons.values()],
            }
            self._path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("cron_store: failed to save crons.json — %s", exc)

    # --- public API --------------------------------------------------------

    def all(self) -> list[CronEntry]:
        return list(self._crons.values())

    def get(self, cron_id: str) -> CronEntry | None:
        return self._crons.get(cron_id)

    def seed(self, entries: list[dict]) -> None:
        """Seed built-in crons by name — skips entries that already exist."""
        existing_names = {e.name for e in self._crons.values() if e.builtin}
        changed = False
        for raw in entries:
            if raw["name"] in existing_names:
                continue
            raw = dict(raw)
            raw.setdefault("id", uuid.uuid4().hex[:8])
            raw.setdefault("builtin", True)
            raw.setdefault("created_at", datetime.now(_TZ).isoformat())
            raw.setdefault("last_run", None)
            raw.setdefault("last_status", "never")
            raw.setdefault("last_error", None)
            entry = CronEntry(raw)
            self._crons[entry.id] = entry
            logger.info("cron_store: seeded builtin '%s'", entry.name)
            changed = True
        if changed:
            self._save()

    def create(
        self,
        name: str,
        schedule: str,
        prompt: str,
        session_id: str = "",
        telegram_notify: bool = False,
    ) -> CronEntry:
        """Create a user cron. Raises ValueError on invalid schedule."""
        parse_schedule(schedule)  # validate — raises on bad input
        cron_id = uuid.uuid4().hex[:8]
        entry = CronEntry({
            "id": cron_id,
            "name": name,
            "schedule": schedule,
            "prompt": prompt,
            "session_id": session_id or f"heartbeat-{cron_id}",
            "telegram_notify": telegram_notify,
            "enabled": True,
            "created_at": datetime.now(_TZ).isoformat(),
            "last_run": None,
            "last_status": "never",
            "last_error": None,
            "builtin": False,
        })
        self._crons[cron_id] = entry
        self._save()
        return entry

    def update(self, cron_id: str, **kwargs) -> CronEntry:
        """Update allowed fields. Raises KeyError if not found."""
        entry = self._crons.get(cron_id)
        if entry is None:
            raise KeyError(f"Cron '{cron_id}' not found")
        allowed = {"name", "schedule", "prompt", "session_id", "telegram_notify", "enabled"}
        for key, val in kwargs.items():
            if key not in allowed:
                raise ValueError(f"Field '{key}' cannot be updated")
            if key == "schedule":
                parse_schedule(val)  # validate
            setattr(entry, key, val)
        self._save()
        return entry

    def delete(self, cron_id: str) -> None:
        """Delete a user cron. Raises KeyError / ValueError for builtins."""
        entry = self._crons.get(cron_id)
        if entry is None:
            raise KeyError(f"Cron '{cron_id}' not found")
        if entry.builtin:
            raise ValueError(
                f"'{entry.name}' is a built-in task. Use cron_update to disable it."
            )
        del self._crons[cron_id]
        self._save()

    def record_run(self, cron_id: str, status: str, error: str | None = None) -> None:
        """Record the result of a completed run. Auto-disables one-shots."""
        entry = self._crons.get(cron_id)
        if entry is None:
            return
        entry.last_run = datetime.now(_TZ).isoformat()
        entry.last_status = status
        entry.last_error = error
        if entry.schedule.startswith("once@"):
            entry.enabled = False
        self._save()


# ---------------------------------------------------------------------------
# Singleton factory — one CronStore per workspace path per process
# ---------------------------------------------------------------------------

_instances: dict[str, CronStore] = {}


def get_store(workspace_path: Path) -> CronStore:
    """Return the shared CronStore for this workspace path."""
    key = str(workspace_path.resolve())
    if key not in _instances:
        _instances[key] = CronStore(workspace_path)
    return _instances[key]
