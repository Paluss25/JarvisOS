# src/agent_runner/client.py
"""Generic agent client — wraps ClaudeSDKClient behind a stable interface.

ClaudeSDKClient maintains a *persistent* subprocess connection (spawned once
at startup), so each message avoids the ~4s Node.js boot cost.  It runs in
streaming mode by default.
"""

import asyncio
import logging
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

from src.agent_runner.config import AgentConfig
from src.agent_runner.memory.daily_logger import DailyLogger

logger = logging.getLogger(__name__)


class BaseAgentClient:
    """Persistent Claude SDK subprocess connection.

    Usage (managed by the FastAPI lifespan):
        client = create_agent_client(config)
        await client.connect()
        text = await client.query(msg)
        async for chunk in client.stream(msg): ...
        await client.disconnect()
    """

    def __init__(self, config: AgentConfig, system_prompt: str, options: ClaudeAgentOptions) -> None:
        self.config = config
        self.name = config.name
        self._system_prompt = system_prompt
        self._options = options
        self._sdk: ClaudeSDKClient | None = None
        self._lock = asyncio.Lock()
        self._daily = DailyLogger(config.workspace_path)

    # -- Lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
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
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        text_parts.append(text)
                        return False
        elif hasattr(msg, "content") and msg.content:
            for block in msg.content:
                if hasattr(block, "text") and block.text:
                    text_parts.append(block.text)

        if isinstance(msg, ResultMessage):
            try:
                self._daily.log(
                    f"[COST] ${msg.total_cost_usd:.4f} | {msg.duration_ms}ms"
                    f" | turns={msg.num_turns}"
                )
            except Exception:
                pass
            return True
        return False

    # -- Public interface ---------------------------------------------------

    async def query(self, message: str, session_id: str | None = None) -> str:
        if not self._sdk:
            raise RuntimeError(f"{self.name} not connected")
        async with self._lock:
            try:
                await self._sdk.query(message, session_id=session_id or "default")
            except Exception as exc:
                logger.warning("agent[%s]: subprocess error on query — %s", self.config.id, exc)
                await self._reconnect()
                await self._sdk.query(message, session_id=session_id or "default")
            text_parts: list[str] = []
            async for msg in self._sdk.receive_response():
                if self._process_message(msg, text_parts):
                    break
        return "".join(text_parts)

    async def stream(self, message: str, session_id: str | None = None):
        if not self._sdk:
            raise RuntimeError(f"{self.name} not connected")
        async with self._lock:
            try:
                await self._sdk.query(message, session_id=session_id or "default")
            except Exception as exc:
                logger.warning("agent[%s]: subprocess error on stream — %s", self.config.id, exc)
                await self._reconnect()
                await self._sdk.query(message, session_id=session_id or "default")
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
        async with self._lock:
            try:
                await self._sdk.query(_prompt_stream(), session_id=session_id or "default")
            except Exception as exc:
                logger.warning("agent[%s]: subprocess error on stream_image — %s", self.config.id, exc)
                await self._reconnect()
                await self._sdk.query(_prompt_stream(), session_id=session_id or "default")
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
                dummy2: list[str] = []
                if self._process_message(msg, dummy2):
                    break


def create_agent_client(config: AgentConfig) -> "BaseAgentClient":
    """Build and return a configured BaseAgentClient (not yet connected)."""
    from src.agent_runner.memory.workspace_loader import load_workspace_context

    workspace_path = config.workspace_path
    ctx = load_workspace_context(workspace_path)
    system_prompt = _build_system_prompt(ctx)

    # MCP servers
    mcp_servers = {}
    if config.mcp_server_factory:
        try:
            mcp_servers = {f"{config.id}-tools": config.mcp_server_factory(workspace_path)}
        except Exception as exc:
            logger.warning("agent[%s]: mcp_server_factory failed — %s", config.id, exc)

    # Permission hook + SDK hooks
    can_use_tool = None
    sdk_hooks: dict = {}
    try:
        from src.agent_runner.hooks.permission_hook import build_can_use_tool
        from src.agent_runner.hooks.sdk_hooks import build_all_hooks

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
    return BaseAgentClient(config=config, system_prompt=system_prompt, options=options)


def _build_system_prompt(ctx: dict) -> str:
    """Assemble the full system prompt from workspace context dict."""
    sections = [
        ("soul", "Identity & Soul"),
        ("agents", "Operating Manual"),
        ("user", "About Your User"),
        ("identity", "Self-Image"),
        ("memory", "Long-Term Memory"),
        ("daily", "Today's Memory Log"),
        ("yesterday", "Yesterday's Memory Log"),
        ("tools_md", "Tool Conventions"),
        ("heartbeat", "Scheduled Tasks"),
        ("architecture", "Technical Architecture"),
    ]
    parts = []
    for key, heading in sections:
        if ctx.get(key):
            parts.append(f"## {heading}\n\n{ctx[key]}")
    return "\n\n---\n\n".join(parts)
