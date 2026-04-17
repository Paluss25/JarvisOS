"""SSE event stream — relay Redis pub/sub to dashboard clients."""

import asyncio
import logging
import os
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from platform.auth import decode_access_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])


@router.get("/api/events")
async def events(token: str = Query(...)):
    """Stream Redis pub/sub messages to client as Server-Sent Events.

    JWT token is passed as query param (EventSource API doesn't support headers).
    Subscribes to: platform:events, tasks:*, a2a:*
    """
    # Validate JWT token from query param
    try:
        decode_access_token(token)
    except Exception:
        async def _unauthorized():
            yield "event: error\ndata: unauthorized\n\n"
        return StreamingResponse(_unauthorized(), media_type="text/event-stream")

    async def _event_stream() -> AsyncGenerator[str, None]:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        r = aioredis.from_url(redis_url)
        pubsub = r.pubsub()
        await pubsub.psubscribe("platform:events", "tasks:*", "a2a:*")
        try:
            # Keepalive comment every 25 s to prevent proxy timeouts
            last_keepalive = asyncio.get_event_loop().time()
            async for message in pubsub.listen():
                now = asyncio.get_event_loop().time()
                if now - last_keepalive > 25:
                    yield ": keepalive\n\n"
                    last_keepalive = now

                if message["type"] == "pmessage":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.punsubscribe()
            await r.aclose()

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
