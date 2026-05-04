"""A2A message envelope."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class A2AMessage:
    from_agent: str
    to_agent: str
    type: str                          # "request", "response", "notification"
    payload: str                       # natural language message
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str | None = None  # links request → response
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    # Async fire-and-continue routing (default values preserve sync behaviour
    # bit-for-bit so legacy publishers/subscribers are unaffected).
    mode: str = "sync"                          # "sync" | "async"
    root_correlation_id: str | None = None      # first cid in the chain (set on first async send, propagated)
    parent_correlation_id: str | None = None    # cid that triggered this message (None for the root)
    hop_count: int = 0                          # incremented per async send; bounded by max_hops
    max_hops: int = 5                           # tool rejects new async sends when hop_count >= max_hops
    # Reply-routing metadata: copied verbatim from the originator's PendingEntry
    # onto the continuation envelope so the drain loop can hydrate chain_context.
    # See projects/jarvios-async-feedback-loop/2026-05-03-jarvios-async-feedback-loop.md
    reply_channel: str | None = None            # "telegram" | "slack" | "mattermost" | "cron" | None
    reply_chat_id: str | None = None            # external channel id (Telegram chat id as string)
    reply_intent: str | None = None             # short label, e.g. "tennis_event_inserted"
