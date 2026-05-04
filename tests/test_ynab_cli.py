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

runner = CliRunner()  # stderr mixed into output by default in this Click/Typer version


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


# ---------------------------------------------------------------------------
# Categories / Payees / Months
# ---------------------------------------------------------------------------

def test_categories_list(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "grp-1", "name": "Necessities"}], "category_groups")
    with patch("tools.ynab_cli.httpx.get", return_value=fake):
        result = runner.invoke(app, ["categories", "list"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out[0]["id"] == "grp-1"


def test_categories_update_month(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "cat-1", "budgeted": 200000}, "category")
    captured = {}
    def fake_patch(url, json=None, **kwargs):
        captured["body"] = json
        captured["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.patch", side_effect=fake_patch):
        result = runner.invoke(app, [
            "categories", "update-month", "cat-1",
            "--budgeted", "200.00",
            "--month", "2026-05-01",
        ])
    assert result.exit_code == 0
    assert captured["body"]["category"]["budgeted"] == 200000
    assert "2026-05-01" in captured["url"]
    assert "cat-1" in captured["url"]
    assert "/months/" in captured["url"]
    assert "/categories/" in captured["url"]


def test_categories_get(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "cat-1", "name": "Groceries"}, "category")
    captured_url = {}
    def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["categories", "get", "cat-1"])
    assert result.exit_code == 0
    assert "cat-1" in captured_url["url"]
    out = json.loads(result.output)
    assert out["id"] == "cat-1"


def test_payees_list(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "payee-1", "name": "Amazon"}], "payees")
    with patch("tools.ynab_cli.httpx.get", return_value=fake):
        result = runner.invoke(app, ["payees", "list"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out[0]["name"] == "Amazon"


def test_payees_update(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "payee-1", "name": "Esselunga"}, "payee")
    captured = {}
    def fake_patch(url, json=None, **kwargs):
        captured["url"] = url
        captured["body"] = json
        return fake
    with patch("tools.ynab_cli.httpx.patch", side_effect=fake_patch):
        result = runner.invoke(app, ["payees", "update", "payee-1", "--name", "Esselunga"])
    assert result.exit_code == 0
    assert "payee-1" in captured["url"]
    assert captured["body"]["payee"]["name"] == "Esselunga"


def test_months_get_current(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    expected_month = date.today().replace(day=1).isoformat()
    fake = _fake_resp({"month": expected_month, "income": 0}, "month")
    captured_url = {}
    def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["months", "get", "current"])
    assert result.exit_code == 0
    assert expected_month in captured_url["url"]
