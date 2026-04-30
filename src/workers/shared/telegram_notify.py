"""Telegram notification helpers for strategy/finance workers.

Sends approval requests with inline keyboard directly via the Telegram Bot
HTTP API, without relying on the long-poll Application instance running in
the agent process. This keeps workers decoupled from the agent_runner
lifecycle while still surfacing actionable buttons to the operator.

Callback data convention: `cfo_approval:approve|deny:<id>` — handled by
agent_runner.interfaces.telegram_bot._handle_cfo_approval_callback.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_DEFAULT_TIMEOUT = 15.0


def _bot_token() -> str | None:
    return (
        os.environ.get("TELEGRAM_CFO_TOKEN")
        or os.environ.get("TELEGRAM_WARREN_TOKEN")
        or os.environ.get("TELEGRAM_JARVIS_TOKEN")
    )


def _chat_id() -> str | None:
    return os.environ.get("TELEGRAM_ALLOWED_CHAT_ID")


async def send_cfo_approval_request(
    approval_id: int,
    summary: str,
    *,
    request_type: str = "capital_move",
    extra_lines: list[str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Push an approval message with inline Approve/Deny buttons to the
    operator chat. Returns the Telegram API response or an error envelope.

    Best-effort — never raises. Callers should treat a falsy `ok` field as
    a soft failure (the approval is still persisted in the sidecar DB).
    """
    token = _bot_token()
    chat_id = _chat_id()
    if not token or not chat_id:
        logger.warning(
            "telegram_notify: missing TELEGRAM_*_TOKEN / TELEGRAM_ALLOWED_CHAT_ID — skipping push"
        )
        return {"ok": False, "error": "telegram_not_configured"}

    lines = [f"*CFO approval request* `#{approval_id}` — _{request_type}_", "", summary]
    if extra_lines:
        lines.extend(["", *extra_lines])
    text = "\n".join(lines)

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"cfo_approval:approve:{approval_id}"},
            {"text": "❌ Deny", "callback_data": f"cfo_approval:deny:{approval_id}"},
        ]]
    }
    body = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
    }
    url = f"{_API_BASE}/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=body)
        if response.status_code >= 400:
            logger.warning(
                "telegram_notify: sendMessage failed — status=%s body=%s",
                response.status_code,
                response.text[:200],
            )
            return {"ok": False, "error": f"http_{response.status_code}"}
        return response.json()
    except Exception as exc:
        logger.warning("telegram_notify: sendMessage error — %s", exc)
        return {"ok": False, "error": str(exc)}
