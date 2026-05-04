"""Unit tests for mailctl-backed COS EmailSorter."""

import json
from unittest.mock import patch

import agents.cos.email_sorter as _mod
from agents.cos.email_sorter import sort_email_after_routing


class _Process:
    def __init__(self, returncode: int, body: dict | None = None, stderr: str = ""):
        self.returncode = returncode
        self.stdout = json.dumps(body or {})
        self.stderr = stderr


def test_sort_returns_sorted_true():
    payload = {
        "email_id": "42",
        "account": "protonmail",
        "subject": "Fattura n.1",
        "body_redacted": "importo dovuto 100 EUR",
        "classification": {"primary_domain": "finance", "priority": "normal", "sensitivity": "public"},
    }
    expected = {"sorted": True, "folder": "Fatture", "uid": "42"}

    with patch.object(_mod.subprocess, "run", return_value=_Process(0, expected)) as mock_run:
        result = sort_email_after_routing("42", payload)

    assert result["sorted"] is True
    assert result["folder"] == "Fatture"
    assert mock_run.call_args.args[0] == ["mailctl", "sort", "--account", "protonmail", "--uid", "42", "--json"]


def test_sort_uses_gmx_and_strips_prefixed_uid():
    payload = {"email_id": "gmx-7", "account": "gmx", "subject": "Hello", "body_redacted": "", "classification": {}}
    expected = {"sorted": False, "reason": "no_rule_matched"}

    with patch.object(_mod.subprocess, "run", return_value=_Process(0, expected)) as mock_run:
        result = sort_email_after_routing("gmx-7", payload)

    assert result["sorted"] is False
    assert mock_run.call_args.args[0] == ["mailctl", "sort", "--account", "gmx", "--uid", "7", "--json"]


def test_sort_cli_failure_does_not_raise():
    payload = {"email_id": "99", "subject": "", "body_redacted": "", "classification": {}}

    with patch.object(_mod.subprocess, "run", return_value=_Process(1, stderr="Connection refused")):
        result = sort_email_after_routing("99", payload)

    assert result["sorted"] is False
    assert "error" in result
