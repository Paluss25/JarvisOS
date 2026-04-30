"""Tests for the 5 MT contacts MCP tools."""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _find_tool(server, name: str):
    for tool in server._tools:
        if tool.name == name:
            return tool.fn
    raise KeyError(f"Tool '{name}' not registered")


def _build_server(workspace, monkeypatch, mock_client=None):
    from agents.mt.tools import create_mt_mcp_server
    if mock_client is None:
        mock_client = MagicMock()
    monkeypatch.setattr("agents.mt.tools.ContactsClient", lambda **kw: mock_client)
    server = create_mt_mcp_server(workspace)
    return server, mock_client


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

def test_contacts_tools_return_not_configured_when_url_missing(tmp_path):
    env_backup = os.environ.pop("RADICALE_URL", None)
    try:
        from agents.mt.tools import create_mt_mcp_server
        server = create_mt_mcp_server(tmp_path)
        for tool_name in ["contacts_list", "contacts_search", "contacts_get", "contacts_update", "contacts_delete"]:
            fn = _find_tool(server, tool_name)
            result = _run(fn({}))
            assert "not configured" in result["content"][0]["text"].lower()
    finally:
        if env_backup is not None:
            os.environ["RADICALE_URL"] = env_backup


# ---------------------------------------------------------------------------
# contacts_list
# ---------------------------------------------------------------------------

def test_contacts_list_returns_contacts(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.list_contacts.return_value = [
        {"uid": "c-1", "fn": "Alice Example", "email": "alice@example.com", "tel": "", "note": ""}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_list")

    result = _run(fn({}))
    assert "Alice Example" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# contacts_search
# ---------------------------------------------------------------------------

def test_contacts_search_returns_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.search_contacts.return_value = [
        {"uid": "c-2", "fn": "Bob Builder", "email": "bob@example.com", "tel": "", "note": ""}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_search")

    result = _run(fn({"query": "bob"}))
    assert "Bob Builder" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# contacts_get
# ---------------------------------------------------------------------------

def test_contacts_get_returns_contact(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.get_contact.return_value = {
        "uid": "c-3", "fn": "Carol Dev", "email": "carol@example.com", "tel": "+39111", "note": "VIP"
    }
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_get")

    result = _run(fn({"uid": "c-3"}))
    assert "Carol Dev" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# contacts_update — confirmation gate
# ---------------------------------------------------------------------------

def test_contacts_update_does_not_write_when_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_update")

    result = _run(fn({"uid": "c-4", "fn": "New Name", "confirmed": False}))
    mock_client.update_contact.assert_not_called()
    text = result["content"][0]["text"].lower()
    assert "ready" in text or "confirm" in text


def test_contacts_update_writes_when_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_update")

    result = _run(fn({"uid": "c-4", "fn": "New Name", "confirmed": True}))
    mock_client.update_contact.assert_called_once()
    assert "updated" in result["content"][0]["text"].lower()


# ---------------------------------------------------------------------------
# contacts_delete — confirmation gate
# ---------------------------------------------------------------------------

def test_contacts_delete_does_not_delete_when_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_delete")

    _run(fn({"uid": "c-5", "confirmed": False}))
    mock_client.delete_contact.assert_not_called()


def test_contacts_delete_deletes_when_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_delete")

    _run(fn({"uid": "c-5", "confirmed": True}))
    mock_client.delete_contact.assert_called_once_with("c-5")
