"""Proactive OAuth token refresh for Claude SDK credentials."""

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_CREDS_PATH = Path("/root/.claude/.credentials.json")
_CHECK_INTERVAL = 300   # 5 minutes
_REFRESH_THRESHOLD = 600  # 10 minutes before expiry


class TokenKeepalive:
    """Check credentials.json every 5 minutes; trigger refresh if near expiry."""

    def __init__(self, agent_ports: list[int]):
        self._ports = agent_ports
        self._port_idx = 0
        self._consecutive_failures = 0

    async def start(self):
        logger.info("token_keepalive: started (checking every %ds)", _CHECK_INTERVAL)
        try:
            while True:
                await self._check()
                await asyncio.sleep(_CHECK_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _check(self):
        try:
            creds = json.loads(_CREDS_PATH.read_text())
            expires_at = creds.get("expiresAt", 0)
        except Exception:
            return

        remaining = expires_at - time.time()
        if remaining > _REFRESH_THRESHOLD:
            self._consecutive_failures = 0
            return

        # Token near expiry — send minimal query to trigger SDK refresh
        port = self._ports[self._port_idx % len(self._ports)]
        self._port_idx += 1
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"http://localhost:{port}/chat",
                    json={"message": "ping", "session_id": "keepalive"},
                )
                resp.raise_for_status()
            self._consecutive_failures = 0
            logger.info("token_keepalive: refresh triggered via port %d", port)
        except Exception as exc:
            self._consecutive_failures += 1
            logger.warning(
                "token_keepalive: refresh failed (%d) — %s",
                self._consecutive_failures,
                exc,
            )
            if self._consecutive_failures >= 3:
                logger.error("token_keepalive: 3 consecutive failures — Telegram alert TODO")
