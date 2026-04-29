"""rebalancing-advisor sub-agent (P4.T5).

Computes a rebalance proposal grounded in the live portfolio snapshot,
the user's target allocation, and (optionally) the P3.T3 portfolio
optimizer reference. If any asset class is outside the configured band,
emits an approval_request of type=capital_move so the user can confirm
before any real-money action.

Heavy logic lives sidecar-side (`RebalancingService`); this worker is
the orchestrator that decides whether to escalate to HITL approval.

Scope flags:
  * scope.target_allocation = {asset_class: pct, ...}    optional override
  * scope.band_pct          = 2.0                        ±band, default 2 pp
  * scope.lookback_days     = 365                        optimizer lookback
  * scope.emit_approval     = true                       create approval_request
                                                          when out_of_band
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared.cfo_sidecar import (
    create_approval,
    fetch_rebalance_advice,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _summary(advice: dict[str, Any]) -> str:
    out_of_band = advice.get("out_of_band") or []
    if not out_of_band:
        return "Portfolio within target bands — no rebalance needed."
    n_trades = len(advice.get("paper_trades") or [])
    classes = ", ".join(out_of_band)
    return (
        f"Rebalance proposed: {n_trades} action(s) across {classes}. "
        f"Target band ±{advice.get('band_pct', 2.0):.1f}pp. NAV: "
        f"EUR {float(advice.get('total_eur') or 0):,.2f}."
    )


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    scope = task.scope or {}
    target_allocation = scope.get("target_allocation")
    band_pct = float(scope.get("band_pct", 2.0))
    lookback_days = int(scope.get("lookback_days", 365))
    emit_approval = bool(scope.get("emit_approval", True))

    try:
        advice = await fetch_rebalance_advice(
            target_allocation=target_allocation,
            band_pct=band_pct,
            lookback_days=lookback_days,
        )
    except Exception as exc:
        logger.exception("rebalancing-advisor: sidecar advice failed")
        return {
            "status": "error",
            "subagent": "rebalancing-advisor",
            "error": str(exc),
        }

    summary = _summary(advice)
    out_of_band = advice.get("out_of_band") or []

    approval_record: dict[str, Any] | None = None
    if emit_approval and out_of_band:
        try:
            approval_record = await create_approval(
                request_type="capital_move",
                requested_by="warren",
                summary=summary,
                payload={
                    "advice": advice,
                    "scope": {
                        "band_pct": band_pct,
                        "lookback_days": lookback_days,
                        "target_allocation": target_allocation,
                    },
                },
            )
        except Exception as exc:
            logger.warning("rebalancing-advisor: approval persist failed — %s", exc)
            approval_record = {"persisted": False, "error": str(exc)}

    return {
        "status": "ok",
        "subagent": "rebalancing-advisor",
        "summary": summary,
        "within_band": advice.get("within_band"),
        "out_of_band": out_of_band,
        "current_allocation_pct": advice.get("current_allocation_pct"),
        "target_allocation_pct": advice.get("target_allocation_pct"),
        "deltas_pct": advice.get("deltas_pct"),
        "paper_trades": advice.get("paper_trades", []),
        "optimizer": advice.get("optimizer", {}),
        "approval": approval_record,
    }
