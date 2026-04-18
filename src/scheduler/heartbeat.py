"""Heartbeat scheduler — proactive task runner for Jarvis.

Reads the schedule from workspace/HEARTBEAT.md and executes tasks at the
configured times (all times in Europe/Rome — CET/CEST):

    08:00  — morning briefing: yesterday's log + pending tasks → Telegram
    23:00  — end-of-day consolidation: session summary → daily memory
    Sunday 20:00  — weekly consolidation: week's learnings → MEMORY.md

Runs as an asyncio.Task inside the JarvisOS lifespan (src/main.py).
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from config import settings
from memory.daily_logger import DailyLogger

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Europe/Rome")

# Task fires if the current minute is within this many minutes of the target hour
_WINDOW_MINUTES = 4


class HeartbeatScheduler:
    """Asyncio-based proactive task scheduler for Jarvis.

    Each task runs at most once per calendar day (guarded by _last_run).
    The main loop wakes every 60 seconds to check whether any task is due.
    """

    def __init__(self, agent) -> None:
        self._agent = agent
        self._last_run: dict[str, date] = {}  # task_name → last run date

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """Start the scheduler loop. Blocks until the task is cancelled."""
        logger.info("heartbeat: scheduler started")
        try:
            while True:
                await self._tick()
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("heartbeat: scheduler stopped")

    # -----------------------------------------------------------------------
    # Internal tick
    # -----------------------------------------------------------------------

    async def _tick(self) -> None:
        now = datetime.now(_TZ)
        today = now.date()
        h, m = now.hour, now.minute

        # Morning briefing — 08:00 CET
        if h == 8 and m < _WINDOW_MINUTES:
            await self._run_once("morning_briefing", today, self._morning_briefing)

        # End-of-day consolidation — 23:00 CET
        if h == 23 and m < _WINDOW_MINUTES:
            await self._run_once("eod_consolidation", today, self._eod_consolidation)

        # Weekly MEMORY.md consolidation — Sunday (weekday 6) at 20:00 CET
        if now.weekday() == 6 and h == 20 and m < _WINDOW_MINUTES:
            await self._run_once("weekly_consolidation", today, self._weekly_consolidation)

    async def _run_once(self, name: str, today: date, task) -> None:
        """Fire *task* at most once per calendar day."""
        if self._last_run.get(name) == today:
            return
        self._last_run[name] = today
        logger.info("heartbeat: triggering '%s'", name)
        try:
            await task()
        except Exception as exc:
            logger.error("heartbeat: '%s' failed — %s", name, exc, exc_info=True)

    # -----------------------------------------------------------------------
    # Scheduled tasks
    # -----------------------------------------------------------------------

    async def _morning_briefing(self) -> None:
        """08:00 CET — brief summary of yesterday + today's schedule → Telegram."""
        daily = DailyLogger(settings.workspace_path)
        yesterday = date.today() - timedelta(days=1)
        yesterday_log = daily.read_date(yesterday)

        prompt = (
            "Good morning! Prepare a concise morning briefing (under 200 words). "
            "Include: key items from yesterday's activity log, any tasks or appointments "
            "for today from HEARTBEAT.md, and anything actionable I should know. "
            "Be brief and direct — no filler.\n\n"
        )
        if yesterday_log:
            prompt += f"Yesterday's memory log ({yesterday.isoformat()}):\n{yesterday_log[:3000]}"

        text = await self._run_agent(prompt, session_id="heartbeat-morning")
        await _send_telegram(f"*Morning Briefing — {date.today().isoformat()}*\n\n{text}")

    async def _eod_consolidation(self) -> None:
        """23:00 CET — summarise today's sessions, append to daily memory."""
        daily = DailyLogger(settings.workspace_path)
        today_log = daily.read_today()

        prompt = (
            "End of day. Summarise today's activity in 3-5 bullet points. "
            "Focus on: decisions made, tasks completed, issues encountered, lessons learned. "
            "End with a 'KEY FACTS' line listing any durable facts worth remembering "
            "beyond today.\n\n"
        )
        if today_log:
            prompt += f"Today's memory log:\n{today_log[:4000]}"

        summary = await self._run_agent(prompt, session_id="heartbeat-eod")
        daily.log_session_summary(f"[EOD CONSOLIDATION]\n{summary}")
        logger.info("heartbeat: EOD consolidation written to daily memory")

    async def _weekly_consolidation(self) -> None:
        """Sunday 20:00 CET — review week's logs and rewrite workspace/MEMORY.md."""
        workspace = settings.workspace_path
        daily = DailyLogger(workspace)
        memory_path = workspace / "MEMORY.md"

        current_memory = ""
        if memory_path.exists():
            current_memory = memory_path.read_text(encoding="utf-8")

        today = date.today()
        week_parts: list[str] = []
        for i in range(7):
            d = today - timedelta(days=i)
            content = daily.read_date(d)
            if content:
                week_parts.append(f"### {d.isoformat()}\n{content[:2000]}")
        week_log = "\n\n".join(week_parts)

        prompt = (
            "Weekly memory consolidation. Review this week's daily logs and the current "
            "MEMORY.md. Produce an updated MEMORY.md that: adds important facts worth "
            "remembering long-term, removes entries that are no longer relevant, and "
            "organises everything clearly under appropriate headings. "
            "Return ONLY the raw markdown for the new MEMORY.md — no extra commentary.\n\n"
            f"CURRENT MEMORY.md:\n{current_memory[:3000]}\n\n"
            f"THIS WEEK'S LOGS:\n{week_log[:5000]}"
        )

        new_memory = await self._run_agent(prompt, session_id="heartbeat-weekly")

        # Strip any markdown code fence the agent may have wrapped the output in
        lines = new_memory.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        new_memory = "\n".join(lines)

        memory_path.write_text(new_memory, encoding="utf-8")
        logger.info("heartbeat: weekly MEMORY.md updated")
        await _send_telegram("*Weekly consolidation complete* — MEMORY.md updated.")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _run_agent(self, prompt: str, session_id: str) -> str:
        """Invoke agent.query() and return the response text."""
        if hasattr(self._agent, "query"):
            return await self._agent.query(prompt, session_id=session_id)
        # Legacy agno-style agent fallback
        response = await asyncio.to_thread(self._agent.run, prompt, session_id=session_id)
        return response.content if hasattr(response, "content") else str(response)


async def _send_telegram(text: str) -> None:
    """Best-effort Telegram message send — uses the Bot HTTP API directly.

    Does not require the PTB Application instance, so the heartbeat can send
    notifications independently of whether the Telegram polling task is running.
    """
    token = settings.TELEGRAM_JARVIS_TOKEN
    chat_id = settings.TELEGRAM_ALLOWED_CHAT_ID
    if not token or not chat_id:
        logger.debug("heartbeat: Telegram not configured — skipping notification")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": int(chat_id),
        "text": text,
        "parse_mode": "Markdown",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("heartbeat: Telegram notification failed — %s", exc)
