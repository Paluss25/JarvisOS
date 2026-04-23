"""DrHouse (Chief of Health) agent configuration."""

from pathlib import Path

from agent_runner.config import AgentConfig


DRHOUSE_BUILTIN_CRONS = [
    {
        "name": "morning_briefing",
        "schedule": "daily@08:00",
        "prompt": (
            "Morning infrastructure check for COH. Verify: "
            "1. NutritionDirector (DON) is reachable — send_message(to='don', message='ping') and check response. "
            "2. COH database connections (run a health_query to confirm nutrition_data is accessible). "
            "3. Yesterday's COH activity log — any errors or anomalies? "
            "Produce a concise status (under 100 words). Then you MUST call report_issue. "
            "Extract all technical issues found: unreachable services, DB errors, unexpected errors. "
            "Call report_issue(issues=[...]) with all issues. "
            "If no technical issues: call report_issue(issues=[]). Never skip this call."
        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "morning_health_briefing",
        "schedule": "daily@08:05",
        "prompt": (
            "Morning health briefing. Aggregate and synthesize a concise integrated health brief (under 200 words):\n"
            "1. Today's training plan from Roger (use send_message to ask Roger for today's session)\n"
            "2. Nutrition targets for the day (query nutrition_data for active goals and today's macro targets)\n"
            "3. Body composition trend — last 7 days (query sport_metrics body_measurements)\n"
            "4. Any active health flags or medical notes from MEMORY.md\n"
            "Highlight conflicts between training load and nutrition (e.g. deficit on high-intensity day). "
            "Be directive and concise. "
            "After producing the briefing, forward a copy to Timothy (CIO) via: "
            "send_message(to='cio', message=<your briefing>). "
            "After producing and sending this briefing, you MUST call report_issue. "
            "Extract all technical issues detected during this session: failed connections, "
            "unreachable databases, MCP servers not responding, unexpected restarts, "
            "elevated error rates, authentication failures. "
            "Call report_issue(issues=[...]) with all issues found. "
            "If no technical issues were detected: call report_issue(issues=[]). "
            "Never skip this call."
        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "eod_health_consolidation",
        "schedule": "daily@23:00",
        "prompt": (
            "End-of-day health consolidation. Review today's data across all domains:\n"
            "1. Meals logged (query nutrition_data meals for today)\n"
            "2. Training completed or skipped (use send_message to Roger for today's activity)\n"
            "3. Recovery indicators — sleep, HRV, readiness if available\n"
            "4. Cross-domain conflicts or flags (e.g. insufficient protein on training day)\n"
            "Summarise in 3-4 bullet points. Log key findings to daily_log."
        ),
        "session_id": "heartbeat-eod",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "weekly_health_report",
        "schedule": "weekly@mon@09:00",
        "prompt": (
            "Weekly Executive Health Brief. Produce an integrated, data-driven health report covering:\n"
            "1. Training adherence and load trend (request weekly sport summary from Roger via send_message)\n"
            "2. Nutrition adherence — average daily macros vs. targets, caloric balance\n"
            "3. Body composition movement — weight and waist trend direction\n"
            "4. Recovery quality assessment\n"
            "5. Cross-domain analysis: conflicts, alignment issues, positive synergies\n"
            "6. Top 3 actionable recommendations for the coming week\n"
            "Send the full report to Jarvis via send_message for executive awareness. "
            "Be data-driven, direct, and flag any medical concerns explicitly."
        ),
        "session_id": "heartbeat-weekly-report",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "weekly_memory_consolidation",
        "schedule": "weekly@sun@20:00",
        "prompt": (
            "Weekly health memory consolidation. Review this week's daily logs and the current MEMORY.md. "
            "Update MEMORY.md with: current health status, active medical or screening notes, "
            "body composition trend direction, integrated health goals, nutrition protocol status, "
            "any strategic decisions or adjustments made this week across health domains. "
            "Remove stale or superseded entries. Return ONLY the raw markdown — no commentary."
        ),
        "session_id": "heartbeat-weekly-memory",
        "telegram_notify": False,
        "builtin": True,
    },
]


def build_drhouse_config(workspace_root: Path = Path("/app/workspace/coh")) -> AgentConfig:
    from agents.coh.tools import create_drhouse_mcp_server
    return AgentConfig(
        id="coh",
        name="DrHouse",
        port=8006,
        workspace_path=workspace_root,
        telegram_token_env="TELEGRAM_DRHOUSE_TOKEN",
        telegram_chat_id_env="TELEGRAM_HEALTH_CHAT_ID",
        domains=["health", "sport", "nutrition", "medical"],
        capabilities=["health-orchestration", "conflict-resolution", "medical-screening", "cross-domain-analysis"],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="DRHOUSE_",
        memory_backend="filesystem",
        mcp_server_factory=create_drhouse_mcp_server,
        builtin_crons=DRHOUSE_BUILTIN_CRONS,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
    )
