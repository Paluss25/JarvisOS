"""NutritionDirector agent configuration.

NutritionDirector is headless — no builtin crons.
Scheduling is owned by DrHouse (Chief of Health).
"""

from pathlib import Path

from agent_runner.config import AgentConfig


def build_nutrition_config(workspace_root: Path = Path("/app/workspace/nutrition-director")) -> AgentConfig:
    from agents.nutrition.tools import create_nutrition_mcp_server
    return AgentConfig(
        id="nutrition-director",
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
        builtin_crons=[],
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
        ],
    )
