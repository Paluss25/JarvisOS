# agents/cio/issue_collector.py
"""IssueCollector — reads shared volume reports and produces deduplicated ConsolidatedIssues.

Reads /app/workspace/shared/issues/{today}/*.json (written by each agent's report_issue tool).
Agents that did NOT write a file are flagged as silent → high-severity issue.
Deduplicates by (component, issue_type) — takes highest severity across reporters.
Returns list sorted: critical first, then high, then medium.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent_runner.issues.schema import IssueReport, IssueSeverity, IssueType, severity_rank

logger = logging.getLogger(__name__)

EXPECTED_REPORTERS = [
    "ceo", "cos", "email_intelligence_agent", "cfo", "coh", "dos",
]


@dataclass
class ConsolidatedIssue:
    component: str
    severity: IssueSeverity         # highest severity across all reporters
    reporters: list[str]            # agent IDs that reported this component
    issue_type: IssueType
    description: str                # merged description (first reporter's + count suffix)
    suggested_action: str           # action string for RemediationEngine


class IssueCollector:
    def __init__(
        self,
        shared_issues_path: Path = Path("/app/workspace/shared/issues"),
    ) -> None:
        self._shared_path = shared_issues_path

    def collect(self, date_str: str | None = None) -> tuple[list[ConsolidatedIssue], list[str]]:
        """Collect, deduplicate, and sort issues for date_str (default: today).

        Returns:
            (consolidated_issues, medium_descriptions)
            consolidated_issues — critical/high issues sorted by severity
            medium_descriptions — plain strings for medium issues (log-only)
        """
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        date_dir = self._shared_path / date_str
        reports: list[IssueReport] = []
        found_agents: set[str] = set()

        if date_dir.exists():
            for json_path in date_dir.glob("*.json"):
                agent_id = json_path.stem
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    report = IssueReport.from_dict(data)
                    reports.append(report)
                    found_agents.add(agent_id)
                except Exception as exc:
                    logger.warning("issue_collector: failed to read %s — %s", json_path, exc)

        # Silent agents: did not write a report file
        for agent_id in EXPECTED_REPORTERS:
            if agent_id not in found_agents:
                logger.warning("issue_collector: no report from agent '%s' — flagging as silent", agent_id)
                from agent_runner.issues.schema import Issue
                silent_report = IssueReport(
                    agent_id=agent_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    issues=[
                        Issue(
                            type="connection_error",
                            severity="high",
                            component=f"{agent_id}-agent",
                            description=f"No issue report received from {agent_id} — agent may be down",
                        )
                    ],
                )
                reports.append(silent_report)

        # Deduplicate by (component, issue_type)
        dedup: dict[tuple[str, str], ConsolidatedIssue] = {}

        for report in reports:
            for issue in report.issues:
                key = (issue.component, issue.type)
                if key not in dedup:
                    dedup[key] = ConsolidatedIssue(
                        component=issue.component,
                        severity=issue.severity,
                        reporters=[report.agent_id],
                        issue_type=issue.type,
                        description=issue.description,
                        suggested_action=self._suggest_action(issue.component, issue.type),
                    )
                else:
                    ci = dedup[key]
                    if report.agent_id not in ci.reporters:
                        ci.reporters.append(report.agent_id)
                    # Escalate severity if higher
                    if severity_rank(issue.severity) < severity_rank(ci.severity):
                        ci.severity = issue.severity
                    # Merge description if different
                    if issue.description and issue.description not in ci.description:
                        ci.description = ci.description + "; " + issue.description

        all_issues = list(dedup.values())

        # Split medium from critical/high
        hitl_issues = [i for i in all_issues if i.severity in ("critical", "high")]
        medium_issues = [i for i in all_issues if i.severity == "medium"]

        # Sort hitl by severity (critical first)
        hitl_issues.sort(key=lambda i: severity_rank(i.severity))

        medium_descriptions = [
            f"• {i.component}: {i.description[:100]} [reported by: {', '.join(i.reporters)}]"
            for i in medium_issues
        ]

        return hitl_issues, medium_descriptions

    def _suggest_action(self, component: str, issue_type: IssueType) -> str:
        """Produce a default suggested_action string based on component name and issue type.

        Action strings are interpreted by RemediationEngine:
          docker_action:restart:{name}     — restart a Docker container
          supervisorctl:restart:{process}  — restart a supervisord process
          infra_verify:{url}               — HTTP health check (diagnostic only)
          tcp_check:{host}:{port}          — TCP connectivity check
          pg_check:{db}                    — PostgreSQL SELECT 1 check
          manual:{description}             — no automation; prompt user
        """
        c = component.lower()

        # Well-known Docker containers
        docker_containers = {
            "redis": "jarvios-redis",
            "postgres": "jarvios-postgres",
            "postgres-shared": "postgres-shared",
            "protonmail-mcp": "protonmail-mcp",
        }
        for keyword, container_name in docker_containers.items():
            if keyword in c:
                if issue_type in ("connection_error", "mcp_unreachable", "restart_detected"):
                    return f"docker_action:restart:{container_name}"

        # Agent processes in supervisord (agent-<id>)
        if c.endswith("-agent") or (issue_type == "connection_error" and "agent" in c):
            process = c.replace("-agent", "")
            return f"supervisorctl:restart:{process}"

        # DB errors → connectivity check
        if issue_type == "db_error":
            if "nutrition" in c or "drhouse" in c:
                return "pg_check:nutrition"
            if "sport" in c:
                return "pg_check:sport"
            return "pg_check:ceo"

        # Default: manual intervention
        return f"manual:investigate {component} ({issue_type})"
