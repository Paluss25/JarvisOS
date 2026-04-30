"""Tests for the 5 MT contacts MCP tools."""
import os
from unittest.mock import MagicMock

import pytest


def _find_tool(server, name: str):
    for tool in server._tools:
        if tool.name == name:
            return tool.fn
    raise KeyError(f"Tool '{name}' not registered")


async def _call_in_process(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def _build_server(workspace, monkeypatch, mock_client=None):
    from agents.mt.tools import create_mt_mcp_server
    import agents.mt.tools as tools_mod

    if mock_client is None:
        mock_client = MagicMock()
    monkeypatch.setattr(tools_mod, "ContactsClient", lambda **kw: mock_client)
    monkeypatch.setattr(tools_mod.asyncio, "to_thread", _call_in_process)
    server = create_mt_mcp_server(workspace)
    return server, mock_client


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contacts_tools_return_not_configured_when_url_missing(tmp_path):
    env_backup = os.environ.pop("RADICALE_URL", None)
    try:
        from agents.mt.tools import create_mt_mcp_server
        server = create_mt_mcp_server(tmp_path)
        for tool_name in ["contacts_list", "contacts_search", "contacts_get", "contacts_update", "contacts_delete"]:
            fn = _find_tool(server, tool_name)
            result = await fn({})
            assert "not configured" in result["content"][0]["text"].lower()
    finally:
        if env_backup is not None:
            os.environ["RADICALE_URL"] = env_backup


# ---------------------------------------------------------------------------
# contacts_list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contacts_list_returns_contacts(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.list_contacts.return_value = [
        {"uid": "c-1", "fn": "Alice Example", "email": "alice@example.com", "tel": "", "note": ""}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_list")

    result = await fn({})
    assert "Alice Example" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# contacts_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contacts_search_returns_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.search_contacts.return_value = [
        {"uid": "c-2", "fn": "Bob Builder", "email": "bob@example.com", "tel": "", "note": ""}
    ]
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_search")

    result = await fn({"query": "bob"})
    assert "Bob Builder" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# contacts_get
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contacts_get_returns_contact(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    mock_client.get_contact.return_value = {
        "uid": "c-3", "fn": "Carol Dev", "email": "carol@example.com", "tel": "+39111", "note": "VIP"
    }
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_get")

    result = await fn({"uid": "c-3"})
    assert "Carol Dev" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# contacts_update — confirmation gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contacts_update_does_not_write_when_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_update")

    result = await fn({"uid": "c-4", "fn": "New Name", "confirmed": False})
    mock_client.update_contact.assert_not_called()
    text = result["content"][0]["text"].lower()
    assert "ready" in text or "confirm" in text


@pytest.mark.asyncio
async def test_contacts_update_writes_when_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_update")

    result = await fn({"uid": "c-4", "fn": "New Name", "confirmed": True})
    mock_client.update_contact.assert_called_once()
    assert "updated" in result["content"][0]["text"].lower()


# ---------------------------------------------------------------------------
# contacts_delete — confirmation gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contacts_delete_does_not_delete_when_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_delete")

    await fn({"uid": "c-5", "confirmed": False})
    mock_client.delete_contact.assert_not_called()


@pytest.mark.asyncio
async def test_contacts_delete_deletes_when_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("RADICALE_URL", "https://cal.prova9x.com")
    monkeypatch.setenv("RADICALE_USER", "paluss")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")

    mock_client = MagicMock()
    server, _ = _build_server(tmp_path, monkeypatch, mock_client)
    fn = _find_tool(server, "contacts_delete")

    await fn({"uid": "c-5", "confirmed": True})
    mock_client.delete_contact.assert_called_once_with("c-5")
