"""Unit tests for CalendarClient — mocks caldav.DAVClient."""
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ICAL_TEMPLATE = """\
BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//1.0//EN\r\n\
BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\n\
DTSTART:{dtstart}\r\nDTEND:{dtend}\r\n\
END:VEVENT\r\nEND:VCALENDAR\r\n"""


def _mock_event(uid="uid-1", summary="Meeting", dtstart="20260428T150000Z", dtend="20260428T160000Z"):
    e = MagicMock()
    e.data = ICAL_TEMPLATE.format(uid=uid, summary=summary, dtstart=dtstart, dtend=dtend)
    e.uid = uid
    return e


def _make_client(calendar_name="personal"):
    """Return a CalendarClient with a fully mocked caldav.DAVClient."""
    from agents.mt.calendar_client import CalendarClient

    mock_cal = MagicMock()
    mock_cal.name = calendar_name
    mock_cal.url = f"https://cal.prova9x.com/paluss/{calendar_name}/"

    mock_principal = MagicMock()
    mock_principal.calendars.return_value = [mock_cal]

    mock_dav = MagicMock()
    mock_dav.principal.return_value = mock_principal

    with patch("agents.mt.calendar_client.caldav.DAVClient", return_value=mock_dav):
        client = CalendarClient(
            url="https://cal.prova9x.com",
            user="paluss",
            password="secret",
            calendar_name=calendar_name,
        )
        # Attach mocks so tests can configure search/add_event/etc.
        client._mock_cal = mock_cal
        client._mock_dav = mock_dav
    return client


# ---------------------------------------------------------------------------
# list_calendars
# ---------------------------------------------------------------------------

def test_list_calendars_returns_name_and_url():
    from agents.mt.calendar_client import CalendarClient

    mock_cal = MagicMock()
    mock_cal.name = "personal"
    mock_cal.url = "https://cal.prova9x.com/paluss/personal/"

    mock_principal = MagicMock()
    mock_principal.calendars.return_value = [mock_cal]

    mock_dav = MagicMock()
    mock_dav.principal.return_value = mock_principal

    with patch("agents.mt.calendar_client.caldav.DAVClient", return_value=mock_dav):
        client = CalendarClient("https://cal.prova9x.com", "paluss", "secret")
        result = client.list_calendars()

    assert len(result) == 1
    assert result[0]["name"] == "personal"
    assert "prova9x.com" in result[0]["url"]


# ---------------------------------------------------------------------------
# get_events
# ---------------------------------------------------------------------------

def test_get_events_returns_parsed_list():
    client = _make_client()
    event = _mock_event(uid="evt-1", summary="Dentist")
    client._mock_cal.search.return_value = [event]

    result = client.get_events(date(2026, 4, 28), date(2026, 4, 28))

    assert len(result) == 1
    assert result[0]["uid"] == "evt-1"
    assert result[0]["summary"] == "Dentist"


def test_get_events_returns_empty_when_no_events():
    client = _make_client()
    client._mock_cal.search.return_value = []

    result = client.get_events(date(2026, 4, 28), date(2026, 4, 28))

    assert result == []


# ---------------------------------------------------------------------------
# check_conflicts
# ---------------------------------------------------------------------------

def test_check_conflicts_returns_overlapping_events():
    client = _make_client()
    event = _mock_event(uid="conflict-1", summary="Existing Meeting")
    client._mock_cal.search.return_value = [event]

    start = datetime(2026, 4, 28, 15, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 28, 16, 0, tzinfo=timezone.utc)
    conflicts = client.check_conflicts(start, end)

    assert len(conflicts) == 1
    assert conflicts[0]["uid"] == "conflict-1"


def test_check_conflicts_returns_empty_when_free():
    client = _make_client()
    client._mock_cal.search.return_value = []

    start = datetime(2026, 4, 28, 15, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 28, 16, 0, tzinfo=timezone.utc)
    conflicts = client.check_conflicts(start, end)

    assert conflicts == []


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------

def test_create_event_calls_add_event_and_returns_uid():
    client = _make_client()
    client._mock_cal.search.return_value = []  # no conflicts

    start = datetime(2026, 4, 28, 15, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 28, 16, 0, tzinfo=timezone.utc)
    uid = client.create_event("Team Sync", start, end, "Weekly sync")

    client._mock_cal.add_event.assert_called_once()
    assert isinstance(uid, str) and len(uid) == 36  # UUID format


# ---------------------------------------------------------------------------
# update_event
# ---------------------------------------------------------------------------

def test_update_event_saves_modified_ical():
    import caldav.error as caldav_error  # noqa: F401 (imported for type)
    client = _make_client()

    mock_event = _mock_event(uid="uid-to-update", summary="Old Title")
    client._mock_cal.event_by_uid.return_value = mock_event

    start = datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 29, 11, 0, tzinfo=timezone.utc)
    client.update_event("uid-to-update", "New Title", start, end)

    mock_event.save.assert_called_once()
    assert "New Title" in mock_event.data


def test_update_event_raises_for_unknown_uid():
    import caldav.error as caldav_error

    client = _make_client()
    client._mock_cal.event_by_uid.side_effect = caldav_error.NotFoundError("not found")

    with pytest.raises(ValueError, match="Event not found"):
        client.update_event(
            "unknown-uid",
            "Title",
            datetime(2026, 4, 29, 10, 0),
            datetime(2026, 4, 29, 11, 0),
        )


# ---------------------------------------------------------------------------
# delete_event
# ---------------------------------------------------------------------------

def test_delete_event_calls_delete():
    import caldav.error as caldav_error  # noqa: F401

    client = _make_client()
    mock_event = _mock_event(uid="uid-to-delete")
    client._mock_cal.event_by_uid.return_value = mock_event

    client.delete_event("uid-to-delete")

    mock_event.delete.assert_called_once()


def test_delete_event_raises_for_unknown_uid():
    import caldav.error as caldav_error

    client = _make_client()
    client._mock_cal.event_by_uid.side_effect = caldav_error.NotFoundError("not found")

    with pytest.raises(ValueError, match="Event not found"):
        client.delete_event("unknown-uid")


# ---------------------------------------------------------------------------
# calendar name not found
# ---------------------------------------------------------------------------

def test_get_events_raises_when_calendar_name_not_found():
    from agents.mt.calendar_client import CalendarClient

    mock_cal = MagicMock()
    mock_cal.name = "work"
    mock_cal.url = "https://cal.prova9x.com/paluss/work/"

    mock_principal = MagicMock()
    mock_principal.calendars.return_value = [mock_cal]

    mock_dav = MagicMock()
    mock_dav.principal.return_value = mock_principal

    with patch("agents.mt.calendar_client.caldav.DAVClient", return_value=mock_dav):
        client = CalendarClient("https://cal.prova9x.com", "paluss", "secret", "personal")

    with pytest.raises(ValueError, match="not found"):
        client.get_events(date(2026, 4, 28), date(2026, 4, 28))
