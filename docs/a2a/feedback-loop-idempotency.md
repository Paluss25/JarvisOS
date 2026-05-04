# `send_telegram_message` idempotency contract

This document specifies the behaviour of the idempotency lock that guards
`send_telegram_message` — the originator-authored Telegram feedback tool
that closes the loop after an async A2A delegation.

Source: `src/agent_runner/tools/send_telegram_message.py`. See also
`projects/jarvios-async-feedback-loop/2026-05-03-jarvios-async-feedback-loop.md`.

## Why a lock is needed

The continuation envelope that triggers `send_telegram_message` arrives via
the inbox drain loop. The drain loop has two recovery mechanisms that can
re-fire the same continuation:

- `requeue_with_retry` — transient `agent.query()` failures cause the
  continuation envelope to be re-pushed onto `a2a:inbox:<agent>` (up to 2
  retries by default).
- Dead-letter replay — operators can re-inject envelopes from
  `a2a:dead-letter:<agent>` into the inbox via the `a2a_dead_letter.py`
  CLI.

Without a lock, each replay would post a duplicate Telegram message to the
user, producing the *exact* UX the feedback loop is meant to prevent.

## Lock primitive

Each successful continuation send claims a Redis key:

- **Key**: `a2a:feedback-sent:<parent_correlation_id>`
- **Set primitive**: `SET <key> 1 NX EX 86400` — *atomic claim, 24 h TTL*
- **TTL**: 24 hours (matches `PendingResponseStore` default)

The `parent_correlation_id` comes from the `chain_context` populated by
the drain loop. It is the cid of the original `send_message(mode='async')`
that started the delegation, so a single delegation maps to exactly one
lock regardless of how many times its continuation envelope drains.

## Behaviour matrix

| Scenario | Lock state before call | Action | Lock state after call | Tool response |
|----------|------------------------|--------|------------------------|----------------|
| First call, send succeeds (markdown) | absent | Bot.send_message OK | present (TTL 24 h) | `[Telegram message sent ... markdown]` |
| First call, markdown rejected → plain-text fallback OK | absent | 2× Bot.send_message | present (TTL 24 h) | `[Telegram message sent ... plain text fallback]` |
| First call, 429 → retry succeeds | absent | sleep(retry_after) + Bot.send_message | present (TTL 24 h) | `[Telegram message sent ... after Ns rate-limit wait]` |
| First call, send fails (network, plain-text fallback also fails) | absent | Bot.send_message raises | **absent** (released) | `Error: telegram send failed: …` |
| Token env unset | absent | claim made, then released | **absent** (released) | `Error: telegram token env '…' is not set.` |
| Replay: lock already present | present (`1`) | no Bot call | present (untouched) | `[Telegram feedback already sent for cid=… — no-op (idempotency guard)]` |

The "release on failure" path is what allows operator-driven retry: if a
genuine send failure occurs, the lock is dropped so a future drain (or a
manual replay) can succeed.

## Manual operations

### Inspect a lock

```bash
docker exec jarvios-redis redis-cli -a "$REDIS_PASSWORD" \
  GET "a2a:feedback-sent:<parent_correlation_id>"
docker exec jarvios-redis redis-cli -a "$REDIS_PASSWORD" \
  TTL "a2a:feedback-sent:<parent_correlation_id>"
```

### Force a re-send

If a continuation arrived, was acked, but the user reports they did not
receive the Telegram message (e.g. Telegram outage at the moment of
send), drop the lock and replay the envelope:

```bash
# 1. Drop the lock
docker exec jarvios-redis redis-cli -a "$REDIS_PASSWORD" \
  DEL "a2a:feedback-sent:<parent_correlation_id>"

# 2. Re-publish the continuation envelope (it must still be in the
#    dead-letter list, or you must reconstruct it).
python3 scripts/a2a_dead_letter.py requeue --agent <agent_id> \
        --correlation-id <parent_correlation_id>
```

### List all live locks

```bash
docker exec jarvios-redis redis-cli -a "$REDIS_PASSWORD" \
  --scan --pattern "a2a:feedback-sent:*"
```

## Invariants

1. **At most one Telegram send per delegation**: enforced by the `SET NX`
   primitive and the contextvar that uniquely identifies the delegation
   (`parent_correlation_id`).
2. **TTL ≥ pending entry TTL**: 24 h matches `PendingResponseStore`. A
   delegation whose pending entry expires unsuccessfully cannot have its
   feedback loop fired anyway.
3. **No silent drops on send failure**: the lock is released so the
   operator (or the next replay) can retry.
4. **No leakage across delegations**: the key is keyed by the unique
   `parent_correlation_id`; two distinct delegations have distinct locks.

## Test coverage

See `tests/test_send_telegram_message.py`:
- `test_refuses_when_idempotency_key_already_set` — replay refusal.
- `test_happy_path_markdown` — lock persists on success.
- `test_send_failure_releases_idempotency_lock` — lock released on raise.
- `test_refuses_when_token_env_unset` — lock released when no token.
