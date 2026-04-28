"""macro-scenario sub-agent (skeleton — implemented in P4.T3).

Goal: simulate impact of a macro scenario (e.g., "Fed +50bps in June")
on portfolio drawdown and produce a rebalance proposal.
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
        "subagent": "macro-scenario",
        "phase": "P4.T3",
        "note": "Skeleton stub — historical correlation simulator pending.",
    }
