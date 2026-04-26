# agents/cio/run_issue_collection.py
"""Top-level async orchestrator for the CIO daily issue collection and HITL loop.

Called from the collect_and_remediate MCP tool (which the CIO LLM invokes when
the issue_collector cron fires). Not called from the LLM directly.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Prevents two concurrent loops from overwriting hitl_gate._resolve_fn
_loop_lock = asyncio.Lock()


async def run_issue_collection(workspace_path: Path) -> str:
    """Collect issues, build queue, run HITL loop.

    Returns a short status string (for the LLM response after tool completion).
    """
    if _loop_lock.locked():
        return "Issue collection loop already running — skipping duplicate invocation."

    async with _loop_lock:
        from agents.cio.issue_collector import IssueCollector
        from agents.cio.hitl_queue import HITLQueue
        from agents.cio.remediation import RemediationEngine
        from agent_runner.memory.daily_logger import DailyLogger

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        collector = IssueCollector()
        hitl_q = HITLQueue(workspace_path)
        remediation = RemediationEngine()
        daily_log = DailyLogger(workspace_path)

        # Load existing state (resume if CIO restarted mid-loop)
        state = hitl_q.load_or_create(today)

        if state.status == "complete":
            return f"Issue collection for {today} already complete — nothing to do."

        if state.status == "idle":
            # Fresh run: collect issues and build queue
            logger.info("run_issue_collection: collecting issues for %s", today)
            hitl_issues, medium_descriptions = await collector.collect(today)

            if hitl_issues:
                state = hitl_q.build_from_issues(hitl_issues, medium_descriptions, today)
                # Emit one [INCIDENT] entry per critical/high issue for Loki filtering
                for issue in hitl_issues:
                    daily_log.log(
                        f"[INCIDENT] {issue.severity.upper()} — {issue.component}: "
                        f"{issue.description[:120]}"
                    )
                daily_log.log(
                    f"[ISSUE_COLLECTOR] {today}: {len(hitl_issues)} HITL tasks, "
                    f"{len(medium_descriptions)} medium (log-only)"
                )
            else:
                # Zero critical/high issues — log medium ones and exit fast path
                for desc in medium_descriptions:
                    daily_log.log(f"[MEDIUM ISSUE] {desc}")
                from agent_runner.issues.hitl_gate import send_notification
                await send_notification(
                    f"✅ *All systems nominal — {today}*\n"
                    + (f"\n_{len(medium_descriptions)} medium issue(s) logged:_\n" + "\n".join(medium_descriptions[:5])
                       if medium_descriptions else "")
                )
                return f"No HITL tasks. {len(medium_descriptions)} medium issues logged."

        # Both fresh-build and resume paths fall through to the approval loop
        final_state = await hitl_q.run_approval_loop(
            state=state,
            remediation_engine=remediation,
            daily_log_fn=daily_log.log,
        )

        completed = sum(1 for t in final_state.tasks if t.status == "completed")
        total = len(final_state.tasks)
        return f"HITL loop complete: {completed}/{total} tasks resolved."
