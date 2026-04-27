"""Tests for the 5 MT calendar MCP tools registered in create_mt_mcp_server()."""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


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


def _build_server(workspace, monkeypatch_or_none=None, mock_client=None):
    """Build MT MCP server; optionally inject a mock CalendarClient.

    Uses monkeypatch.setattr so the patch stays alive for the entire test,
    not just the server-construction call.
    """
    from agents.mt.tools import create_mt_mcp_server
    import agents.mt.tools as tools_mod

    if mock_client is None:
        mock_client = MagicMock()

    if monkeypatch_or_none is not None:
        monkeypatch_or_none.setattr(tools_mod, "CalendarClient", MagicMock(return_value=mock_client))

    server = create_mt_mcp_server(workspace)
    return server, mock_client


# ---------------------------------------------------------------------------
# Graceful degradation — no RADICALE_URL
# ---------------------------------------------------------------------------

def test_calendar_tools_return_not_configured_when_url_missing(tmp_path):
    """All calendar tools must degrade gracefully when RADICALE_URL is absent."""
    env_backup = os.environ.pop("RADICALE_URL", None)
    try:
        from agents.mt.tools import create_mt_mcp_server
        server = create_mt_mcp_server(tmp_path)
        for tool_name in [
            "calendar_list",
            "calendar_get_events",
            "calendar_create_event",
            "calendar_update_event",
            "calendar_delete_event",
        ]:
            fn = _find_tool(server, tool_name)
            result = _run(fn({}))
            assert "not configured" in result["content"][0]["text"].lower(), (
                f"{tool_name} should report 'not configured' when RADICALE_URL missing"
            )
    finally:
        if env_backup is not None:
            os.environ["RADICALE_URL"] = env_backup


# ---------------------------------------------------------------------------
# calendar_list
# ---------------------------------------------------------------------------

def test_calendar_list_returns_calendars(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.list_calendars.return_value = [
        {"name": "personal", "url": "https://cal.prova9x.com/paluss/personal/"}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_list")

    result = _run(fn({}))
    text = result["content"][0]["text"]
    assert "personal" in text


# ---------------------------------------------------------------------------
# calendar_get_events
# ---------------------------------------------------------------------------

def test_calendar_get_events_returns_event_list(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.get_events.return_value = [
        {"uid": "uid-1", "summary": "Dentist", "start": "2026-04-28T15:00:00", "end": "2026-04-28T16:00:00", "description": ""}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_get_events")

    result = _run(fn({"start_date": "2026-04-28", "end_date": "2026-04-28"}))
    text = result["content"][0]["text"]
    assert "Dentist" in text


# ---------------------------------------------------------------------------
# calendar_create_event — confirmation gate
# ---------------------------------------------------------------------------

def test_calendar_create_event_does_not_write_when_unconfirmed(tmp_path, monkeypatch):
    """confirmed=False must never call client.create_event."""
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.check_conflicts.return_value = []
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_create_event")

    result = _run(fn({
        "title": "Team Sync",
        "start_datetime": "2026-04-28T15:00:00Z",
        "end_datetime": "2026-04-28T16:00:00Z",
        "description": "",
        "confirmed": False,
    }))
    mock_client.create_event.assert_not_called()
    assert "ready to create" in result["content"][0]["text"].lower() or \
           "confirm" in result["content"][0]["text"].lower()


def test_calendar_create_event_writes_when_confirmed_no_conflicts(tmp_path, monkeypatch):
    """confirmed=True + no conflicts must call client.create_event and return uid."""
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.check_conflicts.return_value = []
    mock_client.create_event.return_value = "new-uid-123"
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_create_event")

    result = _run(fn({
        "title": "Team Sync",
        "start_datetime": "2026-04-28T15:00:00Z",
        "end_datetime": "2026-04-28T16:00:00Z",
        "description": "",
        "confirmed": True,
    }))
    mock_client.create_event.assert_called_once()
    assert "new-uid-123" in result["content"][0]["text"]


def test_calendar_create_event_blocks_on_conflict(tmp_path, monkeypatch):
    """confirmed=True must still block and return conflict list if conflicts found."""
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.check_conflicts.return_value = [
        {"uid": "conflict-1", "summary": "Existing Meeting", "start": "2026-04-28T15:00:00Z", "end": "2026-04-28T16:00:00Z"}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_create_event")

    result = _run(fn({
        "title": "New Meeting",
        "start_datetime": "2026-04-28T15:00:00Z",
        "end_datetime": "2026-04-28T16:00:00Z",
        "description": "",
        "confirmed": True,
    }))
    mock_client.create_event.assert_not_called()
    assert "conflict" in result["content"][0]["text"].lower()
    assert "Existing Meeting" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# calendar_delete_event — confirmation gate
# ---------------------------------------------------------------------------

def test_calendar_delete_event_does_not_delete_when_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_delete_event")

    _run(fn({"uid": "uid-to-delete", "confirmed": False}))
    mock_client.delete_event.assert_not_called()


def test_calendar_delete_event_deletes_when_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_delete_event")

    _run(fn({"uid": "uid-to-delete", "confirmed": True}))
    mock_client.delete_event.assert_called_once_with("uid-to-delete")
