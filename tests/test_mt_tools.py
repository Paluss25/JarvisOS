"""Tests for MT agent helpers and email_sorter client."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def _mock_response(status_code: int, body: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    if status_code >= 400:
        resp.raise_for_status = MagicMock(side_effect=Exception("HTTP error"))
    else:
        resp.raise_for_status = MagicMock()
    return resp


def test_sort_email_returns_result():
    payload = {
        "sender": "noreply@example.com",
        "subject": "Newsletter",
        "body_redacted": "This week in tech...",
        "classification": {"primary_domain": "newsletter"},
    }
    expected = {"sorted": True, "folder": "INBOX/Archive"}
    with patch.object(sorter_mod.httpx, "post", return_value=_mock_response(200, expected)):
        result = sort_email("42", payload)
    assert result["sorted"] is True
    assert result["folder"] == "INBOX/Archive"


def test_sort_email_raises_on_http_error():
    payload = {"sender": "", "subject": "", "body_redacted": "", "classification": {}}
    with patch.object(sorter_mod.httpx, "post", return_value=_mock_response(500, {})):
        with pytest.raises(Exception, match="HTTP error"):
            sort_email("bad", payload)
