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


# ---------------------------------------------------------------------------
# Payee Locations
# ---------------------------------------------------------------------------

def test_payee_locations_list(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "loc-1", "payee_id": "payee-1"}], "payee_locations")
    with patch("tools.ynab_cli.httpx.get", return_value=fake):
        result = runner.invoke(app, ["payee-locations", "list"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out[0]["id"] == "loc-1"


def test_payee_locations_get(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "loc-1", "latitude": "45.46"}, "payee_location")
    with patch("tools.ynab_cli.httpx.get", return_value=fake):
        result = runner.invoke(app, ["payee-locations", "get", "loc-1"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["id"] == "loc-1"


def test_payee_locations_list_by_payee(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "loc-1"}], "payee_locations")
    captured_url = {}
    def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["payee-locations", "list-by-payee", "payee-99"])
    assert result.exit_code == 0
    assert "payees/payee-99/payee_locations" in captured_url["url"]


# ---------------------------------------------------------------------------
# Transactions — list / get / update / delete
# ---------------------------------------------------------------------------

def test_transactions_list_all(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "tx-1", "amount": -45900}], "transactions")
    with patch("tools.ynab_cli.httpx.get", return_value=fake):
        result = runner.invoke(app, ["transactions", "list"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out[0]["id"] == "tx-1"


def test_transactions_list_since(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([], "transactions")
    captured = {}
    def fake_get(url, params=None, **kwargs):
        captured["params"] = params
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["transactions", "list", "--since", "2026-05-01"])
    assert result.exit_code == 0
    assert captured["params"]["since_date"] == "2026-05-01"


def test_transactions_list_by_account(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([], "transactions")
    captured_url = {}
    def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["transactions", "list", "--account-id", "acct-1"])
    assert result.exit_code == 0
    assert "accounts/acct-1/transactions" in captured_url["url"]


def test_transactions_get(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "tx-1", "amount": -45900}, "transaction")
    captured_url = {}
    def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["transactions", "get", "tx-1"])
    assert result.exit_code == 0
    assert "tx-1" in captured_url["url"]
    out = json.loads(result.output)
    assert out["id"] == "tx-1"


def test_transactions_update(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "tx-1", "cleared": "cleared"}, "transaction")
    captured = {}
    def fake_put(url, json=None, **kwargs):
        captured["body"] = json
        return fake
    with patch("tools.ynab_cli.httpx.put", side_effect=fake_put):
        result = runner.invoke(app, ["transactions", "update", "tx-1", "--cleared", "cleared"])
    assert result.exit_code == 0
    assert captured["body"]["transaction"]["cleared"] == "cleared"


def test_transactions_update_no_fields(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    result = runner.invoke(app, ["transactions", "update", "tx-1"])
    assert result.exit_code == 1


def test_transactions_delete(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "tx-1", "deleted": True}, "transaction")
    captured_url = {}
    def fake_delete(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.delete", side_effect=fake_delete):
        result = runner.invoke(app, ["transactions", "delete", "tx-1"])
    assert result.exit_code == 0
    assert "tx-1" in captured_url["url"]


# ---------------------------------------------------------------------------
# Transactions — create / create-bulk
# ---------------------------------------------------------------------------

def test_transactions_create_outflow(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "tx-new", "amount": -45900}, "transaction")
    captured = {}
    def fake_post(url, json=None, **kwargs):
        captured["body"] = json
        return fake
    with patch("tools.ynab_cli.httpx.post", side_effect=fake_post):
        result = runner.invoke(app, [
            "transactions", "create",
            "--account-id", "acct-1",
            "--date", "2026-05-04",
            "--amount", "45.90",
            "--direction", "outflow",
            "--payee", "Amazon",
        ])
    assert result.exit_code == 0
    tx = captured["body"]["transaction"]
    assert tx["amount"] == -45900
    assert tx["payee_name"] == "Amazon"
    assert tx["cleared"] == "uncleared"
    assert tx["approved"] is False


def test_transactions_create_inflow_with_import_id(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "tx-sal"}, "transaction")
    captured = {}
    def fake_post(url, json=None, **kwargs):
        captured["body"] = json
        return fake
    with patch("tools.ynab_cli.httpx.post", side_effect=fake_post):
        result = runner.invoke(app, [
            "transactions", "create",
            "--account-id", "acct-1",
            "--date", "2026-05-01",
            "--amount", "1500.00",
            "--direction", "inflow",
            "--payee", "Stipendio",
            "--import-id", "SAL-2026-05",
        ])
    assert result.exit_code == 0
    tx = captured["body"]["transaction"]
    assert tx["amount"] == 1500000
    assert tx["import_id"] == "SAL-2026-05"


def test_transactions_create_bulk(monkeypatch, tmp_path):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    txns = [
        {"account_id": "acct-1", "date": "2026-05-04", "amount": -10000},
        {"account_id": "acct-1", "date": "2026-05-04", "amount": -5000},
    ]
    f = tmp_path / "txns.json"
    f.write_text(json.dumps(txns))
    fake = _fake_resp({"transaction_ids": ["tx-1", "tx-2"]})
    captured = {}
    def fake_post(url, json=None, **kwargs):
        captured["body"] = json
        return fake
    with patch("tools.ynab_cli.httpx.post", side_effect=fake_post):
        result = runner.invoke(app, ["transactions", "create-bulk", "--file", str(f)])
    assert result.exit_code == 0
    assert len(captured["body"]["transactions"]) == 2


def test_transactions_create_bulk_invalid_json(monkeypatch, tmp_path):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    f = tmp_path / "bad.json"
    f.write_text("not json")
    result = runner.invoke(app, ["transactions", "create-bulk", "--file", str(f)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Transactions — list-by-category / list-by-payee / list-by-month / import / update-multiple
# ---------------------------------------------------------------------------

def test_transactions_list_by_category(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "tx-cat-1"}], "transactions")
    captured_url = {}
    def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["transactions", "list-by-category", "cat-1"])
    assert result.exit_code == 0
    assert "categories/cat-1/transactions" in captured_url["url"]


def test_transactions_list_by_payee(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "tx-payee-1"}], "transactions")
    captured_url = {}
    def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["transactions", "list-by-payee", "payee-1"])
    assert result.exit_code == 0
    assert "payees/payee-1/transactions" in captured_url["url"]


def test_transactions_list_by_month(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "tx-month-1"}], "transactions")
    captured_url = {}
    def fake_get(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.get", side_effect=fake_get):
        result = runner.invoke(app, ["transactions", "list-by-month", "2026-05-01"])
    assert result.exit_code == 0
    assert "months/2026-05-01/transactions" in captured_url["url"]


def test_transactions_import(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"transaction_ids": ["tx-imported-1"]})
    with patch("tools.ynab_cli.httpx.post", return_value=fake):
        result = runner.invoke(app, ["transactions", "import"])
    assert result.exit_code == 0


def test_transactions_update_multiple(monkeypatch, tmp_path):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    txns = [{"id": "tx-1", "cleared": "cleared"}, {"id": "tx-2", "memo": "updated"}]
    f = tmp_path / "updates.json"
    f.write_text(json.dumps(txns))
    fake = _fake_resp({"transactions": txns})
    captured = {}
    def fake_patch(url, json=None, **kwargs):
        captured["body"] = json
        return fake
    with patch("tools.ynab_cli.httpx.patch", side_effect=fake_patch):
        result = runner.invoke(app, ["transactions", "update-multiple", "--file", str(f)])
    assert result.exit_code == 0
    assert len(captured["body"]["transactions"]) == 2


# ---------------------------------------------------------------------------
# Scheduled Transactions
# ---------------------------------------------------------------------------

def test_scheduled_list(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp([{"id": "sched-1", "frequency": "monthly"}], "scheduled_transactions")
    with patch("tools.ynab_cli.httpx.get", return_value=fake):
        result = runner.invoke(app, ["scheduled", "list"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out[0]["id"] == "sched-1"


def test_scheduled_create(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "sched-new", "frequency": "monthly"}, "scheduled_transaction")
    captured = {}
    def fake_post(url, json=None, **kwargs):
        captured["body"] = json
        return fake
    with patch("tools.ynab_cli.httpx.post", side_effect=fake_post):
        result = runner.invoke(app, [
            "scheduled", "create",
            "--account-id", "acct-1",
            "--date", "2026-06-01",
            "--frequency", "monthly",
            "--amount", "500.00",
            "--direction", "outflow",
            "--payee", "Affitto",
        ])
    assert result.exit_code == 0
    tx = captured["body"]["scheduled_transaction"]
    assert tx["amount"] == -500000
    assert tx["frequency"] == "monthly"
    assert tx["payee_name"] == "Affitto"


def test_scheduled_delete(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    fake = _fake_resp({"id": "sched-1", "deleted": True}, "scheduled_transaction")
    captured_url = {}
    def fake_delete(url, **kwargs):
        captured_url["url"] = url
        return fake
    with patch("tools.ynab_cli.httpx.delete", side_effect=fake_delete):
        result = runner.invoke(app, ["scheduled", "delete", "sched-1"])
    assert result.exit_code == 0
    assert "sched-1" in captured_url["url"]
