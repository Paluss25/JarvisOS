"""Async A2A chain context — propagates loop-guard metadata into nested sends.

When the inbox drain loop processes a continuation envelope (i.e. a previously
async-dispatched request finally got a reply and is now triggering the
sender's follow-up turn), it sets a :class:`contextvars.ContextVar` so that
any further ``send_message(mode='async')`` invoked inside that follow-up turn
inherits ``root_correlation_id`` and a bumped ``hop_count`` from the caller.

This is the only mechanism that lets the loop guard work across turn
boundaries without a global registry: ContextVar follows the asyncio task that
runs the agent.query() invocation but is invisible to other concurrent tasks.

The drain loop sets the context with :func:`set_chain_context` (and resets it
in a ``finally`` block); the send_message tool reads it via
:func:`read_chain_context`. Outside of a continuation turn the value is
``None`` and async sends start a fresh chain.
"""

from contextvars import ContextVar
from typing import TypedDict


class ChainContext(TypedDict, total=False):
    """Snapshot of A2A chain metadata visible to nested sends within one turn.

    Required keys: ``root_correlation_id``, ``parent_correlation_id``, ``hop_count``.
    Optional keys: ``reply_channel`` / ``reply_chat_id`` / ``reply_intent`` —
    populated when the original delegation came from a user channel
    (Telegram for now). Used by ``send_telegram_message`` to decide whether
    a feedback message is allowed and to which chat it should go.
    """

    root_correlation_id: str
    parent_correlation_id: str
    hop_count: int  # hop_count of the message that triggered this turn — new sends should be > this
    reply_channel: str | None
    reply_chat_id: str | None
    reply_intent: str | None


_chain_ctx: ContextVar[ChainContext | None] = ContextVar(
    "a2a_chain_ctx", default=None
)


def set_chain_context(ctx: ChainContext):
    """Set the chain context for the current asyncio task. Returns the token
    to pass back into :func:`reset_chain_context`."""
    return _chain_ctx.set(ctx)


def reset_chain_context(token) -> None:
    """Restore the chain context to its previous state."""
    _chain_ctx.reset(token)


def read_chain_context() -> ChainContext | None:
    """Read the chain context for the current task, or ``None`` if outside one."""
    return _chain_ctx.get()
