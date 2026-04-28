"""opportunity-scanner sub-agent (skeleton — implemented in P4.T6).

Goal: daily 09:00 (Warren cron) scan for RSI extremes, dividend yield
threshold, news sentiment outliers, macro release triggers. Use Opus
thinking to rank top-5 opportunities. Emit signals with priority.
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
        "subagent": "opportunity-scanner",
        "phase": "P4.T6",
        "note": "Skeleton stub — RSI + sentiment + macro scan + Opus ranking pending.",
    }
