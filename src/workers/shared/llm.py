"""Direct Anthropic claude-haiku calls for hybrid worker sub-agents."""

import os

import anthropic

_MODEL = "claude-haiku-4-5-20251001"
_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


async def complete(prompt: str, system: str = "") -> str:
    """Single-turn completion with haiku. Returns the text response."""
    client = _get_client()
    kwargs: dict = {
        "model": _MODEL,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    msg = await client.messages.create(**kwargs)
    return msg.content[0].text if msg.content else ""
