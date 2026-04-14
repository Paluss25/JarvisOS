"""Human-in-the-loop permission gate via Telegram inline keyboard.

telegram_bot.py calls configure() after building the Application.
Tools call request_approval() which blocks until the user responds or times out.
telegram_bot.py's CallbackQueryHandler calls resolve() to unblock the waiter.
"""

import asyncio
import logging
import threading
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120  # seconds

# Populated by telegram_bot.configure_gate() at startup
_bot: Any = None
_event_loop: asyncio.AbstractEventLoop | None = None
_allowed_chat_id: int | None = None

# In-flight requests: request_id → threading.Event
_pending: dict[str, threading.Event] = {}
_results: dict[str, bool] = {}


def configure(bot: Any, event_loop: asyncio.AbstractEventLoop, allowed_chat_id: int) -> None:
    """Register the Telegram bot so the gate can send messages.

    Called by telegram_bot.start_polling() once the Application is ready.
    """
    global _bot, _event_loop, _allowed_chat_id
    _bot = bot
    _event_loop = event_loop
    _allowed_chat_id = allowed_chat_id
    logger.info("permission_gate: configured (chat_id=%s)", allowed_chat_id)


def resolve(request_id: str, approved: bool) -> None:
    """Unblock a pending request.  Called by the Telegram callback handler."""
    if request_id in _pending:
        _results[request_id] = approved
        _pending[request_id].set()


def request_approval(action: str, details: str, timeout: int = _DEFAULT_TIMEOUT) -> bool:
    """Send a Telegram approval request and block until the user responds.

    Args:
        action:  Short description of the action (e.g. "Delete file").
        details: Full details shown in the message body.
        timeout: Seconds to wait before auto-denying.

    Returns:
        True if approved, False if denied or timed out.
    """
    if _bot is None or _event_loop is None or _allowed_chat_id is None:
        logger.warning("permission_gate: not configured — auto-denying dangerous action")
        return False

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    request_id = uuid.uuid4().hex[:8]
    event = threading.Event()
    _pending[request_id] = event

    # Truncate details to keep the message readable
    details_snippet = details[:800] + ("…" if len(details) > 800 else "")
    text = (
        f"*Permission Required*\n\n"
        f"*Action:* {action}\n\n"
        f"```\n{details_snippet}\n```"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"gate:approve:{request_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"gate:deny:{request_id}"),
            ]
        ]
    )

    # Send message from the event loop (we're running in a thread)
    coro = _bot.send_message(
        chat_id=_allowed_chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    future = asyncio.run_coroutine_threadsafe(coro, _event_loop)
    try:
        future.result(timeout=10)
    except Exception as exc:
        logger.warning("permission_gate: failed to send approval request — %s", exc)
        _pending.pop(request_id, None)
        return False

    # Block until user responds or timeout
    responded = event.wait(timeout=timeout)
    result = _results.pop(request_id, False)
    _pending.pop(request_id, None)

    if not responded:
        logger.warning("permission_gate: request %s timed out after %ds", request_id, timeout)
        return False

    logger.info("permission_gate: request %s → %s", request_id, "approved" if result else "denied")
    return result
