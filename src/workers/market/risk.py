"""Risk sub-agent — Polymarket portfolio exposure analysis.

Reads open positions from the polymarket DB and computes exposure,
concentration risk, and overall portfolio risk level.

Tunable defaults (from K3s configmap):
  high_risk_threshold   = 1200  EUR — total exposure > this → HIGH
  medium_risk_threshold = 600   EUR — total exposure > this → MEDIUM
  confidence            = 0.95
"""

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import polymarket_db as db

router = APIRouter()

_HIGH_RISK = 1200.0
_MEDIUM_RISK = 600.0


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    high_threshold = float(task.scope.get("high_risk_threshold", _HIGH_RISK))
    medium_threshold = float(task.scope.get("medium_risk_threshold", _MEDIUM_RISK))

    # Fetch open positions — JOIN markets for condition_id + title
    rows = await db.fetch(
        """
        SELECT
            m.condition_id,
            m.title                          AS question,
            p.side,
            p.size,
            p.avg_entry_price,
            p.current_price,
            p.unrealized_pnl,
            (p.size * p.current_price)       AS market_value
        FROM positions p
        JOIN markets m ON p.market_id = m.market_id
        WHERE p.size > 0
        ORDER BY (p.size * p.current_price) DESC
        """
    )

    if rows is None:
        return {
            "total_exposure": 0,
            "positions": [],
            "risk_level": "unknown",
            "confidence": 0.3,
            "method": "no_data",
            "note": "Polymarket DB not available",
        }

    positions = []
    total_exposure = 0.0
    total_unrealized_pnl = 0.0
    largest_position = 0.0

    for row in rows:
        market_value = float(row["market_value"] or 0)
        unrealized = float(row["unrealized_pnl"] or 0)
        total_exposure += market_value
        total_unrealized_pnl += unrealized
        if market_value > largest_position:
            largest_position = market_value

        positions.append({
            "condition_id": row["condition_id"],
            "question": row["question"],
            "side": row["side"],
            "size": float(row["size"] or 0),
            "avg_entry_price": float(row["avg_entry_price"] or 0),
            "current_price": float(row["current_price"] or 0),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized, 2),
        })

    # Concentration ratio: largest position / total
    concentration = (largest_position / total_exposure) if total_exposure > 0 else 0.0

    if total_exposure >= high_threshold:
        risk_level = "high"
    elif total_exposure >= medium_threshold:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "total_exposure": round(total_exposure, 2),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "position_count": len(positions),
        "largest_position": round(largest_position, 2),
        "concentration_ratio": round(concentration, 4),
        "risk_level": risk_level,
        "positions": positions,
        "confidence": 0.95,
        "method": "polymarket_db",
    }
