"""Passive OAuth token expiry monitor for Claude SDK credentials.

Rewritten from active keepalive to passive monitor after root-cause analysis:
the previous implementation forced a `POST /chat "ping"` against a round-robin
agent port to trigger SDK refresh as a side-effect. That `ping` ran a full
agent turn and stole/deadlocked active streams (CoH/DON/CIO silent since
2026-04-23 17:28 UTC). The Claude CLI has no non-inference refresh path, so
we stop forcing refresh here entirely and let the next natural agent turn
refresh the token on its own.

Responsibilities now:
1. Read credentials.json every 5 minutes.
2. Log token state (healthy / expiring soon / expired).
3. If token has been expired for 3 consecutive checks, log an ERROR so the
   operator knows a manual `claude auth login` may be needed.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CREDS_PATH = Path("/root/.claude/.credentials.json")
_CHECK_INTERVAL = 300        # 5 minutes
_REFRESH_THRESHOLD = 600     # warn inside last 10 minutes
_EXPIRED_ALERT_AFTER = 3     # consecutive expired checks → operator alert


def _find_expires_at(obj: Any) -> int | None:
    """Recursively look up expiresAt / expires_at anywhere in the JSON tree."""
    if isinstance(obj, dict):
        for key in ("expiresAt", "expires_at"):
            if key in obj and isinstance(obj[key], (int, float)):
                return int(obj[key])
        for value in obj.values():
            found = _find_expires_at(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_expires_at(item)
            if found is not None:
                return found
    return None


def _remaining_seconds(expires_at: int) -> float:
    """Normalise expiresAt (seconds or milliseconds) and return remaining seconds."""
    epoch = expires_at / 1000 if expires_at > 1e12 else float(expires_at)
    return epoch - time.time()


class TokenKeepalive:
    """Passive monitor — no longer issues HTTP pings to agent ports.

    The `agent_ports` argument is kept for backward compatibility with
    `platform_api/app.py` but is ignored.
    """

    def __init__(self, agent_ports: list[int] | None = None):
        self._ports_unused = agent_ports or []
        self._consecutive_expired = 0

    async def start(self):
        logger.info(
            "token_keepalive: started in passive mode (checking every %ds, no forced refresh)",
            _CHECK_INTERVAL,
        )
        try:
            while True:
                await self._check()
                await asyncio.sleep(_CHECK_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _check(self):
        try:
            creds = json.loads(_CREDS_PATH.read_text())
        except FileNotFoundError:
            logger.warning("token_keepalive: credentials file missing at %s", _CREDS_PATH)
            return
        except Exception as exc:
            logger.warning(
                "token_keepalive: cannot parse credentials — %s: %s",
                type(exc).__name__,
                exc or "(no detail)",
            )
            return

        expires_at = _find_expires_at(creds)
        if expires_at is None:
            logger.warning("token_keepalive: no expiresAt key found in credentials.json")
            return

        remaining = _remaining_seconds(expires_at)

        if remaining > _REFRESH_THRESHOLD:
            # Healthy — reset counter silently.
            self._consecutive_expired = 0
            return

        if remaining > 0:
            self._consecutive_expired = 0
            logger.info(
                "token_keepalive: token expiring in %.0fs — next agent turn will refresh naturally",
                remaining,
            )
            return

        # Token already expired.
        self._consecutive_expired += 1
        logger.warning(
            "token_keepalive: token EXPIRED %.0fs ago (consecutive=%d)",
            -remaining,
            self._consecutive_expired,
        )
        if self._consecutive_expired >= _EXPIRED_ALERT_AFTER:
            logger.error(
                "token_keepalive: token expired for %d consecutive checks (~%dm) — "
                "operator action may be needed (`claude auth login`). Telegram alert TODO.",
                self._consecutive_expired,
                self._consecutive_expired * _CHECK_INTERVAL // 60,
            )
