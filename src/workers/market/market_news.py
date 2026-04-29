"""Market news sub-agent backed by CFO sidecar news ingestion."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared.cfo_sidecar import fetch_market_news

router = APIRouter()


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict[str, Any] = {}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict[str, Any]:
    limit = int(task.scope.get("limit", 10))
    try:
        articles = await fetch_market_news(limit=limit)
    except Exception as exc:
        return {"article_count": 0, "articles": [], "confidence": 0.2, "error": str(exc)}

    return {
        "article_count": len(articles),
        "articles": articles,
        "confidence": 0.85,
        "method": "cfo_sidecar_market_news",
    }
