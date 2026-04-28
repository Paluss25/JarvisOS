"""Failing tests for the sync_training_week MCP tool (P2.T1).

These tests are written before the implementation exists (P2.T2).
They will fail with KeyError / StopIteration until the tool is registered.
"""
import asyncio
import datetime
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ---------------------------------------------------------------------------
# Mock heavy optional deps that are not installed in the test venv.
# Must happen before any agent_runner import, because agent_runner/__init__.py
# imports client.py which imports telemetry.py which requires opentelemetry
# and prometheus_client.
# ---------------------------------------------------------------------------
if "opentelemetry" not in sys.modules:
    _otel_mock = MagicMock()
    _otel_trace_mock = MagicMock()
    _otel_trace_mock.StatusCode = type("StatusCode", (), {"ERROR": "ERROR", "OK": "OK"})
    sys.modules["opentelemetry"] = _otel_mock
    sys.modules["opentelemetry.trace"] = _otel_trace_mock
    sys.modules["opentelemetry.sdk"] = MagicMock()
    sys.modules["opentelemetry.sdk.trace"] = MagicMock()
    sys.modules["opentelemetry.exporter"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp.proto"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp.proto.grpc"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = MagicMock()
    sys.modules["opentelemetry.instrumentation"] = MagicMock()

if "prometheus_client" not in sys.modules:
    _prom_mock = MagicMock()
    _prom_mock.Counter = MagicMock(return_value=MagicMock())
    _prom_mock.Gauge = MagicMock(return_value=MagicMock())
    _prom_mock.Histogram = MagicMock(return_value=MagicMock())
    sys.modules["prometheus_client"] = _prom_mock

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_UTC = datetime.timezone.utc

# Week 21 / 2026:
#   day_of_week=0 (Monday)  → May 18, 2026
#   day_of_week=1 (Tuesday) → May 19, 2026
_W21_MON = datetime.date(2026, 5, 18)
_W21_TUE = datetime.date(2026, 5, 19)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _find_tool(server, name: str):
    """Return the tool function registered under *name* in the MCP server."""
    for tool in server._tools:
        if tool.name == name:
            return tool.fn
    raise KeyError(f"Tool '{name}' not registered")


def _make_row(
    session_type="run",
    day_of_week=0,
    planned_duration=45,
    notes="",
    created_at=None,
):
    return {
        "session_type": session_type,
        "day_of_week": day_of_week,
        "planned_duration": planned_duration,
        "notes": notes,
        "created_at": created_at or datetime.datetime(2026, 5, 1, 0, 0, 0, tzinfo=_UTC),
    }


def _make_asyncpg_mock(rows):
    """Return a mock asyncpg connection that returns *rows* from .fetch()."""
    conn = AsyncMock()
    conn.fetch.return_value = rows
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    mock_connect = AsyncMock(return_value=conn)
    return mock_connect


def _make_calendar_mock():
    cal = MagicMock()
    # Synchronous — called via asyncio.to_thread in the tool, not awaited directly
    cal._ensure_calendar = MagicMock(
        return_value="https://cal.prova9x.com/paluss/TrainingPlan/"
    )
    cal.upsert_event = MagicMock()
    return cal


async def _fake_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def _get_sync_fn():
    """Build the MT MCP server and extract the sync_training_week tool function.

    Server must be built inside the patch context so CalendarClient is mocked
    at construction time.
    """
    from agents.mt.tools import create_mt_mcp_server

    server = create_mt_mcp_server(Path("/tmp"))
    return _find_tool(server, "sync_training_week")


_BASE_ENV = {
    "SPORT_POSTGRES_URL": "postgresql://test",
    "RADICALE_TRAINING_CALENDAR": "TrainingPlan",
    # Required by _get_calendar_client so it does not return None
    "RADICALE_URL": "https://cal.prova9x.com",
    "RADICALE_USER": "paluss",
    "RADICALE_PASSWORD": "secret",
}


# ---------------------------------------------------------------------------
# Test 1 — run session creates an iCal event
# ---------------------------------------------------------------------------

def test_run_session_creates_event():
    """A single 'run' session must produce one upsert_event call with correct iCal."""
    rows = [_make_row(session_type="run", day_of_week=0, planned_duration=45)]
    cal = _make_calendar_mock()

    import agents.mt.tools as tools_mod

    with (
        patch.dict(os.environ, _BASE_ENV, clear=False),
        patch("asyncpg.connect", _make_asyncpg_mock(rows)),
        patch.object(tools_mod, "CalendarClient", return_value=cal),
        patch("asyncio.to_thread", side_effect=_fake_to_thread),
    ):
        fn = _get_sync_fn()
        result = _run(fn({"week_number": 21, "year": 2026}))

    cal.upsert_event.assert_called_once()
    _call = cal.upsert_event.call_args
    uid_arg = _call.args[1]   # upsert_event(calendar_url, uid, ical_data)
    ical_arg = _call.args[2]

    assert uid_arg == "training-2026w21d0", f"Unexpected UID: {uid_arg!r}"
    assert "DTSTART;TZID=Europe/Rome:20260518T180000" in ical_arg, ical_arg
    assert "DTEND;TZID=Europe/Rome:20260518T184500" in ical_arg, ical_arg
    assert "SUMMARY:🏃 Run" in ical_arg or "SUMMARY:\U0001f3c3 Run" in ical_arg, ical_arg

    assert result["synced"] == 1
    assert result["skipped"] == 0


# ---------------------------------------------------------------------------
# Test 2 — strength_metabolic session has correct title
# ---------------------------------------------------------------------------

def test_strength_metabolic_title():
    """session_type='strength_metabolic' must produce SUMMARY with strength label."""
    rows = [_make_row(session_type="strength_metabolic", day_of_week=1, planned_duration=60)]
    cal = _make_calendar_mock()

    import agents.mt.tools as tools_mod

    with (
        patch.dict(os.environ, _BASE_ENV, clear=False),
        patch("asyncpg.connect", _make_asyncpg_mock(rows)),
        patch.object(tools_mod, "CalendarClient", return_value=cal),
        patch("asyncio.to_thread", side_effect=_fake_to_thread),
    ):
        fn = _get_sync_fn()
        _run(fn({"week_number": 21, "year": 2026}))

    _call = cal.upsert_event.call_args
    ical_arg = _call.args[2]   # upsert_event(calendar_url, uid, ical_data)
    assert "Strength" in ical_arg and "Metabolic" in ical_arg, (
        f"Expected 'Strength & Metabolic' in SUMMARY, got: {ical_arg!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — rest session is skipped
# ---------------------------------------------------------------------------

def test_rest_session_skipped():
    """session_type='rest' must be skipped: upsert_event not called, skipped=1."""
    rows = [_make_row(session_type="rest", day_of_week=0, planned_duration=60)]
    cal = _make_calendar_mock()

    import agents.mt.tools as tools_mod

    with (
        patch.dict(os.environ, _BASE_ENV, clear=False),
        patch("asyncpg.connect", _make_asyncpg_mock(rows)),
        patch.object(tools_mod, "CalendarClient", return_value=cal),
        patch("asyncio.to_thread", side_effect=_fake_to_thread),
    ):
        fn = _get_sync_fn()
        result = _run(fn({"week_number": 21, "year": 2026}))

    cal.upsert_event.assert_not_called()
    assert result["synced"] == 0
    assert result["skipped"] == 1


# ---------------------------------------------------------------------------
# Test 4 — zero-duration session is skipped
# ---------------------------------------------------------------------------

def test_zero_duration_skipped():
    """planned_duration=0 must be skipped even when session_type is not 'rest'."""
    rows = [_make_row(session_type="run", day_of_week=0, planned_duration=0)]
    cal = _make_calendar_mock()

    import agents.mt.tools as tools_mod

    with (
        patch.dict(os.environ, _BASE_ENV, clear=False),
        patch("asyncpg.connect", _make_asyncpg_mock(rows)),
        patch.object(tools_mod, "CalendarClient", return_value=cal),
        patch("asyncio.to_thread", side_effect=_fake_to_thread),
    ):
        fn = _get_sync_fn()
        result = _run(fn({"week_number": 21, "year": 2026}))

    cal.upsert_event.assert_not_called()
    assert result["synced"] == 0
    assert result["skipped"] == 1


# ---------------------------------------------------------------------------
# Test 5 — empty DB returns zero counts
# ---------------------------------------------------------------------------

def test_no_sessions_returns_zero():
    """Empty training_plan table must return synced=0, skipped=0."""
    cal = _make_calendar_mock()

    import agents.mt.tools as tools_mod

    with (
        patch.dict(os.environ, _BASE_ENV, clear=False),
        patch("asyncpg.connect", _make_asyncpg_mock([])),
        patch.object(tools_mod, "CalendarClient", return_value=cal),
        patch("asyncio.to_thread", side_effect=_fake_to_thread),
    ):
        fn = _get_sync_fn()
        result = _run(fn({"week_number": 21, "year": 2026}))

    assert result.get("synced", 0) == 0
    assert result.get("skipped", 0) == 0


# ---------------------------------------------------------------------------
# Test 6 — DB error returns error dict
# ---------------------------------------------------------------------------

def test_db_error_returns_error_dict():
    """A connection failure must return a dict with 'error' key, no calendar writes."""
    cal = _make_calendar_mock()

    import agents.mt.tools as tools_mod

    broken_connect = AsyncMock(side_effect=Exception("db down"))

    with (
        patch.dict(os.environ, _BASE_ENV, clear=False),
        patch("asyncpg.connect", broken_connect),
        patch.object(tools_mod, "CalendarClient", return_value=cal),
        patch("asyncio.to_thread", side_effect=_fake_to_thread),
    ):
        fn = _get_sync_fn()
        result = _run(fn({"week_number": 21, "year": 2026}))

    assert "error" in result, f"Expected 'error' key in result, got: {result!r}"
    cal.upsert_event.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7 — _ensure_calendar called with calendar name
# ---------------------------------------------------------------------------

def test_ensure_calendar_called_on_first_sync():
    """_ensure_calendar must be called with the configured calendar name."""
    rows = [_make_row(session_type="run", day_of_week=0, planned_duration=45)]
    cal = _make_calendar_mock()

    import agents.mt.tools as tools_mod

    with (
        patch.dict(os.environ, _BASE_ENV, clear=False),
        patch("asyncpg.connect", _make_asyncpg_mock(rows)),
        patch.object(tools_mod, "CalendarClient", return_value=cal),
        patch("asyncio.to_thread", side_effect=_fake_to_thread),
    ):
        fn = _get_sync_fn()
        _run(fn({"week_number": 21, "year": 2026}))

    cal._ensure_calendar.assert_called_once_with("TrainingPlan")


# ---------------------------------------------------------------------------
# Test 8 — year falls back to created_at year when not provided
# ---------------------------------------------------------------------------

def test_year_from_created_at():
    """When year is 0/missing, the tool must derive it from row['created_at']."""
    rows = [
        _make_row(
            session_type="run",
            day_of_week=0,
            planned_duration=45,
            created_at=datetime.datetime(2025, 12, 1, tzinfo=_UTC),
        )
    ]
    cal = _make_calendar_mock()

    import agents.mt.tools as tools_mod

    with (
        patch.dict(os.environ, _BASE_ENV, clear=False),
        patch("asyncpg.connect", _make_asyncpg_mock(rows)),
        patch.object(tools_mod, "CalendarClient", return_value=cal),
        patch("asyncio.to_thread", side_effect=_fake_to_thread),
    ):
        fn = _get_sync_fn()
        result = _run(fn({"week_number": 1}))

    assert result.get("year") == 2025, (
        f"Expected year=2025 derived from created_at, got: {result.get('year')!r}"
    )
