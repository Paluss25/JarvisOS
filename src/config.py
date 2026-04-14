"""Jarvis settings — all configuration loaded from environment."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="/home/paluss/docker/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    DATABASE_URL: str = "postgresql://jarvis:password@localhost:5432/jarvis"
    POSTGRES_PASSWORD: str = ""

    # --- Redis ---
    REDIS_URL: str = "redis://:password@localhost:6379/0"
    REDIS_PASSWORD: str = ""

    # --- Workspace ---
    WORKSPACE_PATH: str = "/app/workspace"

    # --- Telegram ---
    TELEGRAM_JARVIS_TOKEN: str = ""
    TELEGRAM_ALLOWED_CHAT_ID: str = ""

    # --- Memory API ---
    MEMORY_API_URL: str = "https://memory-api.prova9x.com"
    MEMORY_API_USER_ID: str = "jarvis"

    # --- Codex OAuth ---
    # Token read from file at runtime (bind-mounted from host ~/.codex/auth.json)
    CODEX_AUTH_PATH: str = "/root/.codex/auth.json"

    # --- Groq ---
    # Existing ~/docker/.env uses GROK_API_KEY — alias both names
    GROQ_API_KEY: str = ""
    GROK_API_KEY: str = ""  # legacy name in shared .env

    # --- Optional future providers ---
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    PERPLEXITY_API_KEY: str = ""
    GITHUB_TOKEN: str = ""

    # --- OpenAI (direct key fallback, distinct from Codex OAuth) ---
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5.4"

    # --- Runtime ---
    JARVIS_ENV: str = "production"
    LOG_LEVEL: str = "INFO"
    TZ: str = "Europe/Rome"

    @property
    def groq_key(self) -> str:
        """Return Groq key, checking both GROQ_API_KEY and legacy GROK_API_KEY."""
        return self.GROQ_API_KEY or self.GROK_API_KEY

    @property
    def codex_auth_path(self) -> Path:
        return Path(self.CODEX_AUTH_PATH)

    @property
    def workspace_path(self) -> Path:
        return Path(self.WORKSPACE_PATH)

    @property
    def is_development(self) -> bool:
        return self.JARVIS_ENV == "development"


settings = Settings()
