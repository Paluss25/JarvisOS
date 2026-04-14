"""Jarvis Telegram interface — polling mode.

Routes Telegram messages to the Jarvis CEO agent.
Auth: only TELEGRAM_ALLOWED_CHAT_ID is processed; all others silently ignored.

Commands:
    /start   — welcome message
    /status  — model chain + session info
    /session — current session ID
"""

import asyncio
import logging
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import settings
from src.middleware.auth import is_authorized

logger = logging.getLogger(__name__)

# Per-chat session IDs — reset on restart, keyed by Telegram chat_id
_chat_sessions: dict[int, str] = {}


def _get_or_create_session(chat_id: int, session_manager: Any) -> str:
    """Return the existing session for chat_id or create a new one."""
    if chat_id not in _chat_sessions:
        if session_manager:
            _chat_sessions[chat_id] = session_manager.start()
        else:
            _chat_sessions[chat_id] = str(chat_id)
    return _chat_sessions[chat_id]


async def _send_response(msg, text: str) -> None:
    """Send text as a Telegram message, falling back to plain text on parse error."""
    # Try Markdown first (may fail if agent output contains unbalanced syntax)
    try:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except BadRequest:
        try:
            await msg.edit_text(text)
        except Exception as exc:
            logger.warning("telegram: could not edit message — %s", exc)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update.effective_chat.id):
        return
    await update.message.reply_text(
        "Jarvis online. How can I assist you?",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update.effective_chat.id):
        return

    agent = context.bot_data.get("agent")
    if not agent:
        await update.message.reply_text("Agent not initialized.")
        return

    primary = agent.model
    provider = getattr(primary, "provider", "?")
    model_id = getattr(primary, "id", "?")
    chain_str = f"{provider}/{model_id}"

    session_id = _chat_sessions.get(update.effective_chat.id, "none")
    text = (
        f"*Jarvis Status*\n\n"
        f"Model: `{chain_str}`\n"
        f"Session: `{session_id}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def _cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update.effective_chat.id):
        return

    session_id = _chat_sessions.get(update.effective_chat.id)
    if session_id:
        await update.message.reply_text(
            f"Current session: `{session_id}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("No active session.")


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update.effective_chat.id):
        return

    agent = context.bot_data.get("agent")
    session_manager = context.bot_data.get("session_manager")

    if not agent:
        await update.message.reply_text("Agent not available. Try again shortly.")
        return

    chat_id = update.effective_chat.id
    session_id = _get_or_create_session(chat_id, session_manager)

    # Send typing action + placeholder while the agent thinks
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    placeholder = await update.message.reply_text("…")

    try:
        response = await asyncio.to_thread(
            agent.run,
            update.message.text,
            session_id=session_id,
        )
        content = response.content if hasattr(response, "content") else str(response)

        # Telegram hard limit: 4096 chars per message
        if len(content) <= 4096:
            await _send_response(placeholder, content)
        else:
            await placeholder.delete()
            for i in range(0, len(content), 4000):
                chunk = content[i : i + 4000]
                try:
                    await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                except BadRequest:
                    await update.message.reply_text(chunk)

    except Exception as exc:
        logger.error("telegram: error processing message — %s", exc, exc_info=True)
        try:
            await placeholder.edit_text(f"Sorry, something went wrong: {exc}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Polling entry point
# ---------------------------------------------------------------------------

async def start_polling(agent: Any, session_manager: Any) -> None:
    """Start Telegram polling in the current asyncio event loop.

    Designed to be launched as an asyncio.Task from JarvisOS lifespan.
    Runs until cancelled.

    Args:
        agent: The Jarvis CEO Agent instance.
        session_manager: SessionManager for per-chat session IDs.
    """
    if not settings.TELEGRAM_JARVIS_TOKEN:
        raise ValueError("TELEGRAM_JARVIS_TOKEN not configured")

    app = Application.builder().token(settings.TELEGRAM_JARVIS_TOKEN).build()

    # Inject agent + session_manager into bot_data for all handlers
    app.bot_data["agent"] = agent
    app.bot_data["session_manager"] = session_manager

    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CommandHandler("session", _cmd_session))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))

    logger.info(
        "telegram: starting polling (allowed_chat_id=%s)",
        settings.TELEGRAM_ALLOWED_CHAT_ID or "<not set>",
    )

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        try:
            await asyncio.Event().wait()  # block until Task is cancelled
        except asyncio.CancelledError:
            pass
        finally:
            await app.updater.stop()
            await app.stop()

    logger.info("telegram: polling stopped")
