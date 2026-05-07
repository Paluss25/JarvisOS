# agent_runner/tools/report_issue.py
"""Shared factory: creates the report_issue MCP tool for any agent.

Usage in an agent's tools.py:
    from agent_runner.tools.report_issue import create_report_issue_tool, REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA

    @sdk_tool("report_issue", REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA)
    async def report_issue(args: dict) -> dict:
        return await create_report_issue_tool(agent_id)(args)
"""
import logging

from agent_runner.tools.report_issue_client import (
    SHARED_ISSUES_ROOT as _SHARED_ISSUES_ROOT,
    VALID_ISSUE_TYPES as _VALID_TYPES,
    VALID_SEVERITIES as _VALID_SEVERITIES,
    report_issue,
)

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

def create_report_issue_tool(agent_id: str):
    """Return an async callable that implements the report_issue tool for agent_id."""

    async def _report_issue(args) -> dict:
        return await report_issue(agent_id, args, issues_root=_SHARED_ISSUES_ROOT)

    return _report_issue
