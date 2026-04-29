"""Loki HTTP query_range client for ops-detector.

Queries Loki's /loki/api/v1/query_range endpoint for a given LogQL expression
over the last N minutes. Returns matched log lines as plain strings.

All errors are caught and logged — the detector must stay running even when
Loki is temporarily unreachable.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)


def _loki_url() -> str:
    return os.environ.get("LOKI_URL", "http://10.10.200.71:3100")


async def query_loki(logql: str, lookback_minutes: int, limit: int = 100) -> list[str]:
    """Execute a LogQL query against Loki and return matched log lines.

    Each returned string has the format: "2026-04-19T14:32:01Z  <log message>"

    Returns an empty list on any network or parse error.
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=lookback_minutes)

    params = {
        "query": logql,
        "start": str(int(start.timestamp() * 1_000_000_000)),  # nanoseconds
        "end": str(int(now.timestamp() * 1_000_000_000)),
        "limit": str(limit),
        "direction": "backward",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_loki_url()}/loki/api/v1/query_range",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("detector: Loki query timed out (logql=%s)", logql[:60])
        return []
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "detector: Loki HTTP %d — %s", exc.response.status_code, logql[:60]
        )
        return []
    except Exception as exc:
        logger.warning("detector: Loki error — %s", exc)
        return []

    lines: list[str] = []
    for stream in data.get("data", {}).get("result", []):
        for ts_ns, msg in stream.get("values", []):
            ts = datetime.fromtimestamp(
                int(ts_ns) / 1_000_000_000, tz=timezone.utc
            ).isoformat()
            lines.append(f"{ts}  {msg}")

    return lines
