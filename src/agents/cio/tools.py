"""Timothy (CIO) MCP server — custom tools exposed to the Claude agent.

Tools:
  daily_log          — Append entry to today's memory log
  memory_search      — Text search across MEMORY.md + memory/*.md
  memory_get         — Read a specific memory file from workspace
  infra_check        — HTTP health check on internal service URLs
  docker_query       — List/inspect Docker containers/networks via socket proxy
  docker_action      — Perform lifecycle actions on Docker containers (restart/start/stop/kill)
  tcp_check          — TCP port connectivity checks (pure-Python, no dig needed)
  dns_lookup         — DNS resolution for hostnames
  pg_query           — Read-only SELECT queries against any named database
  send_message       — Send a message to another agent via Redis pub/sub
  cron_create/list/update/delete — Scheduled task management
"""

import asyncio
import json
import logging
import os
import socket as _socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_args(args) -> dict:
    """Normalize tool args — older SDK versions pass a JSON string instead of a dict."""
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return args if isinstance(args, dict) else {}


def _text(s: str) -> dict:
    """Wrap a plain string as an MCP text content response.

    The SDK's call_tool handler calls result.get("is_error") unconditionally,
    so every tool MUST return a dict — never a bare string.
    """
    return {"content": [{"type": "text", "text": str(s)}]}


try:
    from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    create_sdk_mcp_server = None
    sdk_tool = None


def create_timothy_mcp_server(workspace_path: Path, redis_a2a=None):
    """Build and return the in-process MCP server with Timothy custom tools.

    Returns None if the SDK MCP server API is not available.
    """
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
        return None

    # --- Memory tools -------------------------------------------------------

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's Timothy memory log. "
        "Use this to record infrastructure changes, incidents, decisions, findings, and resolved issues. message is required.",
        {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
    async def daily_log(args: dict) -> dict:
        args = _parse_args(args)
        message = args.get("message", "")
        if not message:
            return _text("No message provided.")
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(message)
            return _text(f"Logged: {message[:80]}")
        except Exception as exc:
            logger.error("daily_log: failed — %s", exc)
            return _text(f"Failed to log: {exc}")

    @sdk_tool(
        "memory_search",
        "Search across long-term memory (MEMORY.md) and all daily logs (memory/*.md) using text matching. "
        "Use this to recall past incidents, infrastructure changes, decisions, or known issues. "
        "Results include the matching lines with surrounding context, most recent files first.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    )
    async def memory_search(args: dict) -> dict:
        args = _parse_args(args)
        query = args.get("query", "").strip()
        if not query:
            return _text("No query provided.")

        top_k = int(args.get("top_k") or 5)
        query_lower = query.lower()

        memory_dir = workspace_path / "memory"
        dated_files = sorted(memory_dir.glob("*.md"), reverse=True) if memory_dir.exists() else []
        files_to_search = list(dated_files) + [workspace_path / "MEMORY.md"]

        results = []
        for f in files_to_search:
            if not f.exists():
                continue
            try:
                lines = f.read_text(encoding="utf-8").split("\n")
            except OSError:
                continue

            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    snippet = "\n".join(lines[start:end])
                    results.append(f"**{f.name}** (line {i + 1}):\n```\n{snippet}\n```")
                    if len(results) >= top_k:
                        break
            if len(results) >= top_k:
                break

        if not results:
            return _text(f"No results found for '{query}'.")

        return _text("\n\n---\n\n".join(results))

    @sdk_tool(
        "memory_get",
        "Read a specific memory file from the workspace. "
        "Use path relative to workspace root, e.g. 'MEMORY.md' or 'memory/2026-04-16.md'. "
        "Optionally specify start_line and num_lines to read a slice.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "default": 1},
                "num_lines": {"type": "integer", "default": 50},
            },
            "required": ["path"],
        },
    )
    async def memory_get(args: dict) -> dict:
        args = _parse_args(args)
        rel_path = args.get("path", "").strip()
        if not rel_path:
            return _text("No path provided.")

        target = (workspace_path / rel_path).resolve()
        try:
            target.relative_to(workspace_path.resolve())
        except ValueError:
            return _text("Access denied: path is outside the workspace directory.")

        if not target.exists():
            return _text(f"File not found: {rel_path}")

        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return _text(f"Error reading {rel_path}: {exc}")

        start_line = args.get("start_line")
        num_lines = args.get("num_lines")

        if start_line is not None or num_lines is not None:
            lines = content.split("\n")
            s = int(start_line or 1) - 1  # 1-indexed → 0-indexed
            n = int(num_lines) if num_lines is not None else len(lines)
            content = "\n".join(lines[s: s + n])

        return _text(content)

    # --- CIO domain tools ---------------------------------------------------

    @sdk_tool(
        "infra_check",
        "Run HTTP health checks against one or more internal service URLs. "
        "Returns HTTP status code and response time for each URL. "
        "Use this before writing any health report to verify actual service state. "
        "urls: comma-separated list of URLs (e.g. 'http://10.10.200.50/ping,http://10.10.200.62:80'). "
        "timeout: per-request timeout in seconds (default 5).",
        {
            "type": "object",
            "properties": {
                "urls": {"type": "string"},
                "timeout": {"type": "integer", "default": 5},
            },
            "required": ["urls"],
        },
    )
    async def infra_check(args: dict) -> dict:
        args = _parse_args(args)
        urls_raw = args.get("urls", "").strip()
        if not urls_raw:
            return _text("No URLs provided.")
        timeout = max(1, int(args.get("timeout") or 5))

        url_list = [u.strip() for u in urls_raw.split(",") if u.strip()]
        results = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            for url in url_list:
                try:
                    import time
                    t0 = time.monotonic()
                    resp = await client.get(url, follow_redirects=True)
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    results.append(f"{url}: HTTP {resp.status_code} ({elapsed_ms}ms)")
                except httpx.TimeoutException:
                    results.append(f"{url}: TIMEOUT after {timeout}s")
                except Exception as exc:
                    results.append(f"{url}: ERROR — {exc}")

        return _text("\n".join(results))

    @sdk_tool(
        "docker_query",
        "Query Docker via the socket proxy for infrastructure visibility. "
        "resource: 'containers' (list all with state/status), "
        "'networks' (list Docker networks), "
        "'logs' (tail container logs — requires name), "
        "'inspect' (full container detail — requires name), "
        "'version' (Docker engine version). "
        "name: container name or id (required for logs/inspect). "
        "lines: number of log lines to tail (default 30, max 200). "
        "filter: optional substring to filter container names.",
        {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "enum": ["containers", "networks", "logs", "inspect", "version"],
                    "default": "containers",
                },
                "name": {"type": "string"},
                "lines": {"type": "integer", "default": 30},
                "filter": {"type": "string"},
            },
            "required": ["resource"],
        },
    )
    async def docker_query(args: dict) -> dict:
        args = _parse_args(args)
        resource = (args.get("resource") or "containers").strip().lower()
        name = (args.get("name") or "").strip()
        lines = min(200, max(1, int(args.get("lines") or 30)))
        name_filter = (args.get("filter") or "").strip().lower()

        proxy = os.environ.get("DOCKER_PROXY_URL", "http://socket-proxy:2375")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if resource == "version":
                    resp = await client.get(f"{proxy}/version")
                    data = resp.json()
                    return _text(
                        f"Docker {data.get('Version','?')} "
                        f"(API {data.get('ApiVersion','?')}, "
                        f"OS {data.get('Os','?')}/{data.get('Arch','?')})"
                    )

                elif resource == "containers":
                    resp = await client.get(f"{proxy}/containers/json?all=1")
                    containers = resp.json()
                    out = []
                    for c in containers:
                        cname = c.get("Names", ["/??"])[0].lstrip("/")
                        if name_filter and name_filter not in cname.lower():
                            continue
                        state = c.get("State", "?")
                        status = c.get("Status", "?")
                        image = c.get("Image", "?").split("/")[-1]
                        out.append(f"{cname:<40} {state:<12} {status:<30} {image}")
                    if not out:
                        return _text("No containers found" + (f" matching '{name_filter}'" if name_filter else ""))
                    header = f"{'NAME':<40} {'STATE':<12} {'STATUS':<30} {'IMAGE'}"
                    return _text(header + "\n" + "\n".join(out))

                elif resource == "networks":
                    resp = await client.get(f"{proxy}/networks")
                    nets = resp.json()
                    out = []
                    for n in nets:
                        nname = n.get("Name", "?")
                        driver = n.get("Driver", "?")
                        scope = n.get("Scope", "?")
                        containers_count = len(n.get("Containers") or {})
                        out.append(f"{nname:<40} {driver:<12} {scope:<10} {containers_count} containers")
                    return _text("\n".join(out) if out else "No networks found")

                elif resource == "logs":
                    if not name:
                        return _text("name is required for logs (e.g. name='jarvios-redis')")
                    resp = await client.get(
                        f"{proxy}/containers/{name}/logs",
                        params={"stdout": "1", "stderr": "1", "tail": str(lines)},
                    )
                    # Docker log stream has 8-byte frame headers — strip them
                    raw = resp.content
                    text_lines = []
                    i = 0
                    while i < len(raw):
                        if i + 8 > len(raw):
                            break
                        frame_size = int.from_bytes(raw[i + 4:i + 8], "big")
                        i += 8
                        if frame_size > 0 and i + frame_size <= len(raw):
                            text_lines.append(raw[i:i + frame_size].decode("utf-8", errors="replace").rstrip())
                        i += frame_size
                    if not text_lines:
                        # Fallback: treat entire response as plain text
                        text_lines = resp.text.splitlines()
                    return _text("\n".join(text_lines[-lines:]) if text_lines else "(no logs)")

                elif resource == "inspect":
                    if not name:
                        return _text("name is required for inspect (e.g. name='jarvios-platform')")
                    resp = await client.get(f"{proxy}/containers/{name}/json")
                    if resp.status_code == 404:
                        return _text(f"Container '{name}' not found")
                    data = resp.json()
                    # Return key fields only to avoid huge output
                    summary = {
                        "Name": data.get("Name", "?").lstrip("/"),
                        "State": data.get("State", {}),
                        "NetworkSettings": {
                            k: v.get("IPAddress")
                            for k, v in (data.get("NetworkSettings", {}).get("Networks") or {}).items()
                        },
                        "RestartCount": data.get("RestartCount", 0),
                        "Mounts": [m.get("Source") for m in (data.get("Mounts") or [])],
                    }
                    return _text(json.dumps(summary, indent=2))

                else:
                    return _text(f"Unknown resource '{resource}'. Use: containers, networks, logs, inspect, version")

        except httpx.ConnectError:
            return _text(f"Cannot reach Docker socket proxy at {proxy}. Is the socket_proxy network up?")
        except Exception as exc:
            logger.error("docker_query: error — %s", exc)
            return _text(f"Docker query error: {exc}")

    @sdk_tool(
        "docker_action",
        "Perform a lifecycle action on a Docker container on the local host. "
        "Actions: restart | start | stop | kill. "
        "Run docker_query first to confirm the exact container name. "
        "name: container name or id. "
        "timeout: graceful stop timeout in seconds before kill (default 10, only used for 'stop').",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["restart", "start", "stop", "kill"]},
                "name": {"type": "string"},
                "timeout": {"type": "integer", "default": 10},
            },
            "required": ["action", "name"],
        },
    )
    async def docker_action(args: dict) -> dict:
        args = _parse_args(args)
        action = (args.get("action") or "").strip().lower()
        name = (args.get("name") or "").strip()
        timeout = int(args.get("timeout") or 10)

        if not name:
            return _text("name is required.")
        if action not in {"restart", "start", "stop", "kill"}:
            return _text(f"Invalid action '{action}'. Valid actions: restart, start, stop, kill")

        proxy = os.environ.get("DOCKER_PROXY_URL", "http://socket-proxy:2375")
        url = f"{proxy}/containers/{name}/{action}"
        params = {"t": timeout} if action == "stop" else {}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, params=params)

            if resp.status_code == 204:
                return _text(f"OK: container '{name}' {action}ed successfully.")
            elif resp.status_code == 304:
                return _text(f"Container '{name}' already in the target state (no-op).")
            elif resp.status_code == 404:
                return _text(f"Container '{name}' not found. Use docker_query to list containers.")
            elif resp.status_code == 409:
                return _text(f"Conflict: container '{name}' cannot perform '{action}' in its current state.")
            else:
                return {"content": [{"type": "text", "text": f"Unexpected response {resp.status_code}: {resp.text[:200]}"}], "is_error": True}

        except httpx.ConnectError:
            return _text(f"Cannot reach Docker socket proxy at {proxy}. Is the socket_proxy network up?")
        except Exception as exc:
            logger.error("docker_action[%s/%s]: error — %s", name, action, exc)
            return {"content": [{"type": "text", "text": f"Action failed: {exc}"}], "is_error": True}

    @sdk_tool(
        "tcp_check",
        "Check TCP connectivity to one or more host:port targets. "
        "No system tools needed — uses pure-Python asyncio. "
        "targets: comma-separated list of host:port (e.g. 'postgres-shared:5432,10.10.200.50:443'). "
        "timeout: per-target timeout in seconds (default 3).",
        {
            "type": "object",
            "properties": {
                "targets": {"type": "string"},
                "timeout": {"type": "integer", "default": 3},
            },
            "required": ["targets"],
        },
    )
    async def tcp_check(args: dict) -> dict:
        args = _parse_args(args)
        targets_raw = (args.get("targets") or "").strip()
        if not targets_raw:
            return _text("No targets provided. Use host:port format (comma-separated).")
        timeout = max(1, int(args.get("timeout") or 3))

        results = []
        for target in [t.strip() for t in targets_raw.split(",") if t.strip()]:
            if ":" not in target:
                results.append(f"{target}: ERROR — use host:port format")
                continue
            host, port_str = target.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                results.append(f"{target}: ERROR — invalid port '{port_str}'")
                continue
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=timeout
                )
                writer.close()
                await writer.wait_closed()
                results.append(f"{target}: OPEN")
            except asyncio.TimeoutError:
                results.append(f"{target}: TIMEOUT (>{timeout}s)")
            except ConnectionRefusedError:
                results.append(f"{target}: REFUSED")
            except OSError as exc:
                results.append(f"{target}: {exc}")

        return _text("\n".join(results))

    @sdk_tool(
        "dns_lookup",
        "Resolve hostnames to IP addresses using the container's DNS resolver. "
        "No dig/nslookup needed — uses Python socket. "
        "hosts: comma-separated list of hostnames (e.g. 'postgres-shared,socket-proxy,traefik.prova9x.com').",
        {
            "type": "object",
            "properties": {"hosts": {"type": "string"}},
            "required": ["hosts"],
        },
    )
    async def dns_lookup(args: dict) -> dict:
        args = _parse_args(args)
        hosts_raw = (args.get("hosts") or "").strip()
        if not hosts_raw:
            return _text("No hosts provided.")

        results = []
        for host in [h.strip() for h in hosts_raw.split(",") if h.strip()]:
            try:
                # Run blocking getaddrinfo in thread pool to avoid blocking event loop
                loop = asyncio.get_event_loop()
                addrs_raw = await loop.run_in_executor(
                    None, lambda h=host: _socket.getaddrinfo(h, None, _socket.AF_UNSPEC)
                )
                ips = sorted({a[4][0] for a in addrs_raw})
                results.append(f"{host}: {', '.join(ips)}")
            except _socket.gaierror as exc:
                results.append(f"{host}: NXDOMAIN ({exc})")
            except Exception as exc:
                results.append(f"{host}: ERROR — {exc}")

        return _text("\n".join(results))

    @sdk_tool(
        "pg_query",
        "Run a read-only SELECT query against a named PostgreSQL database. "
        "db: one of 'sport_metrics', 'nutrition_data', 'gestionale', 'cedolino', 'jarvios'. "
        "sql: a SELECT statement. "
        "params: optional list of query parameters (for $1/$2 placeholders). "
        "Returns rows as JSON. Use this to check DB health, counts, or diagnose data issues.",
        {
            "type": "object",
            "properties": {
                "db": {"type": "string"},
                "sql": {"type": "string"},
                "params": {"type": "array", "items": {}, "default": []},
            },
            "required": ["db", "sql"],
        },
    )
    async def pg_query(args: dict) -> dict:
        args = _parse_args(args)
        db = (args.get("db") or "").strip().lower()
        sql = (args.get("sql") or "").strip()
        raw_params = args.get("params") or []
        if isinstance(raw_params, str):
            try:
                raw_params = json.loads(raw_params)
            except Exception:
                raw_params = []
        params = raw_params if isinstance(raw_params, list) else []

        DB_URLS = {
            "sport_metrics": os.environ.get("SPORT_POSTGRES_URL", ""),
            "nutrition_data": os.environ.get("NUTRITION_POSTGRES_URL", ""),
            "gestionale": os.environ.get("GESTIONALE_POSTGRES_URL", ""),
            "cedolino": os.environ.get("CEDOLINO_POSTGRES_URL", ""),
            "jarvios": os.environ.get("JARVIOS_POSTGRES_URL", ""),
        }

        if not db:
            configured = [k for k, v in DB_URLS.items() if v]
            return _text(f"db is required. Available: {', '.join(DB_URLS.keys())} (configured: {', '.join(configured) or 'none'})")

        if db not in DB_URLS:
            return _text(f"Unknown database '{db}'. Available: {', '.join(DB_URLS.keys())}")

        url = DB_URLS[db]
        if not url:
            return _text(f"Database '{db}' URL not configured (env var missing).")

        if not sql:
            return _text("sql is required.")

        first_word = sql.split()[0].upper() if sql.split() else ""
        if first_word != "SELECT":
            return _text("Only SELECT statements are allowed via pg_query.")

        try:
            import asyncpg
            conn = await asyncpg.connect(url)
            try:
                rows = await conn.fetch(sql, *params)
                data = [dict(r) for r in rows]
                return _text(json.dumps(data, default=str, indent=2))
            finally:
                await conn.close()
        except Exception as exc:
            logger.error("pg_query[%s]: error — %s", db, exc)
            return _text(f"Query error: {exc}")

    # --- Ops-detector observability tools -----------------------------------

    @sdk_tool(
        "loki_query",
        "Query Loki for log lines matching a LogQL expression. "
        "logql: LogQL stream selector + filter (e.g. '{job=\"jarvios-platform\"} |= \"ERROR\"'). "
        "start_minutes_ago: how many minutes back to search (default 15, max 1440). "
        "limit: max log lines to return (default 100, max 500). "
        "Returns matched lines with ISO timestamps.",
        {
            "type": "object",
            "properties": {
                "logql": {"type": "string"},
                "start_minutes_ago": {"type": "integer", "default": 15},
                "limit": {"type": "integer", "default": 100},
            },
            "required": ["logql"],
        },
    )
    async def loki_query(args: dict) -> dict:
        args = _parse_args(args)
        logql = args.get("logql", "").strip()
        if not logql:
            return _text("logql is required.")
        lookback = max(1, min(1440, int(args.get("start_minutes_ago") or 15)))
        limit = max(1, min(500, int(args.get("limit") or 100)))

        loki_base = os.environ.get("LOKI_URL", "http://10.10.200.71:3100")
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=lookback)
        params = {
            "query": logql,
            "start": str(int(start.timestamp() * 1_000_000_000)),
            "end": str(int(now.timestamp() * 1_000_000_000)),
            "limit": str(limit),
            "direction": "backward",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{loki_base}/loki/api/v1/query_range", params=params
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            return _text("Loki query timed out.")
        except httpx.HTTPStatusError as exc:
            return _text(f"Loki HTTP {exc.response.status_code}: {exc.response.text[:200]}")
        except Exception as exc:
            return _text(f"Loki error: {exc}")

        lines: list[str] = []
        for stream in data.get("data", {}).get("result", []):
            for ts_ns, msg in stream.get("values", []):
                ts = datetime.fromtimestamp(
                    int(ts_ns) / 1_000_000_000, tz=timezone.utc
                ).isoformat()
                lines.append(f"{ts}  {msg}")

        if not lines:
            return _text(f"No log lines found for query: {logql}")
        lines.sort()
        return _text(f"Found {len(lines)} lines (last {lookback}m):\n\n" + "\n".join(lines))

    @sdk_tool(
        "runbook_list",
        "List all runbook .md files available in the runbooks directory. "
        "Returns filenames only — use runbook_read to read a specific file.",
        {},
    )
    async def runbook_list(args: dict) -> dict:
        runbooks_path = Path(os.environ.get("RUNBOOKS_PATH", "/app/runbooks"))
        if not runbooks_path.exists():
            return _text(f"Runbooks directory not found: {runbooks_path}")
        files = sorted(p.name for p in runbooks_path.iterdir()
                       if p.suffix in (".md", ".yaml", ".yml"))
        if not files:
            return _text("No runbook files found.")
        return _text("\n".join(files))

    @sdk_tool(
        "runbook_read",
        "Read a runbook file from the runbooks directory. "
        "filename: the filename (e.g. 'runbook-telegram-crash.md' or 'index.yaml'). "
        "Returns the full file content.",
        {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    )
    async def runbook_read(args: dict) -> dict:
        args = _parse_args(args)
        filename = args.get("filename", "").strip()
        if not filename:
            return _text("filename is required.")

        runbooks_path = Path(os.environ.get("RUNBOOKS_PATH", "/app/runbooks"))
        target = (runbooks_path / filename).resolve()

        # Path traversal guard
        try:
            target.relative_to(runbooks_path.resolve())
        except ValueError:
            return _text("Access denied: path is outside the runbooks directory.")

        if not target.exists():
            return _text(f"Runbook not found: {filename}")

        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return _text(f"Error reading {filename}: {exc}")

        return _text(content)

    @sdk_tool(
        "runbook_write",
        "Create or overwrite a runbook file in the runbooks directory. "
        "Use this when you discover a new failure pattern with no existing runbook, "
        "or when an existing runbook needs correction. "
        "filename: target filename (e.g. 'runbook-new-issue.md'). "
        "content: full file content (markdown or yaml).",
        {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["filename", "content"],
        },
    )
    async def runbook_write(args: dict) -> dict:
        args = _parse_args(args)
        filename = args.get("filename", "").strip()
        content = args.get("content", "")
        if not filename:
            return _text("filename is required.")

        runbooks_path = Path(os.environ.get("RUNBOOKS_PATH", "/app/runbooks"))
        target = (runbooks_path / filename).resolve()

        try:
            target.relative_to(runbooks_path.resolve())
        except ValueError:
            return _text("Access denied: path is outside the runbooks directory.")

        try:
            runbooks_path.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return _text(f"Written: {filename} ({len(content)} bytes)")
        except OSError as exc:
            return _text(f"Error writing {filename}: {exc}")

    # Strict command allowlist — read-only inspection or safe lifecycle ops only.
    # Adding to this list requires a security review.
    _CONTAINER_EXEC_ALLOWLIST = {
        "supervisorctl status",
        "supervisorctl tail ceo",
        "supervisorctl tail cio",
        "supervisorctl tail cfo",
        "supervisorctl tail cos",
        "supervisorctl tail coh",
        "supervisorctl tail don",
        "supervisorctl tail dos",
        "supervisorctl tail mt",
        "supervisorctl tail email_intelligence_agent",
        "supervisorctl tail platform-api",
        "supervisorctl tail worker-ops-detector",
        "supervisorctl tail worker-market",
        "supervisorctl restart worker-market",
        "supervisorctl restart worker-ops-detector",
        "supervisorctl restart cfo",
        "supervisorctl restart cio",
        "supervisorctl restart cos",
        "supervisorctl restart coh",
        "supervisorctl restart don",
        "supervisorctl restart dos",
        "supervisorctl restart mt",
        "supervisorctl restart email_intelligence_agent",
        "supervisorctl restart ceo",
    }

    _CONTAINER_EXEC_ALLOWED_CONTAINERS = {
        "jarvios-platform",
    }

    @sdk_tool(
        "container_exec",
        "Execute a pre-approved command inside an allowlisted Docker container. "
        "Only commands and containers on the static allowlist are accepted; any "
        "other request is rejected. "
        "container: container name (only 'jarvios-platform' is currently allowed). "
        "command: must exactly match an allowlisted command (e.g. "
        "'supervisorctl status', 'supervisorctl tail coh', 'supervisorctl restart worker-market'). "
        "Use 'supervisorctl tail <agent>' to read recent stdout of a specific process. "
        "Returns combined stdout+stderr output.",
        {
            "type": "object",
            "properties": {
                "container": {"type": "string"},
                "command": {"type": "string"},
            },
            "required": ["container", "command"],
        },
    )
    async def container_exec(args: dict) -> dict:
        args = _parse_args(args)
        container = args.get("container", "").strip()
        command = args.get("command", "").strip()
        if not container:
            return _text("container is required.")
        if not command:
            return _text("command is required.")
        if container not in _CONTAINER_EXEC_ALLOWED_CONTAINERS:
            return _text(
                f"Container '{container}' is not on the allowlist. "
                f"Allowed: {sorted(_CONTAINER_EXEC_ALLOWED_CONTAINERS)}"
            )
        if command not in _CONTAINER_EXEC_ALLOWLIST:
            return _text(
                f"Command not on allowlist. Reject reason: arbitrary shell "
                f"execution disabled. Use one of: "
                f"{sorted(_CONTAINER_EXEC_ALLOWLIST)}"
            )

        proxy = os.environ.get("DOCKER_PROXY_URL", "http://socket-proxy:2375")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Step 1: Create exec instance
                exec_resp = await client.post(
                    f"{proxy}/containers/{container}/exec",
                    json={
                        "Cmd": ["sh", "-c", command],
                        "AttachStdout": True,
                        "AttachStderr": True,
                    },
                )
                if exec_resp.status_code == 404:
                    return _text(f"Container '{container}' not found.")
                exec_resp.raise_for_status()
                exec_id = exec_resp.json().get("Id", "")
                if not exec_id:
                    return _text("Docker exec create returned no Id.")

                # Step 2: Start exec and collect output
                start_resp = await client.post(
                    f"{proxy}/exec/{exec_id}/start",
                    json={"Detach": False, "Tty": False},
                )
                start_resp.raise_for_status()

                # Docker multiplexed stream: 8-byte header per frame
                raw = start_resp.content
                output_parts: list[str] = []
                i = 0
                while i < len(raw):
                    if i + 8 > len(raw):
                        break
                    frame_size = int.from_bytes(raw[i + 4:i + 8], "big")
                    i += 8
                    if frame_size > 0:
                        if i + frame_size <= len(raw):
                            output_parts.append(
                                raw[i:i + frame_size].decode("utf-8", errors="replace")
                            )
                        else:
                            logger.warning(
                                "container_exec: truncated frame (expected %d bytes, got %d)",
                                frame_size, len(raw) - i,
                            )
                    i += frame_size

                output = "".join(output_parts).strip()

                # Retrieve exit code via inspect
                exit_code = None
                try:
                    inspect_resp = await client.get(f"{proxy}/exec/{exec_id}/inspect")
                    if inspect_resp.status_code == 200:
                        exit_code = inspect_resp.json().get("ExitCode")
                except Exception:
                    pass

                exit_info = f" (exit {exit_code})" if exit_code is not None else ""
                return _text(f"Executed: {command}{exit_info}\nOutput: {output or '(no output)'}")

        except httpx.ConnectError:
            return _text(f"Cannot reach Docker socket proxy at {proxy}.")
        except Exception as exc:
            logger.error("container_exec[%s/%s]: error — %s", container, command, exc)
            return {"content": [{"type": "text", "text": f"Exec error: {exc}"}], "is_error": True}

    @sdk_tool(
        "container_file_patch",
        "DISABLED — arbitrary in-container file writes are not permitted from "
        "the agent runtime. To patch a file in a running container, the operator "
        "must perform `docker cp` manually after review. "
        "Calling this tool returns a clear rejection.",
        {
            "type": "object",
            "properties": {
                "container": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["container", "path", "content"],
        },
    )
    async def container_file_patch(args: dict) -> dict:
        args = _parse_args(args)
        container = args.get("container", "").strip()
        path = args.get("path", "").strip()
        return _text(
            "container_file_patch is disabled: arbitrary file writes into "
            "running containers must be performed by a human operator via "
            f"`docker cp`. Requested target was '{container}:{path}'. "
            "If a recurring patch is required, add a wrapper in the agent "
            "image and an explicit allowlist before re-enabling this tool."
        )

    # --- A2A send_message (Redis pub/sub) -----------------------------------

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _send_message_fn = create_send_message_tool("cio", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Use 'to' to specify the target agent ID (e.g. 'ceo' for the CEO). "
            "'message' is the natural language request to send. "
            "Use this for cross-domain escalation, executive decisions, or business context. "
            "Set wait_response=false for one-way notifications (morning briefings, FYI copies, status broadcasts) — returns immediately without blocking on the receiver's reasoning. Default true preserves request/response semantics: the call blocks until the target agent replies.",
            {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "message": {"type": "string"},
                    "wait_response": {"type": "boolean", "default": True},
                },
                "required": ["to", "message"],
            },
        )
        async def send_message(args: dict) -> dict:
            args = _parse_args(args)
            return _text(await _send_message_fn(args))
    else:
        send_message = None  # Redis not configured

    # --- Cron tools ---------------------------------------------------------

    @sdk_tool(
        "cron_create",
        "Create a new scheduled IT task. "
        "schedule format: 'daily@HH:MM' | 'weekly@DOW@HH:MM' (mon/tue/.../sun) | 'once@YYYY-MM-DD@HH:MM'. "
        "All times are Europe/Rome (CET/CEST). "
        "telegram_notify: set to true to receive a Telegram message with the result.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "schedule": {"type": "string"},
                "prompt": {"type": "string"},
                "session_id": {"type": "string", "default": ""},
                "telegram_notify": {"type": "boolean", "default": False},
            },
            "required": ["name", "schedule", "prompt"],
        },
    )
    async def cron_create(args: dict) -> dict:
        args = _parse_args(args)
        name = args.get("name", "").strip()
        schedule = args.get("schedule", "").strip()
        prompt_text = args.get("prompt", "").strip()
        if not name or not schedule or not prompt_text:
            return _text("name, schedule, and prompt are required.")
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            entry = store.create(
                name=name,
                schedule=schedule,
                prompt=prompt_text,
                session_id=args.get("session_id") or "",
                telegram_notify=bool(args.get("telegram_notify", False)),
            )
            return _text(f"Created cron '{entry.name}' (id={entry.id}, schedule={entry.schedule})")
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool(
        "cron_list",
        "List all scheduled tasks (built-in and user-created) with their current status.",
        {},
    )
    async def cron_list(args: dict) -> dict:
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            entries = store.all()
            if not entries:
                return _text("No scheduled tasks.")
            lines = []
            for e in entries:
                status = e.last_status if e.last_run else "never run"
                enabled = "enabled" if e.enabled else "disabled"
                builtin_tag = " [builtin]" if e.builtin else ""
                lines.append(
                    f"- **{e.name}** (id={e.id}){builtin_tag}\n"
                    f"  schedule={e.schedule}, {enabled}, last={status}\n"
                    f"  telegram_notify={e.telegram_notify}"
                )
            return _text("\n\n".join(lines))
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool(
        "cron_update",
        "Update a scheduled task by its id. "
        "Updatable fields: name, schedule, prompt, session_id, telegram_notify, enabled.",
        {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "schedule": {"type": "string"},
                "prompt": {"type": "string"},
                "session_id": {"type": "string"},
                "telegram_notify": {"type": "boolean"},
                "enabled": {"type": "boolean"},
            },
            "required": ["id"],
        },
    )
    async def cron_update(args: dict) -> dict:
        args = _parse_args(args)
        cron_id = args.get("id", "").strip()
        if not cron_id:
            return _text("id is required.")
        updates = {k: v for k, v in args.items() if k != "id" and v is not None}
        if not updates:
            return _text("No fields to update.")
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            entry = store.update(cron_id, **updates)
            return _text(f"Updated cron '{entry.name}' (id={entry.id})")
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool(
        "cron_delete",
        "Delete a user-created scheduled task by its id. "
        "Built-in tasks cannot be deleted — use cron_update with enabled=false to disable them.",
        {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    )
    async def cron_delete(args: dict) -> dict:
        args = _parse_args(args)
        cron_id = args.get("id", "").strip()
        if not cron_id:
            return _text("id is required.")
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            store.delete(cron_id)
            return _text(f"Deleted cron id={cron_id}")
        except Exception as exc:
            return _text(f"Error: {exc}")

    # --- Issue reporting and HITL remediation --------------------------------

    @sdk_tool(
        "collect_and_remediate",
        "Collect all morning issue reports from agents, deduplicate by component, "
        "and drive the sequential HITL Telegram approval loop. "
        "Call this IMMEDIATELY when the issue_collector cron fires. "
        "Do NOT call any other tool before this — the loop may run for up to 70 minutes. "
        "Returns a summary string when the loop completes.",
        {},  # No input args — the tool handles everything internally
    )
    async def collect_and_remediate(args: dict) -> dict:
        try:
            from agents.cio.run_issue_collection import run_issue_collection
            result = await run_issue_collection(workspace_path)
            return {"content": [{"type": "text", "text": result}]}
        except Exception as exc:
            logger.error("collect_and_remediate: failed — %s", exc, exc_info=True)
            return {"content": [{"type": "text", "text": f"Error: {exc}"}], "is_error": True}

    # --- Build server -------------------------------------------------------

    all_tools = [
        daily_log, memory_search, memory_get,
        infra_check,
        docker_query, docker_action, tcp_check, dns_lookup, pg_query,
        loki_query, runbook_list, runbook_read, runbook_write,
        container_exec, container_file_patch,
        cron_create, cron_list, cron_update, cron_delete, collect_and_remediate,
    ]
    if send_message is not None:
        all_tools.append(send_message)
    from agent_runner.tools.memory_box import create_query_memory_tool
    _query_memory = create_query_memory_tool("cio")
    if _query_memory is not None:
        all_tools.append(_query_memory)
    try:
        server = create_sdk_mcp_server(name="cio-tools", tools=all_tools)
        logger.info(
            "mcp_server: Timothy (CIO) tools registered (%d tools)",
            len(all_tools),
        )
        return server
    except Exception as exc:
        logger.error("mcp_server: failed to create server — %s", exc)
        return None
