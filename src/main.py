"""JarvisOS — Custom control plane for the Jarvis AI executive assistant.

Endpoints:
    GET  /health          — liveness probe
    GET  /status          — agent status (model chain, uptime, session info)
    POST /chat            — send a message, receive a full response
    POST /chat/stream     — send a message, receive an SSE stream
    GET  /sessions        — list active Agno sessions (last 10)
    GET  /memory/daily    — read today's memory log

Lifecycle (FastAPI lifespan):
    startup  — build agent, start Telegram polling (if token configured)
    shutdown — stop Telegram polling, close session
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.config import settings
from src.memory.daily_logger import DailyLogger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state — populated during lifespan startup
# ---------------------------------------------------------------------------
_agent = None
_session_manager = None
_telegram_task: asyncio.Task | None = None
_start_time: float = time.time()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    global _agent, _session_manager, _telegram_task

    # ---- Startup --------------------------------------------------------
    logger.info("JarvisOS: starting up…")

    try:
        from src.agent import create_jarvis_agent, create_session_manager
        _agent = create_jarvis_agent()
        _session_manager = create_session_manager()
        logger.info("JarvisOS: agent ready — model chain: %s", _model_chain_str(_agent))
    except Exception as exc:
        logger.error("JarvisOS: agent init failed — %s", exc, exc_info=True)
        # Continue startup so health endpoint still works; chat will 503

    # Start Telegram polling if token is configured
    if settings.TELEGRAM_JARVIS_TOKEN:
        try:
            from src.interfaces.telegram_bot import start_polling
            _telegram_task = asyncio.create_task(start_polling(_agent, _session_manager))
            logger.info("JarvisOS: Telegram polling started")
        except Exception as exc:
            logger.warning("JarvisOS: Telegram polling failed to start — %s", exc)
    else:
        logger.info("JarvisOS: TELEGRAM_JARVIS_TOKEN not set — skipping Telegram")

    yield  # ← application runs here

    # ---- Shutdown -------------------------------------------------------
    logger.info("JarvisOS: shutting down…")

    if _telegram_task and not _telegram_task.done():
        _telegram_task.cancel()
        try:
            await _telegram_task
        except asyncio.CancelledError:
            pass

    if _session_manager:
        try:
            await _session_manager.end("JarvisOS graceful shutdown")
        except Exception as exc:
            logger.warning("JarvisOS: session end failed — %s", exc)

    logger.info("JarvisOS: shutdown complete")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="JarvisOS",
    description="Jarvis AI Executive Assistant — control plane",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _model_chain_str(agent) -> str:
    """Return a short, safe model chain string (no API keys)."""
    if not agent:
        return "not initialized"
    primary = agent.model
    parts = [f"{getattr(primary, 'provider', '?')}/{getattr(primary, 'id', '?')}"]
    for fb in getattr(agent, "fallback_models", None) or []:
        parts.append(f"{getattr(fb, 'provider', '?')}/{getattr(fb, 'id', '?')}")
    return " → ".join(parts)


@app.get("/health")
async def health():
    """Liveness probe — always returns 200 if the process is alive."""
    return {
        "status": "ok",
        "agent": "jarvis",
        "model_chain": _model_chain_str(_agent),
        "uptime_seconds": int(time.time() - _start_time),
    }


@app.get("/status")
async def status():
    """Agent status — model chain, uptime, session info."""
    if not _agent:
        return {"status": "degraded", "reason": "agent not initialized"}

    return {
        "status": "ok",
        "agent": _agent.name,
        "model_chain": _model_chain_str(_agent),
        "uptime_seconds": int(time.time() - _start_time),
        "session_id": _session_manager.session_id if _session_manager else None,
        "telegram": "running" if (_telegram_task and not _telegram_task.done()) else "stopped",
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message and receive a full (non-streaming) response."""
    if not _agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    session_id = req.session_id or (
        _session_manager.start() if _session_manager else None
    )

    try:
        response = await asyncio.to_thread(
            _agent.run,
            req.message,
            session_id=session_id,
        )
        content = response.content if hasattr(response, "content") else str(response)
        return ChatResponse(response=content, session_id=session_id or "")
    except Exception as exc:
        logger.error("chat: error processing message — %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Send a message and receive an SSE-style streaming response."""
    if not _agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    session_id = req.session_id or (
        _session_manager.start() if _session_manager else None
    )

    async def _stream_generator():
        try:
            # Agno's run_stream is synchronous; run in thread pool
            stream = await asyncio.to_thread(
                _agent.run,
                req.message,
                session_id=session_id,
                stream=True,
            )
            for chunk in stream:
                text = chunk.content if hasattr(chunk, "content") else str(chunk)
                if text:
                    yield f"data: {text}\n\n"
        except Exception as exc:
            logger.error("chat/stream: error — %s", exc)
            yield f"data: [ERROR] {exc}\n\n"

    return StreamingResponse(_stream_generator(), media_type="text/event-stream")


@app.get("/sessions")
async def sessions():
    """List the last 10 Agno sessions from PostgreSQL."""
    if not _agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        all_sessions = _agent.storage.get_all_sessions() if _agent.storage else []
        recent = sorted(all_sessions, key=lambda s: getattr(s, "updated_at", 0), reverse=True)[:10]
        return {"sessions": [{"id": getattr(s, "session_id", str(s))} for s in recent]}
    except Exception as exc:
        logger.warning("sessions: could not fetch — %s", exc)
        return {"sessions": [], "error": str(exc)}


@app.get("/memory/daily")
async def memory_daily():
    """Return today's memory log content."""
    dl = DailyLogger(settings.workspace_path)
    content = dl.read_today()
    return {"date": __import__("datetime").date.today().isoformat(), "content": content}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_level=settings.LOG_LEVEL.lower(),
    )
