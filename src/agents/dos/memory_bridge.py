"""Memory-box dual-write helper for Roger DOS training and body composition events.

Writes training sessions, body composition changes, and sport
insights to memory-box for vector + graph storage.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://10.10.200.139:8000")


async def write_memory(
    text: str,
    user_id: str = "dos",
    entities: list[dict] | None = None,
    relations: list[dict] | None = None,
):
    """Write a memory entry to memory-box."""
    payload = {
        "text": text,
        "user_id": user_id,
        "session_id": f"dos-{__import__('datetime').date.today().isoformat()}",
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


async def write_sport_memory(
    text: str,
    activity: str | None = None,
    metrics: dict | None = None,
):
    """Write a training or body composition event to memory-box for sport tracking."""
    prefix = "[SPORT EVENT]"
    if activity:
        prefix += f" Activity: {activity}."
    if metrics:
        metrics_str = ", ".join(f"{k}={v}" for k, v in metrics.items())
        prefix += f" Metrics: {metrics_str}."
    full_text = f"{prefix} {text[:400]}"
    entities = [{"name": activity or "training", "type": "Sport"}]
    relations = []
    await write_memory(full_text, entities=entities, relations=relations)
