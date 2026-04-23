# agents/cio/hitl_queue.py
"""HITLQueue — persistent state machine for the sequential HITL approval loop.

State is persisted to workspace/cio/hitl_queue.json so CIO can resume after restart.
The approval loop runs as a coroutine: it sends Telegram messages via hitl_gate and
waits for asyncio.Event signals set by the Telegram callback handler.

Timeout per task: 600s (10 minutes). Expired tasks are skipped and logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from agent_runner.issues.hitl_gate import register_resolve, send_task_message, send_notification
from agent_runner.issues.schema import IssueSeverity

logger = logging.getLogger(__name__)

_HITL_TIMEOUT = 600  # seconds (10 minutes per task)


@dataclass
class HITLTask:
    id: str                       # 8-char hex, used in callback data
    index: int                    # 0-based position in queue
    title: str                    # shown in Telegram
    component: str
    severity: IssueSeverity
    reporters: list[str]
    action: str                   # RemediationEngine action string
    status: Literal["pending", "approved", "rejected", "expired", "completed", "failed"] = "pending"
    result: str = ""              # filled after execution

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "HITLTask":
        return HITLTask(**{k: v for k, v in d.items() if k in HITLTask.__dataclass_fields__})


@dataclass
class HITLQueueState:
    date: str
    status: Literal["idle", "running", "complete"] = "idle"
    summary_sent: bool = False
    tasks: list[HITLTask] = field(default_factory=list)
    current_index: int = 0
    medium_issues: list[str] = field(default_factory=list)   # log-only descriptions

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "status": self.status,
            "summary_sent": self.summary_sent,
            "tasks": [t.to_dict() for t in self.tasks],
            "current_index": self.current_index,
            "medium_issues": self.medium_issues,
        }

    @staticmethod
    def from_dict(d: dict) -> "HITLQueueState":
        tasks = [HITLTask.from_dict(t) for t in d.get("tasks", [])]
        return HITLQueueState(
            date=d.get("date", ""),
            status=d.get("status", "idle"),
            summary_sent=d.get("summary_sent", False),
            tasks=tasks,
            current_index=d.get("current_index", 0),
            medium_issues=d.get("medium_issues", []),
        )


class HITLQueue:
    """Manages persistent HITL state and drives the sequential Telegram approval loop."""

    def __init__(self, workspace_path: Path) -> None:
        self._state_path = workspace_path / "hitl_queue.json"
        self._pending: dict[str, asyncio.Event] = {}
        self._results: dict[str, bool] = {}
        register_resolve(self._resolve)

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def load_or_create(self, date_str: str) -> HITLQueueState:
        """Load existing queue for date_str, or create a fresh idle state."""
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                state = HITLQueueState.from_dict(data)
                if state.date == date_str:
                    logger.info("hitl_queue: resumed state for %s (status=%s)", date_str, state.status)
                    return state
            except Exception as exc:
                logger.warning("hitl_queue: failed to load state — %s", exc)

        return HITLQueueState(date=date_str)

    def save(self, state: HITLQueueState) -> None:
        try:
            self._state_path.write_text(
                json.dumps(state.to_dict(), indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.error("hitl_queue: failed to save state — %s", exc)

    # ------------------------------------------------------------------
    # Telegram callback → asyncio.Event resolution
    # ------------------------------------------------------------------

    def _resolve(self, task_id: str, approved: bool) -> None:
        """Called by hitl_gate.resolve() from the Telegram callback handler."""
        if task_id in self._pending:
            self._results[task_id] = approved
            self._pending[task_id].set()
        else:
            logger.warning("hitl_queue: resolve called for unknown task_id=%s", task_id)

    # ------------------------------------------------------------------
    # Queue building
    # ------------------------------------------------------------------

    def build_from_issues(
        self,
        consolidated_issues,  # list[ConsolidatedIssue]
        medium_issues: list[str],
        date_str: str,
    ) -> HITLQueueState:
        """Convert ConsolidatedIssues into HITLTasks and create a fresh queue state."""
        tasks = []
        for idx, issue in enumerate(consolidated_issues):
            task_id = uuid.uuid4().hex[:8]
            sev_emoji = "🔴" if issue.severity == "critical" else "🟠"
            title = f"{sev_emoji} {issue.component}: {issue.description[:80]}"
            tasks.append(HITLTask(
                id=task_id,
                index=idx,
                title=title,
                component=issue.component,
                severity=issue.severity,
                reporters=list(issue.reporters),
                action=issue.suggested_action,
            ))

        state = HITLQueueState(
            date=date_str,
            status="idle",
            summary_sent=False,
            tasks=tasks,
            current_index=0,
            medium_issues=medium_issues,
        )
        self.save(state)
        return state

    # ------------------------------------------------------------------
    # Approval loop
    # ------------------------------------------------------------------

    async def run_approval_loop(
        self,
        state: HITLQueueState,
        remediation_engine,  # RemediationEngine instance
        daily_log_fn,        # callable(message: str) → None
    ) -> HITLQueueState:
        """Drive the sequential HITL loop. Modifies state in-place and persists after each step."""
        if not state.tasks:
            await send_notification("✅ *All systems nominal* — no issues reported by any agent.")
            state.status = "complete"
            self.save(state)
            return state

        # Send summary (Msg 0) if not already sent
        if not state.summary_sent:
            summary = self._build_summary_text(state)
            await send_notification(summary)
            state.summary_sent = True
            state.status = "running"
            self.save(state)

        # Process tasks from current_index
        for i in range(state.current_index, len(state.tasks)):
            task = state.tasks[i]
            state.current_index = i
            self.save(state)

            if task.status != "pending":
                continue  # already resolved (resume after restart)

            # Send task approval message with inline keyboard
            task_text = self._build_task_text(task, i + 1, len(state.tasks))
            await send_task_message(task_text, task.id)

            # Wait for user response or timeout
            event = asyncio.Event()
            self._pending[task.id] = event

            try:
                await asyncio.wait_for(event.wait(), timeout=_HITL_TIMEOUT)
            except asyncio.TimeoutError:
                self._pending.pop(task.id, None)
                self._results.pop(task.id, None)
                task.status = "expired"
                task.result = f"Timed out after {_HITL_TIMEOUT}s"
                daily_log_fn(f"[HITL] Task expired: {task.title}")
                self.save(state)
                continue

            approved = self._results.pop(task.id, False)
            self._pending.pop(task.id, None)

            if approved:
                task.status = "approved"
                self.save(state)
                try:
                    result_text = await remediation_engine.execute(task.action)
                    task.status = "completed"
                    task.result = result_text
                    await send_notification(f"✅ *Task {i + 1} completato*\n{result_text[:300]}")
                    daily_log_fn(f"[HITL] Completed: {task.title} → {result_text[:80]}")
                except Exception as exc:
                    task.status = "failed"
                    task.result = str(exc)
                    await send_notification(f"❌ *Task {i + 1} fallito*\n```\n{str(exc)[:200]}\n```")
                    daily_log_fn(f"[HITL] Failed: {task.title} — {exc}")
            else:
                task.status = "rejected"
                daily_log_fn(f"[HITL] Rejected: {task.title}")

            self.save(state)

        # Final summary
        completed = sum(1 for t in state.tasks if t.status == "completed")
        skipped = sum(1 for t in state.tasks if t.status == "rejected")
        expired = sum(1 for t in state.tasks if t.status == "expired")
        failed = sum(1 for t in state.tasks if t.status == "failed")
        medium_count = len(state.medium_issues)

        final_text = (
            f"*Review completata — {state.date}*\n"
            f"✅ Risolti: {completed}\n"
            f"❌ Saltati: {skipped}\n"
            f"⏱ Scaduti: {expired}\n"
            f"💥 Falliti: {failed}\n"
            f"📋 Medium (solo log): {medium_count}"
        )
        await send_notification(final_text)

        state.status = "complete"
        self.save(state)
        return state

    # ------------------------------------------------------------------
    # Message builders
    # ------------------------------------------------------------------

    def _build_summary_text(self, state: HITLQueueState) -> str:
        hitl_lines = []
        for t in state.tasks:
            sev_label = t.severity.upper()
            reporters_str = ", ".join(t.reporters)
            hitl_lines.append(f"• {t.component} [{sev_label}] — da: {reporters_str}")

        summary = f"🔧 *Issue Report — {state.date}*\n\n"
        summary += f"{len(state.tasks)} issue da risolvere:\n"
        summary += "\n".join(hitl_lines)

        if state.medium_issues:
            summary += f"\n\n{len(state.medium_issues)} issue monitorate (medium — solo log):\n"
            summary += "\n".join(state.medium_issues[:5])

        summary += "\n\n_Avvio review..._"
        return summary

    def _build_task_text(self, task: HITLTask, task_num: int, total: int) -> str:
        reporters_str = ", ".join(task.reporters)
        action_label = self._action_label(task.action)
        sev_label = task.severity.capitalize()
        return (
            f"*Task {task_num}/{total} — {sev_label}*\n"
            f"{task.component}\n"
            f"_{task.title}_\n"
            f"Segnalato da: {reporters_str}\n"
            f"Azione: {action_label}"
        )

    def _action_label(self, action: str) -> str:
        parts = action.split(":", 2)
        if parts[0] == "docker_action":
            return f"restart container `{parts[2]}`"
        if parts[0] == "supervisorctl":
            return f"supervisorctl restart `{parts[2]}`"
        if parts[0] == "infra_verify":
            return f"HTTP health check `{parts[1] if len(parts) > 1 else '?'}`"
        if parts[0] == "pg_check":
            return f"PostgreSQL connectivity check ({parts[1] if len(parts) > 1 else '?'})"
        if parts[0] == "tcp_check":
            return f"TCP check `{':'.join(parts[1:])}`"
        if parts[0] == "manual":
            return f"intervento manuale: {':'.join(parts[1:])}"
        return action
