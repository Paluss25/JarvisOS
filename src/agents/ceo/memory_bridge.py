"""Memory-box dual-write helper for Jarvis CEO strategic decisions.

Writes strategic decisions, executive actions, and cross-domain
insights to memory-box for vector + graph storage.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://10.10.200.139:8000")


async def write_memory(
    text: str,
    user_id: str = "ceo",
    entities: list[dict] | None = None,
    relations: list[dict] | None = None,
):
    """Write a memory entry to memory-box."""
    payload = {
        "text": text,
        "user_id": user_id,
        "session_id": f"ceo-{__import__('datetime').date.today().isoformat()}",
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


async def write_decision_memory(
    text: str,
    decision_type: str | None = None,
    stakeholders: list[str] | None = None,
):
    """Write a strategic decision to memory-box for executive tracking."""
    prefix = f"[STRATEGIC DECISION]"
    if decision_type:
        prefix += f" Type: {decision_type}."
    full_text = f"{prefix} {text[:400]}"
    if stakeholders:
        full_text += f" Stakeholders: {', '.join(stakeholders)}"
    entities = [{"name": "strategic-decision", "type": "Decision"}]
    relations = []
    await write_memory(full_text, entities=entities, relations=relations)
