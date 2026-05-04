# src/agent_runner/config.py
"""Agent configuration — loaded from agents.yaml per-agent entry."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any
import os


@dataclass
class AgentConfig:
    """Per-agent configuration. Built by the agent-specific run.py from agents.yaml."""

    id: str                                  # "ceo", "dos"
    name: str                                # "Jarvis", "Roger"
    port: int                                # 8000, 8001
    workspace_path: Path                     # /app/workspace/ceo
    telegram_token_env: str                  # "TELEGRAM_JARVIS_TOKEN"
    telegram_chat_id_env: str                # "TELEGRAM_ALLOWED_CHAT_ID"
    telegram_polling_enabled: bool = True    # set False for backend agents that only send notifications
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
    extra_mcp_servers: dict[str, Any] = field(default_factory=dict)
    skills: list[str] | None = None          # None = unrestricted, [] = disabled, list = per-agent allowlist
    skills_watch_enabled: bool = True
    skills_watch_debounce_s: float = 1.0
    a2a_fast_path: Callable[..., Any] | None = None  # async fn(payload: dict) → dict | None — bypasses LLM for structured A2A actions
    builtin_crons: list[dict] = field(default_factory=list)
    default_image_caption: str = "Analyze this image."
    allowed_tools: list[str] = field(default_factory=lambda: [
        "Bash", "Read", "Write", "Edit",
        "WebSearch", "WebFetch", "Glob", "Grep",
    ])
    # Telegram streaming mode: how response content is shown while the agent is processing.
    # "partial"  — update placeholder live every ~1s with partial text + spinner (default)
    # "progress" — spinner + active tool name only; never shows partial text (best for long A2A flows)
    # "block"    — update only on paragraph boundaries (\n\n); reduces edit frequency
    # "off"      — no placeholder; typing indicator only; single reply_text at the end
    telegram_streaming_mode: str = "partial"

    # Webhook mode (opt-in — leave None to keep polling)
    telegram_webhook_url_env: str | None = None    # e.g. "CEO_TELEGRAM_WEBHOOK_URL"
    telegram_webhook_secret_env: str | None = None # e.g. "CEO_TELEGRAM_WEBHOOK_SECRET"

    # ---------------------------------------------------------------------------
    # Multi-channel support (all optional — channels only start when their
    # primary token env var is set to a non-empty value in the environment)
    # ---------------------------------------------------------------------------

    # Slack (Socket Mode — no public URL required)
    # Requires: slack-bolt[async]>=1.18.0
    slack_token_env: str = ""              # xoxb-... bot token
    slack_app_token_env: str = ""          # xapp-... app-level token (Socket Mode)
    slack_channel_env: str = ""            # restrict to one channel ID (optional)

    # Discord
    # Requires: discord.py>=2.3.0
    # Note: MESSAGE_CONTENT privileged intent must be enabled in Developer Portal
    discord_token_env: str = ""            # bot token
    discord_channel_env: str = ""          # restrict to one channel ID (optional)

    # Mattermost (WebSocket + REST)
    # Requires: mattermostdriver>=7.3.0
    mattermost_url_env: str = ""           # https://mattermost.example.com
    mattermost_token_env: str = ""         # personal access token or bot token
    mattermost_channel_env: str = ""       # restrict to one channel ID (optional)

    # ---------------------------------------------------------------------------
    # Voice / STT / TTS  (Telegram voice messages only)
    # ---------------------------------------------------------------------------
    # voice_enabled=True  → voice messages are transcribed and replied to with audio
    # STT backends: "faster-whisper" (local, no key) | "openai" (needs OPENAI_API_KEY)
    # TTS backends: "edge"           (free, edge-tts) | "openai" (needs OPENAI_API_KEY)
    # edge-tts voices: https://speech.microsoft.com/portal/voicegallery
    #   Italian — it-IT-ElsaNeural (F), it-IT-IsabellaNeural (F), it-IT-DiegoNeural (M)
    #   English — en-US-JennyNeural (F), en-US-GuyNeural (M)
    voice_enabled: bool = False
    voice_stt_backend: str = "faster-whisper"
    voice_whisper_model: str = "tiny"      # "tiny" (39 MB) | "base" | "small" | "medium"
    voice_language: str | None = None      # STT language hint ("it", "en") or None = auto
    voice_tts_enabled: bool = True         # send audio reply in addition to text
    voice_tts_backend: str = "edge"
    voice_tts_voice: str = "it-IT-ElsaNeural"

    def env(self, key: str) -> str:
        """Return env var value, trying prefixed key first then unprefixed."""
        if self.env_prefix:
            val = os.environ.get(f"{self.env_prefix}{key}", "")
            if val:
                return val
        return os.environ.get(key, "")

    def _resolve(self, env_key: str) -> str:
        """Strip own prefix from a stored env key, then resolve via env()."""
        bare = env_key.removeprefix(self.env_prefix) if self.env_prefix else env_key
        return self.env(bare)

    @property
    def model(self) -> str:
        return self._resolve(self.model_env)

    @property
    def fallback_model(self) -> str:
        return self._resolve(self.fallback_model_env)

    @property
    def budget(self) -> float | None:
        val = self._resolve(self.budget_env)
        if not val:
            return None
        try:
            return float(val)
        except ValueError:
            raise ValueError(
                f"AgentConfig '{self.id}': invalid value for {self.budget_env!r}: "
                f"expected a number, got {val!r}"
            )

    @property
    def effort(self) -> str:
        return self._resolve(self.effort_env)

    @property
    def thinking(self) -> bool:
        return self._resolve(self.thinking_env).lower() in ("true", "1", "yes")

    @property
    def context_1m(self) -> bool:
        return self._resolve(self.context_1m_env).lower() in ("true", "1", "yes")

    @property
    def log_level(self) -> str:
        return self._resolve(self.log_level_env) or "INFO"

    @staticmethod
    def _parse_skill_list(raw: str) -> list[str] | None:
        value = raw.strip()
        if not value:
            return None
        if value.lower() in {"none", "disabled", "off", "false"}:
            return []
        if value.lower() in {"all", "*"}:
            return None
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def skill_allowlist(self) -> list[str] | None:
        per_agent = os.environ.get(f"JARVIOS_SKILLS_{self.id.upper()}", "")
        if per_agent.strip():
            return self._parse_skill_list(per_agent)
        global_value = os.environ.get("JARVIOS_SKILLS", "")
        if global_value.strip():
            return self._parse_skill_list(global_value)
        return self.skills

    @property
    def effective_skills_watch_enabled(self) -> bool:
        value = os.environ.get("JARVIOS_SKILLS_WATCH", "")
        if value:
            return value.lower() in {"1", "true", "yes", "on"}
        return self.skills_watch_enabled

    @property
    def effective_skills_watch_debounce_s(self) -> float:
        value = os.environ.get("JARVIOS_SKILLS_WATCH_DEBOUNCE_S", "")
        if value:
            try:
                return float(value)
            except ValueError:
                pass
        return self.skills_watch_debounce_s

    @property
    def agent_max_turn_s(self) -> float:
        """Hard cap on agent.query() invoked from the A2A handler.

        Resolution order:
        1. ``JARVIOS_AGENT_MAX_TURN_S_<AGENT_ID_UPPER>`` (per-agent override)
        2. ``JARVIOS_AGENT_MAX_TURN_S`` (global default)
        3. 600.0 (built-in default)

        Must be ``>= stream_timeout_s + 30`` so the A2A handler has margin to
        publish the timeout sentinel response after the inner SDK stream
        timeout fires. Validated at startup in BaseAgentClient.
        """
        per_agent = os.environ.get(f"JARVIOS_AGENT_MAX_TURN_S_{self.id.upper()}")
        if per_agent:
            try:
                return float(per_agent)
            except ValueError:
                pass
        global_val = os.environ.get("JARVIOS_AGENT_MAX_TURN_S")
        if global_val:
            try:
                return float(global_val)
            except ValueError:
                pass
        return 600.0

    @property
    def stream_timeout_s(self) -> float:
        """Inner SDK stream timeout for ``agent.query()`` / ``agent.stream()``.

        Resolution order mirrors :attr:`agent_max_turn_s`:
        1. ``JARVIOS_STREAM_TIMEOUT_<AGENT_ID_UPPER>`` (per-agent override)
        2. ``JARVIOS_STREAM_TIMEOUT`` (global default)
        3. 480.0 (built-in default — historical value).
        """
        per_agent = os.environ.get(f"JARVIOS_STREAM_TIMEOUT_{self.id.upper()}")
        if per_agent:
            try:
                return float(per_agent)
            except ValueError:
                pass
        global_val = os.environ.get("JARVIOS_STREAM_TIMEOUT")
        if global_val:
            try:
                return float(global_val)
            except ValueError:
                pass
        return 480.0
