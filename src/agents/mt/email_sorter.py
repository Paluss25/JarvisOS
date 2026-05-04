"""mailctl-backed email sorter for MT."""

import json
import subprocess


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


def sort_email(uid: str, payload: dict) -> dict:
    account = _account_for(uid, payload)
    imap_uid = _imap_uid(uid, account)
    proc = subprocess.run(
        ["mailctl", "sort", "--account", account, "--uid", imap_uid, "--json"],
        capture_output=True,
        check=False,
        text=True,
        timeout=20.0,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit_status={proc.returncode}"
        raise RuntimeError(f"mailctl sort failed for {account}:{imap_uid}: {detail}")
    return json.loads(proc.stdout)
