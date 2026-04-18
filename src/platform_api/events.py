"""SSE event stream — relay Redis pub/sub to dashboard clients.

SSE ticket flow (avoids long-lived JWT in query string / access logs):
  1. Client calls POST /api/events/ticket (Bearer auth) → gets a 60-second ticket
  2. Client opens GET /api/events?ticket=<ticket>
"""

import asyncio
import logging
import os
import secrets
import time
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from platform_api.auth import decode_access_token, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])

# In-memory ticket store: ticket → (user_payload, expires_at)
_SSE_TICKETS: dict[str, tuple[dict, float]] = {}
_TICKET_TTL = 60  # seconds


def _issue_ticket(user: dict) -> str:
    """Create a short-lived SSE ticket."""
    ticket = secrets.token_urlsafe(32)
    _SSE_TICKETS[ticket] = (user, time.monotonic() + _TICKET_TTL)
    return ticket


def _consume_ticket(ticket: str) -> dict:
    """Validate and consume a ticket. Raises HTTPException on failure."""
    entry = _SSE_TICKETS.pop(ticket, None)
    if entry is None:
        raise HTTPException(status_code=401, detail="Invalid or expired SSE ticket")
    _, expires_at = entry
    user, _ = entry
    if time.monotonic() > expires_at:
        raise HTTPException(status_code=401, detail="SSE ticket expired")
    return user


@router.post("/api/events/ticket", status_code=201)
async def issue_sse_ticket(user: dict = Depends(get_current_user)):
    """Issue a short-lived (60 s) ticket for the SSE endpoint.

    Call this first with a Bearer token, then open the SSE stream with the
    returned ticket. Keeps the JWT out of access logs.
    """
    ticket = _issue_ticket(user)
    return {"ticket": ticket, "ttl_seconds": _TICKET_TTL}


@router.get("/api/events")
async def events(ticket: str = Query(...)):
    """Stream Redis pub/sub messages to client as Server-Sent Events.

    Pass the short-lived ticket from POST /api/events/ticket.
    Subscribes to: platform:events, tasks:*, a2a:*
    """
    try:
        _consume_ticket(ticket)
    except HTTPException:
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
