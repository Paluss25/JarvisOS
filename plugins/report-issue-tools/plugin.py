from __future__ import annotations

from plugin_runtime.tools import ToolSpec


def register(context):
    from agent_runner.tools.report_issue import REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA
    from agent_runner.tools.report_issue_client import report_issue

    async def _report(args: dict) -> dict:
        return await report_issue(context.agent_id, args)

    return [
        ToolSpec(
            name="report_issue",
            description=REPORT_ISSUE_DESCRIPTION,
            schema=REPORT_ISSUE_SCHEMA,
            handler=_report,
        )
    ]
