import os
from datetime import datetime
from typing import Any

import httpx

_TIMEOUT = 20.0


def sidecar_url() -> str:
    return os.environ.get("CFO_SIDECAR_URL", "http://cfo-data-service:8000").rstrip("/")


def auth_headers() -> dict[str, str]:
    token = os.environ.get("CFO_CLI_TOKEN", "")
    if not token:
        raise ValueError("CFO_CLI_TOKEN not configured")
    return {"Authorization": f"Bearer {token}"}


async def fetch_ledger_events(
    *,
    source: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    if source:
        params["source"] = source
    if from_date:
        params["from_date"] = from_date.isoformat()
    if to_date:
        params["to_date"] = to_date.isoformat()

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f"{sidecar_url()}/ledger/events",
            params=params,
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def fetch_live_quote(*, symbol: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f"{sidecar_url()}/prices/live/{symbol.upper()}",
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def fetch_market_news(*, limit: int = 10) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f"{sidecar_url()}/news/articles",
            params={"limit": limit},
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("articles", [])


async def fetch_macro_indicators(*, limit: int = 25) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f"{sidecar_url()}/macro/indicators",
            params={"limit": limit},
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json().get("indicators", [])


async def fetch_research_fundamentals(
    *,
    symbol: str,
    period_hint: str | None = None,
    news_limit: int = 25,
    macro_limit: int = 12,
    timeout: float = 60.0,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "symbol": symbol,
        "news_limit": news_limit,
        "macro_limit": macro_limit,
    }
    if period_hint:
        body["period_hint"] = period_hint
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{sidecar_url()}/research/fundamentals",
            json=body,
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def fetch_rebalance_advice(
    *,
    target_allocation: dict[str, float] | None = None,
    band_pct: float = 2.0,
    lookback_days: int = 365,
    timeout: float = 60.0,
) -> dict[str, Any]:
    body: dict[str, Any] = {"band_pct": band_pct, "lookback_days": lookback_days}
    if target_allocation is not None:
        body["target_allocation"] = target_allocation
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{sidecar_url()}/analytics/rebalance",
            json=body,
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def create_approval(
    *,
    request_type: str,
    requested_by: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "request_type": request_type,
        "requested_by": requested_by,
        "summary": summary,
    }
    if payload is not None:
        body["payload"] = payload
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{sidecar_url()}/approvals",
            json=body,
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def decide_approval(
    approval_id: int,
    *,
    decision: str,
    decided_by: str,
    notes: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Approve or reject a pending approval request via the sidecar."""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    body: dict[str, Any] = {"decision": decision, "decided_by": decided_by}
    if notes is not None:
        body["notes"] = notes
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{sidecar_url()}/approvals/{approval_id}/decide",
            json=body,
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def fetch_holdings(*, timeout: float = 30.0) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{sidecar_url()}/portfolio/holdings",
            headers=auth_headers(),
        )
        response.raise_for_status()
        data = response.json()
    if isinstance(data, list):
        return data
    return data.get("holdings") or data.get("positions") or []


async def fetch_technical_analysis(
    symbol: str,
    *,
    indicators: str = "rsi",
    limit: int = 100,
    timeout: float = 30.0,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{sidecar_url()}/analytics/ta/{symbol.upper()}",
            params={"indicators": indicators, "limit": limit},
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def fetch_correlation_matrix(*, recompute: bool = False, window_days: int = 90, timeout: float = 60.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        if recompute:
            response = await client.post(
                f"{sidecar_url()}/analytics/correlation/recompute",
                params={"window": window_days},
                headers=auth_headers(),
            )
        else:
            response = await client.get(
                f"{sidecar_url()}/analytics/correlation",
                headers=auth_headers(),
            )
        response.raise_for_status()
        return response.json()


async def fetch_portfolio_snapshot(*, timeout: float = 30.0) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            f"{sidecar_url()}/portfolio/snapshot",
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json()


async def create_signal(
    *,
    signal_type: str,
    severity: str = "info",
    asset_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"signal_type": signal_type, "severity": severity}
    if asset_id is not None:
        body["asset_id"] = asset_id
    if payload is not None:
        body["payload"] = payload
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f"{sidecar_url()}/signals",
            json=body,
            headers=auth_headers(),
        )
        response.raise_for_status()
        return response.json()
