"""BTC Fiscal Analysis sub-agent — BTC portfolio + Italian Quadro W data."""

import os

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import btc_fiscal as bfa

router = APIRouter()

_BITPANDA_BASE = "https://api.bitpanda.com/v1"
_TIMEOUT = 15.0


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


async def _bitpanda_trades(api_key: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_BITPANDA_BASE}/trades",
                headers={"X-API-KEY": api_key},
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
    except Exception:
        return []


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    year = task.scope.get("year")
    include_bitpanda = bool(task.scope.get("include_bitpanda", False))

    result: dict = {}
    errors: list[str] = []

    # --- Balance ---
    try:
        balance = await bfa.get_balance()
        result["balance"] = balance
    except Exception as exc:
        errors.append(f"balance: {exc}")

    # --- Addresses ---
    try:
        addresses = await bfa.get_addresses()
        result["addresses"] = addresses
    except Exception as exc:
        errors.append(f"addresses: {exc}")

    # --- Transactions ---
    try:
        txns = await bfa.get_transactions(year=year)
        result["transactions"] = txns
        result["transaction_count"] = len(txns)
    except Exception as exc:
        errors.append(f"transactions: {exc}")

    # --- Quadro W (if year specified) ---
    if year:
        try:
            quadro_w = await bfa.get_quadro_w(int(year))
            result["quadro_w"] = quadro_w
            result["fiscal_year"] = year
        except Exception as exc:
            errors.append(f"quadro_w({year}): {exc}")

    # --- Bitpanda (optional) ---
    bitpanda_key = os.environ.get("BITPANDA_API_KEY", "")
    if include_bitpanda and bitpanda_key:
        trades = await _bitpanda_trades(bitpanda_key)
        result["bitpanda_trades"] = trades
        result["bitpanda_trade_count"] = len(trades)

    if errors:
        result["errors"] = errors

    return result
