# src/agent_runner/client.py
"""Generic agent client — wraps ClaudeSDKClient behind a stable interface.

ClaudeSDKClient maintains a *persistent* subprocess connection (spawned once
at startup), so each message avoids the ~4s Node.js boot cost.  It runs in
streaming mode by default.
"""

import asyncio
import inspect
import logging
import time
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    ThinkingConfigAdaptive,
)

from agent_runner.config import AgentConfig
from agent_runner.memory.daily_logger import DailyLogger
from agent_runner.memory.pipeline.queue import PipelineItem, PipelineQueue
from agent_runner.telemetry import AGENT_BUSY, get_tracer, record_llm_turn
from plugin_runtime.context import PluginContext
from plugin_runtime.tools import ToolSpec
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)

_tracer = get_tracer(__name__)

_STREAM_TIMEOUT = 480   # seconds — fallback default; per-agent override via AgentConfig.stream_timeout_s
_IMAGE_TIMEOUT = 120    # seconds — generous for large vision requests
_MARGIN_S = 30          # AGENT_MAX_TURN_S must be >= STREAM_TIMEOUT + this margin

_FACTUAL_EVIDENCE_CONTRACT = """\
You must ground operational claims in the actual state visible through tools,
explicit user-provided data, or quoted workspace memory that is still current.

Do not state patterns, trends, streaks, totals, causes, or status as fact unless
you have checked the relevant source data in the current turn or the prompt
provides exact evidence for that claim. This includes phrases such as
"consecutive days", "driver", "confirmed", "resolved", "open", "clean",
"under/over target", "root cause", and similar status language.

When evidence exists, include the relevant scope in the answer: date range,
row count, source/tool, or concrete values. When evidence is partial, say what
was verified and what was not. If evidence is unavailable, say that it is unverified
and present any interpretation as a hypothesis, not as a fact.

If challenged by the user, re-check the source data before correcting yourself.
Do not defend or elaborate an unsupported claim."""


class BaseAgentClient:
    """Persistent Claude SDK subprocess connection.

    Usage (managed by the FastAPI lifespan):
        client = create_agent_client(config)
        await client.connect()
        text = await client.query(msg)
        async for chunk in client.stream(msg): ...
        await client.disconnect()
    """

    def __init__(
        self,
        config: AgentConfig,
        system_prompt: str,
        options: ClaudeAgentOptions,
        redis_a2a=None,
        skills_signature: str = "",
    ) -> None:
        self.config = config
        self.name = config.name
        self._system_prompt = system_prompt
        self._options = options
        self._skills_signature = skills_signature
        self._skills_last_check = 0.0
        # Validate timeout layering: outer A2A cap must leave room for the
        # inner SDK stream timeout + margin so the receiver can always publish
        # a sentinel response on hard-cap exit.
        if config.agent_max_turn_s < config.stream_timeout_s + _MARGIN_S:
            raise ValueError(
                f"AgentConfig '{config.id}': agent_max_turn_s "
                f"({config.agent_max_turn_s:.0f}s) must be >= "
                f"stream_timeout_s ({config.stream_timeout_s:.0f}s) + "
                f"{_MARGIN_S}s margin. Adjust JARVIOS_AGENT_MAX_TURN_S"
                f"[_{config.id.upper()}] or JARVIOS_STREAM_TIMEOUT"
                f"[_{config.id.upper()}]."
            )
        logger.info(
            "agent[%s]: stream_timeout=%.0fs, agent_max_turn=%.0fs",
            config.id, config.stream_timeout_s, config.agent_max_turn_s,
        )
        # Held so `_refresh_mcp_options()` can rebuild a fresh in-process MCP
        # server before every (re)connect — the SDK does not refresh server
        # bindings when the same options object is reused across SDK
        # reincarnations, which causes long-lived agents to lose visibility
        # of their `mcp__<id>-tools__*` tools after the first subprocess.
        self._redis_a2a = redis_a2a
        self._sdk: ClaudeSDKClient | None = None
        self._lock = asyncio.Lock()
        # True while *any* code path is consuming `_sdk.receive_response()`.
        # The dispatch lock alone is not sufficient: stream() releases the lock
        # right after the SDK query is sent and iterates the response outside
        # of it (see Issue 1 fix below). A second concurrent caller of
        # query()/stream() would open a second async-iterator on the same
        # underlying anyio MemoryObjectReceiveStream and the two consumers
        # would steal messages from each other, wedging at least one of them.
        self._stream_active: bool = False
        self._daily = DailyLogger(config.workspace_path)
        self._pipeline_queue: PipelineQueue | None = None
        self._last_result_msg = None
        self._last_turn_stats: dict[str, object] = {}

    def set_pipeline_queue(self, queue: PipelineQueue) -> None:
        """Attach the memory pipeline queue. Called by the lifespan before serving."""
        self._pipeline_queue = queue

    def get_last_turn_stats(self) -> dict[str, object]:
        """Return lightweight telemetry for the last completed SDK turn."""
        return dict(self._last_turn_stats)

    @property
    def is_busy(self) -> bool:
        """True while any caller holds the dispatch lock OR is consuming the SDK stream."""
        return self._lock.locked() or self._stream_active

    # -- Lifecycle ----------------------------------------------------------

    def _update_options(self, update: dict) -> None:
        try:
            updated = self._options.model_copy(update=update)
            if all(getattr(updated, key, None) == value for key, value in update.items()):
                self._options = updated
                return
        except AttributeError:
            pass
        for key, value in update.items():
            setattr(self._options, key, value)

    def _reset_turn_stats(self) -> None:
        self._last_turn_stats = {
            "tool_calls": 0,
            "tool_failures": 0,
            "mutating_tool_calls": 0,
            "last_tool_name": "",
            "text_after_last_tool_chars": 0,
        }

    def _record_tool_call(self, name: str) -> None:
        name = str(name or "").strip()
        self._last_turn_stats["tool_calls"] = int(self._last_turn_stats.get("tool_calls", 0)) + 1
        self._last_turn_stats["last_tool_name"] = name
        self._last_turn_stats["text_after_last_tool_chars"] = 0
        readonly_names = {
            "Read",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "infra_check",
            "log_search",
            "memory_get",
            "pg_query",
            "runbook_read",
        }
        if name and name not in readonly_names:
            self._last_turn_stats["mutating_tool_calls"] = int(
                self._last_turn_stats.get("mutating_tool_calls", 0)
            ) + 1

    def _record_stream_event_stats(self, event: dict) -> None:
        if event.get("type") == "content_block_start":
            block = event.get("content_block", {}) or {}
            if block.get("type") == "tool_use":
                self._record_tool_call(str(block.get("name", "")))
        elif event.get("type") == "content_block_delta":
            delta = event.get("delta", {}) or {}
            if delta.get("type") == "tool_use_error_delta":
                self._last_turn_stats["tool_failures"] = int(
                    self._last_turn_stats.get("tool_failures", 0)
                ) + 1

    def _refresh_skill_snapshot_options(self, force: bool = False) -> bool:
        if not self.config.effective_skills_watch_enabled:
            return False
        now = time.monotonic()
        debounce = max(0.0, self.config.effective_skills_watch_debounce_s)
        if not force and now - self._skills_last_check < debounce:
            return False
        self._skills_last_check = now
        try:
            from agent_runner.memory.workspace_loader import load_workspace_context

            ctx = load_workspace_context(
                self.config.workspace_path,
                skills_allowlist=self.config.skill_allowlist,
            )
            signature = ctx.get("skills_signature", "")
            if signature == self._skills_signature:
                return False
            system_prompt = _build_system_prompt(ctx)
            self._system_prompt = system_prompt
            self._skills_signature = signature
            self._update_options({"system_prompt": system_prompt})
            logger.info("agent[%s]: refreshed skills snapshot", self.config.id)
            return True
        except Exception as exc:
            logger.warning("agent[%s]: skills snapshot refresh failed — %s", self.config.id, exc)
            return False

    async def _refresh_skill_subprocess_if_needed(self) -> None:
        changed = self._refresh_skill_snapshot_options()
        if not changed or not self._sdk:
            return
        await self._sdk.disconnect()
        self._sdk = ClaudeSDKClient(options=self._options)
        await self._sdk.connect()
        logger.info("agent[%s]: reconnected after skills snapshot refresh", self.config.id)

    def _refresh_mcp_options(self) -> None:
        """Rebuild the in-process MCP server before each (re)connect.

        Reusing the same MCP server `instance` object across multiple
        ClaudeSDKClient lifecycles leaves the new claude CLI subprocess
        with a stale stdio bridge: the `mcp__<id>-tools__*` entries are
        announced at session init but tool invocations resolve to a
        dead/replaced server and surface as "No such tool available"
        (or get filtered out of the deferred-tool manifest entirely).
        Refreshing the factory output rebinds the bridge cleanly.
        """
        mcp_servers = _build_mcp_servers(
            self.config,
            self.config.workspace_path,
            redis_a2a=self._redis_a2a,
        )
        self._update_options({"mcp_servers": mcp_servers if mcp_servers else None})

    async def connect(self) -> None:
        self._refresh_skill_snapshot_options(force=True)
        self._refresh_mcp_options()
        self._sdk = ClaudeSDKClient(options=self._options)
        await self._sdk.connect()
        logger.info("agent[%s]: ClaudeSDKClient connected", self.config.id)

    async def disconnect(self) -> None:
        if self._sdk:
            try:
                await self._sdk.disconnect()
            except Exception as exc:
                logger.warning("agent[%s]: disconnect error — %s", self.config.id, exc)
            finally:
                self._sdk = None

    async def _reconnect(self) -> None:
        logger.warning("agent[%s]: reconnecting subprocess…", self.config.id)
        if self._sdk:
            try:
                await self._sdk.disconnect()
            except Exception:
                pass
            self._sdk = None
        self._refresh_mcp_options()
        self._sdk = ClaudeSDKClient(options=self._options)
        await self._sdk.connect()
        logger.info("agent[%s]: subprocess reconnected", self.config.id)

    async def interrupt(self) -> bool:
        if not self._sdk:
            return False
        try:
            await self._sdk.interrupt()
            return True
        except Exception as exc:
            logger.warning("agent[%s]: interrupt failed — %s", self.config.id, exc)
            return False

    async def get_context_usage(self) -> dict:
        if not self._sdk:
            return {}
        try:
            usage = await self._sdk.get_context_usage()
            return {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
                "cache_creation_tokens": getattr(usage, "cache_creation_tokens", 0) or 0,
                "cache_read_tokens": getattr(usage, "cache_read_tokens", 0) or 0,
            }
        except Exception as exc:
            logger.warning("agent[%s]: get_context_usage failed — %s", self.config.id, exc)
            return {}

    async def get_mcp_status(self) -> dict:
        if not self._sdk:
            return {}
        try:
            status = await self._sdk.get_mcp_status()
            servers = getattr(status, "servers", None) or {}
            return servers if isinstance(servers, dict) else {}
        except Exception as exc:
            logger.warning("agent[%s]: get_mcp_status failed — %s", self.config.id, exc)
            return {}

    async def set_model(self, model_name: str) -> None:
        if not self._sdk:
            raise RuntimeError(f"{self.name} not connected")
        await self._sdk.set_model(model_name)
        logger.info("agent[%s]: model switched to %s", self.config.id, model_name)

    async def set_thinking(self, mode: str) -> None:
        try:
            from claude_agent_sdk import ThinkingConfigEnabled, ThinkingConfigDisabled
        except ImportError:
            ThinkingConfigEnabled = None
            ThinkingConfigDisabled = None

        if mode == "auto":
            thinking = ThinkingConfigAdaptive(type="adaptive")
        elif mode == "on":
            thinking = (
                ThinkingConfigEnabled(type="enabled", budget_tokens=8000)
                if ThinkingConfigEnabled else ThinkingConfigAdaptive(type="adaptive")
            )
        else:
            thinking = None

        try:
            self._options = self._options.model_copy(update={"thinking": thinking})
        except AttributeError:
            try:
                self._options.thinking = thinking
            except Exception as exc:
                logger.warning("agent[%s]: cannot update thinking — %s", self.config.id, exc)
                return

        # Fix Issue 3: acquire lock before reconnect to prevent races with
        # in-flight query()/stream() calls that also mutate self._sdk.
        async with self._lock:
            await self._reconnect()
        logger.info("agent[%s]: thinking mode set to %s", self.config.id, mode)

    # -- Response processing helpers ----------------------------------------

    def _process_message(self, msg, text_parts: list[str]) -> bool:
        """Process a single SDK message. Returns True if ResultMessage (stop)."""
        if isinstance(msg, RateLimitEvent):
            logger.warning(
                "agent[%s]: rate limit — status=%s utilization=%.0f%%",
                self.config.id,
                getattr(msg, "status", "?"),
                (getattr(msg, "utilization", 0) or 0) * 100,
            )
        elif isinstance(msg, TaskStartedMessage):
            logger.info("agent[%s]: subagent started — %s", self.config.id, msg.description[:80])
            try:
                self._daily.log(f"[SUBAGENT] Started: {msg.description[:100]}")
            except Exception:
                pass
        elif isinstance(msg, TaskProgressMessage):
            logger.debug("agent[%s]: subagent progress — tool=%s", self.config.id, msg.last_tool_name)
        elif isinstance(msg, TaskNotificationMessage):
            icon = {"completed": "\u2713", "failed": "\u2717", "stopped": "\u2298"}.get(msg.status, "?")
            logger.info("agent[%s]: subagent %s — %s", self.config.id, msg.status, msg.summary[:80])
            try:
                self._daily.log(f"[SUBAGENT] {icon} {msg.status.upper()}: {msg.summary[:120]}")
            except Exception:
                pass
        elif isinstance(msg, StreamEvent):
            event = msg.event
            self._record_stream_event_stats(event)
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        if int(self._last_turn_stats.get("tool_calls", 0)) > 0:
                            self._last_turn_stats["text_after_last_tool_chars"] = int(
                                self._last_turn_stats.get("text_after_last_tool_chars", 0)
                            ) + len(text)
                        text_parts.append(text)
                        return False
        elif hasattr(msg, "content") and msg.content:
            for block in msg.content:
                if hasattr(block, "text") and block.text:
                    text_parts.append(block.text)

        if isinstance(msg, ResultMessage):
            self._last_result_msg = msg
            try:
                self._daily.log(
                    f"[COST] ${msg.total_cost_usd:.4f} | {msg.duration_ms}ms"
                    f" | turns={msg.num_turns}"
                )
            except Exception:
                pass
            return True
        return False

    # -- Private stream helper ----------------------------------------------

    async def _iter_stream_response(self):
        """Iterate SDK response, yielding text chunks. Side-effects via _process_message.

        Must be called *outside* self._lock so that early cancellation / break
        by the caller does not permanently hold the lock.
        """
        yielded_any = False
        async for msg in self._sdk.receive_response():
            if isinstance(msg, StreamEvent):
                event = msg.event
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yielded_any = True
                            yield text
            elif not yielded_any and hasattr(msg, "content") and msg.content:
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        yielded_any = True
                        yield block.text
            dummy: list[str] = []
            if self._process_message(msg, dummy):
                break

    # -- Public interface ---------------------------------------------------

    async def query(self, message: str, session_id: str | None = None, source: str = "user") -> str:
        if not self._sdk:
            raise RuntimeError(f"{self.name} not connected")
        self._last_result_msg = None
        self._reset_turn_stats()
        AGENT_BUSY.labels(agent_id=self.config.id).set(1)
        with _tracer.start_as_current_span(
            "llm.turn",
            attributes={"agent.id": self.config.id, "llm.source": source},
        ) as span:
            try:
                # Fix Issue 2: guard the retry path with a null-check and wrap the
                # second query() call in its own try/except.
                async with self._lock:
                    await self._refresh_skill_subprocess_if_needed()
                    try:
                        await self._sdk.query(message, session_id=session_id or "default")
                    except Exception as exc:
                        logger.warning("agent[%s]: subprocess error on query — %s", self.config.id, exc)
                        await self._reconnect()
                        if not self._sdk:
                            raise RuntimeError(f"{self.name} reconnect failed") from exc
                        try:
                            await self._sdk.query(message, session_id=session_id or "default")
                        except Exception as retry_exc:
                            logger.error("agent[%s]: query failed after reconnect — %s", self.config.id, retry_exc)
                            raise
                    text_parts: list[str] = []
                    self._stream_active = True
                    try:
                        async with asyncio.timeout(self.config.stream_timeout_s):
                            async for msg in self._sdk.receive_response():
                                if self._process_message(msg, text_parts):
                                    break
                    except TimeoutError:
                        logger.error(
                            "agent[%s]: query timed out after %.0fs — reconnecting",
                            self.config.id, self.config.stream_timeout_s,
                        )
                        await self._reconnect()
                        raise
                    finally:
                        self._stream_active = False
                if self._last_result_msg is not None:
                    rm = self._last_result_msg
                    span.set_attribute("llm.cost_usd", float(rm.total_cost_usd or 0))
                    span.set_attribute("llm.duration_ms", int(rm.duration_ms or 0))
                    span.set_attribute("llm.num_turns", int(rm.num_turns or 0))
                    record_llm_turn(
                        agent_id=self.config.id,
                        source=source,
                        cost_usd=float(rm.total_cost_usd or 0),
                        duration_ms=int(rm.duration_ms or 0),
                    )
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                raise
            finally:
                AGENT_BUSY.labels(agent_id=self.config.id).set(0)
        response_text = "".join(text_parts)
        if self._pipeline_queue:
            priority = 0 if source == "a2a" else 1
            await self._pipeline_queue.put(PipelineItem(
                priority=priority,
                agent_id=self.config.id,
                message=message,
                response=response_text,
                source=source,
            ))
        return response_text

    async def stream(self, message: str, session_id: str | None = None):
        if not self._sdk:
            raise RuntimeError(f"{self.name} not connected")
        self._last_result_msg = None
        self._reset_turn_stats()
        # Fix Issue 1: only hold the lock for the query dispatch, not across
        # yields — an early break / cancellation by the caller would otherwise
        # permanently hold the lock and deadlock future query() calls.
        async with self._lock:
            await self._refresh_skill_subprocess_if_needed()
            try:
                await self._sdk.query(message, session_id=session_id or "default")
            except Exception as exc:
                logger.warning("agent[%s]: subprocess error on stream — %s", self.config.id, exc)
                await self._reconnect()
                if not self._sdk:
                    raise RuntimeError(f"{self.name} reconnect failed")
                await self._sdk.query(message, session_id=session_id or "default")
        # Iterate outside the lock — safe because only one caller can dispatch
        # at a time, and `_stream_active` blocks any concurrent A2A receivers.
        AGENT_BUSY.labels(agent_id=self.config.id).set(1)
        self._stream_active = True
        try:
            async with asyncio.timeout(self.config.stream_timeout_s):
                async for chunk in self._iter_stream_response():
                    yield chunk
            if self._last_result_msg is not None:
                rm = self._last_result_msg
                record_llm_turn(
                    agent_id=self.config.id,
                    source="stream",
                    cost_usd=float(rm.total_cost_usd or 0),
                    duration_ms=int(rm.duration_ms or 0),
                )
        except TimeoutError:
            logger.error("agent[%s]: stream timed out after %.0fs — reconnecting", self.config.id, self.config.stream_timeout_s)
            await self._reconnect()
            raise
        finally:
            # Cleared even on cancellation before the first yield.
            self._stream_active = False
            AGENT_BUSY.labels(agent_id=self.config.id).set(0)

    async def stream_image(
        self,
        image_bytes: bytes,
        caption: str | None = None,
        session_id: str | None = None,
        media_type: str = "image/jpeg",
    ):
        import base64

        b64 = base64.b64encode(image_bytes).decode()
        content: list = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": caption or self.config.default_image_caption},
        ]
        prompt_dict = {
            "type": "user",
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
        }

        async def _prompt_stream():
            yield prompt_dict

        if not self._sdk:
            raise RuntimeError(f"{self.name} not connected")
        # Fix Issue 1 (stream_image): same pattern — lock only covers dispatch.
        async with self._lock:
            await self._refresh_skill_subprocess_if_needed()
            try:
                await self._sdk.query(_prompt_stream(), session_id=session_id or "default")
            except Exception as exc:
                logger.warning("agent[%s]: subprocess error on stream_image — %s", self.config.id, exc)
                await self._reconnect()
                if not self._sdk:
                    raise RuntimeError(f"{self.name} reconnect failed")
                await self._sdk.query(_prompt_stream(), session_id=session_id or "default")
        # Iterate outside the lock — deduplicated via _iter_stream_response.
        self._stream_active = True
        try:
            async for chunk in self._iter_stream_response():
                yield chunk
        finally:
            self._stream_active = False


def create_agent_client(config: AgentConfig, redis_a2a=None) -> "BaseAgentClient":
    """Build and return a configured BaseAgentClient (not yet connected).

    Args:
        config: Per-agent configuration.
        redis_a2a: Optional RedisA2A instance — passed to the MCP server factory
                   so tools like send_message can be wired up at creation time.
    """
    from agent_runner.memory.workspace_loader import load_workspace_context

    workspace_path = config.workspace_path
    ctx = load_workspace_context(workspace_path, skills_allowlist=config.skill_allowlist)
    system_prompt = _build_system_prompt(ctx)

    # MCP servers
    mcp_servers = _build_mcp_servers(config, workspace_path, redis_a2a=redis_a2a)

    # Permission hook + SDK hooks
    can_use_tool = None
    sdk_hooks: dict = {}
    try:
        from agent_runner.hooks.permission_hook import build_can_use_tool
        from agent_runner.hooks.sdk_hooks import build_all_hooks

        can_use_tool = build_can_use_tool()
        sdk_hooks = build_all_hooks(workspace_path)
    except ImportError:
        logger.warning("agent[%s]: hooks not available — all tools auto-allowed", config.id)

    thinking_cfg = ThinkingConfigAdaptive(type="adaptive") if config.thinking else None
    betas = ["context-1m-2025-08-07"] if config.context_1m else []

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=config.allowed_tools,
        can_use_tool=can_use_tool,
        hooks=sdk_hooks if sdk_hooks else None,
        mcp_servers=mcp_servers if mcp_servers else None,
        cwd=str(workspace_path),
        model=config.model or None,
        fallback_model=config.fallback_model or None,
        max_budget_usd=config.budget,
        effort=config.effort or None,
        thinking=thinking_cfg,
        betas=betas,
    )

    dl = DailyLogger(workspace_path)
    dl.log(f"[AGENT INIT] {config.name} (ClaudeSDKClient, persistent) ready")
    logger.info("agent[%s]: %s initialized (not yet connected)", config.id, config.name)
    return BaseAgentClient(
        config=config,
        system_prompt=system_prompt,
        options=options,
        redis_a2a=redis_a2a,
        skills_signature=ctx.get("skills_signature", ""),
    )


def _build_mcp_servers(
    config: AgentConfig,
    workspace_path: Path,
    redis_a2a=None,
) -> dict[str, object]:
    """Build direct MCP servers first, then shadow-safe plugin MCP servers."""
    mcp_servers: dict[str, object] = {}
    direct_tool_names: set[str] = set()

    if config.mcp_server_factory:
        try:
            direct_server = config.mcp_server_factory(workspace_path, redis_a2a=redis_a2a)
            if direct_server is not None:
                mcp_servers[f"{config.id}-tools"] = direct_server
                direct_tool_names.update(_server_tool_names(direct_server))
        except Exception as exc:
            logger.warning("agent[%s]: mcp_server_factory failed — %s", config.id, exc)

    if config.extra_mcp_servers:
        mcp_servers.update(config.extra_mcp_servers)
        for server in config.extra_mcp_servers.values():
            direct_tool_names.update(_server_tool_names(server))

    plugin_server = _create_plugin_mcp_server(config, workspace_path, direct_tool_names)
    if plugin_server is not None:
        mcp_servers[f"{config.id}-plugin-tools"] = plugin_server

    return mcp_servers


def _server_tool_names(server: object) -> set[str]:
    return {
        str(getattr(tool, "name", "")).strip()
        for tool in (getattr(server, "_tools", None) or [])
        if str(getattr(tool, "name", "")).strip()
    }


def _create_plugin_mcp_server(
    config: AgentConfig,
    workspace_path: Path,
    direct_tool_names: set[str],
) -> object | None:
    if not config.effective_plugins_enabled:
        return None
    plugin_names = config.plugin_allowlist
    if plugin_names == ():
        return None

    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool
        from plugin_runtime.registry import tools_for_agent

        context = PluginContext(
            agent_id=config.id,
            workspace_path=workspace_path,
            config={"plugins": plugin_names},
        )
        plugin_tools = tools_for_agent(
            config.effective_plugin_root,
            config.id,
            context,
            plugin_names=plugin_names,
        )
    except Exception as exc:
        logger.warning("agent[%s]: plugin loading failed — %s", config.id, exc)
        return None

    sdk_tools = []
    registered_names = set(direct_tool_names)
    for spec in plugin_tools:
        if spec.name in registered_names:
            logger.warning(
                "agent[%s]: plugin tool %s shadows a direct tool; keeping direct tool",
                config.id,
                spec.name,
            )
            continue
        registered_names.add(spec.name)
        sdk_tools.append(_sdk_tool_from_spec(spec, sdk_tool))

    if not sdk_tools:
        return None
    return create_sdk_mcp_server(name=f"{config.id}-plugin-tools", tools=sdk_tools)


def _sdk_tool_from_spec(spec: ToolSpec, sdk_tool):
    @sdk_tool(spec.name, spec.description, spec.schema)
    async def plugin_tool(args: dict | None = None):
        result = spec.handler(args or {})
        if inspect.isawaitable(result):
            result = await result
        return result

    return plugin_tool


def _build_system_prompt(ctx: dict) -> str:
    """Assemble the full system prompt from workspace context dict."""
    sections = [
        ("factual_evidence_contract", "Factual Evidence Contract"),
        ("soul", "Identity & Soul"),
        ("memory_guard", "Memory Freshness Guard"),
        ("open_loops", "Open Loop Registry"),
        ("watchpoints", "Watchpoint Registry"),
        ("agents", "Operating Manual"),
        ("user", "About Your User"),
        ("identity", "Self-Image"),
        ("memory", "Long-Term Memory"),
        ("dreams", "Dream Log"),
        ("daily", "Today's Memory Log"),
        ("yesterday", "Yesterday's Memory Log"),
        ("tools_md", "Tool Conventions"),
        ("skills", "Skills"),
        ("heartbeat", "Scheduled Tasks"),
        ("architecture", "Technical Architecture"),
    ]
    parts = []
    ctx = {"factual_evidence_contract": _FACTUAL_EVIDENCE_CONTRACT, **ctx}
    for key, heading in sections:
        if ctx.get(key):
            parts.append(f"## {heading}\n\n{ctx[key]}")
    return "\n\n---\n\n".join(parts)
