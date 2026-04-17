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
