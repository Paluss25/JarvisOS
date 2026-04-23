# agent_runner/tools/report_issue.py
"""Shared factory: creates the report_issue MCP tool for any agent.

Usage in an agent's tools.py:
    from agent_runner.tools.report_issue import create_report_issue_tool, REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA

    @sdk_tool("report_issue", REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA)
    async def report_issue(args: dict) -> dict:
        return await create_report_issue_tool(agent_id)(args)
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

REPORT_ISSUE_DESCRIPTION = (
    "Report technical issues detected during this session to CIO for aggregation and remediation. "
    "Call this at the END of every morning briefing — even when issues is an empty list. "
    "Mandatory call — do not skip. "
    "Issue types: connection_error | db_error | mcp_unreachable | restart_detected | "
    "high_error_rate | auth_failure | custom. "
    "Severity: critical | high | medium. "
    "component: the service name (e.g. 'redis', 'postgres-shared', 'protonmail-mcp'). "
    "description: max 200 chars. "
    "If no issues detected: call with issues=[]."
)

REPORT_ISSUE_SCHEMA = {
    "issues": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "severity": {"type": "string"},
                "component": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["type", "severity", "component", "description"],
        },
    }
}

_SHARED_ISSUES_ROOT = Path("/app/workspace/shared/issues")

_VALID_TYPES = frozenset({
    "connection_error", "db_error", "mcp_unreachable",
    "restart_detected", "high_error_rate", "auth_failure", "custom",
})
_VALID_SEVERITIES = frozenset({"critical", "high", "medium"})


def create_report_issue_tool(agent_id: str):
    """Return an async callable that implements the report_issue tool for agent_id."""

    async def _report_issue(args) -> dict:
        # Normalize args (older SDK versions pass a JSON string)
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, ValueError):
                args = {}
        if not isinstance(args, dict):
            args = {}

        raw_issues = args.get("issues", [])
        if isinstance(raw_issues, str):
            try:
                raw_issues = json.loads(raw_issues)
            except Exception:
                raw_issues = []

        validated = []
        for item in (raw_issues or []):
            if not isinstance(item, dict):
                continue
            issue_type = item.get("type", "custom")
            severity = item.get("severity", "medium")
            component = str(item.get("component", "unknown"))[:80]
            description = str(item.get("description", ""))[:200]

            if issue_type not in _VALID_TYPES:
                issue_type = "custom"
            if severity not in _VALID_SEVERITIES:
                severity = "medium"

            validated.append({
                "type": issue_type,
                "severity": severity,
                "component": component,
                "description": description,
            })

        report = {
            "agent_id": agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "issues": validated,
        }

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_dir = _SHARED_ISSUES_ROOT / today
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{agent_id}.json"
            out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            n = len(validated)
            return {"content": [{"type": "text", "text": f"reported {n} issue{'s' if n != 1 else ''}"}]}
        except Exception as exc:
            logger.error("report_issue(%s): write failed — %s", agent_id, exc)
            return {"content": [{"type": "text", "text": f"error writing issue report: {exc}"}]}

    return _report_issue
