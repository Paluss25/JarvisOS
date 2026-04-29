"""Memory-box dual-write helper for CFO financial decisions.

Writes financial decisions, budget events, and fiscal insights
to memory-box for vector + graph storage.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://10.10.200.139:8000")


async def write_memory(
    text: str,
    user_id: str = "cfo",
    entities: list[dict] | None = None,
    relations: list[dict] | None = None,
):
    """Write a memory entry to memory-box."""
    payload = {
        "text": text,
        "user_id": user_id,
        "session_id": f"cfo-{__import__('datetime').date.today().isoformat()}",
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


async def write_financial_event(
    text: str,
    category: str | None = None,
    amount: float | None = None,
):
    """Write a financial decision or event to memory-box for fiscal tracking."""
    prefix = "[FINANCIAL EVENT]"
    if category:
        prefix += f" Category: {category}."
    if amount is not None:
        prefix += f" Amount: {amount}."
    full_text = f"{prefix} {text[:400]}"
    entities = [{"name": category or "financial-event", "type": "Financial"}]
    relations = []
    await write_memory(full_text, entities=entities, relations=relations)
