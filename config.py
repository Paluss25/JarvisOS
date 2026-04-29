"""Email Intelligence Agent-specific configuration."""

from pathlib import Path

from agent_runner.config import AgentConfig


EMAILINTEL_BUILTIN_CRONS = [
    {
        "name": "morning_briefing",
        "schedule": "daily@08:00",
        "prompt": (
            "Good morning. Prepare a concise briefing (under 200 words): "
            "key items from yesterday's log, any tasks or follow-ups for today, "
            "anything actionable. Be direct."
        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "eod_consolidation",
        "schedule": "daily@23:00",
        "prompt": (
            "End of day. Summarise today in 3-5 bullet points: "
            "decisions made, tasks completed, issues encountered, lessons learned."
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
]


def build_emailintel_config(workspace_root: Path = Path("/app/workspace/emailintel")) -> AgentConfig:
    from agents.emailintel.tools import create_emailintel_mcp_server
    return AgentConfig(
        id="emailintel",
        name="Email Intelligence Agent",
        port=8005,
        workspace_path=workspace_root,
        telegram_token_env="TELEGRAM_EMAILINTEL_TOKEN",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
        domains=['email', 'intelligence', 'extraction', 'analysis'],
        capabilities=[],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="EMAILINTEL_",
        memory_backend="filesystem",
        mcp_server_factory=create_emailintel_mcp_server,
        builtin_crons=EMAILINTEL_BUILTIN_CRONS,
        # Agent tool enables sub-agent dispatch (required for delegate workflows)
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
    )
