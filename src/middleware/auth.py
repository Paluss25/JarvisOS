"""Auth middleware — Telegram chat_id allowlist.

If TELEGRAM_ALLOWED_CHAT_ID is empty, all messages are denied (safe default).
"""

from src.config import settings


def is_authorized(chat_id: int) -> bool:
    """Return True if chat_id matches the configured allowlist."""
    allowed = settings.TELEGRAM_ALLOWED_CHAT_ID
    if not allowed:
        return False
    return str(chat_id) == str(allowed)
