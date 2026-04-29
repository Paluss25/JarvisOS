"""Discord channel adapter.

Requires the following env vars on the agent:
    <prefix>DISCORD_TOKEN       — bot token from Discord Developer Portal
    <prefix>DISCORD_CHANNEL_ID  — (optional) restrict to one channel ID (int)

Install: discord.py>=2.3.0

IMPORTANT: The bot requires the MESSAGE_CONTENT privileged intent, which must be
enabled in the Discord Developer Portal under Bot → Privileged Gateway Intents.

Streaming reliability features mirror the Telegram adapter:
  - Abort fence (generation counter per user)
  - Streaming mode (partial/progress/block/off via AgentConfig.telegram_streaming_mode)
  - Timeout notification
  - Session recording
  - Retry loop with exponential backoff
"""

import asyncio
import datetime
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_UPDATE_INTERVAL = 2.0  # seconds between live message edits

# Per-user session tracking (keyed by Discord user_id int)
_user_sessions: dict[int, str] = {}
_user_session_dates: dict[int, str] = {}

# Abort fence: generation counter per user
_user_generations: dict[int, int] = {}

# Session recording
_user_last_exchange: dict[int, dict] = {}


def _get_or_create_session(user_id: int, session_manager: Any) -> str:
    today = datetime.date.today().isoformat()
    if user_id in _user_sessions and _user_session_dates.get(user_id) == today:
        return _user_sessions[user_id]
    try:
        session_id = session_manager.start() if session_manager else f"discord-{user_id}-{today}"
    except Exception:
        session_id = f"discord-{user_id}-{today}"
    _user_sessions[user_id] = session_id
    _user_session_dates[user_id] = today
    return session_id


async def start_discord(agent: Any, session_manager: Any, config: Any) -> None:
    """Start Discord bot. Runs until the asyncio Task is cancelled.

    Retries on network errors with exponential backoff (5s → 60s).
    """
    try:
        import discord
    except ImportError:
        raise ImportError(
            "discord: discord.py not installed — add discord.py>=2.3.0 to requirements.txt"
        )

    token = os.environ.get(config.discord_token_env, "")
    allowed_channel_str = os.environ.get(config.discord_channel_env, "")
    allowed_channel_id: int | None = int(allowed_channel_str) if allowed_channel_str else None

    if not token:
        raise ValueError(f"discord: {config.discord_token_env!r} not set")

    mode = getattr(config, "telegram_streaming_mode", "partial")
    retry_delay = 5
    attempt = 0

    while True:
        try:
            intents = discord.Intents.default()
            intents.message_content = True  # requires privileged intent in Developer Portal
            client = discord.Client(intents=intents)

            @client.event
            async def on_ready() -> None:
                logger.info(
                    "discord: logged in as %s for %s (channel=%s)",
                    client.user, config.name, allowed_channel_id or "all",
                )

            @client.event
            async def on_message(message: discord.Message) -> None:
                if message.author.bot:
                    return
                if allowed_channel_id and message.channel.id != allowed_channel_id:
                    return
                text = (message.content or "").strip()
                if not text:
                    return

                user_id = message.author.id
                session_id = _get_or_create_session(user_id, session_manager)

                my_gen = _user_generations.get(user_id, 0) + 1
                _user_generations[user_id] = my_gen

                placeholder = await message.channel.send("⠋ *thinking…*")
                accumulated = ""
                last_edit = time.monotonic()

                async def _update(content: str) -> None:
                    nonlocal last_edit
                    try:
                        await placeholder.edit(content=(content[:1990] or "⠋ *thinking…*"))
                        last_edit = time.monotonic()
                    except Exception as exc:
                        logger.warning("discord: message edit failed — %s", exc)

                async def _deliver_final(content: str) -> None:
                    """Edit placeholder or split into multiple messages if > 1990 chars."""
                    if len(content) <= 1990:
                        await _update(content)
                    else:
                        try:
                            await placeholder.delete()
                        except Exception:
                            pass
                        for i in range(0, len(content), 1990):
                            try:
                                await message.channel.send(content[i : i + 1990])
                            except Exception as exc:
                                logger.warning("discord: send chunk failed — %s", exc)

                try:
                    async for chunk in agent.stream(text, session_id=session_id):
                        if _user_generations.get(user_id) != my_gen:
                            logger.info("discord[%s]: stream aborted (generation superseded)", user_id)
                            break
                        accumulated += chunk
                        if mode == "partial" and time.monotonic() - last_edit >= _UPDATE_INTERVAL:
                            await _update(accumulated + " ▌")

                    await _deliver_final(accumulated or "(no response)")
                    _user_last_exchange[user_id] = {
                        "session_id": session_id,
                        "ts": datetime.datetime.now().isoformat(),
                        "msg_len": len(text),
                        "resp_len": len(accumulated),
                        "delivered": True,
                    }

                except TimeoutError:
                    logger.error("discord[%s]: stream timed out (gen %d)", user_id, my_gen)
                    await _update(
                        "⏱ Response timed out — the agent is still processing. "
                        "Check back shortly or retry your message."
                    )
                    _user_last_exchange[user_id] = {
                        "session_id": session_id,
                        "ts": datetime.datetime.now().isoformat(),
                        "delivered": False,
                    }

                except Exception as exc:
                    logger.error("discord: stream error for %s — %s", user_id, exc, exc_info=True)
                    partial = (accumulated[:1800] + "\n\n⚠️ *(stream interrupted)*") if accumulated else "Sorry, something went wrong."
                    await _update(partial)
                    _user_last_exchange[user_id] = {
                        "session_id": session_id,
                        "ts": datetime.datetime.now().isoformat(),
                        "delivered": False,
                    }

            logger.info("discord: connecting bot for %s", config.name)
            await client.start(token)
            break  # clean exit — reset backoff

        except asyncio.CancelledError:
            logger.info("discord: bot stopped for %s", config.name)
            try:
                await client.close()
            except Exception:
                pass
            raise
        except Exception as exc:
            attempt += 1
            logger.warning(
                "discord: connection error (attempt %d) — %s; retrying in %ds",
                attempt, exc, retry_delay,
            )
            try:
                await client.close()
            except Exception:
                pass
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

    logger.info("discord: adapter stopped for %s", config.name)
