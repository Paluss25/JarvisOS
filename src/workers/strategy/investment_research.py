"""investment-research sub-agent (skeleton — implemented in P4.T2).

Goal: given an asset_id or symbol, produce a 500-word investment thesis
with bull/bear/base scenarios, citing news, macro, and Perplexity research.
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
        "subagent": "investment-research",
        "phase": "P4.T2",
        "note": "Skeleton stub — Perplexity + Claude synthesis pending.",
    }
