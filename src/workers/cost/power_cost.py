"""Power Cost sub-agent — electricity consumption and cost analysis.

Queries Prometheus for hwmon power metrics. Falls back to CPU-core
estimate if hwmon is unavailable.

Tunable defaults (from K3s configmap):
  default_electricity_rate_eur = 0.25  EUR/kWh
  watts_per_core_estimate      = 10    W (CPU fallback)
  confidence_hwmon             = 0.9
  confidence_cpu_fallback      = 0.6
"""

import os

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_PROMETHEUS_URL = lambda: os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
_TIMEOUT = 10.0

_HOURS_PER_MONTH = 730.0


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


async def _query_prometheus(expr: str) -> float | None:
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
            return None
    except Exception:
        return None


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    electricity_rate = float(task.scope.get("electricity_rate_eur", 0.25))
    watts_per_core = float(task.scope.get("watts_per_core_estimate", 10))

    # 1. Try hwmon power reading (node_exporter exposes this)
    watts = await _query_prometheus(
        "sum(node_hwmon_power_average_watt)"
    )
    method = "hwmon"
    confidence = 0.9

    # 2. Fallback: estimate from CPU core count
    if watts is None or watts == 0:
        cpu_cores = await _query_prometheus(
            "count(node_cpu_seconds_total{mode='idle'})"
        )
        if cpu_cores is not None and cpu_cores > 0:
            watts = cpu_cores * watts_per_core
            method = "cpu_core_estimate"
            confidence = 0.6
        else:
            return {
                "watts": None,
                "cost_eur_per_hour": None,
                "cost_eur_per_day": None,
                "cost_eur_per_month": None,
                "electricity_rate_eur_per_kwh": electricity_rate,
                "confidence": 0.3,
                "method": "no_data",
                "note": "Prometheus unavailable — cannot estimate power costs",
            }

    # kWh calculations
    kwh_per_hour = watts / 1000
    cost_per_hour = kwh_per_hour * electricity_rate
    cost_per_day = cost_per_hour * 24
    cost_per_month = cost_per_hour * _HOURS_PER_MONTH

    return {
        "watts": round(watts, 1),
        "kwh_per_hour": round(kwh_per_hour, 4),
        "cost_eur_per_hour": round(cost_per_hour, 4),
        "cost_eur_per_day": round(cost_per_day, 3),
        "cost_eur_per_month": round(cost_per_month, 2),
        "electricity_rate_eur_per_kwh": electricity_rate,
        "confidence": confidence,
        "method": method,
    }
