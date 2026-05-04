import email.utils
import imaplib
from contextlib import contextmanager

from mailctl.mime import decode_header_value, parse_attachments, parse_body, parse_message
from mailctl.models import AccountConfig


@contextmanager
def imap_connect(account: AccountConfig):
    cls = imaplib.IMAP4_SSL if account.imap_secure else imaplib.IMAP4
    client = cls(account.imap_host, account.imap_port)
    client.login(account.imap_user, account.imap_pass)
    try:
        yield client
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _uid_list(data: list) -> list[str]:
    if not data or not data[0]:
        return []
    raw = data[0]
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    return text.split() if text.strip() else []


def _decode_flags(raw: object) -> str:
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


def _format_addr(name: str, addr: str) -> str:
    return f"{name} <{addr}>" if name else addr


def list_emails(account: AccountConfig, folder: str = "INBOX", limit: int = 20, offset: int = 0, unseen_only: bool = False) -> dict:
    with imap_connect(account) as client:
        client.select(folder)
        criteria = "UNSEEN" if unseen_only else "ALL"
        _status, uid_data = client.uid("SEARCH", criteria)
        all_uids = list(reversed(_uid_list(uid_data)))
        page_uids = all_uids[offset: offset + limit]
        emails = []
        for uid in page_uids:
            _st, data = client.uid("FETCH", uid, "(RFC822.HEADER FLAGS)")
            if not data or not data[0]:
                continue
            flags_line = _decode_flags(data[0][0])
            msg = parse_message(data[0][1])
            emails.append({
                "uid": uid,
                "from": decode_header_value(msg.get("From", "")),
                "subject": decode_header_value(msg.get("Subject", "")),
                "date": msg.get("Date", ""),
                "seen": "\\Seen" in flags_line,
                "flagged": "\\Flagged" in flags_line,
                "has_attachments": False,
            })
        return {"account": account.name, "folder": folder, "total": len(all_uids), "emails": emails}


def read_email(account: AccountConfig, uid: str, folder: str = "INBOX") -> dict:
    with imap_connect(account) as client:
        client.select(folder)
        _st, data = client.uid("FETCH", uid, "(RFC822 FLAGS)")
        if not data or not data[0] or not data[0][1]:
            raise KeyError(f"UID {uid} not found")
        flags_line = _decode_flags(data[0][0])
        msg = parse_message(data[0][1])
        plain, html = parse_body(msg)
        result = {
            "account": account.name,
            "uid": uid,
            "folder": folder,
            "from": decode_header_value(msg.get("From", "")),
            "message_id": msg.get("Message-ID", ""),
            "references": msg.get("References", ""),
            "to": [_format_addr(n, a) for n, a in email.utils.getaddresses(msg.get_all("To") or [])],
            "cc": [_format_addr(n, a) for n, a in email.utils.getaddresses(msg.get_all("Cc") or [])],
            "subject": decode_header_value(msg.get("Subject", "")),
            "date": msg.get("Date", ""),
            "body": plain or "",
            "attachments": parse_attachments(msg),
            "seen": "\\Seen" in flags_line,
            "flagged": "\\Flagged" in flags_line,
        }
        if html:
            result["html"] = html
        return result


def mark_email(account: AccountConfig, uid: str, folder: str = "INBOX", action: str = "read") -> dict:
    flag_map = {
        "read": ("+FLAGS", "(\\Seen)"),
        "unread": ("-FLAGS", "(\\Seen)"),
        "flag": ("+FLAGS", "(\\Flagged)"),
        "unflag": ("-FLAGS", "(\\Flagged)"),
    }
    if action not in flag_map:
        raise ValueError(f"Unsupported mark action: {action}")
    op, flag = flag_map[action]
    with imap_connect(account) as client:
        client.select(folder)
        client.uid("STORE", uid, op, flag)
    return {"account": account.name, "uid": uid, "folder": folder, "marked": action}


def move_email(account: AccountConfig, uid: str, folder: str = "INBOX", destination: str = "Archive") -> dict:
    with imap_connect(account) as client:
        client.select(folder)
        client.uid("COPY", uid, destination)
        client.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
        client.expunge()
    return {"account": account.name, "uid": uid, "from_folder": folder, "folder": destination, "moved": True}


def unread_count(account: AccountConfig, folders: list[str] | None = None) -> dict:
    counts = {}
    with imap_connect(account) as client:
        for folder in folders or ["INBOX"]:
            _status, data = client.status(folder, "(UNSEEN)")
            raw = data[0].decode("utf-8", errors="replace") if data else ""
            marker = "UNSEEN "
            counts[folder] = int(raw.split(marker, 1)[1].split(")", 1)[0]) if marker in raw else 0
    return {"account": account.name, "counts": counts}


def search_emails(
    account: AccountConfig,
    folder: str = "INBOX",
    from_: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    limit: int = 20,
) -> dict:
    criteria: list[str] = []
    if from_:
        criteria.extend(["FROM", f'"{from_}"'])
    if subject:
        criteria.extend(["SUBJECT", f'"{subject}"'])
    if body:
        criteria.extend(["BODY", f'"{body}"'])
    if not criteria:
        criteria = ["ALL"]
    with imap_connect(account) as client:
        client.select(folder)
        _status, uid_data = client.uid("SEARCH", " ".join(criteria))
    return {"account": account.name, "folder": folder, "uids": _uid_list(uid_data)[:limit]}
