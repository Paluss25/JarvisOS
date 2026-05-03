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
from dataclasses import asdict, fields

import redis.asyncio as aioredis

from agent_runner.comms.message import A2AMessage

logger = logging.getLogger(__name__)

# Internal field stamped on the envelope's payload to track how many times an
# inbox item has been requeued after a drain failure. Stored inline (not on a
# dedicated dataclass field) so the existing notification path remains
# unchanged for non-continuation messages.
_RETRY_MARKER = "[a2a-retry={n}] "


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
        valid_fields = {f.name for f in fields(A2AMessage)}
        # LPUSH stores newest at index 0 — reverse for chronological order.
        for raw in reversed(raw_list):
            try:
                data = json.loads(raw)
                # Strip unknown fields so future schema additions on the
                # writer side don't crash an older reader.
                data = {k: v for k, v in data.items() if k in valid_fields}
                out.append(A2AMessage(**data))
            except Exception as exc:
                logger.warning(
                    "inbox[%s]: skipping malformed entry — %s",
                    self.agent_id, exc,
                )
        return out

    async def requeue_with_retry(
        self, msg: A2AMessage, max_retries: int = 2
    ) -> bool:
        """Re-enqueue a message that failed to be processed by the drain loop.

        Returns True when the message was requeued (retry budget remaining)
        and False when the retry cap has been hit (caller should send the
        message to the dead-letter queue instead). The retry counter is
        encoded inline as a leading ``[a2a-retry=N] `` marker on the payload
        so we don't need to widen the envelope schema for a transient field.
        """
        retry = 0
        prefix = ""
        # Match marker like "[a2a-retry=2] " at the very start.
        if msg.payload.startswith("[a2a-retry="):
            try:
                end = msg.payload.index("] ") + 2
                marker = msg.payload[:end]
                # marker like "[a2a-retry=2] " → extract the integer.
                retry = int(marker[len("[a2a-retry="): -2])
                prefix = marker
            except (ValueError, IndexError):
                retry = 0
                prefix = ""
        if retry >= max_retries:
            return False
        new_payload = (
            _RETRY_MARKER.format(n=retry + 1)
            + (msg.payload[len(prefix):] if prefix else msg.payload)
        )
        bumped = A2AMessage(
            **{**asdict(msg), "payload": new_payload}
        )
        await self.push(bumped)
        logger.info(
            "inbox[%s]: requeued cid=%.8s (retry=%d/%d)",
            self.agent_id, msg.correlation_id or "n/a",
            retry + 1, max_retries,
        )
        return True

    async def dead_letter(self, msg: A2AMessage) -> int:
        """Move a message that exhausted its retry budget to the per-agent
        dead-letter list. Returns the new queue length. Operators inspect
        the queue via ``redis-cli LRANGE a2a:dead-letter:<agent_id> 0 -1``
        or the helper script in :mod:`scripts.a2a_dead_letter`.
        """
        key = f"a2a:dead-letter:{self.agent_id}"
        payload = json.dumps(asdict(msg))
        new_len = await self._redis.lpush(key, payload)
        logger.warning(
            "inbox[%s]: cid=%.8s moved to dead-letter (queue len=%d)",
            self.agent_id, msg.correlation_id or "n/a", new_len,
        )
        return new_len
