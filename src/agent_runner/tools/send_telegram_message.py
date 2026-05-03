"""send_telegram_message MCP tool — close the feedback loop with the user
after an async A2A delegation. Sends a Telegram message via the agent's
own Bot, OUTSIDE of any active stream.

Hardening (per Codex review 2026-05-03):
- Triple-guard: refuses unless (a) we're inside a continuation turn,
  (b) the continuation came from Telegram, (c) the chat_id matches this
  agent's allowed_chat_id. Prevents accidental DMs from cron-driven
  continuations or chat-id confusion.
- PTB lifecycle: uses ``async with Bot(token) as bot`` per send to
  guarantee the underlying httpx clients are closed (no leaked pool).
- Idempotency: SET NX on a Redis key keyed by parent_correlation_id so
  inbox retry/dead-letter cannot fire the tool more than once for the
  same delegation.
- RetryAfter backoff: respects Telegram's 429 Retry-After header up to
  one bounded retry.

See projects/jarvios-async-feedback-loop/2026-05-03-jarvios-async-feedback-loop.md
"""

import asyncio
import logging

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter

from agent_runner.comms.chain_context import read_chain_context
from agent_runner.config import AgentConfig

logger = logging.getLogger(__name__)

_IDEM_TTL_S = 86_400  # 24h — same as PendingResponseStore TTL
_TEXT_HARD_LIMIT = 4000  # Telegram bot API max (4096); leave headroom for ellipsis


def create_send_telegram_message_tool(config: AgentConfig, redis_a2a):
    """Return an async fn that sends a Telegram message via this agent's bot.

    Args:
        config: Per-agent config (provides token + allowed_chat_id env keys).
        redis_a2a: Shared RedisA2A instance — used for the idempotency lock.
    """
    async def send_telegram_message(args: dict) -> str:
        text = (args.get("text") or "").strip()
        if not text:
            return "Error: 'text' is required."
        if len(text) > _TEXT_HARD_LIMIT:
            text = text[: _TEXT_HARD_LIMIT - 1] + "…"

        # ----- Guard 1: must be inside a continuation turn ----------------
        chain = read_chain_context()
        if chain is None:
            return (
                "Error: send_telegram_message refused — not in an A2A "
                "continuation turn. This tool is only callable from the "
                "follow-up turn that fires when an [A2A-CONTINUATION] "
                "envelope drains. NEVER call it from an active Telegram "
                "stream (would double-post)."
            )

        # ----- Guard 2: continuation must originate from Telegram --------
        reply_channel = chain.get("reply_channel")
        reply_chat_id = chain.get("reply_chat_id")
        if reply_channel != "telegram" or not reply_chat_id:
            return (
                "Error: send_telegram_message refused — continuation has "
                f"no Telegram origin (reply_channel={reply_channel!r}, "
                f"reply_chat_id={reply_chat_id!r}). For non-Telegram "
                "continuations (cron, A2A-only), use daily_log instead."
            )

        # ----- Guard 3: chat_id must match this agent's allowed_chat_id --
        allowed_chat_id = config._resolve(config.telegram_chat_id_env)
        if not allowed_chat_id:
            return (
                f"Error: telegram chat env '{config.telegram_chat_id_env}' "
                "is not set — cannot validate target chat id."
            )
        if str(reply_chat_id) != str(allowed_chat_id):
            return (
                "Error: send_telegram_message refused — chat id from "
                f"continuation ({reply_chat_id!r}) does not match this "
                f"agent's allowed chat id ({allowed_chat_id!r}). "
                "Cross-agent / cross-user routing is not allowed."
            )

        # ----- Idempotency lock ------------------------------------------
        parent_cid = chain.get("parent_correlation_id")
        idem_key = f"a2a:feedback-sent:{parent_cid}"
        try:
            claimed = await redis_a2a.client.set(
                idem_key, "1", nx=True, ex=_IDEM_TTL_S
            )
        except Exception as exc:
            logger.warning(
                "send_telegram_message[%s]: idempotency check failed (%s) — "
                "proceeding anyway", config.id, exc,
            )
            claimed = True
        if not claimed:
            short_cid = parent_cid[:8] if parent_cid else "n/a"
            return (
                f"[Telegram feedback already sent for cid={short_cid} "
                "— no-op (idempotency guard)]"
            )

        # ----- Resolve token ---------------------------------------------
        token = config._resolve(config.telegram_token_env)
        if not token:
            try:
                await redis_a2a.client.delete(idem_key)
            except Exception:
                pass
            return f"Error: telegram token env '{config.telegram_token_env}' is not set."

        # ----- Send (Markdown then plain-text fallback, ONE Bot per send)
        try:
            async with Bot(token=token) as bot:
                try:
                    await bot.send_message(
                        chat_id=int(reply_chat_id),
                        text=text,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return (
                        f"[Telegram message sent to chat {reply_chat_id} "
                        f"({len(text)} chars, markdown)]"
                    )
                except BadRequest as exc:
                    # Markdown parse failed — retry once as plain text.
                    logger.info(
                        "send_telegram_message[%s]: markdown rejected (%s) — "
                        "retrying as plain text", config.id, exc,
                    )
                    await bot.send_message(chat_id=int(reply_chat_id), text=text)
                    return (
                        f"[Telegram message sent to chat {reply_chat_id} "
                        "(plain text fallback)]"
                    )
                except RetryAfter as exc:
                    # Telegram rate limit — wait and retry once.
                    delay = float(getattr(exc, "retry_after", 5.0))
                    logger.warning(
                        "send_telegram_message[%s]: 429 RetryAfter %.1fs",
                        config.id, delay,
                    )
                    await asyncio.sleep(min(delay, 30.0))
                    await bot.send_message(
                        chat_id=int(reply_chat_id),
                        text=text,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                    return (
                        f"[Telegram message sent to chat {reply_chat_id} "
                        f"(after {delay:.0f}s rate-limit wait)]"
                    )
        except Exception as exc:
            # Genuine send failure — release the idempotency lock so an
            # operator-driven retry can try again.
            try:
                await redis_a2a.client.delete(idem_key)
            except Exception:
                pass
            logger.warning(
                "send_telegram_message[%s]: send failed (%s)", config.id, exc,
            )
            return f"Error: telegram send failed: {exc}"

    return send_telegram_message
