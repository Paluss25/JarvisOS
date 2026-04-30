"""In-process MCP server exposing MT custom tools."""

import asyncio
import datetime
import json
import logging
import os
import re
import uuid
import zoneinfo
from pathlib import Path

import httpx
from agents.mt.calendar_client import CalendarClient
from agents.mt.contacts_client import ContactsClient

logger = logging.getLogger(__name__)


def _parse_args(args) -> dict:
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return args if isinstance(args, dict) else {}


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": str(s)}]}


def _parse_iso_datetime(value: str) -> datetime.datetime:
    """Parse an ISO-8601 datetime, accepting a trailing 'Z' for UTC."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(s)


def _ics_escape(text: str) -> str:
    """Escape special characters in ICS TEXT-typed fields (RFC 5545 §3.3.11)."""
    return (
        text.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n")
    )


def _ics_dtline(prop: str, dt: datetime.datetime) -> str:
    """Render a DTSTART/DTEND line. Naive datetimes are emitted as floating local time;
    aware UTC datetimes use the 'Z' suffix; other tz-aware datetimes use TZID."""
    if dt.tzinfo is None:
        return f"{prop}:{dt.strftime('%Y%m%dT%H%M%S')}"
    if dt.utcoffset() == datetime.timedelta(0):
        return f"{prop}:{dt.astimezone(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    tz_name = str(dt.tzinfo)
    return f"{prop};TZID={tz_name}:{dt.strftime('%Y%m%dT%H%M%S')}"


def _mark_processed(workspace: Path, email_id: str) -> None:
    _mark_email_state(workspace, email_id=email_id, status="processed")
    processed_path = workspace / "processed_ids.txt"
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    with open(processed_path, "a", encoding="utf-8") as handle:
        handle.write(email_id + "\n")


def _email_state_key(email_id: str, account: str = "", received_at: str = "") -> str:
    return "|".join(part for part in (account.strip(), email_id.strip(), received_at.strip()) if part)


def _mark_email_state(
    workspace: Path,
    email_id: str,
    status: str,
    account: str = "",
    received_at: str = "",
    metadata: dict | None = None,
) -> None:
    if not email_id:
        return
    state_path = workspace / "processed_email_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        if not isinstance(state, dict):
            state = {}
    except (json.JSONDecodeError, ValueError, OSError):
        state = {}
    key = _email_state_key(email_id, account, received_at)
    state[key] = {
        "email_id": email_id,
        "account": account,
        "received_at": received_at,
        "status": status,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **(metadata or {}),
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_processed_ids(workspace: Path) -> set[str]:
    processed_path = workspace / "processed_ids.txt"
    processed = set()
    if processed_path.exists():
        processed.update(processed_path.read_text(encoding="utf-8").splitlines())
    state_path = workspace / "processed_email_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                for key, record in state.items():
                    if isinstance(record, dict) and record.get("status") == "processed":
                        processed.add(key)
                        if record.get("email_id"):
                            processed.add(str(record["email_id"]))
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    return processed


def _read_digest(digest_path: Path, processed_ids: set[str], max_items: int = 10) -> list[dict]:
    if not digest_path.exists():
        return []
    # Read newest-first so a backlog does not starve recent emails.
    items: list[dict] = []
    for line in reversed(digest_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        uid = str(entry.get("email_id", ""))
        key = _email_state_key(
            uid,
            str(entry.get("account", "")),
            str(entry.get("received_at", "")),
        )
        if uid and uid not in processed_ids and key not in processed_ids:
            items.append(entry)
            if len(items) >= max_items:
                break
    return items


def _parse_datetime(s: str) -> datetime.datetime:
    """Parse ISO 8601 datetime string. 'Z' suffix → UTC; naive → treated as-is."""
    s = s.strip()
    try:
        if s.endswith("Z"):
            return datetime.datetime.fromisoformat(s[:-1]).replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(
            f"Invalid datetime '{s}': use YYYY-MM-DDTHH:MM:SS or YYYY-MM-DDTHH:MM:SSZ"
        ) from exc


def _get_calendar_client(calendar_name: str = "") -> "CalendarClient | None":
    """Build CalendarClient from env vars; return None if RADICALE_URL not set.

    calendar_name overrides RADICALE_CALENDAR env var when provided.
    """
    url = os.environ.get("RADICALE_URL", "").strip()
    if not url:
        return None
    user = os.environ.get("RADICALE_USER", "").strip()
    password = os.environ.get("RADICALE_PASSWORD", "").strip()
    name = calendar_name.strip() or os.environ.get("RADICALE_CALENDAR", "").strip()
    return CalendarClient(url=url, user=user, password=password, calendar_name=name)


def _get_contacts_client(addressbook_name: str = "") -> "ContactsClient | None":
    """Build ContactsClient from env vars; return None if RADICALE_URL not set."""
    url = os.environ.get("RADICALE_URL", "").strip()
    if not url:
        return None
    user = os.environ.get("RADICALE_USER", "").strip()
    password = os.environ.get("RADICALE_PASSWORD", "").strip()
    name = addressbook_name.strip() or os.environ.get("RADICALE_CONTACTS", "").strip()
    return ContactsClient(url=url, user=user, password=password, addressbook_name=name)


def _task_create(workspace: Path, title: str, notes: str = "", due_date: str = "") -> dict:
    task_log = workspace / "task_log.json"
    tasks = json.loads(task_log.read_text(encoding="utf-8")) if task_log.exists() else []
    task = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "notes": notes,
        "due_date": due_date,
        "status": "open",
        "created_at": datetime.datetime.now().isoformat(),
    }
    tasks.append(task)
    task_log.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    return task


def _task_list(workspace: Path, status: str = "") -> list[dict]:
    task_log = workspace / "task_log.json"
    if not task_log.exists():
        return []
    tasks = json.loads(task_log.read_text(encoding="utf-8"))
    if status:
        tasks = [task for task in tasks if task.get("status", "").lower() == status.lower()]
    tasks.sort(key=lambda task: task.get("due_date") or "9999-12-31")
    return tasks


_TRAINING_TITLE_MAP = {
    "run": "🏃 Run",
    "walk": "🚶 Walk",
    "strength_metabolic": "💪 Strength & Metabolic",
    "strength": "💪 Strength",
}


def _build_training_ical(uid: str, title: str, dtstart: datetime.datetime, dtend: datetime.datetime, description: str) -> str:
    """Build a VCALENDAR iCal string for a single training session event."""
    fmt = "%Y%m%dT%H%M%S"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//JarvisOS//TrainingSync//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{title}",
        f"DTSTART;TZID=Europe/Rome:{dtstart.strftime(fmt)}",
        f"DTEND;TZID=Europe/Rome:{dtend.strftime(fmt)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_ics_escape(description)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


try:
    from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    create_sdk_mcp_server = None
    sdk_tool = None


def create_mt_mcp_server(workspace_path: Path, redis_a2a=None):
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
        return None

    @sdk_tool("daily_log", "Append a timestamped entry to today's memory log. message is required.", {"message": {"type": "string", "default": ""}})
    async def daily_log(args: dict) -> dict:
        args = _parse_args(args)
        message = args.get("message", "")
        if not message:
            return _text("No message provided.")
        try:
            from agent_runner.memory.daily_logger import DailyLogger

            DailyLogger(workspace_path).log(message)
            return _text(f"Logged: {message[:80]}")
        except Exception as exc:
            logger.error("daily_log: failed — %s", exc)
            return _text(f"Failed to log: {exc}")

    @sdk_tool(
        "memory_search",
        "Search across MEMORY.md and daily logs using text matching.",
        {"query": str, "top_k": {"type": "integer", "default": 5}},
    )
    async def memory_search(args: dict) -> dict:
        args = _parse_args(args)
        query = args.get("query", "").strip()
        if not query:
            return _text("No query provided.")
        top_k = int(args.get("top_k") or 5)
        query_lower = query.lower()
        memory_dir = workspace_path / "memory"
        dated_files = sorted(memory_dir.glob("*.md"), reverse=True) if memory_dir.exists() else []
        files_to_search = list(dated_files) + [workspace_path / "MEMORY.md"]
        results = []
        for file_path in files_to_search:
            if not file_path.exists():
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").split("\n")
            except OSError:
                continue
            for idx, line in enumerate(lines):
                if query_lower in line.lower():
                    start = max(0, idx - 2)
                    end = min(len(lines), idx + 3)
                    snippet = "\n".join(lines[start:end])
                    results.append(f"**{file_path.name}** (line {idx + 1}):\n```\n{snippet}\n```")
                    if len(results) >= top_k:
                        break
            if len(results) >= top_k:
                break
        if not results:
            return _text(f"No results found for '{query}'.")
        return _text("\n\n---\n\n".join(results))

    @sdk_tool(
        "memory_get",
        "Read a specific memory file from the workspace. Path relative to workspace root.",
        {"path": str, "start_line": {"type": "integer", "default": 1}, "num_lines": {"type": "integer", "default": 50}},
    )
    async def memory_get(args: dict) -> dict:
        args = _parse_args(args)
        rel_path = args.get("path", "").strip()
        if not rel_path:
            return _text("No path provided.")
        target = (workspace_path / rel_path).resolve()
        try:
            target.relative_to(workspace_path.resolve())
        except ValueError:
            return _text("Access denied: path is outside the workspace directory.")
        if not target.exists():
            return _text(f"File not found: {rel_path}")
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return _text(f"Error reading {rel_path}: {exc}")
        start_line = args.get("start_line")
        num_lines = args.get("num_lines")
        if start_line is not None or num_lines is not None:
            lines = content.split("\n")
            start = int(start_line or 1) - 1
            length = int(num_lines) if num_lines is not None else len(lines)
            content = "\n".join(lines[start : start + length])
        return _text(content)

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool

        _send_message_fn = create_send_message_tool("mt", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Set wait_response=false for one-way notifications; default true blocks until reply.",
            {"to": str, "message": str, "wait_response": bool},
        )
        async def send_message(args: dict) -> dict:
            args = _parse_args(args)
            return _text(await _send_message_fn(args))

        @sdk_tool(
            "forward_to_cos",
            "Forward a payload to ChiefOfStaff (COS) via A2A Redis bus. "
            "Marks the email as processed so it is not re-polled.",
            {
                "type": "object",
                "properties": {
                    "payload_json": {"type": "string"},
                    "reason": {"type": "string"},
                    "email_id": {"type": "string"},
                },
                "required": ["payload_json", "reason"],
            },
        )
        async def forward_to_cos(args: dict) -> dict:
            args = _parse_args(args)
            payload_raw = args.get("payload_json", "").strip()
            reason = args.get("reason", "escalation from MT").strip()
            email_id = args.get("email_id", "").strip()
            if not payload_raw:
                return _text("payload_json is required.")
            # Fallback: extract email_id from payload_json so legacy callers still advance the cursor.
            if not email_id:
                try:
                    payload_obj = json.loads(payload_raw)
                    if isinstance(payload_obj, dict):
                        email_id = str(payload_obj.get("email_id", "")).strip()
                except (json.JSONDecodeError, ValueError):
                    pass
            message = f"MT escalation: {reason}\n\nPayload:\n{payload_raw}"
            result = await _send_message_fn({"to": "cos", "message": message})
            if email_id:
                _mark_email_state(workspace_path, email_id=email_id, status="processed")
                _mark_processed(workspace_path, email_id)
            return _text(f"Forwarded to COS. Response: {result}")

    else:
        send_message = None
        forward_to_cos = None

    @sdk_tool(
        "cron_create",
        "Create a new scheduled task. schedule format: daily@HH:MM | weekly@DOW@HH:MM | once@YYYY-MM-DD@HH:MM.",
        {"name": str, "schedule": str, "prompt": str, "session_id": str, "telegram_notify": bool},
    )
    async def cron_create(args: dict) -> dict:
        args = _parse_args(args)
        name = args.get("name", "").strip()
        schedule = args.get("schedule", "").strip()
        prompt_text = args.get("prompt", "").strip()
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

    @sdk_tool("cron_list", "List all scheduled tasks with their current status.", {})
    async def cron_list(args: dict) -> dict:
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

    @sdk_tool(
        "cron_update",
        "Update a scheduled task by its id.",
        {"id": str, "name": str, "schedule": str, "prompt": str, "session_id": str, "telegram_notify": bool, "enabled": bool},
    )
    async def cron_update(args: dict) -> dict:
        args = _parse_args(args)
        cron_id = args.get("id", "").strip()
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

    @sdk_tool("cron_delete", "Delete a user-created scheduled task by its id.", {"id": str})
    async def cron_delete(args: dict) -> dict:
        args = _parse_args(args)
        cron_id = args.get("id", "").strip()
        if not cron_id:
            return _text("id is required.")
        try:
            from agent_runner.scheduler.cron_store import get_store

            store = get_store(workspace_path)
            store.delete(cron_id)
            return _text(f"Deleted cron id={cron_id}")
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool("read_email_digest", "Read unprocessed entries from the MT email digest.", {
        "max_items": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
    })
    async def read_email_digest(args: dict) -> dict:
        args = _parse_args(args)
        max_items = int(args.get("max_items") or 10)
        digest_path = Path(os.environ.get("MT_DIGEST_PATH", "/app/shared/mt_digest.json"))
        processed_ids = _read_processed_ids(workspace_path)
        items = _read_digest(digest_path, processed_ids, max_items=max_items)
        if not items:
            return _text("No new digest entries.")
        return _text(json.dumps(items, ensure_ascii=False, indent=2))

    @sdk_tool(
        "sort_email",
        "Move an email to the appropriate folder via the account-specific email-mcp /sort endpoint.",
        {"email_id": str, "payload_json": str},
    )
    async def sort_email_tool(args: dict) -> dict:
        args = _parse_args(args)
        email_id = args.get("email_id", "").strip()
        payload_raw = args.get("payload_json", "").strip()
        if not email_id or not payload_raw:
            return _text("email_id and payload_json are required.")
        try:
            payload = json.loads(payload_raw)
        except (json.JSONDecodeError, ValueError) as exc:
            return _text(f"Invalid payload_json: {exc}")
        try:
            from agents.mt.email_sorter import sort_email as sort_email_client

            # Offload blocking client to a threadpool — do not stall the event loop.
            result = await asyncio.to_thread(sort_email_client, email_id, payload)
            _mark_email_state(
                workspace_path,
                email_id=email_id,
                account=str(payload.get("account", "")),
                received_at=str(payload.get("received_at", "")),
                status="processed",
                metadata={"sort_result": result},
            )
            _mark_processed(workspace_path, email_id)
            return _text(json.dumps(result))
        except Exception as exc:
            logger.error("sort_email: failed for %s — %s", email_id, exc)
            return _text(f"Sort failed for {email_id}: {exc}")

    @sdk_tool(
        "draft_reply",
        "Generate a reply draft scaffold and store it under drafts/.",
        {"email_id": str, "subject": str, "sender": str, "body_redacted": str, "draft_instructions": str},
    )
    async def draft_reply(args: dict) -> dict:
        args = _parse_args(args)
        email_id = args.get("email_id", "").strip()
        subject = args.get("subject", "").strip()
        sender = args.get("sender", "").strip()
        body = args.get("body_redacted", "").strip()
        instructions = args.get("draft_instructions", "").strip()
        if not email_id:
            return _text("email_id is required.")
        drafts_dir = workspace_path / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        draft_path = drafts_dir / f"{email_id}.txt"
        draft_text = (
            "Ciao,\n\n"
            "ho ricevuto il tuo messaggio. Ti rispondo a breve con i dettagli.\n\n"
            "A presto,\n"
            "Emiliano"
        )
        if instructions:
            draft_text = (
                "Ciao,\n\n"
                f"{instructions}\n\n"
                "A presto,\n"
                "Emiliano"
            )
        draft_path.write_text(
            f"Subject: Re: {subject}\n"
            f"To: {sender}\n"
            "Status: draft_pending\n"
            f"--- Original ---\n{body}\n"
            f"--- Instructions ---\n{instructions or 'none'}\n"
            f"--- Draft ---\n{draft_text}\n",
            encoding="utf-8",
        )
        status_path = drafts_dir / "draft_status.json"
        try:
            draft_status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
            if not isinstance(draft_status, dict):
                draft_status = {}
        except (json.JSONDecodeError, ValueError, OSError):
            draft_status = {}
        draft_status[email_id] = {
            "status": "draft_pending",
            "subject": subject,
            "sender": sender,
            "path": f"drafts/{email_id}.txt",
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        status_path.write_text(json.dumps(draft_status, ensure_ascii=False, indent=2), encoding="utf-8")
        _mark_email_state(
            workspace_path,
            email_id=email_id,
            status="draft_pending",
            metadata={"draft_path": f"drafts/{email_id}.txt"},
        )
        return _text(f"draft_pending saved to drafts/{email_id}.txt. Re: {subject} | To: {sender}")

    @sdk_tool(
        "create_task",
        "Create a new task entry in task_log.json.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "notes": {"type": "string"},
                "due_date": {"type": "string"},
            },
            "required": ["title"],
        },
    )
    async def create_task(args: dict) -> dict:
        args = _parse_args(args)
        title = args.get("title", "").strip()
        if not title:
            return _text("title is required.")
        task = _task_create(
            workspace_path,
            title=title,
            notes=args.get("notes", "").strip(),
            due_date=args.get("due_date", "").strip(),
        )
        return _text(json.dumps(task))

    @sdk_tool(
        "list_tasks",
        "List tasks from task_log.json, optionally filtered by status.",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
            },
            "required": [],
        },
    )
    async def list_tasks(args: dict) -> dict:
        args = _parse_args(args)
        tasks = _task_list(workspace_path, status=args.get("status", "").strip())
        if not tasks:
            return _text("No tasks found.")
        return _text(json.dumps(tasks, ensure_ascii=False, indent=2))

    @sdk_tool("calendar_list", "List all calendars available in Radicale.", {})
    async def calendar_list(args: dict) -> dict:
        client = _get_calendar_client()
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        try:
            result = await asyncio.to_thread(client.list_calendars)
            return _text(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as exc:
            return _text(f"Calendar unavailable: {exc}")

    @sdk_tool(
        "calendar_get_events",
        "Fetch calendar events for a date range. Dates: YYYY-MM-DD. calendar: optional name (lavoro/sport), defaults to RADICALE_CALENDAR.",
        {"start_date": str, "end_date": str, "calendar": {"type": "string", "default": ""}},
    )
    async def calendar_get_events(args: dict) -> dict:
        args = _parse_args(args)
        client = _get_calendar_client(args.get("calendar", ""))
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        start_str = args.get("start_date") or datetime.date.today().isoformat()
        end_str = args.get("end_date") or start_str
        try:
            start = datetime.date.fromisoformat(start_str)
            end = datetime.date.fromisoformat(end_str)
            events = await asyncio.to_thread(client.get_events, start, end)
            if not events:
                return _text("No events found in the requested range.")
            return _text(json.dumps(events, ensure_ascii=False, indent=2))
        except Exception as exc:
            return _text(f"Calendar fetch failed: {exc}")

    @sdk_tool(
        "calendar_create_event",
        (
            "Create a calendar event. Datetimes: ISO 8601 (YYYY-MM-DDTHH:MM:SS or ...Z). "
            "calendar: optional name (lavoro/sport), defaults to RADICALE_CALENDAR. "
            "Call with confirmed=False first to check for conflicts. "
            "Call again with confirmed=True to actually write."
        ),
        {
            "title": str,
            "start_datetime": str,
            "end_datetime": str,
            "description": {"type": "string", "default": ""},
            "calendar": {"type": "string", "default": ""},
            "confirmed": {"type": "boolean", "default": False},
        },
    )
    async def calendar_create_event(args: dict) -> dict:
        args = _parse_args(args)
        client = _get_calendar_client(args.get("calendar", ""))
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        title = args.get("title", "").strip()
        start_str = args.get("start_datetime", "").strip()
        end_str = args.get("end_datetime", "").strip()
        if not title or not start_str or not end_str:
            return _text("title, start_datetime, and end_datetime are required.")
        try:
            start = _parse_datetime(start_str)
            end = _parse_datetime(end_str)
        except ValueError as exc:
            return _text(str(exc))
        try:
            conflicts = await asyncio.to_thread(client.check_conflicts, start, end)
        except Exception as exc:
            return _text(f"Conflict check failed: {exc}")
        if conflicts:
            return _text(
                "Conflict: the following events overlap the requested slot:\n"
                + json.dumps(conflicts, ensure_ascii=False, indent=2)
            )
        confirmed = bool(args.get("confirmed", False))
        if not confirmed:
            return _text(
                f"Ready to create '{title}' ({start_str} → {end_str}). "
                "No conflicts found. Call again with confirmed=True to write."
            )
        try:
            uid = await asyncio.to_thread(client.create_event, title, start, end, args.get("description", ""))
            return _text(f"Event created: '{title}' ({start_str} → {end_str}) uid={uid}")
        except Exception as exc:
            return _text(f"Calendar create failed: {exc}")

    @sdk_tool(
        "calendar_update_event",
        (
            "Update an existing calendar event by UID. All fields required — pass existing "
            "values unchanged if only one field needs updating. Datetimes: ISO 8601. "
            "calendar: optional name (lavoro/sport), defaults to RADICALE_CALENDAR. "
            "Call with confirmed=False to preview; confirmed=True to write."
        ),
        {
            "uid": str,
            "title": str,
            "start_datetime": str,
            "end_datetime": str,
            "description": {"type": "string", "default": ""},
            "calendar": {"type": "string", "default": ""},
            "confirmed": {"type": "boolean", "default": False},
        },
    )
    async def calendar_update_event(args: dict) -> dict:
        args = _parse_args(args)
        client = _get_calendar_client(args.get("calendar", ""))
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        uid = args.get("uid", "").strip()
        title = args.get("title", "").strip()
        start_str = args.get("start_datetime", "").strip()
        end_str = args.get("end_datetime", "").strip()
        if not uid or not title or not start_str or not end_str:
            return _text("uid, title, start_datetime, and end_datetime are required.")
        try:
            start = _parse_datetime(start_str)
            end = _parse_datetime(end_str)
        except ValueError as exc:
            return _text(str(exc))
        try:
            conflicts = await asyncio.to_thread(client.check_conflicts, start, end)
            conflicts = [c for c in conflicts if c.get("uid") != uid]
        except Exception as exc:
            return _text(f"Conflict check failed: {exc}")
        if conflicts:
            return _text(
                "Conflict: the following events overlap the new slot:\n"
                + json.dumps(conflicts, ensure_ascii=False, indent=2)
            )
        confirmed = bool(args.get("confirmed", False))
        if not confirmed:
            return _text(
                f"Ready to update event uid={uid} → '{title}' ({start_str} → {end_str}). "
                "No conflicts. Call again with confirmed=True to write."
            )
        try:
            await asyncio.to_thread(client.update_event, uid, title, start, end, args.get("description", ""))
            return _text(f"Event updated: uid={uid} → '{title}' ({start_str} → {end_str})")
        except ValueError as exc:
            return _text(str(exc))
        except Exception as exc:
            return _text(f"Calendar update failed: {exc}")

    @sdk_tool(
        "calendar_delete_event",
        "Delete a calendar event by UID. calendar: optional name (lavoro/sport), defaults to RADICALE_CALENDAR. Call with confirmed=False to preview; confirmed=True to delete.",
        {
            "uid": str,
            "calendar": {"type": "string", "default": ""},
            "confirmed": {"type": "boolean", "default": False},
        },
    )
    async def calendar_delete_event(args: dict) -> dict:
        args = _parse_args(args)
        client = _get_calendar_client(args.get("calendar", ""))
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        uid = args.get("uid", "").strip()
        if not uid:
            return _text("uid is required.")
        confirmed = bool(args.get("confirmed", False))
        if not confirmed:
            return _text(
                f"Ready to delete event uid={uid}. "
                "Call again with confirmed=True to delete permanently."
            )
        try:
            await asyncio.to_thread(client.delete_event, uid)
            return _text(f"Event deleted: uid={uid}")
        except ValueError as exc:
            return _text(str(exc))
        except Exception as exc:
            return _text(f"Calendar delete failed: {exc}")

    @sdk_tool(
        "contacts_list",
        "List all contacts in Radicale. addressbook: optional address book name, defaults to RADICALE_CONTACTS.",
        {"addressbook": {"type": "string", "default": ""}},
    )
    async def contacts_list(args: dict) -> dict:
        args = _parse_args(args)
        client = _get_contacts_client(args.get("addressbook", ""))
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        try:
            result = await asyncio.to_thread(client.list_contacts)
            if not result:
                return _text("No contacts found.")
            return _text(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as exc:
            return _text(f"Contacts unavailable: {exc}")

    @sdk_tool(
        "contacts_search",
        "Search contacts by name or email. addressbook: optional address book name.",
        {"query": str, "addressbook": {"type": "string", "default": ""}},
    )
    async def contacts_search(args: dict) -> dict:
        args = _parse_args(args)
        client = _get_contacts_client(args.get("addressbook", ""))
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        query = args.get("query", "").strip()
        if not query:
            return _text("query is required.")
        try:
            result = await asyncio.to_thread(client.search_contacts, query)
            if not result:
                return _text(f"No contacts found matching '{query}'.")
            return _text(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as exc:
            return _text(f"Contacts search failed: {exc}")

    @sdk_tool(
        "contacts_get",
        "Get a specific contact by UID. addressbook: optional address book name.",
        {"uid": str, "addressbook": {"type": "string", "default": ""}},
    )
    async def contacts_get(args: dict) -> dict:
        args = _parse_args(args)
        client = _get_contacts_client(args.get("addressbook", ""))
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        uid = args.get("uid", "").strip()
        if not uid:
            return _text("uid is required.")
        try:
            result = await asyncio.to_thread(client.get_contact, uid)
            return _text(json.dumps(result, ensure_ascii=False, indent=2))
        except ValueError as exc:
            return _text(str(exc))
        except Exception as exc:
            return _text(f"Contact fetch failed: {exc}")

    @sdk_tool(
        "contacts_update",
        (
            "Update a contact by UID. addressbook: optional. "
            "Call with confirmed=False to preview; confirmed=True to write."
        ),
        {
            "uid": str,
            "fn": str,
            "email": {"type": "string", "default": ""},
            "tel": {"type": "string", "default": ""},
            "note": {"type": "string", "default": ""},
            "addressbook": {"type": "string", "default": ""},
            "confirmed": {"type": "boolean", "default": False},
        },
    )
    async def contacts_update(args: dict) -> dict:
        args = _parse_args(args)
        client = _get_contacts_client(args.get("addressbook", ""))
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        uid = args.get("uid", "").strip()
        fn = args.get("fn", "").strip()
        if not uid or not fn:
            return _text("uid and fn are required.")
        confirmed = bool(args.get("confirmed", False))
        if not confirmed:
            return _text(
                f"Ready to update contact uid={uid} → fn='{fn}'. "
                "Call again with confirmed=True to write."
            )
        try:
            await asyncio.to_thread(
                client.update_contact,
                uid,
                fn,
                args.get("email", ""),
                args.get("tel", ""),
                args.get("note", ""),
            )
            return _text(f"Contact updated: uid={uid} → fn='{fn}'")
        except ValueError as exc:
            return _text(str(exc))
        except Exception as exc:
            return _text(f"Contact update failed: {exc}")

    @sdk_tool(
        "contacts_delete",
        "Delete a contact by UID. addressbook: optional. confirmed=False to preview; confirmed=True to delete.",
        {
            "uid": str,
            "addressbook": {"type": "string", "default": ""},
            "confirmed": {"type": "boolean", "default": False},
        },
    )
    async def contacts_delete(args: dict) -> dict:
        args = _parse_args(args)
        client = _get_contacts_client(args.get("addressbook", ""))
        if client is None:
            return _text("Calendar not configured (RADICALE_URL not set).")
        uid = args.get("uid", "").strip()
        if not uid:
            return _text("uid is required.")
        confirmed = bool(args.get("confirmed", False))
        if not confirmed:
            return _text(
                f"Ready to delete contact uid={uid}. "
                "Call again with confirmed=True to delete permanently."
            )
        try:
            await asyncio.to_thread(client.delete_contact, uid)
            return _text(f"Contact deleted: uid={uid}")
        except ValueError as exc:
            return _text(str(exc))
        except Exception as exc:
            return _text(f"Contact delete failed: {exc}")

    from agent_runner.tools.report_issue import (
        create_report_issue_tool,
        REPORT_ISSUE_DESCRIPTION,
        REPORT_ISSUE_SCHEMA,
    )

    _report_issue_fn = create_report_issue_tool("mt")

    @sdk_tool("report_issue", REPORT_ISSUE_DESCRIPTION, REPORT_ISSUE_SCHEMA)
    async def report_issue(args: dict) -> dict:
        return await _report_issue_fn(args)

    @sdk_tool(
        "sync_training_week",
        "Sync a week's training plan from sport_metrics DB to the TrainingPlan Radicale calendar. "
        "Reads rows from training_plan table, computes real dates, and upserts CalDAV events. "
        "week_number is the ISO week number (1-53). year defaults to current year if omitted.",
        {
            "week_number": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
            "year": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        },
    )
    async def sync_training_week(args: dict) -> dict:
        import asyncpg
        args = _parse_args(args)
        week_number = int(args.get("week_number", 0))
        if not week_number:
            return _text("week_number is required.")
        year = int(args.get("year", 0))
        db_url = os.environ.get("SPORT_POSTGRES_URL")
        if not db_url:
            return _text("SPORT_POSTGRES_URL not configured")
        calendar_name = os.environ.get("RADICALE_TRAINING_CALENDAR", "TrainingPlan")

        try:
            conn = await asyncpg.connect(db_url)
            try:
                rows = await conn.fetch(
                    "SELECT session_type, day_of_week, planned_duration, notes, "
                    "planned_intensity, status, created_at "
                    "FROM training_plan WHERE week_number = $1 AND user_id = 1 "
                    "ORDER BY day_of_week",
                    week_number,
                )
            finally:
                await conn.close()
        except Exception as exc:
            return _text(f"DB unavailable: {exc}")

        if not rows:
            return _text(json.dumps({"synced": 0, "skipped": 0, "week": week_number, "year": year or datetime.date.today().isocalendar()[0], "calendar": calendar_name}))

        # Resolve year
        if year <= 0:
            year = rows[0]["created_at"].year

        client = _get_calendar_client()
        if client is None:
            return _text("CalDAV unavailable: RADICALE_URL not set")
        try:
            cal_url = await asyncio.to_thread(client._ensure_calendar, calendar_name)
        except Exception as exc:
            return _text(f"CalDAV unavailable: {exc}")

        rome = zoneinfo.ZoneInfo("Europe/Rome")
        synced = 0
        skipped = 0

        for row in rows:
            session_type = row["session_type"]
            planned_duration = row["planned_duration"]
            if session_type == "rest" or planned_duration == 0:
                skipped += 1
                continue

            day_of_week = row["day_of_week"]
            uid = f"training-{year}w{week_number:02d}d{day_of_week}"
            title = _TRAINING_TITLE_MAP.get(session_type, f"🏋️ {session_type.replace('_', ' ').title()}")

            # DB convention is Postgres EXTRACT(DOW): 0=Sun, 1=Mon, ..., 6=Sat.
            # ISO calendar weekday is 1=Mon, ..., 7=Sun. Sunday wraps from 0 -> 7.
            iso_weekday = day_of_week if day_of_week != 0 else 7
            date = datetime.date.fromisocalendar(year, week_number, iso_weekday)
            dtstart = datetime.datetime(date.year, date.month, date.day, 18, 0, 0, tzinfo=rome)
            dtend = dtstart + datetime.timedelta(minutes=planned_duration)

            notes = row.get("notes") or ""
            intensity = row.get("planned_intensity") or ""
            status_val = row.get("status") or "planned"
            description = (
                f"Type: {session_type.replace('_', ' ').title()} | "
                f"Intensity: {intensity} | "
                f"Duration: {planned_duration}min | "
                f"Status: {status_val}"
            )
            if notes:
                description += f"\n{notes}"

            ical = _build_training_ical(uid, title, dtstart, dtend, description)
            await asyncio.to_thread(client.upsert_event, cal_url, uid, ical)
            synced += 1

        return _text(json.dumps({"synced": synced, "skipped": skipped, "week": week_number, "year": year, "calendar": calendar_name}))

    all_tools = [
        daily_log,
        memory_search,
        memory_get,
        cron_create,
        cron_list,
        cron_update,
        cron_delete,
        read_email_digest,
        sort_email_tool,
        draft_reply,
        create_task,
        list_tasks,
        calendar_list,
        calendar_get_events,
        calendar_create_event,
        calendar_update_event,
        calendar_delete_event,
        contacts_list,
        contacts_search,
        contacts_get,
        contacts_update,
        contacts_delete,
        report_issue,
        sync_training_week,
    ]
    if send_message is not None:
        all_tools.append(send_message)
    if forward_to_cos is not None:
        all_tools.append(forward_to_cos)
    from agent_runner.tools.memory_box import create_query_memory_tool
    _query_memory = create_query_memory_tool("mt")
    if _query_memory is not None:
        all_tools.append(_query_memory)

    logger.info("mcp_server: MT tools registered (%d tools)", len(all_tools))
    return create_sdk_mcp_server(name="mt-tools", tools=all_tools)
