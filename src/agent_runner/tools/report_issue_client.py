from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SHARED_ISSUES_ROOT = Path("/app/workspace/shared/issues")

VALID_ISSUE_TYPES = frozenset({
    "connection_error",
    "db_error",
    "mcp_unreachable",
    "restart_detected",
    "high_error_rate",
    "auth_failure",
    "custom",
})
VALID_SEVERITIES = frozenset({"critical", "high", "medium"})


def normalize_issue_args(args: Any) -> list[dict]:
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

        if issue_type not in VALID_ISSUE_TYPES:
            issue_type = "custom"
        if severity not in VALID_SEVERITIES:
            severity = "medium"

        validated.append({
            "type": issue_type,
            "severity": severity,
            "component": component,
            "description": description,
        })
    return validated


async def report_issue(agent_id: str, args: Any, *, issues_root: Path = SHARED_ISSUES_ROOT) -> dict:
    validated = normalize_issue_args(args)
    report = {
        "agent_id": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "issues": validated,
    }

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = issues_root / today
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{agent_id}.json"
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        n = len(validated)
        return {"content": [{"type": "text", "text": f"reported {n} issue{'s' if n != 1 else ''}"}]}
    except Exception as exc:
        logger.error("report_issue(%s): write failed — %s", agent_id, exc)
        return {"content": [{"type": "text", "text": f"error writing issue report: {exc}"}]}
