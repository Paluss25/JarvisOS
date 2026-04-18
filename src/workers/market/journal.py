"""Trade Journal sub-agent — Polymarket historical performance review.

Reads trades, orders, and daily PnL from the polymarket DB.
Returns performance stats: win rate, total PnL, avg return per trade,
best/worst trades.

Tunable defaults (from K3s configmap):
  default_period   = "month"  (day | week | month | year | all)
  history_limit    = 50
"""

from datetime import date, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import polymarket_db as db

router = APIRouter()


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _period_start(period: str) -> str | None:
    today = date.today()
    if period == "day":
        return (today - timedelta(days=1)).isoformat()
    elif period == "week":
        return (today - timedelta(weeks=1)).isoformat()
    elif period == "month":
        return today.replace(day=1).isoformat()
    elif period == "year":
        return today.replace(month=1, day=1).isoformat()
    return None  # "all"


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    period = task.scope.get("period", "month")
    limit = int(task.scope.get("history_limit", 50))
    since = _period_start(period)

    # Fetch resolved trades
    where = "WHERE resolved_at IS NOT NULL"
    params: list = []
    if since:
        params.append(since)
        where += f" AND resolved_at >= ${len(params)}"

    trades = await db.fetch(
        f"""
        SELECT
            condition_id,
            question,
            side,
            size,
            entry_price,
            exit_price,
            realized_pnl,
            resolved_at
        FROM trades
        {where}
        ORDER BY resolved_at DESC
        LIMIT ${len(params) + 1}
        """,
        *params,
        limit,
    )

    if trades is None:
        return {
            "period": period,
            "trade_count": 0,
            "stats": {},
            "confidence": 0.3,
            "method": "no_data",
            "note": "Polymarket DB not available",
        }

    if not trades:
        return {
            "period": period,
            "trade_count": 0,
            "stats": {"total_pnl": 0.0, "win_rate": 0.0},
            "confidence": 0.9,
            "method": "polymarket_db",
        }

    pnls = [float(t["realized_pnl"] or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) if pnls else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None

    best = max(trades, key=lambda t: float(t["realized_pnl"] or 0))
    worst = min(trades, key=lambda t: float(t["realized_pnl"] or 0))

    # Daily PnL for the period
    pnl_daily = await db.fetch(
        f"""
        SELECT pnl_date, realized_pnl, unrealized_pnl, total_pnl
        FROM pnl_daily
        {"WHERE pnl_date >= $1" if since else ""}
        ORDER BY pnl_date DESC
        LIMIT 30
        """,
        *([since] if since else []),
    )

    return {
        "period": period,
        "trade_count": len(trades),
        "stats": {
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 3) if profit_factor else None,
        },
        "best_trade": {
            "question": best["question"],
            "pnl": round(float(best["realized_pnl"] or 0), 2),
        },
        "worst_trade": {
            "question": worst["question"],
            "pnl": round(float(worst["realized_pnl"] or 0), 2),
        },
        "recent_trades": [
            {
                "question": t["question"],
                "side": t["side"],
                "pnl": round(float(t["realized_pnl"] or 0), 2),
                "resolved_at": str(t["resolved_at"]) if t["resolved_at"] else None,
            }
            for t in trades[:10]
        ],
        "pnl_daily": [
            {
                "date": str(r["pnl_date"]),
                "realized_pnl": float(r["realized_pnl"] or 0),
                "total_pnl": float(r["total_pnl"] or 0),
            }
            for r in (pnl_daily or [])
        ],
        "confidence": 0.9,
        "method": "polymarket_db",
    }
