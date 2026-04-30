"""Tests for the 5 MT calendar MCP tools registered in create_mt_mcp_server()."""
import os
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_tool(server, name: str):
    """Return the tool function registered under *name* in the MCP server."""
    for tool in server._tools:
        if tool.name == name:
            return tool.fn
    raise KeyError(f"Tool '{name}' not registered")


async def _call_in_process(fn, *args, **kwargs):
    return fn(*args, **kwargs)


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
        monkeypatch_or_none.setattr(tools_mod.asyncio, "to_thread", _call_in_process)

    server = create_mt_mcp_server(workspace)
    return server, mock_client


# ---------------------------------------------------------------------------
# Graceful degradation — no RADICALE_URL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_tools_return_not_configured_when_url_missing(tmp_path):
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
            result = await fn({})
            assert "not configured" in result["content"][0]["text"].lower(), (
                f"{tool_name} should report 'not configured' when RADICALE_URL missing"
            )
    finally:
        if env_backup is not None:
            os.environ["RADICALE_URL"] = env_backup


# ---------------------------------------------------------------------------
# calendar_list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_list_returns_calendars(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.list_calendars.return_value = [
        {"name": "personal", "url": "https://cal.prova9x.com/paluss/personal/"}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_list")

    result = await fn({})
    text = result["content"][0]["text"]
    assert "personal" in text


# ---------------------------------------------------------------------------
# calendar_get_events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_get_events_returns_event_list(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.get_events.return_value = [
        {"uid": "uid-1", "summary": "Dentist", "start": "2026-04-28T15:00:00", "end": "2026-04-28T16:00:00", "description": ""}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_get_events")

    result = await fn({"start_date": "2026-04-28", "end_date": "2026-04-28"})
    text = result["content"][0]["text"]
    assert "Dentist" in text


# ---------------------------------------------------------------------------
# calendar_create_event — confirmation gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_create_event_does_not_write_when_unconfirmed(tmp_path, monkeypatch):
    """confirmed=False must never call client.create_event."""
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.check_conflicts.return_value = []
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_create_event")

    result = await fn({
        "title": "Team Sync",
        "start_datetime": "2026-04-28T15:00:00Z",
        "end_datetime": "2026-04-28T16:00:00Z",
        "description": "",
        "confirmed": False,
    })
    mock_client.create_event.assert_not_called()
    assert "ready to create" in result["content"][0]["text"].lower() or \
           "confirm" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_calendar_create_event_writes_when_confirmed_no_conflicts(tmp_path, monkeypatch):
    """confirmed=True + no conflicts must call client.create_event and return uid."""
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.check_conflicts.return_value = []
    mock_client.create_event.return_value = "new-uid-123"
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_create_event")

    result = await fn({
        "title": "Team Sync",
        "start_datetime": "2026-04-28T15:00:00Z",
        "end_datetime": "2026-04-28T16:00:00Z",
        "description": "",
        "confirmed": True,
    })
    mock_client.create_event.assert_called_once()
    assert "new-uid-123" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_calendar_create_event_blocks_on_conflict(tmp_path, monkeypatch):
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

    result = await fn({
        "title": "New Meeting",
        "start_datetime": "2026-04-28T15:00:00Z",
        "end_datetime": "2026-04-28T16:00:00Z",
        "description": "",
        "confirmed": True,
    })
    mock_client.create_event.assert_not_called()
    assert "conflict" in result["content"][0]["text"].lower()
    assert "Existing Meeting" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# calendar_delete_event — confirmation gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_delete_event_does_not_delete_when_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_delete_event")

    await fn({"uid": "uid-to-delete", "confirmed": False})
    mock_client.delete_event.assert_not_called()


@pytest.mark.asyncio
async def test_calendar_delete_event_deletes_when_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_delete_event")

    await fn({"uid": "uid-to-delete", "confirmed": True})
    mock_client.delete_event.assert_called_once_with("uid-to-delete")


# ---------------------------------------------------------------------------
# calendar_update_event — confirmation gate + conflict self-exclusion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_update_event_does_not_write_when_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.check_conflicts.return_value = []
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_update_event")

    result = await fn({
        "uid": "uid-to-update",
        "title": "New Title",
        "start_datetime": "2026-04-29T10:00:00Z",
        "end_datetime": "2026-04-29T11:00:00Z",
        "description": "",
        "confirmed": False,
    })
    mock_client.update_event.assert_not_called()
    assert "ready to update" in result["content"][0]["text"].lower() or \
           "confirm" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_calendar_update_event_writes_when_confirmed_no_conflicts(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.check_conflicts.return_value = []
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_update_event")

    result = await fn({
        "uid": "uid-to-update",
        "title": "New Title",
        "start_datetime": "2026-04-29T10:00:00Z",
        "end_datetime": "2026-04-29T11:00:00Z",
        "description": "",
        "confirmed": True,
    })
    mock_client.update_event.assert_called_once()
    assert "updated" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_calendar_update_event_excludes_self_from_conflict_check(tmp_path, monkeypatch):
    """The event being updated must not count as a conflict with itself."""
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    # check_conflicts returns the event itself — this must be filtered out
    mock_client.check_conflicts.return_value = [
        {"uid": "uid-to-update", "summary": "Self", "start": "2026-04-29T10:00:00Z", "end": "2026-04-29T11:00:00Z"}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "calendar_update_event")

    result = await fn({
        "uid": "uid-to-update",
        "title": "New Title",
        "start_datetime": "2026-04-29T10:00:00Z",
        "end_datetime": "2026-04-29T11:00:00Z",
        "description": "",
        "confirmed": True,
    })
    # The self-event should be excluded → no conflict → write should proceed
    mock_client.update_event.assert_called_once()
    assert "conflict" not in result["content"][0]["text"].lower()
