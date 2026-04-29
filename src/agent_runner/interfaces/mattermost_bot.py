"""Mattermost channel adapter — WebSocket + REST API.

Requires the following env vars on the agent:
    <prefix>MATTERMOST_URL        — https://mattermost.example.com
    <prefix>MATTERMOST_TOKEN      — personal access token or bot token
    <prefix>MATTERMOST_CHANNEL_ID — (optional) restrict to one channel ID

Install: mattermostdriver>=7.3.0

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
from urllib.parse import urlparse
from typing import Any

logger = logging.getLogger(__name__)

_UPDATE_INTERVAL = 2.0  # seconds between live post patches

# Per-user session tracking (keyed by Mattermost user_id string)
_user_sessions: dict[str, str] = {}
_user_session_dates: dict[str, str] = {}

# Abort fence: generation counter per user
_user_generations: dict[str, int] = {}

# Session recording
_user_last_exchange: dict[str, dict] = {}


def _get_or_create_session(user_id: str, session_manager: Any) -> str:
    today = datetime.date.today().isoformat()
    if user_id in _user_sessions and _user_session_dates.get(user_id) == today:
        return _user_sessions[user_id]
    try:
        session_id = session_manager.start() if session_manager else f"mm-{user_id}-{today}"
    except Exception:
        session_id = f"mm-{user_id}-{today}"
    _user_sessions[user_id] = session_id
    _user_session_dates[user_id] = today
    return session_id


async def start_mattermost(agent: Any, session_manager: Any, config: Any) -> None:
    """Start Mattermost WebSocket listener. Runs until the asyncio Task is cancelled.

    Retries on connection errors with exponential backoff (5s → 60s).
    """
    try:
        from mattermostdriver import AsyncDriver
    except ImportError:
        raise ImportError(
            "mattermost: mattermostdriver not installed — add mattermostdriver>=7.3.0 to requirements.txt"
        )

    url_str = os.environ.get(config.mattermost_url_env, "")
    token = os.environ.get(config.mattermost_token_env, "")
    allowed_channel = os.environ.get(config.mattermost_channel_env, "")

    if not url_str:
        raise ValueError(f"mattermost: {config.mattermost_url_env!r} not set")
    if not token:
        raise ValueError(f"mattermost: {config.mattermost_token_env!r} not set")

    parsed = urlparse(url_str)
    hostname = parsed.hostname or url_str
    port = parsed.port or (443 if (parsed.scheme or "https") == "https" else 80)
    scheme = parsed.scheme or "https"

    mode = getattr(config, "telegram_streaming_mode", "partial")
    retry_delay = 5
    attempt = 0

    while True:
        driver: Any | None = None
        try:
            driver = AsyncDriver({
                "url": hostname,
                "token": token,
                "port": port,
                "scheme": scheme,
                "verify": True,
            })

            await driver.login()
            me = await driver.users.get_user("me")
            my_user_id: str = me["id"]
            logger.info(
                "mattermost: logged in as %s for %s (channel=%s)",
                me.get("username", my_user_id), config.name, allowed_channel or "all",
            )

            async def handle_event(raw: Any) -> None:
                """Process inbound WebSocket events from Mattermost."""
                try:
                    event = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    return

                if event.get("event") != "posted":
                    return

                data = event.get("data", {})
                post_raw = data.get("post")
                if not post_raw:
                    return

                try:
                    post = json.loads(post_raw) if isinstance(post_raw, str) else post_raw
                except Exception:
                    return

                sender_id: str = post.get("user_id", "")
                if sender_id == my_user_id:
                    return  # ignore own messages

                channel_id: str = post.get("channel_id", "")
                if allowed_channel and channel_id != allowed_channel:
                    return

                text = (post.get("message") or "").strip()
                if not text:
                    return

                # Dispatch to a task to avoid blocking the WebSocket reader
                asyncio.create_task(
                    _process(driver, agent, session_manager, config, mode,
                              sender_id, channel_id, text)
                )

            logger.info("mattermost: starting WebSocket for %s", config.name)
            await driver.init_websocket(handle_event)
            break  # clean exit — reset backoff

        except asyncio.CancelledError:
            logger.info("mattermost: WebSocket stopped for %s", config.name)
            if driver:
                try:
                    await driver.logout()
                except Exception:
                    pass
            raise
        except Exception as exc:
            attempt += 1
            logger.warning(
                "mattermost: connection error (attempt %d) — %s; retrying in %ds",
                attempt, exc, retry_delay,
            )
            if driver:
                try:
                    await driver.logout()
                except Exception:
                    pass
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

    logger.info("mattermost: adapter stopped for %s", config.name)


async def _process(
    driver: Any,
    agent: Any,
    session_manager: Any,
    config: Any,
    mode: str,
    sender_id: str,
    channel_id: str,
    text: str,
) -> None:
    """Stream a user message through the agent and update the placeholder post."""
    session_id = _get_or_create_session(sender_id, session_manager)

    my_gen = _user_generations.get(sender_id, 0) + 1
    _user_generations[sender_id] = my_gen

    try:
        placeholder_post = await driver.posts.create_post({
            "channel_id": channel_id,
            "message": "⠋ _thinking…_",
        })
        placeholder_id: str = placeholder_post["id"]
    except Exception as exc:
        logger.error("mattermost: could not create placeholder post — %s", exc)
        return

    accumulated = ""
    last_edit = time.monotonic()

    async def _update(content: str) -> None:
        nonlocal last_edit
        try:
            await driver.posts.patch_post(placeholder_id, options={
                "message": (content[:16000] or "⠋ _thinking…_"),
            })
            last_edit = time.monotonic()
        except Exception as exc:
            logger.warning("mattermost: patch_post failed — %s", exc)

    try:
        async for chunk in agent.stream(text, session_id=session_id):
            if _user_generations.get(sender_id) != my_gen:
                logger.info("mattermost[%s]: stream aborted (generation superseded)", sender_id)
                break
            accumulated += chunk
            if mode == "partial" and time.monotonic() - last_edit >= _UPDATE_INTERVAL:
                await _update(accumulated + " ▌")

        await _update(accumulated or "(no response)")
        _user_last_exchange[sender_id] = {
            "session_id": session_id,
            "ts": datetime.datetime.now().isoformat(),
            "msg_len": len(text),
            "resp_len": len(accumulated),
            "delivered": True,
        }

    except TimeoutError:
        logger.error("mattermost[%s]: stream timed out (gen %d)", sender_id, my_gen)
        await _update(
            "⏱ Response timed out — the agent is still processing. "
            "Check back shortly or retry your message."
        )
        _user_last_exchange[sender_id] = {
            "session_id": session_id,
            "ts": datetime.datetime.now().isoformat(),
            "delivered": False,
        }

    except Exception as exc:
        logger.error("mattermost: stream error for %s — %s", sender_id, exc, exc_info=True)
        partial = (accumulated[:15000] + "\n\n⚠️ _(stream interrupted)_") if accumulated else "Sorry, something went wrong."
        await _update(partial)
        _user_last_exchange[sender_id] = {
            "session_id": session_id,
            "ts": datetime.datetime.now().isoformat(),
            "delivered": False,
        }
