"""GPT models via Codex OAuth — reads access_token from ~/.codex/auth.json.

The `codex-auth` Python library is NOT used. Instead we read the token
that the Codex CLI (Node.js @openai/codex) stores at ~/.codex/auth.json
and pass it directly as the API key to the OpenAI Python SDK.

Supported auth.json layouts:

  chatgpt OAuth (tokens nested):
    { "auth_mode": "chatgpt", "tokens": { "access_token": "ey...", ... } }

  Legacy flat layout:
    { "auth_mode": "chatgpt", "access_token": "ey...", ... }

  Direct API key:
    { "OPENAI_API_KEY": "sk-...", ... }
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_AUTH_PATH = Path("/root/.codex/auth.json")


def _read_access_token(auth_path: Path | None = None) -> str | None:
    """Read the OAuth access_token from Codex CLI's auth.json."""
    path = auth_path or _DEFAULT_AUTH_PATH
    try:
        with open(path) as f:
            data = json.load(f)
        # Layout 1: tokens nested dict (current Codex CLI format)
        tokens = data.get("tokens")
        if isinstance(tokens, dict):
            token = tokens.get("access_token")
            if token:
                return token

        # Layout 2: flat access_token at root (legacy)
        token = data.get("access_token")
        if token:
            return token

        # Layout 3: direct OpenAI API key
        token = data.get("OPENAI_API_KEY")
        if token:
            return token

        logger.warning("codex_model: auth.json exists but has no recognisable token field")
        return None
    except FileNotFoundError:
        logger.warning("codex_model: auth.json not found at %s", path)
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("codex_model: failed to read auth.json: %s", exc)
        return None


def create_codex_model(model_id: str = "gpt-5.4", auth_path: Path | None = None):
    """Return an Agno-compatible OpenAI model using Codex OAuth tokens.

    Reads the access_token from the Codex CLI auth.json and passes it
    as api_key to Agno's OpenAIChat.

    Returns None if auth.json is unavailable (caller should fall through
    to next model in the FallbackModel chain).
    """
    from agno.models.openai import OpenAIChat

    token = _read_access_token(auth_path)
    if not token:
        logger.warning(
            "codex_model: no Codex token available — "
            "model will fail on first invoke (will cascade to Groq)"
        )
        # Still return a model so FallbackModel can build the chain;
        # the token failure will surface on invoke() and cascade to Groq.
        from config import settings
        api_key = settings.OPENAI_API_KEY or "codex-oauth-unavailable"
        return OpenAIChat(id=model_id, api_key=api_key)

    logger.info("codex_model: OAuth token loaded from %s", auth_path or _DEFAULT_AUTH_PATH)
    return OpenAIChat(id=model_id, api_key=token)
