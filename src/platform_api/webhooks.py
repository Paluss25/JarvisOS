"""Telegram webhook proxy — platform_api receives Telegram updates and
forwards them to the correct agent's FastAPI app at localhost:{port}.

Inner agent endpoints now enqueue the update onto PTB's ``update_queue`` and
return 200 within ~50ms (see ``agent_runner.interfaces.telegram_bot.
_make_webhook_handler``), so the proxy no longer needs the duplicate
background re-fire that previously caused ``_chat_generations`` races and
silent placeholder loss for slow LLM streams. A short read timeout is
sufficient — anything beyond it indicates the inner FastAPI is genuinely
unreachable, which we surface as 502 to the upstream.
"""

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

# The inner handler now enqueues + returns 200 immediately (~50ms typical).
# A short cap is intentional: anything slower means the inner FastAPI is
# unhealthy, not just busy with an LLM turn.
_INNER_FORWARD_TIMEOUT_S = 5.0


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
    except httpx.HTTPError as exc:
        logger.warning("webhooks: forward to %s failed — %s", target, exc)
        return Response(status_code=502)
