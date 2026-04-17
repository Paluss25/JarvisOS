"""Generic FastAPI app factory — creates a fully configured agent API."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_runner.config import AgentConfig
from agent_runner.client import create_agent_client, BaseAgentClient
from agent_runner.memory.daily_logger import DailyLogger
from agent_runner.memory.session_manager import SessionManager
from agent_runner.memory.pipeline import run_pipeline
from agent_runner.memory.pipeline.queue import PipelineItem, PipelineQueue

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


class A2ARequest(BaseModel):
    from_agent: str
    message: str
    session_id: str | None = None


def create_app(config: AgentConfig) -> FastAPI:
    """Build a fully configured FastAPI app for this agent."""

    state: dict = {
        "agent": None,
        "session_manager": None,
        "telegram_task": None,
        "scheduler_task": None,
        "pipeline_task": None,
        "start_time": time.time(),
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        logger.info("%s: starting up…", config.name)

        try:
            agent = create_agent_client(config)
            await agent.connect()
            pipeline_queue = PipelineQueue()
            agent.set_pipeline_queue(pipeline_queue)
            state["agent"] = agent
            state["session_manager"] = SessionManager(workspace_path=config.workspace_path)
            state["pipeline_task"] = asyncio.create_task(run_pipeline(pipeline_queue, config))
            logger.info("%s: agent + pipeline ready", config.name)
        except Exception as exc:
            logger.error("%s: agent init failed — %s", config.name, exc, exc_info=True)

        # Telegram polling
        import os
        if os.environ.get(config.telegram_token_env):
            try:
                from agent_runner.interfaces.telegram_bot import start_polling
                state["telegram_task"] = asyncio.create_task(
                    start_polling(state["agent"], state["session_manager"], config)
                )
                logger.info("%s: Telegram polling started", config.name)
            except Exception as exc:
                logger.warning("%s: Telegram polling failed — %s", config.name, exc)

        # Heartbeat scheduler
        if state["agent"]:
            try:
                from agent_runner.scheduler.heartbeat import HeartbeatScheduler
                scheduler = HeartbeatScheduler(agent=state["agent"], config=config)
                state["scheduler_task"] = asyncio.create_task(scheduler.start())
                logger.info("%s: heartbeat scheduler started", config.name)
            except Exception as exc:
                logger.warning("%s: heartbeat scheduler failed — %s", config.name, exc)

        yield

        # Shutdown
        logger.info("%s: shutting down…", config.name)
        for key in ("telegram_task", "scheduler_task", "pipeline_task"):
            task = state.get(key)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if state["session_manager"]:
            try:
                await state["session_manager"].end(f"{config.name} graceful shutdown")
            except Exception as exc:
                logger.warning("%s: session end failed — %s", config.name, exc)

        if state["agent"]:
            try:
                await state["agent"].disconnect()
            except Exception as exc:
                logger.warning("%s: agent disconnect failed — %s", config.name, exc)

        logger.info("%s: shutdown complete", config.name)

    app = FastAPI(
        title=f"{config.name}OS",
        description=f"{config.name} agent — control plane",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Endpoints ---------------------------------------------------------

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "agent": config.id,
            "model_chain": "claude (sdk)",
            "uptime_seconds": int(time.time() - state["start_time"]),
        }

    @app.get("/status")
    async def status():
        agent = state["agent"]
        if not agent:
            return {"status": "degraded", "reason": "agent not initialized"}
        sm = state["session_manager"]
        return {
            "status": "ok",
            "agent": agent.name,
            "model_chain": "claude (sdk)",
            "uptime_seconds": int(time.time() - state["start_time"]),
            "session_id": sm.session_id if sm else None,
            "telegram": "running" if (state["telegram_task"] and not state["telegram_task"].done()) else "stopped",
            "scheduler": "running" if (state["scheduler_task"] and not state["scheduler_task"].done()) else "stopped",
        }

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        agent = state["agent"]
        if not agent:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        sm = state["session_manager"]
        session_id = req.session_id or (sm.start() if sm else None)
        try:
            content = await agent.query(req.message, session_id=session_id)
            return ChatResponse(response=content, session_id=session_id or "")
        except Exception as exc:
            logger.error("chat: error — %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Internal agent error")

    @app.post("/chat/stream")
    async def chat_stream(req: ChatRequest):
        agent = state["agent"]
        if not agent:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        sm = state["session_manager"]
        session_id = req.session_id or (sm.start() if sm else None)

        async def _gen():
            try:
                async for chunk in agent.stream(req.message, session_id=session_id):
                    if chunk:
                        yield f"data: {chunk}\n\n"
            except Exception as exc:
                logger.error("chat/stream: error — %s", exc)
                yield "data: [ERROR] Internal stream error\n\n"

        return StreamingResponse(_gen(), media_type="text/event-stream")

    @app.post("/a2a", response_model=ChatResponse)
    async def agent_to_agent(req: A2ARequest):
        agent = state["agent"]
        if not agent:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        session_id = req.session_id or f"a2a-{req.from_agent}"
        prefixed = f"[Message from {req.from_agent}]\n\n{req.message}"
        try:
            DailyLogger(config.workspace_path).log(
                f"[A2A] Received from {req.from_agent}: {req.message[:100]}"
            )
        except Exception:
            pass
        try:
            content = await agent.query(prefixed, session_id=session_id, source="a2a")
            return ChatResponse(response=content, session_id=session_id)
        except Exception as exc:
            logger.error("a2a: error — %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Internal agent error")

    @app.get("/sessions")
    async def sessions():
        try:
            from claude_agent_sdk import list_sessions
            raw = list_sessions() or []
            result = []
            for s in raw:
                entry = {}
                for attr in ("session_id", "first_prompt", "last_modified", "git_branch", "cwd"):
                    val = getattr(s, attr, None)
                    if val is not None:
                        entry[attr] = str(val)
                result.append(entry)
            return {"sessions": result}
        except Exception as exc:
            logger.warning("sessions: could not list — %s", exc)
            return {"sessions": [], "error": str(exc)}

    @app.get("/memory/daily")
    async def memory_daily():
        dl = DailyLogger(config.workspace_path)
        content = dl.read_today()
        return {"date": __import__("datetime").date.today().isoformat(), "content": content}

    return app
