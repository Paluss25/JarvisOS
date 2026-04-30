# agents/cio/issue_collector.py
"""LokiIssueCollector — detects issues by querying Loki and Prometheus.

Sources:
  - Prometheus: node_exporter `up` metric → host-level infrastructure health
  - Prometheus: cadvisor `up` metric → container daemon health per host
  - Loki: agent memory logs → silent-agent detection (no entries today)
  - Loki: aipal-runner container logs → agent-side error patterns

Returns the same (ConsolidatedIssue, medium_descriptions) tuple as the previous
file-based collector so that run_issue_collection.py needs no changes.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agents.cio.loki_client import LokiClient, PrometheusClient, TelemetryError

logger = logging.getLogger(__name__)

# Hosts scraped by node_exporter (strip port at query time)
EXPECTED_NODE_EXPORTER = [
    "10.10.200.50:9100",
    "10.10.200.51:9100",
    "10.10.200.60:9100",
    "10.10.200.61:9100",
    "10.10.200.62:9100",
    "10.10.200.139:9100",
    "10.10.200.71:9100",
]

# Agents expected to log activity every morning
EXPECTED_AGENTS = ["ceo", "cos", "email_intelligence_agent", "cfo", "coh", "dos"]

# Lookback for "has this agent logged anything today?" (8 hours)
AGENT_SILENCE_LOOKBACK_S = 8 * 3600

# Lookback for error pattern scan (6 hours)
ERROR_SCAN_LOOKBACK_S = 6 * 3600

# Minimum error occurrences before raising a medium issue
ERROR_MIN_COUNT = 3


# ── Data classes (same as before so callers are unchanged) ────────────────────

IssueType = str
IssueSeverity = str

_SEVERITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2}


def severity_rank(s: IssueSeverity) -> int:
    return _SEVERITY_RANK.get(s, 99)


@dataclass
class ConsolidatedIssue:
    component: str
    severity: IssueSeverity
    reporters: list[str]
    issue_type: IssueType
    description: str
    suggested_action: str


# ── Collector ─────────────────────────────────────────────────────────────────

class LokiIssueCollector:
    def __init__(self) -> None:
        self._loki = LokiClient()
        self._prom = PrometheusClient()

    async def collect(
        self, date_str: str | None = None
    ) -> tuple[list[ConsolidatedIssue], list[str]]:
        """Collect, deduplicate, and sort issues for *date_str* (default: today).

        Returns:
            (hitl_issues, medium_descriptions)
            hitl_issues           — critical/high ConsolidatedIssues sorted by severity
            medium_descriptions   — plain strings for medium issues (log-only)
        """
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        raw: list[ConsolidatedIssue] = []

        # Prometheus-backed checks — emit a single medium issue if Prometheus is unreachable
        # rather than generating false-positive HIGH alerts for every expected target.
        try:
            raw += await self._check_node_exporter()
            raw += await self._check_cadvisor()
        except TelemetryError as exc:
            logger.warning("issue_collector: prometheus unavailable — %s", exc)
            raw.append(ConsolidatedIssue(
                component="prometheus",
                severity="medium",
                reporters=["cio"],
                issue_type="telemetry_unavailable",
                description=f"Prometheus unreachable — node/cadvisor checks skipped: {exc}",
                suggested_action="infra_verify:https://prometheus.prova9x.com/-/healthy",
            ))

        # Loki-backed checks — same pattern
        try:
            raw += await self._check_silent_agents()
            raw += await self._check_agent_errors()
        except TelemetryError as exc:
            logger.warning("issue_collector: loki unavailable — %s", exc)
            raw.append(ConsolidatedIssue(
                component="loki",
                severity="medium",
                reporters=["cio"],
                issue_type="telemetry_unavailable",
                description=f"Loki unreachable — agent silence checks skipped: {exc}",
                suggested_action="infra_verify:http://10.10.200.71:3100/ready",
            ))

        # Deduplicate by (component, issue_type) — keep highest severity
        dedup: dict[tuple[str, str], ConsolidatedIssue] = {}
        for ci in raw:
            key = (ci.component, ci.issue_type)
            if key not in dedup:
                dedup[key] = ci
            else:
                existing = dedup[key]
                if severity_rank(ci.severity) < severity_rank(existing.severity):
                    existing.severity = ci.severity
                for r in ci.reporters:
                    if r not in existing.reporters:
                        existing.reporters.append(r)

        all_issues = list(dedup.values())
        hitl = sorted(
            [i for i in all_issues if i.severity in ("critical", "high")],
            key=lambda i: severity_rank(i.severity),
        )
        medium = [
            f"• {i.component}: {i.description[:100]} [{i.issue_type}]"
            for i in all_issues
            if i.severity == "medium"
        ]
        return hitl, medium

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _check_node_exporter(self) -> list[ConsolidatedIssue]:
        """Flag hosts where node_exporter is down (Prometheus up=0)."""
        results = await self._prom.query('up{job="node_exporter"}')
        down = []
        seen = {r["metric"].get("instance") for r in results if float(r["value"][1]) == 1.0}
        for expected in EXPECTED_NODE_EXPORTER:
            if expected not in seen:
                ip = expected.split(":")[0]
                down.append(ConsolidatedIssue(
                    component=ip,
                    severity="high",
                    reporters=["cio"],
                    issue_type="connection_error",
                    description=f"node_exporter unreachable on {ip} — host may be down",
                    suggested_action=f"tcp_check:{ip}:9100",
                ))
        return down

    async def _check_cadvisor(self) -> list[ConsolidatedIssue]:
        """Flag hosts where cadvisor is down (Prometheus up=0)."""
        results = await self._prom.query('up{job="cadvisor"}')
        issues = []
        seen = {r["metric"].get("instance") for r in results if float(r["value"][1]) == 1.0}
        for expected in EXPECTED_NODE_EXPORTER:
            cadvisor_instance = expected.replace(":9100", ":9080")
            if cadvisor_instance not in seen:
                ip = expected.split(":")[0]
                issues.append(ConsolidatedIssue(
                    component=f"{ip}-cadvisor",
                    severity="medium",
                    reporters=["cio"],
                    issue_type="mcp_unreachable",
                    description=f"cadvisor unreachable on {ip}",
                    suggested_action=f"tcp_check:{ip}:9080",
                ))
        return issues

    async def _check_silent_agents(self) -> list[ConsolidatedIssue]:
        """Flag agents that have no Loki entries in the last AGENT_SILENCE_LOOKBACK_S."""
        issues = []
        for agent_id in EXPECTED_AGENTS:
            query = f'{{job="jarvios-agent-memory", agent="{agent_id}"}}'
            count = await self._loki.count_entries(query, AGENT_SILENCE_LOOKBACK_S)
            if count == 0:
                issues.append(ConsolidatedIssue(
                    component=f"{agent_id}-agent",
                    severity="high",
                    reporters=["cio"],
                    issue_type="connection_error",
                    description=f"No log activity from {agent_id} in the last 8h — agent may be silent or down",
                    suggested_action=f"supervisorctl:restart:{agent_id}",
                ))
        return issues

    async def _check_agent_errors(self) -> list[ConsolidatedIssue]:
        """Scan aipal-runner logs for ERROR patterns; raise medium issue if recurring."""
        query = '{container="aipal-runner"} |~ "(?i)(ERROR|Traceback|Exception|CRITICAL)"'
        now = int(time.time())
        streams = await self._loki.query_range(
            query,
            now - ERROR_SCAN_LOOKBACK_S,
            now,
            limit=500,
        )

        # Count error occurrences per component (extract from log lines)
        component_errors: dict[str, int] = {}
        for stream in streams:
            for _ts, line in stream.get("values", []):
                component = self._extract_component(line)
                component_errors[component] = component_errors.get(component, 0) + 1

        issues = []
        for component, count in component_errors.items():
            if count >= ERROR_MIN_COUNT:
                issues.append(ConsolidatedIssue(
                    component=component,
                    severity="medium",
                    reporters=["cio"],
                    issue_type="high_error_rate",
                    description=f"{count} ERROR entries in last 6h",
                    suggested_action=f"manual:investigate {component} errors in Loki",
                ))
        return issues

    @staticmethod
    def _extract_component(log_line: str) -> str:
        """Best-effort extraction of a component name from a log line."""
        # Try to match "agent_id=<id>" or "[<id>]" patterns
        m = re.search(r"agent_id[=:]\s*['\"]?(\w+)", log_line)
        if m:
            return f"{m.group(1)}-agent"
        m = re.search(r"\[(\w+)\]", log_line)
        if m and m.group(1) not in {"ERROR", "WARNING", "INFO", "DEBUG", "CRITICAL"}:
            return m.group(1).lower()
        return "aipal-runner"


# Keep backward-compatible alias so existing imports don't break during transition
IssueCollector = LokiIssueCollector
