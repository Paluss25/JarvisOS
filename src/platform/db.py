"""AsyncPG connection pool for PostgreSQL."""

import logging
import os

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = os.environ.get("JARVIOS_POSTGRES_URL", "")
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        logger.info("db: connection pool created")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
