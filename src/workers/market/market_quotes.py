"""Market quotes sub-agent backed by the CFO sidecar live price cache."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared.cfo_sidecar import fetch_live_quote

router = APIRouter()


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict[str, Any] = {}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    symbol = str(task.scope.get("symbol") or task.goal).strip().upper()
    if not symbol:
        return {
            "symbol": None,
            "confidence": 0.2,
            "error": "symbol is required in scope.symbol or goal",
        }

    try:
        quote = await fetch_live_quote(symbol=symbol)
    except Exception as exc:
        return {
            "symbol": symbol,
            "confidence": 0.2,
            "error": str(exc),
        }

    return {
        **quote,
        "confidence": 0.9,
        "method": "cfo_sidecar_live_quote",
    }
