"""opportunity-scanner sub-agent (P4.T6).

Daily scan that surfaces ranked trading/positioning opportunities by
aggregating four signal sources:

  1. RSI extremes on the watchlist     (oversold ≤ 30, overbought ≥ 70)
  2. News sentiment outliers           (|score| ≥ threshold, default 0.8)
  3. Macro indicator releases today    (anything published in the last 24h)
  4. Dividend yield > threshold        (deferred — no structured equity
                                         fundamentals source yet; placeholder
                                         in the Opus prompt so it can flag
                                         this dimension as data-gap)

Ranking is done by Claude Opus with extended thinking. The top-5 ranked
opportunities are persisted as `signal_type=opportunity` rows for the
operator to review. Designed to be triggered by Warren's daily 09:00
cron — Warren itself sends the resulting summary to Telegram (cron lives
in P4.T7).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared.cfo_sidecar import (
    create_signal,
    fetch_holdings,
    fetch_macro_indicators,
    fetch_market_news,
    fetch_technical_analysis,
)
from workers.shared.redaction import redact

router = APIRouter()
logger = logging.getLogger(__name__)

_DEFAULT_MODEL = os.environ.get("CFO_OPPORTUNITY_CLAUDE_MODEL", "claude-opus-4-7")
_CLAUDE_TIMEOUT_S = float(os.environ.get("CFO_OPPORTUNITY_CLAUDE_TIMEOUT", "240"))
_RSI_OVERSOLD = 30.0
_RSI_OVERBOUGHT = 70.0
_DEFAULT_SENTIMENT_THRESHOLD = 0.8
_DEFAULT_TOP_N = 5


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _extract_first_json(text: str) -> Any:
    """Return the first valid JSON object or array embedded in text."""
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
            return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("Claude output did not contain a JSON value")


async def _gather_rsi_signals(symbols: list[str]) -> list[dict[str, Any]]:
    """For each symbol, fetch RSI(14) and flag oversold/overbought."""
    if not symbols:
        return []
    results = await asyncio.gather(
        *[fetch_technical_analysis(s, indicators="rsi") for s in symbols],
        return_exceptions=True,
    )
    flagged: list[dict[str, Any]] = []
    for sym, res in zip(symbols, results):
        if isinstance(res, Exception):
            logger.debug("opportunity-scanner: RSI fetch failed for %s — %s", sym, res)
            continue
        rsi = (res.get("indicators") or {}).get("rsi_14")
        if rsi is None:
            continue
        if rsi <= _RSI_OVERSOLD:
            flagged.append({"symbol": sym, "kind": "rsi_oversold", "rsi": rsi})
        elif rsi >= _RSI_OVERBOUGHT:
            flagged.append({"symbol": sym, "kind": "rsi_overbought", "rsi": rsi})
    return flagged


def _filter_sentiment_outliers(
    articles: list[dict[str, Any]],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for article in articles:
        score = article.get("sentiment_score")
        if score is None:
            continue
        try:
            score_f = float(score)
        except (TypeError, ValueError):
            continue
        if abs(score_f) >= threshold:
            out.append({
                "title": article.get("title"),
                "url": article.get("url"),
                "sentiment_score": score_f,
                "related_assets": article.get("related_assets") or [],
                "published_at": article.get("published_at"),
            })
    return out


def _filter_macro_releases_today(indicators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    out: list[dict[str, Any]] = []
    for row in indicators:
        published = row.get("published_at")
        if not published:
            continue
        try:
            ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if ts >= cutoff:
            out.append(row)
    return out


async def _rank_with_opus(
    rsi_signals: list[dict[str, Any]],
    sentiment_outliers: list[dict[str, Any]],
    macro_releases: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    """Hand all gathered signals to Opus with thinking. Return up to
    `top_n` ranked opportunities."""
    schema_hint = (
        '[{"rank":1,"symbol":"...","kind":"buy|reduce|hedge|watch",'
        '"thesis":"...","priority":"high|medium|low","confidence":0.0,'
        '"sources":["rsi_oversold","sentiment_outlier","macro_release"]}]'
    )
    prompt = (
        "You are Warren, a sober CFO scanning the market for the user's daily 09:00 "
        "opportunity briefing. You have four input streams (some may be empty):\n\n"
        f"RSI signals (oversold ≤ {_RSI_OVERSOLD}, overbought ≥ {_RSI_OVERBOUGHT}):\n"
        f"{json.dumps(redact(rsi_signals), ensure_ascii=False)}\n\n"
        f"News sentiment outliers (|score| ≥ {_DEFAULT_SENTIMENT_THRESHOLD}):\n"
        f"{json.dumps(redact(sentiment_outliers), ensure_ascii=False)}\n\n"
        f"Macro releases (last 24h):\n{json.dumps(redact(macro_releases), ensure_ascii=False)}\n\n"
        f"Current holdings (for context — favor opportunities that improve diversification):\n"
        f"{json.dumps(redact(holdings), ensure_ascii=False)}\n\n"
        f"Pick the top {top_n} opportunities. For each, return: rank, symbol, "
        "kind (buy|reduce|hedge|watch), 1-2 sentence thesis, priority "
        "(high|medium|low), confidence in [0.0, 1.0], and the source tags "
        "you relied on. If fewer than five distinct opportunities exist, "
        "return only the ones the data actually supports — do not pad. "
        "Return ONLY a JSON array. Schema:\n"
        f"{schema_hint}"
    )

    process = await asyncio.create_subprocess_exec(
        "claude",
        "-p",
        prompt,
        "--model",
        _DEFAULT_MODEL,
        "--output-format",
        "json",
        "--tools",
        "",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_CLAUDE_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise RuntimeError("Claude CLI opportunity ranking timed out") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Claude CLI opportunity ranking failed: {detail}")

    raw = stdout.decode("utf-8", errors="replace").strip()
    try:
        envelope = json.loads(raw)
        assistant_text = envelope.get("content") or envelope.get("result") or raw
        if isinstance(assistant_text, list):
            assistant_text = "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in assistant_text
            )
    except json.JSONDecodeError:
        assistant_text = raw

    parsed = _extract_first_json(assistant_text)
    if isinstance(parsed, dict):
        parsed = parsed.get("opportunities") or parsed.get("items") or [parsed]
    if not isinstance(parsed, list):
        return []
    return parsed[:top_n]


def _resolve_watchlist(holdings: list[dict[str, Any]], scope_watchlist: Any) -> list[str]:
    if isinstance(scope_watchlist, list) and scope_watchlist:
        return [str(s).strip().upper() for s in scope_watchlist if s]
    symbols: list[str] = []
    seen: set[str] = set()
    for h in holdings:
        sym = (h.get("symbol") or "").strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append(sym)
    if symbols:
        return symbols
    return ["BTC", "ETH"]  # sensible default when nothing else is known


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    scope = task.scope or {}
    sentiment_threshold = float(scope.get("sentiment_threshold", _DEFAULT_SENTIMENT_THRESHOLD))
    top_n = int(scope.get("top_n", _DEFAULT_TOP_N))
    persist = bool(scope.get("persist", True))
    news_limit = int(scope.get("news_limit", 50))
    macro_limit = int(scope.get("macro_limit", 20))

    try:
        holdings = await fetch_holdings()
    except Exception as exc:
        logger.warning("opportunity-scanner: holdings fetch failed — %s", exc)
        holdings = []

    watchlist = _resolve_watchlist(holdings, scope.get("watchlist"))

    rsi_signals_task = _gather_rsi_signals(watchlist)
    news_task = fetch_market_news(limit=news_limit)
    macro_task = fetch_macro_indicators(limit=macro_limit)

    rsi_signals, news_articles, macro_indicators = await asyncio.gather(
        rsi_signals_task,
        news_task,
        macro_task,
        return_exceptions=True,
    )
    if isinstance(rsi_signals, Exception):
        logger.warning("opportunity-scanner: RSI batch failed — %s", rsi_signals)
        rsi_signals = []
    if isinstance(news_articles, Exception):
        logger.warning("opportunity-scanner: news fetch failed — %s", news_articles)
        news_articles = []
    if isinstance(macro_indicators, Exception):
        logger.warning("opportunity-scanner: macro fetch failed — %s", macro_indicators)
        macro_indicators = []

    sentiment_outliers = _filter_sentiment_outliers(news_articles, threshold=sentiment_threshold)
    macro_releases = _filter_macro_releases_today(macro_indicators)

    try:
        ranked = await _rank_with_opus(
            rsi_signals,
            sentiment_outliers,
            macro_releases,
            holdings,
            top_n=top_n,
        )
    except Exception as exc:
        logger.exception("opportunity-scanner: ranking failed")
        return {
            "status": "error",
            "subagent": "opportunity-scanner",
            "stage": "ranking",
            "error": str(exc),
            "input_summary": {
                "watchlist_size": len(watchlist),
                "rsi_signals": len(rsi_signals),
                "sentiment_outliers": len(sentiment_outliers),
                "macro_releases": len(macro_releases),
            },
        }

    persisted: list[dict[str, Any]] = []
    if persist and ranked:
        for opp in ranked:
            severity = "warning" if str(opp.get("priority", "low")).lower() == "high" else "info"
            try:
                created = await create_signal(
                    signal_type="opportunity",
                    severity=severity,
                    payload={
                        "rank": opp.get("rank"),
                        "symbol": opp.get("symbol"),
                        "kind": opp.get("kind"),
                        "thesis": opp.get("thesis"),
                        "priority": opp.get("priority"),
                        "confidence": opp.get("confidence"),
                        "sources": opp.get("sources", []),
                        "scanned_at": datetime.now(UTC).isoformat(),
                    },
                )
                persisted.append({"id": created.get("id"), "rank": opp.get("rank")})
            except Exception as exc:
                logger.warning("opportunity-scanner: signal persist failed — %s", exc)

    return {
        "status": "ok",
        "subagent": "opportunity-scanner",
        "watchlist": watchlist,
        "input_summary": {
            "watchlist_size": len(watchlist),
            "rsi_signals": len(rsi_signals),
            "sentiment_outliers": len(sentiment_outliers),
            "macro_releases": len(macro_releases),
        },
        "ranked": ranked,
        "persisted_signals": persisted,
    }
