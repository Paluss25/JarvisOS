"""Redis cache for nutrition API lookups."""

import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

TTL_FATSECRET = 86400       # 24 hours
TTL_OPENFOODFACTS = 604800  # 7 days
TTL_USDA = 86400            # 24 hours


class NutritionCache:
    def __init__(self):
        self._redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        self._redis = None

    async def _ensure_connected(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)

    @staticmethod
    def _make_key(provider: str, query: str) -> str:
        raw = f"{provider}:{query}".lower()
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"nutrition:cache:{h}"

    async def get(self, provider: str, query: str) -> dict | None:
        await self._ensure_connected()
        key = self._make_key(provider, query)
        data = await self._redis.get(key)
        if data:
            logger.debug("cache HIT: %s:%s", provider, query)
            return json.loads(data)
        return None

    async def set(self, provider: str, query: str, result: dict):
        await self._ensure_connected()
        key = self._make_key(provider, query)
        ttl = {"fatsecret": TTL_FATSECRET, "openfoodfacts": TTL_OPENFOODFACTS, "usda": TTL_USDA}.get(provider, TTL_FATSECRET)
        await self._redis.setex(key, ttl, json.dumps(result, default=str))

    async def invalidate(self, provider: str, query: str):
        await self._ensure_connected()
        key = self._make_key(provider, query)
        await self._redis.delete(key)
