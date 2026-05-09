"""NutritionDirector agent configuration.

NutritionDirector is headless — no telegram, no user-facing crons.
Nightly dreaming runs silently to consolidate nutrition memory.
"""

from pathlib import Path

from agent_runner.config import AgentConfig

NUTRITION_BUILTIN_CRONS = [
    {
        "name": "morning_nutrition_signal",
        "schedule": "daily@08:32",
        "prompt": (
            "Daily nutrition signal for COS. Review yesterday's nutrition memory/logs and today's known nutrition context. "
            "Report only material items: missed logging, macro/protein risk, stale goal data, unresolved food ambiguity, "
            "or any nutrition decision needed from Paluss. Keep it under 80 words. If nothing matters today, send a one-line green check. "
            "Send the summary to COS via send_message(to='cos', message=<your briefing>) for the single morning briefing. "
            "Do not send Telegram directly to Paluss from this cron."
        ),
        "session_id": "heartbeat-morning-nutrition-signal",
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
    {
        "name": "goal_review_prep",
        "schedule": "once@2026-05-19@09:03",
        "prompt": (
            "Goal review prep for COH/Jarvis review. Build a trusted W18/W19 nutrition snapshot "
            "using corrected values only: reject implausible API refinements, identify stale or "
            "superseded duplicate-memory claims, compare intake against active targets, and send "
            "a concise prep packet to COH via send_message(to='coh', message=<summary>, "
            "wait_response=false). Log the packet and any unresolved data-integrity gaps via daily_log."
        ),
        "session_id": "heartbeat-goal-review-prep",
        "telegram_notify": False,
        "builtin": True,
    },
]


def build_nutrition_config(workspace_root: Path = Path("/app/workspace/don")) -> AgentConfig:
    from agents.don.tools import create_nutrition_mcp_server
    from agents.don.fast_actions import handle_a2a_action
    return AgentConfig(
        id="don",
        name="NutritionDirector",
        port=8007,
        workspace_path=workspace_root,
        telegram_token_env="",
        telegram_chat_id_env="",
        domains=["nutrition", "meals", "diet"],
        capabilities=[
            "meal-recognition",
            "nutrition-resolution",
            "barcode-lookup",
            "meal-logging",
            "food-coaching",
        ],
        model_env="CLAUDE_MODEL",
        fallback_model_env="CLAUDE_FALLBACK_MODEL",
        budget_env="CLAUDE_MAX_BUDGET_USD",
        effort_env="CLAUDE_EFFORT",
        thinking_env="CLAUDE_THINKING",
        context_1m_env="CLAUDE_CONTEXT_1M",
        log_level_env="LOG_LEVEL",
        env_prefix="NUTRITION_",
        memory_backend="filesystem",
        # Same rationale as COH: progress-only streaming reduces Telegram
        # flood-control risk during long nutrition_execute summaries.
        telegram_streaming_mode="progress",
        mcp_server_factory=create_nutrition_mcp_server,
        a2a_fast_path=handle_a2a_action,
        builtin_crons=NUTRITION_BUILTIN_CRONS,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
        ],
    )
