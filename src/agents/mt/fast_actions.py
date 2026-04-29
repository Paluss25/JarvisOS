"""MT fast-path: structured A2A actions that bypass the LLM."""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


async def mt_fast_path(payload: dict) -> dict | None:
    """Handle structured A2A actions for MT without invoking the LLM.

    Returns a result dict when the action is handled; None to fall through to LLM.
    """
    action = payload.get("action")
    if action == "create_reminder":
        return await _create_reminder(payload)
    return None


async def _create_reminder(payload: dict) -> dict:
    import datetime

    title = payload.get("title", "Reminder").strip()
    start_iso = payload.get("start", "").strip()
    end_iso = payload.get("end", "").strip()
    description = payload.get("description", "").strip()
    calendar_name = payload.get("calendar", "").strip()

    if not title or not start_iso or not end_iso:
        return {"ok": False, "error": "title, start, and end are required"}

    url = os.environ.get("RADICALE_URL", "").strip()
    if not url:
        return {"ok": False, "error": "CalDAV not configured (RADICALE_URL not set)"}

    user = os.environ.get("RADICALE_USER", "").strip()
    password = os.environ.get("RADICALE_PASSWORD", "").strip()
    name = calendar_name or os.environ.get("RADICALE_CALENDAR", "").strip()

    def _parse(s: str) -> datetime.datetime:
        s = s.strip()
        if s.endswith("Z"):
            return datetime.datetime.fromisoformat(s[:-1]).replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.fromisoformat(s)

    try:
        start = _parse(start_iso)
        end = _parse(end_iso)
    except ValueError as exc:
        return {"ok": False, "error": f"Invalid datetime: {exc}"}

    try:
        from agents.mt.calendar_client import CalendarClient

        client = CalendarClient(url=url, user=user, password=password, calendar_name=name)
        uid = await asyncio.to_thread(client.create_event, title, start, end, description)
        return {"ok": True, "uid": uid, "title": title, "start": start_iso, "end": end_iso}
    except Exception as exc:
        logger.error("mt_fast_path: create_reminder failed — %s", exc)
        return {"ok": False, "error": str(exc)}
