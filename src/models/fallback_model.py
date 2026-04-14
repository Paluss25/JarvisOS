"""Model wrapper that cascades through a chain of LLMs on failure."""

import time
import logging
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger(__name__)

# HTTP status codes that trigger fallback (transient errors)
RETRIABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _is_retriable(exc: Exception) -> bool:
    """Return True if this exception should trigger a fallback."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    # Check for HTTP status codes in common SDK exceptions
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in RETRIABLE_STATUS_CODES:
        return True
    # openai / groq SDK raises APIStatusError with status_code
    if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        if exc.response.status_code in RETRIABLE_STATUS_CODES:
            return True
    return True  # fallback on any error — model failures should not bubble up


class FallbackModel:
    """Transparent model wrapper with ordered fallback chain.

    To the Agno agent, this looks like a single model.
    Underneath, it tries each model in order until one succeeds.

    Usage:
        model = FallbackModel([codex_model, groq_model])
        agent = Agent(name="Jarvis", model=model, ...)
    """

    def __init__(
        self,
        models: list,
        max_retries_per_model: int = 1,
        retry_delay: float = 1.5,
        on_fallback: Optional[Callable] = None,
    ):
        if not models:
            raise ValueError("FallbackModel requires at least one model")

        self.models = models
        self.max_retries = max_retries_per_model
        self.retry_delay = retry_delay
        self.on_fallback = on_fallback  # callback(from_model, to_model, error)

        # Expose primary model's id as our own (Agno reads model.id)
        self.id = models[0].id

    @property
    def primary(self):
        return self.models[0]

    # ------------------------------------------------------------------ #
    #  Agno Model protocol methods                                         #
    # ------------------------------------------------------------------ #

    def invoke(self, messages: list, **kwargs) -> Any:
        """Try each model in chain until one succeeds."""
        last_error = None

        for i, model in enumerate(self.models):
            for attempt in range(self.max_retries + 1):
                try:
                    result = model.invoke(messages, **kwargs)
                    if i > 0:
                        logger.info(
                            "FallbackModel: succeeded with fallback "
                            "#%d (%s) after primary failed", i, model.id
                        )
                    return result
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "FallbackModel: %s failed (attempt %d/%d): %s",
                        model.id, attempt + 1, self.max_retries + 1, exc,
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)

            # Cascade to next model
            if i < len(self.models) - 1:
                next_model = self.models[i + 1]
                logger.warning(
                    "FallbackModel: cascading %s → %s", model.id, next_model.id
                )
                if self.on_fallback:
                    try:
                        self.on_fallback(model, next_model, last_error)
                    except Exception:
                        pass  # never let callback failure break the chain

        raise last_error or RuntimeError("All models in fallback chain failed")

    def invoke_stream(self, messages: list, **kwargs) -> Iterator:
        """Streaming version with same fallback logic."""
        last_error = None

        for i, model in enumerate(self.models):
            for attempt in range(self.max_retries + 1):
                try:
                    return model.invoke_stream(messages, **kwargs)
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "FallbackModel (stream): %s failed (attempt %d): %s",
                        model.id, attempt + 1, exc,
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)

            if i < len(self.models) - 1:
                if self.on_fallback:
                    try:
                        self.on_fallback(model, self.models[i + 1], last_error)
                    except Exception:
                        pass

        raise last_error or RuntimeError("All models in fallback chain failed (stream)")

    # Delegate common Agno model properties to primary
    @property
    def name(self) -> str:
        return getattr(self.primary, "name", self.primary.id)

    def __repr__(self) -> str:
        chain = " → ".join(m.id for m in self.models)
        return f"FallbackModel({chain})"
