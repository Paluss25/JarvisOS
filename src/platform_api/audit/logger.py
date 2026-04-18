"""AuditLogger — dual-sink audit logging (PostgreSQL + structured JSON stdout)."""

import json
import logging
import sys

from platform_api.audit.models import AuditEvent
from platform_api.db import get_pool

logger = logging.getLogger(__name__)


class AuditLogger:
    """Singleton audit logger. Inject into agent runner + platform endpoints."""

    async def log(self, event: AuditEvent) -> None:
        # 1. Structured JSON to stdout (picked up by Grafana Alloy)
        self._log_stdout(event)

        # 2. Async PostgreSQL INSERT
        try:
            pool = await get_pool()
            await pool.execute(
                """INSERT INTO audit_log (ts, category, agent_id, user_id, action, detail, source)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)""",
                event.ts,
                event.category,
                event.agent_id,
                event.user_id,
                event.action,
                json.dumps(event.detail),
                event.source,
            )
        except Exception as exc:
            logger.warning("audit: PG insert failed — %s", exc)

    def _log_stdout(self, event: AuditEvent) -> None:
        line = json.dumps(
            {
                "ts": event.ts.isoformat(),
                "level": "info",
                "logger": "audit",
                "category": event.category,
                "agent_id": event.agent_id,
                "user_id": event.user_id,
                "action": event.action,
                "source": event.source,
                "detail": event.detail,
            },
            separators=(",", ":"),
        )
        print(line, file=sys.stdout, flush=True)


# Module-level singleton — import and use directly: `from platform_api.audit import audit`
audit = AuditLogger()
