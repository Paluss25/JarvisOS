# agents/cio/remediation.py
"""RemediationEngine — maps HITL action strings to actual infrastructure calls.

Action string format (from IssueCollector._suggest_action):
  docker_action:restart:{container_name}   — POST /containers/{name}/restart via socket proxy
  supervisorctl:restart:{process}          — POST to container exec endpoint
  infra_verify:{url}                       — GET {url}, return status
  pg_check:{db_name}                       — asyncpg SELECT 1
  tcp_check:{host}:{port}                  — raw TCP connect
  manual:{description}                     — returns description (no execution)

All methods are async. They call the Docker socket proxy (DOCKER_PROXY_URL env) and
asyncpg directly — not through CIO's MCP tools (avoiding double permission-gate calls).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket

import httpx

logger = logging.getLogger(__name__)

_PROXY_URL = os.environ.get("DOCKER_PROXY_URL", "http://socket-proxy:2375")
_EXEC_TIMEOUT = 30.0
_HTTP_TIMEOUT = 15.0
_TCP_TIMEOUT = 5.0


class RemediationEngine:
    async def execute(self, action: str) -> str:
        """Dispatch an action string. Returns a human-readable result string.

        Raises RuntimeError if the action fails (caller logs + marks task failed).
        """
        parts = action.split(":", 2)
        action_type = parts[0]

        if action_type == "docker_action" and len(parts) == 3:
            _, sub_action, container = parts
            return await self._docker_action(sub_action, container)

        if action_type == "supervisorctl" and len(parts) == 3:
            _, sub_action, process = parts
            return await self._supervisorctl(sub_action, process)

        if action_type == "infra_verify" and len(parts) >= 2:
            url = ":".join(parts[1:])
            return await self._infra_verify(url)

        if action_type == "pg_check" and len(parts) >= 2:
            db_name = parts[1]
            return await self._pg_check(db_name)

        if action_type == "tcp_check" and len(parts) >= 3:
            host = parts[1]
            port_str = parts[2]
            return await self._tcp_check(host, int(port_str))

        if action_type == "manual":
            description = ":".join(parts[1:]) if len(parts) > 1 else "no description"
            return f"Intervento manuale richiesto: {description}"

        raise RuntimeError(f"Unknown action format: {action!r}")

    # ------------------------------------------------------------------
    # Docker container lifecycle
    # ------------------------------------------------------------------

    async def _docker_action(self, action: str, container: str) -> str:
        async with httpx.AsyncClient(timeout=_EXEC_TIMEOUT) as client:
            if action == "restart":
                resp = await client.post(f"{_PROXY_URL}/containers/{container}/restart")
            elif action == "start":
                resp = await client.post(f"{_PROXY_URL}/containers/{container}/start")
            elif action == "stop":
                resp = await client.post(f"{_PROXY_URL}/containers/{container}/stop")
            else:
                raise RuntimeError(f"Unknown docker action: {action!r}")

            if resp.status_code in (204, 200):
                return f"docker {action} {container} → OK (HTTP {resp.status_code})"
            if resp.status_code == 304:
                return f"docker {action} {container} → already in desired state"
            if resp.status_code == 404:
                raise RuntimeError(f"Container '{container}' not found")
            raise RuntimeError(f"docker {action} {container} → HTTP {resp.status_code}: {resp.text[:100]}")

    # ------------------------------------------------------------------
    # supervisord process management via container exec
    # ------------------------------------------------------------------

    async def _supervisorctl(self, sub_action: str, process: str) -> str:
        """Execute supervisorctl command in the jarvios-platform container."""
        # Create exec instance
        exec_create_url = f"{_PROXY_URL}/containers/jarvios-platform/exec"
        exec_body = {
            "AttachStdout": True,
            "AttachStderr": True,
            "Cmd": ["supervisorctl", sub_action, process],
        }
        async with httpx.AsyncClient(timeout=_EXEC_TIMEOUT) as client:
            r = await client.post(exec_create_url, json=exec_body)
            if r.status_code != 201:
                raise RuntimeError(f"exec create failed: HTTP {r.status_code}")
            exec_id = r.json().get("Id", "")

            # Start exec (detached — avoids multiplexed-stream binary output)
            r2 = await client.post(f"{_PROXY_URL}/exec/{exec_id}/start", json={"Detach": True})
            if r2.status_code not in (200, 204):
                raise RuntimeError(f"exec start failed: HTTP {r2.status_code}")

            # Poll inspect until the process exits (ExitCode != -1 means done)
            deadline = asyncio.get_event_loop().time() + _EXEC_TIMEOUT
            while True:
                inspect_r = await client.get(f"{_PROXY_URL}/exec/{exec_id}/json")
                data = inspect_r.json() if inspect_r.status_code == 200 else {}
                if not data.get("Running", True):
                    exit_code = data.get("ExitCode", -1)
                    break
                if asyncio.get_event_loop().time() >= deadline:
                    raise RuntimeError(f"supervisorctl {sub_action} {process} → timed out waiting for exit")
                await asyncio.sleep(0.5)

            if exit_code != 0:
                raise RuntimeError(f"supervisorctl {sub_action} {process} → exit {exit_code}")
            return f"supervisorctl {sub_action} {process} → OK (exit 0)"

    # ------------------------------------------------------------------
    # HTTP health check
    # ------------------------------------------------------------------

    async def _infra_verify(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                return f"infra_verify {url} → HTTP {resp.status_code}"
            except httpx.ConnectError:
                raise RuntimeError(f"infra_verify: cannot connect to {url}")
            except httpx.TimeoutException:
                raise RuntimeError(f"infra_verify: timeout connecting to {url}")

    # ------------------------------------------------------------------
    # PostgreSQL connectivity
    # ------------------------------------------------------------------

    async def _pg_check(self, db_name: str) -> str:
        import asyncpg
        env_map = {
            "nutrition": "DRHOUSE_POSTGRES_URL",
            "sport": "DRHOUSE_SPORT_POSTGRES_URL",
            "jarvis": "JARVIS_DB_URL",
            "ceo": "JARVIS_DB_URL",
        }
        url_env = env_map.get(db_name, f"{db_name.upper()}_DB_URL")
        url = os.environ.get(url_env, "")
        if not url:
            raise RuntimeError(f"pg_check: env var {url_env!r} not set")
        conn = await asyncpg.connect(url)
        try:
            await conn.execute("SELECT 1")
            return f"pg_check {db_name} → OK"
        finally:
            await conn.close()

    # ------------------------------------------------------------------
    # TCP connectivity
    # ------------------------------------------------------------------

    async def _tcp_check(self, host: str, port: int) -> str:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=_TCP_TIMEOUT,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return f"tcp_check {host}:{port} → open"
        except (OSError, asyncio.TimeoutError) as exc:
            raise RuntimeError(f"tcp_check {host}:{port} → {exc}")
