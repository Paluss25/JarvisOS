#!/usr/bin/env python3
"""Inspect and operate on the per-agent A2A dead-letter queue.

Continuation envelopes that fail to be processed by the inbox drain loop
2× in a row land in ``a2a:dead-letter:<agent_id>``. This script exposes
read / drain / requeue operations for ops use.

Usage:
    a2a_dead_letter.py list <agent_id>             # Print queue contents
    a2a_dead_letter.py count <agent_id>            # Print queue length
    a2a_dead_letter.py drain <agent_id>            # Discard all entries
    a2a_dead_letter.py requeue <agent_id> <index>  # Move one back to inbox

Connection settings come from the same env vars used by the platform:
    REDIS_URL        e.g. redis://127.0.0.1:6379/0
    REDIS_PASSWORD   if Redis requires AUTH

Exit codes: 0 success, 1 usage error, 2 Redis error.
"""

import argparse
import asyncio
import json
import os
import sys

import redis.asyncio as aioredis


def _redis() -> aioredis.Redis:
    url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    kwargs = {"decode_responses": True}
    pw = os.environ.get("REDIS_PASSWORD")
    if pw:
        kwargs["password"] = pw
    return aioredis.from_url(url, **kwargs)


def _dl_key(agent_id: str) -> str:
    return f"a2a:dead-letter:{agent_id}"


def _inbox_key(agent_id: str) -> str:
    return f"a2a:inbox:{agent_id}"


async def cmd_list(agent_id: str) -> int:
    r = _redis()
    try:
        items = await r.lrange(_dl_key(agent_id), 0, -1)
        if not items:
            print(f"(dead-letter queue for '{agent_id}' is empty)")
            return 0
        # Reverse so the oldest entry has index 0 (matches inbox drain order).
        for i, raw in enumerate(reversed(items)):
            try:
                env = json.loads(raw)
                cid = (env.get("correlation_id") or "n/a")[:8]
                src = env.get("from_agent", "?")
                ts = env.get("timestamp", "?")
                payload = (env.get("payload") or "")[:80].replace("\n", " ")
                print(f"[{i}] cid={cid} from={src} ts={ts}")
                print(f"    payload: {payload}…")
            except json.JSONDecodeError:
                print(f"[{i}] (malformed): {raw[:120]}")
        return 0
    finally:
        await r.aclose()


async def cmd_count(agent_id: str) -> int:
    r = _redis()
    try:
        n = await r.llen(_dl_key(agent_id))
        print(n)
        return 0
    finally:
        await r.aclose()


async def cmd_drain(agent_id: str) -> int:
    r = _redis()
    try:
        deleted = await r.delete(_dl_key(agent_id))
        print(
            f"Dead-letter queue for '{agent_id}' "
            f"{'cleared' if deleted else 'was already empty'}."
        )
        return 0
    finally:
        await r.aclose()


async def cmd_requeue(agent_id: str, index: int) -> int:
    r = _redis()
    try:
        items = await r.lrange(_dl_key(agent_id), 0, -1)
        if not items:
            print(f"Dead-letter queue for '{agent_id}' is empty.", file=sys.stderr)
            return 1
        chronological = list(reversed(items))
        if index < 0 or index >= len(chronological):
            print(
                f"Index out of range: {index} (have {len(chronological)} entries)",
                file=sys.stderr,
            )
            return 1
        raw = chronological[index]
        # LREM removes the first occurrence of the value from the list.
        removed = await r.lrem(_dl_key(agent_id), 1, raw)
        if not removed:
            print(
                "Failed to remove entry from dead-letter (concurrent modification?)",
                file=sys.stderr,
            )
            return 2
        # Strip any [a2a-retry=N] prefix so the requeued copy starts fresh.
        try:
            env = json.loads(raw)
            payload = env.get("payload", "")
            if payload.startswith("[a2a-retry="):
                end = payload.index("] ") + 2
                env["payload"] = payload[end:]
            raw = json.dumps(env)
        except (json.JSONDecodeError, ValueError):
            pass
        await r.lpush(_inbox_key(agent_id), raw)
        print(f"Requeued entry #{index} from dead-letter to inbox '{agent_id}'.")
        return 0
    finally:
        await r.aclose()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "count", "drain"):
        s = sub.add_parser(name)
        s.add_argument("agent_id")
    s = sub.add_parser("requeue")
    s.add_argument("agent_id")
    s.add_argument("index", type=int)
    args = ap.parse_args()
    if args.cmd == "list":
        coro = cmd_list(args.agent_id)
    elif args.cmd == "count":
        coro = cmd_count(args.agent_id)
    elif args.cmd == "drain":
        coro = cmd_drain(args.agent_id)
    elif args.cmd == "requeue":
        coro = cmd_requeue(args.agent_id, args.index)
    else:
        ap.error(f"unknown command: {args.cmd}")
        return 1
    return asyncio.run(coro)


if __name__ == "__main__":
    sys.exit(main())
