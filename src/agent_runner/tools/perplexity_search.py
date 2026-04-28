"""Shared Perplexity web search tool for all agents.

Provides web search via the Perplexity API (sonar model).
Results are logged to the agent's daily memory file.
"""

import logging

logger = logging.getLogger(__name__)

_PERPLEXITY_BASE = "https://api.perplexity.ai"
_DEFAULT_MODEL = "sonar"
_MAX_TOKENS = 1024


class PerplexitySearchTools:
    """Legacy Perplexity search class (agno-free). Not used by SDK-based agents."""

    def __init__(self):
        pass

    def search(self, query: str) -> str:
        """Search the web using Perplexity AI and return a summarised answer.

        Args:
            query: The search query.

        Returns:
            A text answer with sources cited inline.
        """
        import httpx
        from config import settings
        from memory.daily_logger import DailyLogger

        api_key = settings.PERPLEXITY_API_KEY
        if not api_key:
            return "Perplexity API key not configured."

        payload = {
            "model": _DEFAULT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "Be precise and concise. Cite your sources.",
                },
                {"role": "user", "content": query},
            ],
            "max_tokens": _MAX_TOKENS,
        }

        try:
            resp = httpx.post(
                f"{_PERPLEXITY_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]

            try:
                dl = DailyLogger(settings.workspace_path)
                dl.log(f"[SEARCH] {query[:120]}")
            except Exception:
                pass

            logger.info("perplexity: search completed for %r", query[:80])
            return answer

        except Exception as exc:
            logger.error("perplexity: search failed — %s", exc)
            return f"Search failed: {exc}"
