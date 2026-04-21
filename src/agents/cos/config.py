"""ChiefOfStaff-specific configuration."""

from pathlib import Path

from agent_runner.config import AgentConfig


MARK_BUILTIN_CRONS = [
    {
        "name": "morning_briefing",
        "schedule": "daily@08:00",
        "prompt": (
            "Good morning. Review yesterday's routing log. Concise briefing (under 200 words): "
            "cases routed, any pending escalations, items awaiting human approval, "
            "routing anomalies or security flags detected. Be direct. "
            "After producing the briefing, forward a copy to Timothy (CIO) via: "
            "send_message(to='timothy', message=<your briefing>)."
        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "eod_consolidation",
        "schedule": "daily@23:00",
        "prompt": (
            "End of day. Routing summary in 3-5 bullet points: "
            "total cases processed, actions taken (ignored/archived/routed/escalated), "
            "security flags triggered, unresolved items."
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
            "MEMORY.md. Update routing patterns, recurring security flags, and ownership "
            "decisions. Produce an updated MEMORY.md. Return ONLY the raw markdown."
        ),
        "session_id": "heartbeat-weekly",
        "telegram_notify": True,
        "builtin": True,
    },
]


def build_chief_of_staff_config(workspace_root: Path = Path("/app/workspace/chief_of_staff")) -> AgentConfig:
    from agents.cos.tools import create_chief_of_staff_mcp_server
    return AgentConfig(
        id="chief_of_staff",
        name="ChiefOfStaffAgent",
        port=8008,
        workspace_path=workspace_root,
        telegram_token_env="TELEGRAM_CHIEF_OF_STAFF_TOKEN",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
        domains=['chief-of-staff', 'email', 'communications', 'routing', 'coordination', 'triage', 'prioritization'],
        capabilities=['chief-of-staff', 'agent-coordination', 'email-triage', 'routing-decisions', 'escalation-management', 'priority-assessment', 'cross-domain-coordination'],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="CHIEF_OF_STAFF_",
        memory_backend="filesystem",
        mcp_server_factory=create_chief_of_staff_mcp_server,
        extra_mcp_servers={
            "protonmail-email": {"type": "sse", "url": "http://protonmail-mcp:3000/sse"},
            "gmx-email": {"type": "sse", "url": "http://gmx-mcp:3001/sse"},
        },
        builtin_crons=MARK_BUILTIN_CRONS,
        # Agent tool enables sub-agent dispatch (required for delegate workflows)
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
    )
