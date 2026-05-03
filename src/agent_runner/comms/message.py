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
