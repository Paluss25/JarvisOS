"""YNAB CLI — full YNAB REST API wrapper for the CFO agent (Warren).

Usage inside container:
    python3 /app/src/tools/ynab_cli.py <group> <command> [options]

Output: JSON to stdout, exit 0 on success / exit 1 on error (JSON error to stderr).
YNAB_API_KEY and YNAB_BUDGET_ID are read from environment variables.
"""

import json
import os
import sys
from datetime import date

import httpx
import typer

app = typer.Typer(add_completion=False, no_args_is_help=True)
budgets_app = typer.Typer(no_args_is_help=True)
accounts_app = typer.Typer(no_args_is_help=True)
categories_app = typer.Typer(no_args_is_help=True)
payees_app = typer.Typer(no_args_is_help=True)
payee_locations_app = typer.Typer(no_args_is_help=True)
months_app = typer.Typer(no_args_is_help=True)
transactions_app = typer.Typer(no_args_is_help=True)
scheduled_app = typer.Typer(no_args_is_help=True)

app.add_typer(budgets_app, name="budgets", help="Budget operations")
app.add_typer(accounts_app, name="accounts", help="Account operations")
app.add_typer(categories_app, name="categories", help="Category operations")
app.add_typer(payees_app, name="payees", help="Payee operations")
app.add_typer(payee_locations_app, name="payee-locations", help="Payee location operations")
app.add_typer(months_app, name="months", help="Month budget operations")
app.add_typer(transactions_app, name="transactions", help="Transaction CRUD")
app.add_typer(scheduled_app, name="scheduled", help="Scheduled transaction CRUD")

_BASE = "https://api.ynab.com/v1"
_TIMEOUT = 15.0


def _api_key() -> str:
    key = os.environ.get("YNAB_API_KEY", "")
    if not key:
        _die("YNAB_API_KEY not set")
    return key


def _headers() -> dict:
    return {"Authorization": f"Bearer {_api_key()}"}


def _budget(budget_id: str) -> str:
    if budget_id:
        return budget_id
    return os.environ.get("YNAB_BUDGET_ID", "last-used")


def _get(path: str, params: dict | None = None) -> dict:
    resp = httpx.get(f"{_BASE}{path}", headers=_headers(), params=params or {}, timeout=_TIMEOUT)
    _check(resp)
    return resp.json()


def _post(path: str, body: dict) -> dict:
    resp = httpx.post(f"{_BASE}{path}", json=body, headers=_headers(), timeout=_TIMEOUT)
    _check(resp)
    return resp.json()


def _put(path: str, body: dict) -> dict:
    resp = httpx.put(f"{_BASE}{path}", json=body, headers=_headers(), timeout=_TIMEOUT)
    _check(resp)
    return resp.json()


def _patch(path: str, body: dict) -> dict:
    resp = httpx.patch(f"{_BASE}{path}", json=body, headers=_headers(), timeout=_TIMEOUT)
    _check(resp)
    return resp.json()


def _delete(path: str) -> dict:
    resp = httpx.delete(f"{_BASE}{path}", headers=_headers(), timeout=_TIMEOUT)
    _check(resp)
    return resp.json()


def _check(resp: httpx.Response) -> None:
    if not resp.is_success:
        _die(f"YNAB API {resp.status_code}: {resp.text[:300]}")


def _die(msg: str) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    raise typer.Exit(1)


def _out(data) -> None:
    print(json.dumps(data, indent=2))


def _milliunits(amount: float, direction: str) -> int:
    """Convert EUR amount + direction to YNAB milliunits (signed)."""
    base = int(round(abs(amount) * 1000))
    return -base if direction == "outflow" else base


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

@budgets_app.command("list")
def budgets_list():
    """List all budgets."""
    data = _get("/budgets")
    _out(data["data"]["budgets"])


@budgets_app.command("get")
def budgets_get(
    budget_id: str = typer.Option("", "--budget-id", help="Budget ID or 'last-used'"),
):
    """Get a budget's full detail."""
    data = _get(f"/budgets/{_budget(budget_id)}")
    _out(data["data"]["budget"])


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@accounts_app.command("list")
def accounts_list(
    budget_id: str = typer.Option("", "--budget-id"),
):
    """List all accounts for a budget."""
    data = _get(f"/budgets/{_budget(budget_id)}/accounts")
    _out(data["data"]["accounts"])


@accounts_app.command("get")
def accounts_get(
    account_id: str = typer.Argument(..., help="Account UUID"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Get a single account."""
    data = _get(f"/budgets/{_budget(budget_id)}/accounts/{account_id}")
    _out(data["data"]["account"])


@accounts_app.command("create")
def accounts_create(
    name: str = typer.Option(..., "--name", help="Account name"),
    type_: str = typer.Option(..., "--type", help="checking|savings|creditCard|cash|lineOfCredit|mortgage|autoLoan|studentLoan|personalLoan|medicalDebt|otherDebt|otherAsset|otherLiability"),
    balance: float = typer.Option(0.0, "--balance", help="Opening balance in EUR"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Create a new account."""
    body = {"account": {"name": name, "type": type_, "balance": int(round(balance * 1000))}}
    data = _post(f"/budgets/{_budget(budget_id)}/accounts", body)
    _out(data["data"]["account"])


if __name__ == "__main__":
    app()
