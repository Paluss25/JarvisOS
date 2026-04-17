"""Async permission hook + SDK hooks for agent runners.

Provides:
  - can_use_tool callback: gates destructive Bash commands via Telegram approval
  - build_pre_tool_use_matchers(): SDK PreToolUse hook → daily memory log
  - build_notification_matchers(): SDK Notification hook → Telegram message
  - build_post_tool_use_matchers(): SDK PostToolUse hook → daily memory log
  - build_post_tool_use_failure_matchers(): SDK PostToolUseFailure hook → memory + Telegram alert
  - build_stop_matchers(): SDK Stop hook → daily memory log
  - build_subagent_start_matchers(): SDK SubagentStart hook → daily memory log
  - build_subagent_stop_matchers(): SDK SubagentStop hook → daily memory log
  - build_user_prompt_submit_matchers(): SDK UserPromptSubmit hook → daily memory log
  - build_pre_compact_matchers(): SDK PreCompact hook → daily memory log
"""
import asyncio
import logging
import re
import uuid
from pathlib import Path

from claude_agent_sdk import (
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120

# ---------------------------------------------------------------------------
# Active-tool state — updated by PreToolUse/PostToolUse hooks so the Telegram
# status task can show the user what the agent is currently doing.
# ---------------------------------------------------------------------------

_active_tool: str = ""

# Base tool labels — agents can extend by setting additional entries here or
# by providing extra_tool_labels to build_pre_tool_use_matchers().
_BASE_TOOL_LABELS: dict[str, str] = {
    "Bash":        "executing command",
    "Read":        "reading file",
    "Write":       "writing file",
    "Edit":        "editing file",
    "WebSearch":   "searching the web",
    "WebFetch":    "loading page",
    "daily_log":   "logging memory",
}


def get_active_tool() -> str:
    """Return the human-readable label of the currently-running tool, or ''."""
    return _active_tool


# Read-only command prefixes (these auto-allow without prompting)
_SAFE_PREFIXES = {
    "ls", "cat", "head", "tail", "grep", "find", "df", "du", "ps",
    "free", "uptime", "echo", "pwd", "wc", "env",
    "docker ps", "docker logs", "docker inspect", "docker images",
    "kubectl get", "kubectl describe", "kubectl logs",
    "git status", "git log", "git diff", "git show",
    "ping", "curl", "dig", "nslookup",
    "systemctl status", "journalctl",
}

_SHELL_META = re.compile(r'[;&|`<>]|\$\(')


def _is_safe(command: str) -> bool:
    cmd = command.strip()
    if not any(cmd == p or cmd.startswith(p + " ") for p in _SAFE_PREFIXES):
        return False
    return not bool(_SHELL_META.search(cmd))


# Pending approval requests: request_id → asyncio.Event
_pending: dict[str, asyncio.Event] = {}
_results: dict[str, bool] = {}

# Injected at runtime by telegram_bot.start_polling()
_send_approval_message = None   # coroutine: (text, request_id) → None
_send_notification = None       # coroutine: (text) → None
_allowed_chat_id: int | None = None


def configure_hook(send_fn, allowed_chat_id: int, notify_fn=None) -> None:
    """Wire the hook to the Telegram bot. Called from telegram_bot.start_polling()."""
    global _send_approval_message, _send_notification, _allowed_chat_id
    _send_approval_message = send_fn
    _send_notification = notify_fn
    _allowed_chat_id = allowed_chat_id
    logger.info("permission_hook: configured (chat_id=%s)", allowed_chat_id)


def resolve(request_id: str, approved: bool) -> None:
    """Unblock a pending approval request. Called from Telegram callback handler."""
    if request_id in _pending:
        _results[request_id] = approved
        _pending[request_id].set()
    else:
        logger.warning("permission_hook: resolve called for unknown request_id=%s", request_id)


# ---------------------------------------------------------------------------
# can_use_tool callback
# ---------------------------------------------------------------------------

def build_can_use_tool():
    """Return the can_use_tool async callback for ClaudeAgentOptions."""

    async def can_use_tool(tool_name: str, input_data: dict, context) -> PermissionResultAllow | PermissionResultDeny:
        # Only gate the Bash tool; all others auto-allow
        if tool_name != "Bash":
            return PermissionResultAllow()

        command = input_data.get("command", "")
        if _is_safe(command):
            return PermissionResultAllow()

        # Destructive command — request Telegram approval
        if _send_approval_message is None:
            logger.warning("permission_hook: not configured — auto-denying destructive command")
            return PermissionResultDeny(message="Permission system not configured")

        request_id = uuid.uuid4().hex[:8]
        event = asyncio.Event()
        _pending[request_id] = event

        snippet = command[:800] + ("…" if len(command) > 800 else "")
        text = (
            f"*Permission Required*\n\n"
            f"*Tool:* `{tool_name}`\n\n"
            f"```\n{snippet}\n```"
        )
        try:
            await _send_approval_message(text, request_id)
        except Exception as exc:
            logger.warning("permission_hook: failed to send approval request — %s", type(exc).__name__)
            _pending.pop(request_id, None)
            return PermissionResultDeny(message="Could not send approval request")

        try:
            await asyncio.wait_for(event.wait(), timeout=_DEFAULT_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("permission_hook: request %s timed out after %ds", request_id, _DEFAULT_TIMEOUT)
            _pending.pop(request_id, None)
            _results.pop(request_id, None)
            return PermissionResultDeny(message="Approval timed out")

        approved = _results.pop(request_id, False)
        _pending.pop(request_id, None)
        logger.info("permission_hook: request %s → %s", request_id, "approved" if approved else "denied")
        return PermissionResultAllow() if approved else PermissionResultDeny(message="User denied")

    return can_use_tool


# ---------------------------------------------------------------------------
# SDK hook builders — return HookMatcher lists for ClaudeAgentOptions.hooks
# ---------------------------------------------------------------------------

def build_pre_tool_use_matchers(
    workspace_path: Path,
    extra_tool_labels: dict[str, str] | None = None,
) -> list[HookMatcher]:
    """PreToolUse hook event → daily memory log + active tool update for Telegram UI."""
    tool_labels = {**_BASE_TOOL_LABELS, **(extra_tool_labels or {})}

    async def _log_pre(input_data, tool_use_id: str | None, context) -> dict:
        global _active_tool
        tool_name = input_data.get("tool_name", "?")
        tool_input = input_data.get("tool_input", {})

        _active_tool = tool_labels.get(tool_name, tool_name)

        if tool_name == "Bash":
            summary = tool_input.get("command", "")[:120]
        elif tool_name in ("Read", "Write", "Edit"):
            summary = tool_input.get("file_path", "") or tool_input.get("path", "")
        elif tool_name in ("WebSearch", "WebFetch"):
            summary = tool_input.get("query", "") or tool_input.get("url", "")[:80]
        else:
            summary = str(tool_input)[:80]

        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(f"[PRE_TOOL] {tool_name}: {summary}")
        except Exception:
            pass
        return {}

    return [HookMatcher(hooks=[_log_pre])]


def build_notification_matchers() -> list[HookMatcher]:
    """Notification hook event → Telegram message."""
    async def _notify(input_data, tool_use_id: str | None, context) -> dict:
        message = input_data.get("message", "")
        title = input_data.get("title", "")
        if not message:
            return {}
        if _send_notification is None:
            logger.debug("notification_hook: Telegram not configured — skipping")
            return {}
        text = f"*{title}*\n\n{message}" if title else message
        try:
            await _send_notification(text)
        except Exception as exc:
            logger.warning("notification_hook: send failed — %s", exc)
        return {}

    return [HookMatcher(hooks=[_notify])]


def build_post_tool_use_matchers(workspace_path: Path) -> list[HookMatcher]:
    """PostToolUse hook event → daily memory log + active tool clear."""
    async def _log_tool(input_data, tool_use_id: str | None, context) -> dict:
        global _active_tool
        _active_tool = ""
        tool_name = input_data.get("tool_name", "?")
        tool_input = input_data.get("tool_input", {})

        if tool_name == "Bash":
            summary = tool_input.get("command", "")[:120]
        elif tool_name in ("Read", "Write", "Edit"):
            summary = tool_input.get("file_path", "") or tool_input.get("path", "")
        elif tool_name in ("WebSearch", "WebFetch"):
            summary = tool_input.get("query", "") or tool_input.get("url", "")[:80]
        else:
            summary = str(tool_input)[:80]

        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(f"[TOOL] {tool_name}: {summary}")
        except Exception:
            pass
        return {}

    return [HookMatcher(hooks=[_log_tool])]


def build_post_tool_use_failure_matchers(workspace_path: Path) -> list[HookMatcher]:
    """PostToolUseFailure hook event → daily memory log + Telegram alert."""
    async def _log_failure(input_data, tool_use_id: str | None, context) -> dict:
        global _active_tool
        _active_tool = ""
        tool_name = input_data.get("tool_name", "?")
        error = str(input_data.get("error", "unknown error"))
        tool_input = input_data.get("tool_input", {})

        if tool_name == "Bash":
            cmd = tool_input.get("command", "")[:80]
            summary = f"{cmd!r} → {error[:120]}"
        else:
            summary = error[:160]

        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(f"[TOOL_FAIL] {tool_name}: {summary}")
        except Exception:
            pass

        if _send_notification:
            try:
                await _send_notification(
                    f"*Tool failed:* `{tool_name}`\n```\n{error[:300]}\n```"
                )
            except Exception as exc:
                logger.warning("post_tool_use_failure_hook: notify failed — %s", exc)
        return {}

    return [HookMatcher(hooks=[_log_failure])]


def build_stop_matchers(workspace_path: Path) -> list[HookMatcher]:
    """Stop hook event → daily memory log."""
    async def _log_stop(input_data, tool_use_id: str | None, context) -> dict:
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log("[STOP] Agent session stopped")
        except Exception:
            pass
        return {}

    return [HookMatcher(hooks=[_log_stop])]


def build_subagent_start_matchers(workspace_path: Path) -> list[HookMatcher]:
    """SubagentStart hook event → daily memory log."""
    async def _log_start(input_data, tool_use_id: str | None, context) -> dict:
        agent_type = input_data.get("agent_type", "?")
        agent_id = input_data.get("agent_id", "?")
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(
                f"[SUBAGENT_START] type={agent_type} id={str(agent_id)[:8]}"
            )
        except Exception:
            pass
        return {}

    return [HookMatcher(hooks=[_log_start])]


def build_subagent_stop_matchers(workspace_path: Path) -> list[HookMatcher]:
    """SubagentStop hook event → daily memory log."""
    async def _log_stop(input_data, tool_use_id: str | None, context) -> dict:
        agent_type = input_data.get("agent_type", "?")
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(f"[SUBAGENT_STOP] type={agent_type}")
        except Exception:
            pass
        return {}

    return [HookMatcher(hooks=[_log_stop])]


def build_user_prompt_submit_matchers(workspace_path: Path) -> list[HookMatcher]:
    """UserPromptSubmit hook event → daily memory log (prompt preview)."""
    async def _log_prompt(input_data, tool_use_id: str | None, context) -> dict:
        prompt = input_data.get("prompt", "")
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(f"[USER] {prompt[:160]}")
        except Exception:
            pass
        return {}

    return [HookMatcher(hooks=[_log_prompt])]


def build_pre_compact_matchers(workspace_path: Path) -> list[HookMatcher]:
    """PreCompact hook event → daily memory log."""
    async def _on_compact(input_data, tool_use_id: str | None, context) -> dict:
        trigger = input_data.get("trigger", "?")
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(
                f"[COMPACT] Context compaction triggered (trigger={trigger})"
            )
        except Exception:
            pass
        return {}

    return [HookMatcher(hooks=[_on_compact])]
