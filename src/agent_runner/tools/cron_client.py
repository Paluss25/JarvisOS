from __future__ import annotations

from pathlib import Path


async def create_cron(workspace_path: Path, args: dict) -> dict:
    name = str(args.get("name", "")).strip()
    schedule = str(args.get("schedule", "")).strip()
    prompt_text = str(args.get("prompt", "")).strip()
    if not name or not schedule or not prompt_text:
        return _text("name, schedule, and prompt are required.")

    try:
        from agent_runner.scheduler.cron_store import get_store

        store = get_store(workspace_path)
        entry = store.create(
            name=name,
            schedule=schedule,
            prompt=prompt_text,
            session_id=args.get("session_id") or "",
            telegram_notify=bool(args.get("telegram_notify", False)),
        )
        return _text(f"Created cron '{entry.name}' (id={entry.id}, schedule={entry.schedule})")
    except Exception as exc:
        return _text(f"Error: {exc}")


async def list_crons(workspace_path: Path) -> dict:
    try:
        from agent_runner.scheduler.cron_store import get_store

        store = get_store(workspace_path)
        entries = store.all()
        if not entries:
            return _text("No scheduled tasks.")
        lines = []
        for entry in entries:
            status = entry.last_status if entry.last_run else "never run"
            enabled = "enabled" if entry.enabled else "disabled"
            builtin_tag = " [builtin]" if entry.builtin else ""
            lines.append(
                f"- **{entry.name}** (id={entry.id}){builtin_tag}\n"
                f"  schedule={entry.schedule}, {enabled}, last={status}\n"
                f"  telegram_notify={entry.telegram_notify}"
            )
        return _text("\n\n".join(lines))
    except Exception as exc:
        return _text(f"Error: {exc}")


async def update_cron(workspace_path: Path, args: dict) -> dict:
    cron_id = str(args.get("id", "")).strip()
    if not cron_id:
        return _text("id is required.")
    updates = {k: v for k, v in args.items() if k != "id" and v is not None}
    if not updates:
        return _text("No fields to update.")
    try:
        from agent_runner.scheduler.cron_store import get_store

        store = get_store(workspace_path)
        entry = store.update(cron_id, **updates)
        return _text(f"Updated cron '{entry.name}' (id={entry.id})")
    except Exception as exc:
        return _text(f"Error: {exc}")


async def delete_cron(workspace_path: Path, args: dict) -> dict:
    cron_id = str(args.get("id", "")).strip()
    if not cron_id:
        return _text("id is required.")
    try:
        from agent_runner.scheduler.cron_store import get_store

        store = get_store(workspace_path)
        store.delete(cron_id)
        return _text(f"Deleted cron id={cron_id}")
    except Exception as exc:
        return _text(f"Error: {exc}")


def _text(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}]}
