"""Strategy sub-agent — Polymarket opportunity identification.

Reads market signals from DB, enriches with news, uses haiku to
generate a strategic recommendation.

Tunable defaults (from K3s configmap):
  db_limit            = 50
  top_opportunities   = 10
  news_max_results    = 5
  news_days_back      = 3
"""

import os

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import llm, polymarket_db as db
from workers.shared.news import search_news

router = APIRouter()

_TIMEOUT = 15.0

_SYSTEM = (
    "You are a Polymarket prediction market strategist. "
    "Given a list of markets with signals and news context, "
    "identify the top trading opportunities and explain your reasoning. "
    "Focus on: edge (market price vs your probability estimate), "
    "liquidity, time to resolution, and news catalysts. "
    "Return a JSON array of up to 10 objects with fields: "
    "condition_id, question, recommended_side, edge_pct, rationale (1 sentence). "
    "Return ONLY the JSON array."
)


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    db_limit = int(task.scope.get("db_limit", 50))
    top_n = int(task.scope.get("top_opportunities", 10))
    news_max = int(task.scope.get("news_max_results", 5))
    news_days = int(task.scope.get("news_days_back", 3))

    # 1. Fetch top signals from DB
    # signals_log uses market_id (not condition_id); score field is final_score
    rows = await db.fetch(
        """
        SELECT
            m.condition_id,
            sl.signal_type,
            sl.final_score                AS signal_value,
            sl.ts                         AS created_at,
            m.title                       AS question,
            m.category,
            m.close_time                  AS end_date,
            m.volume,
            ph.price_yes                  AS current_price
        FROM signals_log sl
        LEFT JOIN markets m ON sl.market_id = m.market_id
        LEFT JOIN LATERAL (
            SELECT price_yes FROM price_history
            WHERE market_id = sl.market_id
            ORDER BY ts DESC LIMIT 1
        ) ph ON true
        WHERE sl.ts > NOW() - INTERVAL '24 hours'
        ORDER BY sl.ts DESC
        LIMIT $1
        """,
        db_limit,
    )

    if rows is None:
        return {
            "opportunities": [],
            "news_context": None,
            "confidence": 0.3,
            "method": "no_data",
            "note": "Polymarket DB not available",
        }

    if not rows:
        return {
            "opportunities": [],
            "confidence": 0.3,
            "method": "no_signals",
            "note": "No signals in the last 24 hours",
        }

    # 2. Fetch news for context
    categories = list({r["category"] for r in rows if r.get("category")})
    news_query = " ".join(categories[:3]) + " prediction market" if categories else "prediction market"
    news = await search_news(
        query=news_query,
        domain="markets",
        days_back=news_days,
        max_results=news_max,
    )

    # 3. Build LLM prompt
    market_list = "\n".join(
        f"- {r['condition_id']} | {r['question']} | signal={r['signal_type']}:{r['signal_value']:.3f} | price={r['current_price']}"
        for r in rows[:20]
        if r.get("question")
    )
    news_summary = (
        "\n".join(f"- {a.title} (sentiment={a.sentiment_score:.2f})" for a in news.articles)
        if news.articles else "No relevant news."
    )

    prompt = (
        f"Markets with signals (last 24h):\n{market_list}\n\n"
        f"News context:\n{news_summary}"
    )

    opportunities = []
    try:
        import json
        raw = await llm.complete(prompt, system=_SYSTEM)
        import re
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`")
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            opportunities = parsed[:top_n]
    except Exception:
        # Fallback: return top signals without LLM ranking
        for row in rows[:top_n]:
            if row.get("question"):
                opportunities.append({
                    "condition_id": row["condition_id"],
                    "question": row["question"],
                    "signal_type": row["signal_type"],
                    "signal_value": float(row["signal_value"] or 0),
                    "current_price": float(row["current_price"] or 0),
                })

    return {
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
        "signal_count": len(rows),
        "news_consensus": news.consensus if news.articles else None,
        "confidence": 0.85 if opportunities else 0.3,
        "method": "llm" if opportunities else "fallback",
    }
