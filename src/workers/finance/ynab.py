"""YNAB Finance sub-agent — spending analysis from YNAB transactions."""

import os
from collections import defaultdict
from datetime import date

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

    return {
        "period": {"from": since, "to": until},
        "total_spent": round(total_spent, 2),
        "transaction_count": count,
        "spending_by_category": {
            k: round(v, 2)
            for k, v in sorted(spending.items(), key=lambda x: x[1], reverse=True)
        },
    }
