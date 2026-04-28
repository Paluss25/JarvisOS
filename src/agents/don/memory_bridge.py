"""Memory-box dual-write helper for nutrition events.

Writes to memory-box HTTP API (Qdrant vectors + FalkorDB graph)
alongside the primary filesystem workspace writes.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://10.10.200.139:8000")


async def write_meal_memory(
    text: str,
    user_id: str = "don",
    entities: list[dict] | None = None,
    relations: list[dict] | None = None,
):
    """Write a meal event to memory-box for vector + graph storage."""
    payload = {
        "text": text,
        "user_id": user_id,
        "session_id": f"nutrition-{__import__('datetime').date.today().isoformat()}",
        "entities": entities or [],
        "relations": relations or [],
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{MEMORY_BOX_URL}/write", json=payload)
            resp.raise_for_status()
            logger.info("memory-box write OK: %s", text[:80])
    except Exception as exc:
        logger.warning("memory-box write failed (non-fatal): %s", exc)
