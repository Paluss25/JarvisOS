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

        # Stop the animation BEFORE sending the final response.
        state["done"] = True
        status_task.cancel()
        await asyncio.sleep(0)

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

async def _stream_to_agent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    """Dispatch an arbitrary text string to the agent and stream the response.

    Used by both the regular message handler and sport shortcut commands
    (/pesi, /addome) that convert a command into a natural-language sentence
    before forwarding it to the agent.
    """
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
        async for chunk in agent.stream(text, session_id=session_id):
            state["text"] += chunk

        content = state["text"] or "(no response)"

        # Stop the animation BEFORE sending the final response to prevent
        # the status task from overwriting it with a spinner frame.
        state["done"] = True
        status_task.cancel()
        await asyncio.sleep(0)  # yield so the task processes CancelledError first

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


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    await _stream_to_agent(update, context, update.message.text)


# ---------------------------------------------------------------------------
# Roger-specific sport shortcut commands
# ---------------------------------------------------------------------------

async def _cmd_pesi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shortcut: /pesi 81.5 — log body weight, forwarded to Roger as structured input."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/pesi 81.5`", parse_mode=ParseMode.MARKDOWN)
        return
    weight = context.args[0]
    await _stream_to_agent(update, context, f"Ho pesato {weight} kg oggi")


async def _cmd_addome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shortcut: /addome 84 — log waist circumference, forwarded to Roger."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/addome 84`", parse_mode=ParseMode.MARKDOWN)
        return
    cm = context.args[0]
    await _stream_to_agent(update, context, f"Circonferenza addominale oggi: {cm} cm")


async def _cmd_profilo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or update athlete profile: /profilo | /profilo altezza 178 | /profilo nascita 1990-05-15 | /profilo sesso M"""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    url = os.environ.get("SPORT_POSTGRES_URL", "")
    if not url:
        await update.message.reply_text("DB non configurato (`SPORT_POSTGRES_URL` mancante).", parse_mode=ParseMode.MARKDOWN)
        return

    args = context.args or []
    chat_id = update.effective_chat.id

    try:
        import asyncpg
        conn = await asyncpg.connect(url)
        try:
            # Resolve user_id from telegram_chat_id
            user_row = await conn.fetchrow(
                "SELECT id, name FROM users WHERE telegram_chat_id = $1 AND is_active = true", chat_id
            )
            if not user_row:
                await update.message.reply_text("Utente non trovato nel DB. Contatta l'admin.")
                return
            user_id = user_row["id"]
            user_name = user_row["name"]

            # Ensure profile row exists
            await conn.execute(
                "INSERT INTO athlete_profile (user_id, name) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
                user_id, user_name,
            )

            if not args:
                # Read profile
                row = await conn.fetchrow("SELECT * FROM athlete_profile WHERE user_id = $1", user_id)
                dob = row["date_of_birth"]
                height = row["height_cm"]
                sex = row["sex"] or "—"
                age_str = "—"
                if dob:
                    today = datetime.date.today()
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                    age_str = f"{age} anni"
                lines = [
                    f"*Profilo atleta — {user_name}*",
                    f"Altezza: {height} cm" if height else "Altezza: — _(non impostata)_",
                    f"Data di nascita: {dob} \\({age_str}\\)" if dob else "Data di nascita: — _(non impostata)_",
                    f"Sesso: {sex}",
                    "",
                    "_Modifica: /profilo altezza 178 \\| /profilo nascita 1990\\-05\\-15 \\| /profilo sesso M_",
                ]
                await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)
                return

            field = args[0].lower()
            if len(args) < 2:
                await update.message.reply_text(
                    "Specifica il valore. Esempi:\n"
                    "`/profilo altezza 178`\n"
                    "`/profilo nascita 1990-05-15`\n"
                    "`/profilo sesso M`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            value = args[1]

            if field in ("altezza", "height"):
                try:
                    h = float(value)
                except ValueError:
                    await update.message.reply_text("Altezza non valida. Esempio: `/profilo altezza 178`", parse_mode=ParseMode.MARKDOWN)
                    return
                await conn.execute(
                    "UPDATE athlete_profile SET height_cm = $1, updated_at = now() WHERE user_id = $2", h, user_id
                )
                await update.message.reply_text(f"Altezza aggiornata: *{h} cm*", parse_mode=ParseMode.MARKDOWN)

            elif field in ("nascita", "dob", "birthday"):
                try:
                    dob = datetime.date.fromisoformat(value)
                except ValueError:
                    await update.message.reply_text("Data non valida. Formato: `YYYY-MM-DD`", parse_mode=ParseMode.MARKDOWN)
                    return
                await conn.execute(
                    "UPDATE athlete_profile SET date_of_birth = $1, updated_at = now() WHERE user_id = $2", dob, user_id
                )
                today = datetime.date.today()
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                await update.message.reply_text(f"Data di nascita: *{dob}* \\({age} anni\\)", parse_mode=ParseMode.MARKDOWN_V2)

            elif field in ("sesso", "sex"):
                s = value.upper()
                if s not in ("M", "F", "OTHER"):
                    await update.message.reply_text("Sesso non valido. Usa `M`, `F`, o `other`.", parse_mode=ParseMode.MARKDOWN)
                    return
                await conn.execute(
                    "UPDATE athlete_profile SET sex = $1, updated_at = now() WHERE user_id = $2", s, user_id
                )
                await update.message.reply_text(f"Sesso aggiornato: *{s}*", parse_mode=ParseMode.MARKDOWN)

            else:
                await update.message.reply_text(
                    "Campo non riconosciuto. Usa: `altezza`, `nascita`, `sesso`.",
                    parse_mode=ParseMode.MARKDOWN,
                )
        finally:
            await conn.close()
    except Exception as exc:
        logger.error("_cmd_profilo: error — %s", exc)
        await update.message.reply_text(f"Errore DB: {exc}")


async def _cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/adduser <telegram_chat_id> <name> — register a new user in sport_metrics."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    if len(context.args or []) < 2:
        chat_id = update.effective_chat.id
        await update.message.reply_text(
            "Usage: `/adduser <telegram_chat_id> <nome>`\n"
            f"Esempio: `/adduser {chat_id} Mario`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = os.environ.get("SPORT_POSTGRES_URL", "")
    if not url:
        await update.message.reply_text("DB non configurato.")
        return

    try:
        new_chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("telegram_chat_id deve essere un numero intero.")
        return

    name = " ".join(context.args[1:])

    try:
        import asyncpg
        conn = await asyncpg.connect(url)
        try:
            existing = await conn.fetchrow("SELECT id, is_active FROM users WHERE telegram_chat_id = $1", new_chat_id)
            if existing:
                if existing["is_active"]:
                    await update.message.reply_text(f"Utente `{name}` (chat_id {new_chat_id}) già registrato.", parse_mode=ParseMode.MARKDOWN)
                else:
                    await conn.execute("UPDATE users SET is_active = true, name = $1 WHERE telegram_chat_id = $2", name, new_chat_id)
                    await update.message.reply_text(f"Utente `{name}` riattivato.", parse_mode=ParseMode.MARKDOWN)
                return
            row = await conn.fetchrow(
                "INSERT INTO users (telegram_chat_id, name) VALUES ($1, $2) RETURNING id",
                new_chat_id, name,
            )
            user_id = row["id"]
            await conn.execute(
                "INSERT INTO athlete_profile (user_id, name) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
                user_id, name,
            )
            await update.message.reply_text(
                f"✅ Utente *{name}* registrato \\(id={user_id}\\)\\. "
                f"Usa `/start` nel suo chat per iniziare\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.error("_cmd_adduser: error — %s", exc)
        await update.message.reply_text(f"Errore: {exc}")


async def _cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/listusers — show all registered users."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    url = os.environ.get("SPORT_POSTGRES_URL", "")
    if not url:
        await update.message.reply_text("DB non configurato.")
        return

    try:
        import asyncpg
        conn = await asyncpg.connect(url)
        try:
            rows = await conn.fetch("SELECT id, name, telegram_chat_id, is_active, is_admin, created_at FROM users ORDER BY id")
            if not rows:
                await update.message.reply_text("Nessun utente registrato.")
                return
            lines = ["*Utenti registrati:*\n"]
            for r in rows:
                status = "✅" if r["is_active"] else "❌"
                admin_tag = " 👑" if r["is_admin"] else ""
                lines.append(f"{status} *{r['name']}*{admin_tag} — chat_id: `{r['telegram_chat_id']}` (id={r['id']})")
            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        finally:
            await conn.close()
    except Exception as exc:
        logger.error("_cmd_listusers: error — %s", exc)
        await update.message.reply_text(f"Errore: {exc}")


async def _cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/removeuser <nome_o_user_id> — deactivate a user (does not delete data)."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    if not context.args:
        await update.message.reply_text("Usage: `/removeuser <nome_o_user_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    url = os.environ.get("SPORT_POSTGRES_URL", "")
    if not url:
        await update.message.reply_text("DB non configurato.")
        return

    target = context.args[0]

    try:
        import asyncpg
        conn = await asyncpg.connect(url)
        try:
            # Try numeric ID first, then name
            try:
                row = await conn.fetchrow("SELECT id, name FROM users WHERE id = $1", int(target))
            except ValueError:
                row = await conn.fetchrow("SELECT id, name FROM users WHERE lower(name) = lower($1)", target)
            if not row:
                await update.message.reply_text(f"Utente `{target}` non trovato.", parse_mode=ParseMode.MARKDOWN)
                return
            await conn.execute("UPDATE users SET is_active = false WHERE id = $1", row["id"])
            await update.message.reply_text(f"Utente *{row['name']}* disattivato (dati conservati).", parse_mode=ParseMode.MARKDOWN)
        finally:
            await conn.close()
    except Exception as exc:
        logger.error("_cmd_removeuser: error — %s", exc)
        await update.message.reply_text(f"Errore: {exc}")


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

    if config.name.lower() == "roger":
        app.add_handler(CommandHandler("pesi",        _cmd_pesi))
        app.add_handler(CommandHandler("addome",      _cmd_addome))
        app.add_handler(CommandHandler("profilo",     _cmd_profilo))
        app.add_handler(CommandHandler("adduser",     _cmd_adduser))
        app.add_handler(CommandHandler("listusers",   _cmd_listusers))
        app.add_handler(CommandHandler("removeuser",  _cmd_removeuser))

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

    if config.name.lower() == "roger":
        _COMMANDS += [
            ("pesi",        "Log body weight — /pesi 81.5"),
            ("addome",      "Log waist circumference — /addome 84"),
            ("profilo",     "View or update athlete profile (height, DOB, sex)"),
            ("adduser",     "Admin: register a new user"),
            ("listusers",   "Admin: list all users"),
            ("removeuser",  "Admin: deactivate a user"),
        ]

    async with app:
        await app.start()
        try:
            from telegram import BotCommand
            await app.bot.set_my_commands([BotCommand(cmd, desc) for cmd, desc in _COMMANDS])
            logger.info("telegram: bot commands registered (%d commands)", len(_COMMANDS))
        except Exception as exc:
            logger.warning("telegram: could not register bot commands — %s", exc)
        await app.updater.start_polling(drop_pending_updates=False)

        try:
            await asyncio.Event().wait()  # block until Task is cancelled
        except asyncio.CancelledError:
            pass
        finally:
            await app.updater.stop()
            await app.stop()

    logger.info("telegram: polling stopped for %s", config.name)
