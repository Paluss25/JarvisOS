import hashlib
import json
import os


def build_approval_preview(
    account: str,
    from_addr: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    body: str,
    attachments: list[dict],
    reply_uid: str | None,
) -> dict:
    preview = {
        "account": account,
        "from": from_addr,
        "to": to,
        "cc": cc,
        "bcc": bcc,
        "subject": subject,
        "reply_uid": reply_uid,
        "body_preview": body[:1000],
        "attachments": attachments,
    }
    canonical = json.dumps(preview, sort_keys=True, separators=(",", ":"))
    preview["approval_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return preview


def enforce_send_allowed(preview: dict, hitl_token: str | None, interactive: bool) -> None:
    agent_mode = os.environ.get("MAILCTL_AGENT_MODE", "").strip().lower() in {"1", "true", "yes"}
    if agent_mode or not interactive:
        if hitl_token != preview["approval_hash"]:
            raise PermissionError("HITL confirmation required for send/reply in agent or non-interactive mode.")
        return
    print(json.dumps(preview, indent=2))
    answer = input("Send this email? Type SEND to confirm: ").strip()
    if answer != "SEND":
        raise PermissionError("User declined send/reply confirmation.")
