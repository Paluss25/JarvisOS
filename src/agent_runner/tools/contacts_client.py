from __future__ import annotations

import asyncio
import json


async def contacts_list(args: dict) -> dict:
    from agents.mt.tools import _get_contacts_client, _parse_args, _text

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


async def contacts_search(args: dict) -> dict:
    from agents.mt.tools import _get_contacts_client, _parse_args, _text

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


async def contacts_get(args: dict) -> dict:
    from agents.mt.tools import _get_contacts_client, _parse_args, _text

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


async def contacts_update(args: dict) -> dict:
    from agents.mt.tools import _get_contacts_client, _parse_args, _text

    args = _parse_args(args)
    client = _get_contacts_client(args.get("addressbook", ""))
    if client is None:
        return _text("Calendar not configured (RADICALE_URL not set).")
    uid = args.get("uid", "").strip()
    fn = args.get("fn", "").strip()
    if not uid or not fn:
        return _text("uid and fn are required.")
    if not bool(args.get("confirmed", False)):
        return _text(f"Ready to update contact uid={uid} -> fn='{fn}'. Call again with confirmed=True to write.")
    try:
        await asyncio.to_thread(
            client.update_contact,
            uid,
            fn,
            args.get("email", ""),
            args.get("tel", ""),
            args.get("note", ""),
        )
        return _text(f"Contact updated: uid={uid} -> fn='{fn}'")
    except ValueError as exc:
        return _text(str(exc))
    except Exception as exc:
        return _text(f"Contact update failed: {exc}")


async def contacts_delete(args: dict) -> dict:
    from agents.mt.tools import _get_contacts_client, _parse_args, _text

    args = _parse_args(args)
    client = _get_contacts_client(args.get("addressbook", ""))
    if client is None:
        return _text("Calendar not configured (RADICALE_URL not set).")
    uid = args.get("uid", "").strip()
    if not uid:
        return _text("uid is required.")
    if not bool(args.get("confirmed", False)):
        return _text(f"Ready to delete contact uid={uid}. Call again with confirmed=True to delete permanently.")
    try:
        await asyncio.to_thread(client.delete_contact, uid)
        return _text(f"Contact deleted: uid={uid}")
    except ValueError as exc:
        return _text(str(exc))
    except Exception as exc:
        return _text(f"Contact delete failed: {exc}")
