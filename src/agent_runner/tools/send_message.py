"""send_message MCP tool — generic inter-agent communication via Redis + HTTP fallback.

Three delivery modes:

- ``mode='sync'`` + ``wait_response=True``  (default, backward-compatible)
  → publishes a ``request`` envelope, awaits the receiver's correlated
  ``response``, returns the response text. Blocks the sender's turn for up
  to ~120s (240–300s for don/dos). Use ONLY for data needed *now* to
  continue reasoning in the same turn.

- ``mode='async'`` → publishes a ``request`` envelope, persists pending state
  in Redis (``a2a:pending:<cid>`` HASH), returns INSTANTLY with an
  ``[Async dispatched cid=...]`` ack. When the receiver eventually replies,
  the response handler routes the payload as a continuation envelope into
  the sender's own InboxQueue, triggering a new turn. Use for long tasks
  (>30s) and anything that doesn't strictly need the answer in this turn.

- ``wait_response=False`` (legacy notification) → publishes a ``notification``
  envelope. Receiver's drain loop folds it into a batched turn. No
  correlation, no continuation. Used for FYI copies and morning briefings.
"""

import asyncio
import logging
import os
import time
import uuid

import httpx

from agent_runner.comms.chain_context import read_chain_context
from agent_runner.comms.inbox import InboxQueue
from agent_runner.comms.message import A2AMessage
from agent_runner.comms.pending_store import PendingEntry, PendingResponseStore
from agent_runner.comms.redis_pubsub import RedisA2A
from agent_runner.registry import get_agent_entry

logger = logging.getLogger(__name__)

_RESPONSE_TIMEOUT = 120  # seconds (default)
# Agents that use thinking-mode LLMs + multi-step DB writes need more time.
_AGENT_TIMEOUTS: dict[str, float] = {
    "don": 300.0,   # NutritionDirector: thinking mode + multiple nutrition_execute calls
    "dos": 240.0,   # DirectorOfSport: training plan generation + DB writes
}

# Async chain loop guard. The tool refuses to dispatch a new async send when
# ``hop_count >= MAX_HOPS``, so an unbounded CEO→CIO→COS→… cascade cannot
# build up. Override per-deployment via env (e.g. set lower for testing).
MAX_HOPS = int(os.environ.get("JARVIOS_A2A_MAX_HOPS", "5"))


def _coerce_mode(value, default: str = "sync") -> str:
    """Normalize the ``mode`` arg to one of {'sync', 'async'}."""
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("sync", "async"):
            return v
    return default


def _truncate(s: str | None, limit: int) -> str | None:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _build_continuation_envelope(
    self_id: str, entry: PendingEntry, response: A2AMessage
) -> A2AMessage:
    """Build the continuation envelope that gets pushed onto the sender's own
    inbox when an async response arrives. The drain loop will fold this
    (along with any other queued items) into a fresh agent turn.

    The envelope is self-contained: original request, recipient, reply text,
    correlation chain, and (if set) the caller's original context hint. The
    receiving agent doesn't need any state from the original turn.
    """
    parts = [
        f"[A2A-CONTINUATION] You previously sent an async request "
        f"(cid={entry.correlation_id[:8]}, "
        f"root={(entry.root_correlation_id or entry.correlation_id)[:8]}, "
        f"hop={entry.hop_count}/{entry.max_hops}).",
        f"Recipient: {entry.to_agent}",
        f"Original request: {entry.original_message}",
    ]
    if entry.context_hint:
        parts.append(f"Your original context note: {entry.context_hint}")
    parts.append(f"--- Reply from {response.from_agent} ---")
    parts.append(response.payload)
    parts.append("--- End of reply ---")
    parts.append(
        "Continue your work using this information. Do NOT re-send the same "
        "async request. If further work is needed, call the next tool or "
        "send the next message; otherwise summarise the result."
    )
    return A2AMessage(
        # Logical from = the responder; to = ourselves. We piggyback on the
        # existing notification path because the inbox drain loop already
        # batches non-request envelopes into a single follow-up turn.
        from_agent=response.from_agent,
        to_agent=self_id,
        type="notification",
        payload="\n".join(parts),
        correlation_id=entry.correlation_id,
        mode="async",
        root_correlation_id=entry.root_correlation_id or entry.correlation_id,
        parent_correlation_id=entry.correlation_id,
        hop_count=entry.hop_count,
        max_hops=entry.max_hops,
        # Reply-routing for the originator-authored feedback loop.
        reply_channel=entry.reply_channel,
        reply_chat_id=entry.reply_chat_id,
        reply_intent=entry.reply_intent,
    )


def _coerce_bool(value, default: bool = True) -> bool:
    """Best-effort bool coercion — MCP arg dicts often arrive with string values."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "y", "on"):
            return True
        if v in ("false", "0", "no", "n", "off"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def create_send_message_tool(
    agent_id: str,
    redis_a2a: RedisA2A,
    pending_store: PendingResponseStore | None = None,
    inbox: InboxQueue | None = None,
):
    """Return the send_message async function bound to this agent's transport.

    The returned function is suitable for registration with the MCP sdk_tool
    decorator. By default it sends a request and waits for a correlated
    response (legacy sync mode). Pass ``wait_response=False`` for one-way
    notifications, or ``mode='async'`` for fire-and-continue.

    Args:
        agent_id: This agent's ID (used as ``from_agent`` in the envelope).
        redis_a2a: Shared RedisA2A instance (already connected in lifespan).
        pending_store: Required to use ``mode='async'``. Persists pending
            state in Redis HASH so continuations survive sender restarts.
            If None, falls back to ``redis_a2a._pending_store`` (set by
            :mod:`agent_runner.app` lifespan) — letting agent factories
            keep their two-arg signature.
        inbox: Required to deliver continuation envelopes. Falls back to
            ``redis_a2a._inbox`` for the same reason.
    """
    # Auto-discover from the redis_a2a instance if the factory didn't pass
    # them explicitly (the agent-side factories all use the legacy
    # two-argument call shape). app.py wires these attrs in lifespan.
    if pending_store is None:
        pending_store = getattr(redis_a2a, "_pending_store", None)
    if inbox is None:
        inbox = getattr(redis_a2a, "_inbox", None)
    # Pending futures keyed by correlation_id — resolved by the response callback.
    # Each entry stores (future, expected_from) so we can verify the response
    # actually came from the target agent we addressed.
    _pending: dict[str, tuple[asyncio.Future, str]] = {}
    # Cooldown: after *consecutive* timeouts on an agent, skip subsequent calls
    # for a short window so Claude doesn't retry 5+ times at 120s each. A single
    # transient timeout no longer suppresses follow-up requests.
    _timeout_count: dict[str, int] = {}
    _timeout_ts: dict[str, float] = {}
    _COOLDOWN_S: float = 15.0
    _COOLDOWN_MIN_FAILS: int = 2

    async def _handle_response(msg: A2AMessage) -> None:
        """Callback registered with redis_a2a — routes responses two ways:

        1. ``mode='async'`` (durable pending HASH claim) → push a continuation
           envelope into our own inbox so the next drain triggers a new turn
           with the receiver's reply as context.
        2. ``mode='sync'`` (in-memory Future) → resolve the awaiter so the
           current send_message call returns the payload.

        Atomic claim from the pending store guarantees exactly-one
        continuation per response, even if Redis pub/sub redelivers.
        """
        if msg.type != "response" or not msg.correlation_id:
            return

        # ----- Async path: durable pending → continuation envelope -----
        if pending_store is not None:
            entry = await pending_store.claim(msg.correlation_id)
            if entry is not None and entry.mode == "async":
                if entry.from_agent != agent_id:
                    # Pending was for someone else; we shouldn't have claimed it.
                    # Defensive: best-effort restore is racy, so just warn.
                    logger.warning(
                        "send_message[%s]: claimed pending cid=%.8s but "
                        "from_agent=%s ≠ self — leaking continuation",
                        agent_id, msg.correlation_id, entry.from_agent,
                    )
                if inbox is None:
                    logger.warning(
                        "send_message[%s]: cid=%.8s response arrived but "
                        "inbox is None — dropping continuation",
                        agent_id, msg.correlation_id,
                    )
                    return
                continuation = _build_continuation_envelope(
                    self_id=agent_id, entry=entry, response=msg
                )
                try:
                    await inbox.push(continuation)
                    logger.info(
                        "send_message[%s]: cid=%.8s async response from %s "
                        "→ pushed continuation envelope (hop=%d, root=%.8s)",
                        agent_id, msg.correlation_id, msg.from_agent,
                        entry.hop_count,
                        entry.root_correlation_id or "n/a",
                    )
                except Exception as exc:
                    logger.error(
                        "send_message[%s]: cid=%.8s failed to push "
                        "continuation envelope — %s",
                        agent_id, msg.correlation_id, exc,
                    )
                return

        # ----- Sync path: in-memory Future resolution (legacy) -----
        fut_entry = _pending.get(msg.correlation_id)
        if fut_entry is None:
            return
        fut, expected_from = fut_entry
        if msg.from_agent != expected_from:
            logger.warning(
                "send_message[%s]: response with cid=%.8s from '%s' "
                "but expected '%s' — discarding",
                agent_id, msg.correlation_id, msg.from_agent, expected_from,
            )
            return
        if not fut.done():
            fut.set_result(msg.payload)

    redis_a2a.on_message(_handle_response)

    async def send_message(args: dict) -> str:
        """Send a message to another agent.

        Args (in dict):
            to: Target agent ID (e.g. "dos", "ceo").
            message: Natural language message to send.
            mode: ``'sync'`` (default) blocks the current turn until the target
                replies (or 120–300s timeout). ``'async'`` returns instantly
                with an ack; the reply arrives later as a new turn with the
                full context. Use async for tasks >30s.
            wait_response: legacy flag. ``False`` sends a one-way notification
                (no correlation, no continuation). Mutually exclusive with
                ``mode='async'``.
            context_hint: optional, max ~500 chars. Persisted with the pending
                entry and surfaced in the continuation prompt to remind the
                agent why it sent the request.
        Returns:
            On ``mode='async'``: ``"[Async dispatched cid=<8> → <to>]"``.
            On ``mode='sync'``+``wait_response=True``: the target's response.
            On ``wait_response=False``: ``"[Sent notification <id> to <to>]"``.
            On error: a string starting with ``"Error: "``.
        """
        to = (args.get("to") or "").strip()
        message = (args.get("message") or "").strip()
        wait_response = _coerce_bool(args.get("wait_response"), default=True)
        mode = _coerce_mode(args.get("mode"), default="sync")
        if not to:
            return "Error: 'to' (target agent ID) is required."
        if not message:
            return "Error: 'message' is required."

        # Mutual exclusion: async mode IS request/response, just decoupled
        # from the sender's turn. wait_response=False is the legacy
        # notification path with no correlation at all.
        if mode == "async" and not wait_response:
            return (
                "Error: mode='async' is incompatible with wait_response=False. "
                "Use mode='async' (correlated, continuation-routed) OR "
                "wait_response=False (one-way notification), not both."
            )

        # ----- Async fire-and-continue path -----
        if mode == "async":
            if pending_store is None or inbox is None:
                return (
                    "Error: async mode unavailable — pending_store/inbox "
                    "not wired in this build. Use mode='sync' or "
                    "wait_response=False."
                )
            chain = read_chain_context()
            # Chain may now be a partial dict (e.g. only reply_channel /
            # reply_chat_id, set at the START of a user-facing turn) — use
            # ``.get()`` with safe defaults instead of subscript access.
            current_hop = int(chain.get("hop_count", 0)) if chain else 0
            if current_hop >= MAX_HOPS:
                root = chain.get("root_correlation_id") if chain else None
                return (
                    f"Error: async chain hop limit ({MAX_HOPS}) reached "
                    f"(root={(root or 'n/a')[:8]}). "
                    "Aborting to prevent runaway cascade. Reply directly "
                    "instead of dispatching another async send."
                )
            correlation_id = str(uuid.uuid4())
            new_hop = current_hop + 1
            root_cid = (chain.get("root_correlation_id") if chain else None) or correlation_id
            parent_cid = chain.get("parent_correlation_id") if chain else None
            envelope = A2AMessage(
                from_agent=agent_id, to_agent=to,
                type="request", payload=message,
                correlation_id=correlation_id,
                mode="async",
                root_correlation_id=root_cid,
                parent_correlation_id=parent_cid,
                hop_count=new_hop,
                max_hops=MAX_HOPS,
            )
            # Reply-routing fields. Inherit from the chain context (a nested
            # async send started from a continuation turn keeps the original
            # user's reply channel) unless the caller explicitly overrides
            # them in args. Empty strings collapse to None.
            def _arg_or_chain(arg_name: str, chain_key: str) -> str | None:
                v = args.get(arg_name)
                if isinstance(v, str):
                    v = v.strip() or None
                if v is not None:
                    return v
                if chain is None:
                    return None
                cv = chain.get(chain_key)
                if isinstance(cv, str):
                    return cv or None
                return cv
            reply_channel = _arg_or_chain("reply_channel", "reply_channel")
            reply_chat_id = _arg_or_chain("reply_chat_id", "reply_chat_id")
            reply_intent = _arg_or_chain("reply_intent", "reply_intent")
            # Auto-resolve reply_chat_id from agent config when the LLM set
            # reply_channel='telegram' but didn't pass a chat_id. Each agent
            # has exactly one Telegram chat (its allowed_chat_id), so this
            # is unambiguous and removes the LLM's burden of remembering it.
            # ContextVar from _stream_to_agent doesn't reach here because the
            # SDK's tool-dispatch task is spawned at agent.connect() time
            # (before the per-turn chain context is set).
            if reply_channel == "telegram" and not reply_chat_id:
                _cfg = getattr(redis_a2a, "_config", None)
                if _cfg is not None and _cfg.telegram_chat_id_env:
                    _resolved = _cfg._resolve(_cfg.telegram_chat_id_env)
                    if _resolved:
                        reply_chat_id = _resolved
                        logger.debug(
                            "send_message[%s→%s]: auto-resolved reply_chat_id "
                            "from config (telegram_chat_id_env=%s)",
                            agent_id, to, _cfg.telegram_chat_id_env,
                        )
            envelope.reply_channel = reply_channel
            envelope.reply_chat_id = reply_chat_id
            envelope.reply_intent = reply_intent
            entry = PendingEntry(
                correlation_id=correlation_id,
                from_agent=agent_id, to_agent=to,
                original_message=message,
                sent_at=time.time(),
                mode="async",
                root_correlation_id=root_cid,
                hop_count=new_hop,
                max_hops=MAX_HOPS,
                context_hint=_truncate(args.get("context_hint"), 500),
                reply_channel=reply_channel,
                reply_chat_id=str(reply_chat_id) if reply_chat_id is not None else None,
                reply_intent=reply_intent,
            )
            try:
                await pending_store.put(entry)
            except Exception as exc:
                logger.warning(
                    "send_message[%s→%s]: pending_store.put failed (%s)",
                    agent_id, to, exc,
                )
                return f"Error: async dispatch failed (pending store): {exc}"
            try:
                await redis_a2a.publish(envelope)
            except Exception as exc:
                # Pending entry stays — sender startup scan or TTL handles it.
                logger.warning(
                    "send_message[%s→%s]: async publish failed (%s) — "
                    "pending entry retained for cleanup",
                    agent_id, to, exc,
                )
                return f"Error: async publish failed: {exc}"
            return (
                f"[Async dispatched cid={correlation_id[:8]} → {to}. "
                "Continue your turn; the reply will arrive as a new turn "
                "with full context.]"
            )

        msg_type = "request" if wait_response else "notification"

        # Fire-and-forget path: publish and return immediately. No timeouts to
        # track, no pending future, no cooldown logic — the sender's p95 is
        # decoupled from the receiver's turn duration.
        if not wait_response:
            correlation_id = str(uuid.uuid4())
            msg = A2AMessage(
                from_agent=agent_id,
                to_agent=to,
                type=msg_type,
                payload=message,
                correlation_id=correlation_id,
            )
            try:
                await redis_a2a.publish(msg)
                return f"[Sent notification {msg.id[:8]} to {to}]"
            except Exception as exc:
                logger.warning(
                    "send_message[%s→%s]: notification publish failed (%s)",
                    agent_id, to, exc,
                )
                return f"Error: could not deliver notification to '{to}': {exc}"

        # Request/response path (legacy behaviour, fully preserved).
        # Fast-fail only after a *streak* of timeouts. A single transient
        # 120s timeout no longer suppresses unrelated follow-up requests.
        last_timeout = _timeout_ts.get(to)
        if last_timeout is not None and _timeout_count.get(to, 0) >= _COOLDOWN_MIN_FAILS:
            elapsed = time.monotonic() - last_timeout
            if elapsed < _COOLDOWN_S:
                return (
                    f"Error: agent '{to}' is unreachable "
                    f"(timed out {elapsed:.0f}s ago, cooldown active). "
                    "Proceed without this data."
                )
            # Cooldown expired — clear streak and try again.
            _timeout_ts.pop(to, None)
            _timeout_count.pop(to, None)

        correlation_id = str(uuid.uuid4())
        msg = A2AMessage(
            from_agent=agent_id,
            to_agent=to,
            type=msg_type,
            payload=message,
            correlation_id=correlation_id,
        )

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        _pending[correlation_id] = (future, to)

        try:
            await redis_a2a.publish(msg)
        except Exception as exc:
            # Redis not available — fall back to HTTP POST to target agent's /a2a endpoint
            _pending.pop(correlation_id, None)
            logger.warning(
                "send_message[%s→%s]: Redis publish failed (%s), trying HTTP fallback",
                agent_id, to, exc,
            )
            entry = get_agent_entry(to)
            if not entry:
                return f"Error: agent '{to}' not found in registry."
            port = entry["port"]
            _timeout = _AGENT_TIMEOUTS.get(to, _RESPONSE_TIMEOUT)
            try:
                async with httpx.AsyncClient(timeout=_timeout) as client:
                    resp = await client.post(
                        f"http://localhost:{port}/a2a",
                        json={"from_agent": agent_id, "message": message},
                    )
                    resp.raise_for_status()
                    return resp.json().get("response", "")
            except Exception as http_exc:
                return f"Error: could not reach agent '{to}' via HTTP: {http_exc}"

        _timeout = _AGENT_TIMEOUTS.get(to, _RESPONSE_TIMEOUT)
        try:
            result = await asyncio.wait_for(future, timeout=_timeout)
            # Reset failure streak on success.
            _timeout_count.pop(to, None)
            _timeout_ts.pop(to, None)
            return result
        except asyncio.TimeoutError:
            _timeout_ts[to] = time.monotonic()
            _timeout_count[to] = _timeout_count.get(to, 0) + 1
            return f"Error: agent '{to}' did not respond within {_timeout:.0f}s."
        finally:
            _pending.pop(correlation_id, None)

    return send_message
