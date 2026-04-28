"""NutritionDirector agent configuration.

NutritionDirector is headless — no telegram, no user-facing crons.
Nightly dreaming runs silently to consolidate nutrition memory.
"""

from pathlib import Path

from agent_runner.config import AgentConfig

NUTRITION_BUILTIN_CRONS = [
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
        mcp_server_factory=create_nutrition_mcp_server,
        a2a_fast_path=handle_a2a_action,
        builtin_crons=NUTRITION_BUILTIN_CRONS,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
        ],
    )
