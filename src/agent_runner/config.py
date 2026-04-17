# src/agent_runner/config.py
"""Agent configuration — loaded from agents.yaml per-agent entry."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any
import os


@dataclass
class AgentConfig:
    """Per-agent configuration. Built by the agent-specific run.py from agents.yaml."""

    id: str                                  # "jarvis", "roger"
    name: str                                # "Jarvis", "Roger"
    port: int                                # 8000, 8001
    workspace_path: Path                     # /app/workspace/jarvis
    telegram_token_env: str                  # "TELEGRAM_JARVIS_TOKEN"
    telegram_chat_id_env: str                # "TELEGRAM_ALLOWED_CHAT_ID"
    domains: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    model_env: str = "CLAUDE_MODEL"
    fallback_model_env: str = "CLAUDE_FALLBACK_MODEL"
    budget_env: str = "CLAUDE_MAX_BUDGET_USD"
    effort_env: str = "CLAUDE_EFFORT"
    thinking_env: str = "CLAUDE_THINKING"
    context_1m_env: str = "CLAUDE_CONTEXT_1M"
    log_level_env: str = "LOG_LEVEL"
    env_prefix: str = ""                     # "CHIEF_" for Roger
    memory_backend: str = "filesystem"       # "filesystem" or "agentic"
    mcp_server_factory: Callable[..., Any] | None = None
    builtin_crons: list[dict] = field(default_factory=list)
    default_image_caption: str = "Analyze this image."
    allowed_tools: list[str] = field(default_factory=lambda: [
        "Bash", "Read", "Write", "Edit",
        "WebSearch", "WebFetch", "Glob", "Grep",
    ])

    def env(self, key: str) -> str:
        """Return env var value, trying prefixed key first then unprefixed."""
        if self.env_prefix:
            val = os.environ.get(f"{self.env_prefix}{key}", "")
            if val:
                return val
        return os.environ.get(key, "")

    @property
    def model(self) -> str:
        base_key = self.model_env.removeprefix(self.env_prefix) if self.env_prefix else self.model_env
        return self.env(base_key)

    @property
    def fallback_model(self) -> str:
        base_key = self.fallback_model_env.removeprefix(self.env_prefix) if self.env_prefix else self.fallback_model_env
        return self.env(base_key)

    @property
    def budget(self) -> float | None:
        base_key = self.budget_env.removeprefix(self.env_prefix) if self.env_prefix else self.budget_env
        val = self.env(base_key)
        return float(val) if val else None

    @property
    def effort(self) -> str:
        base_key = self.effort_env.removeprefix(self.env_prefix) if self.env_prefix else self.effort_env
        return self.env(base_key)

    @property
    def thinking(self) -> bool:
        base_key = self.thinking_env.removeprefix(self.env_prefix) if self.env_prefix else self.thinking_env
        return self.env(base_key).lower() in ("true", "1", "yes")

    @property
    def context_1m(self) -> bool:
        base_key = self.context_1m_env.removeprefix(self.env_prefix) if self.env_prefix else self.context_1m_env
        return self.env(base_key).lower() in ("true", "1", "yes")

    @property
    def log_level(self) -> str:
        base_key = self.log_level_env.removeprefix(self.env_prefix) if self.env_prefix else self.log_level_env
        return self.env(base_key) or "INFO"
