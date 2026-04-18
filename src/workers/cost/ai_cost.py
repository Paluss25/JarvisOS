"""AI Cost sub-agent — LLM/AI infrastructure spend analysis.

Queries Prometheus for token usage metrics, applies per-model rates,
returns estimated EUR spend. Falls back to confidence=0.3 if Prometheus
is unreachable.

Tunable defaults (from K3s configmap):
  rate_claude_opus   = 15.0 $/1M tokens
  rate_claude_sonnet = 3.0
  rate_claude_haiku  = 0.25
  rate_gemini        = 0.075
  rate_llama         = 0 (self-hosted, electricity only)
"""

import os

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_PROMETHEUS_URL = lambda: os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
_TIMEOUT = 10.0

# Per-million-token rates in USD (overridable via scope)
_DEFAULT_RATES = {
    "claude_opus": 15.0,
    "claude_sonnet": 3.0,
    "claude_haiku": 0.25,
    "gemini": 0.075,
    "llama": 0.0,
}

# Prometheus metric name → model key
# Adjust to match the actual metric names in your Prometheus setup
_METRIC_MAP = {
    "litellm_total_tokens_total{model=~'.*opus.*'}": "claude_opus",
    "litellm_total_tokens_total{model=~'.*sonnet.*'}": "claude_sonnet",
    "litellm_total_tokens_total{model=~'.*haiku.*'}": "claude_haiku",
    "litellm_total_tokens_total{model=~'.*gemini.*'}": "gemini",
    "litellm_total_tokens_total{model=~'.*llama.*|.*mistral.*|.*qwen.*'}": "llama",
}


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


async def _query_prometheus(expr: str) -> float | None:
    """Run an instant query against Prometheus. Returns the scalar value or None."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_PROMETHEUS_URL()}/api/v1/query",
                params={"query": expr},
            )
            if not resp.is_success:
                return None
            body = resp.json()
            result = body.get("data", {}).get("result", [])
            if result:
                return float(result[0]["value"][1])
            return 0.0
    except Exception:
        return None


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    rates = {
        k: float(task.scope.get(f"rate_{k}", _DEFAULT_RATES[k]))
        for k in _DEFAULT_RATES
    }
    period_days = int(task.scope.get("period_days", 30))

    breakdown: list[dict] = []
    total_cost_usd = 0.0
    prometheus_available = True

    for expr_template, model_key in _METRIC_MAP.items():
        # Use increase() over the requested period to get delta tokens
        expr = f"sum(increase({expr_template}[{period_days}d]))"
        tokens = await _query_prometheus(expr)

        if tokens is None:
            prometheus_available = False
            break

        cost_usd = (tokens / 1_000_000) * rates[model_key]
        total_cost_usd += cost_usd
        breakdown.append({
            "model": model_key,
            "tokens": round(tokens),
            "rate_per_1m_usd": rates[model_key],
            "cost_usd": round(cost_usd, 4),
        })

    if not prometheus_available:
        return {
            "period_days": period_days,
            "total_cost_usd": None,
            "breakdown": [],
            "confidence": 0.3,
            "method": "no_data",
            "note": "Prometheus unavailable — cannot estimate AI costs",
        }

    # Convert USD → EUR at a fixed rate (close enough for budgeting)
    usd_eur = float(task.scope.get("usd_eur_rate", 0.92))
    total_cost_eur = total_cost_usd * usd_eur
    for item in breakdown:
        item["cost_eur"] = round(item["cost_usd"] * usd_eur, 4)

    return {
        "period_days": period_days,
        "total_cost_usd": round(total_cost_usd, 4),
        "total_cost_eur": round(total_cost_eur, 4),
        "breakdown": sorted(breakdown, key=lambda x: x["cost_usd"], reverse=True),
        "confidence": 0.9,
        "method": "prometheus",
    }
