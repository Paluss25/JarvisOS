"""Tests for MT agent helpers and email_sorter client."""
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agents.mt.tools import (
    _mark_processed,
    _read_processed_ids,
    _read_digest,
    _task_create,
    _task_list,
)
import agents.mt.email_sorter as sorter_mod
from agents.mt.email_sorter import sort_email


def _tool(server, name):
    for entry in server._tools:
        if entry.name == name:
            return entry
    raise AssertionError(f"tool not registered: {name}")


class _RedisStub:
    _config = None

    def on_message(self, _callback):
        return None


def test_read_processed_ids_empty(tmp_path):
    assert _read_processed_ids(tmp_path) == set()


def test_mark_and_read_processed(tmp_path):
    _mark_processed(tmp_path, "uid-1")
    _mark_processed(tmp_path, "uid-2")
    assert _read_processed_ids(tmp_path) == {"uid-1", "uid-2"}


def test_read_digest_returns_unprocessed(tmp_path):
    digest = tmp_path / "mt_digest.json"
    digest.write_text(
        json.dumps({"email_id": "1", "mt_action_hint": "archive"}) + "\n" +
        json.dumps({"email_id": "2", "mt_action_hint": "draft_reply"}) + "\n",
        encoding="utf-8",
    )
    items = _read_digest(digest, {"1"})
    assert len(items) == 1
    assert items[0]["email_id"] == "2"


def test_task_helpers(tmp_path):
    task = _task_create(tmp_path, "Review invoice", notes="Q1 2026", due_date="2026-05-01")
    assert task["title"] == "Review invoice"
    assert task["status"] == "open"
    tasks = _task_list(tmp_path, status="open")
    assert len(tasks) == 1
    assert tasks[0]["id"] == task["id"]


@pytest.mark.asyncio
async def test_create_task_marks_source_email_processed(tmp_path):
    from agents.mt.tools import create_mt_mcp_server

    server = create_mt_mcp_server(tmp_path)
    create_task = _tool(server, "create_task").fn

    response = await create_task({
        "title": "Amazon rata 76,96 EUR",
        "notes": "Digest item from pm-437",
        "due_date": "2026-05-12",
        "email_id": "pm-437",
        "account": "protonmail",
        "received_at": "2026-05-07T01:29:20Z",
    })

    assert response["content"][0]["text"]
    processed = _read_processed_ids(tmp_path)
    assert "pm-437" in processed
    assert "protonmail|pm-437|2026-05-07T01:29:20Z" in processed


@pytest.mark.asyncio
async def test_create_task_extracts_email_id_from_notes_when_missing(tmp_path):
    from agents.mt.tools import create_mt_mcp_server

    server = create_mt_mcp_server(tmp_path)
    create_task = _tool(server, "create_task").fn

    await create_task({
        "title": "xAI invoice",
        "notes": "Verificare fattura xAI API 04/2026 (pm-339)",
    })

    assert "pm-339" in _read_processed_ids(tmp_path)


@pytest.mark.asyncio
async def test_forward_to_cos_sends_telegram_alert_for_aruba_spid(tmp_path, monkeypatch):
    from agents.mt import tools as mt_tools

    fake_send_message = types.SimpleNamespace(
        create_send_message_tool=lambda *_args, **_kw: AsyncMock(return_value="cos-ok")
    )
    monkeypatch.setitem(sys.modules, "agent_runner.tools.send_message", fake_send_message)
    notifier = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(mt_tools, "_send_cos_security_telegram_alert", notifier)

    server = mt_tools.create_mt_mcp_server(tmp_path, redis_a2a=_RedisStub())
    forward_to_cos = _tool(server, "forward_to_cos").fn
    payload = {
        "email_id": "pm-171",
        "sender": "Aruba ID <comunicazioni@staff.aruba.it>",
        "subject": "SPID Aruba ID - Modifica la tua password",
        "received_at": "2026-04-25T13:07:47+02:00",
    }

    await forward_to_cos({"payload_json": json.dumps(payload), "reason": "SPID security alert"})

    notifier.assert_awaited_once_with(payload)


def _mock_response(status_code: int, body: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    if status_code >= 400:
        resp.raise_for_status = MagicMock(side_effect=Exception("HTTP error"))
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _mock_completed_process(returncode: int, stdout: str = "", stderr: str = ""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_sort_email_returns_result():
    payload = {
        "sender": "noreply@example.com",
        "subject": "Newsletter",
        "body_redacted": "This week in tech...",
        "classification": {"primary_domain": "newsletter"},
    }
    expected = {"sorted": True, "folder": "INBOX/Archive"}
    with patch.object(
        sorter_mod.subprocess,
        "run",
        return_value=_mock_completed_process(0, json.dumps(expected)),
    ) as run_mock:
        result = sort_email("42", payload)
    run_mock.assert_called_once()
    assert run_mock.call_args.args[0][:5] == ["mailctl", "sort", "--account", "protonmail", "--uid"]
    assert result["sorted"] is True
    assert result["folder"] == "INBOX/Archive"


def test_sort_email_strips_protonmail_alias_and_ordinal_suffix():
    payload = {"account": "protonmail", "subject": "Newsletter", "classification": {}}
    expected = {"sorted": True, "folder": "INBOX/Archive"}
    with patch.object(
        sorter_mod.subprocess,
        "run",
        return_value=_mock_completed_process(0, json.dumps(expected)),
    ) as run_mock:
        result = sort_email("pm-374°", payload)

    assert result["sorted"] is True
    assert run_mock.call_args.args[0] == [
        "mailctl",
        "sort",
        "--account",
        "protonmail",
        "--uid",
        "374",
        "--json",
    ]


def test_sort_email_strips_gmx_alias_and_ordinal_suffix():
    payload = {"account": "gmx", "subject": "Newsletter", "classification": {}}
    expected = {"sorted": True, "folder": "Archive"}
    with patch.object(
        sorter_mod.subprocess,
        "run",
        return_value=_mock_completed_process(0, json.dumps(expected)),
    ) as run_mock:
        result = sort_email("gmx-317°", payload)

    assert result["sorted"] is True
    assert run_mock.call_args.args[0] == [
        "mailctl",
        "sort",
        "--account",
        "gmx",
        "--uid",
        "317",
        "--json",
    ]


def test_sort_email_raises_on_http_error():
    payload = {"sender": "", "subject": "", "body_redacted": "", "classification": {}}
    with patch.object(
        sorter_mod.subprocess,
        "run",
        return_value=_mock_completed_process(1, stderr="mailctl failed"),
    ):
        with pytest.raises(RuntimeError, match="mailctl sort failed"):
            sort_email("bad", payload)
