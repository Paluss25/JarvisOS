"""Durable pending-response store for async A2A.

Stores per-correlation-id metadata so the sender can route the eventual
response into a continuation envelope. Survives sender restarts because the
state lives in Redis (HASH ``a2a:pending:<cid>`` with TTL).

Atomic claim is implemented via a Lua script that does ``HGETALL`` + ``DEL``
in a single Redis round-trip, guaranteeing exactly-once continuation even if
the response is delivered twice (e.g. pub/sub reconnect, duplicate publish).
"""

import logging
import time
from dataclasses import asdict, dataclass

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Atomic claim: returns the full hash if present (and deletes it), else nil.
_CLAIM_LUA = """
local v = redis.call('HGETALL', KEYS[1])
if #v == 0 then return nil end
redis.call('DEL', KEYS[1])
return v
"""


@dataclass
class PendingEntry:
    """Metadata persisted while an async A2A request is in flight.

    All scalar values are str-coerced when written to Redis (Redis HASH stores
    only bytes/strings); :meth:`PendingResponseStore.claim` reverses the cast.
    """

    correlation_id: str
    from_agent: str
    to_agent: str
    original_message: str
    sent_at: float                       # epoch seconds — used by stale-scan
    mode: str = "async"
    root_correlation_id: str | None = None
    hop_count: int = 0
    max_hops: int = 5
    sender_session_id: str | None = None
    sender_user_id: str | None = None
    context_hint: str | None = None      # max ~500 chars of caller context


class PendingResponseStore:
    """Redis HASH wrapper for pending async A2A requests.

    Layout:
        Key  : ``a2a:pending:<correlation_id>``
        Type : Redis HASH
        TTL  : ``default_ttl_s`` (default 24h) — pending entries auto-expire
               so a missed response cannot leak forever.
    """

    def __init__(self, redis_client: aioredis.Redis, default_ttl_s: int = 86_400):
        self._r = redis_client
        self._ttl = default_ttl_s
        # Pre-register the Lua script. The first call to the returned object
        # uses EVAL; subsequent calls use EVALSHA, which is cheap.
        self._claim_script = self._r.register_script(_CLAIM_LUA)

    @staticmethod
    def _key(correlation_id: str) -> str:
        return f"a2a:pending:{correlation_id}"

    async def put(self, entry: PendingEntry) -> None:
        """Persist ``entry`` and set its TTL atomically.

        HSET + EXPIRE are pipelined inside a transaction so partial state
        cannot leak: either both succeed or neither does.
        """
        key = self._key(entry.correlation_id)
        # Redis HASH cannot store None — coerce to empty string. Caller code
        # in :meth:`claim` re-coerces empty strings back to None for
        # ``str | None`` fields.
        mapping = {k: ("" if v is None else str(v)) for k, v in asdict(entry).items()}
        async with self._r.pipeline(transaction=True) as p:
            p.hset(key, mapping=mapping)
            p.expire(key, self._ttl)
            await p.execute()

    async def claim(self, correlation_id: str) -> PendingEntry | None:
        """Atomic get-and-delete by correlation_id.

        Returns the entry on success and removes it from the store. If another
        consumer already claimed the entry — or it was never written / has
        expired — returns ``None``. This is the primitive that guarantees
        exactly-once continuation envelope creation.
        """
        result = await self._claim_script(keys=[self._key(correlation_id)])
        if not result:
            return None
        kv = self._flat_to_dict(result)
        return self._entry_from_dict(kv)

    async def peek(self, correlation_id: str) -> PendingEntry | None:
        """Read without claiming. For diagnostics / startup scan only.

        Production code MUST use :meth:`claim`; ``peek + later delete`` is
        racy and breaks the exactly-once guarantee.
        """
        data = await self._r.hgetall(self._key(correlation_id))
        if not data:
            return None
        return self._entry_from_dict(data)

    async def scan_stale(
        self, agent_id: str, older_than_s: float
    ) -> list[PendingEntry]:
        """List pending entries addressed to ``agent_id`` older than the cutoff.

        Used at receiver startup to drain stale requests with error responses
        (a request whose receiver crashed mid-processing must not hang the
        sender forever — see P4.T1).
        """
        now = time.time()
        out: list[PendingEntry] = []
        async for key in self._r.scan_iter(match="a2a:pending:*", count=100):
            data = await self._r.hgetall(key)
            if not data:
                continue
            if data.get("to_agent") != agent_id:
                continue
            try:
                sent_at = float(data.get("sent_at", "0") or 0)
            except ValueError:
                continue
            if now - sent_at < older_than_s:
                continue
            out.append(self._entry_from_dict(data))
        return out

    async def delete(self, correlation_id: str) -> bool:
        """Remove an entry without claiming. Returns True if it existed."""
        deleted = await self._r.delete(self._key(correlation_id))
        return bool(deleted)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flat_to_dict(flat: list) -> dict:
        """Lua HGETALL returns ``[k1, v1, k2, v2, ...]``; collapse to a dict."""
        return {flat[i]: flat[i + 1] for i in range(0, len(flat), 2)}

    @staticmethod
    def _entry_from_dict(data: dict) -> PendingEntry:
        def _opt(key: str) -> str | None:
            v = data.get(key)
            return v if v else None

        return PendingEntry(
            correlation_id=data["correlation_id"],
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            original_message=data["original_message"],
            sent_at=float(data.get("sent_at", "0") or 0),
            mode=data.get("mode", "async") or "async",
            root_correlation_id=_opt("root_correlation_id"),
            hop_count=int(data.get("hop_count", "0") or 0),
            max_hops=int(data.get("max_hops", "5") or 5),
            sender_session_id=_opt("sender_session_id"),
            sender_user_id=_opt("sender_user_id"),
            context_hint=_opt("context_hint"),
        )
