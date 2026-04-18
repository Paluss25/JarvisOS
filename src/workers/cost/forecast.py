"""Forecast sub-agent — cost trend projection with LLM commentary.

Looks back `lookback_days` (default 90) of YNAB spending data and
projects `projection_months` (default 6) forward.

Uses haiku for natural-language commentary when trend is detected.

Tunable defaults (from K3s configmap):
  default_projection_months      = 6
  lookback_days                  = 90
  confidence_sufficient_data     = 0.8
  confidence_insufficient_data   = 0.5
  sufficient_data_months         = 3
  trend_increase_threshold       = 10  %
  trend_decrease_threshold       = -10 %
  trend_increase_rate            = 0.03 (3% / month)
  trend_decrease_rate            = 0.02 (2% / month)
  trend_floor                    = 0.5  (min multiplier)
"""

import os
from datetime import date, timedelta

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import llm

router = APIRouter()

_YNAB_BASE = "https://api.ynab.com/v1"
_TIMEOUT = 10.0

_SYSTEM = (
    "You are a financial forecasting assistant. Given monthly spending data and a trend, "
    "write a concise 2-sentence commentary suitable for a CFO dashboard. "
    "Be specific about amounts, trend direction, and any notable outliers. "
    "Reply with ONLY the commentary, no preamble."
)


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _ynab_headers() -> dict:
    return {"Authorization": f"Bearer {os.environ.get('YNAB_API_KEY', '')}"}


async def _fetch_monthly_spending(budget_id: str, lookback_days: int) -> list[dict]:
    """Fetch spending totals by month for the lookback period."""
    months_back = max(1, lookback_days // 30)
    today = date.today()
    result = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for i in range(months_back, 0, -1):
            # First day of month i months ago
            m = today.replace(day=1) - timedelta(days=30 * i)
            month_str = m.strftime("%Y-%m-01")
            try:
                resp = await client.get(
                    f"{_YNAB_BASE}/budgets/{budget_id}/months/{month_str}",
                    headers=_ynab_headers(),
                )
                if resp.is_success:
                    data = resp.json()["data"]["month"]
                    activity = abs(data.get("activity", 0)) / 1000  # milliunits → currency
                    result.append({"month": month_str, "spent": round(activity, 2)})
            except Exception:
                pass

    return result


def _calculate_trend(monthly: list[dict]) -> tuple[str, float]:
    """Return (trend_label, monthly_growth_rate)."""
    if len(monthly) < 2:
        return "insufficient_data", 0.0

    # Simple linear trend: compare first half average vs second half average
    mid = len(monthly) // 2
    first_avg = sum(m["spent"] for m in monthly[:mid]) / mid
    second_avg = sum(m["spent"] for m in monthly[mid:]) / max(len(monthly) - mid, 1)

    if first_avg == 0:
        return "stable", 0.0

    pct_change = ((second_avg - first_avg) / first_avg) * 100

    if pct_change > 10:
        return "increasing", 0.03
    elif pct_change < -10:
        return "decreasing", -0.02
    return "stable", 0.0


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    budget_id = task.scope.get("budget_id") or os.environ.get("YNAB_BUDGET_ID", "last-used")
    lookback_days = int(task.scope.get("lookback_days", 90))
    projection_months = int(task.scope.get("projection_months", 6))
    trend_floor = float(task.scope.get("trend_floor", 0.5))

    if not os.environ.get("YNAB_API_KEY"):
        return {
            "trend": "unknown",
            "projection": [],
            "confidence": 0.3,
            "method": "no_data",
            "note": "YNAB_API_KEY not configured",
        }

    try:
        monthly = await _fetch_monthly_spending(budget_id, lookback_days)
    except Exception as exc:
        return {"trend": "unknown", "error": str(exc), "confidence": 0.3}

    if not monthly:
        return {"trend": "unknown", "projection": [], "confidence": 0.3, "method": "no_data"}

    sufficient = len(monthly) >= int(task.scope.get("sufficient_data_months", 3))
    confidence = 0.8 if sufficient else 0.5

    trend_label, monthly_rate = _calculate_trend(monthly)

    # Project forward from the last known month spend
    base_spend = monthly[-1]["spent"] if monthly else 0.0
    last_month_date = date.today().replace(day=1)
    projection = []
    for i in range(1, projection_months + 1):
        multiplier = max(trend_floor, (1 + monthly_rate) ** i)
        proj_month = (last_month_date.replace(day=1) + timedelta(days=32 * i)).replace(day=1)
        projection.append({
            "month": proj_month.strftime("%Y-%m-01"),
            "projected_spend": round(base_spend * multiplier, 2),
        })

    # LLM commentary
    commentary = None
    if monthly and trend_label != "insufficient_data":
        try:
            history_summary = ", ".join(
                f"{m['month'][:7]}: €{m['spent']:.0f}" for m in monthly
            )
            prompt = (
                f"Monthly spending data: {history_summary}\n"
                f"Trend detected: {trend_label} (rate: {monthly_rate:+.1%}/month)\n"
                f"Projected next {projection_months} months: "
                + ", ".join(f"€{p['projected_spend']:.0f}" for p in projection)
            )
            commentary = (await llm.complete(prompt, system=_SYSTEM)).strip()
        except Exception:
            pass

    return {
        "lookback_days": lookback_days,
        "monthly_history": monthly,
        "trend": trend_label,
        "monthly_growth_rate": round(monthly_rate, 4),
        "projection_months": projection_months,
        "projection": projection,
        "commentary": commentary,
        "confidence": confidence,
        "method": "ynab" if monthly else "no_data",
    }
