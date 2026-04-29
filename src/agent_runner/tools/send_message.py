"""send_message MCP tool — generic inter-agent communication via Redis + HTTP fallback."""

import asyncio
import logging
import time
import uuid

import httpx

from agent_runner.comms.message import A2AMessage
from agent_runner.comms.redis_pubsub import RedisA2A
from agent_runner.registry import get_agent_entry

logger = logging.getLogger(__name__)

_RESPONSE_TIMEOUT = 120  # seconds (default)
# Agents that use thinking-mode LLMs + multi-step DB writes need more time.
_AGENT_TIMEOUTS: dict[str, float] = {
    "don": 300.0,   # NutritionDirector: thinking mode + multiple nutrition_execute calls
    "dos": 240.0,   # DirectorOfSport: training plan generation + DB writes
}


def create_send_message_tool(agent_id: str, redis_a2a: RedisA2A):
    """Return the send_message async function bound to this agent's Redis transport.

    The returned function is suitable for registration with the MCP sdk_tool decorator.
    It sends a request message via Redis pub/sub and awaits a correlated response.
    Falls back to HTTP POST if Redis publish fails (e.g. Redis not available).

    Args:
        agent_id: This agent's ID (used as from_agent in the envelope).
        redis_a2a: Shared RedisA2A instance (already connected in lifespan).
    """
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
        """Callback registered with redis_a2a — resolves pending request futures."""
        if msg.type != "response":
            return
        entry = _pending.get(msg.correlation_id)
        if entry is None:
            return
        fut, expected_from = entry
        if msg.from_agent != expected_from:
            # Stray response with a colliding correlation_id from another agent.
            # Drop it instead of resolving the wrong future.
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
        """Send a message to another agent and wait for their response.

        Args (in dict):
            to: Target agent ID (e.g. "dos", "ceo")
            message: Natural language message to send
        Returns:
            The target agent's response text, or an error string.
        """
        to = (args.get("to") or "").strip()
        message = (args.get("message") or "").strip()
        if not to:
            return "Error: 'to' (target agent ID) is required."
        if not message:
            return "Error: 'message' is required."

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
            type="request",
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
