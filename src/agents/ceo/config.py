"""Jarvis-specific configuration."""

from pathlib import Path

from agent_runner.config import AgentConfig


JARVIS_BUILTIN_CRONS = [
    {
        "name": "morning_briefing",
        "schedule": "daily@08:15",
        "prompt": (
            "Good morning! Prepare a concise morning briefing (under 200 words). "
            "Include: key items from yesterday's activity log, any tasks or appointments "
            "for today from HEARTBEAT.md, and anything actionable I should know. "
            "After producing the briefing, forward a copy to Timothy (CIO) via: "
            "send_message(to='cio', message=<your briefing>). "        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "eod_consolidation",
        "schedule": "daily@23:00",
        "prompt": (
            "End of day. Summarise today's activity in 3-5 bullet points. "
            "Focus on: decisions made, tasks completed, issues encountered, lessons learned."
        ),
        "session_id": "heartbeat-eod",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "weekly_consolidation",
        "schedule": "weekly@sun@20:00",
        "prompt": (
            "Weekly memory consolidation. Review this week's daily logs and the current "
            "MEMORY.md. Produce an updated MEMORY.md. Return ONLY the raw markdown."
        ),
        "session_id": "heartbeat-weekly",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "nightly_dreaming",
        "schedule": "daily@02:00",
        "prompt": (
            "Nightly dreaming. Review your recent activity logs and long-term memory. "
            "Produce a DREAMS.md that captures: unresolved threads (things started but "
            "not finished), emerging patterns (recurring themes across days), free "
            "associations (unexpected connections between topics), and seeds (ideas worth "
            "developing later). Be interpretive, not just descriptive — surface what the "
            "logs don't explicitly say. Return ONLY the raw markdown for DREAMS.md."
        ),
        "session_id": "heartbeat-dreaming",
        "telegram_notify": False,
        "builtin": True,
    },
]


def build_jarvis_config(workspace_root: Path = Path("/app/workspace/ceo")) -> AgentConfig:
    from agents.ceo.tools import create_jarvis_mcp_server
    return AgentConfig(
        id="ceo",
        name="Jarvis",
        port=8000,
        workspace_path=workspace_root,
        telegram_token_env="TELEGRAM_JARVIS_TOKEN",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
        mattermost_url_env="MATTERMOST_URL",
        mattermost_token_env="MATTERMOST_BOT_TOKEN",
        mattermost_channel_env="CEO_MATTERMOST_CHANNEL_ID",
        domains=["*"],
        capabilities=["delegation", "planning", "coordination", "general-knowledge"],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="",
        memory_backend="filesystem",
        mcp_server_factory=create_jarvis_mcp_server,
        builtin_crons=JARVIS_BUILTIN_CRONS,
        default_image_caption="Analizza questa immagine nel contesto delle mie attivita.",
        voice_enabled=True,
        voice_language="it",
        voice_tts_voice="it-IT-ElsaNeural",
        telegram_webhook_url_env="CEO_TELEGRAM_WEBHOOK_URL",
        telegram_webhook_secret_env="CEO_TELEGRAM_WEBHOOK_SECRET",
    )
