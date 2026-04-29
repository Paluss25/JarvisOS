"""CHRO (Chief People Officer) agent configuration."""

from pathlib import Path

from agent_runner.config import AgentConfig


CHRO_BUILTIN_CRONS = [
    {
        "name": "weekly_people_brief",
        "schedule": "weekly@mon@08:00",
        "prompt": (
            "Weekly People Brief — Monday morning HR summary for Paluss.\n"
            "Produce a structured Telegram message covering:\n"
            "1. Ferie e ROL: remaining days/hours this year — query chro.leave_snapshots for the most recent snapshot\n"
            "2. Ultimo cedolino: net pay, gross pay, IRPEF, INPS — query chro.payslips ORDER BY period_to DESC LIMIT 1\n"
            "3. TFR accantonato YTD: sum of tfr_accrued since Jan 1 of this year\n"
            "4. Anomalie: any payslip where net_pay varied more than 5% vs the previous month\n"
            "5. Scadenze imminenti: flag if ferie_remaining < 5 days and year-end is within 90 days\n"
            "Format with clear Italian section headers. Be concise. No legal advice.\n"
            "Send ONLY to Paluss via Telegram — do NOT forward to Jarvis or other agents."
        ),
        "session_id": "heartbeat-weekly-brief",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "monthly_payslip_check",
        "schedule": "weekly@sun@09:00",
        "prompt": (
            "Monthly payslip arrival reminder.\n"
            "Only act if today is the last Sunday of the month (day >= 25).\n"
            "Check chro.payslips for a record with period_to in the current month.\n"
            "If none found: remind Paluss via Telegram to upload this month's cedolino.\n"
            "If found: confirm it was processed and show the net/gross summary.\n"
            "If today is NOT the last Sunday of the month (day < 25), do nothing."
        ),
        "session_id": "heartbeat-monthly-payslip",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "net_pay_anomaly_alert",
        "schedule": "weekly@wed@09:00",
        "prompt": (
            "Net pay anomaly check.\n"
            "Query: SELECT period_from, period_to, net_pay FROM chro.payslips ORDER BY period_to DESC LIMIT 2\n"
            "If the latest net_pay differs from the previous by more than 5%, "
            "send a Telegram alert to Paluss: 'ANOMALIA CEDOLINO: netto variato di X% — verifica.'\n"
            "If no anomaly, do nothing (no message).\n"
            "If fewer than 2 payslips exist, do nothing."
        ),
        "session_id": "heartbeat-anomaly-check",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "leave_low_warning",
        "schedule": "weekly@mon@09:30",
        "prompt": (
            "Annual leave low-balance warning check.\n"
            "Only act if today is the first Monday of the month (day <= 7).\n"
            "Query: SELECT ferie_remaining, snapshot_date FROM chro.leave_snapshots ORDER BY snapshot_date DESC LIMIT 1\n"
            "If ferie_remaining < 5 days AND we are within 90 days of Dec 31, "
            "alert Paluss via Telegram: 'ATTENZIONE: Ferie residue critiche (X giorni). Pianifica prima della fine anno.'\n"
            "If balance is sufficient, we are not in Q4, or today is NOT the first Monday of the month (day > 7), do nothing."
        ),
        "session_id": "heartbeat-leave-warning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "weekly_memory_consolidation",
        "schedule": "weekly@sun@20:30",
        "prompt": (
            "Weekly HR memory consolidation. Review this week's daily logs and the current MEMORY.md. "
            "Update MEMORY.md with: current employment status, active HR flags, leave balance direction, "
            "TFR accrual trend, any policy changes or decisions made this week. "
            "Remove stale or superseded entries. Return ONLY the raw markdown — no commentary."
        ),
        "session_id": "heartbeat-weekly-memory",
        "telegram_notify": False,
        "builtin": True,
    },
]


def build_chro_config(workspace_root: Path = Path("/app/workspace/chro")) -> AgentConfig:
    from agents.chro.tools import create_chro_mcp_server
    return AgentConfig(
        id="chro",
        name="CHRO",
        port=8004,
        workspace_path=workspace_root,
        telegram_token_env="TELEGRAM_CHRO_TOKEN",
        telegram_chat_id_env="TELEGRAM_ALLOWED_CHAT_ID",
        domains=["hr", "payroll", "leave", "pension", "expenses", "compliance"],
        capabilities=[
            "payroll-analysis",
            "leave-tracking",
            "pension-monitoring",
            "document-processing",
            "italian-labor-law",
        ],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="CHRO_",
        memory_backend="filesystem",
        mcp_server_factory=create_chro_mcp_server,
        builtin_crons=CHRO_BUILTIN_CRONS,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
        voice_enabled=True,
        voice_language="it",
        voice_tts_voice="it-IT-ElsaNeural",
    )
