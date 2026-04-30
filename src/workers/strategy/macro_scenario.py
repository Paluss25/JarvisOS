"""macro-scenario sub-agent (P4.T3).

Takes a free-text macro scenario (e.g., "Fed raises 50bps in June") and
simulates the impact on the user's current portfolio. Output: per-asset-class
impact, expected portfolio drawdown, and a rebalance proposal.

Implementation: Claude Sonnet simulation grounded in
  - the current portfolio snapshot (sidecar /portfolio/snapshot)
  - the latest macro indicators (sidecar /macro/indicators)

P4.T4 will add a numerical correlation matrix; once available, this
sub-agent can swap in the math-based path while keeping the same
contract.
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
    fetch_macro_indicators,
    fetch_portfolio_snapshot,
)
from workers.shared.redaction import redact

router = APIRouter()
logger = logging.getLogger(__name__)

_DEFAULT_MODEL = os.environ.get("CFO_MACRO_CLAUDE_MODEL", "claude-sonnet-4-6")
_CLAUDE_TIMEOUT_S = float(os.environ.get("CFO_MACRO_CLAUDE_TIMEOUT", "180"))
_DEFAULT_MACRO_LIMIT = 12


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


async def _run_claude_simulation(
    scenario: str,
    portfolio: dict[str, Any],
    macro_indicators: list[dict[str, Any]],
) -> dict[str, Any]:
    schema_hint = (
        '{"by_asset_class":[{"asset_class":"...","impact_pct":0.0,"rationale":"..."}],'
        '"portfolio_drawdown_pct":0.0,"rebalance_proposal":[{"action":"reduce|increase|hold",'
        '"asset_class":"...","target_weight_pct":0.0,"rationale":"..."}],'
        '"confidence_score":0.0,"key_assumptions":["..."]}'
    )
    prompt = (
        "You are a senior macro strategist simulating the impact of a single "
        "scenario on a private investor's portfolio. Be sober, quantitative "
        "where you can, and explicit about assumptions when you can't.\n\n"
        f"Scenario: {redact(scenario)}\n\n"
        f"Current portfolio snapshot:\n{json.dumps(redact(portfolio), ensure_ascii=False)}\n\n"
        f"Latest macro indicators:\n{json.dumps(redact(macro_indicators), ensure_ascii=False)}\n\n"
        "Produce a JSON object with:\n"
        " - by_asset_class: array — for each asset class present in the portfolio, "
        "estimate impact_pct (signed percentage change in EUR value) and a 1-sentence rationale.\n"
        " - portfolio_drawdown_pct: aggregate expected EUR drawdown as a signed pct of total NAV.\n"
        " - rebalance_proposal: array of 2-5 actions. Each: action (reduce|increase|hold), "
        "asset_class, target_weight_pct (post-rebalance), 1-sentence rationale.\n"
        " - confidence_score: float [0.0, 1.0]; low if the scenario is very specific or data is sparse.\n"
        " - key_assumptions: 3-5 short bullet strings naming the assumptions you relied on.\n\n"
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
        raise RuntimeError("Claude CLI macro simulation timed out") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Claude CLI macro simulation failed: {detail}")

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
    return _extract_first_json(assistant_text)


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    scope = task.scope or {}
    scenario = (scope.get("scenario") or task.goal or "").strip()
    if not scenario:
        return {
            "status": "error",
            "subagent": "macro-scenario",
            "error": "task.scope.scenario (or task.goal) is required.",
        }

    persist = bool(scope.get("persist", True))
    macro_limit = int(scope.get("macro_limit", _DEFAULT_MACRO_LIMIT))

    try:
        portfolio = await fetch_portfolio_snapshot()
    except Exception as exc:
        logger.exception("macro-scenario: portfolio snapshot failed")
        return {
            "status": "error",
            "subagent": "macro-scenario",
            "stage": "portfolio",
            "error": str(exc),
        }

    try:
        macro_indicators = await fetch_macro_indicators(limit=macro_limit)
    except Exception as exc:
        logger.exception("macro-scenario: macro indicators failed")
        return {
            "status": "error",
            "subagent": "macro-scenario",
            "stage": "macro",
            "error": str(exc),
        }

    try:
        simulation = await _run_claude_simulation(scenario, portfolio, macro_indicators)
    except Exception as exc:
        logger.exception("macro-scenario: claude simulation failed")
        return {
            "status": "error",
            "subagent": "macro-scenario",
            "stage": "simulation",
            "error": str(exc),
        }

    confidence = float(simulation.get("confidence_score") or 0.5)
    confidence = max(0.0, min(1.0, confidence))
    drawdown_pct = float(simulation.get("portfolio_drawdown_pct") or 0.0)
    severity = "warning" if abs(drawdown_pct) >= 5.0 else "info"

    signal_payload = {
        "scenario": scenario,
        "simulation": simulation,
        "context_summary": {
            "portfolio_total_eur": (portfolio.get("total_eur") or portfolio.get("net_worth_eur")),
            "macro_indicators_count": len(macro_indicators),
        },
        "confidence_score": confidence,
    }

    persisted_signal: dict[str, Any] | None = None
    if persist:
        try:
            persisted_signal = await create_signal(
                signal_type="macro_scenario",
                severity=severity,
                payload=signal_payload,
            )
        except Exception as exc:
            logger.warning("macro-scenario: signal persist failed — %s", exc)
            persisted_signal = {"persisted": False, "error": str(exc)}

    return {
        "status": "ok",
        "subagent": "macro-scenario",
        "scenario": scenario,
        "by_asset_class": simulation.get("by_asset_class", []),
        "portfolio_drawdown_pct": drawdown_pct,
        "rebalance_proposal": simulation.get("rebalance_proposal", []),
        "key_assumptions": simulation.get("key_assumptions", []),
        "confidence_score": confidence,
        "signal": persisted_signal,
    }
