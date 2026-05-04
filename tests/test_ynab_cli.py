"""Tests for YNAB CLI — src/tools/ynab_cli.py."""
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tools.ynab_cli import app, _milliunits

runner = CliRunner()


def _fake_resp(data, key=None, status_code=200):
    """Build a fake httpx.Response with is_success based on status_code."""
    body = {"data": {key: data}} if key else {"data": data}
    resp = MagicMock()
    resp.is_success = status_code < 400
    resp.status_code = status_code
    resp.text = json.dumps(body)
    resp.json.return_value = body
    return resp


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_milliunits_outflow():
    assert _milliunits(45.90, "outflow") == -45900


def test_milliunits_inflow():
    assert _milliunits(1500.0, "inflow") == 1500000


def test_milliunits_zero():
    assert _milliunits(0.0, "outflow") == 0


# ---------------------------------------------------------------------------
# Error path — YNAB_API_KEY not set
# ---------------------------------------------------------------------------

def test_error_no_api_key(monkeypatch):
    monkeypatch.delenv("YNAB_API_KEY", raising=False)
    result = runner.invoke(app, ["budgets", "list"])
    assert result.exit_code == 1
    err = json.loads(result.output)
    assert "YNAB_API_KEY" in err["error"]


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

def test_budgets_list(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "budget-123", "name": "Home"}], "budgets")
    with patch("tools.ynab_cli.httpx.get", return_value=fake):
        result = runner.invoke(app, ["budgets", "list"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out[0]["id"] == "budget-123"


def test_budgets_get(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "budget-123", "name": "Home"}, "budget")
    with patch("tools.ynab_cli.httpx.get", return_value=fake):
        result = runner.invoke(app, ["budgets", "get"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["id"] == "budget-123"


def test_accounts_list(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "acct-1", "name": "Fineco"}], "accounts")
    captured_url = {}
    def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["accounts", "list"])
    assert result.exit_code == 0
    assert "budget-123" in captured_url["url"]


def test_accounts_create(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "acct-new", "name": "Savings"}, "account")
    captured = {}
    def fake_post(url, json=None, **kwargs):
        captured["body"] = json
        return fake
    with patch("tools.ynab_cli.httpx.post", side_effect=fake_post):
        result = runner.invoke(app, [
            "accounts", "create",
            "--name", "Savings",
            "--type", "savings",
            "--balance", "1000.00",
        ])
    assert result.exit_code == 0
    assert captured["body"]["account"]["balance"] == 1000000
