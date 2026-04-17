"""JarvisOS Platform API — FastAPI application factory."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from platform.db import get_pool, close_pool

logger = logging.getLogger(__name__)


def create_platform_app() -> FastAPI:
    from platform.agents import router as agents_router
    from platform.auth import router as auth_router
    from platform.domains import router as domains_router
    from platform.events import router as events_router
    from platform.tasks import router as tasks_router
    from platform.token_keepalive import TokenKeepalive

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator:
        # DB pool
        try:
            await get_pool()
        except Exception as exc:
            logger.warning("platform: DB pool unavailable — %s (continuing without DB)", exc)

        # Token keepalive
        from agent_runner.registry import list_agents
        try:
            agent_ports = [a["port"] for a in list_agents()]
        except Exception:
            agent_ports = [8000, 8001]

        keepalive = TokenKeepalive(agent_ports=agent_ports)
        keepalive_task = asyncio.create_task(keepalive.start())
        logger.info("platform: startup complete")

        yield

        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass
        await close_pool()
        logger.info("platform: shutdown complete")

    app = FastAPI(title="JarvisOS Platform API", version="1.0.0", lifespan=lifespan)

    # Routers
    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(tasks_router)
    app.include_router(domains_router)
    app.include_router(events_router)

    # Health endpoint (no auth required)
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "platform-api"}

    # Serve React dashboard from dashboard/dist/ if it exists
    dashboard_dist = Path("/app/dashboard/dist")
    if dashboard_dist.exists():
        app.mount("/", StaticFiles(directory=str(dashboard_dist), html=True), name="dashboard")
        logger.info("platform: serving dashboard from %s", dashboard_dist)

    return app
