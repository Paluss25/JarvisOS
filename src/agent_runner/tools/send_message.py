"""send_message MCP tool — generic inter-agent communication via Redis + HTTP fallback."""

import asyncio
import logging
import uuid

import httpx

from agent_runner.comms.message import A2AMessage
from agent_runner.comms.redis_pubsub import RedisA2A
from agent_runner.registry import get_agent_entry

logger = logging.getLogger(__name__)

_RESPONSE_TIMEOUT = 120  # seconds


def create_send_message_tool(agent_id: str, redis_a2a: RedisA2A):
    """Return the send_message async function bound to this agent's Redis transport.

    The returned function is suitable for registration with the MCP sdk_tool decorator.
    It sends a request message via Redis pub/sub and awaits a correlated response.
    Falls back to HTTP POST if Redis publish fails (e.g. Redis not available).

    Args:
        agent_id: This agent's ID (used as from_agent in the envelope).
        redis_a2a: Shared RedisA2A instance (already connected in lifespan).
    """
    # Pending futures keyed by correlation_id — resolved by the response callback
    _pending: dict[str, asyncio.Future] = {}

    async def _handle_response(msg: A2AMessage) -> None:
        """Callback registered with redis_a2a — resolves pending request futures."""
        if msg.type == "response" and msg.correlation_id in _pending:
            fut = _pending[msg.correlation_id]
            if not fut.done():
                fut.set_result(msg.payload)

    redis_a2a.on_message(_handle_response)

    async def send_message(args: dict) -> str:
        """Send a message to another agent and wait for their response.

        Args (in dict):
            to: Target agent ID (e.g. "roger", "jarvis")
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
        _pending[correlation_id] = future

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
            try:
                async with httpx.AsyncClient(timeout=_RESPONSE_TIMEOUT) as client:
                    resp = await client.post(
                        f"http://localhost:{port}/a2a",
                        json={"from_agent": agent_id, "message": message},
                    )
                    resp.raise_for_status()
                    return resp.json().get("response", "")
            except Exception as http_exc:
                return f"Error: could not reach agent '{to}' via HTTP: {http_exc}"

        try:
            result = await asyncio.wait_for(future, timeout=_RESPONSE_TIMEOUT)
            return result
        except asyncio.TimeoutError:
            return f"Error: agent '{to}' did not respond within {_RESPONSE_TIMEOUT}s."
        finally:
            _pending.pop(correlation_id, None)

    return send_message
