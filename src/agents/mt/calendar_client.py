"""CalDAV wrapper for Radicale calendar operations.

Synchronous API — call from async code via asyncio.to_thread().
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import caldav
import caldav.lib.error as _caldav_error
import vobject
import vobject.icalendar as _vical

_UTC = _vical.utc


class CalendarClient:
    """Thin wrapper around caldav.DAVClient targeting a single Radicale collection."""

    def __init__(
        self,
        url: str,
        user: str,
        password: str,
        calendar_name: str = "",
    ) -> None:
        self._client = caldav.DAVClient(url=url, username=user, password=password)
        self._calendar_name = calendar_name
        self._calendar: Optional[caldav.Calendar] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_calendar(self) -> caldav.Calendar:
        """Return the cached caldav.Calendar, resolving it from the principal on first access."""
        if self._calendar is not None:
            return self._calendar
        principal = self._client.principal()
        calendars = principal.calendars()
        if not calendars:
            raise ValueError("No calendars found in Radicale principal.")
        if not self._calendar_name:
            self._calendar = calendars[0]
        else:
            for cal in calendars:
                if (cal.name or "").lower() == self._calendar_name.lower():
                    self._calendar = cal
                    break
            if self._calendar is None:
                names = [c.name for c in calendars]
                raise ValueError(
                    f"Calendar '{self._calendar_name}' not found. Available: {names}"
                )
        return self._calendar

    def _ensure_calendar(self, name: str) -> str:
        """Return the URL for calendar *name*, creating it via MKCOL if absent."""
        principal = self._client.principal()
        for cal in principal.calendars():
            if (cal.name or "").lower() == name.lower():
                url = str(cal.url)
                return url if url.endswith("/") else url + "/"
        new_cal = principal.make_calendar(name=name)
        url = str(new_cal.url)
        return url if url.endswith("/") else url + "/"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_calendars(self) -> list[dict]:
        principal = self._client.principal()
        return [
            {"name": cal.name, "url": str(cal.url)}
            for cal in principal.calendars()
        ]

    def get_events(self, start: date, end: date) -> list[dict]:
        cal = self._get_calendar()
        start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc)
        events = cal.search(start=start_dt, end=end_dt, event=True, expand=True)
        return [_parse_event(e) for e in events]

    def check_conflicts(self, start: datetime, end: datetime) -> list[dict]:
        cal = self._get_calendar()
        events = cal.search(start=start, end=end, event=True, expand=True)
        return [_parse_event(e) for e in events]

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str = "",
    ) -> str:
        cal = self._get_calendar()
        uid = str(uuid.uuid4())
        cal.add_event(_build_ical(uid, title, start, end, description))
        return uid

    def update_event(
        self,
        uid: str,
        title: str,
        start: datetime,
        end: datetime,
        description: str = "",
    ) -> None:
        cal = self._get_calendar()
        try:
            event = cal.event_by_uid(uid)
        except _caldav_error.NotFoundError as exc:
            raise ValueError(f"Event not found: {uid}") from exc
        event.data = _build_ical(uid, title, start, end, description)
        event.save()

    def delete_event(self, uid: str) -> None:
        cal = self._get_calendar()
        try:
            event = cal.event_by_uid(uid)
        except _caldav_error.NotFoundError as exc:
            raise ValueError(f"Event not found: {uid}") from exc
        event.delete()

    def upsert_event(self, calendar_url: str, uid: str, ical_data: str) -> None:
        """PUT an iCal string to *calendar_url*/*uid*.ics, creating or replacing the event."""
        try:
            self._client.request(
                f"{calendar_url}{uid}.ics",
                method="PUT",
                headers={"Content-Type": "text/calendar; charset=utf-8"},
                body=ical_data,
            )
        except Exception as exc:
            raise ValueError(f"Failed to upsert event {uid}: {exc}") from exc


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _parse_event(event) -> dict:
    """Parse a caldav Event object into a plain dict."""
    vobj = vobject.readOne(event.data)
    vevent = vobj.vevent
    return {
        "uid": str(vevent.uid.value),
        "summary": str(vevent.summary.value) if hasattr(vevent, "summary") else "",
        "start": str(vevent.dtstart.value),
        "end": str(vevent.dtend.value) if hasattr(vevent, "dtend") else "",
        "description": str(vevent.description.value) if hasattr(vevent, "description") else "",
    }


def _build_ical(uid: str, title: str, start: datetime, end: datetime, description: str) -> str:
    """Build a minimal VCALENDAR iCal string for a single VEVENT."""
    cal = vobject.iCalendar()
    vevent = cal.add("vevent")
    vevent.add("uid").value = uid
    vevent.add("summary").value = title
    # Normalise to vobject-recognised UTC to avoid "Unable to guess TZID" error
    if start.tzinfo is not None:
        start = start.astimezone(_UTC)
    if end.tzinfo is not None:
        end = end.astimezone(_UTC)
    vevent.add("dtstart").value = start
    vevent.add("dtend").value = end
    if description:
        vevent.add("description").value = description
    return cal.serialize()
