"""mailctl-backed email sorter for COS routing decisions."""

import json
import logging
import subprocess

logger = logging.getLogger(__name__)


def _account_for(uid: str, payload: dict) -> str:
    account = str(payload.get("account", "")).strip().lower()
    if account in {"protonmail", "gmx"}:
        return account
    uid_lower = uid.strip().lower()
    if uid_lower.startswith("gmx-"):
        return "gmx"
    return "protonmail"


def _imap_uid(uid: str, account: str) -> str:
    prefix = f"{account}-"
    if uid.lower().startswith(prefix):
        return uid[len(prefix):]
    return uid


def sort_email_after_routing(uid: str, payload: dict) -> dict:
    """Move an email after routing by delegating mailbox access to mailctl."""
    account = _account_for(uid, payload)
    imap_uid = _imap_uid(uid, account)
    try:
        proc = subprocess.run(
            ["mailctl", "sort", "--account", account, "--uid", imap_uid, "--json"],
            capture_output=True,
            check=False,
            text=True,
            timeout=20.0,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or f"exit_status={proc.returncode}"
            raise RuntimeError(detail)
        result = json.loads(proc.stdout)
        if result.get("sorted"):
            logger.info("EmailSorter: uid=%s account=%s -> %s", uid, account, result.get("folder"))
        else:
            logger.debug("EmailSorter: uid=%s account=%s no match - %s", uid, account, result.get("reason", ""))
        return result
    except Exception as exc:
        logger.warning("EmailSorter: failed uid=%s account=%s - %s", uid, account, exc)
        return {"sorted": False, "account": account, "uid": imap_uid, "error": str(exc)}
