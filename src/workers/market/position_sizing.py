"""Position Sizing sub-agent — Kelly criterion sizing for Polymarket trades.

Pure calculation — no DB or API calls required.

Kelly formula: f* = (p * b - q) / b
  where p = win probability, q = 1-p, b = net odds (profit / stake)

For prediction markets: b = (1 - price) / price (YES side)

Fractional Kelly: apply kelly_fraction multiplier (default 0.15 = 15% Kelly)
to reduce variance.

Tunable defaults (from K3s configmap):
  kelly_fraction      = 0.15
  min_size            = 25    EUR
  max_size            = 250   EUR
  max_bankroll_pct    = 0.02  (2% of bankroll)
  default_bankroll    = 5000  EUR
  min_edge_for_trade  = 0.30  (min Kelly edge to recommend a trade)
"""

import math

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _kelly_size(
    bankroll: float,
    price: float,
    p_win: float,
    kelly_fraction: float,
    min_size: float,
    max_size: float,
    max_bankroll_pct: float,
) -> dict:
    """Compute fractional Kelly position size for a binary prediction market."""
    if not (0 < price < 1):
        return {"error": f"price must be between 0 and 1, got {price}"}
    if not (0 < p_win < 1):
        return {"error": f"p_win must be between 0 and 1, got {p_win}"}

    # Net odds: profit per unit staked on YES
    b = (1 - price) / price

    # Kelly fraction of bankroll
    q = 1 - p_win
    full_kelly = (p_win * b - q) / b if b > 0 else 0.0
    fractional_kelly = full_kelly * kelly_fraction

    edge = p_win - price  # raw edge (probability edge)

    # Suggested size in EUR
    unconstrained = bankroll * fractional_kelly
    max_by_bankroll_pct = bankroll * max_bankroll_pct

    recommended = min(unconstrained, max_by_bankroll_pct, max_size)
    recommended = max(recommended, 0.0)  # never negative

    return {
        "price": price,
        "p_win": p_win,
        "edge": round(edge, 4),
        "full_kelly_fraction": round(full_kelly, 4),
        "fractional_kelly": round(fractional_kelly, 4),
        "kelly_fraction_used": kelly_fraction,
        "unconstrained_size_eur": round(unconstrained, 2),
        "recommended_size_eur": round(recommended, 2),
        "min_size_eur": min_size,
        "max_size_eur": max_size,
        "viable": recommended >= min_size and edge > 0,
    }


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    kelly_fraction = float(task.scope.get("kelly_fraction", 0.15))
    min_size = float(task.scope.get("min_size", 25))
    max_size = float(task.scope.get("max_size", 250))
    max_bankroll_pct = float(task.scope.get("max_bankroll_pct", 0.02))
    default_bankroll = float(task.scope.get("bankroll", 5000))
    min_edge = float(task.scope.get("min_edge_for_trade", 0.30))

    trades_raw = task.scope.get("trades", [])

    # Support single-trade mode
    if not trades_raw:
        price = task.scope.get("price")
        p_win = task.scope.get("p_win")
        if price is None or p_win is None:
            return {
                "error": (
                    "Required: scope.price and scope.p_win "
                    "(or scope.trades list of {price, p_win, question?, bankroll?})"
                )
            }
        trades_raw = [{
            "price": price,
            "p_win": p_win,
            "question": task.scope.get("question", ""),
            "bankroll": task.scope.get("bankroll", default_bankroll),
        }]

    results = []
    for trade in trades_raw:
        bankroll = float(trade.get("bankroll", default_bankroll))
        sizing = _kelly_size(
            bankroll=bankroll,
            price=float(trade.get("price", 0.5)),
            p_win=float(trade.get("p_win", 0.5)),
            kelly_fraction=kelly_fraction,
            min_size=min_size,
            max_size=max_size,
            max_bankroll_pct=max_bankroll_pct,
        )
        sizing["question"] = trade.get("question", "")
        sizing["bankroll"] = bankroll
        results.append(sizing)

    viable = [r for r in results if r.get("viable") and r.get("edge", 0) >= min_edge]

    return {
        "trade_count": len(results),
        "viable_count": len(viable),
        "results": results,
        "summary": {
            "viable_trades": [r["question"] for r in viable if r.get("question")],
            "total_recommended_eur": round(sum(r["recommended_size_eur"] for r in viable), 2),
        },
        "confidence": 0.95,
        "method": "kelly_calculation",
    }
