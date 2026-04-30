"""Telegram webhook proxy — platform_api receives Telegram updates and
forwards them to the correct agent's FastAPI app at localhost:{port}."""

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

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"http://localhost:{port}/telegram/webhook",
            content=body,
            headers=headers,
        )

    return Response(status_code=resp.status_code)
