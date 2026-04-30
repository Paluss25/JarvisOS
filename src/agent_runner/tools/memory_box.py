"""Cross-agent memory query tool — searches the shared memory-box Qdrant store."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://10.10.200.139:8000"
_COLLECTION = "memory"


def create_query_memory_tool(agent_id: str):
    """Return an SDK tool entry for querying the shared memory-box store.

    Returns None if claude_agent_sdk is not available.
    """
    try:
        from claude_agent_sdk import tool as sdk_tool
    except (ImportError, AttributeError):
        return None

    SCHEMA = {
        "query": {"type": "string"},
        "agent_filter": {"type": "string", "default": ""},
        "limit": {"type": "integer", "default": 10},
    }
    DESCRIPTION = (
        "Search the shared memory store for entries across all agents. "
        "query is required. "
        "agent_filter optionally restricts to a specific agent's memories "
        "(e.g. 'coh', 'cio', 'mt', 'cos'). "
        "Returns up to limit results sorted by relevance."
    )

    @sdk_tool("query_agent_memory", DESCRIPTION, SCHEMA)
    async def query_agent_memory(args: dict) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            return {"error": "query is required", "results": []}

        agent_filter = (args.get("agent_filter") or "").strip() or None
        limit = int(args.get("limit") or 10)
        url = os.environ.get("MEMORY_BOX_URL", _DEFAULT_URL)

        payload: dict = {
            "query": query,
            "collection": _COLLECTION,
            "top_k": limit,
        }
        if agent_filter:
            payload["user"] = agent_filter

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{url}/query", json=payload)
                resp.raise_for_status()
                data = resp.json()
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

    return query_agent_memory
