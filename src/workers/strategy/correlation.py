"""correlation-engine sub-agent (P4.T4).

Lightweight passthrough that surfaces the latest cross-asset correlation
matrix from the cfo-data-service sidecar. Heavy computation lives on the
sidecar (`CorrelationEngine`) and runs on a weekly Celery schedule
(Mondays 06:15 Europe/Rome).

Scope flags:
  * scope.recompute = true   → trigger an on-demand recompute via
                                POST /analytics/correlation/recompute.
  * scope.window_days = 90   → window passed to the recompute (clamped
                                30-730 server-side).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared.cfo_sidecar import fetch_correlation_matrix

router = APIRouter()
logger = logging.getLogger(__name__)


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    scope = task.scope or {}
    recompute = bool(scope.get("recompute", False))
    window_days = int(scope.get("window_days", 90))

    try:
        matrix = await fetch_correlation_matrix(
            recompute=recompute,
            window_days=window_days,
        )
    except Exception as exc:
        logger.exception("correlation-engine: sidecar fetch failed")
        return {
            "status": "error",
            "subagent": "correlation-engine",
            "error": str(exc),
        }

    return {
        "status": "ok",
        "subagent": "correlation-engine",
        "as_of": matrix.get("as_of"),
        "window_days": matrix.get("window_days"),
        "asset_count": matrix.get("asset_count"),
        "symbols": matrix.get("symbols"),
        "asset_classes": matrix.get("asset_classes"),
        "matrix": matrix.get("matrix"),
        "recompute_triggered": recompute,
    }
