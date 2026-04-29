"""rebalancing-advisor sub-agent (skeleton — implemented in P4.T5).

Goal: compare current allocation vs target_allocation.yaml, compute deltas
with ±2% bands, produce paper-trade plan, emit approval_request of type
capital_move.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    return {
        "status": "not_implemented",
        "subagent": "rebalancing-advisor",
        "phase": "P4.T5",
        "note": "Skeleton stub — target allocation diff + approval emit pending.",
    }
