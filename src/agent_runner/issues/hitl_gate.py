# agent_runner/issues/hitl_gate.py
"""hitl_gate — thin dispatch module for CIO HITL Telegram callbacks.

Mirrors the pattern of agent_runner/hooks/permission_hook.py:
  configure()          — called by telegram_bot.start_polling() to inject bot functions
  register_resolve()   — called by HITLQueue.__init__() to wire its resolve method
  resolve()            — called by Telegram ^issue: callback handler
  send_task_message()  — sends a Telegram message with Approve/Reject inline keyboard
  send_notification()  — sends a plain Telegram text notification

Non-CIO agents: configure() may not be called. resolve() and send_* log warnings and
return gracefully — they never raise.
"""
import logging

logger = logging.getLogger(__name__)

_send_task_fn = None       # coroutine: (text, task_id) → None  — sends inline keyboard msg
_send_plain_fn = None      # coroutine: (text) → None           — sends plain text msg
_resolve_fn = None         # sync: (task_id: str, approved: bool) → None


def configure(send_task_fn, send_plain_fn) -> None:
    """Inject bot functions from telegram_bot.start_polling(). CIO only."""
    global _send_task_fn, _send_plain_fn
    _send_task_fn = send_task_fn
    _send_plain_fn = send_plain_fn
    logger.info("hitl_gate: configured")


def register_resolve(resolve_fn) -> None:
    """Register the HITLQueue.resolve callback. Called from HITLQueue.__init__()."""
    global _resolve_fn
    _resolve_fn = resolve_fn
    logger.info("hitl_gate: resolve function registered")


def resolve(task_id: str, approved: bool) -> None:
    """Called by Telegram callback handler when user taps Accetta/Rifiuta."""
    if _resolve_fn is None:
        logger.warning("hitl_gate: resolve called but not registered (task_id=%s)", task_id)
        return
    _resolve_fn(task_id, approved)


async def send_task_message(text: str, task_id: str) -> None:
    """Send a Telegram message with [✅ Accetta] [❌ Rifiuta] inline keyboard."""
    if _send_task_fn is None:
        logger.warning("hitl_gate: send_task_fn not configured — skipping Telegram send")
        return
    try:
        await _send_task_fn(text, task_id)
    except Exception as exc:
        logger.error("hitl_gate: send_task_message failed — %s", exc)


async def send_notification(text: str) -> None:
    """Send a plain Telegram notification."""
    if _send_plain_fn is None:
        logger.warning("hitl_gate: send_plain_fn not configured — skipping Telegram send")
        return
    try:
        await _send_plain_fn(text)
    except Exception as exc:
        logger.error("hitl_gate: send_notification failed — %s", exc)
