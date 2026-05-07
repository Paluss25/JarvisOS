from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path


async def calendar_list(args: dict) -> dict:
    from agents.mt.tools import _get_calendar_client, _text

    client = _get_calendar_client()
    if client is None:
        return _text("Calendar not configured (RADICALE_URL not set).")
    try:
        result = await asyncio.to_thread(client.list_calendars)
        return _text(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        return _text(f"Calendar unavailable: {exc}")


async def calendar_get_events(args: dict) -> dict:
    from agents.mt.tools import _get_calendar_client, _parse_args, _text

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


async def calendar_create_event(args: dict) -> dict:
    from agents.mt.tools import _get_calendar_client, _parse_args, _parse_datetime, _text

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
        return _text("Conflict: the following events overlap the requested slot:\n" + json.dumps(conflicts, ensure_ascii=False, indent=2))
    if not bool(args.get("confirmed", False)):
        return _text(f"Ready to create '{title}' ({start_str} -> {end_str}). No conflicts found. Call again with confirmed=True to write.")
    try:
        uid = await asyncio.to_thread(client.create_event, title, start, end, args.get("description", ""))
        return _text(f"Event created: '{title}' ({start_str} -> {end_str}) uid={uid}")
    except Exception as exc:
        return _text(f"Calendar create failed: {exc}")


async def calendar_update_event(args: dict) -> dict:
    from agents.mt.tools import _get_calendar_client, _parse_args, _parse_datetime, _text

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
        conflicts = await asyncio.to_thread(client.check_conflicts, start, end)
        conflicts = [c for c in conflicts if c.get("uid") != uid]
    except ValueError as exc:
        return _text(str(exc))
    except Exception as exc:
        return _text(f"Conflict check failed: {exc}")
    if conflicts:
        return _text("Conflict: the following events overlap the new slot:\n" + json.dumps(conflicts, ensure_ascii=False, indent=2))
    if not bool(args.get("confirmed", False)):
        return _text(f"Ready to update event uid={uid} -> '{title}' ({start_str} -> {end_str}). No conflicts. Call again with confirmed=True to write.")
    try:
        await asyncio.to_thread(client.update_event, uid, title, start, end, args.get("description", ""))
        return _text(f"Event updated: uid={uid} -> '{title}' ({start_str} -> {end_str})")
    except ValueError as exc:
        return _text(str(exc))
    except Exception as exc:
        return _text(f"Calendar update failed: {exc}")


async def calendar_delete_event(args: dict) -> dict:
    from agents.mt.tools import _get_calendar_client, _parse_args, _text

    args = _parse_args(args)
    client = _get_calendar_client(args.get("calendar", ""))
    if client is None:
        return _text("Calendar not configured (RADICALE_URL not set).")
    uid = args.get("uid", "").strip()
    if not uid:
        return _text("uid is required.")
    if not bool(args.get("confirmed", False)):
        return _text(f"Ready to delete event uid={uid}. Call again with confirmed=True to delete permanently.")
    try:
        await asyncio.to_thread(client.delete_event, uid)
        return _text(f"Event deleted: uid={uid}")
    except ValueError as exc:
        return _text(str(exc))
    except Exception as exc:
        return _text(f"Calendar delete failed: {exc}")
