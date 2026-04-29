"""worker-ops-detector — entry point.

Runs two concurrent tasks in the same event loop:
  1. An aiohttp HTTP server on DETECTOR_PORT (default 8013) that accepts
     Grafana webhook alerts at POST /alert.
  2. A background poll loop that queries Loki every DETECTOR_POLL_INTERVAL
     seconds and publishes matching patterns to Redis channel a2a:cio.

Redis payload format matches A2AMessage (agent_runner.comms.message):
  {from_agent, to_agent, type, payload, id, correlation_id, timestamp}
The inner `payload` field is a JSON string with the structured alert data.
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from aiohttp import web

from workers.ops_detector.dedup import DedupTracker
from workers.ops_detector.detector import query_loki
from workers.ops_detector.patterns import Pattern, load_patterns

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

_POLL_INTERVAL = int(os.environ.get("DETECTOR_POLL_INTERVAL", "300"))
_LOOKBACK_MINUTES = int(os.environ.get("DETECTOR_LOOKBACK_MINUTES", "10"))
_PORT = int(os.environ.get("DETECTOR_PORT", "8013"))


def _redis_kwargs() -> dict:
    """Build kwargs for redis.asyncio.from_url()."""
    url = os.environ.get("REDIS_URL", "")
    password = os.environ.get("REDIS_PASSWORD", "")
    if not url or not (url.startswith("redis://") or url.startswith("rediss://")):
        host = os.environ.get("REDIS_HOST", "localhost")
        port = os.environ.get("REDIS_PORT", "6379")
        url = f"redis://{host}:{port}"
    kwargs: dict = {"decode_responses": True}
    if password:
        kwargs["password"] = password
    return {"url": url, "kwargs": kwargs}


def _build_a2a_message(pattern_id: str, severity: str,
                        matched_lines: list[str], runbook: str) -> str:
    """Serialise an A2AMessage-compatible dict for Redis publish."""
    inner = json.dumps({
        "source": "ops-detector",
        "pattern_id": pattern_id,
        "severity": severity,
        "matched_lines": matched_lines[:20],
        "runbook": runbook,
        "fired_at": datetime.now(timezone.utc).isoformat(),
    })
    msg = {
        "from_agent": "ops-detector",
        "to_agent": "cio",
        "type": "request",
        "payload": inner,
        "id": str(uuid.uuid4()),
        "correlation_id": None,
        "timestamp": datetime.utcnow().isoformat(),
    }
    return json.dumps(msg)


async def _publish(pattern_id: str, severity: str,
                   matched_lines: list[str], runbook: str) -> None:
    """Publish alert to Redis channel a2a:cio."""
    cfg = _redis_kwargs()
    if not cfg["url"]:
        logger.warning("detector: REDIS_URL not configured — skipping publish")
        return
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(cfg["url"], **cfg["kwargs"])
        try:
            payload = _build_a2a_message(pattern_id, severity, matched_lines, runbook)
            await r.publish("a2a:cio", payload)
            logger.info(
                "detector: published alert pattern_id=%s (%d lines)",
                pattern_id, len(matched_lines),
            )
        finally:
            await r.aclose()
    except Exception as exc:
        logger.error("detector: Redis publish error — %s", exc)


async def _poll_loop(tracker: DedupTracker) -> None:
    """Run the detection loop: load patterns, query Loki, publish on match."""
    logger.info(
        "detector: poll loop started (interval=%ds, lookback=%dm, port=%d)",
        _POLL_INTERVAL, _LOOKBACK_MINUTES, _PORT,
    )
    while True:
        try:
            patterns = load_patterns()
            for pattern in patterns:
                if not tracker.is_allowed(pattern.id, pattern.cooldown_minutes):
                    continue
                lines = await query_loki(pattern.logql, _LOOKBACK_MINUTES)
                if lines:
                    logger.info(
                        "detector: MATCH pattern=%s severity=%s lines=%d",
                        pattern.id, pattern.severity, len(lines),
                    )
                    tracker.record(pattern.id)
                    await _publish(pattern.id, pattern.severity, lines, pattern.runbook)
        except Exception as exc:
            logger.error("detector: poll loop error — %s", exc, exc_info=True)
        await asyncio.sleep(_POLL_INTERVAL)


async def _handle_alert(request: web.Request) -> web.Response:
    """POST /alert — Grafana unified alerting webhook receiver."""
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text="invalid json")

    for alert in body.get("alerts", []):
        name = alert.get("labels", {}).get("alertname", "unknown")
        state = alert.get("status", "unknown")
        severity = "high" if state == "firing" else "low"
        logger.info("detector: Grafana alert name=%s state=%s", name, state)
        await _publish(
            pattern_id=f"grafana_{name}",
            severity=severity,
            matched_lines=[f"Grafana alert '{name}' is {state}"],
            runbook="",
        )

    return web.Response(status=200, text="ok")


async def _handle_health(request: web.Request) -> web.Response:
    return web.Response(status=200, text="ok")


async def main() -> None:
    tracker = DedupTracker()

    app = web.Application()
    app.router.add_post("/alert", _handle_alert)
    app.router.add_get("/health", _handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", _PORT)
    await site.start()
    logger.info("detector: HTTP server listening on :%d", _PORT)

    poll_task = asyncio.create_task(_poll_loop(tracker))
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
