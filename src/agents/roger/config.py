"""Roger (Chief of Sport) agent configuration."""

from pathlib import Path

from agent_runner.config import AgentConfig


ROGER_BUILTIN_CRONS = [
    {
        "name": "morning_check",
        "schedule": "daily@08:00",
        "prompt": (
            "Morning check. Produce a concise sport briefing (under 150 words):\n"
            "1. Any new activities logged yesterday (use sport_query)\n"
            "2. Today's planned training session (check training_plan table)\n"
            "3. Any pending body measurements (last measurement date)\n"
            "Direct, no fluff."
        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "eod_consolidation",
        "schedule": "daily@23:00",
        "prompt": (
            "End of sport day. Summarise today in 2-3 bullet points: "
            "training completed/skipped, meals logged, any measurements. "
            "If any data was logged, confirm it's saved to the database."
        ),
        "session_id": "heartbeat-eod",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "weekly_report",
        "schedule": "weekly@mon@09:00",
        "prompt": (
            "Weekly sport report. Run the rules engine (run_rules_engine with "
            "check_type='weekly') and summarize the week: training adherence, "
            "nutrition adherence, body composition trend, flags and recommendations. "
            "Be data-driven and direct."
        ),
        "session_id": "heartbeat-weekly-report",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "weekly_consolidation",
        "schedule": "weekly@sun@20:00",
        "prompt": (
            "Weekly sport memory consolidation. Review this week's logs and the current "
            "MEMORY.md. Update MEMORY.md with: current training plan status, body composition "
            "trend direction, active goals, any strategic decisions made this week. "
            "Remove stale entries. Return ONLY the raw markdown — no commentary."
        ),
        "session_id": "heartbeat-weekly-memory",
        "telegram_notify": True,
        "builtin": True,
    },
]


def build_roger_config(workspace_root: Path = Path("/app/workspace/roger")) -> AgentConfig:
    from agents.roger.tools import create_chief_mcp_server
    return AgentConfig(
        id="roger",
        name="Roger",
        port=8001,
        workspace_path=workspace_root,
        telegram_token_env="TELEGRAM_CHIEF_TOKEN",
        telegram_chat_id_env="TELEGRAM_SPORT_CHAT_ID",
        domains=["sport", "fitness", "health", "nutrition"],
        capabilities=["sport-analysis", "training-planning", "body-composition", "strava-integration"],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="CHIEF_",
        memory_backend="filesystem",
        mcp_server_factory=create_chief_mcp_server,
        builtin_crons=ROGER_BUILTIN_CRONS,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
    )
