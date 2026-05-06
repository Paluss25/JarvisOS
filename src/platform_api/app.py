"""JarvisOS Platform API — FastAPI application factory."""

import errno
import os
import asyncio
import logging
import stat
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import RedirectResponse
from starlette.datastructures import URL

from platform_api.db import get_pool, close_pool

logger = logging.getLogger(__name__)


class SPAStaticFiles(StaticFiles):
    """Serve React client routes through index.html while preserving API 404s."""

    async def get_response(self, path: str, scope):
        if scope["method"] not in ("GET", "HEAD"):
            raise StarletteHTTPException(status_code=405)

        try:
            full_path, stat_result = self.lookup_path(path)
        except PermissionError:
            raise StarletteHTTPException(status_code=401)
        except OSError as exc:
            if exc.errno == errno.ENAMETOOLONG:
                raise StarletteHTTPException(status_code=404)
            raise

        if stat_result and stat.S_ISREG(stat_result.st_mode):
            return self.file_response(full_path, stat_result, scope)

        if stat_result and stat.S_ISDIR(stat_result.st_mode) and self.html:
            index_path = os.path.join(path, "index.html")
            full_path, stat_result = self.lookup_path(index_path)
            if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
                if not scope["path"].endswith("/"):
                    url = URL(scope=scope)
                    return RedirectResponse(url=url.replace(path=url.path + "/"))
                return self.file_response(full_path, stat_result, scope)

        if self.html and self._should_fallback_to_index(path):
            full_path, stat_result = self.lookup_path("index.html")
            if stat_result and stat.S_ISREG(stat_result.st_mode):
                return self.file_response(full_path, stat_result, scope)

        raise StarletteHTTPException(status_code=404)

    @staticmethod
    def _should_fallback_to_index(path: str) -> bool:
        first_segment = path.split("/", 1)[0]
        if first_segment in {"api", "webhooks"}:
            return False
        return "." not in Path(path).name


def create_platform_app() -> FastAPI:
    from platform_api.a2a import router as a2a_router
    from platform_api.activity import router as activity_router
    from platform_api.agents import router as agents_router
    from platform_api.audit_endpoints import router as audit_router
    from platform_api.auth import router as auth_router
    from platform_api.chat import router as chat_router
    from platform_api.control_center import router as control_router
    from platform_api.cockpits import router as cockpits_router
    from platform_api.costs import router as costs_router
    from platform_api.decisions import router as decisions_router
    from platform_api.domains import router as domains_router
    from platform_api.events import router as events_router
    from platform_api.incidents import router as incidents_router
    from platform_api.logs import router as logs_router
    from platform_api.memory import router as memory_router
    from platform_api.plugins import router as plugins_router
    from platform_api.settings import router as settings_router
    from platform_api.tasks import router as tasks_router
    from platform_api.token_keepalive import TokenKeepalive
    from platform_api.traces import router as traces_router
    from platform_api.webhooks import router as webhooks_router

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
    app.include_router(control_router)
    app.include_router(activity_router)
    app.include_router(chat_router)
    app.include_router(a2a_router)
    app.include_router(decisions_router)
    app.include_router(cockpits_router)
    app.include_router(costs_router)
    app.include_router(agents_router)
    app.include_router(tasks_router)
    app.include_router(domains_router)
    app.include_router(events_router)
    app.include_router(traces_router)
    app.include_router(logs_router)
    app.include_router(incidents_router)
    app.include_router(memory_router)
    app.include_router(plugins_router)
    app.include_router(settings_router)
    app.include_router(audit_router)
    app.include_router(webhooks_router)

    # Health endpoint (no auth required)
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "platform-api"}

    # Serve React dashboard from dashboard/dist/ if it exists
    dashboard_dist = Path("/app/dashboard/dist")
    if dashboard_dist.exists():
        app.mount("/", SPAStaticFiles(directory=str(dashboard_dist), html=True), name="dashboard")
        logger.info("platform: serving dashboard from %s", dashboard_dist)

    return app
