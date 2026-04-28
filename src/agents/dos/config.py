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
            "Direct, no fluff. "
            "Send the result to DrHouse via send_message(to='coh', message=<your briefing>). "
            "Also forward a copy to Timothy (CIO) via send_message(to='cio', message=<your briefing>). "        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "eod_consolidation",
        "schedule": "daily@23:00",
        "prompt": (
            "End of sport day. Summarise today in 2-3 bullet points: "
            "training completed/skipped, meals logged, any measurements. "
            "If any data was logged, confirm it's saved to the database. "
            "Send the summary to DrHouse via send_message(to='coh', message=<your summary>)."
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
            "Be data-driven and direct. "
            "Send the sport report to DrHouse via send_message(to='coh', message=<report>). "
            "DrHouse will include it in the integrated weekly health report to Jarvis."
        ),
        "session_id": "heartbeat-weekly-report",
        "telegram_notify": False,
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
        "telegram_notify": False,
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


def build_dos_config(workspace_root: Path = Path("/app/workspace/dos")) -> AgentConfig:
    from agents.dos.tools import create_chief_mcp_server
    return AgentConfig(
        id="dos",
        name="Roger",
        port=8001,
        workspace_path=workspace_root,
        telegram_token_env="",
        telegram_chat_id_env="",
        domains=["sport", "fitness"],
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


# Backward-compatible alias for older imports.
build_roger_config = build_dos_config
