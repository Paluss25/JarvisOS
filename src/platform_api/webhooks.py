"""Telegram webhook proxy — platform_api receives Telegram updates and
forwards them to the correct agent's FastAPI app at localhost:{port}.

The forward is fire-and-forget: we ack Telegram with 200 OK as soon as the
inner POST returns OR after a short bounded wait, so a slow agent.query()
inside python-telegram-bot does NOT cause Telegram to retry (which produces
the user-visible "(no response)" + duplicate dispatch pattern).
"""

import asyncio
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

AGENT_PORTS: dict[str, int] = {
    "ceo": 8000,
    "dos": 8001,
    "cio": 8002,
    "cfo": 8003,
    "chro": 8004,
    "email": 8005,
    "coh": 8006,
    "don": 8007,
    "cos": 8008,
    "mt": 8009,
}

# Bounded wait for the inner agent endpoint. python-telegram-bot in webhook
# mode normally returns within ~50ms (it queues the update for the dispatcher
# task and acks immediately). If the inner endpoint takes longer than this
# cap, we ack Telegram anyway and the inner POST keeps running in the
# background — Telegram's own webhook timeout is 60s, our retry-storm
# protection sits well below that.
_INNER_FORWARD_TIMEOUT_S = 30.0


async def _fire_and_forget_forward(url: str, body: bytes, headers: dict) -> None:
    """Background-task fallback: completes the forward even after we acked
    Telegram, so the agent still receives every update."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await client.post(url, content=body, headers=headers)
    except Exception as exc:
        logger.warning("webhooks: background forward to %s failed — %s", url, exc)


@router.post("/webhooks/{agent_id}")
async def telegram_webhook(agent_id: str, request: Request) -> Response:
    """Proxy a Telegram webhook update to the target agent's FastAPI app."""
    port = AGENT_PORTS.get(agent_id)
    if port is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id!r}")

    body = await request.body()
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    headers = {
        "Content-Type": "application/json",
        "X-Telegram-Bot-Api-Secret-Token": secret,
    }
    target = f"http://localhost:{port}/telegram/webhook"

    try:
        async with httpx.AsyncClient(timeout=_INNER_FORWARD_TIMEOUT_S) as client:
            resp = await client.post(target, content=body, headers=headers)
        return Response(status_code=resp.status_code)
    except (httpx.ReadTimeout, httpx.PoolTimeout):
        # The inner endpoint is taking too long — most likely the agent is
        # mid-turn. Telegram has already delivered to us; we MUST ack with
        # 200 to prevent retry storms ("(no response)" from the user side).
        # Re-issue the forward as a background task so the update is not lost.
        logger.warning(
            "webhooks: inner forward to %s exceeded %.0fs — acking 200 and "
            "completing in background",
            target, _INNER_FORWARD_TIMEOUT_S,
        )
        asyncio.create_task(_fire_and_forget_forward(target, body, headers))
        return Response(status_code=200)
    except httpx.HTTPError as exc:
        logger.warning("webhooks: forward to %s failed — %s", target, exc)
        return Response(status_code=502)
