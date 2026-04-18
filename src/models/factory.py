"""Build Agno model instances from YAML configuration.

Reads workspace/config/agent-models.yaml and constructs the correct
FallbackModel chain for each agent.
"""

import logging
from pathlib import Path

import yaml

from models.fallback_model import FallbackModel

logger = logging.getLogger(__name__)


def _build_single_model(provider: str, model_id: str):
    """Instantiate one Agno model from provider name + model ID."""

    if provider == "openai-codex":
        from models.codex_model import create_codex_model
        from config import settings
        return create_codex_model(
            model_id=model_id,
            auth_path=settings.codex_auth_path,
        )

    elif provider == "xai":
        from agno.models.xai import xAI
        from config import settings
        return xAI(id=model_id, api_key=settings.GROK_API_KEY)

    elif provider == "litellm":
        # Use LiteLLM self-hosted gateway via OpenAI-compatible API
        from agno.models.openai import OpenAILike
        from config import settings
        return OpenAILike(
            id=model_id,
            name=f"LiteLLM/{model_id}",
            provider="LiteLLM",
            api_key=settings.LITELLM_API_KEY,
            base_url=settings.LITELLM_API_URL + "/v1",
        )

    elif provider == "groq":
        from agno.models.groq import Groq
        from config import settings
        return Groq(id=model_id, api_key=settings.groq_key)

    elif provider == "anthropic":
        from agno.models.anthropic import Claude
        from config import settings
        return Claude(id=model_id, api_key=settings.ANTHROPIC_API_KEY)

    elif provider == "google":
        from agno.models.google import Gemini
        from config import settings
        return Gemini(id=model_id, api_key=settings.GOOGLE_API_KEY)

    elif provider == "ollama":
        from agno.models.ollama import Ollama
        return Ollama(id=model_id)

    else:
        raise ValueError(f"Unknown model provider: {provider!r}")


def build_agent_model(agent_name: str) -> FallbackModel:
    """Build a FallbackModel chain for a given agent from YAML config.

    Reads workspace/config/agent-models.yaml and returns a FallbackModel
    wrapping [primary, fallback_1, fallback_2, ...].

    Args:
        agent_name: Key in agent-models.yaml (e.g. "jarvis")

    Returns:
        FallbackModel instance ready to pass to agno.Agent(model=...)

    Raises:
        ValueError: If agent_name not found in config
        FileNotFoundError: If agent-models.yaml not found
    """
    from config import settings

    config_path = settings.workspace_path / "config" / "agent-models.yaml"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    agent_cfg = (config.get("agents") or {}).get(agent_name)
    if not agent_cfg:
        available = list((config.get("agents") or {}).keys())
        raise ValueError(
            f"No model config for agent {agent_name!r}. "
            f"Available agents: {available}"
        )

    # Build primary model
    primary = agent_cfg["primary"]
    models = [_build_single_model(primary["provider"], primary["model"])]

    # Build fallback chain
    for fb in agent_cfg.get("fallback", []):
        try:
            models.append(_build_single_model(fb["provider"], fb["model"]))
        except Exception as exc:
            logger.warning(
                "factory: skipping fallback %s/%s — %s",
                fb["provider"], fb["model"], exc,
            )

    chain_str = " → ".join(m.id for m in models)
    logger.info("Model chain for %r: %s", agent_name, chain_str)

    def on_fallback(from_model, to_model, error):
        """Log fallback cascade to daily memory (best-effort)."""
        try:
            from memory.daily_logger import DailyLogger
            from config import settings as s
            dl = DailyLogger(workspace_path=str(s.workspace_path))
            dl.log(
                f"[FALLBACK] {agent_name}: {from_model.id} → {to_model.id} "
                f"— {type(error).__name__}: {error}"
            )
        except Exception:
            pass  # never interrupt the chain over a logging failure

    return FallbackModel(
        models=models,
        max_retries_per_model=1,
        retry_delay=1.5,
        on_fallback=on_fallback,
    )


def build_agent_model_native(agent_name: str):
    """Return (primary_model, fallback_models_list) for use with Agno's
    native fallback_models Agent parameter.

    The primary model is a real Agno Model instance.  The fallbacks list
    may be empty if no fallback is configured.

    Uses the same YAML config as build_agent_model().
    """
    fm = build_agent_model(agent_name)
    primary = fm.models[0]
    fallbacks = fm.models[1:] if len(fm.models) > 1 else []
    return primary, fallbacks
