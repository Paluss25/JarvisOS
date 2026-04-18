"""Redis pub/sub for inter-agent communication."""

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from agent_runner.comms.message import A2AMessage

logger = logging.getLogger(__name__)


class RedisA2A:
    """Manages Redis pub/sub subscription + publishing for one agent.

    Subscribes to ``a2a:<agent_id>`` (direct) and ``a2a:broadcast`` (all agents).
    Registered callbacks are invoked for every inbound message.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._redis: aioredis.Redis | None = None
        self._pubsub = None
        self._callbacks: list = []

    async def connect(self) -> None:
        url = os.environ.get("REDIS_URL", "")
        password = os.environ.get("REDIS_PASSWORD", "")

        # REDIS_URL must be a valid redis[s]:// URL. If it's missing or looks
        # like a bare password/hostname, build the URL from REDIS_HOST instead.
        if not url or not (url.startswith("redis://") or url.startswith("rediss://")):
            host = os.environ.get("REDIS_HOST", "localhost")
            port = os.environ.get("REDIS_PORT", "6379")
            url = f"redis://{host}:{port}"
            logger.debug("a2a[%s]: built Redis URL from REDIS_HOST=%s", self.agent_id, host)

        kwargs = {"decode_responses": True}
        if password:
            kwargs["password"] = password
        self._redis = aioredis.from_url(url, **kwargs)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(f"a2a:{self.agent_id}", "a2a:broadcast")
        logger.info("a2a[%s]: subscribed to Redis channels", self.agent_id)

    def on_message(self, callback) -> None:
        """Register an async callback ``async def cb(msg: A2AMessage) -> None``."""
        self._callbacks.append(callback)

    async def listen(self) -> None:
        """Blocking listen loop — run as an asyncio task via lifespan."""
        try:
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        msg = A2AMessage(**data)
                        for cb in self._callbacks:
                            await cb(msg)
                    except Exception as exc:
                        logger.warning("a2a[%s]: bad message — %s", self.agent_id, exc)
        except asyncio.CancelledError:
            pass
        finally:
            if self._pubsub:
                try:
                    await self._pubsub.unsubscribe()
                except Exception:
                    pass
            if self._redis:
                try:
                    await self._redis.aclose()
                except Exception:
                    pass

    async def publish(self, msg: A2AMessage) -> None:
        """Publish a message to the target agent's channel."""
        if not self._redis:
            raise RuntimeError("RedisA2A not connected — call connect() first")
        channel = f"a2a:{msg.to_agent}"
        await self._redis.publish(channel, json.dumps(msg.__dict__))
        logger.debug("a2a[%s]: published %s to %s", self.agent_id, msg.id[:8], channel)
