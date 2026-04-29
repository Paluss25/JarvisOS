"""Slack channel adapter — Socket Mode, single-workspace bot.

Requires the following env vars on the agent:
    <prefix>SLACK_BOT_TOKEN   — xoxb-... bot token
    <prefix>SLACK_APP_TOKEN   — xapp-... app-level token (Socket Mode)
    <prefix>SLACK_CHANNEL_ID  — (optional) restrict to one channel

Install: slack-bolt[async]>=1.18.0

Streaming reliability features mirror the Telegram adapter:
  - Abort fence (generation counter per user)
  - Streaming mode (partial/progress/block/off via AgentConfig.telegram_streaming_mode)
  - Timeout notification
  - Session recording
  - Retry loop with exponential backoff
"""

import asyncio
import datetime
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_UPDATE_INTERVAL = 2.0  # seconds between live chat_update calls (Slack Tier-3 limit: ~1/s)

# Per-user session tracking (keyed by Slack user_id string)
_user_sessions: dict[str, str] = {}
_user_session_dates: dict[str, str] = {}

# Abort fence: generation counter per user
_user_generations: dict[str, int] = {}

# Session recording: lightweight per-user exchange log
_user_last_exchange: dict[str, dict] = {}


def _get_or_create_session(user_id: str, session_manager: Any) -> str:
    today = datetime.date.today().isoformat()
    if user_id in _user_sessions and _user_session_dates.get(user_id) == today:
        return _user_sessions[user_id]
    try:
        session_id = session_manager.start() if session_manager else f"slack-{user_id}-{today}"
    except Exception:
        session_id = f"slack-{user_id}-{today}"
    _user_sessions[user_id] = session_id
    _user_session_dates[user_id] = today
    return session_id


async def start_slack(agent: Any, session_manager: Any, config: Any) -> None:
    """Start Slack Socket Mode listener. Runs until the asyncio Task is cancelled.

    Retries on network errors with exponential backoff (5s → 60s).
    """
    try:
        from slack_bolt.async_app import AsyncApp
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    except ImportError:
        raise ImportError(
            "slack: slack-bolt not installed — add slack-bolt[async]>=1.18.0 to requirements.txt"
        )

    bot_token = os.environ.get(config.slack_token_env, "")
    app_token = os.environ.get(config.slack_app_token_env, "")
    allowed_channel = os.environ.get(config.slack_channel_env, "")

    if not bot_token:
        raise ValueError(f"slack: {config.slack_token_env!r} not set")
    if not app_token:
        raise ValueError(f"slack: {config.slack_app_token_env!r} not set — required for Socket Mode")

    mode = getattr(config, "telegram_streaming_mode", "partial")
    retry_delay = 5
    attempt = 0

    while True:
        try:
            slack_app = AsyncApp(token=bot_token)

            @slack_app.event("message")
            async def handle_message(event, say, client) -> None:  # noqa: ANN001
                # Ignore bot messages, message_changed subtypes, etc.
                if event.get("subtype") or event.get("bot_id"):
                    return

                channel_id: str = event.get("channel", "")
                user_id: str = event.get("user", "")
                text: str = (event.get("text") or "").strip()

                if not text:
                    return
                if allowed_channel and channel_id != allowed_channel:
                    return

                session_id = _get_or_create_session(user_id, session_manager)

                my_gen = _user_generations.get(user_id, 0) + 1
                _user_generations[user_id] = my_gen

                resp = await say("⠋ _thinking…_")
                placeholder_ts: str | None = resp.get("ts")
                accumulated = ""
                last_edit = time.monotonic()

                async def _update(content: str) -> None:
                    nonlocal last_edit
                    if not placeholder_ts:
                        return
                    try:
                        await client.chat_update(
                            channel=channel_id,
                            ts=placeholder_ts,
                            text=(content[:3000] or "⠋ _thinking…_"),
                        )
                        last_edit = time.monotonic()
                    except Exception as exc:
                        logger.warning("slack: chat_update failed — %s", exc)

                try:
                    async for chunk in agent.stream(text, session_id=session_id):
                        if _user_generations.get(user_id) != my_gen:
                            logger.info("slack[%s]: stream aborted (generation superseded)", user_id)
                            break
                        accumulated += chunk
                        if mode == "partial" and time.monotonic() - last_edit >= _UPDATE_INTERVAL:
                            await _update(accumulated + " ▌")

                    await _update(accumulated or "(no response)")
                    _user_last_exchange[user_id] = {
                        "session_id": session_id,
                        "ts": datetime.datetime.now().isoformat(),
                        "msg_len": len(text),
                        "resp_len": len(accumulated),
                        "delivered": True,
                    }

                except TimeoutError:
                    logger.error("slack[%s]: stream timed out (gen %d)", user_id, my_gen)
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
                    logger.error("slack: stream error for %s — %s", user_id, exc, exc_info=True)
                    partial = (accumulated[:2800] + "\n\n⚠️ _(stream interrupted)_") if accumulated else "Sorry, something went wrong."
                    await _update(partial)
                    _user_last_exchange[user_id] = {
                        "session_id": session_id,
                        "ts": datetime.datetime.now().isoformat(),
                        "delivered": False,
                    }

            handler = AsyncSocketModeHandler(slack_app, app_token)
            logger.info(
                "slack: starting Socket Mode for %s (channel=%s)",
                config.name, allowed_channel or "all",
            )
            await handler.start_async()
            break  # clean exit — reset backoff

        except asyncio.CancelledError:
            logger.info("slack: Socket Mode stopped for %s", config.name)
            raise
        except Exception as exc:
            attempt += 1
            logger.warning(
                "slack: connection error (attempt %d) — %s; retrying in %ds",
                attempt, exc, retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

    logger.info("slack: adapter stopped for %s", config.name)
