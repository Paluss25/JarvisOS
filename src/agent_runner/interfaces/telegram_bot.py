"""Generic Telegram interface — polling mode.

Routes Telegram messages to a generic agent runner.
Auth: only the chat_id configured via AgentConfig is processed;
all others silently ignored.

Commands:
    /start         — welcome message
    /status        — model chain + session info
    /session       — current session detail (ID, summary, first prompt, tag)
    /sessions      — list last 5 sessions
    /rename        — rename current session: /rename My Session Title
    /tag           — tag current session: /tag work
    /fork          — fork current session into a new one
    /interrupt     — interrupt the current agent operation
    /tools         — show MCP server status
    /model         — show context usage or switch model: /model [name]
    /thinking      — toggle extended thinking: /thinking on|off|auto
    /deletesession — delete a session: /deletesession [session_id]
"""

import asyncio
import datetime
import logging
import os
import re
import time
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent_runner.middleware.auth import is_authorized

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


def _fmt_ts(ms: int) -> str:
    """Format a millisecond epoch timestamp as a human-readable string."""
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


async def _send_response(msg, text: str) -> None:
    """Send text as a Telegram message, falling back to plain text on parse error."""
    text = _reformat_tables(text)
    try:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except BadRequest:
        try:
            await msg.edit_text(text)
        except Exception as exc:
            logger.warning("telegram: could not edit message — %s", exc)


# ---------------------------------------------------------------------------
# Command handlers — agent config is stored in bot_data["config"]
# ---------------------------------------------------------------------------

async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    await update.message.reply_text(
        f"{config.name} online. How can I assist you?",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    agent = context.bot_data.get("agent")
    session_id = _chat_sessions.get(update.effective_chat.id, "none")
    model_label = getattr(agent, "name", "claude (sdk)") if agent else "not initialized"
    text = (
        f"*{config.name} Status*\n\n"
        f"Model: `claude (sdk)`\n"
        f"Agent: `{model_label}`\n"
        f"Session: `{session_id}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def _cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed info about the current session using get_session_info()."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    session_id = _chat_sessions.get(update.effective_chat.id)
    if not session_id:
        await update.message.reply_text("No active session.")
        return

    try:
        from claude_agent_sdk import get_session_info  # noqa: PLC0415
        info = get_session_info(session_id)

        lines = [f"*Session*\n\nID: `{session_id}`"]
        lines.append(f"Modified: {_fmt_ts(info.last_modified)}")
        if info.created_at:
            lines.append(f"Created: {_fmt_ts(info.created_at)}")
        if info.custom_title:
            lines.append(f"Title: *{info.custom_title}*")
        if info.tag:
            lines.append(f"Tag: `{info.tag}`")
        if info.first_prompt:
            lines.append(f"First: _{info.first_prompt[:120]}_")
        if info.summary:
            lines.append(f"\n_{info.summary[:300]}_")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as exc:
        logger.warning("telegram: get_session_info failed — %s", exc)
        await update.message.reply_text(
            f"Current session: `{session_id}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List the 5 most recent sessions."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    try:
        from claude_agent_sdk import list_sessions  # noqa: PLC0415
        raw = (list_sessions() or [])[:5]
        if not raw:
            await update.message.reply_text("No sessions found.")
            return

        current = _chat_sessions.get(update.effective_chat.id)
        lines = ["*Recent Sessions*\n"]
        for s in raw:
            ts = _fmt_ts(s.last_modified)
            label = s.custom_title or (s.first_prompt or "")[:50] or s.session_id[:8]
            tag = f" `[{s.tag}]`" if s.tag else ""
            marker = " ←" if s.session_id == current else ""
            lines.append(f"`{ts}`{tag} — {label}{marker}")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as exc:
        await update.message.reply_text(f"Could not list sessions: {exc}")


async def _cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rename the current session: /rename My Title."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    if not context.args:
        await update.message.reply_text("Usage: `/rename My Session Title`", parse_mode=ParseMode.MARKDOWN)
        return

    session_id = _chat_sessions.get(update.effective_chat.id)
    if not session_id:
        await update.message.reply_text("No active session.")
        return

    title = " ".join(context.args)
    try:
        from claude_agent_sdk import rename_session  # noqa: PLC0415
        rename_session(session_id, title)
        await update.message.reply_text(
            f"Session renamed to: *{title}*", parse_mode=ParseMode.MARKDOWN
        )
    except Exception as exc:
        await update.message.reply_text(f"Rename failed: {exc}")


async def _cmd_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tag the current session: /tag work. Pass '-' to remove the tag."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    if not context.args:
        await update.message.reply_text("Usage: `/tag <tag>` (or `/tag -` to remove)", parse_mode=ParseMode.MARKDOWN)
        return

    session_id = _chat_sessions.get(update.effective_chat.id)
    if not session_id:
        await update.message.reply_text("No active session.")
        return

    tag = context.args[0]
    tag_value = None if tag == "-" else tag
    try:
        from claude_agent_sdk import tag_session  # noqa: PLC0415
        tag_session(session_id, tag_value)
        if tag_value:
            await update.message.reply_text(
                f"Session tagged: `{tag_value}`", parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("Tag removed.")
    except Exception as exc:
        await update.message.reply_text(f"Tag failed: {exc}")


async def _cmd_fork(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fork the current session. The forked session becomes the active one."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    chat_id = update.effective_chat.id
    session_id = _chat_sessions.get(chat_id)
    if not session_id:
        await update.message.reply_text("No active session to fork.")
        return

    try:
        from claude_agent_sdk import fork_session  # noqa: PLC0415
        result = fork_session(session_id)
        new_id = result.session_id
        _chat_sessions[chat_id] = new_id
        await update.message.reply_text(
            f"Session forked.\nNew session: `{new_id}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        await update.message.reply_text(f"Fork failed: {exc}")


async def _cmd_interrupt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Interrupt the currently running agent operation."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    agent = context.bot_data.get("agent")
    if not agent:
        await update.message.reply_text("Agent not available.")
        return
    ok = await agent.interrupt()
    if ok:
        await update.message.reply_text("Interrupted.")
    else:
        await update.message.reply_text("Nothing to interrupt (or interrupt failed).")


async def _cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show MCP server connection status."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    agent = context.bot_data.get("agent")
    if not agent:
        await update.message.reply_text("Agent not available.")
        return
    status = await agent.get_mcp_status()
    if not status:
        await update.message.reply_text("No MCP servers or status unavailable.")
        return
    lines = ["*MCP Servers*\n"]
    for name, info in status.items():
        state = info if isinstance(info, str) else getattr(info, "status", str(info))
        lines.append(f"• `{name}`: {state}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def _cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/model [name] — show context usage (no arg) or switch model."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    agent = context.bot_data.get("agent")
    if not agent:
        await update.message.reply_text("Agent not available.")
        return
    if not context.args:
        usage = await agent.get_context_usage()
        if usage:
            lines = [
                "*Context Usage*\n",
                f"Input: `{usage.get('input_tokens', 0):,}` tokens",
                f"Output: `{usage.get('output_tokens', 0):,}` tokens",
                f"Cache read: `{usage.get('cache_read_tokens', 0):,}` tokens",
                f"Cache write: `{usage.get('cache_creation_tokens', 0):,}` tokens",
            ]
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(
                "Usage: `/model <model-name>` to switch model", parse_mode=ParseMode.MARKDOWN
            )
        return
    model_name = context.args[0]
    try:
        await agent.set_model(model_name)
        await update.message.reply_text(
            f"Model switched to: `{model_name}`", parse_mode=ParseMode.MARKDOWN
        )
    except Exception as exc:
        await update.message.reply_text(f"Failed to switch model: {exc}")


async def _cmd_thinking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/thinking on|off|auto — toggle extended thinking mode."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    agent = context.bot_data.get("agent")
    if not agent:
        await update.message.reply_text("Agent not available.")
        return
    if not context.args or context.args[0] not in ("on", "off", "auto"):
        await update.message.reply_text(
            "Usage: `/thinking on|off|auto`", parse_mode=ParseMode.MARKDOWN
        )
        return
    mode = context.args[0]
    await update.message.reply_text(
        f"Switching thinking to *{mode}*… (reconnecting subprocess)",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        await agent.set_thinking(mode)
        await update.message.reply_text(
            f"Thinking mode: *{mode}* ✓", parse_mode=ParseMode.MARKDOWN
        )
    except Exception as exc:
        await update.message.reply_text(f"Failed: {exc}")


async def _cmd_delete_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deletesession [id] — delete a session (current if no ID given)."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    chat_id = update.effective_chat.id
    target_id = context.args[0] if context.args else _chat_sessions.get(chat_id)
    if not target_id:
        await update.message.reply_text("No active session to delete.")
        return
    try:
        from claude_agent_sdk import delete_session  # noqa: PLC0415
        delete_session(target_id)
        if _chat_sessions.get(chat_id) == target_id:
            del _chat_sessions[chat_id]
        await update.message.reply_text(
            f"Session `{target_id}` deleted.", parse_mode=ParseMode.MARKDOWN
        )
    except ImportError:
        await update.message.reply_text("delete_session not available in this SDK version.")
    except Exception as exc:
        await update.message.reply_text(f"Delete failed: {exc}")


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------

_THINKING_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_THINKING_LABEL = " thinking…"
_TYPING_RENEW_INTERVAL = 4.0  # seconds between send_chat_action renewals

_TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
_TABLE_SEP_CELL_RE = re.compile(r"^[\s\-:]+$")


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return False
    return all(_TABLE_SEP_CELL_RE.match(c) for c in stripped[1:-1].split("|"))


def _render_table(lines: list[str]) -> str:
    """Convert Markdown table lines into a monospaced box table wrapped in a code block."""
    rows: list[list[str]] = []
    for line in lines:
        if _is_table_separator(line):
            continue
        cells = [c.strip() for c in line.strip()[1:-1].split("|")]
        rows.append(cells)

    if not rows:
        return "\n".join(lines)

    num_cols = max(len(r) for r in rows)
    rows = [r + [""] * (num_cols - len(r)) for r in rows]
    widths = [max(len(r[c]) for r in rows) for c in range(num_cols)]

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep]
    for idx, row in enumerate(rows):
        out.append("| " + " | ".join(row[c].ljust(widths[c]) for c in range(num_cols)) + " |")
        if idx == 0:
            out.append(sep)
    out.append(sep)
    return "```\n" + "\n".join(out) + "\n```"


def _reformat_tables(text: str) -> str:
    """Replace Markdown table blocks with monospaced code-block tables."""
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        if _TABLE_ROW_RE.match(lines[i]):
            block: list[str] = []
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            result.append(_render_table(block))
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)


async def _run_status_task(bot, chat_id: int, placeholder, state: dict) -> None:
    """Animate placeholder throughout the entire agent operation.

    Reads permission_hook._active_tool to show what tool the agent is calling.
    state = {"text": str, "done": bool}
    """
    from agent_runner.hooks import permission_hook as _ph
    frame_idx = 0
    last_typing = 0.0
    try:
        while not state["done"]:
            now = time.monotonic()
            if now - last_typing >= _TYPING_RENEW_INTERVAL:
                try:
                    await bot.send_chat_action(chat_id=chat_id, action="typing")
                    last_typing = now
                except Exception:
                    pass

            frame = _THINKING_FRAMES[frame_idx % len(_THINKING_FRAMES)]
            frame_idx += 1

            active_tool = _ph.get_active_tool()
            current_text = state["text"]

            if not current_text:
                display = f"{frame} {active_tool}…" if active_tool else frame + _THINKING_LABEL
            elif active_tool:
                display = current_text[:3800] + f"\n\n{frame} {active_tool}…"
            else:
                display = current_text[:4000] + " ▌"

            try:
                await placeholder.edit_text(display)
            except Exception:
                pass

            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Photo handler
# ---------------------------------------------------------------------------

async def _handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    agent = context.bot_data.get("agent")
    session_manager = context.bot_data.get("session_manager")

    if not agent:
        await update.message.reply_text("Agent not available. Try again shortly.")
        return

    chat_id = update.effective_chat.id
    session_id = _get_or_create_session(chat_id, session_manager)
    caption = update.message.caption or None

    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)

    import io
    buf = io.BytesIO()
    await photo_file.download_to_memory(buf)
    image_bytes = buf.getvalue()

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    placeholder = await update.message.reply_text(_THINKING_FRAMES[0] + _THINKING_LABEL)

    state: dict = {"text": "", "done": False}
    status_task = asyncio.create_task(
        _run_status_task(context.bot, chat_id, placeholder, state)
    )

    try:
        async for chunk in agent.stream_image(image_bytes, caption, session_id=session_id):
            state["text"] += chunk

        content = state["text"] or "(no response)"

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
        logger.error("telegram: error processing photo — %s", exc, exc_info=True)
        try:
            await placeholder.edit_text("Sorry, something went wrong processing the photo. Check the logs.")
        except Exception:
            pass
    finally:
        state["done"] = True
        status_task.cancel()


# ---------------------------------------------------------------------------
# Permission gate callback handler
# ---------------------------------------------------------------------------

async def _handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Approve / Deny responses from the permission gate inline keyboard."""
    config = context.bot_data.get("config")
    query = update.callback_query
    if not is_authorized(query.message.chat.id, config.telegram_chat_id_env):
        await query.answer("Not authorised.")
        return

    await query.answer()

    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "perm":
        return

    _, action, request_id = parts
    approved = action == "approve"

    from agent_runner.hooks import permission_hook
    permission_hook.resolve(request_id, approved)

    label = "✅ Approved" if approved else "❌ Denied"
    try:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(
            query.message.text + f"\n\n*{label}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    agent = context.bot_data.get("agent")
    session_manager = context.bot_data.get("session_manager")

    if not agent:
        await update.message.reply_text("Agent not available. Try again shortly.")
        return

    chat_id = update.effective_chat.id
    session_id = _get_or_create_session(chat_id, session_manager)

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    placeholder = await update.message.reply_text(_THINKING_FRAMES[0] + _THINKING_LABEL)

    state: dict = {"text": "", "done": False}
    status_task = asyncio.create_task(
        _run_status_task(context.bot, chat_id, placeholder, state)
    )

    try:
        async for chunk in agent.stream(update.message.text, session_id=session_id):
            state["text"] += chunk

        content = state["text"] or "(no response)"

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
            await placeholder.edit_text("Sorry, something went wrong. Check the logs.")
        except Exception:
            pass
    finally:
        state["done"] = True
        status_task.cancel()


# ---------------------------------------------------------------------------
# Polling entry point
# ---------------------------------------------------------------------------

async def start_polling(agent: Any, session_manager: Any, config: Any) -> None:
    """Start Telegram polling in the current asyncio event loop.

    Designed to be launched as an asyncio.Task from the agent lifespan.
    Runs until cancelled.

    Args:
        agent: The agent instance.
        session_manager: SessionManager for per-chat session IDs.
        config: AgentConfig — provides telegram_token_env, telegram_chat_id_env, name.
    """
    token = os.environ.get(config.telegram_token_env, "")
    chat_id_str = os.environ.get(config.telegram_chat_id_env, "")

    if not token:
        raise ValueError(f"{config.telegram_token_env} not configured")
    if not chat_id_str:
        raise ValueError(f"{config.telegram_chat_id_env} not configured")

    allowed_chat_id = int(chat_id_str)

    app = Application.builder().token(token).build()

    # Inject agent, session_manager, and config into bot_data for all handlers
    app.bot_data["agent"] = agent
    app.bot_data["session_manager"] = session_manager
    app.bot_data["config"] = config

    # Wire the async permission hook so tools can send approval requests
    from agent_runner.hooks import permission_hook as _hook

    async def _send_approval(text: str, request_id: str) -> None:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"perm:approve:{request_id}"),
            InlineKeyboardButton("❌ Deny", callback_data=f"perm:deny:{request_id}"),
        ]])
        await app.bot.send_message(
            chat_id=allowed_chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    async def _send_notification(text: str) -> None:
        try:
            await app.bot.send_message(
                chat_id=allowed_chat_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.warning("telegram: notification send failed — %s", exc)

    _hook.configure_hook(_send_approval, allowed_chat_id, notify_fn=_send_notification)

    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CommandHandler("session", _cmd_session))
    app.add_handler(CommandHandler("sessions", _cmd_sessions))
    app.add_handler(CommandHandler("rename", _cmd_rename))
    app.add_handler(CommandHandler("tag", _cmd_tag))
    app.add_handler(CommandHandler("fork", _cmd_fork))
    app.add_handler(CommandHandler("interrupt", _cmd_interrupt))
    app.add_handler(CommandHandler("tools", _cmd_tools))
    app.add_handler(CommandHandler("model", _cmd_model))
    app.add_handler(CommandHandler("thinking", _cmd_thinking))
    app.add_handler(CommandHandler("deletesession", _cmd_delete_session))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, _handle_photo))
    app.add_handler(CallbackQueryHandler(_handle_callback, pattern=r"^perm:"))

    logger.info(
        "telegram: starting polling for %s (allowed_chat_id=%s)",
        config.name, allowed_chat_id,
    )

    _COMMANDS = [
        ("start",         "Welcome message"),
        ("status",        "Agent status and session info"),
        ("session",       "Current session details"),
        ("sessions",      "List last 5 sessions"),
        ("rename",        "Rename current session"),
        ("tag",           "Tag current session"),
        ("fork",          "Fork current session"),
        ("interrupt",     "Interrupt current agent operation"),
        ("tools",         "Show MCP server status"),
        ("model",         "Show context usage or switch model"),
        ("thinking",      "Toggle extended thinking: on|off|auto"),
        ("deletesession", "Delete a session"),
    ]

    async with app:
        await app.start()
        try:
            from telegram import BotCommand
            await app.bot.set_my_commands([BotCommand(cmd, desc) for cmd, desc in _COMMANDS])
            logger.info("telegram: bot commands registered (%d commands)", len(_COMMANDS))
        except Exception as exc:
            logger.warning("telegram: could not register bot commands — %s", exc)
        await app.updater.start_polling(drop_pending_updates=True)

        try:
            await asyncio.Event().wait()  # block until Task is cancelled
        except asyncio.CancelledError:
            pass
        finally:
            await app.updater.stop()
            await app.stop()

    logger.info("telegram: polling stopped for %s", config.name)
