"""Memory-box dual-write helper for DrHouse health decisions.

Writes health decisions, medical gate activations, and cross-domain
insights to memory-box for vector + graph storage.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://10.10.200.139:8000")


async def write_health_memory(
    text: str,
    user_id: str = "drhouse",
    entities: list[dict] | None = None,
    relations: list[dict] | None = None,
):
    """Write a health decision/event to memory-box."""
    payload = {
        "text": text,
        "user_id": user_id,
        "session_id": f"drhouse-{__import__('datetime').date.today().isoformat()}",
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


async def write_medical_gate_event(
    message: str,
    status: str,
    constraints: list[str] | None = None,
):
    """Write a medical gate activation to memory-box for pattern tracking."""
    text = f"[MEDICAL GATE] Status: {status}. Input: {message[:200]}"
    if constraints:
        text += f" Constraints: {', '.join(constraints)}"
    entities = [{"name": "medical-gate", "type": "System"}]
    relations = []
    await write_health_memory(text, entities=entities, relations=relations)
