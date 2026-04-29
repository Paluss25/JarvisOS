"""YNAB Finance sub-agent — spending analysis from YNAB transactions."""

import os
from collections import defaultdict
from datetime import UTC, date, datetime

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_YNAB_BASE = "https://api.ynab.com/v1"
_TIMEOUT = 15.0


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _headers() -> dict:
    key = os.environ.get("YNAB_API_KEY", "")
    if not key:
        raise ValueError("YNAB_API_KEY not configured")
    return {"Authorization": f"Bearer {key}"}


def _budget_id() -> str:
    bid = os.environ.get("YNAB_BUDGET_ID", "")
    if not bid:
        raise ValueError("YNAB_BUDGET_ID not configured")
    return bid


def _period_dates(period: str) -> tuple[str, str]:
    """Return (since_date, until_date) for a period string like 'current_month' or 'YYYY-MM'."""
    today = date.today()
    if period == "current_month" or not period:
        since = today.replace(day=1).isoformat()
        until = today.isoformat()
    elif "-" in period and len(period) == 7:  # YYYY-MM
        y, m = int(period[:4]), int(period[5:7])
        since = date(y, m, 1).isoformat()
        last_day = date(y, m + 1, 1) if m < 12 else date(y + 1, 1, 1)
        import datetime
        until = (last_day - datetime.timedelta(days=1)).isoformat()
    else:
        since = today.replace(day=1).isoformat()
        until = today.isoformat()
    return since, until


def _sidecar_url() -> str:
    return os.environ.get("CFO_SIDECAR_URL", "http://cfo-data-service:8000").rstrip("/")


def _ledger_headers() -> dict[str, str]:
    token = os.environ.get("CFO_CLI_TOKEN", "")
    if not token:
        raise ValueError("CFO_CLI_TOKEN not configured")
    return {"Authorization": f"Bearer {token}"}


def _transaction_payload(tx: dict) -> dict:
    amount = tx.get("amount", 0) / 1000.0
    if tx.get("transfer_account_id"):
        event_type = "transfer"
    elif amount < 0:
        event_type = "expense"
    else:
        event_type = "income"

    happened_at = datetime.fromisoformat(tx["date"]).replace(tzinfo=UTC).isoformat()
    return {
        "source": "ynab",
        "event_type": event_type,
        "external_id": tx["id"],
        "account_id": None,
        "asset_id": None,
        "amount": amount,
        "currency": tx.get("currency_code") or "EUR",
        "fiat_value_eur": amount,
        "fee_eur": None,
        "tx_hash": None,
        "happened_at": happened_at,
        "counterparty_type": None,
        "category": tx.get("category_name"),
        "tax_treatment_candidate": None,
        "confidence_score": None,
        "evidence_link": None,
        "raw_payload": tx,
    }


async def _sync_transactions_to_ledger(txns: list[dict]) -> dict:
    attempted = 0
    succeeded = 0
    failed_ids: list[str] = []

    try:
        headers = _ledger_headers()
    except ValueError:
        return {"attempted": 0, "succeeded": 0, "failed": 0, "failed_ids": []}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for tx in txns:
            if tx.get("deleted"):
                continue
            attempted += 1
            response = await client.post(
                f"{_sidecar_url()}/ledger/events",
                json=_transaction_payload(tx),
                headers=headers,
            )
            if response.is_success:
                succeeded += 1
            else:
                failed_ids.append(tx["id"])

    return {
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": len(failed_ids),
        "failed_ids": failed_ids,
    }


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    period = task.scope.get("period", "current_month")
    since, until = _period_dates(period)

    try:
        bid = _budget_id()
        hdrs = _headers()
    except ValueError as exc:
        return {"error": str(exc)}

    params = {"since_date": since}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_YNAB_BASE}/budgets/{bid}/transactions",
                headers=hdrs,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"error": f"YNAB API error: {exc}"}

    txns = data.get("data", {}).get("transactions", [])

    spending: dict[str, float] = defaultdict(float)
    total_spent = 0.0
    count = 0

    for tx in txns:
        if tx.get("deleted"):
            continue
        # YNAB amounts are in milliunits (1/1000 of currency unit)
        amount = tx.get("amount", 0) / 1000.0
        if amount < 0:  # outflow = spending
            category = tx.get("category_name") or "Uncategorized"
            spending[category] += abs(amount)
            total_spent += abs(amount)
            count += 1

    sync_result = await _sync_transactions_to_ledger(txns)

    result = {
        "period": {"from": since, "to": until},
        "total_spent": round(total_spent, 2),
        "transaction_count": count,
        "spending_by_category": {
            k: round(v, 2)
            for k, v in sorted(spending.items(), key=lambda x: x[1], reverse=True)
        },
        "ledger_sync": {
            "attempted": sync_result["attempted"],
            "succeeded": sync_result["succeeded"],
            "failed": sync_result["failed"],
        },
    }
    if sync_result["failed_ids"]:
        result["ledger_sync_errors"] = sync_result["failed_ids"]
    return result
