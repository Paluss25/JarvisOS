"""Memory extractor + classifier — extract memory candidates from agent turns."""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_TYPES = ("fact", "preference", "feedback", "context", "action", "episode")

_PROMPT_TEMPLATE = """\
You are a memory extraction assistant. Given an agent conversation turn, extract
memory candidates and classify each one.

Agent turn:
USER: {message}
AGENT: {response}

Extract every piece of information worth remembering. For each, return:
- text: the memory in 1–2 sentences
- type: one of {types}
- scope: "agent" (private to this agent) or "domain:{{name}}" for shared domains

Return JSON array: [{{"text":"...","type":"...","scope":"..."}}]
If nothing worth remembering, return [].
"""


async def extract_memories(agent_id: str, message: str, response: str) -> list[dict[str, Any]]:
    """Run Gemini Flash extraction on one agent turn.

    Falls back to Haiku if GEMINI_API_KEY is missing.
    Returns a list of {text, type, scope} dicts.
    """
    prompt = _PROMPT_TEMPLATE.format(
        message=message[:2000],
        response=response[:2000],
        types=", ".join(_MEMORY_TYPES),
    )

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        return await _extract_gemini(prompt, gemini_key)

    # Haiku fallback
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        return await _extract_haiku(prompt, anthropic_key)

    logger.warning("extractor: no LLM API key — skipping memory extraction for %s", agent_id)
    return []


async def _extract_gemini(prompt: str, api_key: str) -> list[dict]:
    from google import genai

    try:
        client = genai.Client(api_key=api_key)
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        return json.loads(resp.text) or []
    except Exception as exc:
        logger.warning("extractor: Gemini extraction failed — %s", exc)
        return []


async def _extract_haiku(prompt: str, api_key: str) -> list[dict]:
    import anthropic

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end]) or []
    except Exception as exc:
        logger.warning("extractor: Haiku extraction failed — %s", exc)
    return []
