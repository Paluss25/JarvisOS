"""mailctl-backed email sorter for MT."""

import json
import re
import subprocess


_ACCOUNT_ALIASES = {
    "protonmail": ("protonmail", "pm"),
    "gmx": ("gmx",),
}


def _account_for(uid: str, payload: dict) -> str:
    account = str(payload.get("account", "")).strip().lower()
    if account in {"protonmail", "gmx"}:
        return account
    uid_lower = uid.strip().lower()
    if uid_lower.startswith("gmx-"):
        return "gmx"
    return "protonmail"


def _imap_uid(uid: str, account: str) -> str:
    raw = str(uid or "").strip()
    lowered = raw.lower()
    for alias in _ACCOUNT_ALIASES.get(account, (account,)):
        prefix = f"{alias}-"
        if lowered.startswith(prefix):
            raw = raw[len(prefix):]
            break
    match = re.search(r"\d+", raw)
    return match.group(0) if match else raw


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
