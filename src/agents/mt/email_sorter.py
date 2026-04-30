"""httpx client calling account-specific email-mcp /sort endpoints."""

import os

import httpx

_DEFAULT_URLS = {
    "protonmail": "http://protonmail-mcp:3000",
    "gmx": "http://gmx-mcp:3001",
}


def _endpoint_for(payload: dict) -> str:
    account = str(payload.get("account", "")).strip().lower()
    if not account:
        uid = str(payload.get("email_id", "")).strip().lower()
        if uid.startswith("gmx-"):
            account = "gmx"
    if account == "gmx":
        return os.environ.get("GMX_MCP_URL", _DEFAULT_URLS["gmx"])
    return os.environ.get("PROTONMAIL_MCP_URL", _DEFAULT_URLS["protonmail"])


def sort_email(uid: str, payload: dict) -> dict:
    payload = {**payload, "email_id": uid}
    body = {
        "uid": uid,
        "source_folder": "INBOX",
        "sender": payload.get("sender", ""),
        "subject": payload.get("subject", ""),
        "body": payload.get("body_redacted", ""),
        "classification": payload.get("classification", {}),
    }
    response = httpx.post(f"{_endpoint_for(payload)}/sort", json=body, timeout=10.0)
    response.raise_for_status()
    return response.json()
