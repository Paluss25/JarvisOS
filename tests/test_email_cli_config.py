"""Email CLI migration guardrails for agent configs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_email_agents_do_not_register_external_email_mcp_servers():
    from agents.cos.config import build_chief_of_staff_config
    from agents.email_intelligence_agent.config import build_email_intelligence_config
    from agents.mt.config import build_mt_config

    configs = [
        build_email_intelligence_config(),
        build_chief_of_staff_config(),
        build_mt_config(),
    ]

    for config in configs:
        assert "protonmail-email" not in config.extra_mcp_servers
        assert "gmx-email" not in config.extra_mcp_servers


def test_email_poll_prompt_uses_mailctl_not_email_mcp():
    from agents.email_intelligence_agent.config import EMAIL_INTELLIGENCE_BUILTIN_CRONS

    email_poll = next(cron for cron in EMAIL_INTELLIGENCE_BUILTIN_CRONS if cron["name"] == "email_poll")

    assert "mailctl list" in email_poll["prompt"]
    assert "MCP" not in email_poll["prompt"]
