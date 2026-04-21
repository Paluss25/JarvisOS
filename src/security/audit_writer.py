from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class AuditEvent:
    event_id: str
    event_type: str
    timestamp: str
    agent_id: str
    action: str
    outcome: str
    target_id: Optional[str] = None
    resource_type: Optional[str] = None
    reason_codes: List[str] = field(default_factory=list)
    model_route: Optional[str] = None
    model_id: Optional[str] = None
    cloud_used: Optional[bool] = None
    redaction_applied: Optional[bool] = None
    approval_token_id: Optional[str] = None
    email_id: Optional[str] = None
    thread_id: Optional[str] = None
    hash_refs: Dict[str, Optional[str]] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)


class AuditWriter:
    FORBIDDEN_DETAIL_KEYS = {
        "raw_email_body",
        "raw_attachment_text",
        "attachment_binary",
        "credentials",
        "system_prompt",
    }

    def __init__(self, audit_log_path: str | Path) -> None:
        self.audit_log_path = Path(audit_log_path)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: AuditEvent) -> None:
        sanitized = self._sanitize_event(event)
        with self.audit_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sanitized, ensure_ascii=False) + "\n")

    def make_event(self, **kwargs: Any) -> AuditEvent:
        return AuditEvent(timestamp=datetime.now(timezone.utc).isoformat(), **kwargs)

    def _sanitize_event(self, event: AuditEvent) -> Dict[str, Any]:
        payload = asdict(event)
        details = payload.get("details", {})
        payload["details"] = {k: v for k, v in details.items() if k not in self.FORBIDDEN_DETAIL_KEYS}
        return payload
