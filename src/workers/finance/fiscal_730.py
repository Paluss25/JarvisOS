"""Fiscal 730 Agent — Italian Modello 730 / Quadro W orchestrator.

Combines: btc-fiscal-api data + memory-box regulatory cache + news headlines.
Returns a structured 730 tax schema for the given year.
Advisory only — always recommend professional review.
"""

import os

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import btc_fiscal as bfa
from workers.shared.news import search_news

router = APIRouter()

_TIMEOUT = 10.0


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


async def _memory_regulatory_check(query: str) -> str | None:
    """Query memory-box HTTP API for past regulatory notes.

    Expected memory-box HTTP API (once available):
      POST {MEMORY_BOX_URL}/memory/query
      Body: {"query": str, "user": str, "top_k": int}
      Response: {"results": [{"content": str, ...}, ...], ...}
    """
    url = os.environ.get("MEMORY_BOX_URL", "").rstrip("/")
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{url}/memory/query",
                json={"query": query, "user": "cfo", "top_k": 3},
            )
            if resp.is_success:
                body = resp.json()
                chunks = [
                    r.get("content") or r.get("chunk") or r.get("text") or ""
                    for r in body.get("results", [])
                ]
                return "\n---\n".join(c for c in chunks if c) or None
    except Exception:
        return None
    return None


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    year = task.scope.get("year")
    if not year:
        from datetime import date
        year = date.today().year - 1  # previous fiscal year

    year = int(year)
    result: dict = {"fiscal_year": year, "advisory_only": True}
    errors: list[str] = []

    # --- BTC data from btc-fiscal-api ---
    try:
        balance = await bfa.get_balance()
        txns = await bfa.get_transactions(year=year)
        quadro_w = await bfa.get_quadro_w(year)

        result["btc_balance"] = balance
        result["transaction_count"] = len(txns)
        result["quadro_w"] = quadro_w
    except Exception as exc:
        errors.append(f"btc_fiscal_api: {exc}")
        result["btc_balance"] = None
        result["quadro_w"] = None

    # --- memory-box — past regulatory notes ---
    memo = await _memory_regulatory_check(f"730 quadro W bitcoin {year} Italy fiscal")
    if memo:
        result["regulatory_context"] = memo

    # --- News headlines — Italian crypto tax ---
    news = await search_news(
        query=f"bitcoin tassazione Italia {year} quadro W crypto tax",
        domain="finance",
        days_back=90,
        max_results=5,
        language="it",
    )
    if news.articles:
        result["news_headlines"] = [
            {
                "title": a.title,
                "sentiment": a.sentiment_score,
                "source": a.source,
                "published_at": a.published_at,
            }
            for a in news.articles[:5]
        ]
        result["news_consensus"] = news.consensus

    # --- 730 schema summary ---
    result["schema_730"] = {
        "modello": "730",
        "sezione": "Quadro W",
        "descrizione": "Crypto-attività detenute all'estero",
        "anno_imposta": year,
        "note": (
            "Compilare con i dati del quadro_w. "
            "Imposta sostitutiva 26% sulle plusvalenze. "
            "Consulta un commercialista prima di presentare la dichiarazione."
        ),
    }

    if errors:
        result["errors"] = errors

    return result
