"""Generic FastAPI app factory — creates a fully configured agent API."""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_runner.comms.message import A2AMessage
from agent_runner.comms.redis_pubsub import RedisA2A
from agent_runner.comms.inbox import InboxQueue
from agent_runner.config import AgentConfig
from agent_runner.client import create_agent_client, BaseAgentClient
from agent_runner.memory.daily_logger import DailyLogger
from agent_runner.memory.session_manager import SessionManager
from agent_runner.memory.pipeline import run_pipeline
from agent_runner.memory.pipeline.queue import PipelineItem, PipelineQueue
from agent_runner.telemetry import configure_logging, setup_telemetry

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
    setup_telemetry(f"jarvios-{config.id}")

    state: dict = {
        "agent": None,
        "session_manager": None,
        "telegram_task": None,
        "scheduler_task": None,
        "pipeline_task": None,
        "redis_a2a_task": None,
        "redis_a2a": None,
        "inbox": None,
        "inbox_drain_task": None,
        "slack_task": None,
        "discord_task": None,
        "mattermost_task": None,
        "start_time": time.time(),
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        configure_logging(config.log_level)
        logger.info("%s: starting up…", config.name)

        import os

        # Redis A2A — create first so it can be passed to the MCP factory
        redis_a2a: RedisA2A | None = None
        if os.environ.get("REDIS_URL"):
            try:
                redis_a2a = RedisA2A(config.id)
                await redis_a2a.connect()
                logger.info("%s: Redis A2A connected", config.name)
            except Exception as exc:
                logger.warning("%s: Redis A2A init failed — %s", config.name, exc)
                redis_a2a = None

        try:
            agent = create_agent_client(config, redis_a2a=redis_a2a)
            await agent.connect()
            pipeline_queue = PipelineQueue()
            agent.set_pipeline_queue(pipeline_queue)
            state["agent"] = agent
            state["session_manager"] = SessionManager(workspace_path=config.workspace_path)
            state["pipeline_task"] = asyncio.create_task(run_pipeline(pipeline_queue, config))
            logger.info("%s: agent + pipeline ready", config.name)
        except Exception as exc:
            logger.error("%s: agent init failed — %s", config.name, exc, exc_info=True)

        # Wire up inbound A2A handler and start the listen loop
        if redis_a2a is not None:
            try:
                # Inbox queue for batched notification consumption.
                # Notifications are stored here and drained periodically by
                # ``_inbox_drain_loop`` so multiple concurrent senders fold
                # into a single agent turn instead of N parallel turns.
                inbox = InboxQueue(config.id, redis_a2a.client)
                state["inbox"] = inbox

                async def _handle_a2a(msg: A2AMessage) -> None:
                    """Callback: process inbound A2A messages.

                    - ``request``      → run a turn, publish correlated ``response``.
                    - ``notification`` → enqueue into the agent's Redis inbox.
                      The drain consumer reads the backlog atomically and
                      processes it in a single batched turn (ack-then-batch).
                    Other types are ignored.
                    """
                    agent = state["agent"]
                    if not agent or msg.type not in ("request", "notification"):
                        return
                    is_request = msg.type == "request"
                    try:
                        prefix = "[A2A]" if is_request else "[A2A-notif]"
                        DailyLogger(config.workspace_path).log(
                            f"{prefix} From {msg.from_agent}: {msg.payload[:100]}"
                        )
                    except Exception:
                        pass

                    # Notifications: enqueue and return. The drain loop owns the
                    # LLM call. Crash-safe (Redis persists) and busy-safe (no drop).
                    if not is_request:
                        try:
                            qlen = await inbox.push(msg)
                            logger.info(
                                "%s: notification from %s queued (inbox depth=%d)",
                                config.name, msg.from_agent, qlen,
                            )
                        except Exception as exc:
                            logger.warning(
                                "%s: failed to enqueue notification from %s — %s",
                                config.name, msg.from_agent, exc,
                            )
                        return

                    # Fast path: structured JSON actions bypass the LLM entirely
                    if config.a2a_fast_path is not None:
                        try:
                            action_payload = json.loads(msg.payload)
                            result = await config.a2a_fast_path(action_payload)
                            if result is not None:
                                response = A2AMessage(
                                    from_agent=config.id,
                                    to_agent=msg.from_agent,
                                    type="response",
                                    payload=json.dumps(result),
                                    correlation_id=msg.correlation_id,
                                )
                                await redis_a2a.publish(response)
                                return
                        except json.JSONDecodeError:
                            pass  # Not JSON — fall through to LLM
                        except Exception as exc:
                            logger.warning("%s: a2a fast path error — %s", config.name, exc)
                    # Fail fast if the agent is mid-turn — prevents the sender from
                    # burning their full 120s send_message timeout waiting for a lock
                    # that won't be released until the current turn completes.
                    if agent.is_busy:
                        logger.info(
                            "%s: busy — sending immediate busy signal to %s (cid=%.8s)",
                            config.name, msg.from_agent, msg.correlation_id,
                        )
                        busy_resp = A2AMessage(
                            from_agent=config.id,
                            to_agent=msg.from_agent,
                            type="response",
                            payload=(
                                f"[{config.name} is currently processing another request. "
                                "Proceed without this data or retry in a moment.]"
                            ),
                            correlation_id=msg.correlation_id,
                        )
                        await redis_a2a.publish(busy_resp)
                        return
                    try:
                        response_text = await agent.query(
                            f"[Message from {msg.from_agent}]\n\n{msg.payload}",
                            session_id=f"a2a-{msg.from_agent}",
                            source="a2a",
                        )
                        response = A2AMessage(
                            from_agent=config.id,
                            to_agent=msg.from_agent,
                            type="response",
                            payload=response_text,
                            correlation_id=msg.correlation_id,
                        )
                        await redis_a2a.publish(response)
                    except Exception as exc:
                        logger.warning("%s: a2a handler error — %s", config.name, exc)

                async def _inbox_drain_loop() -> None:
                    """Periodic consumer: drains the notification inbox into a
                    single batched ``agent.query()`` turn.

                    - Skips the tick if the agent is busy (notifications stay
                      queued for the next drain — no loss).
                    - Skips the tick if the inbox is empty.
                    - When draining, builds a single prompt that lists every
                      pending notification with sender + timestamp so the agent
                      can see the full batch at once and respond holistically.
                    """
                    interval = float(getattr(config, "inbox_drain_interval_s", 60))
                    while True:
                        try:
                            await asyncio.sleep(interval)
                            agent = state["agent"]
                            if not agent or agent.is_busy:
                                continue
                            messages = await inbox.drain()
                            if not messages:
                                continue
                            parts = [
                                f"[Inbox batch — {len(messages)} pending "
                                f"notification(s) since last drain]"
                            ]
                            for i, m in enumerate(messages, 1):
                                parts.append(
                                    f"\n--- {i}. From {m.from_agent} "
                                    f"({m.timestamp}) ---\n{m.payload}"
                                )
                            prompt = "\n".join(parts)
                            try:
                                await agent.query(
                                    prompt,
                                    session_id="a2a-inbox",
                                    source="a2a",
                                )
                            except Exception as exc:
                                logger.warning(
                                    "%s: inbox batch turn failed — %s",
                                    config.name, exc,
                                )
                        except asyncio.CancelledError:
                            break
                        except Exception as exc:
                            logger.warning(
                                "%s: inbox drain loop error — %s",
                                config.name, exc,
                            )

                redis_a2a.on_message(_handle_a2a)
                state["redis_a2a"] = redis_a2a
                state["redis_a2a_task"] = asyncio.create_task(redis_a2a.listen())
                state["inbox_drain_task"] = asyncio.create_task(_inbox_drain_loop())
                drain_interval = float(getattr(config, "inbox_drain_interval_s", 60))
                logger.info(
                    "%s: Redis A2A subscriber + inbox drain (every %.0fs) started",
                    config.name, drain_interval,
                )
            except Exception as exc:
                logger.warning("%s: Redis A2A subscriber failed — %s", config.name, exc)

        # Telegram polling
        if getattr(config, "telegram_polling_enabled", True) and os.environ.get(config.telegram_token_env):
            try:
                from agent_runner.interfaces.telegram_bot import start_polling
                state["telegram_task"] = asyncio.create_task(
                    start_polling(state["agent"], state["session_manager"], config, redis_a2a=redis_a2a)
                )
                logger.info("%s: Telegram polling started", config.name)
            except Exception as exc:
                logger.warning("%s: Telegram polling failed — %s", config.name, exc)

        # Slack (only if slack_token_env is set and the env var has a value)
        if (state["agent"]
                and getattr(config, "slack_token_env", "")
                and os.environ.get(config.slack_token_env, "")):
            try:
                from agent_runner.interfaces.slack_bot import start_slack
                state["slack_task"] = asyncio.create_task(
                    start_slack(state["agent"], state["session_manager"], config)
                )
                logger.info("%s: Slack Socket Mode started", config.name)
            except Exception as exc:
                logger.warning("%s: Slack start failed — %s", config.name, exc)

        # Discord (only if discord_token_env is set and the env var has a value)
        if (state["agent"]
                and getattr(config, "discord_token_env", "")
                and os.environ.get(config.discord_token_env, "")):
            try:
                from agent_runner.interfaces.discord_bot import start_discord
                state["discord_task"] = asyncio.create_task(
                    start_discord(state["agent"], state["session_manager"], config)
                )
                logger.info("%s: Discord bot started", config.name)
            except Exception as exc:
                logger.warning("%s: Discord start failed — %s", config.name, exc)

        # Mattermost (only if mattermost_token_env is set and the env var has a value)
        if (state["agent"]
                and getattr(config, "mattermost_token_env", "")
                and os.environ.get(config.mattermost_token_env, "")):
            try:
                from agent_runner.interfaces.mattermost_bot import start_mattermost
                state["mattermost_task"] = asyncio.create_task(
                    start_mattermost(state["agent"], state["session_manager"], config)
                )
                logger.info("%s: Mattermost WebSocket started", config.name)
            except Exception as exc:
                logger.warning("%s: Mattermost start failed — %s", config.name, exc)

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
        for key in ("telegram_task", "scheduler_task", "pipeline_task", "redis_a2a_task",
                    "inbox_drain_task", "slack_task", "discord_task", "mattermost_task"):
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

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        pass

    try:
        from prometheus_client import make_asgi_app
        app.mount("/metrics", make_asgi_app())
    except Exception:
        pass

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,   # credentials=True + origins=* is invalid per CORS spec
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
            "slack": "running" if (state.get("slack_task") and not state["slack_task"].done()) else "stopped",
            "discord": "running" if (state.get("discord_task") and not state["discord_task"].done()) else "stopped",
            "mattermost": "running" if (state.get("mattermost_task") and not state["mattermost_task"].done()) else "stopped",
        }

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        agent = state["agent"]
        if not agent:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        if agent.is_busy:
            raise HTTPException(status_code=503, detail="Agent busy — retry shortly")
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
        if agent.is_busy:
            raise HTTPException(status_code=503, detail="Agent busy — retry shortly")
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
        if agent.is_busy:
            # Mirror the Redis A2A busy fast-path so HTTP fallback callers get
            # an immediate signal instead of stalling on a wedged stream.
            return ChatResponse(
                response=(
                    f"[{config.name} is currently processing another request. "
                    "Proceed without this data or retry in a moment.]"
                ),
                session_id=req.session_id or f"a2a-{req.from_agent}",
            )
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
