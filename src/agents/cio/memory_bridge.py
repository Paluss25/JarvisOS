"""Memory-box dual-write helper for Timothy CIO infrastructure events.

Writes infrastructure events, system changes, and operational
insights to memory-box for vector + graph storage.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://10.10.200.139:8000")


async def write_memory(
    text: str,
    user_id: str = "cio",
    entities: list[dict] | None = None,
    relations: list[dict] | None = None,
):
    """Write a memory entry to memory-box."""
    payload = {
        "text": text,
        "user_id": user_id,
        "session_id": f"cio-{__import__('datetime').date.today().isoformat()}",
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


async def write_infra_event(
    text: str,
    service: str | None = None,
    event_type: str | None = None,
):
    """Write an infrastructure event to memory-box for operational tracking."""
    prefix = "[INFRA EVENT]"
    if event_type:
        prefix += f" Type: {event_type}."
    if service:
        prefix += f" Service: {service}."
    full_text = f"{prefix} {text[:400]}"
    entities = [{"name": service or "infrastructure", "type": "Infrastructure"}]
    relations = []
    await write_memory(full_text, entities=entities, relations=relations)
