"""OpenTelemetry tracing and Prometheus metrics for JarvisOS agents.

Traces:  OTel SDK → OTLP gRPC → Alloy (.139:4317) → Tempo (.202:4317)
Metrics: prometheus_client → /metrics on each agent port → Prometheus scrapes
Logs:    trace_id injected into every log record → Alloy ships to Loki → Tempo correlation
"""

import logging
import os

from opentelemetry import trace
from opentelemetry.trace import StatusCode
from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

# ── Prometheus metrics ───────────────────────────────────────────────────────
# One registry per supervisord process — each agent's /metrics is isolated.

LLM_CALLS = Counter(
    "jarvios_llm_calls_total",
    "Total LLM calls",
    ["agent_id", "source", "status"],
)

LLM_COST = Counter(
    "jarvios_llm_cost_usd_total",
    "Cumulative LLM spend in USD",
    ["agent_id"],
)

LLM_DURATION = Histogram(
    "jarvios_llm_duration_seconds",
    "LLM turn wall-clock time",
    ["agent_id", "source"],
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600],
)

AGENT_BUSY = Gauge(
    "jarvios_agent_busy",
    "1 while the agent is processing a turn",
    ["agent_id"],
)

# ── OpenTelemetry setup ──────────────────────────────────────────────────────

_setup_done = False


def setup_telemetry(service_name: str) -> None:
    """Configure OTel TracerProvider. Call once per agent process at startup.

    Reads OTEL_EXPORTER_OTLP_ENDPOINT from env (set in docker-compose.yml to
    http://10.10.200.139:4317). No-op if the var is unset.
    """
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        logger.info("telemetry: OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing disabled")
        return

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({
            "service.name": service_name,
            "service.version": "0.2.0",
        })
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrument all outgoing httpx calls (Telegram, A2A HTTP, Loki, etc.)
        HTTPXClientInstrumentor().instrument()

        logger.info("telemetry: OTel traces → %s  service=%s", endpoint, service_name)
    except Exception as exc:
        logger.warning("telemetry: OTel setup failed (%s) — continuing without traces", exc)


def get_tracer(name: str):
    """Return an OTel tracer. Returns the no-op tracer if OTel is not configured."""
    return trace.get_tracer(name)


def record_llm_turn(
    agent_id: str,
    source: str,
    cost_usd: float,
    duration_ms: int,
    status: str = "ok",
) -> None:
    """Update Prometheus counters/histograms for a completed LLM turn."""
    try:
        LLM_CALLS.labels(agent_id=agent_id, source=source, status=status).inc()
        if cost_usd:
            LLM_COST.labels(agent_id=agent_id).inc(cost_usd)
        if duration_ms:
            LLM_DURATION.labels(agent_id=agent_id, source=source).observe(duration_ms / 1000.0)
    except Exception:
        pass


# ── Logging — trace context injection ───────────────────────────────────────

_logging_configured = False


class _TraceContextFilter(logging.Filter):
    """Injects OTel trace_id into every log record for Loki→Tempo correlation.

    When a span is active the full 32-char hex trace_id is embedded so Loki's
    Derived Fields regex can extract it and link to Tempo automatically.
    When no span is active, injects a zero sentinel so the format string stays
    valid without branching in formatter code.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            ctx = trace.get_current_span().get_span_context()
            record.trace_id = format(ctx.trace_id, "032x") if (ctx and ctx.is_valid) else "0" * 32
        except Exception:
            record.trace_id = "0" * 32
        return True


def configure_logging(log_level: str = "INFO") -> None:
    """Inject trace_id into log records and update the root logger format.

    Call once per process after logging.basicConfig(). Updates the formatter
    on every existing root-level handler to include trace_id so Alloy ships
    it to Loki, enabling clickable Tempo trace links in Grafana.
    """
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True

    root = logging.getLogger()
    level = getattr(logging, log_level.upper(), logging.INFO)
    root.setLevel(level)

    # Attach filter to each handler, not to the logger itself.
    # Python's callHandlers() propagation skips parent logger filters — only
    # handler.handle() calls handler.filter(record).  Attaching here ensures
    # trace_id is injected before the formatter runs regardless of which child
    # logger originated the record.
    filter_ = _TraceContextFilter()
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)-30s traceID=%(trace_id)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for handler in root.handlers:
        handler.addFilter(filter_)
        handler.setFormatter(fmt)
