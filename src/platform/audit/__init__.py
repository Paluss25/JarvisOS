"""Audit logging package — dual-sink (PostgreSQL + structured JSON stdout)."""

from platform.audit.logger import AuditLogger, audit
from platform.audit.models import AuditEvent

__all__ = ["AuditLogger", "AuditEvent", "audit"]
