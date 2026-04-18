"""BTC Fiscal API client — http://10.10.200.119:8080 (configurable via BTC_FISCAL_API_URL)."""

import os
from typing import Any

import httpx

_BASE = os.environ.get("BTC_FISCAL_API_URL", "http://10.10.200.119:8080").rstrip("/")
_TIMEOUT = 15.0


async def _get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{_BASE}{path}")
        resp.raise_for_status()
        return resp.json()


async def get_balance() -> dict:
    """Aggregated BTC balance across all tracked wallets."""
    return await _get("/balance")


async def get_wallets() -> list:
    """List all tracked wallets (xpub or address)."""
    return await _get("/wallets")


async def get_addresses() -> list:
    """List all derived addresses with individual balances."""
    return await _get("/addresses")


async def get_transactions(year: int | None = None) -> list:
    """All transactions, optionally filtered by year."""
    path = f"/transactions?year={year}" if year else "/transactions"
    return await _get(path)


async def get_quadro_w(year: int) -> dict:
    """Italian Quadro W fiscal report for the given tax year."""
    return await _get(f"/report/{year}/quadro-w")
