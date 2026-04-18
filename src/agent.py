"""Jarvis CEO agent — the single intelligent entity at the heart of JarvisOS.

Creates an Agno Agent wired to:
- FallbackModel chain loaded from workspace/config/agent-models.yaml
- PostgreSQL session store (Agno's built-in PgAgentStorage)
- OpenClaw workspace instructions (SOUL.md, AGENTS.md, USER.md, …)
- Full tool suite: web search, shell, file ops, code execution
"""

import logging
from functools import lru_cache

from agno.agent import Agent
from agno.db.postgres import PostgresDb

from config import settings
from memory.daily_logger import DailyLogger
from memory.memory_api_client import MemoryAPIClient
from memory.session_manager import SessionManager
from memory.workspace_loader import load_workspace_context
from models.factory import build_agent_model_native

logger = logging.getLogger(__name__)


def _build_instructions(ctx: dict) -> str:
    """Assemble the full instruction block from workspace context dict."""
    parts = []

    if ctx.get("soul"):
        parts.append(f"## Identity & Soul\n\n{ctx['soul']}")

    if ctx.get("agents"):
        parts.append(f"## Operating Manual\n\n{ctx['agents']}")

    if ctx.get("user"):
        parts.append(f"## About Your User\n\n{ctx['user']}")

    if ctx.get("identity"):
        parts.append(f"## Self-Image\n\n{ctx['identity']}")

    if ctx.get("memory"):
        parts.append(f"## Long-Term Memory\n\n{ctx['memory']}")

    if ctx.get("daily"):
        parts.append(f"## Today's Memory Log\n\n{ctx['daily']}")

    if ctx.get("tools_md"):
        parts.append(f"## Tool Conventions\n\n{ctx['tools_md']}")

    if ctx.get("heartbeat"):
        parts.append(f"## Scheduled Tasks\n\n{ctx['heartbeat']}")

    return "\n\n---\n\n".join(parts)


def create_jarvis_agent() -> Agent:
    """Instantiate and return the Jarvis CEO agent.

    Called once at JarvisOS startup.  The agent is NOT a singleton here —
    callers may cache it themselves (e.g., the FastAPI lifespan).

    Returns:
        A configured agno.Agent instance ready to receive messages.
    """
    workspace_path = settings.workspace_path
    ctx = load_workspace_context(workspace_path)
    instructions = _build_instructions(ctx)

    primary_model, fallback_models = build_agent_model_native("jarvis")
    primary_id = f"{getattr(primary_model, 'provider', '?')}/{getattr(primary_model, 'id', '?')}"
    fallback_ids = [f"{getattr(m, 'provider', '?')}/{getattr(m, 'id', '?')}" for m in fallback_models]
    logger.info("agent: model chain — %s", " → ".join([primary_id] + fallback_ids))

    storage = PostgresDb(
        db_url=settings.DATABASE_URL,
        session_table="jarvis_sessions",
    )

    daily_logger = DailyLogger(workspace_path)
    daily_logger.log("[AGENT INIT] model chain ready")

    # --- Tool suite ----------------------------------------------------------
    from tools.code_executor import CodeExecutorTools
    from tools.file_tools import WorkspaceFileTools
    from tools.perplexity_search import PerplexitySearchTools
    from tools.shell_tools import ShellTools

    tools = [
        PerplexitySearchTools(),
        ShellTools(),
        WorkspaceFileTools(workspace_path=str(workspace_path)),
        CodeExecutorTools(),
        daily_logger,
    ]

    agent = Agent(
        name="Jarvis",
        model=primary_model,
        fallback_models=fallback_models if fallback_models else None,
        instructions=instructions,
        db=storage,
        tools=tools,
        # --- Context & history -----------------------------------------------
        add_datetime_to_context=True,
        num_history_runs=5,
        # --- Capabilities --------------------------------------------------------
        read_chat_history=True,
        markdown=True,
    )

    logger.info("agent: Jarvis CEO agent initialized")
    return agent


# ---------------------------------------------------------------------------
# Shared session manager (module-level singleton)
# ---------------------------------------------------------------------------

def create_session_manager() -> SessionManager:
    """Return a SessionManager wired to memory-api."""
    memory_client = MemoryAPIClient(
        base_url=settings.MEMORY_API_URL,
        user_id=settings.MEMORY_API_USER_ID,
    )
    return SessionManager(
        workspace_path=settings.workspace_path,
        memory_client=memory_client,
    )
