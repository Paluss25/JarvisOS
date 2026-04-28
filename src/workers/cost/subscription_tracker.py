"""Subscription tracker — detect recurring merchants from CFO ledger events."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared.cfo_sidecar import fetch_ledger_events

router = APIRouter()


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _merchant_name(event: dict[str, Any]) -> str | None:
    raw = event.get("raw_payload") or {}
    for key in ("payee_name", "merchant", "counterparty", "name"):
        value = raw.get(key)
        if value:
            return str(value).strip()
    return None


def detect_recurring_merchants(
    events: list[dict[str, Any]],
    *,
    tolerance_pct: float = 0.05,
    min_occurrences: int = 3,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for event in events:
        if event.get("event_type") != "expense":
            continue
        merchant = _merchant_name(event)
        if not merchant:
            continue
        amount = abs(float(event.get("fiat_value_eur") or event.get("amount") or 0))
        if amount <= 0:
            continue
        happened_at = event.get("happened_at")
        buckets[merchant].append(
            {
                "amount": amount,
                "happened_at": happened_at,
            }
        )

    subscriptions: list[dict[str, Any]] = []
    for merchant, items in buckets.items():
        if len(items) < min_occurrences:
            continue
        amounts = [item["amount"] for item in items]
        avg_amount = mean(amounts)
        max_delta = max(abs(amount - avg_amount) / avg_amount for amount in amounts) if avg_amount else 0
        if max_delta > tolerance_pct:
            continue
        sorted_dates = sorted(item["happened_at"] for item in items if item["happened_at"])
        subscriptions.append(
            {
                "merchant": merchant,
                "occurrences": len(items),
                "avg_amount_eur": round(avg_amount, 2),
                "estimated_monthly_cost_eur": round(avg_amount, 2),
                "first_seen": sorted_dates[0] if sorted_dates else None,
                "last_seen": sorted_dates[-1] if sorted_dates else None,
            }
        )

    subscriptions.sort(key=lambda item: item["estimated_monthly_cost_eur"], reverse=True)
    return subscriptions


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    lookback_days = int(task.scope.get("lookback_days", 90))
    since = datetime.now(tz=UTC) - timedelta(days=lookback_days)

    try:
        events = await fetch_ledger_events(from_date=since, limit=5000)
    except Exception as exc:
        return {"error": str(exc), "method": "cfo_ledger"}

    subscriptions = detect_recurring_merchants(events)
    monthly_total = round(sum(item["estimated_monthly_cost_eur"] for item in subscriptions), 2)
    annual_total = round(monthly_total * 12, 2)

    return {
        "lookback_days": lookback_days,
        "subscription_count": len(subscriptions),
        "estimated_monthly_total_eur": monthly_total,
        "estimated_annual_total_eur": annual_total,
        "subscriptions": subscriptions,
        "method": "cfo_ledger",
    }
