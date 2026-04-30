"""CFO (Warren) agent configuration."""

from pathlib import Path

from agent_runner.config import AgentConfig


CFO_BUILTIN_CRONS = [
    {
        "name": "morning_cost_check",
        "schedule": "daily@08:30",
        "prompt": (
            "CFO morning check. Review yesterday's daily log and run a quick cost and portfolio pulse:\n"
            "1. Check for any budget deviations flagged in yesterday's log\n"
            "2. If CFO_COST_WORKERS_URL is configured, dispatch cost/ai-cost for yesterday's LLM spend\n"
            "3. Note any anomalies or pending fiscal deadlines\n"
            "Keep it under 150 words. Flag any HIGH severity items immediately to Jarvis via send_message. "        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "weekly_financial_brief",
        "schedule": "weekly@mon@09:30",
        "prompt": (
            "Weekly CFO Executive Brief for Jarvis. Compile a structured financial summary:\n\n"
            "**Budget:** YNAB spending adherence vs plan (dispatch ynab-finance and budget-control if available)\n"
            "**Crypto:** Portfolio status — current BTC positions if btc-fiscal-api is reachable\n"
            "**Costs:** LLM and infrastructure costs vs previous week (dispatch ai-cost if available)\n"
            "**Trading:** Polymarket P&L summary (dispatch polymarket-trade-journal if available)\n"
            "**Fiscal:** Any upcoming deadlines or compliance items\n\n"
            "Send the brief to Jarvis via send_message. If worker runtimes are unreachable, "
            "report their status and send a summary based on memory only."
        ),
        "session_id": "heartbeat-weekly-brief",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "weekly_memory_consolidation",
        "schedule": "weekly@sun@21:00",
        "prompt": (
            "Weekly CFO memory consolidation. Read all 7 daily logs from this week and the "
            "current MEMORY.md. Produce a rewritten MEMORY.md that includes:\n"
            "- Portfolio snapshots (crypto, trading positions) with timestamps\n"
            "- Budget status and any deviations > 10%\n"
            "- Cost trends (LLM spend, infrastructure)\n"
            "- Active fiscal compliance items (730, Quadro W deadlines)\n"
            "- Anomalies detected and their resolution status\n"
            "Remove stale entries older than 90 days unless they are fiscal records. "
            "Keep financial data precise: always include currency, date, and source. "
            "Return ONLY the raw markdown — no commentary."
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


def build_cfo_config(workspace_root: Path = Path("/app/workspace/cfo")) -> AgentConfig:
    from agents.cfo.tools import create_cfo_mcp_server
    return AgentConfig(
        id="cfo",
        name="Warren",
        port=8003,
        workspace_path=workspace_root,
        telegram_token_env="TELEGRAM_CFO_TOKEN",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
        domains=["finance", "crypto", "investments", "budgets", "fiscal"],
        capabilities=["budget-analysis", "crypto-portfolio", "cost-analysis", "trading-analysis", "fiscal-compliance"],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="CFO_",
        memory_backend="filesystem",
        mcp_server_factory=create_cfo_mcp_server,
        builtin_crons=CFO_BUILTIN_CRONS,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
        voice_enabled=True,
        voice_language="it",
        voice_tts_voice="it-IT-ElsaNeural",
        telegram_webhook_url_env="CFO_TELEGRAM_WEBHOOK_URL",
        telegram_webhook_secret_env="CFO_TELEGRAM_WEBHOOK_SECRET",
    )
