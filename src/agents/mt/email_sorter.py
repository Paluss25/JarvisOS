"""httpx client calling protonmail-mcp /sort endpoint."""

import os

import httpx

_URL = os.environ.get("PROTONMAIL_MCP_URL", "http://protonmail-mcp:3000")


def sort_email(uid: str, payload: dict) -> dict:
    body = {
        "uid": uid,
        "source_folder": "INBOX",
        "sender": payload.get("sender", ""),
        "subject": payload.get("subject", ""),
        "body": payload.get("body_redacted", ""),
        "classification": payload.get("classification", {}),
    }
    response = httpx.post(f"{_URL}/sort", json=body, timeout=10.0)
    response.raise_for_status()
    return response.json()
