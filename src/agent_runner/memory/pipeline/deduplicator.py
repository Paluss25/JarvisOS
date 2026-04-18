"""Two-stage memory deduplicator — rapidfuzz pre-filter then LLM arbitration."""

import json
import logging
import os
from typing import Any

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Stage thresholds
_EXACT_THRESHOLD = 98    # ratio >= 98 → silent drop (near-duplicate)
_FUZZY_THRESHOLD = 80    # 80–97 → LLM arbitration; <80 → always ADD

_ARBITRATE_PROMPT = """\
You are a memory deduplication assistant.

Existing memory entry:
"{existing}"

Candidate new entry:
"{candidate}"

Decide how to handle the candidate. Return one of:
- "ADD"    — the candidate adds new information; store it as a new entry
- "UPDATE" — the candidate supersedes the existing entry; replace it
- "DELETE" — the existing entry is now stale; remove it (and skip the candidate)
- "NOOP"   — the candidate is redundant; discard it silently

Return JSON: {{"action": "ADD"|"UPDATE"|"DELETE"|"NOOP", "reason": "..."}}
"""


def _ratio(a: str, b: str) -> float:
    return fuzz.ratio(a.lower(), b.lower())


async def _arbitrate_llm(existing: str, candidate: str) -> dict[str, str]:
    """Ask Gemini Flash (or Haiku fallback) what to do with the candidate."""
    prompt = _ARBITRATE_PROMPT.format(existing=existing[:500], candidate=candidate[:500])

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            from google import genai

            client = genai.Client(api_key=gemini_key)
            resp = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            return json.loads(resp.text)
        except Exception as exc:
            logger.warning("deduplicator: Gemini arbitration failed — %s", exc)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        try:
            import anthropic

            aclient = anthropic.AsyncAnthropic(api_key=anthropic_key)
            msg = await aclient.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text
            start, end = text.find("{"), text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception as exc:
            logger.warning("deduplicator: Haiku arbitration failed — %s", exc)

    # Fallback: always add when LLM unavailable
    return {"action": "ADD", "reason": "no llm available"}


async def deduplicate(
    candidate: dict[str, Any],
    existing_entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Apply two-stage deduplication to a single candidate memory.

    Returns an action dict:
        {"action": "ADD",    "entry": candidate}
        {"action": "UPDATE", "replace_id": id, "entry": candidate}
        {"action": "DELETE", "replace_id": id}
        {"action": "NOOP"}

    existing_entries: list of {id, text, type, scope} from the current store.
    """
    candidate_text = candidate.get("text", "")

    for existing in existing_entries:
        existing_text = existing.get("text", "")
        ratio = _ratio(candidate_text, existing_text)

        if ratio >= _EXACT_THRESHOLD:
            logger.debug("deduplicator: near-duplicate (%.0f%%) — silent drop", ratio)
            return {"action": "NOOP"}

        if ratio >= _FUZZY_THRESHOLD:
            result = await _arbitrate_llm(existing_text, candidate_text)
            action = result.get("action", "ADD")
            logger.debug(
                "deduplicator: fuzzy match (%.0f%%) — LLM says %s (%s)",
                ratio, action, result.get("reason", "")
            )
            if action == "NOOP":
                return {"action": "NOOP"}
            if action == "UPDATE":
                return {"action": "UPDATE", "replace_id": existing.get("id"), "entry": candidate}
            if action == "DELETE":
                return {"action": "DELETE", "replace_id": existing.get("id")}
            # ADD falls through

    # Below threshold (or LLM returned ADD)
    return {"action": "ADD", "entry": candidate}
