"""Cashflow forecast — exponential smoothing over monthly CFO ledger net flows."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared.cfo_sidecar import fetch_ledger_events

router = APIRouter()


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _month_key(timestamp: str) -> str:
    return f"{timestamp[:7]}-01"


def build_projection(monthly_net: list[dict[str, float]], *, alpha: float = 0.4) -> dict[str, Any]:
    if not monthly_net:
        return {
            "method": "exponential_smoothing",
            "projection_3m": [],
            "projection_6m": [],
            "projection_12m": [],
        }

    smoothed = monthly_net[0]["net_eur"]
    for row in monthly_net[1:]:
        smoothed = alpha * row["net_eur"] + (1 - alpha) * smoothed

    def _future_points(months: int) -> list[dict[str, float | str]]:
        start = datetime.fromisoformat(monthly_net[-1]["month"]).replace(tzinfo=UTC)
        points: list[dict[str, float | str]] = []
        for index in range(1, months + 1):
            future = (start + timedelta(days=32 * index)).replace(day=1)
            points.append(
                {
                    "month": future.date().isoformat(),
                    "projected_net_eur": round(smoothed, 2),
                }
            )
        return points

    return {
        "method": "exponential_smoothing",
        "projection_3m": _future_points(3),
        "projection_6m": _future_points(6),
        "projection_12m": _future_points(12),
        "smoothed_monthly_net_eur": round(smoothed, 2),
    }


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    lookback_days = int(task.scope.get("lookback_days", 365))
    since = datetime.now(tz=UTC) - timedelta(days=lookback_days)

    try:
        events = await fetch_ledger_events(from_date=since, limit=5000)
    except Exception as exc:
        return {"error": str(exc), "method": "cfo_ledger"}

    monthly: dict[str, float] = {}
    for event in events:
        happened_at = event.get("happened_at")
        if not happened_at:
            continue
        amount = float(event.get("fiat_value_eur") or event.get("amount") or 0)
        key = _month_key(happened_at)
        monthly[key] = monthly.get(key, 0.0) + amount

    monthly_net = [
        {"month": month, "net_eur": round(value, 2)}
        for month, value in sorted(monthly.items())
    ]
    projection = build_projection(monthly_net)
    projection["history"] = monthly_net
    projection["lookback_days"] = lookback_days
    projection["confidence"] = 0.8 if len(monthly_net) >= 6 else 0.5
    return projection
