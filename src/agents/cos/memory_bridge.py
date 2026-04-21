"""Memory-box dual-write helper for Chief of Staff routing decisions.

Writes email routing decisions, delegation events, and coordination
insights to memory-box for vector + graph storage.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://10.10.200.139:8000")


async def write_memory(
    text: str,
    user_id: str = "chief_of_staff",
    entities: list[dict] | None = None,
    relations: list[dict] | None = None,
):
    """Write a memory entry to memory-box."""
    payload = {
        "text": text,
        "user_id": user_id,
        "session_id": f"chief_of_staff-{__import__('datetime').date.today().isoformat()}",
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


async def write_routing_event(
    text: str,
    routed_to: str | None = None,
    routing_reason: str | None = None,
):
    """Write an email routing decision to memory-box for coordination tracking."""
    prefix = "[ROUTING EVENT]"
    if routed_to:
        prefix += f" Routed to: {routed_to}."
    if routing_reason:
        prefix += f" Reason: {routing_reason}."
    full_text = f"{prefix} {text[:400]}"
    entities = [{"name": routed_to or "routing", "type": "Routing"}]
    relations = []
    await write_memory(full_text, entities=entities, relations=relations)
