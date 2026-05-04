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


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@categories_app.command("list")
def categories_list(
    budget_id: str = typer.Option("", "--budget-id"),
):
    """List all category groups with their categories."""
    data = _get(f"/budgets/{_budget(budget_id)}/categories")
    _out(data["data"]["category_groups"])


@categories_app.command("get")
def categories_get(
    category_id: str = typer.Argument(..., help="Category UUID"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Get a single category."""
    data = _get(f"/budgets/{_budget(budget_id)}/categories/{category_id}")
    _out(data["data"]["category"])


@categories_app.command("update-month")
def categories_update_month(
    category_id: str = typer.Argument(..., help="Category UUID"),
    budgeted: float = typer.Option(..., "--budgeted", help="Budgeted amount in EUR"),
    month: str = typer.Option("current", "--month", help="YYYY-MM-DD (first of month) or 'current'"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Set the budgeted amount for a category in a given month."""
    if month == "current":
        month = date.today().replace(day=1).isoformat()
    body = {"category": {"budgeted": int(round(budgeted * 1000))}}
    data = _patch(
        f"/budgets/{_budget(budget_id)}/months/{month}/categories/{category_id}",
        body,
    )
    _out(data["data"]["category"])


# ---------------------------------------------------------------------------
# Payees
# ---------------------------------------------------------------------------

@payees_app.command("list")
def payees_list(
    budget_id: str = typer.Option("", "--budget-id"),
):
    """List all payees."""
    data = _get(f"/budgets/{_budget(budget_id)}/payees")
    _out(data["data"]["payees"])


@payees_app.command("get")
def payees_get(
    payee_id: str = typer.Argument(..., help="Payee UUID"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Get a single payee."""
    data = _get(f"/budgets/{_budget(budget_id)}/payees/{payee_id}")
    _out(data["data"]["payee"])


@payees_app.command("update")
def payees_update(
    payee_id: str = typer.Argument(..., help="Payee UUID"),
    name: str = typer.Option(..., "--name", help="New canonical payee name"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Rename a payee."""
    body = {"payee": {"name": name}}
    data = _patch(f"/budgets/{_budget(budget_id)}/payees/{payee_id}", body)
    _out(data["data"]["payee"])


# ---------------------------------------------------------------------------
# Payee Locations
# ---------------------------------------------------------------------------

@payee_locations_app.command("list")
def payee_locations_list(
    budget_id: str = typer.Option("", "--budget-id"),
):
    """List all payee locations across the budget."""
    data = _get(f"/budgets/{_budget(budget_id)}/payee_locations")
    _out(data["data"]["payee_locations"])


@payee_locations_app.command("get")
def payee_locations_get(
    payee_location_id: str = typer.Argument(..., help="Payee location UUID"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Get a single payee location."""
    data = _get(f"/budgets/{_budget(budget_id)}/payee_locations/{payee_location_id}")
    _out(data["data"]["payee_location"])


@payee_locations_app.command("list-by-payee")
def payee_locations_list_by_payee(
    payee_id: str = typer.Argument(..., help="Payee UUID"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """List all locations for a specific payee."""
    data = _get(f"/budgets/{_budget(budget_id)}/payees/{payee_id}/payee_locations")
    _out(data["data"]["payee_locations"])


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------

@months_app.command("list")
def months_list(
    budget_id: str = typer.Option("", "--budget-id"),
):
    """List all budget months."""
    data = _get(f"/budgets/{_budget(budget_id)}/months")
    _out(data["data"]["months"])


@months_app.command("get")
def months_get(
    month: str = typer.Argument("current", help="YYYY-MM-DD (first of month) or 'current'"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Get full detail for a budget month (categories + activity)."""
    if month == "current":
        month = date.today().replace(day=1).isoformat()
    data = _get(f"/budgets/{_budget(budget_id)}/months/{month}")
    _out(data["data"]["month"])


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@transactions_app.command("list")
def transactions_list(
    since: str = typer.Option("", "--since", help="Filter from YYYY-MM-DD"),
    account_id: str = typer.Option("", "--account-id", help="Limit to one account"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """List transactions, optionally filtered by date or account."""
    params: dict = {}
    if since:
        params["since_date"] = since
    bid = _budget(budget_id)
    if account_id:
        path = f"/budgets/{bid}/accounts/{account_id}/transactions"
    else:
        path = f"/budgets/{bid}/transactions"
    data = _get(path, params or None)
    _out(data["data"]["transactions"])


@transactions_app.command("get")
def transactions_get(
    tx_id: str = typer.Argument(..., help="Transaction UUID"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Get a single transaction by ID."""
    data = _get(f"/budgets/{_budget(budget_id)}/transactions/{tx_id}")
    _out(data["data"]["transaction"])


@transactions_app.command("update")
def transactions_update(
    tx_id: str = typer.Argument(..., help="Transaction UUID"),
    payee: str = typer.Option("", "--payee", help="New payee name"),
    memo: str = typer.Option("", "--memo"),
    cleared: str = typer.Option("", "--cleared", help="cleared|uncleared|reconciled"),
    approved: bool | None = typer.Option(None, "--approved/--no-approved"),
    category_id: str = typer.Option("", "--category-id"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Update fields on an existing transaction (PUT — replaces the transaction)."""
    tx: dict = {}
    if payee:
        tx["payee_name"] = payee[:50]
    if memo:
        tx["memo"] = memo[:200]
    if cleared:
        tx["cleared"] = cleared
    if approved is not None:
        tx["approved"] = approved
    if category_id:
        tx["category_id"] = category_id
    if not tx:
        _die("No fields to update — provide at least one of --payee, --memo, --cleared, --approved, --category-id")
    data = _put(f"/budgets/{_budget(budget_id)}/transactions/{tx_id}", {"transaction": tx})
    _out(data["data"]["transaction"])


@transactions_app.command("delete")
def transactions_delete(
    tx_id: str = typer.Argument(..., help="Transaction UUID"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Delete a transaction (permanent)."""
    data = _delete(f"/budgets/{_budget(budget_id)}/transactions/{tx_id}")
    _out(data["data"]["transaction"])


@transactions_app.command("create")
def transactions_create(
    account_id: str = typer.Option(..., "--account-id", help="Account UUID"),
    date_: str = typer.Option(..., "--date", help="YYYY-MM-DD"),
    amount: float = typer.Option(..., "--amount", help="Positive EUR amount"),
    direction: str = typer.Option("outflow", "--direction", help="outflow|inflow"),
    payee: str = typer.Option("", "--payee", help="Payee name (max 50 chars)"),
    payee_id: str = typer.Option("", "--payee-id", help="Existing payee UUID (takes priority over --payee)"),
    memo: str = typer.Option("", "--memo", help="Memo (max 200 chars)"),
    category_id: str = typer.Option("", "--category-id"),
    import_id: str = typer.Option("", "--import-id", help="Dedupe key (max 36 chars)"),
    cleared: str = typer.Option("uncleared", "--cleared", help="cleared|uncleared|reconciled"),
    approved: bool = typer.Option(False, "--approved/--no-approved"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Create a single transaction."""
    tx: dict = {
        "account_id": account_id,
        "date": date_,
        "amount": _milliunits(amount, direction),
        "cleared": cleared,
        "approved": approved,
    }
    if payee_id:
        tx["payee_id"] = payee_id
    elif payee:
        tx["payee_name"] = payee[:50]
    if memo:
        tx["memo"] = memo[:200]
    if category_id:
        tx["category_id"] = category_id
    if import_id:
        tx["import_id"] = import_id[:36]
    data = _post(f"/budgets/{_budget(budget_id)}/transactions", {"transaction": tx})
    _out(data["data"]["transaction"])


@transactions_app.command("create-bulk")
def transactions_create_bulk(
    file_path: str = typer.Option(..., "--file", help="Path to JSON file containing array of transaction objects"),
    budget_id: str = typer.Option("", "--budget-id"),
):
    """Create multiple transactions from a JSON file. Each object must match the YNAB transaction schema."""
    import pathlib
    try:
        raw = pathlib.Path(file_path).read_text(encoding="utf-8")
    except OSError as exc:
        _die(f"Cannot read file {file_path}: {exc}")
    try:
        txns = json.loads(raw)
    except json.JSONDecodeError as exc:
        _die(f"Invalid JSON in {file_path}: {exc}")
    if not isinstance(txns, list):
        _die("--file must contain a JSON array of transaction objects")
    data = _post(f"/budgets/{_budget(budget_id)}/transactions", {"transactions": txns})
    _out(data["data"])


if __name__ == "__main__":
    app()
