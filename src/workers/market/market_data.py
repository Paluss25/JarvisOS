"""Market Data sub-agent — Polymarket active markets and prices.

Fetches from the Polymarket CLOB REST API. No DB required — live data only.

Tunable defaults (from K3s configmap):
  market_limit      = 50
  price_fetch_limit = 20
  confidence        = 0.9
  fetch_timeout_ms  = 5000
"""

import os

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_CLOB_BASE = lambda: os.environ.get("POLYMARKET_API_URL", "https://clob.polymarket.com")
_TIMEOUT = 5.0


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    market_limit = int(task.scope.get("market_limit", 50))
    price_fetch_limit = int(task.scope.get("price_fetch_limit", 20))
    category = task.scope.get("category")  # optional filter

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            params: dict = {"limit": market_limit, "active": "true"}
            if category:
                params["tag"] = category
            resp = await client.get(f"{_CLOB_BASE()}/markets", params=params)
            if not resp.is_success:
                return {
                    "market_count": 0,
                    "markets": [],
                    "confidence": 0.3,
                    "error": f"CLOB API returned {resp.status_code}",
                }
            markets_raw = resp.json()

        # Handle both list and {"data": [...]} response shapes
        if isinstance(markets_raw, dict):
            markets_raw = markets_raw.get("data", [])

        markets = []
        for m in markets_raw[:market_limit]:
            entry = {
                "condition_id": m.get("condition_id") or m.get("id"),
                "question": m.get("question") or m.get("title", ""),
                "category": m.get("tags", [None])[0] if m.get("tags") else None,
                "end_date": m.get("end_date_iso") or m.get("end_date"),
                "volume": m.get("volume"),
                "liquidity": m.get("liquidity"),
            }

            # Attach best-bid/ask if available inline
            if "tokens" in m:
                for token in m["tokens"]:
                    if token.get("outcome", "").lower() == "yes":
                        entry["yes_price"] = token.get("price")
                    elif token.get("outcome", "").lower() == "no":
                        entry["no_price"] = token.get("price")

            markets.append(entry)

        # Optionally fetch prices for top markets
        if price_fetch_limit > 0:
            markets_needing_prices = [
                m for m in markets[:price_fetch_limit]
                if m.get("yes_price") is None and m.get("condition_id")
            ]
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                for m in markets_needing_prices:
                    try:
                        pr = await client.get(
                            f"{_CLOB_BASE()}/midpoint",
                            params={"token_id": m["condition_id"]},
                        )
                        if pr.is_success:
                            m["yes_price"] = pr.json().get("mid")
                    except Exception:
                        pass

    except Exception as exc:
        return {
            "market_count": 0,
            "markets": [],
            "confidence": 0.3,
            "error": str(exc),
        }

    return {
        "market_count": len(markets),
        "markets": markets,
        "category_filter": category,
        "confidence": 0.9,
        "method": "polymarket_clob",
    }
