"""Macro indicators sub-agent backed by CFO sidecar macro ingestion."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared.cfo_sidecar import fetch_macro_indicators

router = APIRouter()


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict[str, Any] = {}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    limit = int(task.scope.get("limit", 25))
    try:
        indicators = await fetch_macro_indicators(limit=limit)
    except Exception as exc:
        return {"indicator_count": 0, "indicators": [], "confidence": 0.2, "error": str(exc)}

    return {
        "indicator_count": len(indicators),
        "indicators": indicators,
        "confidence": 0.85,
        "method": "cfo_sidecar_macro_indicators",
    }
