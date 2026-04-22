"""Unit tests for EmailSorter httpx client."""
import json
from unittest.mock import MagicMock, patch

import pytest

import src.agents.cos.email_sorter as _mod
from src.agents.cos.email_sorter import sort_email_after_routing


def _mock_response(status_code: int, body: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.raise_for_status = MagicMock() if status_code < 400 else MagicMock(side_effect=Exception("HTTP error"))
    return resp


def test_sort_returns_sorted_true():
    payload = {
        "email_id": "42",
        "subject": "Fattura n.1",
        "body_redacted": "importo dovuto 100 EUR",
        "classification": {"primary_domain": "finance", "priority": "normal", "sensitivity": "public"},
    }
    expected = {"sorted": True, "folder": "Fatture", "uid": "42"}

    with patch.object(_mod.httpx, "post", return_value=_mock_response(200, expected)) as mock_post:
        result = sort_email_after_routing("42", payload)

    assert result["sorted"] is True
    assert result["folder"] == "Fatture"
    call_kwargs = mock_post.call_args
    sent = call_kwargs[1]["json"] if call_kwargs[1] else call_kwargs[0][1]
    assert sent["uid"] == "42"


def test_sort_returns_no_match():
    payload = {"email_id": "7", "subject": "Hello", "body_redacted": "", "classification": {}}
    expected = {"sorted": False, "reason": "no rule matched"}

    with patch.object(_mod.httpx, "post", return_value=_mock_response(200, expected)):
        result = sort_email_after_routing("7", payload)

    assert result["sorted"] is False


def test_sort_http_failure_does_not_raise():
    payload = {"email_id": "99", "subject": "", "body_redacted": "", "classification": {}}

    with patch.object(_mod.httpx, "post", side_effect=Exception("Connection refused")):
        result = sort_email_after_routing("99", payload)

    assert result["sorted"] is False
    assert "error" in result
