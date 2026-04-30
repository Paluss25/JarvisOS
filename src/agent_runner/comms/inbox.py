"""Redis-backed A2A inbox for ack-then-batch notification delivery.

Notifications (``send_message`` with ``wait_response=False``) are pushed to a
per-agent Redis list instead of triggering an immediate LLM turn on the
receiver. A periodic drain consumer in the agent's lifespan reads the entire
backlog atomically and folds it into a single batched prompt.

Why this matters:
- Decouples receiver LLM cost from notification arrival rate. Five concurrent
  briefings → one batched turn instead of five serial turns (or five parallel
  turns each consuming tokens).
- Eliminates the "busy drop" loss: notifications arriving while the agent is
  mid-turn are queued, not silently discarded.
- Preserves ordering: messages are drained chronologically.
- Crash-safe: notifications survive a container restart because Redis persists
  the list.
"""

import json
import logging
from dataclasses import asdict

import redis.asyncio as aioredis

from agent_runner.comms.message import A2AMessage

logger = logging.getLogger(__name__)


class InboxQueue:
    """Redis LIST-backed inbox for one agent.

    Storage layout:
        Key:   ``a2a:inbox:<agent_id>``
        Type:  Redis LIST
        Items: JSON-serialised :class:`A2AMessage` envelopes

    The producer (the A2A receive callback) does ``LPUSH``; the consumer
    (the drain loop) atomically does ``LRANGE 0 -1`` + ``DEL`` in a single
    transactional pipeline so messages enqueued mid-drain are not lost.
    """

    def __init__(self, agent_id: str, redis_client: aioredis.Redis):
        self.agent_id = agent_id
        self._redis = redis_client
        self._key = f"a2a:inbox:{agent_id}"

    async def push(self, msg: A2AMessage) -> int:
        """Append a notification envelope. Returns the new queue length."""
        payload = json.dumps(asdict(msg))
        new_len = await self._redis.lpush(self._key, payload)
        logger.debug(
            "inbox[%s]: pushed notif from %s (len=%d)",
            self.agent_id, msg.from_agent, new_len,
        )
        return new_len

    async def length(self) -> int:
        """Return the number of pending notifications."""
        return await self._redis.llen(self._key)

    async def drain(self) -> list[A2AMessage]:
        """Atomically read and clear the full inbox.

        Returns messages in chronological order (oldest first).
        """
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.lrange(self._key, 0, -1)
            pipe.delete(self._key)
            raw_list, _ = await pipe.execute()
        out: list[A2AMessage] = []
        # LPUSH stores newest at index 0 — reverse for chronological order.
        for raw in reversed(raw_list):
            try:
                data = json.loads(raw)
                out.append(A2AMessage(**data))
            except Exception as exc:
                logger.warning(
                    "inbox[%s]: skipping malformed entry — %s",
                    self.agent_id, exc,
                )
        return out
