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
    /cron          — list/run/pause/resume scheduled tasks
    /cost          — show today's API spend
    /log           — show today's daily log (last N lines, or /log YYYY-MM-DD)
    /memory        — show or search MEMORY.md
    /note          — append a quick note to today's daily log
    /export        — download the daily log as a markdown file
    /remind        — set a CalDAV reminder via MT: /remind 2h Walk the dog
"""

import asyncio
import datetime
import io
import logging
import os
import re
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter
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

# Per-chat session IDs — reset on restart or on day boundary, keyed by Telegram chat_id
_chat_sessions: dict[int, str] = {}
_chat_session_dates: dict[int, str] = {}

# Abort fence: generation counter per chat_id.  Incremented on each new message;
# the in-flight stream checks its generation and exits early if a newer one arrived.
_chat_generations: dict[int, int] = {}

# Session recording: lightweight per-chat exchange log (in-memory).
# Tracks whether the last response was actually delivered to the user.
_chat_last_exchange: dict[int, dict] = {}


def _get_or_create_session(chat_id: int, session_manager: Any) -> str:
    """Return the existing session for chat_id or create a new one.

    A new session is started whenever the calendar date changes, preventing
    unbounded context growth across multiple days in persistent-mode agents.
    """
    today = datetime.date.today().isoformat()
    if chat_id in _chat_sessions and _chat_session_dates.get(chat_id) == today:
        return _chat_sessions[chat_id]
    # First message of the day (or first ever) — start a fresh session
    if session_manager:
        try:
            session_id = session_manager.start()
        except Exception:
            session_id = f"tg-{chat_id}-{today}"
    else:
        session_id = f"tg-{chat_id}-{today}"
    _chat_sessions[chat_id] = session_id
    _chat_session_dates[chat_id] = today
    return session_id


def _fmt_ts(ms: int) -> str:
    """Format a millisecond epoch timestamp as a human-readable string."""
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


async def _send_response(msg, text: str) -> None:
    """Send text as a Telegram message, falling back to plain text on parse error."""
    text = _strip_outer_code_fence(text)
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
            _chat_session_dates.pop(chat_id, None)
        await update.message.reply_text(
            f"Session `{target_id}` deleted.", parse_mode=ParseMode.MARKDOWN
        )
    except ImportError:
        await update.message.reply_text("delete_session not available in this SDK version.")
    except Exception as exc:
        await update.message.reply_text(f"Delete failed: {exc}")


async def _cmd_cron(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cron list|run|pause|resume — manage scheduled tasks."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    args = context.args or []
    sub = args[0].lower() if args else "list"

    from agent_runner.scheduler.cron_store import get_store
    store = get_store(config.workspace_path)

    if sub == "list":
        entries = store.all()
        if not entries:
            await update.message.reply_text("No crons configured.")
            return
        lines = ["*Scheduled Tasks*\n"]
        for e in entries:
            icon = "✅" if e.enabled else "⏸"
            last = e.last_run[:16] if e.last_run else "never"
            tag = " _(builtin)_" if e.builtin else ""
            lines.append(f"{icon} `{e.name}`{tag}\n  ↳ {e.schedule} | last: {last} | `{e.last_status}`")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    if sub == "run":
        if len(args) < 2:
            await update.message.reply_text("Usage: `/cron run <name>`", parse_mode=ParseMode.MARKDOWN)
            return
        name = args[1]
        entry = next((e for e in store.all() if e.name == name or e.id == name), None)
        if not entry:
            await update.message.reply_text(f"Cron `{name}` not found.", parse_mode=ParseMode.MARKDOWN)
            return
        await _stream_to_agent(update, context, f"[Manual cron trigger: {entry.name}]\n\n{entry.prompt}")
        return

    if sub in ("pause", "disable", "resume", "enable"):
        if len(args) < 2:
            await update.message.reply_text(f"Usage: `/cron {sub} <name>`", parse_mode=ParseMode.MARKDOWN)
            return
        name = args[1]
        entry = next((e for e in store.all() if e.name == name or e.id == name), None)
        if not entry:
            await update.message.reply_text(f"Cron `{name}` not found.", parse_mode=ParseMode.MARKDOWN)
            return
        new_state = sub in ("resume", "enable")
        store.update(entry.id, enabled=new_state)
        await update.message.reply_text(
            f"Cron `{entry.name}` {'resumed' if new_state else 'paused'}.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        "Usage:\n`/cron list`\n`/cron run <name>`\n`/cron pause <name>`\n`/cron resume <name>`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cost — show today's API spend from the daily log."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    try:
        from agent_runner.memory.daily_logger import DailyLogger
        log_text = DailyLogger(config.workspace_path).read_today()  # cost entries written to system log
        cost_re = re.compile(r"\[COST\] \$([0-9]+\.[0-9]+)")
        costs = [float(m) for m in cost_re.findall(log_text)]
        total = sum(costs)
        budget = getattr(config, "budget", None)
        budget_str = f" of ${budget:.2f}" if budget else ""
        calls = len(costs)
        avg = total / calls if calls else 0.0
        lines = [
            f"*API Cost — {datetime.date.today().isoformat()}*\n",
            f"Total: `${total:.4f}`{budget_str}",
            f"Calls: `{calls}`",
            f"Avg:   `${avg:.4f}` per call",
        ]
        if budget and total >= budget * 0.8:
            pct = total / budget * 100
            lines.append(f"\n⚠️ {pct:.0f}% of daily budget used")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as exc:
        await update.message.reply_text(f"Could not compute cost: {exc}")


async def _cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/log [YYYY-MM-DD] [N] — show the last N lines of a day's log (default: today, 30 lines)."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    args = list(context.args or [])
    target_date: datetime.date | None = None

    # Parse optional date argument (must look like YYYY-MM-DD)
    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        try:
            target_date = datetime.date.fromisoformat(args.pop(0))
        except ValueError:
            await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
            return

    # Parse optional line-count argument
    try:
        n = int(args[0]) if args else 30
        n = max(5, min(n, 100))
    except (ValueError, IndexError):
        n = 30

    try:
        from agent_runner.memory.daily_logger import DailyLogger
        dl = DailyLogger(config.workspace_path, user_id=update.effective_chat.id)
        if target_date:
            log_text = dl.read_date(target_date)
            date_label = target_date.isoformat()
        else:
            log_text = dl.read_today()
            date_label = datetime.date.today().isoformat()

        if not log_text.strip():
            await update.message.reply_text(f"No log entries for {date_label}.")
            return
        lines = log_text.strip().splitlines()
        tail = lines[-n:]
        header = f"*Daily Log — {date_label}* (last {len(tail)} lines)\n\n"
        body = "\n".join(tail)
        full = header + f"```\n{body}\n```"
        if len(full) > 4096:
            trim = 4096 - len(header) - 10
            full = header + f"```\n…{body[-trim:]}\n```"
        await update.message.reply_text(full, parse_mode=ParseMode.MARKDOWN)
    except Exception as exc:
        await update.message.reply_text(f"Could not read log: {exc}")


async def _cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/memory [search <query>] — show MEMORY.md or search it."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    args = context.args or []
    memory_path = Path(config.workspace_path) / "MEMORY.md"

    if not memory_path.exists():
        await update.message.reply_text("No MEMORY.md found.")
        return

    text = memory_path.read_text(encoding="utf-8")

    if args and args[0].lower() == "search" and len(args) > 1:
        query = " ".join(args[1:]).lower()
        matching = [line for line in text.splitlines() if query in line.lower()]
        if not matching:
            await update.message.reply_text(
                f"No matches for `{query}` in MEMORY.md.", parse_mode=ParseMode.MARKDOWN
            )
            return
        content = "\n".join(matching[:40])
        await update.message.reply_text(
            f"*MEMORY.md — `{query}`*\n\n```\n{content[:3800]}\n```",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    display = text if len(text) <= 3800 else text[:3800] + "\n\n… _(truncated)_"
    await update.message.reply_text(f"*MEMORY.md*\n\n{display}", parse_mode=ParseMode.MARKDOWN)


async def _cmd_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/note <text> — append a quick note to today's daily log."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    text = " ".join(context.args or []).strip()
    if not text:
        await update.message.reply_text("Usage: /note <your note>")
        return

    try:
        from agent_runner.memory.daily_logger import DailyLogger
        DailyLogger(config.workspace_path, user_id=update.effective_chat.id).log(f"[NOTE] {text}")
        await update.message.reply_text("📝 Note saved.", parse_mode=ParseMode.MARKDOWN)
    except Exception as exc:
        await update.message.reply_text(f"Could not save note: {exc}")


async def _cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/export [YYYY-MM-DD] — send the daily log as a markdown file."""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    args = list(context.args or [])
    target_date: datetime.date | None = None

    if args and re.match(r"^\d{4}-\d{2}-\d{2}$", args[0]):
        try:
            target_date = datetime.date.fromisoformat(args[0])
        except ValueError:
            await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
            return

    try:
        from agent_runner.memory.daily_logger import DailyLogger
        dl = DailyLogger(config.workspace_path, user_id=update.effective_chat.id)
        if target_date:
            log_text = dl.read_date(target_date)
            date_label = target_date.isoformat()
        else:
            log_text = dl.read_today()
            date_label = datetime.date.today().isoformat()

        if not log_text.strip():
            await update.message.reply_text(f"No log entries for {date_label}.")
            return

        filename = f"{config.id}-log-{date_label}.md"
        buf = io.BytesIO(log_text.encode("utf-8"))
        buf.name = filename
        await update.message.reply_document(
            document=buf,
            filename=filename,
            caption=f"Daily log — {config.name} — {date_label}",
        )
    except Exception as exc:
        await update.message.reply_text(f"Could not export log: {exc}")


def _parse_remind_time(token: str) -> datetime.datetime | None:
    """Parse a time token into a future datetime.

    Formats:
    - Relative: ``30m``, ``2h``, ``1h30m``  → now + delta
    - Absolute:  ``09:30``, ``14:00``        → today at HH:MM (tomorrow if past)
    """
    now = datetime.datetime.now()

    # Relative — e.g. 30m, 2h, 1h30m
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", token, re.IGNORECASE)
    if m and (m.group(1) or m.group(2)):
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        if hours or minutes:
            return now + datetime.timedelta(hours=hours, minutes=minutes)

    # Absolute — HH:MM
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", token)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mn < 60:
            target = now.replace(hour=h, minute=mn, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            return target

    return None


async def _cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/remind <time> <title> — create a CalDAV event via MT.

    Time formats: 30m | 2h | 1h30m | 09:30 | 14:00
    Examples:
      /remind 2h Dentist appointment
      /remind 09:30 Morning standup
    """
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    args = list(context.args or [])
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/remind <time> <title>`\n"
            "Examples:\n"
            "  `/remind 2h Dentist`\n"
            "  `/remind 09:30 Standup`\n"
            "  `/remind 1h30m Call Marco`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    time_token = args[0]
    title = " ".join(args[1:]).strip()

    start = _parse_remind_time(time_token)
    if start is None:
        await update.message.reply_text(
            f"Could not parse time `{time_token}`. Use: `30m`, `2h`, `1h30m`, `09:30`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    end = start + datetime.timedelta(minutes=30)
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    time_str = start.strftime("%d/%m %H:%M")

    redis_a2a = context.bot_data.get("redis_a2a")
    if redis_a2a is None:
        await update.message.reply_text(
            "Redis A2A not available — cannot route reminder to MT."
        )
        return

    try:
        import json
        from agent_runner.comms.message import A2AMessage

        payload = json.dumps({
            "action": "create_reminder",
            "title": title,
            "start": start_iso,
            "end": end_iso,
        })
        msg = A2AMessage(
            from_agent=config.id,
            to_agent="mt",
            type="request",
            payload=payload,
        )
        await redis_a2a.publish(msg)
        await update.message.reply_text(
            f"📅 Reminder set: *{title}* at {time_str}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logger.error("_cmd_remind: A2A publish failed — %s", exc)
        await update.message.reply_text(f"Failed to set reminder: {exc}")


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------

_THINKING_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_THINKING_LABEL = " thinking…"
_TYPING_RENEW_INTERVAL = 4.0  # seconds between send_chat_action renewals

# Valid values for AgentConfig.telegram_streaming_mode
_STREAMING_MODES = frozenset({"partial", "progress", "block", "off"})

_TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
_TABLE_SEP_CELL_RE = re.compile(r"^[\s\-:]+$")
_OUTER_FENCE_RE = re.compile(r"^\s*```(?:\w+)?\n(.*?)\n```\s*$", re.DOTALL)


def _strip_outer_code_fence(text: str) -> str:
    """Remove a single outer ``` fence if the entire response is wrapped in one."""
    m = _OUTER_FENCE_RE.match(text.strip())
    return m.group(1) if m else text


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


async def _create_placeholder(message) -> Any:
    """Send the initial thinking placeholder, retrying once on flood control.

    Returns the Message object on success, or None if both attempts fail.
    Logs failures instead of swallowing them silently.
    """
    for attempt in range(2):
        try:
            return await message.reply_text(_THINKING_FRAMES[0] + _THINKING_LABEL)
        except RetryAfter as exc:
            wait = min(float(exc.retry_after), 5.0)
            logger.warning(
                "telegram: placeholder flood control (attempt %d) — retry in %.1fs",
                attempt + 1, wait,
            )
            if attempt == 0:
                await asyncio.sleep(wait)
        except Exception as exc:
            logger.warning("telegram: placeholder creation failed — %s", exc)
            break
    return None


async def _typing_keepalive_task(bot, chat_id: int, state: dict) -> None:
    """Keep the Telegram 'typing...' header indicator alive while the agent is processing.

    Calls send_chat_action('typing') every _TYPING_RENEW_INTERVAL seconds until
    state["done"] is True.  Isolated from the animation task — a crash here does
    not affect the spinner, and vice versa.
    """
    try:
        while not state["done"]:
            try:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:
                pass
            if state["done"]:
                break
            await asyncio.sleep(_TYPING_RENEW_INTERVAL)
    except asyncio.CancelledError:
        pass  # normal task cancellation
    except Exception:
        pass  # suppress unexpected errors — task is best-effort


async def _run_status_task(bot, chat_id: int, placeholder, state: dict, mode: str = "partial") -> None:
    """Animate placeholder throughout the entire agent operation.

    Reads permission_hook.get_active_tool() to show what the agent is currently
    doing.  state = {"text": str, "done": bool, "block_ready": bool (block mode only)}

    Modes:
      partial  — update every 1s with partial text + cursor (default)
      progress — spinner + active tool name only; never exposes partial text
      block    — update only when state["block_ready"] is True (paragraph boundary)
    """
    try:
        from agent_runner.hooks import permission_hook as _ph
        frame_idx = 0
        while not state["done"]:
            try:
                active_tool = _ph.get_active_tool()
            except Exception:
                active_tool = ""

            frame = _THINKING_FRAMES[frame_idx % len(_THINKING_FRAMES)]
            frame_idx += 1

            if mode == "progress":
                # Show only spinner + active tool — never reveal partial response text
                display = f"{frame} {active_tool}…" if active_tool else frame + _THINKING_LABEL

            elif mode == "block":
                current_text = state["text"]
                if state.get("block_ready"):
                    state["block_ready"] = False
                    # Paragraph completed — show accumulated text with cursor
                    display = (current_text[:3800] + f"\n\n{frame} ▌") if current_text else frame + _THINKING_LABEL
                else:
                    # No new block yet — keep placeholder alive without overwriting content
                    display = (current_text[:3800] + f" {frame}") if current_text else frame + _THINKING_LABEL

            else:  # partial (default)
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
        pass  # normal task cancellation
    except Exception:
        pass  # suppress unexpected errors — task is best-effort


# ---------------------------------------------------------------------------
# Photo / image handler (shared helper used by both photo and document uploads)
# ---------------------------------------------------------------------------

async def _do_stream_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_bytes: bytes,
    caption: str | None,
) -> None:
    """Download → stream_image → deliver response. Used by photo and image-document handlers."""
    agent = context.bot_data.get("agent")
    session_manager = context.bot_data.get("session_manager")
    if not agent:
        await update.message.reply_text("Agent not available. Try again shortly.")
        return

    chat_id = update.effective_chat.id
    session_id = _get_or_create_session(chat_id, session_manager)

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    placeholder = await _create_placeholder(update.message)
    state: dict = {"text": "", "done": False}
    tasks = [asyncio.create_task(_typing_keepalive_task(context.bot, chat_id, state))]
    if placeholder is not None:
        tasks.append(asyncio.create_task(_run_status_task(context.bot, chat_id, placeholder, state)))

    async def _image_send_with_retry(coro_fn, *args, max_wait: float = 120.0, **kwargs):
        for attempt in range(3):
            try:
                return await coro_fn(*args, **kwargs)
            except RetryAfter as exc:
                wait = float(exc.retry_after)
                if wait > max_wait or attempt == 2:
                    raise
                logger.warning(
                    "telegram: flood control on image (attempt %d) — waiting %.0fs",
                    attempt + 1, wait,
                )
                await asyncio.sleep(wait)

    def _stop_image_tasks() -> None:
        state["done"] = True
        for t in tasks:
            if not t.done():
                t.cancel()

    # --- Phase 1: agent processing ---
    try:
        async for chunk in agent.stream_image(image_bytes, caption, session_id=session_id):
            state["text"] += chunk
    except Exception as exc:
        _stop_image_tasks()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.error("telegram: error processing image — %s", exc, exc_info=True)
        msg = "Sorry, something went wrong processing the image. Check the logs."
        try:
            if placeholder:
                await placeholder.edit_text(msg)
            else:
                await update.message.reply_text(msg)
        except Exception as notify_exc:
            logger.error("telegram: failed to notify user of image error — %s", notify_exc)
        return

    # --- Phase 2: delivery (processing succeeded) ---
    content = _strip_outer_code_fence(state["text"] or "(no response)")
    content = _reformat_tables(content)
    _stop_image_tasks()
    await asyncio.gather(*tasks, return_exceptions=True)

    try:
        if placeholder is None:
            await _image_send_with_retry(update.message.reply_text, content[:4096])
        elif len(content) <= 4096:
            try:
                await _image_send_with_retry(
                    placeholder.edit_text, content, parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest:
                try:
                    await _image_send_with_retry(placeholder.edit_text, content)
                except Exception as edit_exc:
                    logger.warning("telegram: image edit failed, trying reply — %s", edit_exc)
                    try:
                        await _image_send_with_retry(update.message.reply_text, content[:4096])
                    except Exception:
                        pass
        else:
            try:
                await placeholder.delete()
            except Exception:
                pass
            for i in range(0, len(content), 4000):
                piece = content[i : i + 4000]
                try:
                    await _image_send_with_retry(
                        update.message.reply_text, piece, parse_mode=ParseMode.MARKDOWN
                    )
                except BadRequest:
                    await _image_send_with_retry(update.message.reply_text, piece)
    except Exception as delivery_exc:
        logger.error(
            "telegram: delivery failed after successful image processing — %s",
            delivery_exc, exc_info=True,
        )
        try:
            await update.message.reply_text(content[:4000])
        except Exception:
            pass


async def _handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)
    buf = io.BytesIO()
    await photo_file.download_to_memory(buf)
    await _do_stream_image(update, context, buf.getvalue(), update.message.caption or None)


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
# HITL issue gate callback handler (CIO)
# ---------------------------------------------------------------------------

async def _handle_issue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Approve / Reject responses from CIO's HITL issue inline keyboard."""
    config = context.bot_data.get("config")
    query = update.callback_query
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env if config else None):
        await query.answer("Not authorised.")
        return

    await query.answer()

    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "issue":
        return

    _, action, task_id = parts
    approved = action == "approve"

    try:
        from agent_runner.issues import hitl_gate
        hitl_gate.resolve(task_id, approved)
    except ImportError:
        logger.warning("telegram: hitl_gate not available")
        return
    except Exception as exc:
        logger.error("telegram: hitl_gate.resolve failed task_id=%s — %s", task_id, exc)
        # fall through to UI cleanup so the keyboard is removed

    label = "✅ Accettato" if approved else "❌ Rifiutato"
    try:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(
            query.message.text + f"\n\n*{label}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Budget gate
# ---------------------------------------------------------------------------

async def _check_budget_ok(config: Any, update: Update) -> bool:
    """Return False (and notify user) when today's API spend exceeds the configured budget.

    Best-effort: any read/parse failure is silently swallowed so a broken log
    file never blocks the user.
    """
    budget = getattr(config, "budget", None)
    if not budget:
        return True
    try:
        from agent_runner.memory.daily_logger import DailyLogger
        log_text = DailyLogger(config.workspace_path).read_today()
        cost_re = re.compile(r"\[COST\] \$([0-9]+\.[0-9]+)")
        total = sum(float(m) for m in cost_re.findall(log_text))
        if total >= budget:
            await update.message.reply_text(
                f"⚠️ Budget limit reached: ${total:.4f} of ${budget:.2f} spent today.\n"
                "No further requests will be processed until midnight."
            )
            return False
    except Exception:
        pass
    return True


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

    Reliability features:
    - Abort fence: generation counter prevents stale streams from delivering after a newer
      message has already arrived for the same chat.
    - Streaming modes: partial / progress / block / off (from AgentConfig.telegram_streaming_mode).
    - Timeout notification: explicit Telegram message when stream timeout is reached.
    - Edit→reply fallback: if placeholder.edit_text fails, falls back to reply_text.
    - Session recording: tracks whether the last exchange was delivered successfully.
    """
    agent = context.bot_data.get("agent")
    session_manager = context.bot_data.get("session_manager")
    config = context.bot_data.get("config")
    mode = getattr(config, "telegram_streaming_mode", "partial")
    if mode not in _STREAMING_MODES:
        mode = "partial"

    if not agent:
        await update.message.reply_text("Agent not available. Try again shortly.")
        return

    if not await _check_budget_ok(config, update):
        return

    chat_id = update.effective_chat.id
    session_id = _get_or_create_session(chat_id, session_manager)

    # Abort fence: increment generation for this chat.  Any in-flight stream whose
    # generation no longer matches will stop yielding chunks and exit cleanly.
    my_gen = _chat_generations.get(chat_id, 0) + 1
    _chat_generations[chat_id] = my_gen

    # send_chat_action is just a UX hint — ignore transient network failures
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    # "off" mode skips the placeholder entirely; typing indicator still runs
    placeholder = None if mode == "off" else await _create_placeholder(update.message)

    state: dict = {"text": "", "done": False}
    tasks = [asyncio.create_task(_typing_keepalive_task(context.bot, chat_id, state))]
    if placeholder is not None:
        tasks.append(asyncio.create_task(_run_status_task(context.bot, chat_id, placeholder, state, mode=mode)))

    def _stop_tasks() -> None:
        state["done"] = True
        for t in tasks:
            if not t.done():
                t.cancel()

    async def _drain_tasks() -> None:
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _telegram_send_with_retry(coro_fn, *args, max_wait: float = 120.0, **kwargs):
        """Call a Telegram coroutine, honouring RetryAfter up to max_wait seconds."""
        for attempt in range(3):
            try:
                return await coro_fn(*args, **kwargs)
            except RetryAfter as exc:
                wait = float(exc.retry_after)
                if wait > max_wait or attempt == 2:
                    raise
                logger.warning(
                    "telegram: flood control (attempt %d) — waiting %.0fs before retry",
                    attempt + 1, wait,
                )
                await asyncio.sleep(wait)

    async def _deliver(content: str) -> None:
        """Send final content: edit placeholder if present, reply_text otherwise.
        Falls back to a new reply_text if edit fails with a permanent error.
        Respects Telegram flood control (RetryAfter) with up to 2 retries.
        """
        if placeholder is None:
            # off mode or placeholder failed — split and reply
            for i in range(0, len(content), 4000):
                piece = content[i : i + 4000]
                try:
                    await _telegram_send_with_retry(
                        update.message.reply_text, piece, parse_mode=ParseMode.MARKDOWN
                    )
                except BadRequest:
                    await _telegram_send_with_retry(update.message.reply_text, piece)
        elif len(content) <= 4096:
            try:
                await _telegram_send_with_retry(
                    placeholder.edit_text, content, parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest:
                try:
                    await _telegram_send_with_retry(placeholder.edit_text, content)
                except Exception as edit_exc:
                    logger.warning("telegram: edit failed, falling back to reply — %s", edit_exc)
                    try:
                        await _telegram_send_with_retry(
                            update.message.reply_text, content[:4096]
                        )
                    except Exception:
                        pass
        else:
            try:
                await placeholder.delete()
            except Exception:
                pass
            for i in range(0, len(content), 4000):
                piece = content[i : i + 4000]
                try:
                    await _telegram_send_with_retry(
                        update.message.reply_text, piece, parse_mode=ParseMode.MARKDOWN
                    )
                except BadRequest:
                    await _telegram_send_with_retry(update.message.reply_text, piece)

    async def _notify_error(msg: str) -> None:
        """Best-effort error notification: try edit, fall back to reply."""
        try:
            if placeholder:
                await _telegram_send_with_retry(placeholder.edit_text, msg)
            else:
                await _telegram_send_with_retry(update.message.reply_text, msg)
        except Exception:
            try:
                await _telegram_send_with_retry(update.message.reply_text, msg)
            except Exception as final_exc:
                logger.error("telegram: all error notification fallbacks failed — %s", final_exc)

    try:
        async for chunk in agent.stream(text, session_id=session_id):
            # Abort fence: a newer message arrived for this chat — stop this stream
            if _chat_generations.get(chat_id) != my_gen:
                logger.info("telegram[%s]: stream aborted (generation superseded)", chat_id)
                break
            state["text"] += chunk
            # block mode: flag paragraph boundaries for the status task
            if mode == "block" and "\n\n" in chunk:
                state["block_ready"] = True

        # Pre-process before the length check so _reformat_tables expansion is
        # accounted for — previously _send_response did this AFTER the check,
        # causing silent BadRequest failures when tables pushed content past 4096.
        content = _strip_outer_code_fence(state["text"] or "(no response)")
        content = _reformat_tables(content)

        # Stop animations BEFORE sending the final response to prevent
        # the status task from overwriting it with a spinner frame.
        _stop_tasks()
        await _drain_tasks()

        await _deliver(content)

        # Session recording: mark exchange as successfully delivered
        _chat_last_exchange[chat_id] = {
            "session_id": session_id,
            "ts": datetime.datetime.now().isoformat(),
            "msg_len": len(text),
            "resp_len": len(content),
            "delivered": True,
        }

    except TimeoutError:
        _stop_tasks()
        await _drain_tasks()
        logger.error("telegram[%s]: stream timed out (generation %d)", chat_id, my_gen)
        _chat_last_exchange[chat_id] = {
            "session_id": session_id,
            "ts": datetime.datetime.now().isoformat(),
            "msg_len": len(text),
            "resp_len": len(state.get("text", "")),
            "delivered": False,
        }
        await _notify_error(
            "⏱ Response timed out — the agent is still processing in the background. "
            "Check back shortly or retry your message."
        )

    except Exception as exc:
        _stop_tasks()
        await _drain_tasks()
        logger.error("telegram: error processing message — %s", exc, exc_info=True)
        _chat_last_exchange[chat_id] = {
            "session_id": session_id,
            "ts": datetime.datetime.now().isoformat(),
            "msg_len": len(text),
            "resp_len": len(state.get("text", "")),
            "delivered": False,
        }
        # Include any partial response already generated so the user isn't left empty-handed
        partial_text = state.get("text", "").strip()
        if partial_text:
            err_msg = _strip_outer_code_fence(partial_text)[:3800] + "\n\n⚠️ _(stream interrupted)_"
        else:
            err_msg = "Sorry, something went wrong. Check the logs."
        await _notify_error(err_msg)

    finally:
        _stop_tasks()
        await _drain_tasks()


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
# Voice handler  (STT → agent → TTS)
# ---------------------------------------------------------------------------

async def _handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Telegram voice messages: download → STT → agent → TTS reply.

    The handler is a no-op when voice_enabled=False (default), so registering
    it unconditionally is safe — agents that don't set the flag are unaffected.
    """
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return
    if not getattr(config, "voice_enabled", False):
        return

    agent = context.bot_data.get("agent")
    if not agent:
        await update.message.reply_text("Agent not available.")
        return

    chat_id = update.effective_chat.id

    # Download audio bytes (voice or forwarded audio file)
    voice_obj = update.message.voice or update.message.audio
    voice_file = await context.bot.get_file(voice_obj.file_id)
    buf = io.BytesIO()
    await voice_file.download_to_memory(buf)
    audio_bytes = buf.getvalue()

    # ── STT ──────────────────────────────────────────────────────────────────
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        from agent_runner.voice.stt import transcribe
        text = await transcribe(
            audio_bytes,
            backend=getattr(config, "voice_stt_backend", "faster-whisper"),
            model_size=getattr(config, "voice_whisper_model", "tiny"),
            language=getattr(config, "voice_language", None),
        )
    except Exception as exc:
        logger.error("voice: STT failed — %s", exc, exc_info=True)
        await update.message.reply_text(f"🎤 Transcription failed: {exc}")
        return

    if not text.strip():
        await update.message.reply_text("🎤 Could not make out the audio.")
        return

    # Echo transcript so the user knows what was heard
    try:
        await update.message.reply_text(f"🎤 _{text}_", parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(f"🎤 {text}")

    # ── Agent query (reuses full streaming infrastructure) ───────────────────
    session_manager = context.bot_data.get("session_manager")
    session_id = _get_or_create_session(chat_id, session_manager)
    mode = getattr(config, "telegram_streaming_mode", "partial")
    if mode not in _STREAMING_MODES:
        mode = "partial"

    my_gen = _chat_generations.get(chat_id, 0) + 1
    _chat_generations[chat_id] = my_gen

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    placeholder = None if mode == "off" else await _create_placeholder(update.message)

    state: dict = {"text": "", "done": False}
    tasks = [asyncio.create_task(_typing_keepalive_task(context.bot, chat_id, state))]
    if placeholder:
        tasks.append(asyncio.create_task(_run_status_task(context.bot, chat_id, placeholder, state, mode=mode)))

    def _stop() -> None:
        state["done"] = True
        for t in tasks:
            if not t.done():
                t.cancel()

    try:
        async for chunk in agent.stream(text, session_id=session_id):
            if _chat_generations.get(chat_id) != my_gen:
                logger.info("voice[%s]: stream aborted (generation superseded)", chat_id)
                break
            state["text"] += chunk

        content = _strip_outer_code_fence(state["text"] or "(no response)")
        content = _reformat_tables(content)

        _stop()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Deliver text response
        if placeholder and len(content) <= 4096:
            try:
                await placeholder.edit_text(content, parse_mode=ParseMode.MARKDOWN)
            except BadRequest:
                await placeholder.edit_text(content)
        else:
            if placeholder:
                try:
                    await placeholder.delete()
                except Exception:
                    pass
            for i in range(0, len(content), 4000):
                piece = content[i : i + 4000]
                try:
                    await update.message.reply_text(piece, parse_mode=ParseMode.MARKDOWN)
                except BadRequest:
                    await update.message.reply_text(piece)

        # ── TTS audio reply ──────────────────────────────────────────────────
        if getattr(config, "voice_tts_enabled", True) and content:
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action="record_voice")
                from agent_runner.voice.tts import synthesize, mp3_to_ogg_opus
                mp3 = await synthesize(
                    content,
                    backend=getattr(config, "voice_tts_backend", "edge"),
                    voice=getattr(config, "voice_tts_voice", "it-IT-ElsaNeural"),
                )
                if mp3:
                    ogg = await mp3_to_ogg_opus(mp3)
                    if ogg:
                        await update.message.reply_voice(voice=io.BytesIO(ogg))
                    else:
                        logger.warning("voice: OGG conversion produced empty output")
            except Exception as exc:
                logger.warning("voice: TTS failed (non-fatal) — %s", exc)

    except TimeoutError:
        _stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.error("voice[%s]: stream timed out", chat_id)
        try:
            if placeholder:
                await placeholder.edit_text("⏱ Response timed out.")
            else:
                await update.message.reply_text("⏱ Response timed out.")
        except Exception:
            pass

    except Exception as exc:
        _stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.error("voice: handler error — %s", exc, exc_info=True)
        try:
            if placeholder:
                await placeholder.edit_text("Sorry, something went wrong.")
            else:
                await update.message.reply_text("Sorry, something went wrong.")
        except Exception:
            pass

    finally:
        _stop()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Telegram document uploads.

    - Image MIME types (image/*) are forwarded to the vision pipeline via
      _do_stream_image so the agent can describe / analyse them.
    - All other files are saved to workspace/uploads/ and sent to the agent
      as a text prompt that includes the file path, MIME type, size, and any
      user caption — allowing the agent to open and process the file itself
      (e.g. pdfplumber for CHRO payslips).
    """
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_chat.id, config.telegram_chat_id_env):
        return

    doc = update.message.document
    if not doc:
        return

    mime = doc.mime_type or "application/octet-stream"
    caption = update.message.caption or ""
    safe_name = re.sub(r"[^\w.\-]", "_", doc.file_name or f"upload_{doc.file_id}")

    # Download file bytes
    try:
        doc_file = await context.bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await doc_file.download_to_memory(buf)
        file_bytes = buf.getvalue()
    except Exception as exc:
        logger.error("document: download failed — %s", exc, exc_info=True)
        await update.message.reply_text(f"Failed to download file: {exc}")
        return

    if mime.startswith("image/"):
        await _do_stream_image(update, context, file_bytes, caption or None)
        return

    # Save non-image file to workspace/uploads/
    try:
        uploads_dir = Path(config.workspace_path) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        dest = uploads_dir / safe_name
        dest.write_bytes(file_bytes)
    except Exception as exc:
        logger.error("document: save failed — %s", exc, exc_info=True)
        await update.message.reply_text(f"Failed to save file: {exc}")
        return

    size_kb = len(file_bytes) / 1024
    prompt_parts = [
        f"The user uploaded a file: {safe_name}",
        f"MIME type: {mime}",
        f"Size: {size_kb:.1f} KB",
        f"Saved to: {dest}",
    ]
    if caption:
        prompt_parts.append(f"User note: {caption}")
    prompt_parts.append("Process this file as appropriate for your domain.")
    prompt = "\n".join(prompt_parts)

    await update.message.reply_text(f"📎 Received {safe_name} ({size_kb:.1f} KB) — processing…")
    await _stream_to_agent(update, context, prompt)


# ---------------------------------------------------------------------------
# Polling entry point
# ---------------------------------------------------------------------------

async def start_polling(agent: Any, session_manager: Any, config: Any, redis_a2a: Any = None) -> None:
    """Start Telegram polling in the current asyncio event loop.

    Designed to be launched as an asyncio.Task from the agent lifespan.
    Runs until cancelled.

    Args:
        agent: The agent instance.
        session_manager: SessionManager for per-chat session IDs.
        config: AgentConfig — provides telegram_token_env, telegram_chat_id_env, name.
        redis_a2a: Optional RedisA2A instance for routing commands to other agents.
    """
    token = os.environ.get(config.telegram_token_env, "")
    chat_id_str = os.environ.get(config.telegram_chat_id_env, "")

    if not token:
        raise ValueError(f"{config.telegram_token_env} not configured")
    if not chat_id_str:
        raise ValueError(f"{config.telegram_chat_id_env} not configured")

    allowed_chat_id = int(chat_id_str)

    from agent_runner.hooks import permission_hook as _hook

    retry_delay = 5
    attempt = 0

    while True:
        try:
            app = Application.builder().token(token).build()

            # Inject agent, session_manager, config, and redis_a2a into bot_data
            app.bot_data["agent"] = agent
            app.bot_data["session_manager"] = session_manager
            app.bot_data["config"] = config
            app.bot_data["redis_a2a"] = redis_a2a

            # Wire the async permission hook so tools can send approval requests
            async def _send_approval(text: str, request_id: str, _app=app) -> None:
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Approve", callback_data=f"perm:approve:{request_id}"),
                    InlineKeyboardButton("❌ Deny", callback_data=f"perm:deny:{request_id}"),
                ]])
                await _app.bot.send_message(
                    chat_id=allowed_chat_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )

            async def _send_notification(text: str, _app=app) -> None:
                try:
                    await _app.bot.send_message(
                        chat_id=allowed_chat_id,
                        text=text,
                        parse_mode="Markdown",
                    )
                except Exception as exc:
                    logger.warning("telegram: notification send failed — %s", exc)

            _hook.configure_hook(_send_approval, allowed_chat_id, notify_fn=_send_notification)

            # Configure HITL gate (CIO only — no-op for other agents)
            try:
                from agent_runner.issues import hitl_gate as _hg

                async def _send_task_with_keyboard(text: str, task_id: str, _app=app) -> None:
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Accetta", callback_data=f"issue:approve:{task_id}"),
                        InlineKeyboardButton("❌ Rifiuta", callback_data=f"issue:reject:{task_id}"),
                    ]])
                    await _app.bot.send_message(
                        chat_id=allowed_chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.MARKDOWN,
                    )

                async def _send_plain_notification(text: str, _app=app) -> None:
                    try:
                        await _app.bot.send_message(
                            chat_id=allowed_chat_id,
                            text=text,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    except Exception as exc:
                        logger.warning("telegram: hitl plain notification failed — %s", exc)

                _hg.configure(_send_task_with_keyboard, _send_plain_notification)
            except ImportError:
                pass

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
            app.add_handler(CommandHandler("cron",          _cmd_cron))
            app.add_handler(CommandHandler("cost",          _cmd_cost))
            app.add_handler(CommandHandler("log",           _cmd_log))
            app.add_handler(CommandHandler("memory",        _cmd_memory))
            app.add_handler(CommandHandler("note",          _cmd_note))
            app.add_handler(CommandHandler("export",        _cmd_export))
            app.add_handler(CommandHandler("remind",        _cmd_remind))

            if getattr(config, "id", "").lower() == "dos":
                app.add_handler(CommandHandler("pesi",        _cmd_pesi))
                app.add_handler(CommandHandler("addome",      _cmd_addome))
                app.add_handler(CommandHandler("profilo",     _cmd_profilo))
                app.add_handler(CommandHandler("adduser",     _cmd_adduser))
                app.add_handler(CommandHandler("listusers",   _cmd_listusers))
                app.add_handler(CommandHandler("removeuser",  _cmd_removeuser))

            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
            app.add_handler(MessageHandler(filters.PHOTO, _handle_photo))
            app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, _handle_voice))
            app.add_handler(MessageHandler(filters.Document.ALL, _handle_document))
            app.add_handler(CallbackQueryHandler(_handle_callback, pattern=r"^perm:"))
            app.add_handler(CallbackQueryHandler(_handle_issue_callback, pattern=r"^issue:(approve|reject):\w+"))

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
                ("cron",          "List or trigger scheduled tasks"),
                ("cost",          "Show today's API spend"),
                ("log",           "Show today's activity log (or /log YYYY-MM-DD)"),
                ("memory",        "Show or search MEMORY.md"),
                ("note",          "Save a quick note to today's log"),
                ("export",        "Download daily log as a file"),
                ("remind",        "Set a CalDAV reminder via MT — /remind 2h Walk the dog"),
            ]

            if getattr(config, "id", "").lower() == "dos":
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

            break  # clean exit — reset backoff for next connection drop

        except asyncio.CancelledError:
            raise
        except NetworkError as exc:
            attempt += 1
            logger.warning(
                "telegram: network error (attempt %d) — %s; retrying in %ds",
                attempt, exc, retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

    logger.info("telegram: polling stopped for %s", config.name)
