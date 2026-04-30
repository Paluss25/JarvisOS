# agents/cio/loki_client.py
"""Thin async clients for Loki and Prometheus HTTP APIs."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

LOKI_URL = os.environ.get("LOKI_URL", "http://10.10.200.71:3100")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "https://prometheus.prova9x.com")


class TelemetryError(Exception):
    """Raised when a Loki or Prometheus query fails due to transport or HTTP error.

    Callers should catch this to emit a single 'telemetry unavailable' issue
    rather than generating false-positive alerts for each expected target.
    """

_HTTP_TIMEOUT = 10.0
# Default to TLS verification; allow opt-out only via explicit env var for
# homelab self-signed certs. Use a CA bundle path (CIO_TLS_CA) when possible.
_VERIFY_TLS: bool | str = os.environ.get("CIO_TLS_CA") or (
    os.environ.get("CIO_VERIFY_TLS", "true").lower() not in {"false", "0", "no"}
)


class LokiClient:
    """Query the Loki HTTP API."""

    def __init__(self, base_url: str = LOKI_URL) -> None:
        self._base = base_url.rstrip("/")

    async def query_range(
        self,
        query: str,
        start_s: int,
        end_s: int,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return log stream entries for *query* between *start_s* and *end_s* (unix seconds)."""
        params = {
            "query": query,
            "start": str(start_s) + "000000000",  # nanoseconds
            "end": str(end_s) + "000000000",
            "limit": str(limit),
            "direction": "backward",
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, verify=_VERIFY_TLS) as client:
                r = await client.get(f"{self._base}/loki/api/v1/query_range", params=params)
                r.raise_for_status()
                return r.json().get("data", {}).get("result", [])
        except Exception as exc:
            logger.warning("loki_client.query_range: %s", exc)
            raise TelemetryError(str(exc)) from exc

    async def count_entries(self, query: str, lookback_seconds: int = 21600) -> int:
        """Count log entries matching *query* in the last *lookback_seconds*."""
        now = int(time.time())
        results = await self.query_range(query, now - lookback_seconds, now, limit=1)
        return sum(len(stream.get("values", [])) for stream in results)


class PrometheusClient:
    """Query the Prometheus HTTP API."""

    def __init__(self, base_url: str = PROMETHEUS_URL) -> None:
        self._base = base_url.rstrip("/")

    async def query(self, promql: str) -> list[dict[str, Any]]:
        """Run an instant PromQL query and return the result vector."""
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, verify=_VERIFY_TLS) as client:
                r = await client.get(
                    f"{self._base}/api/v1/query",
                    params={"query": promql},
                )
                r.raise_for_status()
                return r.json().get("data", {}).get("result", [])
        except Exception as exc:
            logger.warning("prometheus_client.query: %s", exc)
            raise TelemetryError(str(exc)) from exc
