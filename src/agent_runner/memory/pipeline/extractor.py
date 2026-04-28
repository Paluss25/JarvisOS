"""Memory extractor + classifier — extract memory candidates from agent turns."""

import asyncio
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
    """Extract memory candidates from one agent turn.

    Primary: local `claude` CLI (OAuth — same auth as agents, no API cost).
    Fallback: Gemini Flash (capped at 10s to avoid quota-retry hangs).
    Returns a list of {text, type, scope} dicts.
    """
    prompt = _PROMPT_TEMPLATE.format(
        message=message[:2000],
        response=response[:2000],
        types=", ".join(_MEMORY_TYPES),
    )

    # Primary: Claude CLI (free, OAuth)
    result = await _extract_claude_cli(prompt, agent_id)
    if result is not None:
        return result

    # Fallback: Gemini Flash (capped to avoid 429-retry hangs)
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if gemini_key:
        try:
            result = await asyncio.wait_for(_extract_gemini(prompt, gemini_key), timeout=10.0)
            if result is not None:
                return result
        except asyncio.TimeoutError:
            logger.warning("extractor[%s]: Gemini timed out — skipping", agent_id)

    logger.debug("extractor[%s]: no memory extracted", agent_id)
    return []


async def _extract_claude_cli(prompt: str, agent_id: str) -> list[dict] | None:
    """Use the local `claude` CLI (OAuth) for extraction.

    Returns a list (possibly empty) on success, None on failure.
    Same authentication as the agents — no API key needed.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--model", "claude-haiku-4-5-20251001", "-p", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        text = stdout.decode().strip()
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end]) or []
        logger.debug("extractor[%s]: claude CLI returned no JSON array — %r", agent_id, text[:200])
    except asyncio.TimeoutError:
        logger.warning("extractor[%s]: claude CLI timed out", agent_id)
    except Exception as exc:
        logger.warning("extractor[%s]: claude CLI extraction failed — %s", agent_id, exc)
    return None


async def _extract_gemini(prompt: str, api_key: str) -> list[dict] | None:
    """Returns extracted memories, or None if Gemini errored."""
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
        return None
