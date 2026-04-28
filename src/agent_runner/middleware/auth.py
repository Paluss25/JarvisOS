"""Auth middleware — Telegram chat_id allowlist.

Configurable per agent via the env var name stored in AgentConfig.
If the env var is unset or empty, all messages are denied (safe default).
"""

import os


def is_authorized(chat_id: int, allowed_chat_id_env: str) -> bool:
    """Return True if chat_id matches the configured allowlist.

    Args:
        chat_id: The Telegram chat ID to check.
        allowed_chat_id_env: Name of the env var holding the allowed chat ID.
    """
    allowed = os.environ.get(allowed_chat_id_env, "")
    if not allowed:
        return False
    return str(chat_id) in {cid.strip() for cid in allowed.split(",")}
