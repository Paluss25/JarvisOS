"""Timothy (CIO) agent configuration."""

from pathlib import Path

from agent_runner.config import AgentConfig


TIMOTHY_BUILTIN_CRONS = [
    {
        "name": "morning_briefing",
        "schedule": "daily@08:45",
        "prompt": (
            "IT morning briefing. Review yesterday's daily log and produce a concise status "
            "summary (under 200 words, 3-5 bullet points):\n"
            "1. Any infrastructure incidents or anomalies from yesterday\n"
            "2. Services that were restarted or had elevated error rates\n"
            "3. Any pending actions or follow-ups from previous logs\n"
            "Use infra_check to verify the health of critical services before reporting. "
            "Be factual and actionable. Flag anything that needs immediate attention."
        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "issue_collector",
        "schedule": "daily@08:50",
        "prompt": (
            "Issue collection time. You MUST immediately call the collect_and_remediate tool. "
            "Do not produce any text, analysis, or briefing before calling it. "
            "Just call collect_and_remediate() now — the tool will handle everything including "
            "sending Telegram messages and waiting for user approvals. "
            "After the tool returns, report back the result string it gave you."
        ),
        "session_id": "heartbeat-issue-collector",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "eod_consolidation",
        "schedule": "daily@23:00",
        "prompt": (
            "End of day IT consolidation. Review today's full daily log and write a "
            "3-5 bullet summary:\n"
            "- Infrastructure changes made today\n"
            "- Incidents detected or resolved\n"
            "- Security events or anomalies\n"
            "- Pending items for tomorrow\n"
            "If anything is worth long-term retention, note it with 'KEY FACT:'. "
            "Append the summary to today's memory log using daily_log."
        ),
        "session_id": "heartbeat-eod",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "weekly_it_report",
        "schedule": "weekly@mon@09:00",
        "prompt": (
            "Weekly IT infrastructure report. Produce a structured report under three headings:\n\n"
            "**Infrastructure:** Service availability this week, any downtime, resource usage trends.\n"
            "**Security:** CrowdSec blocks, certificate status, any anomalous access patterns.\n"
            "**Projects:** Migrations in progress, completed work, blocked items.\n\n"
            "Use infra_check to verify current service health before reporting. "
            "Keep it under 300 words. Flag any HIGH severity items clearly."
        ),
        "session_id": "heartbeat-weekly-report",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "weekly_consolidation",
        "schedule": "weekly@sun@20:00",
        "prompt": (
            "Weekly IT memory consolidation. Read all 7 daily logs from this week and the "
            "current MEMORY.md. Produce a rewritten MEMORY.md that includes:\n"
            "- Current infrastructure state (services running, recent changes)\n"
            "- Security posture (active threats, hardening applied)\n"
            "- Active projects and their status\n"
            "- Known issues and technical debt\n"
            "- Lessons learned this week\n"
            "Remove stale entries. Keep facts durable and concrete. "
            "Return ONLY the raw markdown — no commentary."
        ),
        "session_id": "heartbeat-weekly-memory",
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


def build_timothy_config(workspace_root: Path = Path("/app/workspace/cio")) -> AgentConfig:
    from agents.cio.tools import create_timothy_mcp_server
    return AgentConfig(
        id="cio",
        name="Timothy",
        port=8002,
        workspace_path=workspace_root,
        telegram_token_env="TELEGRAM_TIMOTHY_TOKEN",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
        domains=["infrastructure", "security", "devops", "it-operations"],
        capabilities=["infra-monitoring", "security-audit", "docker-management", "log-analysis"],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="TIMOTHY_",
        memory_backend="filesystem",
        mcp_server_factory=create_timothy_mcp_server,
        builtin_crons=TIMOTHY_BUILTIN_CRONS,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
        voice_enabled=True,
        voice_language="it",
        voice_tts_voice="it-IT-ElsaNeural",
    )
