from __future__ import annotations


DEFAULT_AGENT_PLUGINS: dict[str, tuple[str, ...]] = {
    "ceo": ("memory-box-tools", "report-issue-tools", "task-tools"),
    "cio": ("memory-box-tools", "report-issue-tools", "cron-tools"),
    "mt": ("calendar-tools", "contacts-tools", "email-digest-tools", "task-tools"),
}
