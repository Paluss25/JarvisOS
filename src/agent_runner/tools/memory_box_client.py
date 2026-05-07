from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_BOX_URL = "http://10.10.200.139:8000"
MEMORY_COLLECTION = "memory"


async def query_agent_memory(
    agent_id: str,
    query: str,
    *,
    agent_filter: str | None = None,
    limit: int = 10,
) -> dict:
    query = query.strip()
    if not query:
        return {"error": "query is required", "results": []}

    limit = max(1, min(int(limit or 10), 100))
    url = os.environ.get("MEMORY_BOX_URL", DEFAULT_MEMORY_BOX_URL)

    payload: dict = {
        "query": query,
        "collection": MEMORY_COLLECTION,
        "top_k": limit,
    }
    if agent_filter:
        payload["user"] = agent_filter

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{url}/query", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        logger.warning(
            "query_agent_memory[%s]: HTTP %d from memory-box — %s",
            agent_id,
            status_code,
            exc,
        )
        return {"error": f"memory-box returned HTTP {status_code}", "results": []}
    except Exception as exc:
        logger.warning("query_agent_memory[%s]: request failed — %s", agent_id, exc)
        return {"error": str(exc), "results": []}

    raw = data.get("results", []) if isinstance(data, dict) else []
    results = [
        {
            "content": r.get("text", ""),
            "score": r.get("score", 0.0),
            "date": r.get("date", ""),
            "session": r.get("session", ""),
        }
        for r in raw
    ]

    return {
        "query": query,
        "agent_filter": agent_filter,
        "count": len(results),
        "results": results,
    }
