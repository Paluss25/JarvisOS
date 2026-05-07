from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

PERPLEXITY_BASE = "https://api.perplexity.ai"
DEFAULT_MODEL = "sonar"
MAX_TOKENS = 1024


def build_payload(query: str) -> dict:
    return {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": "Be precise and concise. Cite your sources."},
            {"role": "user", "content": query},
        ],
        "max_tokens": MAX_TOKENS,
    }


async def search_perplexity(
    query: str,
    *,
    workspace_path: Path | None = None,
    api_key: str | None = None,
) -> dict:
    query = query.strip()
    if not query:
        return _text("No query provided.")

    resolved_api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
    if not resolved_api_key:
        return _text("Perplexity API key not configured (PERPLEXITY_API_KEY env var missing).")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{PERPLEXITY_BASE}/chat/completions",
                json=build_payload(query),
                headers={
                    "Authorization": f"Bearer {resolved_api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]

        _log_search(workspace_path, query)
        logger.info("perplexity: search completed for %r", query[:80])
        return _text(answer)
    except Exception as exc:
        logger.error("perplexity: search failed — %s", exc)
        return _text(f"Search failed: {exc}")


def search_perplexity_sync(
    query: str,
    *,
    workspace_path: Path | None = None,
    api_key: str | None = None,
) -> str:
    query = query.strip()
    if not query:
        return "No query provided."

    resolved_api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
    if not resolved_api_key:
        return "Perplexity API key not configured."

    try:
        resp = httpx.post(
            f"{PERPLEXITY_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {resolved_api_key}",
                "Content-Type": "application/json",
            },
            json=build_payload(query),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
        _log_search(workspace_path, query)
        logger.info("perplexity: search completed for %r", query[:80])
        return answer
    except Exception as exc:
        logger.error("perplexity: search failed — %s", exc)
        return f"Search failed: {exc}"


def _log_search(workspace_path: Path | None, query: str) -> None:
    if workspace_path is None:
        return
    try:
        from agent_runner.memory.daily_logger import DailyLogger

        DailyLogger(workspace_path).log(f"[SEARCH] {query[:120]}")
    except Exception:
        pass


def _text(message: str) -> dict:
    return {"content": [{"type": "text", "text": str(message)}]}
