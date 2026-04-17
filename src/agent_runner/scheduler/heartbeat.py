"""Heartbeat scheduler — proactive task runner for agents.

Reads scheduled tasks from workspace/crons.json (via CronStore) and executes
them at the configured times (all times in Europe/Rome — CET/CEST).

Default built-in tasks (agents can override via AgentConfig.builtin_crons):
    daily@08:00      — morning briefing: yesterday's log → Telegram
    daily@23:00      — end-of-day consolidation: today's summary → daily memory
    weekly@sun@20:00 — weekly consolidation: week's logs → MEMORY.md rewrite

User tasks can be added at runtime via the cron_create MCP tool. All tasks
persist across container restarts. Missed tasks (container was down at fire
time) are caught up within _MISSED_WINDOW_HOURS hours.

Runs as an asyncio.Task inside the agent lifespan.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from agent_runner.memory.daily_logger import DailyLogger
from agent_runner.scheduler.cron_store import CronEntry, get_store, is_due, was_missed

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Rome")

# Default built-in crons — each agent can override via AgentConfig.builtin_crons
DEFAULT_BUILTIN_CRONS: list[dict] = [
    {
        "name": "morning_briefing",
        "schedule": "daily@08:00",
        "prompt": (
            "Good morning! Prepare a concise morning briefing (under 200 words). "
            "Include: key items from yesterday's activity log, any tasks or appointments "
            "for today from HEARTBEAT.md, and anything actionable I should know. "
            "Be brief and direct — no filler."
        ),
        "session_id": "heartbeat-morning",
        "telegram_notify": True,
        "builtin": True,
    },
    {
        "name": "eod_consolidation",
        "schedule": "daily@23:00",
        "prompt": (
            "End of day. Summarise today's activity in 3-5 bullet points. "
            "Focus on: decisions made, tasks completed, issues encountered, lessons learned. "
            "End with a 'KEY FACTS' line listing any durable facts worth remembering "
            "beyond today."
        ),
        "session_id": "heartbeat-eod",
        "telegram_notify": False,
        "builtin": True,
    },
    {
        "name": "weekly_consolidation",
        "schedule": "weekly@sun@20:00",
        "prompt": (
            "Weekly memory consolidation. Review this week's daily logs and the current "
            "MEMORY.md. Produce an updated MEMORY.md that: adds important facts worth "
            "remembering long-term, removes entries that are no longer relevant, and "
            "organises everything clearly under appropriate headings. "
            "Return ONLY the raw markdown for the new MEMORY.md — no extra commentary."
        ),
        "session_id": "heartbeat-weekly",
        "telegram_notify": True,
        "builtin": True,
    },
]


class HeartbeatScheduler:
    """Asyncio-based proactive task scheduler for agents.

    Reads from CronStore (workspace/crons.json). Each entry runs at most once
    per scheduled period. Missed tasks (container restart during fire window)
    are caught up automatically.

    Args:
        agent: The agent instance (must implement ``query(prompt, session_id)``).
        config: AgentConfig — provides workspace_path, telegram_token_env,
                telegram_chat_id_env, and builtin_crons.
    """

    def __init__(self, agent, config) -> None:
        self._agent = agent
        self._config = config
        workspace = Path(config.workspace_path)
        self._store = get_store(workspace)
        builtin_crons = getattr(config, "builtin_crons", None) or DEFAULT_BUILTIN_CRONS
        self._store.seed(builtin_crons)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Start the scheduler loop. Blocks until cancelled."""
        logger.info("heartbeat: scheduler started (agent=%s)", self._config.name)
        try:
            while True:
                await self._tick()
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("heartbeat: scheduler stopped (agent=%s)", self._config.name)

    # -----------------------------------------------------------------------
    # Tick
    # -----------------------------------------------------------------------

    async def _tick(self) -> None:
        now = datetime.now(_TZ)
        for entry in self._store.all():
            if is_due(entry, now):
                await self._run(entry, reason="due")
            elif was_missed(entry, now):
                await self._run(entry, reason="missed")

    # -----------------------------------------------------------------------
    # Task dispatch
    # -----------------------------------------------------------------------

    async def _run(self, entry: CronEntry, reason: str = "due") -> None:
        logger.info(
            "heartbeat: triggering '%s' (id=%s, reason=%s)",
            entry.name, entry.id, reason,
        )
        workspace = Path(self._config.workspace_path)

        # --- Context augmentation for built-in tasks -----------------------
        prompt = entry.prompt

        if entry.name == "morning_briefing":
            yesterday = date.today() - timedelta(days=1)
            yesterday_log = DailyLogger(workspace).read_date(yesterday)
            if yesterday_log:
                prompt += (
                    f"\n\nYesterday's memory log ({yesterday.isoformat()}):\n"
                    f"{yesterday_log[:3000]}"
                )

        elif entry.name == "eod_consolidation":
            today_log = DailyLogger(workspace).read_today()
            if today_log:
                prompt += f"\n\nToday's memory log:\n{today_log[:4000]}"

        elif entry.name == "weekly_consolidation":
            prompt = self._build_weekly_prompt(workspace, entry.prompt)

        # --- Run agent -----------------------------------------------------
        try:
            result = await self._run_agent(prompt, entry.session_id)
        except Exception as exc:
            err = str(exc)
            logger.error("heartbeat: '%s' failed — %s", entry.name, exc, exc_info=True)
            self._store.record_run(entry.id, "error", err)
            await self._send_telegram(
                f"*Heartbeat error:* `{entry.name}`\n```\n{err[:300]}\n```"
            )
            return

        # --- Post-run side effects ------------------------------------------
        if entry.name == "eod_consolidation":
            DailyLogger(workspace).log_session_summary(f"[EOD CONSOLIDATION]\n{result}")
            logger.info("heartbeat: EOD consolidation written to daily memory")

        elif entry.name == "weekly_consolidation":
            self._write_memory(workspace, result)
            logger.info("heartbeat: weekly MEMORY.md updated")

        # --- Record success and notify -------------------------------------
        self._store.record_run(entry.id, "ok")

        if entry.telegram_notify:
            label = entry.name.replace("_", " ").title()
            await self._send_telegram(
                f"*{label} — {date.today().isoformat()}*\n\n{result[:3800]}"
            )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _build_weekly_prompt(self, workspace: Path, base_prompt: str) -> str:
        """Build the weekly consolidation prompt with week's logs + current MEMORY.md."""
        daily = DailyLogger(workspace)
        memory_path = workspace / "MEMORY.md"
        current_memory = (
            memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
        )

        today = date.today()
        week_parts: list[str] = []
        for i in range(7):
            d = today - timedelta(days=i)
            content = daily.read_date(d)
            if content:
                week_parts.append(f"### {d.isoformat()}\n{content[:2000]}")
        week_log = "\n\n".join(week_parts)

        return (
            f"{base_prompt}\n\n"
            f"CURRENT MEMORY.md:\n{current_memory[:3000]}\n\n"
            f"THIS WEEK'S LOGS:\n{week_log[:5000]}"
        )

    def _write_memory(self, workspace: Path, raw_output: str) -> None:
        """Strip markdown fences and write workspace/MEMORY.md."""
        lines = raw_output.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        (workspace / "MEMORY.md").write_text("\n".join(lines), encoding="utf-8")

    async def _run_agent(self, prompt: str, session_id: str) -> str:
        return await self._agent.query(prompt, session_id=session_id)

    async def _send_telegram(self, text: str) -> None:
        """Send a Telegram notification using this agent's configured token."""
        token = os.environ.get(self._config.telegram_token_env, "")
        chat_id = os.environ.get(self._config.telegram_chat_id_env, "")
        if not token or not chat_id:
            logger.debug("heartbeat: Telegram not configured — skipping notification")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": int(chat_id), "text": text, "parse_mode": "Markdown"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("heartbeat: Telegram notification failed — %s", exc)
