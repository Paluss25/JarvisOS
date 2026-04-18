"""asyncpg connection pool for the Polymarket database (postgres-shared / polymarket db).

POLYMARKET_DATABASE_URL env var must point to the `polymarket` database, e.g.:
  postgresql://user:pass@postgres-shared:5432/polymarket

Variable name matches the K8s finance-agent-secrets SealedSecret key.
"""

import os
from typing import Any

import asyncpg

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = os.environ.get("POLYMARKET_DATABASE_URL", "")
        if not dsn:
            raise RuntimeError("POLYMARKET_DATABASE_URL is not configured")
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    return _pool


async def fetch(query: str, *args: Any) -> list[dict]:
    """Execute a SELECT query and return rows as dicts."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(r) for r in rows]


async def fetchrow(query: str, *args: Any) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None
