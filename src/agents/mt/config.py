"""MT AgentConfig."""

from pathlib import Path

from agent_runner.config import AgentConfig


MT_BUILTIN_CRONS = [
    {
        "name": "digest_poll",
        "schedule": "interval@15m",
        "prompt": (
            "Call read_email_digest (max_items=10) to fetch unprocessed entries from the MT email digest. "
            "For each entry act on mt_action_hint: "
            "'archive' → call sort_email with email_id and payload_json; "
            "'create_task' → call create_task with title derived from subject; "
            "'draft_reply' → call draft_reply with email_id, subject, sender, body_redacted; "
            "draft_reply creates a draft_pending item and must not be treated as sent or complete; "
            "'forward_to_cos' → call forward_to_cos with payload_json=<full entry as JSON> and a brief reason. "
            "COS is only reachable via forward_to_cos (A2A) — never write files to contact COS. "
            "After processing all entries, call report_issue with any technical issues observed "
            "(pass issues=[] if none)."
        ),
        "session_id": "heartbeat-digest-poll",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "morning_briefing",
        "schedule": "daily@08:40",
        "prompt": (
            "Prepare a short operational morning briefing using today's tasks, calendar, "
            "and any pending digest items. Keep it concise and actionable."
        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "calendar_check",
        "schedule": "daily@07:30",
        "prompt": (
            "Check today's calendar and summarize only the events and action items that "
            "matter operationally."
        ),
        "session_id": "heartbeat-calendar-check",
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


def build_mt_config(workspace_root: Path = Path("/app/workspace/mt")) -> AgentConfig:
    from agents.mt.tools import create_mt_mcp_server
    from agents.mt.fast_actions import mt_fast_path

    return AgentConfig(
        id="mt",
        name="MT",
        port=8009,
        workspace_path=workspace_root,
        telegram_token_env="TELEGRAM_MT_TOKEN",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
        mattermost_url_env="MATTERMOST_URL",
        mattermost_token_env="MATTERMOST_BOT_TOKEN",
        mattermost_channel_env="MT_MATTERMOST_CHANNEL_ID",
        domains=["inbox", "calendar", "drafting", "task_tracking"],
        capabilities=["email_triage", "calendar_management", "draft_preparation", "task_logging"],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="MT_",
        memory_backend="filesystem",
        mcp_server_factory=create_mt_mcp_server,
        a2a_fast_path=mt_fast_path,
        extra_mcp_servers={
            "protonmail-email": {"type": "sse", "url": "http://protonmail-mcp:3000/sse"},
            "gmx-email": {"type": "sse", "url": "http://gmx-mcp:3001/sse"},
        },
        builtin_crons=MT_BUILTIN_CRONS,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
        voice_enabled=True,
        voice_language="it",
        voice_tts_voice="it-IT-ElsaNeural",
    )
