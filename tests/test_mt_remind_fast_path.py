"""E2E tests for the /remind → A2A → MT fast path → CalDAV chain.

Covers three layers:
1. _parse_remind_time()    — time token parsing in telegram_bot
2. mt_fast_path()          — A2A fast-path dispatch in agents/mt/fast_actions.py
3. _create_reminder()      — CalDAV write, including env-var validation and CalendarClient mock
"""

import asyncio
import datetime
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Layer 1 — _parse_remind_time
# ---------------------------------------------------------------------------

class TestParseRemindTime:
    """Unit tests for the _parse_remind_time() helper in telegram_bot."""

    @staticmethod
    def _parse(token: str):
        from agent_runner.interfaces.telegram_bot import _parse_remind_time
        return _parse_remind_time(token)

    def test_relative_minutes_only(self):
        before = datetime.datetime.now()
        result = self._parse("30m")
        after = datetime.datetime.now()
        assert result is not None
        delta = (result - before).total_seconds()
        assert 29 * 60 <= delta <= 31 * 60 + (after - before).total_seconds()

    def test_relative_hours_only(self):
        before = datetime.datetime.now()
        result = self._parse("2h")
        assert result is not None
        delta = (result - before).total_seconds()
        assert 2 * 3600 - 5 <= delta <= 2 * 3600 + 5

    def test_relative_hours_and_minutes(self):
        before = datetime.datetime.now()
        result = self._parse("1h30m")
        assert result is not None
        delta = (result - before).total_seconds()
        assert 90 * 60 - 5 <= delta <= 90 * 60 + 5

    def test_absolute_time_future(self):
        # Use a time guaranteed to be in the future (add 3h to now)
        future = datetime.datetime.now() + datetime.timedelta(hours=3)
        token = future.strftime("%H:%M")
        result = self._parse(token)
        assert result is not None
        assert result.hour == future.hour
        assert result.minute == future.minute
        assert result.second == 0

    def test_absolute_time_past_bumps_to_next_day(self):
        # Pick a time that is definitely in the past today
        past = (datetime.datetime.now() - datetime.timedelta(hours=2)).replace(second=0, microsecond=0)
        token = past.strftime("%H:%M")
        result = self._parse(token)
        assert result is not None
        # Should be tomorrow
        expected_date = (datetime.datetime.now() + datetime.timedelta(days=1)).date()
        assert result.date() == expected_date

    def test_invalid_token_returns_none(self):
        assert self._parse("tomorrow") is None
        assert self._parse("soon") is None
        assert self._parse("") is None
        assert self._parse("25:00") is None

    def test_zero_duration_returns_none(self):
        # "0m" or "0h" should not produce a valid time offset
        result = self._parse("0m")
        assert result is None

    def test_case_insensitive(self):
        result_upper = self._parse("30M")
        result_lower = self._parse("30m")
        assert result_upper is not None
        assert result_lower is not None
        diff = abs((result_upper - result_lower).total_seconds())
        assert diff < 1


# ---------------------------------------------------------------------------
# Layer 2 — mt_fast_path dispatch
# ---------------------------------------------------------------------------

class TestMtFastPathDispatch:
    """mt_fast_path routes known actions and falls through on unknown ones."""

    def test_unknown_action_returns_none(self):
        from agents.mt.fast_actions import mt_fast_path
        result = _run(mt_fast_path({"action": "do_something_else"}))
        assert result is None

    def test_missing_action_returns_none(self):
        from agents.mt.fast_actions import mt_fast_path
        result = _run(mt_fast_path({}))
        assert result is None

    def test_create_reminder_dispatches(self, monkeypatch):
        """create_reminder must return a dict (not None), even if CalDAV is mocked."""
        from agents.mt.fast_actions import mt_fast_path
        import agents.mt.fast_actions as fa_mod

        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")
        monkeypatch.setenv("RADICALE_USER", "user")
        monkeypatch.setenv("RADICALE_PASSWORD", "pass")

        mock_client = MagicMock()
        mock_client.create_event.return_value = "uid-abc"

        with patch("agents.mt.calendar_client.CalendarClient", return_value=mock_client):
            result = _run(mt_fast_path({
                "action": "create_reminder",
                "title": "Call mum",
                "start": "2026-04-28T18:00:00",
                "end": "2026-04-28T18:30:00",
            }))

        assert result is not None
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Layer 3 — _create_reminder internals
# ---------------------------------------------------------------------------

class TestCreateReminder:
    """Direct tests for _create_reminder in mt/fast_actions.py."""

    @staticmethod
    def _call(payload: dict, env: dict | None = None):
        from agents.mt.fast_actions import _create_reminder

        env = env or {}
        with patch.dict(os.environ, env, clear=False):
            return _run(_create_reminder(payload))

    def test_missing_radicale_url_returns_error(self):
        env = {}
        os.environ.pop("RADICALE_URL", None)
        result = self._call({
            "title": "Test",
            "start": "2026-04-28T10:00:00",
            "end": "2026-04-28T10:30:00",
        }, env=env)
        assert result["ok"] is False
        assert "caldav" in result["error"].lower() or "radicale_url" in result["error"].lower()

    def test_missing_title_returns_error(self, monkeypatch):
        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")
        result = self._call({"title": "", "start": "2026-04-28T10:00:00", "end": "2026-04-28T10:30:00"})
        assert result["ok"] is False
        assert "required" in result["error"].lower()

    def test_missing_start_returns_error(self, monkeypatch):
        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")
        result = self._call({"title": "Meeting", "start": "", "end": "2026-04-28T10:30:00"})
        assert result["ok"] is False

    def test_missing_end_returns_error(self, monkeypatch):
        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")
        result = self._call({"title": "Meeting", "start": "2026-04-28T10:00:00", "end": ""})
        assert result["ok"] is False

    def test_invalid_datetime_returns_error(self, monkeypatch):
        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")
        result = self._call({
            "title": "Meeting",
            "start": "not-a-datetime",
            "end": "2026-04-28T10:30:00",
        })
        assert result["ok"] is False
        assert "invalid" in result["error"].lower()

    def test_success_returns_uid(self, monkeypatch):
        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")
        monkeypatch.setenv("RADICALE_USER", "paluss")
        monkeypatch.setenv("RADICALE_PASSWORD", "secret")

        mock_client = MagicMock()
        mock_client.create_event.return_value = "generated-uid-999"

        with patch("agents.mt.calendar_client.CalendarClient", return_value=mock_client):
            result = self._call({
                "title": "Walk the dog",
                "start": "2026-04-28T19:00:00",
                "end": "2026-04-28T19:30:00",
                "description": "Evening walk",
            })

        assert result["ok"] is True
        assert result["uid"] == "generated-uid-999"
        assert result["title"] == "Walk the dog"

    def test_success_zulu_datetime(self, monkeypatch):
        """ISO timestamps ending in Z must be parsed correctly."""
        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")

        mock_client = MagicMock()
        mock_client.create_event.return_value = "uid-zulu"

        with patch("agents.mt.calendar_client.CalendarClient", return_value=mock_client):
            result = self._call({
                "title": "Standup",
                "start": "2026-04-28T09:00:00Z",
                "end": "2026-04-28T09:15:00Z",
            })

        assert result["ok"] is True
        assert result["uid"] == "uid-zulu"

    def test_calendar_client_receives_correct_args(self, monkeypatch):
        """create_event must be called with title, parsed start, parsed end, description."""
        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")
        monkeypatch.setenv("RADICALE_USER", "u")
        monkeypatch.setenv("RADICALE_PASSWORD", "p")

        mock_client = MagicMock()
        mock_client.create_event.return_value = "uid-check"

        with patch("agents.mt.calendar_client.CalendarClient", return_value=mock_client):
            _run(__import__("agents.mt.fast_actions", fromlist=["_create_reminder"])._create_reminder({
                "title": "Dentist",
                "start": "2026-04-29T14:00:00",
                "end": "2026-04-29T15:00:00",
                "description": "Annual checkup",
            }))

        call_args = mock_client.create_event.call_args
        assert call_args is not None
        pos = call_args.args
        assert pos[0] == "Dentist"
        assert pos[1].hour == 14
        assert pos[2].hour == 15
        assert pos[3] == "Annual checkup"

    def test_calendar_client_exception_returns_error(self, monkeypatch):
        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")

        mock_client = MagicMock()
        mock_client.create_event.side_effect = RuntimeError("connection refused")

        with patch("agents.mt.calendar_client.CalendarClient", return_value=mock_client):
            result = self._call({
                "title": "Meeting",
                "start": "2026-04-28T10:00:00",
                "end": "2026-04-28T10:30:00",
            })

        assert result["ok"] is False
        assert "connection refused" in result["error"]

    def test_calendar_name_from_payload_overrides_env(self, monkeypatch):
        """calendar= in payload must take precedence over RADICALE_CALENDAR env var."""
        monkeypatch.setenv("RADICALE_URL", "http://radicale.test")
        monkeypatch.setenv("RADICALE_CALENDAR", "default-cal")

        mock_client = MagicMock()
        mock_client.create_event.return_value = "uid-cal"
        mock_ctor = MagicMock(return_value=mock_client)

        with patch("agents.mt.calendar_client.CalendarClient", mock_ctor):
            _run(__import__("agents.mt.fast_actions", fromlist=["_create_reminder"])._create_reminder({
                "title": "Board meeting",
                "start": "2026-04-29T10:00:00",
                "end": "2026-04-29T11:00:00",
                "calendar": "work",
            }))

        ctor_kwargs = mock_ctor.call_args.kwargs
        assert ctor_kwargs.get("calendar_name") == "work"


# ---------------------------------------------------------------------------
# Layer 4 — A2A integration: bot publishes, fast path handles
# ---------------------------------------------------------------------------

class TestRemindA2AFlow:
    """Simulate the full publish → fast-path → CalDAV flow without real Redis."""

    def test_a2a_payload_structure(self):
        """Verify the JSON payload that _cmd_remind would publish matches what mt_fast_path expects."""
        import json

        # Simulate what _cmd_remind builds
        title = "Team standup"
        start = datetime.datetime(2026, 4, 29, 9, 0, 0)
        end = start + datetime.timedelta(minutes=30)
        payload_str = json.dumps({
            "action": "create_reminder",
            "title": title,
            "start": start.isoformat(),
            "end": end.isoformat(),
        })

        payload = json.loads(payload_str)
        assert payload["action"] == "create_reminder"
        assert payload["title"] == title
        # mt_fast_path must accept this without error
        from agents.mt.fast_actions import mt_fast_path
        import agents.mt.fast_actions as fa_mod

        mock_client = MagicMock()
        mock_client.create_event.return_value = "uid-standup"

        with patch.dict(os.environ, {"RADICALE_URL": "http://test", "RADICALE_USER": "u", "RADICALE_PASSWORD": "p"}):
            with patch("agents.mt.calendar_client.CalendarClient", return_value=mock_client):
                result = _run(mt_fast_path(payload))

        assert result is not None
        assert result["ok"] is True
        assert result["uid"] == "uid-standup"
