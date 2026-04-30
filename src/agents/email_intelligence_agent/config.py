"""Email Intelligence Agent configuration."""

import asyncio
import logging
from pathlib import Path

from agent_runner.config import AgentConfig

logger = logging.getLogger(__name__)


async def _emailintel_a2a_fast_path(payload: dict) -> dict | None:
    """Bypass LLM for structured process_email A2A calls from COS."""
    if payload.get("action") != "process_email":
        return None
    try:
        import os
        from pathlib import Path
        from agents.email_intelligence_agent.tools import (
            _run_security_pipeline,
            _compute_action_hint,
            _write_to_digest,
        )
        result = await asyncio.to_thread(
            _run_security_pipeline,
            email_id=payload.get("email_id", ""),
            account=payload.get("account", ""),
            subject=payload.get("subject", "(no subject)"),
            body=payload.get("body", "(empty body)"),
            attachments=payload.get("attachments", []),
            sender=payload.get("sender", ""),
            received_at=payload.get("received_at", ""),
        )
        if not result.get("blocked") and result.get("policy", {}).get("allow"):
            digest_path = Path(os.environ.get("MT_DIGEST_PATH", "/app/shared/mt_digest.json"))
            try:
                _write_to_digest(
                    {**result, "mt_action_hint": _compute_action_hint(result)},
                    digest_path,
                )
            except Exception as digest_exc:
                logger.warning("emailintel fast_path: digest write failed — %s", digest_exc)
        logger.info("emailintel fast_path: processed email_id=%s", payload.get("email_id"))
        return result
    except Exception as exc:
        logger.error("emailintel fast_path error: %s", exc)
        # Fail closed — do not silently fall through to the LLM for a
        # safety-critical structured email-processing request.
        return {
            "blocked": True,
            "email_id": payload.get("email_id", ""),
            "account": payload.get("account", ""),
            "policy": {
                "decision": "error",
                "allow": False,
                "reasons": [f"fast_path_exception: {exc}"],
                "constraints": [],
            },
        }


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
        "schedule": "daily@08:05",
        "prompt": (
            "Morning email briefing. Poll for unread emails on all accounts (process up to 20). "
            "After processing, send a summary to cos via send_message: "
            "how many emails processed, breakdown by domain, any quarantined items, "
            "any high-risk items. Keep summary under 150 words. "
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


def build_email_intelligence_config(
    workspace_root: Path = Path("/app/workspace/email_intelligence_agent"),
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
        a2a_fast_path=_emailintel_a2a_fast_path,
        allowed_tools=[
            "Bash", "Read", "Write", "Edit",
            "WebSearch", "WebFetch", "Glob", "Grep",
            "Agent",
        ],
    )
