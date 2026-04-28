"""Auth middleware — Telegram chat_id allowlist.

If TELEGRAM_ALLOWED_CHAT_ID is empty, all messages are denied (safe default).
Supports multiple chat IDs as a comma-separated list in the env var.
"""

from config import settings


def is_authorized(chat_id: int) -> bool:
    """Return True if chat_id is in the configured allowlist."""
    raw = settings.TELEGRAM_ALLOWED_CHAT_ID.strip()
    if not raw:
        return False
    allowed = {cid.strip() for cid in raw.split(",") if cid.strip()}
    return str(chat_id) in allowed
