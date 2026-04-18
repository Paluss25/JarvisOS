"""ROI / Procurement sub-agent — buy vs lease analysis for hardware.

Pure calculation — no external API calls.

Decision thresholds (from K3s configmap):
  buy_threshold_fraction   = 0.333  → buy if upfront < 1/3 of total lease cost
  lease_threshold_fraction = 0.667  → lease if upfront > 2/3 of total lease cost
  Middle zone              → evaluate/hybrid

scope fields:
  upfront_cost        — one-time purchase price (EUR)
  monthly_lease       — monthly lease/subscription cost (EUR)
  useful_life_months  — expected useful life of the asset (months)
  residual_value      — residual value at end of life (EUR, optional, default 0)
  discount_rate       — annual discount rate for NPV (optional, default 0.05)
  items               — list of {name, upfront_cost, monthly_lease, useful_life_months,
                               residual_value?, discount_rate?} for batch mode
"""

import math

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_BUY_THRESHOLD = 0.333
_LEASE_THRESHOLD = 0.667


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _analyse_item(
    name: str,
    upfront: float,
    monthly_lease: float,
    life_months: int,
    residual: float = 0.0,
    annual_discount: float = 0.05,
) -> dict:
    total_lease_cost = monthly_lease * life_months
    total_ownership_cost = upfront - residual

    # NPV of lease payments
    monthly_rate = (1 + annual_discount) ** (1 / 12) - 1
    if monthly_rate > 0:
        npv_lease = monthly_lease * (1 - (1 + monthly_rate) ** -life_months) / monthly_rate
    else:
        npv_lease = total_lease_cost

    # Breakeven months: when cumulative lease cost = upfront cost
    breakeven_months = math.ceil(upfront / monthly_lease) if monthly_lease > 0 else None

    # Decision
    ratio = total_ownership_cost / total_lease_cost if total_lease_cost > 0 else 0
    if ratio <= _BUY_THRESHOLD:
        recommendation = "buy"
        reasoning = f"Upfront cost is only {ratio:.0%} of total lease cost — ownership is significantly cheaper."
    elif ratio >= _LEASE_THRESHOLD:
        recommendation = "lease"
        reasoning = f"Upfront cost is {ratio:.0%} of total lease cost — leasing preserves capital and flexibility."
    else:
        recommendation = "evaluate"
        reasoning = f"Upfront cost is {ratio:.0%} of total lease cost — marginal. Consider cash flow, tax treatment, and upgrade cycles."

    return {
        "name": name,
        "upfront_cost": upfront,
        "monthly_lease": monthly_lease,
        "useful_life_months": life_months,
        "residual_value": residual,
        "total_lease_cost": round(total_lease_cost, 2),
        "total_ownership_cost": round(total_ownership_cost, 2),
        "npv_lease": round(npv_lease, 2),
        "cost_ratio": round(ratio, 4),
        "breakeven_months": breakeven_months,
        "recommendation": recommendation,
        "reasoning": reasoning,
    }


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    items_raw = task.scope.get("items", [])

    # Support single-item mode
    if not items_raw:
        upfront = task.scope.get("upfront_cost")
        monthly_lease = task.scope.get("monthly_lease")
        life_months = task.scope.get("useful_life_months")

        if upfront is None or monthly_lease is None or life_months is None:
            return {
                "error": (
                    "Required: scope.upfront_cost, scope.monthly_lease, "
                    "scope.useful_life_months (or scope.items list)"
                )
            }
        items_raw = [{
            "name": task.scope.get("name", "asset"),
            "upfront_cost": upfront,
            "monthly_lease": monthly_lease,
            "useful_life_months": life_months,
            "residual_value": task.scope.get("residual_value", 0.0),
            "discount_rate": task.scope.get("discount_rate", 0.05),
        }]

    results = [
        _analyse_item(
            name=it.get("name", f"item_{i}"),
            upfront=float(it.get("upfront_cost", 0)),
            monthly_lease=float(it.get("monthly_lease", 0)),
            life_months=int(it.get("useful_life_months", 36)),
            residual=float(it.get("residual_value", 0)),
            annual_discount=float(it.get("discount_rate", 0.05)),
        )
        for i, it in enumerate(items_raw)
    ]

    return {
        "item_count": len(results),
        "results": results,
        "summary": {
            "buy": [r["name"] for r in results if r["recommendation"] == "buy"],
            "lease": [r["name"] for r in results if r["recommendation"] == "lease"],
            "evaluate": [r["name"] for r in results if r["recommendation"] == "evaluate"],
        },
        "confidence": 0.95,
        "method": "calculation",
    }
