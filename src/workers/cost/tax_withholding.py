"""Tax withholding — estimate YTD IRPEF from CFO income events."""

from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
import yaml

from workers.shared.cfo_sidecar import fetch_ledger_events

router = APIRouter()

_DEFAULT_BRACKETS = [
    {"up_to": 28000, "rate": 0.23},
    {"up_to": 50000, "rate": 0.35},
    {"up_to": None, "rate": 0.43},
]


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _tax_rules_path() -> Path:
    return Path(os.environ.get("CFO_WORKSPACE", "/app/workspace/cfo")) / "config" / "tax_rules.yaml"


def load_irpef_brackets() -> list[dict[str, Any]]:
    path = _tax_rules_path()
    if not path.exists():
        return _DEFAULT_BRACKETS
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        brackets = data.get("irpef_brackets")
        if isinstance(brackets, list) and brackets:
            return brackets
    except Exception:
        pass
    return _DEFAULT_BRACKETS


def estimate_progressive_tax(
    *,
    taxable_income: float,
    brackets: list[dict[str, Any]],
) -> dict[str, float]:
    remaining = taxable_income
    lower = 0.0
    total_tax = 0.0

    for bracket in brackets:
        upper = bracket.get("up_to")
        rate = float(bracket["rate"])
        if upper is None:
            taxable_slice = max(0.0, remaining)
        else:
            taxable_slice = max(0.0, min(remaining, float(upper) - lower))
        total_tax += taxable_slice * rate
        remaining -= taxable_slice
        if upper is not None:
            lower = float(upper)
        if remaining <= 0:
            break

    effective_rate = (total_tax / taxable_income * 100) if taxable_income > 0 else 0.0
    return {
        "estimated_tax_eur": round(total_tax, 2),
        "effective_rate_pct": round(effective_rate, 2),
    }


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    year = int(task.scope.get("year", datetime.now(tz=UTC).year))
    since = datetime(year, 1, 1, tzinfo=UTC)

    try:
        events = await fetch_ledger_events(from_date=since, limit=5000)
    except Exception as exc:
        return {"error": str(exc), "method": "cfo_ledger"}

    taxable_income = 0.0
    income_events = []
    for event in events:
        if event.get("event_type") != "income":
            continue
        amount = float(event.get("fiat_value_eur") or event.get("amount") or 0)
        if amount <= 0:
            continue
        taxable_income += amount
        income_events.append(event)

    brackets = load_irpef_brackets()
    estimate = estimate_progressive_tax(taxable_income=taxable_income, brackets=brackets)
    ytd_gross = round(taxable_income, 2)
    monthly_run_rate = round(ytd_gross / max(datetime.now(tz=UTC).month, 1), 2)

    return {
        "year": year,
        "income_events": len(income_events),
        "ytd_gross_income_eur": ytd_gross,
        "estimated_irpef_ytd_eur": estimate["estimated_tax_eur"],
        "effective_rate_pct": estimate["effective_rate_pct"],
        "monthly_run_rate_eur": monthly_run_rate,
        "method": "cfo_ledger",
        "brackets": brackets,
    }
