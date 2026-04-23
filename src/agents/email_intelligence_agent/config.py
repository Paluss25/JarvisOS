"""Email Intelligence Agent configuration."""

from pathlib import Path

from agent_runner.config import AgentConfig


EMAIL_INTELLIGENCE_BUILTIN_CRONS = [
    {
        "name": "email_poll",
        "schedule": "interval@15m",
        "prompt": (
            "Poll for unread emails on all accounts (protonmail and gmx). "
            "For each unread email: use the appropriate MCP list_emails / get_email tools "
            "to fetch the full email dict, then call process_email with that dict. "
            "Process at most 20 emails per poll. Skip emails already processed today "
            "if their subject matches a recent audit entry."
        ),
        "session_id": "heartbeat-email-poll",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "morning_briefing",
        "schedule": "daily@08:00",
        "prompt": (
            "Morning email briefing. Poll for unread emails on all accounts (process up to 20). "
            "After processing, send a summary to cos via send_message: "
            "how many emails processed, breakdown by domain, any quarantined items, "
            "any high-risk items. Keep summary under 150 words. "
            "After producing and sending this briefing, you MUST call report_issue. "
            "Extract all technical issues detected during this session: failed connections, "
            "unreachable databases, MCP servers not responding, unexpected restarts, "
            "elevated error rates, authentication failures. "
            "Call report_issue(issues=[...]) with all issues found. "
            "If no technical issues were detected: call report_issue(issues=[]). "
            "Never skip this call."
        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "eod_consolidation",
        "schedule": "daily@23:00",
        "prompt": (
            "End-of-day consolidation. Review today's audit log (use get_audit_log). "
            "Summarise in 3-5 bullets: emails processed, domains encountered, "
            "security events, quarantine decisions. Write to daily memory log."
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
            "MEMORY.md. Produce an updated MEMORY.md capturing recurring senders, "
            "domain patterns, and security incidents. Return ONLY the raw markdown."
        ),
        "session_id": "heartbeat-weekly",
        "telegram_notify": False,
        "builtin": True,
    },
]


def build_email_intelligence_config(
    workspace_root: Path = Path("/app/workspace/email_intelligence"),
) -> AgentConfig:
    from agents.email_intelligence_agent.tools import create_email_intelligence_mcp_server
    return AgentConfig(
        id="email_intelligence_agent",
        name="EmailIntelligenceAgent",
        port=8005,
        workspace_path=workspace_root,
        telegram_token_env="",
        telegram_chat_id_env="",
        domains=["email", "intelligence", "extraction", "analysis"],
        capabilities=["fact-extraction", "entity-identification", "domain-classification",
                      "sensitivity-assessment", "security-pipeline"],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="EMAIL_INTELLIGENCE_",
        memory_backend="filesystem",
        mcp_server_factory=create_email_intelligence_mcp_server,
        extra_mcp_servers={
            "protonmail-email": {"type": "sse", "url": "http://protonmail-mcp:3000/sse"},
            "gmx-email": {"type": "sse", "url": "http://gmx-mcp:3001/sse"},
        },
        builtin_crons=EMAIL_INTELLIGENCE_BUILTIN_CRONS,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
    )
