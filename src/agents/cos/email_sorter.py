"""httpx client that calls the protonmail-mcp /sort endpoint."""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_URL = os.environ.get("PROTONMAIL_MCP_URL", "http://protonmail-mcp:3000")
_TIMEOUT = 10.0


def sort_email_after_routing(uid: str, payload: dict) -> dict:
    """Call protonmail-mcp POST /sort after routing an email.

    Args:
        uid:     IMAP UID string (= email_id from the classified payload).
        payload: EmailIntelligencePayload dict. Must contain at minimum:
                 subject (str), body_redacted (str), classification (dict).

    Returns:
        {"sorted": True, "folder": "<name>", "uid": "<uid>"} on success.
        {"sorted": False, "reason": "<reason>"} if no rule matched.
        {"sorted": False, "error": "<msg>"} on network/server failure.
    """
    body = {
        "uid": uid,
        "source_folder": "INBOX",
        "sender": "",                              # fetched server-side from IMAP if needed
        "subject": payload.get("subject", ""),
        "body": payload.get("body_redacted", ""),
        "classification": payload.get("classification", {}),
    }
    try:
        resp = httpx.post(f"{_URL}/sort", json=body, timeout=_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        if result.get("sorted"):
            logger.info("EmailSorter: uid=%s → %s", uid, result.get("folder"))
        else:
            logger.debug("EmailSorter: uid=%s no match — %s", uid, result.get("reason", ""))
        return result
    except Exception as exc:
        logger.warning("EmailSorter: failed uid=%s — %s", uid, exc)
        return {"sorted": False, "error": str(exc)}
