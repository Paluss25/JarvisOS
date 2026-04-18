"""Budget Control sub-agent — YNAB budget vs spending status.

Fetches current-month spending from YNAB and compares against budget limits.
Returns category-level budget health (over/under/on-track).

Requires: YNAB_API_KEY, YNAB_BUDGET_ID env vars.
"""

import os
from datetime import date

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_YNAB_BASE = "https://api.ynab.com/v1"
_TIMEOUT = 10.0


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _ynab_headers() -> dict:
    token = os.environ.get("YNAB_API_KEY", "")
    return {"Authorization": f"Bearer {token}"}


def _current_month() -> str:
    today = date.today()
    return f"{today.year}-{today.month:02d}-01"


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    budget_id = task.scope.get("budget_id") or os.environ.get("YNAB_BUDGET_ID", "last-used")
    month = task.scope.get("month", _current_month())

    if not os.environ.get("YNAB_API_KEY"):
        return {
            "month": month,
            "categories": [],
            "total_budgeted": 0,
            "total_spent": 0,
            "total_remaining": 0,
            "confidence": 0.3,
            "method": "no_data",
            "note": "YNAB_API_KEY not configured",
        }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_YNAB_BASE}/budgets/{budget_id}/months/{month}",
                headers=_ynab_headers(),
            )
            if not resp.is_success:
                return {
                    "month": month,
                    "error": f"YNAB API returned {resp.status_code}",
                    "confidence": 0.3,
                }

            data = resp.json()["data"]["month"]
            raw_categories = data.get("categories", [])
    except Exception as exc:
        return {"month": month, "error": str(exc), "confidence": 0.3}

    # YNAB amounts are in milliunits (1000 = 1 EUR/USD)
    def _milli(v) -> float:
        return round((v or 0) / 1000, 2)

    categories = []
    total_budgeted = 0.0
    total_spent = 0.0

    for cat in raw_categories:
        if cat.get("hidden") or cat.get("deleted"):
            continue
        budgeted = _milli(cat.get("budgeted", 0))
        spent = _milli(abs(cat.get("activity", 0)))
        balance = _milli(cat.get("balance", 0))

        if budgeted == 0 and spent == 0:
            continue

        pct_used = round((spent / budgeted * 100) if budgeted > 0 else 0, 1)
        status = (
            "over_budget" if spent > budgeted > 0
            else "on_track" if pct_used <= 80
            else "near_limit"
        )

        categories.append({
            "name": cat["name"],
            "group": cat.get("category_group_name", ""),
            "budgeted": budgeted,
            "spent": spent,
            "remaining": balance,
            "pct_used": pct_used,
            "status": status,
        })
        total_budgeted += budgeted
        total_spent += spent

    over_budget = [c for c in categories if c["status"] == "over_budget"]

    return {
        "month": month,
        "categories": categories,
        "total_budgeted": round(total_budgeted, 2),
        "total_spent": round(total_spent, 2),
        "total_remaining": round(total_budgeted - total_spent, 2),
        "over_budget_count": len(over_budget),
        "over_budget_categories": [c["name"] for c in over_budget],
        "confidence": 0.95,
        "method": "ynab",
    }
