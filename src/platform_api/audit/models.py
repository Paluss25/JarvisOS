"""Audit event data model."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AuditEvent:
    category: str          # agent | platform | security | memory | task
    action: str            # message_received | tool_called | login_success | ...
    source: str            # telegram | dashboard | a2a | scheduler | api
    agent_id: str | None = None
    user_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
