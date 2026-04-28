"""CRUD helpers for the sender-whitelist.yaml file.

Thread-safe atomic writes: write to a temp file, then os.replace.
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

import yaml

_WHITELIST_PATH = Path(__file__).parent / "config" / "sender-whitelist.yaml"

_VALID_DOMAINS = frozenset(
    {"finance", "legal", "security", "hr", "ops", "marketing", "general"}
)


class WhitelistError(ValueError):
    pass


def _load() -> dict:
    try:
        data = yaml.safe_load(_WHITELIST_PATH.read_text()) or {}
    except FileNotFoundError:
        data = {}
    data.setdefault("email_overrides", {})
    data.setdefault("domain_overrides", {})
    return data


def _save(data: dict) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=_WHITELIST_PATH.parent, suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as fh:
            yaml.dump(data, fh, default_flow_style=False, allow_unicode=True)
        os.replace(tmp_path, _WHITELIST_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _classify_key(key: str) -> str:
    """Return 'domain' if key starts with '@', else 'email'."""
    return "domain" if key.startswith("@") else "email"


def list_entries() -> str:
    """Return a human-readable summary of all whitelist entries."""
    data = _load()
    lines = []

    emails: dict = data.get("email_overrides") or {}
    domains: dict = data.get("domain_overrides") or {}

    if not emails and not domains:
        return "Whitelist is empty."

    if emails:
        lines.append("*Email overrides:*")
        for addr, entry in emails.items():
            note = f" — {entry['note']}" if entry.get("note") else ""
            lines.append(
                f"  `{addr}` → {entry.get('domain','?')} "
                f"(confidence={entry.get('confidence', 1.0):.1f}){note}"
            )

    if domains:
        lines.append("*Domain overrides:*")
        for pattern, entry in domains.items():
            note = f" — {entry['note']}" if entry.get("note") else ""
            lines.append(
                f"  `{pattern}` → {entry.get('domain','?')} "
                f"(confidence={entry.get('confidence', 1.0):.1f}){note}"
            )

    return "\n".join(lines)


def add_entry(
    key: str,
    domain: str,
    confidence: float = 1.0,
    note: Optional[str] = None,
) -> str:
    """Add or replace a whitelist entry. key is an email address or @domain pattern."""
    key = key.strip().lower()
    if not key:
        raise WhitelistError("Key cannot be empty.")
    if domain not in _VALID_DOMAINS:
        raise WhitelistError(
            f"Unknown domain '{domain}'. Valid: {', '.join(sorted(_VALID_DOMAINS))}"
        )
    if not (0.0 <= confidence <= 1.0):
        raise WhitelistError("Confidence must be between 0.0 and 1.0.")

    entry: dict = {"domain": domain, "confidence": round(confidence, 2)}
    if note:
        entry["note"] = note

    data = _load()
    section = "domain_overrides" if _classify_key(key) == "domain" else "email_overrides"
    existed = key in data[section]
    data[section][key] = entry
    _save(data)

    verb = "Updated" if existed else "Added"
    return f"{verb} `{key}` → {domain} (confidence={confidence:.1f})"


def remove_entry(key: str) -> str:
    """Remove a whitelist entry by email address or @domain pattern."""
    key = key.strip().lower()
    if not key:
        raise WhitelistError("Key cannot be empty.")

    data = _load()
    section = "domain_overrides" if _classify_key(key) == "domain" else "email_overrides"

    if key not in data[section]:
        return f"No entry found for `{key}`."

    del data[section][key]
    _save(data)
    return f"Removed `{key}` from whitelist."
