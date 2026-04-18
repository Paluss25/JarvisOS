"""NewsAPI.org client + keyword-based sentiment scoring.

Ported from news-research-service (TypeScript). No external LLM needed —
deterministic scoring is sufficient for worker use cases.
"""

import os
from dataclasses import dataclass
from typing import Literal

import httpx

_NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")
_NEWS_API_BASE = "https://newsapi.org/v2"
_TIMEOUT = 15.0

NewsDomain = Literal["finance", "security", "infrastructure", "general"]

_BULLISH: dict[str, list[str]] = {
    "finance": [
        "surge", "rally", "bullish", "breakout", "gains", "profit", "growth",
        "recovery", "upgrade", "beat expectations", "all-time high", "ath",
        "approval", "etf approved", "partnership", "acquisition",
        "rialzo", "crescita", "profitto", "guadagno", "record",
    ],
    "security": [
        "patch available", "vulnerability fixed", "security update",
        "threat mitigated", "compliance achieved", "audit passed",
        "zero-day patched", "encryption improved",
    ],
    "infrastructure": [
        "stable release", "performance improvement", "uptime record",
        "scaling success", "migration complete", "zero downtime",
    ],
    "general": ["positive", "success", "improvement", "growth", "innovation"],
}

_BEARISH: dict[str, list[str]] = {
    "finance": [
        "crash", "plunge", "bearish", "sell-off", "losses", "bankruptcy",
        "default", "downgrade", "recession", "dump", "rug pull", "hack",
        "exploit", "sec lawsuit", "regulation", "ban", "sanctions", "fraud",
        "crollo", "perdita", "ribasso", "crisi", "fallimento",
    ],
    "security": [
        "breach", "vulnerability", "cve", "zero-day", "ransomware", "attack",
        "exploit", "data leak", "compromised", "phishing", "malware",
        "critical vulnerability", "unpatched",
    ],
    "infrastructure": [
        "outage", "downtime", "failure", "crash", "incident",
        "degraded", "data loss", "corruption",
    ],
    "general": ["negative", "failure", "crisis", "problem", "risk", "warning"],
}

_DOMAIN_PATTERNS: list[tuple[str, list[str]]] = [
    ("finance", [
        r"bitcoin|btc|ethereum|eth|crypto|stock|market|trading|price|invest|fund|etf",
        r"polymarket|prediction market|odds|betting",
        r"azioni|borsa|mercato|criptovalute",
    ]),
    ("security", [
        r"cve-|vulnerability|breach|ransomware|malware|phishing|zero.?day|exploit|cybersecurity|hack",
    ]),
    ("infrastructure", [
        r"kubernetes|docker|aws|azure|gcp|cloud|outage|server|devops|uptime|deploy",
    ]),
]


@dataclass
class NewsArticle:
    title: str
    description: str | None
    source: str
    url: str
    published_at: str
    domain: str
    sentiment_score: float
    confidence: float


@dataclass
class NewsSearchResult:
    articles: list[NewsArticle]
    total_results: int
    query: str
    domain: str
    avg_sentiment: float
    consensus: str  # bullish | bearish | mixed | neutral


def _classify_domain(text: str) -> str:
    import re
    lower = text.lower()
    for domain, patterns in _DOMAIN_PATTERNS:
        if any(re.search(p, lower) for p in patterns):
            return domain
    return "general"


def _score_headline(text: str, domain: str) -> tuple[float, float]:
    lower = text.lower()
    bull = sum(1 for kw in _BULLISH.get(domain, []) if kw in lower)
    bear = sum(1 for kw in _BEARISH.get(domain, []) if kw in lower)
    total = bull + bear
    if total == 0:
        return 0.0, 0.2
    score = (bull - bear) / total
    confidence = min(0.95, 0.4 + total * 0.15)
    return max(-1.0, min(1.0, score)), confidence


async def search_news(
    query: str,
    domain: str | None = None,
    days_back: int = 7,
    max_results: int = 20,
    language: str = "en",
) -> NewsSearchResult:
    """Search NewsAPI.org and return scored articles. Returns empty result if API key missing."""
    if not _NEWS_API_KEY:
        return NewsSearchResult([], 0, query, domain or "general", 0.0, "neutral")

    from datetime import datetime, timedelta, timezone
    from_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    resolved_domain = domain or _classify_domain(query)

    params = {
        "q": query,
        "from": from_date,
        "pageSize": min(max_results, 100),
        "sortBy": "relevancy",
        "language": language,
        "apiKey": _NEWS_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_NEWS_API_BASE}/everything", params=params)
            if not resp.is_success:
                return NewsSearchResult([], 0, query, resolved_domain, 0.0, "neutral")
            body = resp.json()
    except Exception:
        return NewsSearchResult([], 0, query, resolved_domain, 0.0, "neutral")

    articles = []
    for a in body.get("articles", []):
        text = f"{a.get('title', '')} {a.get('description', '')}"
        detected = domain or _classify_domain(text)
        score, conf = _score_headline(text, detected)
        articles.append(NewsArticle(
            title=a.get("title", ""),
            description=a.get("description"),
            source=a.get("source", {}).get("name", "unknown"),
            url=a.get("url", ""),
            published_at=a.get("publishedAt", ""),
            domain=detected,
            sentiment_score=score,
            confidence=conf,
        ))

    scored = [a for a in articles if a.confidence > 0.3]
    if scored:
        weighted_sum = sum(a.sentiment_score * a.confidence for a in scored)
        weight_total = sum(a.confidence for a in scored)
        avg = round(weighted_sum / weight_total, 2)
    else:
        avg = 0.0

    if avg > 0.2:
        consensus = "bullish"
    elif avg < -0.2:
        consensus = "bearish"
    elif scored:
        consensus = "mixed"
    else:
        consensus = "neutral"

    return NewsSearchResult(
        articles=articles[:max_results],
        total_results=len(articles),
        query=query,
        domain=resolved_domain,
        avg_sentiment=avg,
        consensus=consensus,
    )
