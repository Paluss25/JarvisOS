"""Memory-box dual-write helper for Email Intelligence Agent extractions.

Writes email intelligence extractions, entity detections, and
classification insights to memory-box for vector + graph storage.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://10.10.200.139:8000")


async def write_memory(
    text: str,
    user_id: str = "email_intelligence_agent",
    entities: list[dict] | None = None,
    relations: list[dict] | None = None,
):
    """Write a memory entry to memory-box."""
    payload = {
        "text": text,
        "user_id": user_id,
        "session_id": f"email_intelligence_agent-{__import__('datetime').date.today().isoformat()}",
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


async def write_extraction_event(
    text: str,
    sender: str | None = None,
    classification: str | None = None,
    extracted_entities: list[str] | None = None,
):
    """Write an email intelligence extraction to memory-box for pattern tracking."""
    prefix = "[EMAIL EXTRACTION]"
    if classification:
        prefix += f" Classification: {classification}."
    if sender:
        prefix += f" Sender: {sender}."
    full_text = f"{prefix} {text[:400]}"
    entities = [{"name": e, "type": "EmailEntity"} for e in (extracted_entities or [])]
    if not entities:
        entities = [{"name": "email-extraction", "type": "EmailEntity"}]
    relations = []
    await write_memory(full_text, entities=entities, relations=relations)
