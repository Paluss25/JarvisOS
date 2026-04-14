"""Client for the centralized memory API (memory-api.prova9x.com).

Shared Qdrant + Graphiti backend — used by both Jarvis and Claude Code.
user_id="jarvis" keeps Jarvis memories distinct from "claude-code" entries.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0  # seconds


class MemoryAPIClient:
    """Async HTTP client for memory-api.prova9x.com.

    Endpoints:
    - POST /memory/write  — persist a memory
    - POST /memory/query  — semantic search

    Usage::

        client = MemoryAPIClient("https://memory-api.prova9x.com", "jarvis")
        await client.write("Paluss deployed Jarvis today")
        results = await client.query("recent deployments")
    """

    def __init__(self, base_url: str, user_id: str = "jarvis"):
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    async def write(self, content: str, metadata: dict | None = None) -> dict:
        """Persist a memory to the centralized store.

        Args:
            content: The text to store.
            metadata: Optional key-value metadata attached to the memory.

        Returns:
            The API response dict ({"id": ..., "status": "ok"}).

        Raises:
            httpx.HTTPStatusError: on 4xx/5xx responses.
        """
        payload: dict[str, Any] = {
            "content": content,
            "user_id": self.user_id,
        }
        if metadata:
            payload["metadata"] = metadata

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(f"{self.base_url}/memory/write", json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.debug("memory_api: write ok — %s", data.get("id"))
            return data

    async def query(self, query: str, top_k: int = 5) -> list[dict]:
        """Semantic search across all memories (shared with Claude Code).

        Args:
            query: Natural-language search string.
            top_k: Maximum number of results to return.

        Returns:
            List of memory dicts, each with at minimum {"content": ..., "score": ...}.
        """
        payload = {
            "query": query,
            "user_id": self.user_id,
            "top_k": top_k,
        }

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(f"{self.base_url}/memory/query", json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Accept both {"results": [...]} and bare list responses
        if isinstance(data, list):
            return data
        return data.get("results", [])

    async def health_check(self) -> bool:
        """Return True if memory-api is reachable and healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code < 400
        except Exception as exc:
            logger.warning("memory_api: health check failed — %s", exc)
            return False
