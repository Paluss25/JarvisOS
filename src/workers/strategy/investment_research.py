"""investment-research sub-agent (P4.T2).

Given a `symbol` (or `asset_id`), aggregates context from the cfo-data-service
sidecar (news + macro + Perplexity grounded fundamentals) and asks Claude
Sonnet via the Claude CLI for a 500-word thesis with bull/bear/base
scenarios. The synthesis is persisted as a `signal_type=research` row in
the cfo signals table with the full structured output as payload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared.cfo_sidecar import (
    create_signal,
    fetch_research_fundamentals,
)
from workers.shared.redaction import redact

router = APIRouter()
logger = logging.getLogger(__name__)

_DEFAULT_MODEL = os.environ.get("CFO_RESEARCH_CLAUDE_MODEL", "claude-sonnet-4-6")
_CLAUDE_TIMEOUT_S = float(os.environ.get("CFO_RESEARCH_CLAUDE_TIMEOUT", "180"))


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _extract_first_json(text: str) -> dict[str, Any]:
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("Claude output did not contain a JSON object")


async def _run_claude_synthesis(symbol: str, context: dict[str, Any]) -> dict[str, Any]:
    """Run Claude CLI to synthesize a 500-word thesis + scenarios.

    The prompt asks for strict JSON so the output is machine-readable.
    """
    schema_hint = (
        '{"thesis":"...","bull_case":"...","bear_case":"...","base_case":"...",'
        '"confidence_score":0.0,"recommendation":"buy|hold|sell","key_risks":["..."],'
        '"sources":["..."]}'
    )
    safe_context = redact(context)
    prompt = (
        f"You are a senior equity-research analyst writing for a single private investor. "
        f"Asset: {symbol}.\n\n"
        f"Context (recent news related to the asset, current macro indicators, "
        f"Perplexity-grounded fundamentals with citations):\n{json.dumps(safe_context, ensure_ascii=False)}\n\n"
        "Produce a JSON object with exactly these fields:\n"
        " - thesis: ~500-word narrative covering the company/asset state, valuation context, and forward outlook.\n"
        " - bull_case / bear_case / base_case: 1 paragraph each, mutually exclusive scenarios.\n"
        " - confidence_score: float in [0.0, 1.0] reflecting evidence quality (low if news_related is empty).\n"
        " - recommendation: one of buy | hold | sell.\n"
        " - key_risks: array of 3-5 short bullet strings.\n"
        " - sources: array of URLs you actually relied on (from the input context).\n\n"
        f"Return ONLY the JSON object. Schema:\n{schema_hint}"
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
        raise RuntimeError("Claude CLI synthesis timed out") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Claude CLI synthesis failed: {detail}")

    raw = stdout.decode("utf-8", errors="replace").strip()
    # Claude --output-format=json wraps the assistant text inside a JSON envelope:
    # {"role":"assistant","content":"...","model":"...", ...}
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
    return _extract_first_json(assistant_text)


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    scope = task.scope or {}
    symbol = (scope.get("symbol") or "").strip().upper()
    if not symbol:
        return {
            "status": "error",
            "subagent": "investment-research",
            "error": "task.scope.symbol is required (e.g., AAPL, BTC).",
        }

    asset_id = scope.get("asset_id")
    period_hint = scope.get("period_hint")
    persist = bool(scope.get("persist", True))

    try:
        context = await fetch_research_fundamentals(
            symbol=symbol,
            period_hint=period_hint,
        )
    except Exception as exc:  # network / sidecar error
        logger.exception("investment-research: sidecar fundamentals failed")
        return {
            "status": "error",
            "subagent": "investment-research",
            "stage": "fundamentals",
            "error": str(exc),
        }

    try:
        synthesis = await _run_claude_synthesis(symbol, context)
    except Exception as exc:
        logger.exception("investment-research: claude synthesis failed")
        return {
            "status": "error",
            "subagent": "investment-research",
            "stage": "synthesis",
            "error": str(exc),
            "context_summary": {
                "news_related": len(context.get("news_related") or []),
                "macro_indicators": len(context.get("macro_indicators") or []),
                "perplexity_available": bool((context.get("perplexity") or {}).get("available")),
            },
        }

    confidence = float(synthesis.get("confidence_score") or 0.5)
    confidence = max(0.0, min(1.0, confidence))
    severity = "warning" if confidence >= 0.75 else "info"

    signal_payload = {
        "symbol": symbol,
        "synthesis": synthesis,
        "context_summary": {
            "news_related_count": len(context.get("news_related") or []),
            "macro_indicators_count": len(context.get("macro_indicators") or []),
            "perplexity_available": bool((context.get("perplexity") or {}).get("available")),
            "perplexity_citations": (context.get("perplexity") or {}).get("citations", []),
        },
        "confidence_score": confidence,
    }

    persisted_signal: dict[str, Any] | None = None
    if persist:
        try:
            persisted_signal = await create_signal(
                signal_type="research",
                severity=severity,
                asset_id=asset_id,
                payload=signal_payload,
            )
        except Exception as exc:
            logger.warning("investment-research: signal persist failed — %s", exc)
            persisted_signal = {"persisted": False, "error": str(exc)}

    return {
        "status": "ok",
        "subagent": "investment-research",
        "symbol": symbol,
        "thesis": synthesis.get("thesis"),
        "scenarios": {
            "bull": synthesis.get("bull_case"),
            "bear": synthesis.get("bear_case"),
            "base": synthesis.get("base_case"),
        },
        "recommendation": synthesis.get("recommendation"),
        "confidence_score": confidence,
        "key_risks": synthesis.get("key_risks", []),
        "sources": synthesis.get("sources", []),
        "signal": persisted_signal,
    }
